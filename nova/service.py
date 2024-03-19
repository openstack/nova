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

import os
import os.path
import random
import socket
import ssl
import sys

import eventlet
import eventlet.wsgi
import greenlet
from oslo_concurrency import processutils
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import service
from oslo_utils import excutils
from oslo_utils import importutils

from nova.api import wsgi as api_wsgi
from nova import baserpc
from nova import conductor
import nova.conf
from nova import context
from nova import debugger
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as objects_base
from nova.objects import service as service_obj
from nova import rpc
from nova import servicegroup
from nova import utils
from nova import version

osprofiler = importutils.try_import("osprofiler")
osprofiler_initializer = importutils.try_import("osprofiler.initializer")

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

SERVICE_MANAGERS = {
    'nova-compute': 'nova.compute.manager.ComputeManager',
    'nova-conductor': 'nova.conductor.manager.ConductorManager',
    'nova-scheduler': 'nova.scheduler.manager.SchedulerManager',
}


def _create_service_ref(this_service, context):
    service = objects.Service(context)
    service.host = this_service.host
    service.binary = this_service.binary
    service.topic = this_service.topic
    service.report_count = 0
    service.create()
    return service


def _update_service_ref(service):
    if service.version != service_obj.SERVICE_VERSION:
        LOG.info('Updating service version for %(binary)s on '
                 '%(host)s from %(old)i to %(new)i',
                 {'binary': service.binary,
                  'host': service.host,
                  'old': service.version,
                  'new': service_obj.SERVICE_VERSION})
        service.version = service_obj.SERVICE_VERSION
        service.save()


def setup_profiler(binary, host):
    if osprofiler and CONF.profiler.enabled:
        osprofiler.initializer.init_from_conf(
            conf=CONF,
            context=context.get_admin_context().to_dict(),
            project="nova",
            service=binary,
            host=host)
        LOG.info("OSProfiler is enabled.")


