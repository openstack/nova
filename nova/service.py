# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Generic Node baseclass for all workers that run on hosts."""

import greenlet
import inspect
import os

from eventlet import greenthread

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova import utils
from nova import version
from nova import wsgi


FLAGS = flags.FLAGS
flags.DEFINE_integer('report_interval', 10,
                     'seconds between nodes reporting state to datastore',
                     lower_bound=1)
flags.DEFINE_integer('periodic_interval', 60,
                     'seconds between running periodic tasks',
                     lower_bound=1)
flags.DEFINE_string('ec2_listen', "0.0.0.0",
                    'IP address for EC2 API to listen')
flags.DEFINE_integer('ec2_listen_port', 8773, 'port for ec2 api to listen')
flags.DEFINE_string('osapi_listen', "0.0.0.0",
                    'IP address for OpenStack API to listen')
flags.DEFINE_integer('osapi_listen_port', 8774, 'port for os api to listen')
flags.DEFINE_string('api_paste_config', "api-paste.ini",
                    'File name for the paste.deploy config for nova-api')


class Service(object):
    """Base class for workers that run on hosts."""

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_interval=None, *args, **kwargs):
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        manager_class = utils.import_class(self.manager_class_name)
        self.manager = manager_class(host=self.host, *args, **kwargs)
        self.report_interval = report_interval
        self.periodic_interval = periodic_interval
        super(Service, self).__init__(*args, **kwargs)
        self.saved_args, self.saved_kwargs = args, kwargs
        self.timers = []

    def start(self):
        vcs_string = version.version_string_with_vcs()
        logging.audit(_('Starting %(topic)s node (version %(vcs_string)s)'),
                      {'topic': self.topic, 'vcs_string': vcs_string})
        self.manager.init_host()
        self.model_disconnected = False
        ctxt = context.get_admin_context()
        try:
            service_ref = db.service_get_by_args(ctxt,
                                                 self.host,
                                                 self.binary)
            self.service_id = service_ref['id']
        except exception.NotFound:
            self._create_service_ref(ctxt)

        if 'nova-compute' == self.binary:
            self.manager.update_available_resource(ctxt)

        self.conn = rpc.Connection.instance(new=True)
        logging.debug("Creating Consumer connection for Service %s" %
                      self.topic)

        # Share this same connection for these Consumers
        consumer_all = rpc.TopicAdapterConsumer(
                connection=self.conn,
                topic=self.topic,
                proxy=self)
        consumer_node = rpc.TopicAdapterConsumer(
                connection=self.conn,
                topic='%s.%s' % (self.topic, self.host),
                proxy=self)
        fanout = rpc.FanoutAdapterConsumer(
                connection=self.conn,
                topic=self.topic,
                proxy=self)

        cset = rpc.ConsumerSet(self.conn, [consumer_all,
                                           consumer_node,
                                           fanout])

        # Wait forever, processing these consumers
        def _wait():
            try:
                cset.wait()
            finally:
                cset.close()

        self.csetthread = greenthread.spawn(_wait)

        if self.report_interval:
            pulse = utils.LoopingCall(self.report_state)
            pulse.start(interval=self.report_interval, now=False)
            self.timers.append(pulse)

        if self.periodic_interval:
            periodic = utils.LoopingCall(self.periodic_tasks)
            periodic.start(interval=self.periodic_interval, now=False)
            self.timers.append(periodic)

    def _create_service_ref(self, context):
        zone = FLAGS.node_availability_zone
        service_ref = db.service_create(context,
                                        {'host': self.host,
                                         'binary': self.binary,
                                         'topic': self.topic,
                                         'report_count': 0,
                                         'availability_zone': zone})
        self.service_id = service_ref['id']

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls, host=None, binary=None, topic=None, manager=None,
               report_interval=None, periodic_interval=None):
        """Instantiates class and passes back application object.

        :param host: defaults to FLAGS.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'nova-' part
        :param manager: defaults to FLAGS.<topic>_manager
        :param report_interval: defaults to FLAGS.report_interval
        :param periodic_interval: defaults to FLAGS.periodic_interval

        """
        if not host:
            host = FLAGS.host
        if not binary:
            binary = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = binary.rpartition('nova-')[2]
        if not manager:
            manager = FLAGS.get('%s_manager' % topic, None)
        if not report_interval:
            report_interval = FLAGS.report_interval
        if not periodic_interval:
            periodic_interval = FLAGS.periodic_interval
        service_obj = cls(host, binary, topic, manager,
                          report_interval, periodic_interval)

        return service_obj

    def kill(self):
        """Destroy the service object in the datastore."""
        self.csetthread.kill()
        try:
            self.csetthread.wait()
        except greenlet.GreenletExit:
            pass
        self.stop()
        try:
            db.service_destroy(context.get_admin_context(), self.service_id)
        except exception.NotFound:
            logging.warn(_('Service killed that has no database entry'))

    def stop(self):
        for x in self.timers:
            try:
                x.stop()
            except Exception:
                pass
        self.timers = []

    def wait(self):
        for x in self.timers:
            try:
                x.wait()
            except Exception:
                pass

    def periodic_tasks(self):
        """Tasks to be run at a periodic interval."""
        self.manager.periodic_tasks(context.get_admin_context())

    def report_state(self):
        """Update the state of this service in the datastore."""
        ctxt = context.get_admin_context()
        try:
            try:
                service_ref = db.service_get(ctxt, self.service_id)
            except exception.NotFound:
                logging.debug(_('The service database object disappeared, '
                                'Recreating it.'))
                self._create_service_ref(ctxt)
                service_ref = db.service_get(ctxt, self.service_id)

            db.service_update(ctxt,
                             self.service_id,
                             {'report_count': service_ref['report_count'] + 1})

            # TODO(termie): make this pattern be more elegant.
            if getattr(self, 'model_disconnected', False):
                self.model_disconnected = False
                logging.error(_('Recovered model server connection!'))

        # TODO(vish): this should probably only catch connection errors
        except Exception:  # pylint: disable=W0702
            if not getattr(self, 'model_disconnected', False):
                self.model_disconnected = True
                logging.exception(_('model server went away'))


