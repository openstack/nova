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

"""Generic Node base class for all workers that run on hosts."""

import errno
import inspect
import os
import random
import signal
import sys
import time

import eventlet
import greenlet

from nova import context
from nova import db
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import eventlet_backdoor
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova import servicegroup
from nova import utils
from nova import version
from nova import wsgi

LOG = logging.getLogger(__name__)

service_opts = [
    cfg.IntOpt('report_interval',
               default=10,
               help='seconds between nodes reporting state to datastore'),
    cfg.IntOpt('periodic_interval',
               default=60,
               help='seconds between running periodic tasks'),
    cfg.IntOpt('periodic_fuzzy_delay',
               default=60,
               help='range of seconds to randomly delay when starting the'
                    ' periodic task scheduler to reduce stampeding.'
                    ' (Disable by setting to 0)'),
    cfg.StrOpt('ec2_listen',
               default="0.0.0.0",
               help='IP address for EC2 API to listen'),
    cfg.IntOpt('ec2_listen_port',
               default=8773,
               help='port for ec2 api to listen'),
    cfg.IntOpt('ec2_workers',
               default=None,
               help='Number of workers for EC2 API service'),
    cfg.StrOpt('osapi_compute_listen',
               default="0.0.0.0",
               help='IP address for OpenStack API to listen'),
    cfg.IntOpt('osapi_compute_listen_port',
               default=8774,
               help='list port for osapi compute'),
    cfg.IntOpt('osapi_compute_workers',
               default=None,
               help='Number of workers for OpenStack API service'),
    cfg.StrOpt('metadata_manager',
               default='nova.api.manager.MetadataManager',
               help='OpenStack metadata service manager'),
    cfg.StrOpt('metadata_listen',
               default="0.0.0.0",
               help='IP address for metadata api to listen'),
    cfg.IntOpt('metadata_listen_port',
               default=8775,
               help='port for metadata api to listen'),
    cfg.IntOpt('metadata_workers',
               default=None,
               help='Number of workers for metadata service'),
    ]

CONF = cfg.CONF
CONF.register_opts(service_opts)
CONF.import_opt('host', 'nova.config')
CONF.import_opt('node_availability_zone', 'nova.config')


class SignalExit(SystemExit):
    def __init__(self, signo, exccode=1):
        super(SignalExit, self).__init__(exccode)
        self.signo = signo


class Launcher(object):
    """Launch one or more services and wait for them to complete."""

    def __init__(self):
        """Initialize the service launcher.

        :returns: None

        """
        self._services = []
        self.backdoor_port = eventlet_backdoor.initialize_if_enabled()

    @staticmethod
    def run_server(server):
        """Start and wait for a server to finish.

        :param service: Server to run and wait for.
        :returns: None

        """
        server.start()
        server.wait()

    def launch_server(self, server):
        """Load and start the given server.

        :param server: The server you would like to start.
        :returns: None

        """
        if self.backdoor_port is not None:
            server.backdoor_port = self.backdoor_port
        gt = eventlet.spawn(self.run_server, server)
        self._services.append(gt)

    def stop(self):
        """Stop all services which are currently running.

        :returns: None

        """
        for service in self._services:
            service.kill()

    def wait(self):
        """Waits until all services have been stopped, and then returns.

        :returns: None

        """
        for service in self._services:
            try:
                service.wait()
            except greenlet.GreenletExit:
                pass