class Service(service.Service):
    """Service object for binaries running on hosts.

    A service takes a manager and enables rpc by listening to queues based
    on topic. It also periodically runs tasks on the manager and reports
    its state to the database services table.
    """

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_enable=None, periodic_fuzzy_delay=None,
                 periodic_interval_max=None, *args, **kwargs):
        super(Service, self).__init__()
        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        self.servicegroup_api = servicegroup.API()
        manager_class = importutils.import_class(self.manager_class_name)
        if objects_base.NovaObject.indirection_api:
            conductor_api = conductor.API()
            conductor_api.wait_until_ready(context.get_admin_context())
        self.manager = manager_class(host=self.host, *args, **kwargs)
        self.rpcserver = None
        self.report_interval = report_interval
        self.periodic_enable = periodic_enable
        self.periodic_fuzzy_delay = periodic_fuzzy_delay
        self.periodic_interval_max = periodic_interval_max
        self.saved_args, self.saved_kwargs = args, kwargs
        self.backdoor_port = None
        setup_profiler(binary, self.host)

    def __repr__(self):
        return "<%(cls_name)s: host=%(host)s, binary=%(binary)s, " \
               "manager_class_name=%(manager)s>" % {
                 'cls_name': self.__class__.__name__,
                 'host': self.host,
                 'binary': self.binary,
                 'manager': self.manager_class_name
                }

    def start(self):
        """Start the service.

        This includes starting an RPC service, initializing
        periodic tasks, etc.
        """
        # NOTE(melwitt): Clear the cell cache holding database transaction
        # context manager objects. We do this to ensure we create new internal
        # oslo.db locks to avoid a situation where a child process receives an
        # already locked oslo.db lock when it is forked. When a child process
        # inherits a locked oslo.db lock, database accesses through that
        # transaction context manager will never be able to acquire the lock
        # and requests will fail with CellTimeout errors.
        # See https://bugs.python.org/issue6721 for more information.
        # With python 3.7, it would be possible for oslo.db to make use of the
        # os.register_at_fork() method to reinitialize its lock. Until we
        # require python 3.7 as a minimum version, we must handle the situation
        # outside of oslo.db.
        context.CELL_CACHE = {}

        verstr = version.version_string_with_package()
        LOG.info('Starting %(topic)s node (version %(version)s)',
                  {'topic': self.topic, 'version': verstr})
        self.basic_config_check()
        ctxt = context.get_admin_context()
        self.service_ref = objects.Service.get_by_host_and_binary(
            ctxt, self.host, self.binary)
        self.manager.init_host(self.service_ref)
        self.model_disconnected = False
        if self.service_ref:
            _update_service_ref(self.service_ref)

        else:
            try:
                self.service_ref = _create_service_ref(self, ctxt)
            except (exception.ServiceTopicExists,
                    exception.ServiceBinaryExists):
                # NOTE(danms): If we race to create a record with a sibling
                # worker, don't fail here.
                self.service_ref = objects.Service.get_by_host_and_binary(
                    ctxt, self.host, self.binary)

        self.manager.pre_start_hook(self.service_ref)

        if self.backdoor_port is not None:
            self.manager.backdoor_port = self.backdoor_port

        LOG.debug("Creating RPC server for service %s", self.topic)

        target = messaging.Target(topic=self.topic, server=self.host)

        endpoints = [
            self.manager,
            baserpc.BaseRPCAPI(self.manager.service_name, self.backdoor_port)
        ]
        endpoints.extend(self.manager.additional_endpoints)

        serializer = objects_base.NovaObjectSerializer()

        self.rpcserver = rpc.get_server(target, endpoints, serializer)
        self.rpcserver.start()

        self.manager.post_start_hook()

        LOG.debug("Join ServiceGroup membership for this service %s",
                  self.topic)
        # Add service to the ServiceGroup membership group.
        self.servicegroup_api.join(self.host, self.topic, self)

        if self.periodic_enable:
            if self.periodic_fuzzy_delay:
                initial_delay = random.randint(0, self.periodic_fuzzy_delay)
            else:
                initial_delay = None

            self.tg.add_dynamic_timer(self.periodic_tasks,
                                     initial_delay=initial_delay,
                                     periodic_interval_max=
                                        self.periodic_interval_max)

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls, host=None, binary=None, topic=None, manager=None,
               report_interval=None, periodic_enable=None,
               periodic_fuzzy_delay=None, periodic_interval_max=None):
        """Instantiates class and passes back application object.

        :param host: defaults to CONF.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'nova-' part
        :param manager: defaults to CONF.<topic>_manager
        :param report_interval: defaults to CONF.report_interval
        :param periodic_enable: defaults to CONF.periodic_enable
        :param periodic_fuzzy_delay: defaults to CONF.periodic_fuzzy_delay
        :param periodic_interval_max: if set, the max time to wait between runs

        """
        if not host:
            host = CONF.host
        if not binary:
            binary = os.path.basename(sys.argv[0])
        if not topic:
            topic = binary.rpartition('nova-')[2]
        if not manager:
            manager = SERVICE_MANAGERS.get(binary)
        if report_interval is None:
            report_interval = CONF.report_interval
        if periodic_enable is None:
            periodic_enable = CONF.periodic_enable
        if periodic_fuzzy_delay is None:
            periodic_fuzzy_delay = CONF.periodic_fuzzy_delay

        debugger.init()

        service_obj = cls(host, binary, topic, manager,
                          report_interval=report_interval,
                          periodic_enable=periodic_enable,
                          periodic_fuzzy_delay=periodic_fuzzy_delay,
                          periodic_interval_max=periodic_interval_max)

        # NOTE(gibi): This have to be after the service object creation as
        # that is the point where we can safely use the RPC to the conductor.
        # E.g. the Service.__init__ actually waits for the conductor to start
        # up before it allows the service to be created. The
        # raise_if_old_compute() depends on the RPC to be up and does not
        # implement its own retry mechanism to connect to the conductor.
        try:
            utils.raise_if_old_compute()
        except exception.TooOldComputeService as e:
            if CONF.workarounds.disable_compute_service_check_for_ffu:
                LOG.warning(str(e))
            else:
                raise

        return service_obj

    def kill(self):
        """Destroy the service object in the datastore.

        NOTE: Although this method is not used anywhere else than tests, it is
        convenient to have it here, so the tests might easily and in clean way
        stop and remove the service_ref.

        """
        self.stop()
        try:
            self.service_ref.destroy()
        except exception.NotFound:
            LOG.warning('Service killed that has no database entry')

    def stop(self):
        """stop the service and clean up."""
        try:
            self.rpcserver.stop()
            self.rpcserver.wait()
        except Exception:
            pass

        try:
            self.manager.cleanup_host()
        except Exception:
            LOG.exception('Service error occurred during cleanup_host')
            pass

        super(Service, self).stop()

    def periodic_tasks(self, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        ctxt = context.get_admin_context()
        return self.manager.periodic_tasks(ctxt, raise_on_error=raise_on_error)

    def basic_config_check(self):
        """Perform basic config checks before starting processing."""
        # Make sure the tempdir exists and is writable
        try:
            with utils.tempdir():
                pass
        except Exception as e:
            LOG.error('Temporary directory is invalid: %s', e)
            sys.exit(1)

    def reset(self):
        """reset the service."""
        self.manager.reset()
        # Reset the cell cache that holds database transaction context managers
        context.CELL_CACHE = {}


class WSGIServer(service.ServiceBase):
    """Server class to manage a WSGI server, serving a WSGI application."""

    default_pool_size = CONF.wsgi.default_pool_size

    def __init__(self, name, app, host='0.0.0.0', port=0, pool_size=None,
                       protocol=eventlet.wsgi.HttpProtocol, backlog=128,
                       use_ssl=False, max_url_len=None):
        """Initialize, but do not start, a WSGI server.

        :param name: Pretty name for logging.
        :param app: The WSGI application to serve.
        :param host: IP address to serve the application.
        :param port: Port number to server the application.
        :param pool_size: Maximum number of eventlets to spawn concurrently.
        :param backlog: Maximum number of queued connections.
        :param max_url_len: Maximum length of permitted URLs.
        :returns: None
        :raises: nova.exception.InvalidInput
        """
        # Allow operators to customize http requests max header line size.
        eventlet.wsgi.MAX_HEADER_LINE = CONF.wsgi.max_header_line
        self.name = name
        self.app = app
        self._server = None
        self._protocol = protocol
        self.pool_size = pool_size or self.default_pool_size
        self._pool = eventlet.GreenPool(self.pool_size)
        self._logger = logging.getLogger("nova.%s.wsgi.server" % self.name)
        self._use_ssl = use_ssl
        self._max_url_len = max_url_len
        self.client_socket_timeout = CONF.wsgi.client_socket_timeout or None

        if backlog < 1:
            raise exception.InvalidInput(
                    reason=_('The backlog must be more than 0'))

        bind_addr = (host, port)
        # TODO(dims): eventlet's green dns/socket module does not actually
        # support IPv6 in getaddrinfo(). We need to get around this in the
        # future or monitor upstream for a fix
        try:
            info = socket.getaddrinfo(bind_addr[0],
                                      bind_addr[1],
                                      socket.AF_UNSPEC,
                                      socket.SOCK_STREAM)[0]
            family = info[0]
            bind_addr = info[-1]
        except Exception:
            family = socket.AF_INET

        try:
            self._socket = eventlet.listen(bind_addr, family, backlog=backlog)
        except EnvironmentError:
            LOG.error("Could not bind to %(host)s:%(port)s",
                      {'host': host, 'port': port})
            raise

        (self.host, self.port) = self._socket.getsockname()[0:2]
        LOG.info("%(name)s listening on %(host)s:%(port)s",
                 {'name': self.name, 'host': self.host, 'port': self.port})

    def start(self):
        """Start serving a WSGI application.

        :returns: None
        """
        # The server socket object will be closed after server exits,
        # but the underlying file descriptor will remain open, and will
        # give bad file descriptor error. So duplicating the socket object,
        # to keep file descriptor usable.

        dup_socket = self._socket.dup()
        dup_socket.setsockopt(socket.SOL_SOCKET,
                              socket.SO_REUSEADDR, 1)
        # sockets can hang around forever without keepalive
        dup_socket.setsockopt(socket.SOL_SOCKET,
                              socket.SO_KEEPALIVE, 1)

        # This option isn't available in the OS X version of eventlet
        if hasattr(socket, 'TCP_KEEPIDLE'):
            dup_socket.setsockopt(socket.IPPROTO_TCP,
                                  socket.TCP_KEEPIDLE,
                                  CONF.wsgi.tcp_keepidle)

        if self._use_ssl:
            try:
                ca_file = CONF.wsgi.ssl_ca_file
                cert_file = CONF.wsgi.ssl_cert_file
                key_file = CONF.wsgi.ssl_key_file

                if cert_file and not os.path.exists(cert_file):
                    raise RuntimeError(
                          _("Unable to find cert_file : %s") % cert_file)

                if ca_file and not os.path.exists(ca_file):
                    raise RuntimeError(
                          _("Unable to find ca_file : %s") % ca_file)

                if key_file and not os.path.exists(key_file):
                    raise RuntimeError(
                          _("Unable to find key_file : %s") % key_file)

                if self._use_ssl and (not cert_file or not key_file):
                    raise RuntimeError(
                          _("When running server in SSL mode, you must "
                            "specify both a cert_file and key_file "
                            "option value in your configuration file"))
                ssl_kwargs = {
                    'server_side': True,
                    'certfile': cert_file,
                    'keyfile': key_file,
                    'cert_reqs': ssl.CERT_NONE,
                }

                if CONF.wsgi.ssl_ca_file:
                    ssl_kwargs['ca_certs'] = ca_file
                    ssl_kwargs['cert_reqs'] = ssl.CERT_REQUIRED

                dup_socket = eventlet.wrap_ssl(dup_socket,
                                               **ssl_kwargs)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(
                        "Failed to start %(name)s on %(host)s:%(port)s with "
                        "SSL support",
                        {'name': self.name, 'host': self.host,
                         'port': self.port})

        wsgi_kwargs = {
            'func': eventlet.wsgi.server,
            'sock': dup_socket,
            'site': self.app,
            'protocol': self._protocol,
            'custom_pool': self._pool,
            'log': self._logger,
            'log_format': CONF.wsgi.wsgi_log_format,
            'debug': False,
            'keepalive': CONF.wsgi.keep_alive,
            'socket_timeout': self.client_socket_timeout
            }

        if self._max_url_len:
            wsgi_kwargs['url_length_limit'] = self._max_url_len

        self._server = utils.spawn(**wsgi_kwargs)

    def reset(self):
        """Reset server greenpool size to default.

        :returns: None

        """
        self._pool.resize(self.pool_size)

    def stop(self):
        """Stop this server.

        This is not a very nice action, as currently the method by which a
        server is stopped is by killing its eventlet.

        :returns: None

        """
        LOG.info("Stopping WSGI server.")

        if self._server is not None:
            # Resize pool to stop new requests from being processed
            self._pool.resize(0)
            self._server.kill()

    def wait(self):
        """Block, until the server has stopped.

        Waits on the server's eventlet to finish, then returns.

        :returns: None

        """
        try:
            if self._server is not None:
                self._pool.waitall()
                self._server.wait()
        except greenlet.GreenletExit:
            LOG.info("WSGI server has stopped.")


class WSGIService(service.Service):
    """Provides ability to launch API from a 'paste' configuration."""

    def __init__(self, name, loader=None, use_ssl=False, max_url_len=None):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param loader: Loads the WSGI application using the given name.
        :returns: None

        """
        self.name = name
        # NOTE(danms): Name can be metadata, osapi_compute, per
        # nova.service's enabled_apis
        self.binary = 'nova-%s' % name

        LOG.warning('Running %s using eventlet is deprecated. Deploy with '
                    'a WSGI server such as uwsgi or mod_wsgi.', self.binary)

        self.topic = None
        self.manager = self._get_manager()
        self.loader = loader or api_wsgi.Loader()
        self.app = self.loader.load_app(name)
        # inherit all compute_api worker counts from osapi_compute
        if name.startswith('openstack_compute_api'):
            wname = 'osapi_compute'
        else:
            wname = name
        self.host = getattr(CONF, '%s_listen' % name, "0.0.0.0")
        self.port = getattr(CONF, '%s_listen_port' % name, 0)
        self.workers = (getattr(CONF, '%s_workers' % wname, None) or
                        processutils.get_worker_count())
        if self.workers and self.workers < 1:
            worker_name = '%s_workers' % name
            msg = (_("%(worker_name)s value of %(workers)s is invalid, "
                     "must be greater than 0") %
                   {'worker_name': worker_name,
                    'workers': str(self.workers)})
            raise exception.InvalidInput(msg)
        self.use_ssl = use_ssl
        self.server = WSGIServer(
            name,
            self.app,
            host=self.host,
            port=self.port,
            use_ssl=self.use_ssl,
            max_url_len=max_url_len,
        )
        # Pull back actual port used
        self.port = self.server.port
        self.backdoor_port = None
        setup_profiler(name, self.host)

    def reset(self):
        """Reset the following:

        * server greenpool size to default
        * service version cache
        * cell cache holding database transaction context managers

        :returns: None

        """
        self.server.reset()
        service_obj.Service.clear_min_version_cache()
        context.CELL_CACHE = {}

    def _get_manager(self):
        """Initialize a Manager object appropriate for this service.

        Use the service name to look up a Manager subclass from the
        configuration and initialize an instance. If no class name
        is configured, just return None.

        :returns: a Manager instance, or None.

        """
        manager = SERVICE_MANAGERS.get(self.binary)
        if manager is None:
            return None

        manager_class = importutils.import_class(manager)
        return manager_class()

    def start(self):
        """Start serving this service using loaded configuration.

        Also, retrieve updated port number in case '0' was passed in, which
        indicates a random port should be used.

        :returns: None

        """
        # NOTE(melwitt): Clear the cell cache holding database transaction
        # context manager objects. We do this to ensure we create new internal
        # oslo.db locks to avoid a situation where a child process receives an
        # already locked oslo.db lock when it is forked. When a child process
        # inherits a locked oslo.db lock, database accesses through that
        # transaction context manager will never be able to acquire the lock
        # and requests will fail with CellTimeout errors.
        # See https://bugs.python.org/issue6721 for more information.
        # With python 3.7, it would be possible for oslo.db to make use of the
        # os.register_at_fork() method to reinitialize its lock. Until we
        # require python 3.7 as a minimum version, we must handle the situation
        # outside of oslo.db.
        context.CELL_CACHE = {}

        ctxt = context.get_admin_context()
        service_ref = objects.Service.get_by_host_and_binary(ctxt, self.host,
                                                             self.binary)
        if service_ref:
            _update_service_ref(service_ref)
        else:
            try:
                service_ref = _create_service_ref(self, ctxt)
            except (exception.ServiceTopicExists,
                    exception.ServiceBinaryExists):
                # NOTE(danms): If we race to create a record with a sibling,
                # don't fail here.
                service_ref = objects.Service.get_by_host_and_binary(
                    ctxt, self.host, self.binary)

        self.service_ref = service_ref
        if self.manager:
            self.manager.init_host()
            self.manager.pre_start_hook(self.service_ref)
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


def process_launcher():
    return service.ProcessLauncher(CONF, restart_method='mutate')


# NOTE(vish): the global launcher is to maintain the existing
#             functionality of calling service.serve +
#             service.wait
_launcher = None


def serve(server, workers=None):
    global _launcher
    if _launcher:
        raise RuntimeError(_('serve() can only be called once'))

    _launcher = service.launch(CONF, server, workers=workers,
                               restart_method='mutate')


def wait():
    _launcher.wait()