class WsgiService(object):
    """Base class for WSGI based services.

    For each api you define, you must also define these flags:
    :<api>_listen: The address on which to listen
    :<api>_listen_port: The port on which to listen

    """

    def __init__(self, conf, apis):
        self.conf = conf
        self.apis = apis
        self.wsgi_app = None

    def start(self):
        self.wsgi_app = _run_wsgi(self.conf, self.apis)

    def wait(self):
        self.wsgi_app.wait()

    def get_socket_info(self, api_name):
        """Returns the (host, port) that an API was started on."""
        return self.wsgi_app.socket_info[api_name]


class ApiService(WsgiService):
    """Class for our nova-api service."""

    @classmethod
    def create(cls, conf=None):
        if not conf:
            conf = wsgi.paste_config_file(FLAGS.api_paste_config)
            if not conf:
                message = (_('No paste configuration found for: %s'),
                           FLAGS.api_paste_config)
                raise exception.Error(message)
        api_endpoints = ['ec2', 'osapi']
        service = cls(conf, api_endpoints)
        return service


def serve(*services):
    try:
        if not services:
            services = [Service.create()]
    except Exception:
        logging.exception('in Service.create()')
        raise
    finally:
        # After we've loaded up all our dynamic bits, check
        # whether we should print help
        flags.DEFINE_flag(flags.HelpFlag())
        flags.DEFINE_flag(flags.HelpshortFlag())
        flags.DEFINE_flag(flags.HelpXMLFlag())
        FLAGS.ParseNewFlags()

    name = '_'.join(x.binary for x in services)
    logging.debug(_('Serving %s'), name)
    logging.debug(_('Full set of FLAGS:'))
    for flag in FLAGS:
        flag_get = FLAGS.get(flag, None)
        logging.debug('%(flag)s : %(flag_get)s' % locals())

    for x in services:
        x.start()


def wait():
    while True:
        greenthread.sleep(5)


def serve_wsgi(cls, conf=None):
    try:
        service = cls.create(conf)
    except Exception:
        logging.exception('in WsgiService.create()')
        raise
    finally:
        # After we've loaded up all our dynamic bits, check
        # whether we should print help
        flags.DEFINE_flag(flags.HelpFlag())
        flags.DEFINE_flag(flags.HelpshortFlag())
        flags.DEFINE_flag(flags.HelpXMLFlag())
        FLAGS.ParseNewFlags()

    service.start()

    return service


def _run_wsgi(paste_config_file, apis):
    logging.debug(_('Using paste.deploy config at: %s'), paste_config_file)
    apps = []
    for api in apis:
        config = wsgi.load_paste_configuration(paste_config_file, api)
        if config is None:
            logging.debug(_('No paste configuration for app: %s'), api)
            continue
        logging.debug(_('App Config: %(api)s\n%(config)r') % locals())
        logging.info(_('Running %s API'), api)
        app = wsgi.load_paste_app(paste_config_file, api)
        apps.append((app,
                     getattr(FLAGS, '%s_listen_port' % api),
                     getattr(FLAGS, '%s_listen' % api),
                     api))
    if len(apps) == 0:
        logging.error(_('No known API applications configured in %s.'),
                      paste_config_file)
        return

    server = wsgi.Server()
    for app in apps:
        server.start(*app)
    return server