class ServiceLauncher(Launcher):
    def _handle_signal(self, signo, frame):
        # Allow the process to be killed again and die from natural causes
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        raise SignalExit(signo)

    def wait(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        LOG.debug(_('Full set of CONF:'))
        for flag in CONF:
            flag_get = CONF.get(flag, None)
            # hide flag contents from log if contains a password
            # should use secret flag when switch over to openstack-common
            if ("_password" in flag or "_key" in flag or
                    (flag == "sql_connection" and "mysql:" in flag_get)):
                LOG.debug(_('%(flag)s : FLAG SET ') % locals())
            else:
                LOG.debug('%(flag)s : %(flag_get)s' % locals())

        status = None
        try:
            super(ServiceLauncher, self).wait()
        except SignalExit as exc:
            signame = {signal.SIGTERM: 'SIGTERM',
                       signal.SIGINT: 'SIGINT'}[exc.signo]
            LOG.info(_('Caught %s, exiting'), signame)
            status = exc.code
        except SystemExit as exc:
            status = exc.code
        finally:
            self.stop()
        rpc.cleanup()

        if status is not None:
            sys.exit(status)


class ServerWrapper(object):
    def __init__(self, server, workers):
        self.server = server
        self.workers = workers
        self.children = set()
        self.forktimes = []


class ProcessLauncher(object):
    def __init__(self):
        self.children = {}
        self.sigcaught = None
        self.running = True
        rfd, self.writepipe = os.pipe()
        self.readpipe = eventlet.greenio.GreenPipe(rfd, 'r')

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signo, frame):
        self.sigcaught = signo
        self.running = False

        # Allow the process to be killed again and die from natural causes
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    def _pipe_watcher(self):
        # This will block until the write end is closed when the parent
        # dies unexpectedly
        self.readpipe.read()

        LOG.info(_('Parent process has died unexpectedly, exiting'))

        sys.exit(1)

    def _child_process(self, server):
        # Setup child signal handlers differently
        def _sigterm(*args):
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            raise SignalExit(signal.SIGTERM)

        signal.signal(signal.SIGTERM, _sigterm)
        # Block SIGINT and let the parent send us a SIGTERM
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        # Reopen the eventlet hub to make sure we don't share an epoll
        # fd with parent and/or siblings, which would be bad
        eventlet.hubs.use_hub()

        # Close write to ensure only parent has it open
        os.close(self.writepipe)
        # Create greenthread to watch for parent to close pipe
        eventlet.spawn(self._pipe_watcher)

        # Reseed random number generator
        random.seed()

        launcher = Launcher()
        launcher.run_server(server)

    def _start_child(self, wrap):
        if len(wrap.forktimes) > wrap.workers:
            # Limit ourselves to one process a second (over the period of
            # number of workers * 1 second). This will allow workers to
            # start up quickly but ensure we don't fork off children that
            # die instantly too quickly.
            if time.time() - wrap.forktimes[0] < wrap.workers:
                LOG.info(_('Forking too fast, sleeping'))
                time.sleep(1)

            wrap.forktimes.pop(0)

        wrap.forktimes.append(time.time())

        pid = os.fork()
        if pid == 0:
            # NOTE(johannes): All exceptions are caught to ensure this
            # doesn't fallback into the loop spawning children. It would
            # be bad for a child to spawn more children.
            status = 0
            try:
                self._child_process(wrap.server)
            except SignalExit as exc:
                signame = {signal.SIGTERM: 'SIGTERM',
                           signal.SIGINT: 'SIGINT'}[exc.signo]
                LOG.info(_('Caught %s, exiting'), signame)
                status = exc.code
            except SystemExit as exc:
                status = exc.code
            except BaseException:
                LOG.exception(_('Unhandled exception'))
                status = 2
            finally:
                wrap.server.stop()

            os._exit(status)

        LOG.info(_('Started child %d'), pid)

        wrap.children.add(pid)
        self.children[pid] = wrap

        return pid

    def launch_server(self, server, workers=1):
        wrap = ServerWrapper(server, workers)

        LOG.info(_('Starting %d workers'), wrap.workers)
        while self.running and len(wrap.children) < wrap.workers:
            self._start_child(wrap)

    def _wait_child(self):
        try:
            pid, status = os.wait()
        except OSError as exc:
            if exc.errno not in (errno.EINTR, errno.ECHILD):
                raise
            return None

        if os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            LOG.info(_('Child %(pid)d killed by signal %(sig)d'), locals())
        else:
            code = os.WEXITSTATUS(status)
            LOG.info(_('Child %(pid)d exited with status %(code)d'), locals())

        if pid not in self.children:
            LOG.warning(_('pid %d not in child list'), pid)
            return None

        wrap = self.children.pop(pid)
        wrap.children.remove(pid)
        return wrap

    def wait(self):
        """Loop waiting on children to die and respawning as necessary"""
        while self.running:
            wrap = self._wait_child()
            if not wrap:
                continue

            while self.running and len(wrap.children) < wrap.workers:
                self._start_child(wrap)

        if self.sigcaught:
            signame = {signal.SIGTERM: 'SIGTERM',
                       signal.SIGINT: 'SIGINT'}[self.sigcaught]
            LOG.info(_('Caught %s, stopping children'), signame)

        for pid in self.children:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    raise

        # Wait for children to die
        if self.children:
            LOG.info(_('Waiting on %d children to exit'), len(self.children))
            while self.children:
                self._wait_child()


