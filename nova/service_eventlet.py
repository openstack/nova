# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Generic Node baseclass for all workers that run on hosts
"""

import inspect
import logging
import os
import sys

from eventlet import event
from eventlet import greenthread
from eventlet import greenpool

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import rpc
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_integer('report_interval', 10,
                     'seconds between nodes reporting state to datastore',
                     lower_bound=1)

flags.DEFINE_integer('periodic_interval', 60,
                     'seconds between running periodic tasks',
                     lower_bound=1)

flags.DEFINE_string('pidfile', None,
                    'pidfile to use for this service')


flags.DEFINE_flag(flags.HelpFlag())
flags.DEFINE_flag(flags.HelpshortFlag())
flags.DEFINE_flag(flags.HelpXMLFlag())


class Service(object):
    """Base class for workers that run on hosts."""

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_interval=None, *args, **kwargs):
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        self.report_interval = report_interval
        self.periodic_interval = periodic_interval
        super(Service, self).__init__(*args, **kwargs)
        self.saved_args, self.saved_kwargs = args, kwargs

    def start(self):
        manager_class = utils.import_class(self.manager_class_name)
        self.manager = manager_class(host=self.host, *self.saved_args,
                                                     **self.saved_kwargs)
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

        conn1 = rpc.Connection.instance(new=True)
        conn2 = rpc.Connection.instance(new=True)
        if self.report_interval:
            consumer_all = rpc.AdapterConsumer(
                    connection=conn1,
                    topic=self.topic,
                    proxy=self)
            consumer_node = rpc.AdapterConsumer(
                    connection=conn2,
                    topic='%s.%s' % (self.topic, self.host),
                    proxy=self)

            consumer_all.attach_to_eventlet()
            consumer_node.attach_to_eventlet()
            
            pulse = utils.LoopingCall(self.report_state)
            pulse.start(interval=self.report_interval, now=False)

        if self.periodic_interval:
            pulse = utils.LoopingCall(self.periodic_tasks)
            pulse.start(interval=self.periodic_interval, now=False)

    def _create_service_ref(self, context):
        service_ref = db.service_create(context,
                                        {'host': self.host,
                                         'binary': self.binary,
                                         'topic': self.topic,
                                         'report_count': 0})
        self.service_id = service_ref['id']

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls, 
               host=None,
               binary=None,
               topic=None,
               manager=None,
               report_interval=None,
               periodic_interval=None):
        """Instantiates class and passes back application object.

        Args:
            host, defaults to FLAGS.host
            binary, defaults to basename of executable
            topic, defaults to bin_name - "nova-" part
            manager, defaults to FLAGS.<topic>_manager
            report_interval, defaults to FLAGS.report_interval
            periodic_interval, defaults to FLAGS.periodic_interval
        """
        if not host:
            host = FLAGS.host
        if not binary:
            binary = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = binary.rpartition("nova-")[2]
        if not manager:
            manager = FLAGS.get('%s_manager' % topic, None)
        if not report_interval:
            report_interval = FLAGS.report_interval
        if not periodic_interval:
            periodic_interval = FLAGS.periodic_interval
        logging.warn("Starting %s node", topic)
        service_obj = cls(host, binary, topic, manager,
                          report_interval, periodic_interval)

        return service_obj

    def kill(self):
        """Destroy the service object in the datastore"""
        try:
            db.service_destroy(context.get_admin_context(), self.service_id)
        except exception.NotFound:
            logging.warn("Service killed that has no database entry")

    def periodic_tasks(self):
        """Tasks to be run at a periodic interval"""
        self.manager.periodic_tasks(context.get_admin_context())

    def report_state(self):
        """Update the state of this service in the datastore."""
        ctxt = context.get_admin_context()
        try:
            try:
                service_ref = db.service_get(ctxt, self.service_id)
            except exception.NotFound:
                logging.debug("The service database object disappeared, "
                              "Recreating it.")
                self._create_service_ref(ctxt)
                service_ref = db.service_get(ctxt, self.service_id)

            db.service_update(ctxt,
                             self.service_id,
                             {'report_count': service_ref['report_count'] + 1})
                
            # TODO(termie): make this pattern be more elegant.
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        # TODO(vish): this should probably only catch connection errors
        except Exception:  # pylint: disable-msg=W0702
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")


def stop(pidfile):
    """
    Stop the daemon
    """
    # Get the pid from the pidfile
    try:
        pf = file(pidfile, 'r')
        pid = int(pf.read().strip())
        pf.close()
    except IOError:
        pid = None

    if not pid:
        message = "pidfile %s does not exist. Daemon not running?\n"
        sys.stderr.write(message % pidfile)
        # Not an error in a restart
        return

    # Try killing the daemon process
    try:
        while 1:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.1)
    except OSError, err:
        err = str(err)
        if err.find("No such process") > 0:
            if os.path.exists(pidfile):
                os.remove(pidfile)
        else:
            print str(err)
            sys.exit(1)


def serve(*services):
    argv = FLAGS(sys.argv)
    
    if not services:
        services = [Service.create()]

    name = '_'.join(x.binary for x in services)
    logging.debug("Serving %s" % name)

    logging.getLogger('amqplib').setLevel(logging.DEBUG)

    if not FLAGS.pidfile:
        FLAGS.pidfile = '%s.pid' % name
    # NOTE(vish): if we're running nodaemon, redirect the log to stdout
    #if FLAGS.nodaemon and not FLAGS.logfile:
    #    FLAGS.logfile = "-"
    #if not FLAGS.logfile:
    #    FLAGS.logfile = '%s.log' % name
    #if not FLAGS.prefix:
    #    FLAGS.prefix = name
    #elif FLAGS.prefix.endswith('twisted'):
    #    FLAGS.prefix = FLAGS.prefix.replace('twisted', name)

    action = 'start'
    if len(argv) > 1:
        action = argv.pop()

    if action == 'stop':
        stop(FLAGS.pidfile)
        sys.exit()
    elif action == 'restart':
        stop(FLAGS.pidfile)
    elif action == 'start':
        pass
    else:
        print 'usage: %s [options] [start|stop|restart]' % argv[0]
        sys.exit(1)

    #formatter = logging.Formatter(
    #    '(%(name)s): %(levelname)s %(message)s')
    #handler = logging.StreamHandler()
    #handler.setFormatter(formatter)
    #logging.getLogger().addHandler(handler)

    if FLAGS.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    logging.debug("Full set of FLAGS:")
    for flag in FLAGS:
        logging.debug("%s : %s" % (flag, FLAGS.get(flag, None)))

    for x in services:
        x.start()
    
    #while True:
    #    greenthread.sleep(5)


def wait():
    while True:
        greenthread.sleep(5)
