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

import functools
import inspect
import os
import os.path
import random
import sys
import threading

from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import service
from oslo_utils import importutils

from nova import baserpc
from nova import conductor
import nova.conf
from nova import context
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


class _TrackingEndpointWrapper:
    """RPC endpoint wrapper to track the RPC methods

    This is RPC endpoint wrapper to be supplied to RPC server so that
    each RPC method call can be tracked. `endpoint` is the real object
    oslo.messaging should dispatch calls to (a service's manager or one
    of its additional_endpoints); `tracker` is the object whose
    _record_task_start()/_record_task_end() the call gets recorded on,
    defaulting to `endpoint` itself. additional_endpoints (e.g. conductor's
    ComputeTaskManager) are not Manager subclasses and have no tracking
    dict of their own, so they're wrapped with `tracker` set to the owning
    manager instead, reporting into its in-progress-task dict.
    """

    def __init__(self, endpoint, tracker=None):
        self._endpoint = endpoint
        self._tracker = tracker if tracker is not None else endpoint

    def __getattr__(self, name):
        attr = getattr(self._endpoint, name)
        if (not inspect.ismethod(attr) or
                getattr(attr, '_skip_automatic_rpc_tracking', False)):
            setattr(self, name, attr)
            return attr

        @functools.wraps(attr)
        def _tracked(*args, **kwargs):
            instance_uuid = None
            request_id = None
            if isinstance(args[0], context.RequestContext):
                request_id = getattr(args[0], 'request_id', None)
            if len(args) > 1 and isinstance(args[1], objects.Instance):
                instance_uuid = args[1].uuid
            elif 'instance' in kwargs:
                instance_uuid = kwargs['instance'].uuid

            key = self._tracker._record_task_start(
                name, instance_uuid, request_id)
            try:
                result = attr(*args, **kwargs)
            except Exception:
                self._tracker._record_task_end(key, failed=True)
                raise
            self._tracker._record_task_end(key)
            return result

        # NOTE(gmaan): __getattr__ is only called when `name` isn't found on
        # the object. Setting the _tracked() wrapped method using setattr so
        # that the next RPC call for same method are called directly without
        # rebuilding RPC method with _tracked() wrapper.
        setattr(self, name, _tracked)
        return _tracked


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
                 periodic_interval_max=None, topic_alt=None,
                 *args, **kwargs):
        super(Service, self).__init__()
        self.host = host
        self.binary = binary
        self.topic = topic
        # NOTE(gmaan): If any service would like to create a 2nd rpc server,
        # then it needs to be created with different topic (topic_alt) so that
        # oslo.messaging creates the different RPC objects (for example,
        # dispatcher, consumers, rabbitmq queue, amqp listener, kombu
        # connection etc). The endpoint (manager) stay same so that same
        # manager will be serving the both rpc servers.
        self.topic_alt = topic_alt
        self.manager_class_name = manager
        self.servicegroup_api = servicegroup.API()
        manager_class = importutils.import_class(self.manager_class_name)
        if objects_base.NovaObject.indirection_api:
            conductor_api = conductor.API()
            conductor_api.wait_until_ready(context.get_admin_context())
        self.manager = manager_class(host=self.host, *args, **kwargs)
        self.rpcserver = None
        self.rpcserver_alt = None
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

        target = messaging.Target(topic=self.topic, server=self.host)

        # Wrap the manager (and its additional_endpoints) so every RPC
        # call dispatched to them is recorded. additional_endpoints (e.g.
        # conductor's ComputeTaskManager) are not Manager subclasses, so
        # they report into the manager's tracking dict instead of their
        # own via the tracker argument.
        manager_endpoint = _TrackingEndpointWrapper(self.manager)

        endpoints = [
            manager_endpoint,
            baserpc.BaseRPCAPI(self.manager.service_name, self.backdoor_port)
        ]
        endpoints.extend(
            _TrackingEndpointWrapper(additional_endpoint, self.manager)
            for additional_endpoint in self.manager.additional_endpoints)

        serializer = objects_base.NovaObjectSerializer()

        LOG.debug("Creating RPC server for service: %s on topic: %s",
                  self.binary, self.topic)
        self.rpcserver = rpc.get_server(target, endpoints, serializer)
        self.rpcserver.start()

        self.rpcserver_alt = None
        # NOTE(gmaan): Only compute service creates the two rpcservers which
        # means each compute service will create two rabiitmq queues bound with
        # same exchange but on two different topics (1. 'compute'
        # 2. 'compute-alt').
        # The main use case for 2nd rpcserver is graceful shutdown of compute
        # service. During graceful shutdown, the compute service will stop
        # listening to the new request (stop listening on 'compute' rpcserver)
        # but continue listening to the 'compute-alt' rpcserver so that it can
        # finish all their ongoing operations.
        if self.topic_alt is not None:
            LOG.debug("Creating 2nd RPC server for service: %s on topic: %s",
                      self.binary, self.topic_alt)
            target_alt = messaging.Target(
                    topic=self.topic_alt, server=self.host)
            self.rpcserver_alt = rpc.get_server(
                    target_alt, endpoints, serializer)
            self.rpcserver_alt.start()

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
               periodic_fuzzy_delay=None, periodic_interval_max=None,
               topic_alt=None):
        """Instantiates class and passes back application object.

        :param host: defaults to CONF.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'nova-' part
        :param manager: defaults to CONF.<topic>_manager
        :param report_interval: defaults to CONF.report_interval
        :param periodic_enable: defaults to CONF.periodic_enable
        :param periodic_fuzzy_delay: defaults to CONF.periodic_fuzzy_delay
        :param periodic_interval_max: if set, the max time to wait between runs
        :param topic_alt: defaults to None

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

        service_obj = cls(host, binary, topic, manager,
                          report_interval=report_interval,
                          periodic_enable=periodic_enable,
                          periodic_fuzzy_delay=periodic_fuzzy_delay,
                          periodic_interval_max=periodic_interval_max,
                          topic_alt=topic_alt)

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
            if self.service_ref:
                self.service_ref.destroy()
        except exception.NotFound:
            LOG.warning('Service killed that has no database entry')

    def _stop_rpc_server(self, rpc_server, topic):
        try:
            LOG.debug('%s service stopping RPC server on topic: %s',
                      self.binary, topic)
            rpc_server.stop()
            return True
        except Exception:
            LOG.exception('Error occurred during RPC server stop.')
            return False

    def _wait_rpc_server(self, rpc_server, topic):
        try:
            rpc_server.wait()
            LOG.debug('%s service stopped RPC server on topic: %s',
                      self.binary, topic)
        except Exception:
            LOG.exception('Error occurred during RPC server wait.')

    def _shutdown_rpc_server(self, rpc_server, topic):
        if self._stop_rpc_server(rpc_server, topic):
            self._wait_rpc_server(rpc_server, topic)

    def _get_manager_shutdown_timeout(self):
        if CONF.manager_shutdown_timeout > CONF.graceful_shutdown_timeout:
            LOG.warning('manager_shutdown_timeout (%s) is higher than '
                        'graceful_shutdown_timeout (%s); the service may be '
                        'killed before the manager finishes waiting.',
                        CONF.manager_shutdown_timeout,
                        CONF.graceful_shutdown_timeout)
            return max(0, CONF.graceful_shutdown_timeout - 10)
        return CONF.manager_shutdown_timeout

    def _run_manager_graceful_shutdown(self):
        timeout = self._get_manager_shutdown_timeout()
        finished = threading.Event()

        def _run():
            try:
                LOG.info('%s manager graceful shutdown started.',
                          self.binary)
                self.manager.graceful_shutdown(timeout)
                LOG.info('%s manager graceful shutdown finished.',
                          self.binary)
            except Exception:
                LOG.exception('Error occurred during %s manager graceful '
                              'shutdown', self.binary)
            finally:
                finished.set()

        # NOTE(gmaan): manager's graceful_shutdown does two things 1. wait for
        # in-progress tasks 2. cleanup_host. First one is controlled with
        # timeout but latter one is sync call to drivers cleanup_host which
        # can hang the shutdown so we need to run manager's graceful_shutdown
        # in a thread with timeout so that we do not hang the overall shutdown.
        shutdown_thread = threading.Thread(target=_run)
        shutdown_thread.daemon = True
        shutdown_thread.start()
        # NOTE(gmaan): Event.wait(timeout) always returns a bool even on
        # timeout.
        if not finished.wait(timeout):
            LOG.warning(
                '%s manager graceful shutdown did not complete within '
                'the %s second, proceeding with service shutdown.',
                self.binary, timeout)

    def stop(self):
        """stop the service and clean up."""
        LOG.info('%s service graceful shutdown started.', self.binary)

        self.manager.set_shutdown_in_progress()

        # This RPC server handles new requests during normal operation. During
        # graceful shutdown, we limit the RPC requests the service can handle.
        # So we stop the main RPC server here and let the alternative RPC
        # server handle the remaining requests for the ongoing operations.
        rpcserver_stopped = False
        if self.rpcserver is not None:
            rpcserver_stopped = self._stop_rpc_server(
                self.rpcserver, self.topic)

        # Run manager graceful_shutdown() before waiting for the RPC server
        # to shutdown so that tasks already in progress on self.rpcserver can
        # also be tracked and logged before RPC server wait() finish them.
        self._run_manager_graceful_shutdown()

        if rpcserver_stopped:
            self._wait_rpc_server(self.rpcserver, self.topic)

        if self.rpcserver_alt is not None:
            # During graceful shutdown, manager will use this RPC server to
            # finish the in-progress tasks so this RPC server will be stopped
            # at the end.
            self._shutdown_rpc_server(
                    self.rpcserver_alt, self.topic_alt)

        LOG.info('%s service graceful shutdown finished.', self.binary)
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


# NOTE(vish): the global launcher is to maintain the existing
#             functionality of calling service.serve +
#             service.wait
_launcher = None


def serve(server, workers=None, no_fork=False):
    global _launcher
    if _launcher:
        raise RuntimeError(_('serve() can only be called once'))

    _launcher = service.launch(CONF, server, workers=workers,
                               restart_method='mutate', no_fork=no_fork)


def wait():
    _launcher.wait()