class Service(object):
    """Service object for binaries running on hosts.

    A service takes a manager and enables rpc by listening to queues based
    on topic. It also periodically runs tasks on the manager and reports
    it state to the database services table."""

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_interval=None, periodic_fuzzy_delay=None,
                 *args, **kwargs):
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        manager_class = importutils.import_class(self.manager_class_name)
        self.manager = manager_class(host=self.host, *args, **kwargs)
        self.report_interval = report_interval
        self.periodic_interval = periodic_interval
        self.periodic_fuzzy_delay = periodic_fuzzy_delay
        self.saved_args, self.saved_kwargs = args, kwargs
        self.timers = []
        self.backdoor_port = None
        self.servicegroup_api = servicegroup.API()

    def start(self):
        verstr = version.version_string_with_package()
        LOG.audit(_('Starting %(topic)s node (version %(version)s)'),
                  {'topic': self.topic, 'version': verstr})
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

        if self.backdoor_port is not None:
            self.manager.backdoor_port = self.backdoor_port

        self.conn = rpc.create_connection(new=True)
        LOG.debug(_("Creating Consumer connection for Service %s") %
                  self.topic)

        self.manager.pre_start_hook(rpc_connection=self.conn)

        rpc_dispatcher = self.manager.create_rpc_dispatcher()

        # Share this same connection for these Consumers
        self.conn.create_consumer(self.topic, rpc_dispatcher, fanout=False)

        node_topic = '%s.%s' % (self.topic, self.host)
        self.conn.create_consumer(node_topic, rpc_dispatcher, fanout=False)

        self.conn.create_consumer(self.topic, rpc_dispatcher, fanout=True)

        # Consume from all consumers in a thread
        self.conn.consume_in_thread()

        self.manager.post_start_hook()

        LOG.debug(_("Join ServiceGroup membership for this service %s")
                  % self.topic)
        # Add service to the ServiceGroup membership group.
        pulse = self.servicegroup_api.join(self.host, self.topic, self)
        if pulse:
            self.timers.append(pulse)

        if self.periodic_interval:
            if self.periodic_fuzzy_delay:
                initial_delay = random.randint(0, self.periodic_fuzzy_delay)
            else:
                initial_delay = None

            periodic = utils.LoopingCall(self.periodic_tasks)
            periodic.start(interval=self.periodic_interval,
                           initial_delay=initial_delay)
            self.timers.append(periodic)

    def _create_service_ref(self, context):
        zone = CONF.node_availability_zone
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
               report_interval=None, periodic_interval=None,
               periodic_fuzzy_delay=None):
        """Instantiates class and passes back application object.

        :param host: defaults to CONF.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'nova-' part
        :param manager: defaults to CONF.<topic>_manager
        :param report_interval: defaults to CONF.report_interval
        :param periodic_interval: defaults to CONF.periodic_interval
        :param periodic_fuzzy_delay: defaults to CONF.periodic_fuzzy_delay

        """
        if not host:
            host = CONF.host
        if not binary:
            binary = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = binary.rpartition('nova-')[2]
        if not manager:
            manager_cls = ('%s_manager' %
                           binary.rpartition('nova-')[2])
            CONF.import_opt(manager_cls, 'nova.config')
            manager = CONF.get(manager_cls, None)
        if report_interval is None:
            report_interval = CONF.report_interval
        if periodic_interval is None:
            periodic_interval = CONF.periodic_interval
        if periodic_fuzzy_delay is None:
            periodic_fuzzy_delay = CONF.periodic_fuzzy_delay
        service_obj = cls(host, binary, topic, manager,
                          report_interval=report_interval,
                          periodic_interval=periodic_interval,
                          periodic_fuzzy_delay=periodic_fuzzy_delay)

        return service_obj

    def kill(self):
        """Destroy the service object in the datastore."""
        self.stop()
        try:
            db.service_destroy(context.get_admin_context(), self.service_id)
        except exception.NotFound:
            LOG.warn(_('Service killed that has no database entry'))

    def stop(self):
        # Try to shut the connection down, but if we get any sort of
        # errors, go ahead and ignore them.. as we're shutting down anyway
        try:
            self.conn.close()
        except Exception:
            pass
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

    def periodic_tasks(self, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        ctxt = context.get_admin_context()
        self.manager.periodic_tasks(ctxt, raise_on_error=raise_on_error)


class WSGIService(object):
    """Provides ability to launch API from a 'paste' configuration."""

    def __init__(self, name, loader=None):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param loader: Loads the WSGI application using the given name.
        :returns: None

        """
        self.name = name
        self.manager = self._get_manager()
        self.loader = loader or wsgi.Loader()
        self.app = self.loader.load_app(name)
        self.host = getattr(CONF, '%s_listen' % name, "0.0.0.0")
        self.port = getattr(CONF, '%s_listen_port' % name, 0)
        self.workers = getattr(CONF, '%s_workers' % name, None)
        self.server = wsgi.Server(name,
                                  self.app,
                                  host=self.host,
                                  port=self.port)
        # Pull back actual port used
        self.port = self.server.port
        self.backdoor_port = None

    def _get_manager(self):
        """Initialize a Manager object appropriate for this service.

        Use the service name to look up a Manager subclass from the
        configuration and initialize an instance. If no class name
        is configured, just return None.

        :returns: a Manager instance, or None.

        """
        fl = '%s_manager' % self.name
        if not fl in CONF:
            return None

        manager_class_name = CONF.get(fl, None)
        if not manager_class_name:
            return None

        manager_class = importutils.import_class(manager_class_name)
        return manager_class()

    def start(self):
        """Start serving this service using loaded configuration.

        Also, retrieve updated port number in case '0' was passed in, which
        indicates a random port should be used.

        :returns: None

        """
        if self.manager:
            self.manager.init_host()
            self.manager.pre_start_hook()
        if self.backdoor_port is not None:
            self.manager.backdoor_port = self.backdoor_port
        self.server.start()
        if self.manager:
            self.manager.post_start_hook()

    def stop(self):
        """Stop serving this API.

        :returns: None

        """
        self.server.stop()

    def wait(self):
        """Wait for the service to stop serving this API.

        :returns: None

        """
        self.server.wait()


# NOTE(vish): the global launcher is to maintain the existing
#             functionality of calling service.serve +
#             service.wait
_launcher = None


def serve(server, workers=None):
    global _launcher
    if _launcher:
        raise RuntimeError(_('serve() can only be called once'))

    if workers:
        _launcher = ProcessLauncher()
        _launcher.launch_server(server, workers=workers)
    else:
        _launcher = ServiceLauncher()
        _launcher.launch_server(server)


def wait():
    _launcher.wait()
