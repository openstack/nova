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

"""Handles all processes relating to instances (guest vms).

The :py:class:`ComputeManager` class is a :py:class:`nova.manager.Manager` that
handles RPC calls relating to creating instances.  It is responsible for
building a disk image, launching it via the underlying virtualization driver,
responding to calls to check its state, attaching persistent storage, and
terminating it.

"""

import base64
import binascii
# If py2, concurrent.futures comes from the futures library otherwise it
# comes from the py3 standard library.
from concurrent import futures
import contextlib
import functools
import inspect
import sys
import time
import traceback

from cinderclient import exceptions as cinder_exception
from cursive import exception as cursive_exception
import eventlet.event
from eventlet import greenthread
import eventlet.semaphore
import eventlet.timeout
from keystoneauth1 import exceptions as keystone_exception
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslo_service import periodic_task
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import timeutils
import six
from six.moves import range

from nova import block_device
from nova.cells import rpcapi as cells_rpcapi
from nova import compute
from nova.compute import build_results
from nova.compute import claims
from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute.utils import wrap_instance_event
from nova.compute import vm_states
from nova import conductor
import nova.conf
from nova.console import rpcapi as console_rpcapi
import nova.context
from nova import exception
from nova import exception_wrapper
from nova import hooks
from nova.i18n import _
from nova import image
from nova import manager
from nova import network
from nova.network import base_api as base_net_api
from nova.network import model as network_model
from nova.network.security_group import openstack_driver
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova.objects import instance as obj_instance
from nova.objects import migrate_data as migrate_data_obj
from nova.pci import whitelist
from nova import rpc
from nova import safe_utils
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import utils
from nova.virt import block_device as driver_block_device
from nova.virt import configdrive
from nova.virt import driver
from nova.virt import event as virtevent
from nova.virt import storage_users
from nova.virt import virtapi
from nova.volume import cinder

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

get_notifier = functools.partial(rpc.get_notifier, service='compute')
wrap_exception = functools.partial(exception_wrapper.wrap_exception,
                                   get_notifier=get_notifier,
                                   binary='nova-compute')


@contextlib.contextmanager
def errors_out_migration_ctxt(migration):
    """Context manager to error out migration on failure."""

    try:
        yield
    except Exception:
        with excutils.save_and_reraise_exception():
            if migration:
                # We may have been passed None for our migration if we're
                # receiving from an older client. The migration will be
                # errored via the legacy path.
                migration.status = 'error'
                try:
                    with migration.obj_as_admin():
                        migration.save()
                except Exception:
                    LOG.debug(
                        'Error setting migration status for instance %s.',
                        migration.instance_uuid, exc_info=True)


@utils.expects_func_args('migration')
def errors_out_migration(function):
    """Decorator to error out migration on failure."""

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        wrapped_func = safe_utils.get_wrapped_function(function)
        keyed_args = inspect.getcallargs(wrapped_func, self, context,
                                         *args, **kwargs)
        migration = keyed_args['migration']
        with errors_out_migration_ctxt(migration):
            return function(self, context, *args, **kwargs)

    return decorated_function


@utils.expects_func_args('instance')
def reverts_task_state(function):
    """Decorator to revert task_state on failure."""

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        try:
            return function(self, context, *args, **kwargs)
        except exception.UnexpectedTaskStateError as e:
            # Note(maoy): unexpected task state means the current
            # task is preempted. Do not clear task state in this
            # case.
            with excutils.save_and_reraise_exception():
                LOG.info("Task possibly preempted: %s",
                         e.format_message())
        except Exception:
            with excutils.save_and_reraise_exception():
                wrapped_func = safe_utils.get_wrapped_function(function)
                keyed_args = inspect.getcallargs(wrapped_func, self, context,
                                                 *args, **kwargs)
                # NOTE(mriedem): 'instance' must be in keyed_args because we
                # have utils.expects_func_args('instance') decorating this
                # method.
                instance = keyed_args['instance']
                original_task_state = instance.task_state
                try:
                    self._instance_update(context, instance, task_state=None)
                    LOG.info("Successfully reverted task state from %s on "
                             "failure for instance.",
                             original_task_state, instance=instance)
                except exception.InstanceNotFound:
                    # We might delete an instance that failed to build shortly
                    # after it errored out this is an expected case and we
                    # should not trace on it.
                    pass
                except Exception as e:
                    LOG.warning("Failed to revert task state for instance. "
                                "Error: %s", e, instance=instance)

    return decorated_function


@utils.expects_func_args('instance')
def wrap_instance_fault(function):
    """Wraps a method to catch exceptions related to instances.

    This decorator wraps a method to catch any exceptions having to do with
    an instance that may get thrown. It then logs an instance fault in the db.
    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        try:
            return function(self, context, *args, **kwargs)
        except exception.InstanceNotFound:
            raise
        except Exception as e:
            # NOTE(gtt): If argument 'instance' is in args rather than kwargs,
            # we will get a KeyError exception which will cover up the real
            # exception. So, we update kwargs with the values from args first.
            # then, we can get 'instance' from kwargs easily.
            kwargs.update(dict(zip(function.__code__.co_varnames[2:], args)))

            with excutils.save_and_reraise_exception():
                compute_utils.add_instance_fault_from_exc(context,
                        kwargs['instance'], e, sys.exc_info())

    return decorated_function


@utils.expects_func_args('image_id', 'instance')
def delete_image_on_error(function):
    """Used for snapshot related method to ensure the image created in
    compute.api is deleted when an error occurs.
    """

    @functools.wraps(function)
    def decorated_function(self, context, image_id, instance,
                           *args, **kwargs):
        try:
            return function(self, context, image_id, instance,
                            *args, **kwargs)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug("Cleaning up image %s", image_id,
                          exc_info=True, instance=instance)
                try:
                    self.image_api.delete(context, image_id)
                except exception.ImageNotFound:
                    # Since we're trying to cleanup an image, we don't care if
                    # if it's already gone.
                    pass
                except Exception:
                    LOG.exception("Error while trying to clean up image %s",
                                  image_id, instance=instance)

    return decorated_function


# TODO(danms): Remove me after Icehouse
# TODO(alaski): Actually remove this after Newton, assuming a major RPC bump
# NOTE(mikal): if the method being decorated has more than one decorator, then
# put this one first. Otherwise the various exception handling decorators do
# not function correctly.
def object_compat(function):
    """Wraps a method that expects a new-world instance

    This provides compatibility for callers passing old-style dict
    instances.
    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        def _load_instance(instance_or_dict):
            if isinstance(instance_or_dict, dict):
                # try to get metadata and system_metadata for most cases but
                # only attempt to load those if the db instance already has
                # those fields joined
                metas = [meta for meta in ('metadata', 'system_metadata')
                         if meta in instance_or_dict]
                instance = objects.Instance._from_db_object(
                    context, objects.Instance(), instance_or_dict,
                    expected_attrs=metas)
                instance._context = context
                return instance
            return instance_or_dict

        try:
            kwargs['instance'] = _load_instance(kwargs['instance'])
        except KeyError:
            args = (_load_instance(args[0]),) + args[1:]

        migration = kwargs.get('migration')
        if isinstance(migration, dict):
            migration = objects.Migration._from_db_object(
                    context.elevated(), objects.Migration(),
                    migration)
            kwargs['migration'] = migration

        return function(self, context, *args, **kwargs)

    return decorated_function


class InstanceEvents(object):
    def __init__(self):
        self._events = {}

    @staticmethod
    def _lock_name(instance):
        return '%s-%s' % (instance.uuid, 'events')

    def prepare_for_instance_event(self, instance, name, tag):
        """Prepare to receive an event for an instance.

        This will register an event for the given instance that we will
        wait on later. This should be called before initiating whatever
        action will trigger the event. The resulting eventlet.event.Event
        object should be wait()'d on to ensure completion.

        :param instance: the instance for which the event will be generated
        :param name: the name of the event we're expecting
        :param tag: the tag associated with the event we're expecting
        :returns: an event object that should be wait()'d on
        """
        if self._events is None:
            # NOTE(danms): We really should have a more specific error
            # here, but this is what we use for our default error case
            raise exception.NovaException('In shutdown, no new events '
                                          'can be scheduled')

        @utils.synchronized(self._lock_name(instance))
        def _create_or_get_event():
            instance_events = self._events.setdefault(instance.uuid, {})
            return instance_events.setdefault((name, tag),
                                              eventlet.event.Event())
        LOG.debug('Preparing to wait for external event %(name)s-%(tag)s',
                  {'name': name, 'tag': tag}, instance=instance)
        return _create_or_get_event()

    def pop_instance_event(self, instance, event):
        """Remove a pending event from the wait list.

        This will remove a pending event from the wait list so that it
        can be used to signal the waiters to wake up.

        :param instance: the instance for which the event was generated
        :param event: the nova.objects.external_event.InstanceExternalEvent
                      that describes the event
        :returns: the eventlet.event.Event object on which the waiters
                  are blocked
        """
        no_events_sentinel = object()
        no_matching_event_sentinel = object()

        @utils.synchronized(self._lock_name(instance))
        def _pop_event():
            if self._events is None:
                LOG.debug('Unexpected attempt to pop events during shutdown',
                          instance=instance)
                return no_events_sentinel
            events = self._events.get(instance.uuid)
            if not events:
                return no_events_sentinel
            _event = events.pop((event.name, event.tag), None)
            if not events:
                del self._events[instance.uuid]
            if _event is None:
                return no_matching_event_sentinel
            return _event

        result = _pop_event()
        if result is no_events_sentinel:
            LOG.debug('No waiting events found dispatching %(event)s',
                      {'event': event.key},
                      instance=instance)
            return None
        elif result is no_matching_event_sentinel:
            LOG.debug('No event matching %(event)s in %(events)s',
                      {'event': event.key,
                       'events': self._events.get(instance.uuid, {}).keys()},
                      instance=instance)
            return None
        else:
            return result

    def clear_events_for_instance(self, instance):
        """Remove all pending events for an instance.

        This will remove all events currently pending for an instance
        and return them (indexed by event name).

        :param instance: the instance for which events should be purged
        :returns: a dictionary of {event_name: eventlet.event.Event}
        """
        @utils.synchronized(self._lock_name(instance))
        def _clear_events():
            if self._events is None:
                LOG.debug('Unexpected attempt to clear events during shutdown',
                          instance=instance)
                return dict()
            # NOTE(danms): We have historically returned the raw internal
            # format here, which is {event.key: [events, ...])} so just
            # trivially convert it here.
            return {'%s-%s' % k: e
                    for k, e in self._events.pop(instance.uuid, {}).items()}
        return _clear_events()

    def cancel_all_events(self):
        if self._events is None:
            LOG.debug('Unexpected attempt to cancel events during shutdown.')
            return
        our_events = self._events
        # NOTE(danms): Block new events
        self._events = None

        for instance_uuid, events in our_events.items():
            for (name, tag), eventlet_event in events.items():
                LOG.debug('Canceling in-flight event %(name)s-%(tag)s for '
                          'instance %(instance_uuid)s',
                          {'name': name,
                           'tag': tag,
                           'instance_uuid': instance_uuid})
                event = objects.InstanceExternalEvent(
                    instance_uuid=instance_uuid,
                    name=name, status='failed',
                    tag=tag, data={})
                eventlet_event.send(event)


class ComputeVirtAPI(virtapi.VirtAPI):
    def __init__(self, compute):
        super(ComputeVirtAPI, self).__init__()
        self._compute = compute

    def _default_error_callback(self, event_name, instance):
        raise exception.NovaException(_('Instance event failed'))

    @contextlib.contextmanager
    def wait_for_instance_event(self, instance, event_names, deadline=300,
                                error_callback=None):
        """Plan to wait for some events, run some code, then wait.

        This context manager will first create plans to wait for the
        provided event_names, yield, and then wait for all the scheduled
        events to complete.

        Note that this uses an eventlet.timeout.Timeout to bound the
        operation, so callers should be prepared to catch that
        failure and handle that situation appropriately.

        If the event is not received by the specified timeout deadline,
        eventlet.timeout.Timeout is raised.

        If the event is received but did not have a 'completed'
        status, a NovaException is raised.  If an error_callback is
        provided, instead of raising an exception as detailed above
        for the failure case, the callback will be called with the
        event_name and instance, and can return True to continue
        waiting for the rest of the events, False to stop processing,
        or raise an exception which will bubble up to the waiter.

        :param instance: The instance for which an event is expected
        :param event_names: A list of event names. Each element is a
                            tuple of strings to indicate (name, tag),
                            where name is required, but tag may be None.
        :param deadline: Maximum number of seconds we should wait for all
                         of the specified events to arrive.
        :param error_callback: A function to be called if an event arrives

        """

        if error_callback is None:
            error_callback = self._default_error_callback
        events = {}
        for event_name in event_names:
            name, tag = event_name
            event_name = objects.InstanceExternalEvent.make_key(name, tag)
            try:
                events[event_name] = (
                    self._compute.instance_events.prepare_for_instance_event(
                        instance, name, tag))
            except exception.NovaException:
                error_callback(event_name, instance)
                # NOTE(danms): Don't wait for any of the events. They
                # should all be canceled and fired immediately below,
                # but don't stick around if not.
                deadline = 0
        yield
        with eventlet.timeout.Timeout(deadline):
            for event_name, event in events.items():
                actual_event = event.wait()
                if actual_event.status == 'completed':
                    continue
                decision = error_callback(event_name, instance)
                if decision is False:
                    break


class ComputeManager(manager.Manager):
    """Manages the running instances from creation to destruction."""

    target = messaging.Target(version='5.0')

    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        self.virtapi = ComputeVirtAPI(self)
        self.network_api = network.API()
        self.volume_api = cinder.API()
        self.image_api = image.API()
        self._last_host_check = 0
        self._last_bw_usage_poll = 0
        self._bw_usage_supported = True
        self._last_bw_usage_cell_update = 0
        self.compute_api = compute.API()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.conductor_api = conductor.API()
        self.compute_task_api = conductor.ComputeTaskAPI()
        self.is_neutron_security_groups = (
            openstack_driver.is_neutron_security_groups())
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        self.scheduler_client = scheduler_client.SchedulerClient()
        self.reportclient = self.scheduler_client.reportclient
        self._resource_tracker = None
        self.instance_events = InstanceEvents()
        self._sync_power_pool = eventlet.GreenPool(
            size=CONF.sync_power_state_pool_size)
        self._syncs_in_progress = {}
        self.send_instance_updates = (
            CONF.filter_scheduler.track_instance_changes)
        if CONF.max_concurrent_builds != 0:
            self._build_semaphore = eventlet.semaphore.Semaphore(
                CONF.max_concurrent_builds)
        else:
            self._build_semaphore = compute_utils.UnlimitedSemaphore()
        if max(CONF.max_concurrent_live_migrations, 0) != 0:
            self._live_migration_executor = futures.ThreadPoolExecutor(
                max_workers=CONF.max_concurrent_live_migrations)
        else:
            # Starting in python 3.5, this is technically bounded, but it's
            # ncpu * 5 which is probably much higher than anyone would sanely
            # use for concurrently running live migrations.
            self._live_migration_executor = futures.ThreadPoolExecutor()
        # This is a dict, keyed by instance uuid, to a two-item tuple of
        # migration object and Future for the queued live migration.
        self._waiting_live_migrations = {}

        super(ComputeManager, self).__init__(service_name="compute",
                                             *args, **kwargs)

        # NOTE(russellb) Load the driver last.  It may call back into the
        # compute manager via the virtapi, so we want it to be fully
        # initialized before that happens.
        self.driver = driver.load_compute_driver(self.virtapi, compute_driver)
        self.use_legacy_block_device_info = \
                            self.driver.need_legacy_block_device_info

    def reset(self):
        LOG.info('Reloading compute RPC API')
        compute_rpcapi.LAST_VERSION = None
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()

    def _get_resource_tracker(self):
        if not self._resource_tracker:
            rt = resource_tracker.ResourceTracker(self.host, self.driver)
            self._resource_tracker = rt
        return self._resource_tracker

    def _update_resource_tracker(self, context, instance):
        """Let the resource tracker know that an instance has changed state."""

        if instance.host == self.host:
            rt = self._get_resource_tracker()
            rt.update_usage(context, instance, instance.node)

    def _instance_update(self, context, instance, **kwargs):
        """Update an instance in the database using kwargs as value."""

        for k, v in kwargs.items():
            setattr(instance, k, v)
        instance.save()
        self._update_resource_tracker(context, instance)

    def _nil_out_instance_obj_host_and_node(self, instance):
        # NOTE(jwcroppe): We don't do instance.save() here for performance
        # reasons; a call to this is expected to be immediately followed by
        # another call that does instance.save(), thus avoiding two writes
        # to the database layer.
        instance.host = None
        instance.node = None
        # If the instance is not on a host, it's not in an aggregate and
        # therefore is not in an availability zone.
        instance.availability_zone = None

    def _set_instance_obj_error_state(self, context, instance,
                                      clean_task_state=False):
        try:
            instance.vm_state = vm_states.ERROR
            if clean_task_state:
                instance.task_state = None
            instance.save()
        except exception.InstanceNotFound:
            LOG.debug('Instance has been destroyed from under us while '
                      'trying to set it to ERROR', instance=instance)

    def _get_instances_on_driver(self, context, filters=None):
        """Return a list of instance records for the instances found
        on the hypervisor which satisfy the specified filters. If filters=None
        return a list of instance records for all the instances found on the
        hypervisor.
        """
        if not filters:
            filters = {}
        try:
            driver_uuids = self.driver.list_instance_uuids()
            if len(driver_uuids) == 0:
                # Short circuit, don't waste a DB call
                return objects.InstanceList()
            filters['uuid'] = driver_uuids
            local_instances = objects.InstanceList.get_by_filters(
                context, filters, use_slave=True)
            return local_instances
        except NotImplementedError:
            pass

        # The driver doesn't support uuids listing, so we'll have
        # to brute force.
        driver_instances = self.driver.list_instances()
        # NOTE(mjozefcz): In this case we need to apply host filter.
        # Without this all instance data would be fetched from db.
        filters['host'] = self.host
        instances = objects.InstanceList.get_by_filters(context, filters,
                                                        use_slave=True)
        name_map = {instance.name: instance for instance in instances}
        local_instances = []
        for driver_instance in driver_instances:
            instance = name_map.get(driver_instance)
            if not instance:
                continue
            local_instances.append(instance)
        return local_instances

    def _destroy_evacuated_instances(self, context):
        """Destroys evacuated instances.

        While nova-compute was down, the instances running on it could be
        evacuated to another host. This method looks for evacuation migration
        records where this is the source host and which were either started
        (accepted), in-progress (pre-migrating) or migrated (done). From those
        migration records, local instances reported by the hypervisor are
        compared to the instances for the migration records and those local
        guests are destroyed, along with instance allocation records in
        Placement for this node.
        """
        filters = {
            'source_compute': self.host,
            # NOTE(mriedem): Migration records that have been accepted are
            # included in case the source node comes back up while instances
            # are being evacuated to another host. We don't want the same
            # instance being reported from multiple hosts.
            # NOTE(lyarwood): pre-migrating is also included here as the
            # source compute can come back online shortly after the RT
            # claims on the destination that in-turn moves the migration to
            # pre-migrating. If the evacuate fails on the destination host,
            # the user can rebuild the instance (in ERROR state) on the source
            # host.
            'status': ['accepted', 'pre-migrating', 'done'],
            'migration_type': 'evacuation',
        }
        with utils.temporary_mutation(context, read_deleted='yes'):
            evacuations = objects.MigrationList.get_by_filters(context,
                                                               filters)
        if not evacuations:
            return
        evacuations = {mig.instance_uuid: mig for mig in evacuations}

        # The instances might be deleted in which case we need to avoid
        # InstanceNotFound being raised from lazy-loading fields on the
        # instances while cleaning up this host.
        read_deleted_context = context.elevated(read_deleted='yes')
        # TODO(mriedem): We could optimize by pre-loading the joined fields
        # we know we'll use, like info_cache and flavor. We can also replace
        # this with a generic solution: https://review.openstack.org/575190/
        local_instances = self._get_instances_on_driver(read_deleted_context)
        evacuated = [inst for inst in local_instances
                     if inst.uuid in evacuations]

        # NOTE(gibi): We are called from init_host and at this point the
        # compute_nodes of the resource tracker has not been populated yet so
        # we cannot rely on the resource tracker here.
        compute_nodes = {}

        for instance in evacuated:
            migration = evacuations[instance.uuid]
            LOG.info('Deleting instance as it has been evacuated from '
                     'this host', instance=instance)
            try:
                network_info = self.network_api.get_instance_nw_info(
                    context, instance)
                bdi = self._get_instance_block_device_info(context,
                                                           instance)
                destroy_disks = not (self._is_instance_storage_shared(
                    context, instance))
            except exception.InstanceNotFound:
                network_info = network_model.NetworkInfo()
                bdi = {}
                LOG.info('Instance has been marked deleted already, '
                         'removing it from the hypervisor.',
                         instance=instance)
                # always destroy disks if the instance was deleted
                destroy_disks = True
            self.driver.destroy(context, instance,
                                network_info,
                                bdi, destroy_disks)

            # delete the allocation of the evacuated instance from this host
            if migration.source_node not in compute_nodes:
                try:
                    cn_uuid = objects.ComputeNode.get_by_host_and_nodename(
                        context, self.host, migration.source_node).uuid
                    compute_nodes[migration.source_node] = cn_uuid
                except exception.ComputeHostNotFound:
                    LOG.error("Failed to clean allocation of evacuated "
                              "instance as the source node %s is not found",
                              migration.source_node, instance=instance)
                    continue
            cn_uuid = compute_nodes[migration.source_node]

            # If the instance was deleted in the interim, assume its
            # allocations were properly cleaned up (either by its hosting
            # compute service or the API).
            if (not instance.deleted and
                    not scheduler_utils.remove_allocation_from_compute(
                        context, instance, cn_uuid, self.reportclient)):
                LOG.error("Failed to clean allocation of evacuated instance "
                          "on the source node %s",
                          cn_uuid, instance=instance)

            migration.status = 'completed'
            migration.save()
        return evacuations

    def _is_instance_storage_shared(self, context, instance, host=None):
        shared_storage = True
        data = None
        try:
            data = self.driver.check_instance_shared_storage_local(context,
                                                       instance)
            if data:
                shared_storage = (self.compute_rpcapi.
                                  check_instance_shared_storage(context,
                                  instance, data, host=host))
        except NotImplementedError:
            LOG.debug('Hypervisor driver does not support '
                      'instance shared storage check, '
                      'assuming it\'s not on shared storage',
                      instance=instance)
            shared_storage = False
        except Exception:
            LOG.exception('Failed to check if instance shared',
                          instance=instance)
        finally:
            if data:
                self.driver.check_instance_shared_storage_cleanup(context,
                                                                  data)
        return shared_storage

    def _complete_partial_deletion(self, context, instance):
        """Complete deletion for instances in DELETED status but not marked as
        deleted in the DB
        """
        instance.destroy()
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
        self._complete_deletion(context,
                                instance,
                                bdms)

    def _complete_deletion(self, context, instance, bdms):
        self._update_resource_tracker(context, instance)

        rt = self._get_resource_tracker()
        rt.reportclient.delete_allocation_for_instance(context, instance.uuid)

        self._notify_about_instance_usage(context, instance, "delete.end")
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.DELETE,
                phase=fields.NotificationPhase.END, bdms=bdms)
        self._clean_instance_console_tokens(context, instance)
        self._delete_scheduler_instance_info(context, instance.uuid)

    def _init_instance(self, context, instance):
        """Initialize this instance during service init."""

        # NOTE(danms): If the instance appears to not be owned by this
        # host, it may have been evacuated away, but skipped by the
        # evacuation cleanup code due to configuration. Thus, if that
        # is a possibility, don't touch the instance in any way, but
        # log the concern. This will help avoid potential issues on
        # startup due to misconfiguration.
        if instance.host != self.host:
            LOG.warning('Instance %(uuid)s appears to not be owned '
                        'by this host, but by %(host)s. Startup '
                        'processing is being skipped.',
                        {'uuid': instance.uuid,
                         'host': instance.host})
            return

        # Instances that are shut down, or in an error state can not be
        # initialized and are not attempted to be recovered. The exception
        # to this are instances that are in RESIZE_MIGRATING or DELETING,
        # which are dealt with further down.
        if (instance.vm_state == vm_states.SOFT_DELETED or
            (instance.vm_state == vm_states.ERROR and
            instance.task_state not in
            (task_states.RESIZE_MIGRATING, task_states.DELETING))):
            LOG.debug("Instance is in %s state.",
                      instance.vm_state, instance=instance)
            return

        if instance.vm_state == vm_states.DELETED:
            try:
                self._complete_partial_deletion(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                LOG.exception('Failed to complete a deletion',
                              instance=instance)
            return

        if (instance.vm_state == vm_states.BUILDING or
            instance.task_state in [task_states.SCHEDULING,
                                    task_states.BLOCK_DEVICE_MAPPING,
                                    task_states.NETWORKING,
                                    task_states.SPAWNING]):
            # NOTE(dave-mcnally) compute stopped before instance was fully
            # spawned so set to ERROR state. This is safe to do as the state
            # may be set by the api but the host is not so if we get here the
            # instance has already been scheduled to this particular host.
            LOG.debug("Instance failed to spawn correctly, "
                      "setting to ERROR state", instance=instance)
            instance.task_state = None
            instance.vm_state = vm_states.ERROR
            instance.save()
            return

        if (instance.vm_state in [vm_states.ACTIVE, vm_states.STOPPED] and
            instance.task_state in [task_states.REBUILDING,
                                    task_states.REBUILD_BLOCK_DEVICE_MAPPING,
                                    task_states.REBUILD_SPAWNING]):
            # NOTE(jichenjc) compute stopped before instance was fully
            # spawned so set to ERROR state. This is consistent to BUILD
            LOG.debug("Instance failed to rebuild correctly, "
                      "setting to ERROR state", instance=instance)
            instance.task_state = None
            instance.vm_state = vm_states.ERROR
            instance.save()
            return

        if (instance.vm_state != vm_states.ERROR and
            instance.task_state in [task_states.IMAGE_SNAPSHOT_PENDING,
                                    task_states.IMAGE_PENDING_UPLOAD,
                                    task_states.IMAGE_UPLOADING,
                                    task_states.IMAGE_SNAPSHOT]):
            LOG.debug("Instance in transitional state %s at start-up "
                      "clearing task state",
                      instance.task_state, instance=instance)
            try:
                self._post_interrupted_snapshot_cleanup(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                LOG.exception('Failed to cleanup snapshot.', instance=instance)
            instance.task_state = None
            instance.save()

        if (instance.vm_state != vm_states.ERROR and
            instance.task_state in [task_states.RESIZE_PREP]):
            LOG.debug("Instance in transitional state %s at start-up "
                      "clearing task state",
                      instance['task_state'], instance=instance)
            instance.task_state = None
            instance.save()

        if instance.task_state == task_states.DELETING:
            try:
                LOG.info('Service started deleting the instance during '
                         'the previous run, but did not finish. Restarting'
                         ' the deletion now.', instance=instance)
                instance.obj_load_attr('metadata')
                instance.obj_load_attr('system_metadata')
                bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                        context, instance.uuid)
                self._delete_instance(context, instance, bdms)
            except Exception:
                # we don't want that an exception blocks the init_host
                LOG.exception('Failed to complete a deletion',
                              instance=instance)
                self._set_instance_obj_error_state(context, instance)
            return

        current_power_state = self._get_power_state(context, instance)
        try_reboot, reboot_type = self._retry_reboot(context, instance,
                                                     current_power_state)

        if try_reboot:
            LOG.debug("Instance in transitional state (%(task_state)s) at "
                      "start-up and power state is (%(power_state)s), "
                      "triggering reboot",
                      {'task_state': instance.task_state,
                       'power_state': current_power_state},
                      instance=instance)

            # NOTE(mikal): if the instance was doing a soft reboot that got as
            # far as shutting down the instance but not as far as starting it
            # again, then we've just become a hard reboot. That means the
            # task state for the instance needs to change so that we're in one
            # of the expected task states for a hard reboot.
            if (instance.task_state in task_states.soft_reboot_states and
                reboot_type == 'HARD'):
                instance.task_state = task_states.REBOOT_PENDING_HARD
                instance.save()

            self.reboot_instance(context, instance, block_device_info=None,
                                 reboot_type=reboot_type)
            return

        elif (current_power_state == power_state.RUNNING and
              instance.task_state in [task_states.REBOOT_STARTED,
                                      task_states.REBOOT_STARTED_HARD,
                                      task_states.PAUSING,
                                      task_states.UNPAUSING]):
            LOG.warning("Instance in transitional state "
                        "(%(task_state)s) at start-up and power state "
                        "is (%(power_state)s), clearing task state",
                        {'task_state': instance.task_state,
                         'power_state': current_power_state},
                        instance=instance)
            instance.task_state = None
            instance.vm_state = vm_states.ACTIVE
            instance.save()
        elif (current_power_state == power_state.PAUSED and
              instance.task_state == task_states.UNPAUSING):
            LOG.warning("Instance in transitional state "
                        "(%(task_state)s) at start-up and power state "
                        "is (%(power_state)s), clearing task state "
                        "and unpausing the instance",
                        {'task_state': instance.task_state,
                         'power_state': current_power_state},
                        instance=instance)
            try:
                self.unpause_instance(context, instance)
            except NotImplementedError:
                # Some virt driver didn't support pause and unpause
                pass
            except Exception:
                LOG.exception('Failed to unpause instance', instance=instance)
            return

        if instance.task_state == task_states.POWERING_OFF:
            try:
                LOG.debug("Instance in transitional state %s at start-up "
                          "retrying stop request",
                          instance.task_state, instance=instance)
                self.stop_instance(context, instance, True)
            except Exception:
                # we don't want that an exception blocks the init_host
                LOG.exception('Failed to stop instance', instance=instance)
            return

        if instance.task_state == task_states.POWERING_ON:
            try:
                LOG.debug("Instance in transitional state %s at start-up "
                          "retrying start request",
                          instance.task_state, instance=instance)
                self.start_instance(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                LOG.exception('Failed to start instance', instance=instance)
            return

        net_info = instance.get_network_info()
        try:
            self.driver.plug_vifs(instance, net_info)
        except NotImplementedError as e:
            LOG.debug(e, instance=instance)
        except exception.VirtualInterfacePlugException:
            # NOTE(mriedem): If we get here, it could be because the vif_type
            # in the cache is "binding_failed" or "unbound".  The only way to
            # fix this is to try and bind the ports again, which would be
            # expensive here on host startup. We could add a check to
            # _heal_instance_info_cache to handle this, but probably only if
            # the instance task_state is None.
            LOG.exception('Virtual interface plugging failed for instance. '
                          'The port binding:host_id may need to be manually '
                          'updated.', instance=instance)
            self._set_instance_obj_error_state(context, instance)
            return

        if instance.task_state == task_states.RESIZE_MIGRATING:
            # We crashed during resize/migration, so roll back for safety
            try:
                # NOTE(mriedem): check old_vm_state for STOPPED here, if it's
                # not in system_metadata we default to True for backwards
                # compatibility
                power_on = (instance.system_metadata.get('old_vm_state') !=
                            vm_states.STOPPED)

                block_dev_info = self._get_instance_block_device_info(context,
                                                                      instance)

                self.driver.finish_revert_migration(context,
                    instance, net_info, block_dev_info, power_on)

            except Exception:
                LOG.exception('Failed to revert crashed migration',
                              instance=instance)
            finally:
                LOG.info('Instance found in migrating state during '
                         'startup. Resetting task_state',
                         instance=instance)
                instance.task_state = None
                instance.save()
        if instance.task_state == task_states.MIGRATING:
            # Live migration did not complete, but instance is on this
            # host, so reset the state.
            instance.task_state = None
            instance.save(expected_task_state=[task_states.MIGRATING])

        db_state = instance.power_state
        drv_state = self._get_power_state(context, instance)
        expect_running = (db_state == power_state.RUNNING and
                          drv_state != db_state)

        LOG.debug('Current state is %(drv_state)s, state in DB is '
                  '%(db_state)s.',
                  {'drv_state': drv_state, 'db_state': db_state},
                  instance=instance)

        if expect_running and CONF.resume_guests_state_on_host_boot:
            self._resume_guests_state(context, instance, net_info)
        elif drv_state == power_state.RUNNING:
            # VMwareAPI drivers will raise an exception
            try:
                self.driver.ensure_filtering_rules_for_instance(
                                       instance, net_info)
            except NotImplementedError:
                LOG.debug('Hypervisor driver does not support '
                          'firewall rules', instance=instance)

    def _resume_guests_state(self, context, instance, net_info):
        LOG.info('Rebooting instance after nova-compute restart.',
                 instance=instance)
        block_device_info = \
            self._get_instance_block_device_info(context, instance)

        try:
            self.driver.resume_state_on_host_boot(
                context, instance, net_info, block_device_info)
        except NotImplementedError:
            LOG.warning('Hypervisor driver does not support '
                        'resume guests', instance=instance)
        except Exception:
            # NOTE(vish): The instance failed to resume, so we set the
            #             instance to error and attempt to continue.
            LOG.warning('Failed to resume instance',
                        instance=instance)
            self._set_instance_obj_error_state(context, instance)

    def _retry_reboot(self, context, instance, current_power_state):
        current_task_state = instance.task_state
        retry_reboot = False
        reboot_type = compute_utils.get_reboot_type(current_task_state,
                                                    current_power_state)

        pending_soft = (current_task_state == task_states.REBOOT_PENDING and
                        instance.vm_state in vm_states.ALLOW_SOFT_REBOOT)
        pending_hard = (current_task_state == task_states.REBOOT_PENDING_HARD
                        and instance.vm_state in vm_states.ALLOW_HARD_REBOOT)
        started_not_running = (current_task_state in
                               [task_states.REBOOT_STARTED,
                                task_states.REBOOT_STARTED_HARD] and
                               current_power_state != power_state.RUNNING)

        if pending_soft or pending_hard or started_not_running:
            retry_reboot = True

        return retry_reboot, reboot_type

    def handle_lifecycle_event(self, event):
        LOG.info("VM %(state)s (Lifecycle Event)",
                 {'state': event.get_name()},
                 instance_uuid=event.get_instance_uuid())
        context = nova.context.get_admin_context(read_deleted='yes')
        vm_power_state = None
        event_transition = event.get_transition()
        if event_transition == virtevent.EVENT_LIFECYCLE_STOPPED:
            vm_power_state = power_state.SHUTDOWN
        elif event_transition == virtevent.EVENT_LIFECYCLE_STARTED:
            vm_power_state = power_state.RUNNING
        elif event_transition in (
                virtevent.EVENT_LIFECYCLE_PAUSED,
                virtevent.EVENT_LIFECYCLE_POSTCOPY_STARTED,
                virtevent.EVENT_LIFECYCLE_MIGRATION_COMPLETED):
            vm_power_state = power_state.PAUSED
        elif event_transition == virtevent.EVENT_LIFECYCLE_RESUMED:
            vm_power_state = power_state.RUNNING
        elif event_transition == virtevent.EVENT_LIFECYCLE_SUSPENDED:
            vm_power_state = power_state.SUSPENDED
        else:
            LOG.warning("Unexpected lifecycle event: %d", event_transition)

        migrate_finish_statuses = {
            # This happens on the source node and indicates live migration
            # entered post-copy mode.
            virtevent.EVENT_LIFECYCLE_POSTCOPY_STARTED: 'running (post-copy)',
            # Suspended for offline migration.
            virtevent.EVENT_LIFECYCLE_MIGRATION_COMPLETED: 'running'
        }

        expected_attrs = []
        if event_transition in migrate_finish_statuses:
            # Join on info_cache since that's needed in migrate_instance_start.
            expected_attrs.append('info_cache')
        instance = objects.Instance.get_by_uuid(context,
                                                event.get_instance_uuid(),
                                                expected_attrs=expected_attrs)

        # Note(lpetrut): The event may be delayed, thus not reflecting
        # the current instance power state. In that case, ignore the event.
        current_power_state = self._get_power_state(context, instance)
        if current_power_state == vm_power_state:
            LOG.debug('Synchronizing instance power state after lifecycle '
                      'event "%(event)s"; current vm_state: %(vm_state)s, '
                      'current task_state: %(task_state)s, current DB '
                      'power_state: %(db_power_state)s, VM power_state: '
                      '%(vm_power_state)s',
                      {'event': event.get_name(),
                       'vm_state': instance.vm_state,
                       'task_state': instance.task_state,
                       'db_power_state': instance.power_state,
                       'vm_power_state': vm_power_state},
                      instance_uuid=instance.uuid)
            self._sync_instance_power_state(context,
                                            instance,
                                            vm_power_state)

        # The following checks are for live migration. We want to activate
        # the port binding for the destination host before the live migration
        # is resumed on the destination host in order to reduce network
        # downtime. Otherwise the ports are bound to the destination host
        # in post_live_migration_at_destination.
        # TODO(danms): Explore options for using a different live migration
        # specific callback for this instead of piggy-backing on the
        # handle_lifecycle_event callback.
        if (instance.task_state == task_states.MIGRATING and
                event_transition in migrate_finish_statuses):
            status = migrate_finish_statuses[event_transition]
            try:
                migration = objects.Migration.get_by_instance_and_status(
                            context, instance.uuid, status)
                LOG.debug('Binding ports to destination host: %s',
                          migration.dest_compute, instance=instance)
                # For neutron, migrate_instance_start will activate the
                # destination host port bindings, if there are any created by
                # conductor before live migration started.
                self.network_api.migrate_instance_start(
                    context, instance, migration)
            except exception.MigrationNotFoundByStatus:
                LOG.warning("Unable to find migration record with status "
                            "'%s' for instance. Port binding will happen in "
                            "post live migration.", status, instance=instance)

    def handle_events(self, event):
        if isinstance(event, virtevent.LifecycleEvent):
            try:
                self.handle_lifecycle_event(event)
            except exception.InstanceNotFound:
                LOG.debug("Event %s arrived for non-existent instance. The "
                          "instance was probably deleted.", event)
        else:
            LOG.debug("Ignoring event %s", event)

    def init_virt_events(self):
        if CONF.workarounds.handle_virt_lifecycle_events:
            self.driver.register_event_listener(self.handle_events)
        else:
            # NOTE(mriedem): If the _sync_power_states periodic task is
            # disabled we should emit a warning in the logs.
            if CONF.sync_power_state_interval < 0:
                LOG.warning('Instance lifecycle events from the compute '
                            'driver have been disabled. Note that lifecycle '
                            'changes to an instance outside of the compute '
                            'service will not be synchronized '
                            'automatically since the _sync_power_states '
                            'periodic task is also disabled.')
            else:
                LOG.info('Instance lifecycle events from the compute '
                         'driver have been disabled. Note that lifecycle '
                         'changes to an instance outside of the compute '
                         'service will only be synchronized by the '
                         '_sync_power_states periodic task.')

    def init_host(self):
        """Initialization for a standalone compute service."""

        if CONF.pci.passthrough_whitelist:
            # Simply loading the PCI passthrough whitelist will do a bunch of
            # validation that would otherwise wait until the PciDevTracker is
            # constructed when updating available resources for the compute
            # node(s) in the resource tracker, effectively killing that task.
            # So load up the whitelist when starting the compute service to
            # flush any invalid configuration early so we can kill the service
            # if the configuration is wrong.
            whitelist.Whitelist(CONF.pci.passthrough_whitelist)

        nova.conf.neutron.register_dynamic_opts(CONF)

        self.driver.init_host(host=self.host)
        context = nova.context.get_admin_context()
        instances = objects.InstanceList.get_by_host(
            context, self.host, expected_attrs=['info_cache', 'metadata'])

        if CONF.defer_iptables_apply:
            self.driver.filter_defer_apply_on()

        self.init_virt_events()

        try:
            # checking that instance was not already evacuated to other host
            evacuated_instances = self._destroy_evacuated_instances(context)

            # Initialise instances on the host that are not evacuating
            for instance in instances:
                if (not evacuated_instances or
                        instance.uuid not in evacuated_instances):
                    self._init_instance(context, instance)

        finally:
            if CONF.defer_iptables_apply:
                self.driver.filter_defer_apply_off()
            if instances:
                # We only send the instance info to the scheduler on startup
                # if there is anything to send, otherwise this host might
                # not be mapped yet in a cell and the scheduler may have
                # issues dealing with the information. Later changes to
                # instances on this host will update the scheduler, or the
                # _sync_scheduler_instance_info periodic task will.
                self._update_scheduler_instance_info(context, instances)

    def cleanup_host(self):
        self.driver.register_event_listener(None)
        self.instance_events.cancel_all_events()
        self.driver.cleanup_host(host=self.host)
        self._cleanup_live_migrations_in_pool()

    def _cleanup_live_migrations_in_pool(self):
        # Shutdown the pool so we don't get new requests.
        self._live_migration_executor.shutdown(wait=False)
        # For any queued migrations, cancel the migration and update
        # its status.
        for migration, future in self._waiting_live_migrations.values():
            # If we got here before the Future was submitted then we need
            # to move on since there isn't anything we can do.
            if future is None:
                continue
            if future.cancel():
                self._set_migration_status(migration, 'cancelled')
                LOG.info('Successfully cancelled queued live migration.',
                         instance_uuid=migration.instance_uuid)
            else:
                LOG.warning('Unable to cancel live migration.',
                            instance_uuid=migration.instance_uuid)
        self._waiting_live_migrations.clear()

    def pre_start_hook(self):
        """After the service is initialized, but before we fully bring
        the service up by listening on RPC queues, make sure to update
        our available resources (and indirectly our available nodes).
        """
        self.update_available_resource(nova.context.get_admin_context(),
                                       startup=True)

    def _get_power_state(self, context, instance):
        """Retrieve the power state for the given instance."""
        LOG.debug('Checking state', instance=instance)
        try:
            return self.driver.get_info(instance).state
        except exception.InstanceNotFound:
            return power_state.NOSTATE

    def get_console_topic(self, context):
        """Retrieves the console host for a project on this host.

        Currently this is just set in the flags for each compute host.

        """
        # TODO(mdragon): perhaps make this variable by console_type?
        return '%s.%s' % (console_rpcapi.RPC_TOPIC, CONF.console_host)

    @wrap_exception()
    def get_console_pool_info(self, context, console_type):
        return self.driver.get_console_pool_info(console_type)

    @wrap_exception()
    def refresh_instance_security_rules(self, context, instance):
        """Tell the virtualization driver to refresh security rules for
        an instance.

        Passes straight through to the virtualization driver.

        Synchronize the call because we may still be in the middle of
        creating the instance.
        """
        @utils.synchronized(instance.uuid)
        def _sync_refresh():
            try:
                return self.driver.refresh_instance_security_rules(instance)
            except NotImplementedError:
                LOG.debug('Hypervisor driver does not support '
                          'security groups.', instance=instance)

        return _sync_refresh()

    def _await_block_device_map_created(self, context, vol_id):
        # TODO(yamahata): creating volume simultaneously
        #                 reduces creation time?
        # TODO(yamahata): eliminate dumb polling
        start = time.time()
        retries = CONF.block_device_allocate_retries
        if retries < 0:
            LOG.warning("Treating negative config value (%(retries)s) for "
                        "'block_device_retries' as 0.",
                        {'retries': retries})
        # (1) treat  negative config value as 0
        # (2) the configured value is 0, one attempt should be made
        # (3) the configured value is > 0, then the total number attempts
        #      is (retries + 1)
        attempts = 1
        if retries >= 1:
            attempts = retries + 1
        for attempt in range(1, attempts + 1):
            volume = self.volume_api.get(context, vol_id)
            volume_status = volume['status']
            if volume_status not in ['creating', 'downloading']:
                if volume_status == 'available':
                    return attempt
                LOG.warning("Volume id: %(vol_id)s finished being "
                            "created but its status is %(vol_status)s.",
                            {'vol_id': vol_id,
                             'vol_status': volume_status})
                break
            greenthread.sleep(CONF.block_device_allocate_retries_interval)
        raise exception.VolumeNotCreated(volume_id=vol_id,
                                         seconds=int(time.time() - start),
                                         attempts=attempt,
                                         volume_status=volume_status)

    def _decode_files(self, injected_files):
        """Base64 decode the list of files to inject."""
        if not injected_files:
            return []

        def _decode(f):
            path, contents = f
            # Py3 raises binascii.Error instead of TypeError as in Py27
            try:
                decoded = base64.b64decode(contents)
                return path, decoded
            except (TypeError, binascii.Error):
                raise exception.Base64Exception(path=path)

        return [_decode(f) for f in injected_files]

    def _validate_instance_group_policy(self, context, instance,
                                        scheduler_hints):
        # NOTE(russellb) Instance group policy is enforced by the scheduler.
        # However, there is a race condition with the enforcement of
        # the policy.  Since more than one instance may be scheduled at the
        # same time, it's possible that more than one instance with an
        # anti-affinity policy may end up here.  It's also possible that
        # multiple instances with an affinity policy could end up on different
        # hosts.  This is a validation step to make sure that starting the
        # instance here doesn't violate the policy.
        group_hint = scheduler_hints.get('group')
        if not group_hint:
            return

        # The RequestSpec stores scheduler_hints as key=list pairs so we need
        # to check the type on the value and pull the single entry out. The
        # API request schema validates that the 'group' hint is a single value.
        if isinstance(group_hint, list):
            group_hint = group_hint[0]

        @utils.synchronized(group_hint)
        def _do_validation(context, instance, group_hint):
            group = objects.InstanceGroup.get_by_hint(context, group_hint)
            if group.policy and 'anti-affinity' == group.policy:
                instances_uuids = objects.InstanceList.get_uuids_by_host(
                    context, self.host)
                ins_on_host = set(instances_uuids)
                members = set(group.members)
                # Determine the set of instance group members on this host
                # which are not the instance in question. This is used to
                # determine how many other members from the same anti-affinity
                # group can be on this host.
                members_on_host = ins_on_host & members - set([instance.uuid])
                rules = group.rules
                if rules and 'max_server_per_host' in rules:
                    max_server = rules['max_server_per_host']
                else:
                    max_server = 1
                if len(members_on_host) >= max_server:
                    msg = _("Anti-affinity instance group policy "
                            "was violated.")
                    raise exception.RescheduledException(
                            instance_uuid=instance.uuid,
                            reason=msg)
            elif group.policy and 'affinity' == group.policy:
                group_hosts = group.get_hosts(exclude=[instance.uuid])
                if group_hosts and self.host not in group_hosts:
                    msg = _("Affinity instance group policy was violated.")
                    raise exception.RescheduledException(
                            instance_uuid=instance.uuid,
                            reason=msg)

        if not CONF.workarounds.disable_group_policy_check_upcall:
            _do_validation(context, instance, group_hint)

    def _log_original_error(self, exc_info, instance_uuid):
        LOG.error('Error: %s', exc_info[1], instance_uuid=instance_uuid,
                  exc_info=exc_info)

    def _reschedule(self, context, request_spec, filter_properties,
            instance, reschedule_method, method_args, task_state,
            exc_info=None, host_list=None):
        """Attempt to re-schedule a compute operation."""

        instance_uuid = instance.uuid
        retry = filter_properties.get('retry')
        if not retry:
            # no retry information, do not reschedule.
            LOG.debug("Retry info not present, will not reschedule",
                      instance_uuid=instance_uuid)
            return

        if not request_spec:
            LOG.debug("No request spec, will not reschedule",
                      instance_uuid=instance_uuid)
            return

        LOG.debug("Re-scheduling %(method)s: attempt %(num)d",
                  {'method': reschedule_method.__name__,
                   'num': retry['num_attempts']}, instance_uuid=instance_uuid)

        # reset the task state:
        self._instance_update(context, instance, task_state=task_state)

        if exc_info:
            # stringify to avoid circular ref problem in json serialization:
            retry['exc'] = traceback.format_exception_only(exc_info[0],
                                    exc_info[1])

        reschedule_method(context, *method_args, host_list=host_list)
        return True

    @periodic_task.periodic_task
    def _check_instance_build_time(self, context):
        """Ensure that instances are not stuck in build."""
        timeout = CONF.instance_build_timeout
        if timeout == 0:
            return

        filters = {'vm_state': vm_states.BUILDING,
                   'host': self.host}

        building_insts = objects.InstanceList.get_by_filters(context,
                           filters, expected_attrs=[], use_slave=True)

        for instance in building_insts:
            if timeutils.is_older_than(instance.created_at, timeout):
                self._set_instance_obj_error_state(context, instance)
                LOG.warning("Instance build timed out. Set to error "
                            "state.", instance=instance)

    def _check_instance_exists(self, context, instance):
        """Ensure an instance with the same name is not already present."""
        if self.driver.instance_exists(instance):
            raise exception.InstanceExists(name=instance.name)

    def _allocate_network_async(self, context, instance, requested_networks,
                                macs, security_groups, is_vpn):
        """Method used to allocate networks in the background.

        Broken out for testing.
        """
        # First check to see if we're specifically not supposed to allocate
        # networks because if so, we can exit early.
        if requested_networks and requested_networks.no_allocate:
            LOG.debug("Not allocating networking since 'none' was specified.",
                      instance=instance)
            return network_model.NetworkInfo([])

        LOG.debug("Allocating IP information in the background.",
                  instance=instance)
        retries = CONF.network_allocate_retries
        attempts = retries + 1
        retry_time = 1
        bind_host_id = self.driver.network_binding_host_id(context, instance)
        for attempt in range(1, attempts + 1):
            try:
                nwinfo = self.network_api.allocate_for_instance(
                        context, instance, vpn=is_vpn,
                        requested_networks=requested_networks,
                        macs=macs,
                        security_groups=security_groups,
                        bind_host_id=bind_host_id)
                LOG.debug('Instance network_info: |%s|', nwinfo,
                          instance=instance)
                instance.system_metadata['network_allocated'] = 'True'
                # NOTE(JoshNang) do not save the instance here, as it can cause
                # races. The caller shares a reference to instance and waits
                # for this async greenthread to finish before calling
                # instance.save().
                return nwinfo
            except Exception:
                exc_info = sys.exc_info()
                log_info = {'attempt': attempt,
                            'attempts': attempts}
                if attempt == attempts:
                    LOG.exception('Instance failed network setup '
                                  'after %(attempts)d attempt(s)',
                                  log_info)
                    six.reraise(*exc_info)
                LOG.warning('Instance failed network setup '
                            '(attempt %(attempt)d of %(attempts)d)',
                            log_info, instance=instance)
                time.sleep(retry_time)
                retry_time *= 2
                if retry_time > 30:
                    retry_time = 30
        # Not reached.

    def _build_networks_for_instance(self, context, instance,
            requested_networks, security_groups):

        # If we're here from a reschedule the network may already be allocated.
        if strutils.bool_from_string(
                instance.system_metadata.get('network_allocated', 'False')):
            # NOTE(alex_xu): The network_allocated is True means the network
            # resource already allocated at previous scheduling, and the
            # network setup is cleanup at previous. After rescheduling, the
            # network resource need setup on the new host.
            self.network_api.setup_instance_network_on_host(
                context, instance, instance.host)
            return self.network_api.get_instance_nw_info(context, instance)

        if not self.is_neutron_security_groups:
            security_groups = []

        macs = self.driver.macs_for_instance(instance)
        network_info = self._allocate_network(context, instance,
                requested_networks, macs, security_groups)

        return network_info

    def _allocate_network(self, context, instance, requested_networks, macs,
                          security_groups):
        """Start network allocation asynchronously.  Return an instance
        of NetworkInfoAsyncWrapper that can be used to retrieve the
        allocated networks when the operation has finished.
        """
        # NOTE(comstud): Since we're allocating networks asynchronously,
        # this task state has little meaning, as we won't be in this
        # state for very long.
        instance.vm_state = vm_states.BUILDING
        instance.task_state = task_states.NETWORKING
        instance.save(expected_task_state=[None])

        is_vpn = False
        return network_model.NetworkInfoAsyncWrapper(
                self._allocate_network_async, context, instance,
                requested_networks, macs, security_groups, is_vpn)

    def _default_root_device_name(self, instance, image_meta, root_bdm):
        try:
            return self.driver.default_root_device_name(instance,
                                                        image_meta,
                                                        root_bdm)
        except NotImplementedError:
            return compute_utils.get_next_device_name(instance, [])

    def _default_device_names_for_instance(self, instance,
                                           root_device_name,
                                           *block_device_lists):
        try:
            self.driver.default_device_names_for_instance(instance,
                                                          root_device_name,
                                                          *block_device_lists)
        except NotImplementedError:
            compute_utils.default_device_names_for_instance(
                instance, root_device_name, *block_device_lists)

    def _get_device_name_for_instance(self, instance, bdms, block_device_obj):
        # NOTE(ndipanov): Copy obj to avoid changing the original
        block_device_obj = block_device_obj.obj_clone()
        try:
            return self.driver.get_device_name_for_instance(
                instance, bdms, block_device_obj)
        except NotImplementedError:
            return compute_utils.get_device_name_for_instance(
                instance, bdms, block_device_obj.get("device_name"))

    def _default_block_device_names(self, instance, image_meta, block_devices):
        """Verify that all the devices have the device_name set. If not,
        provide a default name.

        It also ensures that there is a root_device_name and is set to the
        first block device in the boot sequence (boot_index=0).
        """
        root_bdm = block_device.get_root_bdm(block_devices)
        if not root_bdm:
            return

        # Get the root_device_name from the root BDM or the instance
        root_device_name = None
        update_root_bdm = False

        if root_bdm.device_name:
            root_device_name = root_bdm.device_name
            instance.root_device_name = root_device_name
        elif instance.root_device_name:
            root_device_name = instance.root_device_name
            root_bdm.device_name = root_device_name
            update_root_bdm = True
        else:
            root_device_name = self._default_root_device_name(instance,
                                                              image_meta,
                                                              root_bdm)

            instance.root_device_name = root_device_name
            root_bdm.device_name = root_device_name
            update_root_bdm = True

        if update_root_bdm:
            root_bdm.save()

        ephemerals = list(filter(block_device.new_format_is_ephemeral,
                            block_devices))
        swap = list(filter(block_device.new_format_is_swap,
                      block_devices))
        block_device_mapping = list(filter(
              driver_block_device.is_block_device_mapping, block_devices))

        self._default_device_names_for_instance(instance,
                                                root_device_name,
                                                ephemerals,
                                                swap,
                                                block_device_mapping)

    def _block_device_info_to_legacy(self, block_device_info):
        """Convert BDI to the old format for drivers that need it."""

        if self.use_legacy_block_device_info:
            ephemerals = driver_block_device.legacy_block_devices(
                driver.block_device_info_get_ephemerals(block_device_info))
            mapping = driver_block_device.legacy_block_devices(
                driver.block_device_info_get_mapping(block_device_info))
            swap = block_device_info['swap']
            if swap:
                swap = swap.legacy()

            block_device_info.update({
                'ephemerals': ephemerals,
                'swap': swap,
                'block_device_mapping': mapping})

    def _add_missing_dev_names(self, bdms, instance):
        for bdm in bdms:
            if bdm.device_name is not None:
                continue

            device_name = self._get_device_name_for_instance(instance,
                                                             bdms, bdm)
            values = {'device_name': device_name}
            bdm.update(values)
            bdm.save()

    def _prep_block_device(self, context, instance, bdms):
        """Set up the block device for an instance with error logging."""
        try:
            self._add_missing_dev_names(bdms, instance)
            block_device_info = driver.get_block_device_info(instance, bdms)
            mapping = driver.block_device_info_get_mapping(block_device_info)
            driver_block_device.attach_block_devices(
                mapping, context, instance, self.volume_api, self.driver,
                wait_func=self._await_block_device_map_created)

            self._block_device_info_to_legacy(block_device_info)
            return block_device_info

        except exception.OverQuota as e:
            LOG.warning('Failed to create block device for instance due'
                        ' to exceeding volume related resource quota.'
                        ' Error: %s', e.message, instance=instance)
            raise

        except Exception as ex:
            LOG.exception('Instance failed block device setup',
                          instance=instance)
            # InvalidBDM will eventually result in a BuildAbortException when
            # booting from volume, and will be recorded as an instance fault.
            # Maintain the original exception message which most likely has
            # useful details which the standard InvalidBDM error message lacks.
            raise exception.InvalidBDM(six.text_type(ex))

    def _update_instance_after_spawn(self, context, instance):
        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.launched_at = timeutils.utcnow()
        configdrive.update_instance(instance)

    def _update_scheduler_instance_info(self, context, instance):
        """Sends an InstanceList with created or updated Instance objects to
        the Scheduler client.

        In the case of init_host, the value passed will already be an
        InstanceList. Other calls will send individual Instance objects that
        have been created or resized. In this case, we create an InstanceList
        object containing that Instance.
        """
        if not self.send_instance_updates:
            return
        if isinstance(instance, obj_instance.Instance):
            instance = objects.InstanceList(objects=[instance])
        context = context.elevated()
        self.scheduler_client.update_instance_info(context, self.host,
                                                   instance)

    def _delete_scheduler_instance_info(self, context, instance_uuid):
        """Sends the uuid of the deleted Instance to the Scheduler client."""
        if not self.send_instance_updates:
            return
        context = context.elevated()
        self.scheduler_client.delete_instance_info(context, self.host,
                                                   instance_uuid)

    @periodic_task.periodic_task(spacing=CONF.scheduler_instance_sync_interval)
    def _sync_scheduler_instance_info(self, context):
        if not self.send_instance_updates:
            return
        context = context.elevated()
        instances = objects.InstanceList.get_by_host(context, self.host,
                                                     expected_attrs=[],
                                                     use_slave=True)
        uuids = [instance.uuid for instance in instances]
        self.scheduler_client.sync_instance_info(context, self.host, uuids)

    def _notify_about_instance_usage(self, context, instance, event_suffix,
                                     network_info=None, extra_usage_info=None,
                                     fault=None):
        compute_utils.notify_about_instance_usage(
            self.notifier, context, instance, event_suffix,
            network_info=network_info,
            extra_usage_info=extra_usage_info, fault=fault)

    def _deallocate_network(self, context, instance,
                            requested_networks=None):
        # If we were told not to allocate networks let's save ourselves
        # the trouble of calling the network API.
        if requested_networks and requested_networks.no_allocate:
            LOG.debug("Skipping network deallocation for instance since "
                      "networking was not requested.", instance=instance)
            return

        LOG.debug('Deallocating network for instance', instance=instance)
        with timeutils.StopWatch() as timer:
            self.network_api.deallocate_for_instance(
                context, instance, requested_networks=requested_networks)
        # nova-network does an rpc call so we're OK tracking time spent here
        LOG.info('Took %0.2f seconds to deallocate network for instance.',
                 timer.elapsed(), instance=instance)

    def _get_instance_block_device_info(self, context, instance,
                                        refresh_conn_info=False,
                                        bdms=None):
        """Transform block devices to the driver block_device format."""

        if bdms is None:
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)
        block_device_info = driver.get_block_device_info(instance, bdms)

        if not refresh_conn_info:
            # if the block_device_mapping has no value in connection_info
            # (returned as None), don't include in the mapping
            block_device_info['block_device_mapping'] = [
                bdm for bdm in driver.block_device_info_get_mapping(
                                    block_device_info)
                if bdm.get('connection_info')]
        else:
            driver_block_device.refresh_conn_infos(
                driver.block_device_info_get_mapping(block_device_info),
                context, instance, self.volume_api, self.driver)

        self._block_device_info_to_legacy(block_device_info)

        return block_device_info

    def _build_failed(self, node):
        if CONF.compute.consecutive_build_service_disable_threshold:
            rt = self._get_resource_tracker()
            # NOTE(danms): Update our counter, but wait for the next
            # update_available_resource() periodic to flush it to the DB
            rt.build_failed(node)

    def _build_succeeded(self, node):
        rt = self._get_resource_tracker()
        rt.build_succeeded(node)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def build_and_run_instance(self, context, instance, image, request_spec,
                     filter_properties, admin_password=None,
                     injected_files=None, requested_networks=None,
                     security_groups=None, block_device_mapping=None,
                     node=None, limits=None, host_list=None):

        @utils.synchronized(instance.uuid)
        def _locked_do_build_and_run_instance(*args, **kwargs):
            # NOTE(danms): We grab the semaphore with the instance uuid
            # locked because we could wait in line to build this instance
            # for a while and we want to make sure that nothing else tries
            # to do anything with this instance while we wait.
            with self._build_semaphore:
                try:
                    result = self._do_build_and_run_instance(*args, **kwargs)
                except Exception:
                    # NOTE(mriedem): This should really only happen if
                    # _decode_files in _do_build_and_run_instance fails, and
                    # that's before a guest is spawned so it's OK to remove
                    # allocations for the instance for this node from Placement
                    # below as there is no guest consuming resources anyway.
                    # The _decode_files case could be handled more specifically
                    # but that's left for another day.
                    result = build_results.FAILED
                    raise
                finally:
                    if result == build_results.FAILED:
                        # Remove the allocation records from Placement for the
                        # instance if the build failed. The instance.host is
                        # likely set to None in _do_build_and_run_instance
                        # which means if the user deletes the instance, it
                        # will be deleted in the API, not the compute service.
                        # Setting the instance.host to None in
                        # _do_build_and_run_instance means that the
                        # ResourceTracker will no longer consider this instance
                        # to be claiming resources against it, so we want to
                        # reflect that same thing in Placement.  No need to
                        # call this for a reschedule, as the allocations will
                        # have already been removed in
                        # self._do_build_and_run_instance().
                        self._delete_allocation_for_instance(context,
                                                             instance.uuid)

                    if result in (build_results.FAILED,
                                  build_results.RESCHEDULED):
                        self._build_failed(node)
                    else:
                        self._build_succeeded(node)

        # NOTE(danms): We spawn here to return the RPC worker thread back to
        # the pool. Since what follows could take a really long time, we don't
        # want to tie up RPC workers.
        utils.spawn_n(_locked_do_build_and_run_instance,
                      context, instance, image, request_spec,
                      filter_properties, admin_password, injected_files,
                      requested_networks, security_groups,
                      block_device_mapping, node, limits, host_list)

    def _delete_allocation_for_instance(self, context, instance_uuid):
        rt = self._get_resource_tracker()
        rt.reportclient.delete_allocation_for_instance(context, instance_uuid)

    def _check_device_tagging(self, requested_networks, block_device_mapping):
        tagging_requested = False
        if requested_networks:
            for net in requested_networks:
                if 'tag' in net and net.tag is not None:
                    tagging_requested = True
                    break
        if block_device_mapping and not tagging_requested:
            for bdm in block_device_mapping:
                if 'tag' in bdm and bdm.tag is not None:
                    tagging_requested = True
                    break
        if (tagging_requested and
                not self.driver.capabilities.get('supports_device_tagging',
                                                 False)):
            raise exception.BuildAbortException('Attempt to boot guest with '
                                                'tagged devices on host that '
                                                'does not support tagging.')

    def _check_trusted_certs(self, instance):
        if (instance.trusted_certs and
                not self.driver.capabilities.get('supports_trusted_certs',
                                                 False)):
            raise exception.BuildAbortException(
                'Trusted image certificates provided on host that does not '
                'support certificate validation.')

    @hooks.add_hook('build_instance')
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def _do_build_and_run_instance(self, context, instance, image,
            request_spec, filter_properties, admin_password, injected_files,
            requested_networks, security_groups, block_device_mapping,
            node=None, limits=None, host_list=None):

        try:
            LOG.debug('Starting instance...', instance=instance)
            instance.vm_state = vm_states.BUILDING
            instance.task_state = None
            instance.save(expected_task_state=
                    (task_states.SCHEDULING, None))
        except exception.InstanceNotFound:
            msg = 'Instance disappeared before build.'
            LOG.debug(msg, instance=instance)
            return build_results.FAILED
        except exception.UnexpectedTaskStateError as e:
            LOG.debug(e.format_message(), instance=instance)
            return build_results.FAILED

        # b64 decode the files to inject:
        decoded_files = self._decode_files(injected_files)

        if limits is None:
            limits = {}

        if node is None:
            node = self._get_nodename(instance, refresh=True)

        try:
            with timeutils.StopWatch() as timer:
                self._build_and_run_instance(context, instance, image,
                        decoded_files, admin_password, requested_networks,
                        security_groups, block_device_mapping, node, limits,
                        filter_properties, request_spec)
            LOG.info('Took %0.2f seconds to build instance.',
                     timer.elapsed(), instance=instance)
            return build_results.ACTIVE
        except exception.RescheduledException as e:
            retry = filter_properties.get('retry')
            if not retry:
                # no retry information, do not reschedule.
                LOG.debug("Retry info not present, will not reschedule",
                    instance=instance)
                self._cleanup_allocated_networks(context, instance,
                    requested_networks)
                self._cleanup_volumes(context, instance,
                    block_device_mapping, raise_exc=False)
                compute_utils.add_instance_fault_from_exc(context,
                        instance, e, sys.exc_info(),
                        fault_message=e.kwargs['reason'])
                self._nil_out_instance_obj_host_and_node(instance)
                self._set_instance_obj_error_state(context, instance,
                                                   clean_task_state=True)
                return build_results.FAILED
            LOG.debug(e.format_message(), instance=instance)
            # This will be used for logging the exception
            retry['exc'] = traceback.format_exception(*sys.exc_info())
            # This will be used for setting the instance fault message
            retry['exc_reason'] = e.kwargs['reason']
            # NOTE(comstud): Deallocate networks if the driver wants
            # us to do so.
            # NOTE(mriedem): Always deallocate networking when using Neutron.
            # This is to unbind any ports that the user supplied in the server
            # create request, or delete any ports that nova created which were
            # meant to be bound to this host. This check intentionally bypasses
            # the result of deallocate_networks_on_reschedule because the
            # default value in the driver is False, but that method was really
            # only meant for Ironic and should be removed when nova-network is
            # removed (since is_neutron() will then always be True).
            # NOTE(vladikr): SR-IOV ports should be deallocated to
            # allow new sriov pci devices to be allocated on a new host.
            # Otherwise, if devices with pci addresses are already allocated
            # on the destination host, the instance will fail to spawn.
            # info_cache.network_info should be present at this stage.
            if (self.driver.deallocate_networks_on_reschedule(instance) or
                utils.is_neutron() or
                self.deallocate_sriov_ports_on_reschedule(instance)):
                self._cleanup_allocated_networks(context, instance,
                        requested_networks)
            else:
                # NOTE(alex_xu): Network already allocated and we don't
                # want to deallocate them before rescheduling. But we need
                # to cleanup those network resources setup on this host before
                # rescheduling.
                self.network_api.cleanup_instance_network_on_host(
                    context, instance, self.host)

            self._nil_out_instance_obj_host_and_node(instance)
            instance.task_state = task_states.SCHEDULING
            instance.save()
            # The instance will have already claimed resources from this host
            # before this build was attempted. Now that it has failed, we need
            # to unclaim those resources before casting to the conductor, so
            # that if there are alternate hosts available for a retry, it can
            # claim resources on that new host for the instance.
            self._delete_allocation_for_instance(context, instance.uuid)

            self.compute_task_api.build_instances(context, [instance],
                    image, filter_properties, admin_password,
                    injected_files, requested_networks, security_groups,
                    block_device_mapping, request_spec=request_spec,
                    host_lists=[host_list])
            return build_results.RESCHEDULED
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            msg = 'Instance disappeared during build.'
            LOG.debug(msg, instance=instance)
            self._cleanup_allocated_networks(context, instance,
                    requested_networks)
            return build_results.FAILED
        except exception.BuildAbortException as e:
            LOG.error(e.format_message(), instance=instance)
            self._cleanup_allocated_networks(context, instance,
                    requested_networks)
            self._cleanup_volumes(context, instance,
                    block_device_mapping, raise_exc=False)
            compute_utils.add_instance_fault_from_exc(context, instance,
                    e, sys.exc_info())
            self._nil_out_instance_obj_host_and_node(instance)
            self._set_instance_obj_error_state(context, instance,
                                               clean_task_state=True)
            return build_results.FAILED
        except Exception as e:
            # Should not reach here.
            LOG.exception('Unexpected build failure, not rescheduling build.',
                          instance=instance)
            self._cleanup_allocated_networks(context, instance,
                    requested_networks)
            self._cleanup_volumes(context, instance,
                    block_device_mapping, raise_exc=False)
            compute_utils.add_instance_fault_from_exc(context, instance,
                    e, sys.exc_info())
            self._nil_out_instance_obj_host_and_node(instance)
            self._set_instance_obj_error_state(context, instance,
                                               clean_task_state=True)
            return build_results.FAILED

    def deallocate_sriov_ports_on_reschedule(self, instance):
        """Determine if networks are needed to be deallocated before reschedule

        Check the cached network info for any assigned SR-IOV ports.
        SR-IOV ports should be deallocated prior to rescheduling
        in order to allow new sriov pci devices to be allocated on a new host.
        """
        info_cache = instance.info_cache

        def _has_sriov_port(vif):
            return vif['vnic_type'] in network_model.VNIC_TYPES_SRIOV

        if (info_cache and info_cache.network_info):
            for vif in info_cache.network_info:
                if _has_sriov_port(vif):
                    return True
        return False

    @staticmethod
    def _get_scheduler_hints(filter_properties, request_spec=None):
        """Helper method to get scheduler hints.

        This method prefers to get the hints out of the request spec, but that
        might not be provided. Conductor will pass request_spec down to the
        first compute chosen for a build but older computes will not pass
        the request_spec to conductor's build_instances method for a
        a reschedule, so if we're on a host via a retry, request_spec may not
        be provided so we need to fallback to use the filter_properties
        to get scheduler hints.
        """
        hints = {}
        if request_spec is not None and 'scheduler_hints' in request_spec:
            hints = request_spec.scheduler_hints
        if not hints:
            hints = filter_properties.get('scheduler_hints') or {}
        return hints

    def _build_and_run_instance(self, context, instance, image, injected_files,
            admin_password, requested_networks, security_groups,
            block_device_mapping, node, limits, filter_properties,
            request_spec=None):

        image_name = image.get('name')
        self._notify_about_instance_usage(context, instance, 'create.start',
                extra_usage_info={'image_name': image_name})
        compute_utils.notify_about_instance_create(
            context, instance, self.host,
            phase=fields.NotificationPhase.START,
            bdms=block_device_mapping)

        # NOTE(mikal): cache the keystone roles associated with the instance
        # at boot time for later reference
        instance.system_metadata.update(
            {'boot_roles': ','.join(context.roles)})

        self._check_device_tagging(requested_networks, block_device_mapping)
        self._check_trusted_certs(instance)

        try:
            scheduler_hints = self._get_scheduler_hints(filter_properties,
                                                        request_spec)
            rt = self._get_resource_tracker()
            with rt.instance_claim(context, instance, node, limits):
                # NOTE(russellb) It's important that this validation be done
                # *after* the resource tracker instance claim, as that is where
                # the host is set on the instance.
                self._validate_instance_group_policy(context, instance,
                                                     scheduler_hints)
                image_meta = objects.ImageMeta.from_dict(image)
                with self._build_resources(context, instance,
                        requested_networks, security_groups, image_meta,
                        block_device_mapping) as resources:
                    instance.vm_state = vm_states.BUILDING
                    instance.task_state = task_states.SPAWNING
                    # NOTE(JoshNang) This also saves the changes to the
                    # instance from _allocate_network_async, as they aren't
                    # saved in that function to prevent races.
                    instance.save(expected_task_state=
                            task_states.BLOCK_DEVICE_MAPPING)
                    block_device_info = resources['block_device_info']
                    network_info = resources['network_info']
                    allocs = resources['allocations']
                    LOG.debug('Start spawning the instance on the hypervisor.',
                              instance=instance)
                    with timeutils.StopWatch() as timer:
                        self.driver.spawn(context, instance, image_meta,
                                          injected_files, admin_password,
                                          allocs, network_info=network_info,
                                          block_device_info=block_device_info)
                    LOG.info('Took %0.2f seconds to spawn the instance on '
                             'the hypervisor.', timer.elapsed(),
                             instance=instance)
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError) as e:
            with excutils.save_and_reraise_exception():
                self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
                tb = traceback.format_exc()
                compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)
        except exception.ComputeResourcesUnavailable as e:
            LOG.debug(e.format_message(), instance=instance)
            self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
            tb = traceback.format_exc()
            compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)
            raise exception.RescheduledException(
                    instance_uuid=instance.uuid, reason=e.format_message())
        except exception.BuildAbortException as e:
            with excutils.save_and_reraise_exception():
                LOG.debug(e.format_message(), instance=instance)
                self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
                tb = traceback.format_exc()
                compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)
        except (exception.FixedIpLimitExceeded,
                exception.NoMoreNetworks, exception.NoMoreFixedIps) as e:
            LOG.warning('No more network or fixed IP to be allocated',
                        instance=instance)
            self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
            tb = traceback.format_exc()
            compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)
            msg = _('Failed to allocate the network(s) with error %s, '
                    'not rescheduling.') % e.format_message()
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                    reason=msg)
        except (exception.VirtualInterfaceCreateException,
                exception.VirtualInterfaceMacAddressException,
                exception.FixedIpInvalidOnHost,
                exception.UnableToAutoAllocateNetwork) as e:
            LOG.exception('Failed to allocate network(s)',
                          instance=instance)
            self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
            tb = traceback.format_exc()
            compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)
            msg = _('Failed to allocate the network(s), not rescheduling.')
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                    reason=msg)
        except (exception.FlavorDiskTooSmall,
                exception.FlavorMemoryTooSmall,
                exception.ImageNotActive,
                exception.ImageUnacceptable,
                exception.InvalidDiskInfo,
                exception.InvalidDiskFormat,
                cursive_exception.SignatureVerificationError,
                exception.CertificateValidationFailed,
                exception.VolumeEncryptionNotSupported,
                exception.InvalidInput,
                # TODO(mriedem): We should be validating RequestedVRamTooHigh
                # in the API during server create and rebuild.
                exception.RequestedVRamTooHigh) as e:
            self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
            tb = traceback.format_exc()
            compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                    reason=e.format_message())
        except Exception as e:
            self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
            tb = traceback.format_exc()
            compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)
            raise exception.RescheduledException(
                    instance_uuid=instance.uuid, reason=six.text_type(e))

        # NOTE(alaski): This is only useful during reschedules, remove it now.
        instance.system_metadata.pop('network_allocated', None)

        # If CONF.default_access_ip_network_name is set, grab the
        # corresponding network and set the access ip values accordingly.
        network_name = CONF.default_access_ip_network_name
        if (network_name and not instance.access_ip_v4 and
                not instance.access_ip_v6):
            # Note that when there are multiple ips to choose from, an
            # arbitrary one will be chosen.
            for vif in network_info:
                if vif['network']['label'] == network_name:
                    for ip in vif.fixed_ips():
                        if not instance.access_ip_v4 and ip['version'] == 4:
                            instance.access_ip_v4 = ip['address']
                        if not instance.access_ip_v6 and ip['version'] == 6:
                            instance.access_ip_v6 = ip['address']
                    break

        self._update_instance_after_spawn(context, instance)

        try:
            instance.save(expected_task_state=task_states.SPAWNING)
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError) as e:
            with excutils.save_and_reraise_exception():
                self._notify_about_instance_usage(context, instance,
                    'create.error', fault=e)
                tb = traceback.format_exc()
                compute_utils.notify_about_instance_create(
                    context, instance, self.host,
                    phase=fields.NotificationPhase.ERROR, exception=e,
                    bdms=block_device_mapping, tb=tb)

        self._update_scheduler_instance_info(context, instance)
        self._notify_about_instance_usage(context, instance, 'create.end',
                extra_usage_info={'message': _('Success')},
                network_info=network_info)
        compute_utils.notify_about_instance_create(context, instance,
                self.host, phase=fields.NotificationPhase.END,
                bdms=block_device_mapping)

    @contextlib.contextmanager
    def _build_resources(self, context, instance, requested_networks,
                         security_groups, image_meta, block_device_mapping):
        resources = {}
        network_info = None
        try:
            LOG.debug('Start building networks asynchronously for instance.',
                      instance=instance)
            network_info = self._build_networks_for_instance(context, instance,
                    requested_networks, security_groups)
            resources['network_info'] = network_info
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            raise
        except exception.UnexpectedTaskStateError as e:
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                    reason=e.format_message())
        except Exception:
            # Because this allocation is async any failures are likely to occur
            # when the driver accesses network_info during spawn().
            LOG.exception('Failed to allocate network(s)',
                          instance=instance)
            msg = _('Failed to allocate the network(s), not rescheduling.')
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                    reason=msg)

        try:
            # Perform any driver preparation work for the driver.
            self.driver.prepare_for_spawn(instance)

            # Depending on a virt driver, some network configuration is
            # necessary before preparing block devices.
            self.driver.prepare_networks_before_block_device_mapping(
                instance, network_info)

            # Verify that all the BDMs have a device_name set and assign a
            # default to the ones missing it with the help of the driver.
            self._default_block_device_names(instance, image_meta,
                                             block_device_mapping)

            LOG.debug('Start building block device mappings for instance.',
                      instance=instance)
            instance.vm_state = vm_states.BUILDING
            instance.task_state = task_states.BLOCK_DEVICE_MAPPING
            instance.save()

            block_device_info = self._prep_block_device(context, instance,
                    block_device_mapping)
            resources['block_device_info'] = block_device_info
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            with excutils.save_and_reraise_exception():
                # Make sure the async call finishes
                if network_info is not None:
                    network_info.wait(do_raise=False)
                    self.driver.clean_networks_preparation(instance,
                                                           network_info)
                self.driver.failed_spawn_cleanup(instance)
        except (exception.UnexpectedTaskStateError,
                exception.OverQuota, exception.InvalidBDM) as e:
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
                self.driver.clean_networks_preparation(instance, network_info)
            self.driver.failed_spawn_cleanup(instance)
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                    reason=e.format_message())
        except Exception:
            LOG.exception('Failure prepping block device',
                          instance=instance)
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
                self.driver.clean_networks_preparation(instance, network_info)
            self.driver.failed_spawn_cleanup(instance)
            msg = _('Failure prepping block device.')
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                    reason=msg)

        try:
            resources['allocations'] = (
                self.reportclient.get_allocations_for_consumer(context,
                                                               instance.uuid))
        except Exception:
            LOG.exception('Failure retrieving placement allocations',
                          instance=instance)
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            self.driver.failed_spawn_cleanup(instance)
            msg = _('Failure retrieving placement allocations')
            raise exception.BuildAbortException(instance_uuid=instance.uuid,
                                                reason=msg)

        try:
            yield resources
        except Exception as exc:
            with excutils.save_and_reraise_exception() as ctxt:
                if not isinstance(exc, (
                        exception.InstanceNotFound,
                        exception.UnexpectedDeletingTaskStateError)):
                    LOG.exception('Instance failed to spawn',
                                  instance=instance)
                # Make sure the async call finishes
                if network_info is not None:
                    network_info.wait(do_raise=False)
                # if network_info is empty we're likely here because of
                # network allocation failure. Since nothing can be reused on
                # rescheduling it's better to deallocate network to eliminate
                # the chance of orphaned ports in neutron
                deallocate_networks = False if network_info else True
                try:
                    self._shutdown_instance(context, instance,
                            block_device_mapping, requested_networks,
                            try_deallocate_networks=deallocate_networks)
                except Exception as exc2:
                    ctxt.reraise = False
                    LOG.warning('Could not clean up failed build,'
                                ' not rescheduling. Error: %s',
                                six.text_type(exc2))
                    raise exception.BuildAbortException(
                            instance_uuid=instance.uuid,
                            reason=six.text_type(exc))

    def _cleanup_allocated_networks(self, context, instance,
            requested_networks):
        try:
            self._deallocate_network(context, instance, requested_networks)
        except Exception:
            LOG.exception('Failed to deallocate networks', instance=instance)
            return

        instance.system_metadata['network_allocated'] = 'False'
        try:
            instance.save()
        except exception.InstanceNotFound:
            # NOTE(alaski): It's possible that we're cleaning up the networks
            # because the instance was deleted.  If that's the case then this
            # exception will be raised by instance.save()
            pass

    def _try_deallocate_network(self, context, instance,
                                requested_networks=None):

        # During auto-scale cleanup, we could be deleting a large number
        # of servers at the same time and overloading parts of the system,
        # so we retry a few times in case of connection failures to the
        # networking service.
        @loopingcall.RetryDecorator(
            max_retry_count=3, inc_sleep_time=2, max_sleep_time=12,
            exceptions=(keystone_exception.connection.ConnectFailure,))
        def _deallocate_network_with_retries():
            try:
                self._deallocate_network(
                    context, instance, requested_networks)
            except keystone_exception.connection.ConnectFailure as e:
                # Provide a warning that something is amiss.
                with excutils.save_and_reraise_exception():
                    LOG.warning('Failed to deallocate network for instance; '
                                'retrying. Error: %s', six.text_type(e),
                                instance=instance)

        try:
            # tear down allocated network structure
            _deallocate_network_with_retries()
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to deallocate network for instance. '
                          'Error: %s', ex, instance=instance)
                self._set_instance_obj_error_state(context, instance)

    def _get_power_off_values(self, context, instance, clean_shutdown):
        """Get the timing configuration for powering down this instance."""
        if clean_shutdown:
            timeout = compute_utils.get_value_from_system_metadata(instance,
                          key='image_os_shutdown_timeout', type=int,
                          default=CONF.shutdown_timeout)
            retry_interval = CONF.compute.shutdown_retry_interval
        else:
            timeout = 0
            retry_interval = 0

        return timeout, retry_interval

    def _power_off_instance(self, context, instance, clean_shutdown=True):
        """Power off an instance on this host."""
        timeout, retry_interval = self._get_power_off_values(context,
                                        instance, clean_shutdown)
        self.driver.power_off(instance, timeout, retry_interval)

    def _shutdown_instance(self, context, instance,
                           bdms, requested_networks=None, notify=True,
                           try_deallocate_networks=True):
        """Shutdown an instance on this host.

        :param:context: security context
        :param:instance: a nova.objects.Instance object
        :param:bdms: the block devices for the instance to be torn
                     down
        :param:requested_networks: the networks on which the instance
                                   has ports
        :param:notify: true if a final usage notification should be
                       emitted
        :param:try_deallocate_networks: false if we should avoid
                                        trying to teardown networking
        """
        context = context.elevated()
        LOG.info('Terminating instance', instance=instance)

        if notify:
            self._notify_about_instance_usage(context, instance,
                                              "shutdown.start")
            compute_utils.notify_about_instance_action(context, instance,
                    self.host, action=fields.NotificationAction.SHUTDOWN,
                    phase=fields.NotificationPhase.START, bdms=bdms)

        network_info = instance.get_network_info()

        # NOTE(vish) get bdms before destroying the instance
        vol_bdms = [bdm for bdm in bdms if bdm.is_volume]
        block_device_info = self._get_instance_block_device_info(
            context, instance, bdms=bdms)

        # NOTE(melwitt): attempt driver destroy before releasing ip, may
        #                want to keep ip allocated for certain failures
        try:
            LOG.debug('Start destroying the instance on the hypervisor.',
                      instance=instance)
            with timeutils.StopWatch() as timer:
                self.driver.destroy(context, instance, network_info,
                                    block_device_info)
            LOG.info('Took %0.2f seconds to destroy the instance on the '
                     'hypervisor.', timer.elapsed(), instance=instance)
        except exception.InstancePowerOffFailure:
            # if the instance can't power off, don't release the ip
            with excutils.save_and_reraise_exception():
                pass
        except Exception:
            with excutils.save_and_reraise_exception():
                # deallocate ip and fail without proceeding to
                # volume api calls, preserving current behavior
                if try_deallocate_networks:
                    self._try_deallocate_network(context, instance,
                                                 requested_networks)

        if try_deallocate_networks:
            self._try_deallocate_network(context, instance, requested_networks)

        timer.restart()
        for bdm in vol_bdms:
            try:
                if bdm.attachment_id:
                    self.volume_api.attachment_delete(context,
                                                      bdm.attachment_id)
                else:
                    # NOTE(vish): actual driver detach done in driver.destroy,
                    #             so just tell cinder that we are done with it.
                    connector = self.driver.get_volume_connector(instance)
                    self.volume_api.terminate_connection(context,
                                                         bdm.volume_id,
                                                         connector)
                    self.volume_api.detach(context, bdm.volume_id,
                                           instance.uuid)

            except exception.VolumeAttachmentNotFound as exc:
                LOG.debug('Ignoring VolumeAttachmentNotFound: %s', exc,
                          instance=instance)
            except exception.DiskNotFound as exc:
                LOG.debug('Ignoring DiskNotFound: %s', exc,
                          instance=instance)
            except exception.VolumeNotFound as exc:
                LOG.debug('Ignoring VolumeNotFound: %s', exc,
                          instance=instance)
            except (cinder_exception.EndpointNotFound,
                    keystone_exception.EndpointNotFound) as exc:
                LOG.warning('Ignoring EndpointNotFound for '
                            'volume %(volume_id)s: %(exc)s',
                            {'exc': exc, 'volume_id': bdm.volume_id},
                            instance=instance)
            except cinder_exception.ClientException as exc:
                LOG.warning('Ignoring unknown cinder exception for '
                            'volume %(volume_id)s: %(exc)s',
                            {'exc': exc, 'volume_id': bdm.volume_id},
                            instance=instance)
            except Exception as exc:
                LOG.warning('Ignoring unknown exception for '
                            'volume %(volume_id)s: %(exc)s',
                            {'exc': exc, 'volume_id': bdm.volume_id},
                            instance=instance)
        if vol_bdms:
            LOG.info('Took %(time).2f seconds to detach %(num)s volumes '
                     'for instance.',
                     {'time': timer.elapsed(), 'num': len(vol_bdms)},
                     instance=instance)

        if notify:
            self._notify_about_instance_usage(context, instance,
                                              "shutdown.end")
            compute_utils.notify_about_instance_action(context, instance,
                    self.host, action=fields.NotificationAction.SHUTDOWN,
                    phase=fields.NotificationPhase.END, bdms=bdms)

    def _cleanup_volumes(self, context, instance, bdms, raise_exc=True,
                         detach=True):
        exc_info = None
        for bdm in bdms:
            if detach and bdm.volume_id:
                try:
                    LOG.debug("Detaching volume: %s", bdm.volume_id,
                              instance_uuid=instance.uuid)
                    destroy = bdm.delete_on_termination
                    self._detach_volume(context, bdm, instance,
                                        destroy_bdm=destroy)
                except Exception as exc:
                    exc_info = sys.exc_info()
                    LOG.warning('Failed to detach volume: %(volume_id)s '
                                'due to %(exc)s',
                                {'volume_id': bdm.volume_id, 'exc': exc})

            if bdm.volume_id and bdm.delete_on_termination:
                try:
                    LOG.debug("Deleting volume: %s", bdm.volume_id,
                              instance_uuid=instance.uuid)
                    self.volume_api.delete(context, bdm.volume_id)
                except Exception as exc:
                    exc_info = sys.exc_info()
                    LOG.warning('Failed to delete volume: %(volume_id)s '
                                'due to %(exc)s',
                                {'volume_id': bdm.volume_id, 'exc': exc})
        if exc_info is not None and raise_exc:
            six.reraise(exc_info[0], exc_info[1], exc_info[2])

    @hooks.add_hook("delete_instance")
    def _delete_instance(self, context, instance, bdms):
        """Delete an instance on this host.

        :param context: nova request context
        :param instance: nova.objects.instance.Instance object
        :param bdms: nova.objects.block_device.BlockDeviceMappingList object
        """
        events = self.instance_events.clear_events_for_instance(instance)
        if events:
            LOG.debug('Events pending at deletion: %(events)s',
                      {'events': ','.join(events.keys())},
                      instance=instance)
        self._notify_about_instance_usage(context, instance,
                                          "delete.start")
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.DELETE,
                phase=fields.NotificationPhase.START, bdms=bdms)

        self._shutdown_instance(context, instance, bdms)

        # NOTE(vish): We have already deleted the instance, so we have
        #             to ignore problems cleaning up the volumes. It
        #             would be nice to let the user know somehow that
        #             the volume deletion failed, but it is not
        #             acceptable to have an instance that can not be
        #             deleted. Perhaps this could be reworked in the
        #             future to set an instance fault the first time
        #             and to only ignore the failure if the instance
        #             is already in ERROR.

        # NOTE(ameeda): The volumes already detached during the above
        #               _shutdown_instance() call and this is why
        #               detach is not requested from _cleanup_volumes()
        #               in this case

        self._cleanup_volumes(context, instance, bdms,
                raise_exc=False, detach=False)
        # if a delete task succeeded, always update vm state and task
        # state without expecting task state to be DELETING
        instance.vm_state = vm_states.DELETED
        instance.task_state = None
        instance.power_state = power_state.NOSTATE
        instance.terminated_at = timeutils.utcnow()
        instance.save()
        instance.destroy()

        self._complete_deletion(context,
                                instance,
                                bdms)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def terminate_instance(self, context, instance, bdms):
        """Terminate an instance on this host."""
        @utils.synchronized(instance.uuid)
        def do_terminate_instance(instance, bdms):
            # NOTE(mriedem): If we are deleting the instance while it was
            # booting from volume, we could be racing with a database update of
            # the BDM volume_id. Since the compute API passes the BDMs over RPC
            # to compute here, the BDMs may be stale at this point. So check
            # for any volume BDMs that don't have volume_id set and if we
            # detect that, we need to refresh the BDM list before proceeding.
            # TODO(mriedem): Move this into _delete_instance and make the bdms
            # parameter optional.
            for bdm in list(bdms):
                if bdm.is_volume and not bdm.volume_id:
                    LOG.debug('There are potentially stale BDMs during '
                              'delete, refreshing the BlockDeviceMappingList.',
                              instance=instance)
                    bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                        context, instance.uuid)
                    break
            try:
                self._delete_instance(context, instance, bdms)
            except exception.InstanceNotFound:
                LOG.info("Instance disappeared during terminate",
                         instance=instance)
            except Exception:
                # As we're trying to delete always go to Error if something
                # goes wrong that _delete_instance can't handle.
                with excutils.save_and_reraise_exception():
                    LOG.exception('Setting instance vm_state to ERROR',
                                  instance=instance)
                    self._set_instance_obj_error_state(context, instance)

        do_terminate_instance(instance, bdms)

    # NOTE(johannes): This is probably better named power_off_instance
    # so it matches the driver method, but because of other issues, we
    # can't use that name in grizzly.
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def stop_instance(self, context, instance, clean_shutdown):
        """Stopping an instance on this host."""

        @utils.synchronized(instance.uuid)
        def do_stop_instance():
            current_power_state = self._get_power_state(context, instance)
            LOG.debug('Stopping instance; current vm_state: %(vm_state)s, '
                      'current task_state: %(task_state)s, current DB '
                      'power_state: %(db_power_state)s, current VM '
                      'power_state: %(current_power_state)s',
                      {'vm_state': instance.vm_state,
                       'task_state': instance.task_state,
                       'db_power_state': instance.power_state,
                       'current_power_state': current_power_state},
                      instance_uuid=instance.uuid)

            # NOTE(mriedem): If the instance is already powered off, we are
            # possibly tearing down and racing with other operations, so we can
            # expect the task_state to be None if something else updates the
            # instance and we're not locking it.
            expected_task_state = [task_states.POWERING_OFF]
            # The list of power states is from _sync_instance_power_state.
            if current_power_state in (power_state.NOSTATE,
                                       power_state.SHUTDOWN,
                                       power_state.CRASHED):
                LOG.info('Instance is already powered off in the '
                         'hypervisor when stop is called.',
                         instance=instance)
                expected_task_state.append(None)

            self._notify_about_instance_usage(context, instance,
                                              "power_off.start")

            compute_utils.notify_about_instance_action(context, instance,
                        self.host, action=fields.NotificationAction.POWER_OFF,
                        phase=fields.NotificationPhase.START)

            self._power_off_instance(context, instance, clean_shutdown)
            instance.power_state = self._get_power_state(context, instance)
            instance.vm_state = vm_states.STOPPED
            instance.task_state = None
            instance.save(expected_task_state=expected_task_state)
            self._notify_about_instance_usage(context, instance,
                                              "power_off.end")

            compute_utils.notify_about_instance_action(context, instance,
                        self.host, action=fields.NotificationAction.POWER_OFF,
                        phase=fields.NotificationPhase.END)

        do_stop_instance()

    def _power_on(self, context, instance):
        network_info = self.network_api.get_instance_nw_info(context, instance)
        block_device_info = self._get_instance_block_device_info(context,
                                                                 instance)
        self.driver.power_on(context, instance,
                             network_info,
                             block_device_info)

    def _delete_snapshot_of_shelved_instance(self, context, instance,
                                             snapshot_id):
        """Delete snapshot of shelved instance."""
        try:
            self.image_api.delete(context, snapshot_id)
        except (exception.ImageNotFound,
                exception.ImageNotAuthorized) as exc:
            LOG.warning("Failed to delete snapshot "
                        "from shelved instance (%s).",
                        exc.format_message(), instance=instance)
        except Exception:
            LOG.exception("Something wrong happened when trying to "
                          "delete snapshot from shelved instance.",
                          instance=instance)

    # NOTE(johannes): This is probably better named power_on_instance
    # so it matches the driver method, but because of other issues, we
    # can't use that name in grizzly.
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def start_instance(self, context, instance):
        """Starting an instance on this host."""
        self._notify_about_instance_usage(context, instance, "power_on.start")
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.POWER_ON,
            phase=fields.NotificationPhase.START)
        self._power_on(context, instance)
        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None

        # Delete an image(VM snapshot) for a shelved instance
        snapshot_id = instance.system_metadata.get('shelved_image_id')
        if snapshot_id:
            self._delete_snapshot_of_shelved_instance(context, instance,
                                                      snapshot_id)

        # Delete system_metadata for a shelved instance
        compute_utils.remove_shelved_keys_from_system_metadata(instance)

        instance.save(expected_task_state=task_states.POWERING_ON)
        self._notify_about_instance_usage(context, instance, "power_on.end")
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.POWER_ON,
            phase=fields.NotificationPhase.END)

    @messaging.expected_exceptions(NotImplementedError,
                                   exception.TriggerCrashDumpNotSupported,
                                   exception.InstanceNotRunning)
    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def trigger_crash_dump(self, context, instance):
        """Trigger crash dump in an instance."""

        self._notify_about_instance_usage(context, instance,
                                          "trigger_crash_dump.start")
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.TRIGGER_CRASH_DUMP,
                phase=fields.NotificationPhase.START)

        # This method does not change task_state and power_state because the
        # effect of a trigger depends on user's configuration.
        self.driver.trigger_crash_dump(instance)

        self._notify_about_instance_usage(context, instance,
                                          "trigger_crash_dump.end")
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.TRIGGER_CRASH_DUMP,
                phase=fields.NotificationPhase.END)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def soft_delete_instance(self, context, instance):
        """Soft delete an instance on this host."""
        with compute_utils.notify_about_instance_delete(
                self.notifier, context, instance, 'soft_delete'):
            compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.SOFT_DELETE,
                phase=fields.NotificationPhase.START)
            try:
                self.driver.soft_delete(instance)
            except NotImplementedError:
                # Fallback to just powering off the instance if the
                # hypervisor doesn't implement the soft_delete method
                self.driver.power_off(instance)
            instance.power_state = self._get_power_state(context, instance)
            instance.vm_state = vm_states.SOFT_DELETED
            instance.task_state = None
            instance.save(expected_task_state=[task_states.SOFT_DELETING])
            compute_utils.notify_about_instance_action(
                context, instance, self.host,
                action=fields.NotificationAction.SOFT_DELETE,
                phase=fields.NotificationPhase.END)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def restore_instance(self, context, instance):
        """Restore a soft-deleted instance on this host."""
        self._notify_about_instance_usage(context, instance, "restore.start")
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.RESTORE,
            phase=fields.NotificationPhase.START)
        try:
            self.driver.restore(instance)
        except NotImplementedError:
            # Fallback to just powering on the instance if the hypervisor
            # doesn't implement the restore method
            self._power_on(context, instance)
        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.save(expected_task_state=task_states.RESTORING)
        self._notify_about_instance_usage(context, instance, "restore.end")
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.RESTORE,
            phase=fields.NotificationPhase.END)

    @staticmethod
    def _set_migration_status(migration, status):
        """Set the status, and guard against a None being passed in.

        This is useful as some of the compute RPC calls will not pass
        a migration object in older versions. The check can be removed when
        we move past 4.x major version of the RPC API.
        """
        if migration:
            migration.status = status
            migration.save()

    def _rebuild_default_impl(self, context, instance, image_meta,
                              injected_files, admin_password, allocations,
                              bdms, detach_block_devices, attach_block_devices,
                              network_info=None,
                              evacuate=False, block_device_info=None,
                              preserve_ephemeral=False):
        if preserve_ephemeral:
            # The default code path does not support preserving ephemeral
            # partitions.
            raise exception.PreserveEphemeralNotSupported()

        if evacuate:
            detach_block_devices(context, bdms)
        else:
            self._power_off_instance(context, instance, clean_shutdown=True)
            detach_block_devices(context, bdms)
            self.driver.destroy(context, instance,
                                network_info=network_info,
                                block_device_info=block_device_info)

        instance.task_state = task_states.REBUILD_BLOCK_DEVICE_MAPPING
        instance.save(expected_task_state=[task_states.REBUILDING])

        new_block_device_info = attach_block_devices(context, instance, bdms)

        instance.task_state = task_states.REBUILD_SPAWNING
        instance.save(
            expected_task_state=[task_states.REBUILD_BLOCK_DEVICE_MAPPING])

        with instance.mutated_migration_context():
            self.driver.spawn(context, instance, image_meta, injected_files,
                              admin_password, allocations,
                              network_info=network_info,
                              block_device_info=new_block_device_info)

    def _notify_instance_rebuild_error(self, context, instance, error, bdms):
        tb = traceback.format_exc()
        self._notify_about_instance_usage(context, instance,
                                          'rebuild.error', fault=error)
        compute_utils.notify_about_instance_rebuild(
            context, instance, self.host,
            phase=fields.NotificationPhase.ERROR, exception=error, bdms=bdms,
            tb=tb)

    @messaging.expected_exceptions(exception.PreserveEphemeralNotSupported)
    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata,
                         bdms, recreate, on_shared_storage,
                         preserve_ephemeral, migration,
                         scheduled_node, limits, request_spec):
        """Destroy and re-make this instance.

        A 'rebuild' effectively purges all existing data from the system and
        remakes the VM with given 'metadata' and 'personalities'.

        :param context: `nova.RequestContext` object
        :param instance: Instance object
        :param orig_image_ref: Original image_ref before rebuild
        :param image_ref: New image_ref for rebuild
        :param injected_files: Files to inject
        :param new_pass: password to set on rebuilt instance
        :param orig_sys_metadata: instance system metadata from pre-rebuild
        :param bdms: block-device-mappings to use for rebuild
        :param recreate: True if the instance is being recreated (e.g. the
            hypervisor it was on failed) - cleanup of old state will be
            skipped.
        :param on_shared_storage: True if instance files on shared storage.
                                  If not provided then information from the
                                  driver will be used to decide if the instance
                                  files are available or not on the target host
        :param preserve_ephemeral: True if the default ephemeral storage
                                   partition must be preserved on rebuild
        :param migration: a Migration object if one was created for this
                          rebuild operation (if it's a part of evacuate)
        :param scheduled_node: A node of the host chosen by the scheduler. If a
                               host was specified by the user, this will be
                               None
        :param limits: Overcommit limits set by the scheduler. If a host was
                       specified by the user, this will be None
        :param request_spec: a RequestSpec object used to schedule the instance

        """
        # recreate=True means the instance is being evacuated from a failed
        # host to a new destination host (this host). The 'recreate' variable
        # name is confusing, so rename it to evacuate here at the top, which
        # is simpler than renaming a parameter in an RPC versioned method.
        evacuate = recreate
        context = context.elevated()

        if evacuate:
            LOG.info("Evacuating instance", instance=instance)
        else:
            LOG.info("Rebuilding instance", instance=instance)

        rt = self._get_resource_tracker()
        if evacuate:
            # This is an evacuation to a new host, so we need to perform a
            # resource claim.
            rebuild_claim = rt.rebuild_claim
        else:
            # This is a rebuild to the same host, so we don't need to make
            # a claim since the instance is already on this host.
            rebuild_claim = claims.NopClaim

        image_meta = {}
        if image_ref:
            image_meta = self.image_api.get(context, image_ref)
        elif evacuate:
            # For evacuate the API does not send down the image_ref since the
            # image does not change so just get it from what was stashed in
            # the instance system_metadata when the instance was created (or
            # last rebuilt). This also works for volume-backed instances.
            image_meta = instance.image_meta

        # NOTE(mriedem): On an evacuate, we need to update
        # the instance's host and node properties to reflect it's
        # destination node for the evacuate.
        if not scheduled_node:
            if evacuate:
                try:
                    compute_node = self._get_compute_info(context, self.host)
                    scheduled_node = compute_node.hypervisor_hostname
                except exception.ComputeHostNotFound:
                    LOG.exception('Failed to get compute_info for %s',
                                  self.host)
            else:
                scheduled_node = instance.node

        with self._error_out_instance_on_exception(context, instance):
            try:
                claim_ctxt = rebuild_claim(
                    context, instance, scheduled_node,
                    limits=limits, image_meta=image_meta,
                    migration=migration)
                self._do_rebuild_instance_with_claim(
                    claim_ctxt, context, instance, orig_image_ref,
                    image_ref, injected_files, new_pass, orig_sys_metadata,
                    bdms, evacuate, on_shared_storage, preserve_ephemeral,
                    migration, request_spec)
            except (exception.ComputeResourcesUnavailable,
                    exception.RescheduledException) as e:
                if isinstance(e, exception.ComputeResourcesUnavailable):
                    LOG.debug("Could not rebuild instance on this host, not "
                              "enough resources available.", instance=instance)
                else:
                    # RescheduledException is raised by the late server group
                    # policy check during evacuation if a parallel scheduling
                    # violated the policy.
                    # We catch the RescheduledException here but we don't have
                    # the plumbing to do an actual reschedule so we abort the
                    # operation.
                    LOG.debug("Could not rebuild instance on this host, "
                              "late server group check failed.",
                              instance=instance)
                # NOTE(ndipanov): We just abort the build for now and leave a
                # migration record for potential cleanup later
                self._set_migration_status(migration, 'failed')
                # Since the claim failed, we need to remove the allocation
                # created against the destination node. Note that we can only
                # get here when evacuating to a destination node. Rebuilding
                # on the same host (not evacuate) uses the NopClaim which will
                # not raise ComputeResourcesUnavailable.
                rt.delete_allocation_for_evacuated_instance(
                    context, instance, scheduled_node, node_type='destination')
                self._notify_instance_rebuild_error(context, instance, e, bdms)
                raise exception.BuildAbortException(
                    instance_uuid=instance.uuid, reason=e.format_message())
            except (exception.InstanceNotFound,
                    exception.UnexpectedDeletingTaskStateError) as e:
                LOG.debug('Instance was deleted while rebuilding',
                          instance=instance)
                self._set_migration_status(migration, 'failed')
                self._notify_instance_rebuild_error(context, instance, e, bdms)
            except Exception as e:
                self._set_migration_status(migration, 'failed')
                if evacuate or scheduled_node is not None:
                    rt.delete_allocation_for_evacuated_instance(
                        context, instance, scheduled_node,
                        node_type='destination')
                self._notify_instance_rebuild_error(context, instance, e, bdms)
                raise
            else:
                instance.apply_migration_context()
                # NOTE (ndipanov): This save will now update the host and node
                # attributes making sure that next RT pass is consistent since
                # it will be based on the instance and not the migration DB
                # entry.
                instance.host = self.host
                instance.node = scheduled_node
                instance.save()
                instance.drop_migration_context()

                # NOTE (ndipanov): Mark the migration as done only after we
                # mark the instance as belonging to this host.
                self._set_migration_status(migration, 'done')

    def _do_rebuild_instance_with_claim(self, claim_context, *args, **kwargs):
        """Helper to avoid deep nesting in the top-level method."""

        with claim_context:
            self._do_rebuild_instance(*args, **kwargs)

    @staticmethod
    def _get_image_name(image_meta):
        if image_meta.obj_attr_is_set("name"):
            return image_meta.name
        else:
            return ''

    def _do_rebuild_instance(self, context, instance, orig_image_ref,
                             image_ref, injected_files, new_pass,
                             orig_sys_metadata, bdms, evacuate,
                             on_shared_storage, preserve_ephemeral,
                             migration, request_spec):
        orig_vm_state = instance.vm_state

        if evacuate:
            if request_spec:
                # NOTE(gibi): Do a late check of server group policy as
                # parallel scheduling could violate such policy. This will
                # cause the evacuate to fail as rebuild does not implement
                # reschedule.
                hints = self._get_scheduler_hints({}, request_spec)
                self._validate_instance_group_policy(context, instance, hints)

            if not self.driver.capabilities.get("supports_evacuate", False):
                raise exception.InstanceEvacuateNotSupported

            self._check_instance_exists(context, instance)

            if on_shared_storage is None:
                LOG.debug('on_shared_storage is not provided, using driver '
                          'information to decide if the instance needs to '
                          'be evacuated')
                on_shared_storage = self.driver.instance_on_disk(instance)

            elif (on_shared_storage !=
                    self.driver.instance_on_disk(instance)):
                # To cover case when admin expects that instance files are
                # on shared storage, but not accessible and vice versa
                raise exception.InvalidSharedStorage(
                        _("Invalid state of instance files on shared"
                            " storage"))

            if on_shared_storage:
                LOG.info('disk on shared storage, evacuating using'
                         ' existing disk')
            else:
                image_ref = orig_image_ref = instance.image_ref
                LOG.info("disk not on shared storage, evacuating from:"
                         " '%s'", str(image_ref))

        if image_ref:
            image_meta = objects.ImageMeta.from_image_ref(
                context, self.image_api, image_ref)
        else:
            image_meta = instance.image_meta

        # We check trusted certs capabilities for both evacuate (rebuild on
        # another host) and rebuild (rebuild on the same host) because for
        # evacuate we need to make sure an instance with trusted certs can
        # have the image verified with those certs during rebuild, and for
        # rebuild we could be rebuilding a server that started out with no
        # trusted certs on this host, and then was rebuilt with trusted certs
        # for a new image, in which case we need to validate that new image
        # with the trusted certs during the rebuild.
        self._check_trusted_certs(instance)

        # This instance.exists message should contain the original
        # image_ref, not the new one.  Since the DB has been updated
        # to point to the new one... we have to override it.
        orig_image_ref_url = self.image_api.generate_image_url(orig_image_ref,
                                                               context)
        extra_usage_info = {'image_ref_url': orig_image_ref_url}
        compute_utils.notify_usage_exists(
                self.notifier, context, instance, self.host,
                current_period=True, system_metadata=orig_sys_metadata,
                extra_usage_info=extra_usage_info)

        # This message should contain the new image_ref
        extra_usage_info = {'image_name': self._get_image_name(image_meta)}
        self._notify_about_instance_usage(context, instance,
                "rebuild.start", extra_usage_info=extra_usage_info)
        # NOTE: image_name is not included in the versioned notification
        # because we already provide the image_uuid in the notification
        # payload and the image details can be looked up via the uuid.
        compute_utils.notify_about_instance_rebuild(
            context, instance, self.host,
            phase=fields.NotificationPhase.START,
            bdms=bdms)

        instance.power_state = self._get_power_state(context, instance)
        instance.task_state = task_states.REBUILDING
        instance.save(expected_task_state=[task_states.REBUILDING])

        if evacuate:
            self.network_api.setup_networks_on_host(
                    context, instance, self.host)
            # For nova-network this is needed to move floating IPs
            # For neutron this updates the host in the port binding
            # TODO(cfriesen): this network_api call and the one above
            # are so similar, we should really try to unify them.
            self.network_api.setup_instance_network_on_host(
                    context, instance, self.host, migration)
            # TODO(mriedem): Consider decorating setup_instance_network_on_host
            # with @base_api.refresh_cache and then we wouldn't need this
            # explicit call to get_instance_nw_info.
            network_info = self.network_api.get_instance_nw_info(context,
                                                                 instance)
        else:
            network_info = instance.get_network_info()

        allocations = self.reportclient.get_allocations_for_consumer(
            context, instance.uuid)

        if bdms is None:
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

        block_device_info = \
            self._get_instance_block_device_info(
                    context, instance, bdms=bdms)

        def detach_block_devices(context, bdms):
            for bdm in bdms:
                if bdm.is_volume:
                    # NOTE (ildikov): Having the attachment_id set in the BDM
                    # means that it's the new Cinder attach/detach flow
                    # (available from v3.44). In that case we explicitly
                    # attach and detach the volumes through attachment level
                    # operations. In this scenario _detach_volume will delete
                    # the existing attachment which would make the volume
                    # status change to 'available' if we don't pre-create
                    # another empty attachment before deleting the old one.
                    attachment_id = None
                    if bdm.attachment_id:
                        attachment_id = self.volume_api.attachment_create(
                            context, bdm['volume_id'], instance.uuid)['id']
                    self._detach_volume(context, bdm, instance,
                                        destroy_bdm=False)
                    if attachment_id:
                        bdm.attachment_id = attachment_id
                        bdm.save()

        files = self._decode_files(injected_files)

        kwargs = dict(
            context=context,
            instance=instance,
            image_meta=image_meta,
            injected_files=files,
            admin_password=new_pass,
            allocations=allocations,
            bdms=bdms,
            detach_block_devices=detach_block_devices,
            attach_block_devices=self._prep_block_device,
            block_device_info=block_device_info,
            network_info=network_info,
            preserve_ephemeral=preserve_ephemeral,
            evacuate=evacuate)
        try:
            with instance.mutated_migration_context():
                self.driver.rebuild(**kwargs)
        except NotImplementedError:
            # NOTE(rpodolyaka): driver doesn't provide specialized version
            # of rebuild, fall back to the default implementation
            self._rebuild_default_impl(**kwargs)
        self._update_instance_after_spawn(context, instance)
        instance.save(expected_task_state=[task_states.REBUILD_SPAWNING])

        if orig_vm_state == vm_states.STOPPED:
            LOG.info("bringing vm to original state: '%s'",
                     orig_vm_state, instance=instance)
            instance.vm_state = vm_states.ACTIVE
            instance.task_state = task_states.POWERING_OFF
            instance.progress = 0
            instance.save()
            self.stop_instance(context, instance, False)
        # TODO(melwitt): We should clean up instance console tokens here in the
        # case of evacuate. The instance is on a new host and will need to
        # establish a new console connection.
        self._update_scheduler_instance_info(context, instance)
        self._notify_about_instance_usage(
                context, instance, "rebuild.end",
                network_info=network_info,
                extra_usage_info=extra_usage_info)
        compute_utils.notify_about_instance_rebuild(
            context, instance, self.host,
            phase=fields.NotificationPhase.END,
            bdms=bdms)

    def _handle_bad_volumes_detached(self, context, instance, bad_devices,
                                     block_device_info):
        """Handle cases where the virt-layer had to detach non-working volumes
        in order to complete an operation.
        """
        for bdm in block_device_info['block_device_mapping']:
            if bdm.get('mount_device') in bad_devices:
                try:
                    volume_id = bdm['connection_info']['data']['volume_id']
                except KeyError:
                    continue

                # NOTE(sirp): ideally we'd just call
                # `compute_api.detach_volume` here but since that hits the
                # DB directly, that's off limits from within the
                # compute-manager.
                #
                # API-detach
                LOG.info("Detaching from volume api: %s", volume_id)
                self.volume_api.begin_detaching(context, volume_id)

                # Manager-detach
                self.detach_volume(context, volume_id, instance)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def reboot_instance(self, context, instance, block_device_info,
                        reboot_type):
        """Reboot an instance on this host."""
        # acknowledge the request made it to the manager
        if reboot_type == "SOFT":
            instance.task_state = task_states.REBOOT_PENDING
            expected_states = task_states.soft_reboot_states
        else:
            instance.task_state = task_states.REBOOT_PENDING_HARD
            expected_states = task_states.hard_reboot_states

        context = context.elevated()
        LOG.info("Rebooting instance", instance=instance)

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)
        block_device_info = self._get_instance_block_device_info(
            context, instance, bdms=bdms)

        network_info = self.network_api.get_instance_nw_info(context, instance)

        self._notify_about_instance_usage(context, instance, "reboot.start")
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.REBOOT,
            phase=fields.NotificationPhase.START,
            bdms=bdms
        )

        instance.power_state = self._get_power_state(context, instance)
        instance.save(expected_task_state=expected_states)

        if instance.power_state != power_state.RUNNING:
            state = instance.power_state
            running = power_state.RUNNING
            LOG.warning('trying to reboot a non-running instance:'
                        ' (state: %(state)s expected: %(running)s)',
                        {'state': state, 'running': running},
                        instance=instance)

        def bad_volumes_callback(bad_devices):
            self._handle_bad_volumes_detached(
                    context, instance, bad_devices, block_device_info)

        try:
            # Don't change it out of rescue mode
            if instance.vm_state == vm_states.RESCUED:
                new_vm_state = vm_states.RESCUED
            else:
                new_vm_state = vm_states.ACTIVE
            new_power_state = None
            if reboot_type == "SOFT":
                instance.task_state = task_states.REBOOT_STARTED
                expected_state = task_states.REBOOT_PENDING
            else:
                instance.task_state = task_states.REBOOT_STARTED_HARD
                expected_state = task_states.REBOOT_PENDING_HARD
            instance.save(expected_task_state=expected_state)
            self.driver.reboot(context, instance,
                               network_info,
                               reboot_type,
                               block_device_info=block_device_info,
                               bad_volumes_callback=bad_volumes_callback)

        except Exception as error:
            with excutils.save_and_reraise_exception() as ctxt:
                exc_info = sys.exc_info()
                # if the reboot failed but the VM is running don't
                # put it into an error state
                new_power_state = self._get_power_state(context, instance)
                if new_power_state == power_state.RUNNING:
                    LOG.warning('Reboot failed but instance is running',
                                instance=instance)
                    compute_utils.add_instance_fault_from_exc(context,
                            instance, error, exc_info)
                    self._notify_about_instance_usage(context, instance,
                            'reboot.error', fault=error)
                    tb = traceback.format_exc()
                    compute_utils.notify_about_instance_action(
                        context, instance, self.host,
                        action=fields.NotificationAction.REBOOT,
                        phase=fields.NotificationPhase.ERROR,
                        exception=error, bdms=bdms, tb=tb
                    )
                    ctxt.reraise = False
                else:
                    LOG.error('Cannot reboot instance: %s', error,
                              instance=instance)
                    self._set_instance_obj_error_state(context, instance)

        if not new_power_state:
            new_power_state = self._get_power_state(context, instance)
        try:
            instance.power_state = new_power_state
            instance.vm_state = new_vm_state
            instance.task_state = None
            instance.save()
        except exception.InstanceNotFound:
            LOG.warning("Instance disappeared during reboot",
                        instance=instance)

        self._notify_about_instance_usage(context, instance, "reboot.end")
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.REBOOT,
            phase=fields.NotificationPhase.END,
            bdms=bdms
        )

    @delete_image_on_error
    def _do_snapshot_instance(self, context, image_id, instance):
        self._snapshot_instance(context, image_id, instance,
                                task_states.IMAGE_BACKUP)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def backup_instance(self, context, image_id, instance, backup_type,
                        rotation):
        """Backup an instance on this host.

        :param backup_type: daily | weekly
        :param rotation: int representing how many backups to keep around
        """
        self._do_snapshot_instance(context, image_id, instance)
        self._rotate_backups(context, instance, backup_type, rotation)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    @delete_image_on_error
    def snapshot_instance(self, context, image_id, instance):
        """Snapshot an instance on this host.

        :param context: security context
        :param image_id: glance.db.sqlalchemy.models.Image.Id
        :param instance: a nova.objects.instance.Instance object
        """
        # NOTE(dave-mcnally) the task state will already be set by the api
        # but if the compute manager has crashed/been restarted prior to the
        # request getting here the task state may have been cleared so we set
        # it again and things continue normally
        try:
            instance.task_state = task_states.IMAGE_SNAPSHOT
            instance.save(
                        expected_task_state=task_states.IMAGE_SNAPSHOT_PENDING)
        except exception.InstanceNotFound:
            # possibility instance no longer exists, no point in continuing
            LOG.debug("Instance not found, could not set state %s "
                      "for instance.",
                      task_states.IMAGE_SNAPSHOT, instance=instance)
            return

        except exception.UnexpectedDeletingTaskStateError:
            LOG.debug("Instance being deleted, snapshot cannot continue",
                      instance=instance)
            return

        self._snapshot_instance(context, image_id, instance,
                                task_states.IMAGE_SNAPSHOT)

    def _snapshot_instance(self, context, image_id, instance,
                           expected_task_state):
        context = context.elevated()

        instance.power_state = self._get_power_state(context, instance)
        try:
            instance.save()

            LOG.info('instance snapshotting', instance=instance)

            if instance.power_state != power_state.RUNNING:
                state = instance.power_state
                running = power_state.RUNNING
                LOG.warning('trying to snapshot a non-running instance: '
                            '(state: %(state)s expected: %(running)s)',
                            {'state': state, 'running': running},
                            instance=instance)

            self._notify_about_instance_usage(
                context, instance, "snapshot.start")
            compute_utils.notify_about_instance_snapshot(context, instance,
                self.host, phase=fields.NotificationPhase.START,
                snapshot_image_id=image_id)

            def update_task_state(task_state,
                                  expected_state=expected_task_state):
                instance.task_state = task_state
                instance.save(expected_task_state=expected_state)

            with timeutils.StopWatch() as timer:
                self.driver.snapshot(context, instance, image_id,
                                     update_task_state)
            LOG.info('Took %0.2f seconds to snapshot the instance on '
                     'the hypervisor.', timer.elapsed(), instance=instance)

            instance.task_state = None
            instance.save(expected_task_state=task_states.IMAGE_UPLOADING)

            self._notify_about_instance_usage(context, instance,
                                              "snapshot.end")
            compute_utils.notify_about_instance_snapshot(context, instance,
                self.host, phase=fields.NotificationPhase.END,
                snapshot_image_id=image_id)
        except (exception.InstanceNotFound,
                exception.UnexpectedDeletingTaskStateError):
            # the instance got deleted during the snapshot
            # Quickly bail out of here
            msg = 'Instance disappeared during snapshot'
            LOG.debug(msg, instance=instance)
            try:
                image = self.image_api.get(context, image_id)
                if image['status'] != 'active':
                    self.image_api.delete(context, image_id)
            except exception.ImageNotFound:
                LOG.debug('Image not found during clean up %s', image_id)
            except Exception:
                LOG.warning("Error while trying to clean up image %s",
                            image_id, instance=instance)
        except exception.ImageNotFound:
            instance.task_state = None
            instance.save()
            LOG.warning("Image not found during snapshot", instance=instance)

    def _post_interrupted_snapshot_cleanup(self, context, instance):
        self.driver.post_interrupted_snapshot_cleanup(context, instance)

    @messaging.expected_exceptions(NotImplementedError)
    @wrap_exception()
    def volume_snapshot_create(self, context, instance, volume_id,
                               create_info):
        self.driver.volume_snapshot_create(context, instance, volume_id,
                                           create_info)

    @messaging.expected_exceptions(NotImplementedError)
    @wrap_exception()
    def volume_snapshot_delete(self, context, instance, volume_id,
                               snapshot_id, delete_info):
        self.driver.volume_snapshot_delete(context, instance, volume_id,
                                           snapshot_id, delete_info)

    @wrap_instance_fault
    def _rotate_backups(self, context, instance, backup_type, rotation):
        """Delete excess backups associated to an instance.

        Instances are allowed a fixed number of backups (the rotation number);
        this method deletes the oldest backups that exceed the rotation
        threshold.

        :param context: security context
        :param instance: Instance dict
        :param backup_type: a user-defined type, like "daily" or "weekly" etc.
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        """
        filters = {'property-image_type': 'backup',
                   'property-backup_type': backup_type,
                   'property-instance_uuid': instance.uuid}

        images = self.image_api.get_all(context, filters=filters,
                                        sort_key='created_at', sort_dir='desc')
        num_images = len(images)
        LOG.debug("Found %(num_images)d images (rotation: %(rotation)d)",
                  {'num_images': num_images, 'rotation': rotation},
                  instance=instance)

        if num_images > rotation:
            # NOTE(sirp): this deletes all backups that exceed the rotation
            # limit
            excess = len(images) - rotation
            LOG.debug("Rotating out %d backups", excess,
                      instance=instance)
            for i in range(excess):
                image = images.pop()
                image_id = image['id']
                LOG.debug("Deleting image %s", image_id,
                          instance=instance)
                try:
                    self.image_api.delete(context, image_id)
                except exception.ImageNotFound:
                    LOG.info("Failed to find image %(image_id)s to "
                             "delete", {'image_id': image_id},
                             instance=instance)
                except (exception.ImageDeleteConflict, Exception) as exc:
                    LOG.info("Failed to delete image %(image_id)s during "
                             "deleting excess backups. "
                             "Continuing for next image.. %(exc)s",
                             {'image_id': image_id, 'exc': exc},
                             instance=instance)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def set_admin_password(self, context, instance, new_pass):
        """Set the root/admin password for an instance on this host.

        This is generally only called by API password resets after an
        image has been built.

        @param context: Nova auth context.
        @param instance: Nova instance object.
        @param new_pass: The admin password for the instance.
        """

        context = context.elevated()
        if new_pass is None:
            # Generate a random password
            new_pass = utils.generate_password()

        current_power_state = self._get_power_state(context, instance)
        expected_state = power_state.RUNNING

        if current_power_state != expected_state:
            instance.task_state = None
            instance.save(expected_task_state=task_states.UPDATING_PASSWORD)
            _msg = _('instance %s is not running') % instance.uuid
            raise exception.InstancePasswordSetFailed(
                instance=instance.uuid, reason=_msg)

        try:
            self.driver.set_admin_password(instance, new_pass)
            LOG.info("Admin password set", instance=instance)
            instance.task_state = None
            instance.save(
                expected_task_state=task_states.UPDATING_PASSWORD)
        except exception.InstanceAgentNotEnabled:
            with excutils.save_and_reraise_exception():
                LOG.debug('Guest agent is not enabled for the instance.',
                          instance=instance)
                instance.task_state = None
                instance.save(
                    expected_task_state=task_states.UPDATING_PASSWORD)
        except exception.SetAdminPasswdNotSupported:
            with excutils.save_and_reraise_exception():
                LOG.info('set_admin_password is not supported '
                         'by this driver or guest instance.',
                         instance=instance)
                instance.task_state = None
                instance.save(
                    expected_task_state=task_states.UPDATING_PASSWORD)
        except NotImplementedError:
            LOG.warning('set_admin_password is not implemented '
                        'by this driver or guest instance.',
                        instance=instance)
            instance.task_state = None
            instance.save(
                expected_task_state=task_states.UPDATING_PASSWORD)
            raise NotImplementedError(_('set_admin_password is not '
                                        'implemented by this driver or guest '
                                        'instance.'))
        except exception.UnexpectedTaskStateError:
            # interrupted by another (most likely delete) task
            # do not retry
            raise
        except Exception:
            # Catch all here because this could be anything.
            LOG.exception('set_admin_password failed', instance=instance)
            # We create a new exception here so that we won't
            # potentially reveal password information to the
            # API caller.  The real exception is logged above
            _msg = _('error setting admin password')
            raise exception.InstancePasswordSetFailed(
                instance=instance.uuid, reason=_msg)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def inject_file(self, context, path, file_contents, instance):
        """Write a file to the specified path in an instance on this host."""
        # NOTE(russellb) Remove this method, as well as the underlying virt
        # driver methods, when the compute rpc interface is bumped to 4.x
        # as it is no longer used.
        context = context.elevated()
        current_power_state = self._get_power_state(context, instance)
        expected_state = power_state.RUNNING
        if current_power_state != expected_state:
            LOG.warning('trying to inject a file into a non-running '
                        '(state: %(current_state)s expected: '
                        '%(expected_state)s)',
                        {'current_state': current_power_state,
                         'expected_state': expected_state},
                        instance=instance)
        LOG.info('injecting file to %s', path, instance=instance)
        self.driver.inject_file(instance, path, file_contents)

    def _get_rescue_image(self, context, instance, rescue_image_ref=None):
        """Determine what image should be used to boot the rescue VM."""
        # 1. If rescue_image_ref is passed in, use that for rescue.
        # 2. Else, use the base image associated with instance's current image.
        #       The idea here is to provide the customer with a rescue
        #       environment which they are familiar with.
        #       So, if they built their instance off of a Debian image,
        #       their rescue VM will also be Debian.
        # 3. As a last resort, use instance's current image.
        if not rescue_image_ref:
            system_meta = utils.instance_sys_meta(instance)
            rescue_image_ref = system_meta.get('image_base_image_ref')

        if not rescue_image_ref:
            LOG.warning('Unable to find a different image to use for '
                        'rescue VM, using instance\'s current image',
                        instance=instance)
            rescue_image_ref = instance.image_ref

        return objects.ImageMeta.from_image_ref(
            context, self.image_api, rescue_image_ref)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def rescue_instance(self, context, instance, rescue_password,
                        rescue_image_ref, clean_shutdown):
        context = context.elevated()
        LOG.info('Rescuing', instance=instance)

        admin_password = (rescue_password if rescue_password else
                      utils.generate_password())

        network_info = self.network_api.get_instance_nw_info(context, instance)

        rescue_image_meta = self._get_rescue_image(context, instance,
                                                   rescue_image_ref)

        extra_usage_info = {'rescue_image_name':
                            self._get_image_name(rescue_image_meta)}
        self._notify_about_instance_usage(context, instance,
                "rescue.start", extra_usage_info=extra_usage_info,
                network_info=network_info)
        compute_utils.notify_about_instance_rescue_action(
            context, instance, self.host, rescue_image_ref,
            phase=fields.NotificationPhase.START)

        try:
            self._power_off_instance(context, instance, clean_shutdown)

            self.driver.rescue(context, instance,
                               network_info,
                               rescue_image_meta, admin_password)
        except Exception as e:
            LOG.exception("Error trying to Rescue Instance",
                          instance=instance)
            self._set_instance_obj_error_state(context, instance)
            raise exception.InstanceNotRescuable(
                instance_id=instance.uuid,
                reason=_("Driver Error: %s") % e)

        compute_utils.notify_usage_exists(self.notifier, context, instance,
                                          self.host, current_period=True)

        instance.vm_state = vm_states.RESCUED
        instance.task_state = None
        instance.power_state = self._get_power_state(context, instance)
        instance.launched_at = timeutils.utcnow()
        instance.save(expected_task_state=task_states.RESCUING)

        self._notify_about_instance_usage(context, instance,
                "rescue.end", extra_usage_info=extra_usage_info,
                network_info=network_info)
        compute_utils.notify_about_instance_rescue_action(
            context, instance, self.host, rescue_image_ref,
            phase=fields.NotificationPhase.END)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def unrescue_instance(self, context, instance):
        context = context.elevated()
        LOG.info('Unrescuing', instance=instance)

        network_info = self.network_api.get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(context, instance,
                "unrescue.start", network_info=network_info)
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.UNRESCUE,
            phase=fields.NotificationPhase.START)

        with self._error_out_instance_on_exception(context, instance):
            self.driver.unrescue(instance,
                                 network_info)

        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.power_state = self._get_power_state(context, instance)
        instance.save(expected_task_state=task_states.UNRESCUING)

        self._notify_about_instance_usage(context,
                                          instance,
                                          "unrescue.end",
                                          network_info=network_info)
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.UNRESCUE,
            phase=fields.NotificationPhase.END)

    @wrap_exception()
    @wrap_instance_fault
    def change_instance_metadata(self, context, diff, instance):
        """Update the metadata published to the instance."""
        LOG.debug("Changing instance metadata according to %r",
                  diff, instance=instance)
        self.driver.change_instance_metadata(context, instance, diff)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def confirm_resize(self, context, instance, migration):
        """Confirms a migration/resize and deletes the 'old' instance.

        This is called from the API and runs on the source host.

        Nothing needs to happen on the destination host at this point since
        the instance is already running there. This routine just cleans up the
        source host.
        """
        @utils.synchronized(instance.uuid)
        def do_confirm_resize(context, instance, migration_id):
            # NOTE(wangpan): Get the migration status from db, if it has been
            #                confirmed, we do nothing and return here
            LOG.debug("Going to confirm migration %s", migration_id,
                      instance=instance)
            try:
                # TODO(russellb) Why are we sending the migration object just
                # to turn around and look it up from the db again?
                migration = objects.Migration.get_by_id(
                                    context.elevated(), migration_id)
            except exception.MigrationNotFound:
                LOG.error("Migration %s is not found during confirmation",
                          migration_id, instance=instance)
                return

            if migration.status == 'confirmed':
                LOG.info("Migration %s is already confirmed",
                         migration_id, instance=instance)
                return
            elif migration.status not in ('finished', 'confirming'):
                LOG.warning("Unexpected confirmation status '%(status)s' "
                            "of migration %(id)s, exit confirmation process",
                            {"status": migration.status, "id": migration_id},
                            instance=instance)
                return

            # NOTE(wangpan): Get the instance from db, if it has been
            #                deleted, we do nothing and return here
            expected_attrs = ['metadata', 'system_metadata', 'flavor']
            try:
                instance = objects.Instance.get_by_uuid(
                        context, instance.uuid,
                        expected_attrs=expected_attrs)
            except exception.InstanceNotFound:
                LOG.info("Instance is not found during confirmation",
                         instance=instance)
                return

            self._confirm_resize(context, instance, migration=migration)

        do_confirm_resize(context, instance, migration.id)

    def _confirm_resize(self, context, instance, migration=None):
        """Destroys the source instance."""
        self._notify_about_instance_usage(context, instance,
                                          "resize.confirm.start")
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.RESIZE_CONFIRM,
            phase=fields.NotificationPhase.START)

        with self._error_out_instance_on_exception(context, instance):
            # NOTE(danms): delete stashed migration information
            old_instance_type = instance.old_flavor
            instance.old_flavor = None
            instance.new_flavor = None
            instance.system_metadata.pop('old_vm_state', None)
            instance.save()

            # NOTE(tr3buchet): tear down networks on source host
            self.network_api.setup_networks_on_host(context, instance,
                               migration.source_compute, teardown=True)

            network_info = self.network_api.get_instance_nw_info(context,
                                                                 instance)
            # TODO(mriedem): Get BDMs here and pass them to the driver.
            self.driver.confirm_migration(context, migration, instance,
                                          network_info)

            migration.status = 'confirmed'
            with migration.obj_as_admin():
                migration.save()

            rt = self._get_resource_tracker()
            rt.drop_move_claim(context, instance, migration.source_node,
                               old_instance_type, prefix='old_')
            self._delete_allocation_after_move(context, instance, migration,
                                               old_instance_type,
                                               migration.source_node)
            instance.drop_migration_context()

            # NOTE(mriedem): The old_vm_state could be STOPPED but the user
            # might have manually powered up the instance to confirm the
            # resize/migrate, so we need to check the current power state
            # on the instance and set the vm_state appropriately. We default
            # to ACTIVE because if the power state is not SHUTDOWN, we
            # assume _sync_instance_power_state will clean it up.
            p_state = instance.power_state
            vm_state = None
            if p_state == power_state.SHUTDOWN:
                vm_state = vm_states.STOPPED
                LOG.debug("Resized/migrated instance is powered off. "
                          "Setting vm_state to '%s'.", vm_state,
                          instance=instance)
            else:
                vm_state = vm_states.ACTIVE

            instance.vm_state = vm_state
            instance.task_state = None
            instance.save(expected_task_state=[None, task_states.DELETING,
                                               task_states.SOFT_DELETING])

            self._notify_about_instance_usage(
                context, instance, "resize.confirm.end",
                network_info=network_info)
            compute_utils.notify_about_instance_action(context, instance,
                   self.host, action=fields.NotificationAction.RESIZE_CONFIRM,
                   phase=fields.NotificationPhase.END)

    def _delete_allocation_after_move(self, context, instance, migration,
                                      flavor, nodename):
        rt = self._get_resource_tracker()
        cn_uuid = rt.get_node_uuid(nodename)

        if migration.source_node == nodename:
            if migration.status in ('confirmed', 'completed'):
                # NOTE(danms): We're finishing on the source node, so try to
                # delete the allocation based on the migration uuid
                deleted = self.reportclient.delete_allocation_for_instance(
                    context, migration.uuid)
                if deleted:
                    LOG.info(_('Source node %(node)s confirmed migration '
                               '%(mig)s; deleted migration-based '
                               'allocation'),
                             {'node': nodename, 'mig': migration.uuid})
                    # NOTE(danms): We succeeded, which means we do not
                    # need to do the complex double allocation dance
                    return
            else:
                # We're reverting (or failed) on the source, so we
                # need to check if our migration holds a claim and if
                # so, avoid doing the legacy behavior below.
                mig_allocs = (
                    self.reportclient.get_allocations_for_consumer_by_provider(
                        context, cn_uuid, migration.uuid))
                if mig_allocs:
                    LOG.info(_('Source node %(node)s reverted migration '
                               '%(mig)s; not deleting migration-based '
                               'allocation'),
                             {'node': nodename, 'mig': migration.uuid})
                    return
        elif migration.dest_node == nodename:
            # NOTE(danms): We're reverting on the destination node
            # (and we must not be doing a same-host migration if we
            # made it past the check above), so we need to check to
            # see if the source did migration-based allocation
            # accounting
            allocs = self.reportclient.get_allocations_for_consumer(
                context, migration.uuid)
            if allocs:
                # NOTE(danms): The source did migration-based allocation
                # accounting, so we should let the source node rejigger
                # the allocations in finish_resize_revert()
                LOG.info(_('Destination node %(node)s reverted migration '
                           '%(mig)s; not deleting migration-based '
                           'allocation'),
                         {'node': nodename, 'mig': migration.uuid})
                return

        # TODO(danms): Remove below this line when we remove compatibility
        # for double-accounting migrations (likely rocky)
        LOG.info(_('Doing legacy allocation math for migration %(mig)s after '
                   'instance move'),
                 {'mig': migration.uuid},
                 instance=instance)

        # NOTE(jaypipes): This sucks, but due to the fact that confirm_resize()
        # only runs on the source host and revert_resize() runs on the
        # destination host, we need to do this here. Basically, what we're
        # doing here is grabbing the existing allocations for this instance
        # from the placement API, dropping the resources in the doubled-up
        # allocation set that refer to the source host UUID and calling PUT
        # /allocations back to the placement API. The allocation that gets
        # PUT'd back to placement will only include the destination host and
        # any shared providers in the case of a confirm_resize operation and
        # the source host and shared providers for a revert_resize operation..
        if not scheduler_utils.remove_allocation_from_compute(
                context, instance, cn_uuid, self.reportclient, flavor):
            LOG.error("Failed to save manipulated allocation",
                      instance=instance)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @errors_out_migration
    @wrap_instance_fault
    def revert_resize(self, context, instance, migration):
        """Destroys the new instance on the destination machine.

        Reverts the model changes, and powers on the old instance on the
        source machine.

        """
        # NOTE(comstud): A revert_resize is essentially a resize back to
        # the old size, so we need to send a usage event here.
        compute_utils.notify_usage_exists(self.notifier, context, instance,
                                          self.host, current_period=True)

        with self._error_out_instance_on_exception(context, instance):
            # NOTE(tr3buchet): tear down networks on destination host
            self.network_api.setup_networks_on_host(context, instance,
                                                    teardown=True)

            migration_p = obj_base.obj_to_primitive(migration)
            self.network_api.migrate_instance_start(context,
                                                    instance,
                                                    migration_p)

            network_info = self.network_api.get_instance_nw_info(context,
                                                                 instance)
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)
            block_device_info = self._get_instance_block_device_info(
                                context, instance, bdms=bdms)

            destroy_disks = not self._is_instance_storage_shared(
                context, instance, host=migration.source_compute)
            self.driver.destroy(context, instance, network_info,
                                block_device_info, destroy_disks)

            self._terminate_volume_connections(context, instance, bdms)

            migration.status = 'reverted'
            with migration.obj_as_admin():
                migration.save()

            # NOTE(ndipanov): We need to do this here because dropping the
            # claim means we lose the migration_context data. We really should
            # fix this by moving the drop_move_claim call to the
            # finish_revert_resize method as this is racy (revert is dropped,
            # but instance resources will be tracked with the new flavor until
            # it gets rolled back in finish_revert_resize, which is
            # potentially wrong for a period of time).
            instance.revert_migration_context()
            instance.save()

            rt = self._get_resource_tracker()
            rt.drop_move_claim(context, instance, instance.node)
            self._delete_allocation_after_move(context, instance, migration,
                                               instance.flavor,
                                               instance.node)

            # RPC cast back to the source host to finish the revert there.
            self.compute_rpcapi.finish_revert_resize(context, instance,
                    migration, migration.source_compute)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @errors_out_migration
    @wrap_instance_fault
    def finish_revert_resize(self, context, instance, migration):
        """Finishes the second half of reverting a resize on the source host.

        Bring the original source instance state back (active/shutoff) and
        revert the resized attributes in the database.

        """
        with self._error_out_instance_on_exception(context, instance):
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
            self._notify_about_instance_usage(
                    context, instance, "resize.revert.start")
            compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.RESIZE_REVERT,
                    phase=fields.NotificationPhase.START, bdms=bdms)

            # NOTE(mriedem): delete stashed old_vm_state information; we
            # default to ACTIVE for backwards compatibility if old_vm_state
            # is not set
            old_vm_state = instance.system_metadata.pop('old_vm_state',
                                                        vm_states.ACTIVE)

            self._set_instance_info(instance, instance.old_flavor)
            instance.old_flavor = None
            instance.new_flavor = None
            instance.host = migration.source_compute
            instance.node = migration.source_node
            instance.save()

            self._revert_allocation(context, instance, migration)

            self.network_api.setup_networks_on_host(context, instance,
                                                    migration.source_compute)
            migration_p = obj_base.obj_to_primitive(migration)
            # NOTE(hanrong): we need to change migration_p['dest_compute'] to
            # source host temporarily. "network_api.migrate_instance_finish"
            # will setup the network for the instance on the destination host.
            # For revert resize, the instance will back to the source host, the
            # setup of the network for instance should be on the source host.
            # So set the migration_p['dest_compute'] to source host at here.
            migration_p['dest_compute'] = migration.source_compute
            self.network_api.migrate_instance_finish(context,
                                                     instance,
                                                     migration_p)
            network_info = self.network_api.get_instance_nw_info(context,
                                                                 instance)

            # revert_resize deleted any volume attachments for the instance
            # and created new ones to be used on this host, but we
            # have to update those attachments with the host connector so the
            # BDM.connection_info will get set in the call to
            # _get_instance_block_device_info below with refresh_conn_info=True
            # and then the volumes can be re-connected via the driver on this
            # host.
            self._update_volume_attachments(context, instance, bdms)

            block_device_info = self._get_instance_block_device_info(
                    context, instance, refresh_conn_info=True, bdms=bdms)

            power_on = old_vm_state != vm_states.STOPPED
            self.driver.finish_revert_migration(context, instance,
                                       network_info,
                                       block_device_info, power_on)

            instance.drop_migration_context()
            instance.launched_at = timeutils.utcnow()
            instance.save(expected_task_state=task_states.RESIZE_REVERTING)

            # Complete any volume attachments so the volumes are in-use.
            self._complete_volume_attachments(context, bdms)

            # if the original vm state was STOPPED, set it back to STOPPED
            LOG.info("Updating instance to original state: '%s'",
                     old_vm_state, instance=instance)
            if power_on:
                instance.vm_state = vm_states.ACTIVE
                instance.task_state = None
                instance.save()
            else:
                instance.task_state = task_states.POWERING_OFF
                instance.save()
                self.stop_instance(context, instance=instance,
                                   clean_shutdown=True)

            self._notify_about_instance_usage(
                    context, instance, "resize.revert.end")
            compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.RESIZE_REVERT,
                    phase=fields.NotificationPhase.END, bdms=bdms)

    def _revert_allocation(self, context, instance, migration):
        """Revert an allocation that is held by migration to our instance."""

        # Fetch the original allocation that the instance had on the source
        # node, which are now held by the migration
        orig_alloc = self.reportclient.get_allocations_for_consumer(
            context, migration.uuid)
        if not orig_alloc:
            # NOTE(danms): This migration did not do per-migration allocation
            # accounting, so nothing to do here.
            LOG.info('Old-style migration %(mig)s is being reverted; '
                     'no migration claims found on original node '
                     'to swap.',
                     {'mig': migration.uuid},
                     instance=instance)
            return False

        if len(orig_alloc) > 1:
            # NOTE(danms): This may change later if we have other allocations
            # against other providers that need to be held by the migration
            # as well. Perhaps something like shared storage resources that
            # will actually be duplicated during a resize type operation.
            LOG.error('New-style migration %(mig)s has allocations against '
                      'more than one provider %(rps)s. This should not be '
                      'possible, but reverting it anyway.',
                      {'mig': migration.uuid,
                       'rps': ','.join(orig_alloc.keys())},
                      instance=instance)

        # We only have a claim against one provider, it is the source node
        cn_uuid = list(orig_alloc.keys())[0]

        # Get just the resources part of the one allocation we need below
        orig_alloc = orig_alloc[cn_uuid].get('resources', {})

        # FIXME(danms): This method is flawed in that it asssumes allocations
        # against only one provider. So, this may overwite allocations against
        # a shared provider, if we had one.
        LOG.info('Swapping old allocation on %(node)s held by migration '
                 '%(mig)s for instance',
                 {'node': cn_uuid, 'mig': migration.uuid},
                 instance=instance)
        # TODO(cdent): Should we be doing anything with return values here?
        self.reportclient.set_and_clear_allocations(
            context, cn_uuid, instance.uuid, orig_alloc, instance.project_id,
            instance.user_id, consumer_to_clear=migration.uuid)
        return True

    def _prep_resize(self, context, image, instance, instance_type,
                     filter_properties, node, migration, clean_shutdown=True):

        if not filter_properties:
            filter_properties = {}

        if not instance.host:
            self._set_instance_obj_error_state(context, instance)
            msg = _('Instance has no source host')
            raise exception.MigrationError(reason=msg)

        same_host = instance.host == self.host
        # if the flavor IDs match, it's migrate; otherwise resize
        if same_host and instance_type.id == instance['instance_type_id']:
            # check driver whether support migrate to same host
            if not self.driver.capabilities.get(
                    'supports_migrate_to_same_host', False):
                raise exception.UnableToMigrateToSelf(
                    instance_id=instance.uuid, host=self.host)

        # NOTE(danms): Stash the new instance_type to avoid having to
        # look it up in the database later
        instance.new_flavor = instance_type
        # NOTE(mriedem): Stash the old vm_state so we can set the
        # resized/reverted instance back to the same state later.
        vm_state = instance.vm_state
        LOG.debug('Stashing vm_state: %s', vm_state, instance=instance)
        instance.system_metadata['old_vm_state'] = vm_state
        instance.save()

        limits = filter_properties.get('limits', {})
        rt = self._get_resource_tracker()
        with rt.resize_claim(context, instance, instance_type, node,
                             migration, image_meta=image,
                             limits=limits) as claim:
            LOG.info('Migrating', instance=instance)
            # RPC cast to the source host to start the actual resize/migration.
            self.compute_rpcapi.resize_instance(
                    context, instance, claim.migration, image,
                    instance_type, clean_shutdown)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def prep_resize(self, context, image, instance, instance_type,
                    request_spec, filter_properties, node,
                    clean_shutdown, migration, host_list):
        """Initiates the process of moving a running instance to another host.

        Possibly changes the VCPU, RAM and disk size in the process.

        This is initiated from conductor and runs on the destination host.

        The main purpose of this method is performing some checks on the
        destination host and making a claim for resources. If the claim fails
        then a reschedule to another host may be attempted which involves
        calling back to conductor to start the process over again.
        """
        if node is None:
            node = self._get_nodename(instance, refresh=True)

        with self._error_out_instance_on_exception(context, instance), \
                 errors_out_migration_ctxt(migration):
            compute_utils.notify_usage_exists(self.notifier, context, instance,
                                              self.host, current_period=True)
            self._notify_about_instance_usage(
                    context, instance, "resize.prep.start")
            compute_utils.notify_about_resize_prep_instance(
                context, instance, self.host,
                fields.NotificationPhase.START, instance_type)
            try:
                self._prep_resize(context, image, instance,
                                  instance_type, filter_properties,
                                  node, migration, clean_shutdown)
            except Exception:
                # Since we hit a failure, we're either rescheduling or dead
                # and either way we need to cleanup any allocations created
                # by the scheduler for the destination node.
                if migration and not self._revert_allocation(
                        context, instance, migration):
                    # We did not do a migration-based
                    # allocation. Note that for a resize to the
                    # same host, the scheduler will merge the
                    # flavors, so here we'd be subtracting the new
                    # flavor from the allocated resources on this
                    # node.
                    # FIXME(danms): Remove this in Rocky
                    rt = self._get_resource_tracker()
                    rt.delete_allocation_for_failed_resize(
                        context, instance, node, instance_type)
                # try to re-schedule the resize elsewhere:
                exc_info = sys.exc_info()
                self._reschedule_resize_or_reraise(context, image, instance,
                        exc_info, instance_type, request_spec,
                        filter_properties, host_list)
            finally:
                extra_usage_info = dict(
                        new_instance_type=instance_type.name,
                        new_instance_type_id=instance_type.id)

                self._notify_about_instance_usage(
                    context, instance, "resize.prep.end",
                    extra_usage_info=extra_usage_info)
                compute_utils.notify_about_resize_prep_instance(
                    context, instance, self.host,
                    fields.NotificationPhase.END, instance_type)

    def _reschedule_resize_or_reraise(self, context, image, instance, exc_info,
            instance_type, request_spec, filter_properties, host_list):
        """Try to re-schedule the resize or re-raise the original error to
        error out the instance.
        """
        if not request_spec:
            request_spec = {}
        if not filter_properties:
            filter_properties = {}

        rescheduled = False
        instance_uuid = instance.uuid

        try:
            reschedule_method = self.compute_task_api.resize_instance
            scheduler_hint = dict(filter_properties=filter_properties)
            method_args = (instance, None, scheduler_hint, instance_type)
            task_state = task_states.RESIZE_PREP

            rescheduled = self._reschedule(context, request_spec,
                    filter_properties, instance, reschedule_method,
                    method_args, task_state, exc_info, host_list=host_list)
        except Exception as error:
            rescheduled = False
            LOG.exception("Error trying to reschedule",
                          instance_uuid=instance_uuid)
            compute_utils.add_instance_fault_from_exc(context,
                    instance, error,
                    exc_info=sys.exc_info())
            self._notify_about_instance_usage(context, instance,
                    'resize.error', fault=error)
            compute_utils.notify_about_instance_action(
                context, instance, self.host,
                action=fields.NotificationAction.RESIZE,
                phase=fields.NotificationPhase.ERROR,
                exception=error,
                tb=','.join(traceback.format_exception(*exc_info)))
        if rescheduled:
            self._log_original_error(exc_info, instance_uuid)
            compute_utils.add_instance_fault_from_exc(context,
                    instance, exc_info[1], exc_info=exc_info)
            self._notify_about_instance_usage(context, instance,
                    'resize.error', fault=exc_info[1])
            compute_utils.notify_about_instance_action(
                context, instance, self.host,
                action=fields.NotificationAction.RESIZE,
                phase=fields.NotificationPhase.ERROR,
                exception=exc_info[1],
                tb=','.join(traceback.format_exception(*exc_info)))
        else:
            # not re-scheduling
            six.reraise(*exc_info)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def resize_instance(self, context, instance, image,
                        migration, instance_type, clean_shutdown):
        """Starts the migration of a running instance to another host.

        This is initiated from the destination host's ``prep_resize`` routine
        and runs on the source host.
        """
        try:
            self._resize_instance(context, instance, image, migration,
                                  instance_type, clean_shutdown)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._revert_allocation(context, instance, migration)

    def _resize_instance(self, context, instance, image,
                         migration, instance_type, clean_shutdown):
        with self._error_out_instance_on_exception(context, instance), \
             errors_out_migration_ctxt(migration):
            network_info = self.network_api.get_instance_nw_info(context,
                                                                 instance)

            migration.status = 'migrating'
            with migration.obj_as_admin():
                migration.save()

            instance.task_state = task_states.RESIZE_MIGRATING
            instance.save(expected_task_state=task_states.RESIZE_PREP)

            self._notify_about_instance_usage(
                context, instance, "resize.start", network_info=network_info)

            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

            compute_utils.notify_about_instance_action(context, instance,
                   self.host, action=fields.NotificationAction.RESIZE,
                   phase=fields.NotificationPhase.START, bdms=bdms)

            block_device_info = self._get_instance_block_device_info(
                                context, instance, bdms=bdms)

            timeout, retry_interval = self._get_power_off_values(context,
                                            instance, clean_shutdown)
            disk_info = self.driver.migrate_disk_and_power_off(
                    context, instance, migration.dest_host,
                    instance_type, network_info,
                    block_device_info,
                    timeout, retry_interval)

            self._terminate_volume_connections(context, instance, bdms)

            migration_p = obj_base.obj_to_primitive(migration)
            self.network_api.migrate_instance_start(context,
                                                    instance,
                                                    migration_p)

            migration.status = 'post-migrating'
            with migration.obj_as_admin():
                migration.save()

            instance.host = migration.dest_compute
            instance.node = migration.dest_node
            instance.task_state = task_states.RESIZE_MIGRATED
            instance.save(expected_task_state=task_states.RESIZE_MIGRATING)

            # RPC cast to the destination host to finish the resize/migration.
            self.compute_rpcapi.finish_resize(context, instance,
                    migration, image, disk_info, migration.dest_compute)

        self._notify_about_instance_usage(context, instance, "resize.end",
                                          network_info=network_info)

        compute_utils.notify_about_instance_action(context, instance,
               self.host, action=fields.NotificationAction.RESIZE,
               phase=fields.NotificationPhase.END, bdms=bdms)
        self.instance_events.clear_events_for_instance(instance)

    def _terminate_volume_connections(self, context, instance, bdms):
        connector = None
        for bdm in bdms:
            if bdm.is_volume:
                if bdm.attachment_id:
                    # NOTE(jdg): So here's the thing, the idea behind the new
                    # attach API's was to have a new code fork/path that we
                    # followed, we're not going to do that so we have to do
                    # some extra work in here to make it *behave* just like the
                    # old code. Cinder doesn't allow disconnect/reconnect (you
                    # just delete the attachment and get a new one)
                    # attachments in the new attach code so we have to do
                    # a delete and create without a connector (reserve),
                    # in other words, beware
                    attachment_id = self.volume_api.attachment_create(
                        context, bdm.volume_id, instance.uuid)['id']
                    self.volume_api.attachment_delete(context,
                                                      bdm.attachment_id)
                    bdm.attachment_id = attachment_id
                    bdm.save()

                else:
                    if connector is None:
                        connector = self.driver.get_volume_connector(instance)
                    self.volume_api.terminate_connection(context,
                                                         bdm.volume_id,
                                                         connector)

    @staticmethod
    def _set_instance_info(instance, instance_type):
        instance.instance_type_id = instance_type.id
        instance.memory_mb = instance_type.memory_mb
        instance.vcpus = instance_type.vcpus
        instance.root_gb = instance_type.root_gb
        instance.ephemeral_gb = instance_type.ephemeral_gb
        instance.flavor = instance_type

    def _update_volume_attachments(self, context, instance, bdms):
        """Updates volume attachments using the virt driver host connector.

        :param context: nova.context.RequestContext - user request context
        :param instance: nova.objects.Instance
        :param bdms: nova.objects.BlockDeviceMappingList - the list of block
                     device mappings for the given instance
        """
        if bdms:
            connector = None
            for bdm in bdms:
                if bdm.is_volume and bdm.attachment_id:
                    if connector is None:
                        connector = self.driver.get_volume_connector(instance)
                    self.volume_api.attachment_update(
                        context, bdm.attachment_id, connector, bdm.device_name)

    def _complete_volume_attachments(self, context, bdms):
        """Completes volume attachments for the instance

        :param context: nova.context.RequestContext - user request context
        :param bdms: nova.objects.BlockDeviceMappingList - the list of block
                     device mappings for the given instance
        """
        if bdms:
            for bdm in bdms:
                if bdm.is_volume and bdm.attachment_id:
                    self.volume_api.attachment_complete(
                        context, bdm.attachment_id)

    def _finish_resize(self, context, instance, migration, disk_info,
                       image_meta, bdms):
        resize_instance = False
        old_instance_type_id = migration['old_instance_type_id']
        new_instance_type_id = migration['new_instance_type_id']
        old_instance_type = instance.get_flavor()
        # NOTE(mriedem): Get the old_vm_state so we know if we should
        # power on the instance. If old_vm_state is not set we need to default
        # to ACTIVE for backwards compatibility
        old_vm_state = instance.system_metadata.get('old_vm_state',
                                                    vm_states.ACTIVE)
        instance.old_flavor = old_instance_type

        if old_instance_type_id != new_instance_type_id:
            instance_type = instance.get_flavor('new')
            self._set_instance_info(instance, instance_type)
            for key in ('root_gb', 'swap', 'ephemeral_gb'):
                if old_instance_type[key] != instance_type[key]:
                    resize_instance = True
                    break
        instance.apply_migration_context()

        # NOTE(tr3buchet): setup networks on destination host
        self.network_api.setup_networks_on_host(context, instance,
                                                migration['dest_compute'])

        migration_p = obj_base.obj_to_primitive(migration)
        self.network_api.migrate_instance_finish(context,
                                                 instance,
                                                 migration_p)

        network_info = self.network_api.get_instance_nw_info(context, instance)

        instance.task_state = task_states.RESIZE_FINISH
        instance.save(expected_task_state=task_states.RESIZE_MIGRATED)

        self._notify_about_instance_usage(
            context, instance, "finish_resize.start",
            network_info=network_info)
        compute_utils.notify_about_instance_action(context, instance,
               self.host, action=fields.NotificationAction.RESIZE_FINISH,
               phase=fields.NotificationPhase.START, bdms=bdms)

        # We need to update any volume attachments using the destination
        # host connector so that we can update the BDM.connection_info
        # before calling driver.finish_migration otherwise the driver
        # won't know how to connect the volumes to this host.
        # Note that _get_instance_block_device_info with
        # refresh_conn_info=True will update the BDM.connection_info value
        # in the database so we must do this before calling that method.
        self._update_volume_attachments(context, instance, bdms)

        block_device_info = self._get_instance_block_device_info(
            context, instance, refresh_conn_info=True, bdms=bdms)

        # NOTE(mriedem): If the original vm_state was STOPPED, we don't
        # automatically power on the instance after it's migrated
        power_on = old_vm_state != vm_states.STOPPED

        try:
            self.driver.finish_migration(context, migration, instance,
                                         disk_info,
                                         network_info,
                                         image_meta, resize_instance,
                                         block_device_info, power_on)
        except Exception:
            with excutils.save_and_reraise_exception():
                if old_instance_type_id != new_instance_type_id:
                    self._set_instance_info(instance,
                                            old_instance_type)

        # Now complete any volume attachments that were previously updated.
        self._complete_volume_attachments(context, bdms)

        migration.status = 'finished'
        with migration.obj_as_admin():
            migration.save()

        instance.vm_state = vm_states.RESIZED
        instance.task_state = None
        instance.launched_at = timeutils.utcnow()
        instance.save(expected_task_state=task_states.RESIZE_FINISH)

        return network_info

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def finish_resize(self, context, disk_info, image, instance,
                      migration):
        """Completes the migration process.

        Sets up the newly transferred disk and turns on the instance at its
        new host machine.

        """
        try:
            self._finish_resize_helper(context, disk_info, image, instance,
                                       migration)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._revert_allocation(context, instance, migration)

    def _finish_resize_helper(self, context, disk_info, image, instance,
                              migration):
        """Completes the migration process.

        The caller must revert the instance's allocations if the migration
        process failed.
        """
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)

        with self._error_out_instance_on_exception(context, instance), \
             errors_out_migration_ctxt(migration):
            image_meta = objects.ImageMeta.from_dict(image)
            network_info = self._finish_resize(context, instance, migration,
                                               disk_info, image_meta, bdms)

        # TODO(melwitt): We should clean up instance console tokens here. The
        # instance is on a new host and will need to establish a new console
        # connection.
        self._update_scheduler_instance_info(context, instance)
        self._notify_about_instance_usage(
            context, instance, "finish_resize.end",
            network_info=network_info)
        compute_utils.notify_about_instance_action(context, instance,
               self.host, action=fields.NotificationAction.RESIZE_FINISH,
               phase=fields.NotificationPhase.END, bdms=bdms)

    @wrap_exception()
    @wrap_instance_fault
    def add_fixed_ip_to_instance(self, context, network_id, instance):
        """Calls network_api to add new fixed_ip to instance
        then injects the new network info and resets instance networking.

        """
        self._notify_about_instance_usage(
                context, instance, "create_ip.start")

        network_info = self.network_api.add_fixed_ip_to_instance(context,
                                                                 instance,
                                                                 network_id)
        self._inject_network_info(context, instance, network_info)
        self.reset_network(context, instance)

        # NOTE(russellb) We just want to bump updated_at.  See bug 1143466.
        instance.updated_at = timeutils.utcnow()
        instance.save()

        self._notify_about_instance_usage(
            context, instance, "create_ip.end", network_info=network_info)

    @wrap_exception()
    @wrap_instance_fault
    def remove_fixed_ip_from_instance(self, context, address, instance):
        """Calls network_api to remove existing fixed_ip from instance
        by injecting the altered network info and resetting
        instance networking.
        """
        self._notify_about_instance_usage(
                context, instance, "delete_ip.start")

        network_info = self.network_api.remove_fixed_ip_from_instance(context,
                                                                      instance,
                                                                      address)
        self._inject_network_info(context, instance, network_info)
        self.reset_network(context, instance)

        # NOTE(russellb) We just want to bump updated_at.  See bug 1143466.
        instance.updated_at = timeutils.utcnow()
        instance.save()

        self._notify_about_instance_usage(
            context, instance, "delete_ip.end", network_info=network_info)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def pause_instance(self, context, instance):
        """Pause an instance on this host."""
        context = context.elevated()
        LOG.info('Pausing', instance=instance)
        self._notify_about_instance_usage(context, instance, 'pause.start')
        compute_utils.notify_about_instance_action(context, instance,
               self.host, action=fields.NotificationAction.PAUSE,
               phase=fields.NotificationPhase.START)
        self.driver.pause(instance)
        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.PAUSED
        instance.task_state = None
        instance.save(expected_task_state=task_states.PAUSING)
        self._notify_about_instance_usage(context, instance, 'pause.end')
        compute_utils.notify_about_instance_action(context, instance,
               self.host, action=fields.NotificationAction.PAUSE,
               phase=fields.NotificationPhase.END)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def unpause_instance(self, context, instance):
        """Unpause a paused instance on this host."""
        context = context.elevated()
        LOG.info('Unpausing', instance=instance)
        self._notify_about_instance_usage(context, instance, 'unpause.start')
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.UNPAUSE,
            phase=fields.NotificationPhase.START)
        self.driver.unpause(instance)
        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.save(expected_task_state=task_states.UNPAUSING)
        self._notify_about_instance_usage(context, instance, 'unpause.end')
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.UNPAUSE,
            phase=fields.NotificationPhase.END)

    @wrap_exception()
    def host_power_action(self, context, action):
        """Reboots, shuts down or powers up the host."""
        return self.driver.host_power_action(action)

    @wrap_exception()
    def host_maintenance_mode(self, context, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        return self.driver.host_maintenance_mode(host, mode)

    @wrap_exception()
    def set_host_enabled(self, context, enabled):
        """Sets the specified host's ability to accept new instances."""
        return self.driver.set_host_enabled(enabled)

    @wrap_exception()
    def get_host_uptime(self, context):
        """Returns the result of calling "uptime" on the target host."""
        return self.driver.get_host_uptime()

    @wrap_exception()
    @wrap_instance_fault
    def get_diagnostics(self, context, instance):
        """Retrieve diagnostics for an instance on this host."""
        current_power_state = self._get_power_state(context, instance)
        if current_power_state == power_state.RUNNING:
            LOG.info("Retrieving diagnostics", instance=instance)
            return self.driver.get_diagnostics(instance)
        else:
            raise exception.InstanceInvalidState(
                attr='power state',
                instance_uuid=instance.uuid,
                state=power_state.STATE_MAP[instance.power_state],
                method='get_diagnostics')

    @wrap_exception()
    @wrap_instance_fault
    def get_instance_diagnostics(self, context, instance):
        """Retrieve diagnostics for an instance on this host."""
        current_power_state = self._get_power_state(context, instance)
        if current_power_state == power_state.RUNNING:
            LOG.info("Retrieving diagnostics", instance=instance)
            return self.driver.get_instance_diagnostics(instance)
        else:
            raise exception.InstanceInvalidState(
                attr='power state',
                instance_uuid=instance.uuid,
                state=power_state.STATE_MAP[instance.power_state],
                method='get_diagnostics')

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def suspend_instance(self, context, instance):
        """Suspend the given instance."""
        context = context.elevated()

        # Store the old state
        instance.system_metadata['old_vm_state'] = instance.vm_state
        self._notify_about_instance_usage(context, instance, 'suspend.start')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.SUSPEND,
                phase=fields.NotificationPhase.START)
        with self._error_out_instance_on_exception(context, instance,
             instance_state=instance.vm_state):
            self.driver.suspend(context, instance)
        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.SUSPENDED
        instance.task_state = None
        instance.save(expected_task_state=task_states.SUSPENDING)
        self._notify_about_instance_usage(context, instance, 'suspend.end')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.SUSPEND,
                phase=fields.NotificationPhase.END)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def resume_instance(self, context, instance):
        """Resume the given suspended instance."""
        context = context.elevated()
        LOG.info('Resuming', instance=instance)

        self._notify_about_instance_usage(context, instance, 'resume.start')

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)
        block_device_info = self._get_instance_block_device_info(
            context, instance, bdms=bdms)

        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.RESUME,
            phase=fields.NotificationPhase.START, bdms=bdms)

        network_info = self.network_api.get_instance_nw_info(context, instance)

        with self._error_out_instance_on_exception(context, instance,
             instance_state=instance.vm_state):
            self.driver.resume(context, instance, network_info,
                               block_device_info)

        instance.power_state = self._get_power_state(context, instance)

        # We default to the ACTIVE state for backwards compatibility
        instance.vm_state = instance.system_metadata.pop('old_vm_state',
                                                         vm_states.ACTIVE)

        instance.task_state = None
        instance.save(expected_task_state=task_states.RESUMING)
        self._notify_about_instance_usage(context, instance, 'resume.end')
        compute_utils.notify_about_instance_action(context, instance,
            self.host, action=fields.NotificationAction.RESUME,
            phase=fields.NotificationPhase.END, bdms=bdms)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def shelve_instance(self, context, instance, image_id,
                        clean_shutdown):
        """Shelve an instance.

        This should be used when you want to take a snapshot of the instance.
        It also adds system_metadata that can be used by a periodic task to
        offload the shelved instance after a period of time.

        :param context: request context
        :param instance: an Instance object
        :param image_id: an image id to snapshot to.
        :param clean_shutdown: give the GuestOS a chance to stop
        """

        @utils.synchronized(instance.uuid)
        def do_shelve_instance():
            self._shelve_instance(context, instance, image_id, clean_shutdown)
        do_shelve_instance()

    def _shelve_instance(self, context, instance, image_id,
                         clean_shutdown):
        LOG.info('Shelving', instance=instance)
        offload = CONF.shelved_offload_time == 0
        if offload:
            # Get the BDMs early so we can pass them into versioned
            # notifications since _shelve_offload_instance needs the
            # BDMs anyway.
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
        else:
            bdms = None
        compute_utils.notify_usage_exists(self.notifier, context, instance,
                                          self.host, current_period=True)
        self._notify_about_instance_usage(context, instance, 'shelve.start')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.SHELVE,
                phase=fields.NotificationPhase.START, bdms=bdms)

        def update_task_state(task_state, expected_state=task_states.SHELVING):
            shelving_state_map = {
                    task_states.IMAGE_PENDING_UPLOAD:
                        task_states.SHELVING_IMAGE_PENDING_UPLOAD,
                    task_states.IMAGE_UPLOADING:
                        task_states.SHELVING_IMAGE_UPLOADING,
                    task_states.SHELVING: task_states.SHELVING}
            task_state = shelving_state_map[task_state]
            expected_state = shelving_state_map[expected_state]
            instance.task_state = task_state
            instance.save(expected_task_state=expected_state)
        # Do not attempt a clean shutdown of a paused guest since some
        # hypervisors will fail the clean shutdown if the guest is not
        # running.
        if instance.power_state == power_state.PAUSED:
            clean_shutdown = False
        self._power_off_instance(context, instance, clean_shutdown)
        self.driver.snapshot(context, instance, image_id, update_task_state)

        instance.system_metadata['shelved_at'] = timeutils.utcnow().isoformat()
        instance.system_metadata['shelved_image_id'] = image_id
        instance.system_metadata['shelved_host'] = self.host
        instance.vm_state = vm_states.SHELVED
        instance.task_state = None
        if CONF.shelved_offload_time == 0:
            instance.task_state = task_states.SHELVING_OFFLOADING
        instance.power_state = self._get_power_state(context, instance)
        instance.save(expected_task_state=[
                task_states.SHELVING,
                task_states.SHELVING_IMAGE_UPLOADING])

        self._notify_about_instance_usage(context, instance, 'shelve.end')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.SHELVE,
                phase=fields.NotificationPhase.END, bdms=bdms)

        if offload:
            self._shelve_offload_instance(context, instance,
                                          clean_shutdown=False, bdms=bdms)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def shelve_offload_instance(self, context, instance, clean_shutdown):
        """Remove a shelved instance from the hypervisor.

        This frees up those resources for use by other instances, but may lead
        to slower unshelve times for this instance.  This method is used by
        volume backed instances since restoring them doesn't involve the
        potentially large download of an image.

        :param context: request context
        :param instance: nova.objects.instance.Instance
        :param clean_shutdown: give the GuestOS a chance to stop
        """

        @utils.synchronized(instance.uuid)
        def do_shelve_offload_instance():
            self._shelve_offload_instance(context, instance, clean_shutdown)
        do_shelve_offload_instance()

    def _shelve_offload_instance(self, context, instance, clean_shutdown,
                                 bdms=None):
        LOG.info('Shelve offloading', instance=instance)
        if bdms is None:
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
        self._notify_about_instance_usage(context, instance,
                'shelve_offload.start')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.SHELVE_OFFLOAD,
                phase=fields.NotificationPhase.START, bdms=bdms)

        self._power_off_instance(context, instance, clean_shutdown)
        current_power_state = self._get_power_state(context, instance)

        self.network_api.cleanup_instance_network_on_host(context, instance,
                                                          instance.host)
        network_info = self.network_api.get_instance_nw_info(context, instance)

        block_device_info = self._get_instance_block_device_info(context,
                                                                 instance,
                                                                 bdms=bdms)
        self.driver.destroy(context, instance, network_info,
                block_device_info)

        # the instance is going to be removed from the host so we want to
        # terminate all the connections with the volume server and the host
        self._terminate_volume_connections(context, instance, bdms)

        instance.power_state = current_power_state
        # NOTE(mriedem): The vm_state has to be set before updating the
        # resource tracker, see vm_states.ALLOW_RESOURCE_REMOVAL. The host/node
        # values cannot be nulled out until after updating the resource tracker
        # though.
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = None
        instance.save(expected_task_state=[task_states.SHELVING,
                                           task_states.SHELVING_OFFLOADING])

        # NOTE(ndipanov): Free resources from the resource tracker
        self._update_resource_tracker(context, instance)

        rt = self._get_resource_tracker()
        rt.delete_allocation_for_shelve_offloaded_instance(context, instance)

        # NOTE(sfinucan): RPC calls should no longer be attempted against this
        # instance, so ensure any calls result in errors
        self._nil_out_instance_obj_host_and_node(instance)
        instance.save(expected_task_state=None)

        # TODO(melwitt): We should clean up instance console tokens here. The
        # instance has no host at this point and will need to establish a new
        # console connection in the future after it is unshelved.
        self._delete_scheduler_instance_info(context, instance.uuid)
        self._notify_about_instance_usage(context, instance,
                'shelve_offload.end')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.SHELVE_OFFLOAD,
                phase=fields.NotificationPhase.END, bdms=bdms)

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def unshelve_instance(self, context, instance, image,
                          filter_properties, node):
        """Unshelve the instance.

        :param context: request context
        :param instance: a nova.objects.instance.Instance object
        :param image: an image to build from.  If None we assume a
            volume backed instance.
        :param filter_properties: dict containing limits, retry info etc.
        :param node: target compute node
        """
        if filter_properties is None:
            filter_properties = {}

        @utils.synchronized(instance.uuid)
        def do_unshelve_instance():
            self._unshelve_instance(context, instance, image,
                                    filter_properties, node)
        do_unshelve_instance()

    def _unshelve_instance_key_scrub(self, instance):
        """Remove data from the instance that may cause side effects."""
        cleaned_keys = dict(
                key_data=instance.key_data,
                auto_disk_config=instance.auto_disk_config)
        instance.key_data = None
        instance.auto_disk_config = False
        return cleaned_keys

    def _unshelve_instance_key_restore(self, instance, keys):
        """Restore previously scrubbed keys before saving the instance."""
        instance.update(keys)

    def _unshelve_instance(self, context, instance, image, filter_properties,
                           node):
        LOG.info('Unshelving', instance=instance)
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)

        self._notify_about_instance_usage(context, instance, 'unshelve.start')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.UNSHELVE,
                phase=fields.NotificationPhase.START, bdms=bdms)

        instance.task_state = task_states.SPAWNING
        instance.save()

        block_device_info = self._prep_block_device(context, instance, bdms)
        scrubbed_keys = self._unshelve_instance_key_scrub(instance)

        if node is None:
            node = self._get_nodename(instance)

        rt = self._get_resource_tracker()
        limits = filter_properties.get('limits', {})

        allocations = self.reportclient.get_allocations_for_consumer(
            context, instance.uuid)

        shelved_image_ref = instance.image_ref
        if image:
            instance.image_ref = image['id']
            image_meta = objects.ImageMeta.from_dict(image)
        else:
            image_meta = objects.ImageMeta.from_dict(
                utils.get_image_from_system_metadata(
                    instance.system_metadata))

        self.network_api.setup_instance_network_on_host(context, instance,
                                                        self.host)
        network_info = self.network_api.get_instance_nw_info(context, instance)
        try:
            with rt.instance_claim(context, instance, node, limits):
                self.driver.spawn(context, instance, image_meta,
                                  injected_files=[],
                                  admin_password=None,
                                  allocations=allocations,
                                  network_info=network_info,
                                  block_device_info=block_device_info)
        except Exception:
            with excutils.save_and_reraise_exception(logger=LOG):
                LOG.exception('Instance failed to spawn',
                              instance=instance)
                # Cleanup allocations created by the scheduler on this host
                # since we failed to spawn the instance. We do this both if
                # the instance claim failed with ComputeResourcesUnavailable
                # or if we did claim but the spawn failed, because aborting the
                # instance claim will not remove the allocations.
                rt.reportclient.delete_allocation_for_instance(context,
                                                               instance.uuid)
                # FIXME: Umm, shouldn't we be rolling back port bindings too?
                self._terminate_volume_connections(context, instance, bdms)
                # The reverts_task_state decorator on unshelve_instance will
                # eventually save these updates.
                self._nil_out_instance_obj_host_and_node(instance)

        if image:
            instance.image_ref = shelved_image_ref
            self._delete_snapshot_of_shelved_instance(context, instance,
                                                      image['id'])

        self._unshelve_instance_key_restore(instance, scrubbed_keys)
        self._update_instance_after_spawn(context, instance)
        # Delete system_metadata for a shelved instance
        compute_utils.remove_shelved_keys_from_system_metadata(instance)

        instance.save(expected_task_state=task_states.SPAWNING)
        self._update_scheduler_instance_info(context, instance)
        self._notify_about_instance_usage(context, instance, 'unshelve.end')
        compute_utils.notify_about_instance_action(context, instance,
                self.host, action=fields.NotificationAction.UNSHELVE,
                phase=fields.NotificationPhase.END, bdms=bdms)

    @messaging.expected_exceptions(NotImplementedError)
    @wrap_instance_fault
    def reset_network(self, context, instance):
        """Reset networking on the given instance."""
        LOG.debug('Reset network', instance=instance)
        self.driver.reset_network(instance)

    def _inject_network_info(self, context, instance, network_info):
        """Inject network info for the given instance."""
        LOG.debug('Inject network info', instance=instance)
        LOG.debug('network_info to inject: |%s|', network_info,
                  instance=instance)

        self.driver.inject_network_info(instance,
                                        network_info)

    @wrap_instance_fault
    def inject_network_info(self, context, instance):
        """Inject network info, but don't return the info."""
        network_info = self.network_api.get_instance_nw_info(context, instance)
        self._inject_network_info(context, instance, network_info)

    @messaging.expected_exceptions(NotImplementedError,
                                   exception.ConsoleNotAvailable,
                                   exception.InstanceNotFound)
    @wrap_exception()
    @wrap_instance_fault
    def get_console_output(self, context, instance, tail_length):
        """Send the console output for the given instance."""
        context = context.elevated()
        LOG.info("Get console output", instance=instance)
        output = self.driver.get_console_output(context, instance)

        if type(output) is six.text_type:
            output = six.b(output)

        if tail_length is not None:
            output = self._tail_log(output, tail_length)

        return output.decode('ascii', 'replace')

    def _tail_log(self, log, length):
        try:
            length = int(length)
        except ValueError:
            length = 0

        if length == 0:
            return b''
        else:
            return b'\n'.join(log.split(b'\n')[-int(length):])

    @messaging.expected_exceptions(exception.ConsoleTypeInvalid,
                                   exception.InstanceNotReady,
                                   exception.InstanceNotFound,
                                   exception.ConsoleTypeUnavailable,
                                   NotImplementedError)
    @wrap_exception()
    @wrap_instance_fault
    def get_vnc_console(self, context, console_type, instance):
        """Return connection information for a vnc console."""
        context = context.elevated()
        LOG.debug("Getting vnc console", instance=instance)

        if not CONF.vnc.enabled:
            raise exception.ConsoleTypeUnavailable(console_type=console_type)

        if console_type == 'novnc':
            # For essex, novncproxy_base_url must include the full path
            # including the html file (like http://myhost/vnc_auto.html)
            access_url_base = CONF.vnc.novncproxy_base_url
        elif console_type == 'xvpvnc':
            access_url_base = CONF.vnc.xvpvncproxy_base_url
        else:
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        try:
            # Retrieve connect info from driver, and then decorate with our
            # access info token
            console = self.driver.get_vnc_console(context, instance)
            console_auth = objects.ConsoleAuthToken(
                context=context,
                console_type=console_type,
                host=console.host,
                port=console.port,
                internal_access_path=console.internal_access_path,
                instance_uuid=instance.uuid,
                access_url_base=access_url_base,
            )
            console_auth.authorize(CONF.consoleauth.token_ttl)
            connect_info = console.get_connection_info(
                console_auth.token, console_auth.access_url)

        except exception.InstanceNotFound:
            if instance.vm_state != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        return connect_info

    @messaging.expected_exceptions(exception.ConsoleTypeInvalid,
                                   exception.InstanceNotReady,
                                   exception.InstanceNotFound,
                                   exception.ConsoleTypeUnavailable,
                                   NotImplementedError)
    @wrap_exception()
    @wrap_instance_fault
    def get_spice_console(self, context, console_type, instance):
        """Return connection information for a spice console."""
        context = context.elevated()
        LOG.debug("Getting spice console", instance=instance)

        if not CONF.spice.enabled:
            raise exception.ConsoleTypeUnavailable(console_type=console_type)

        if console_type != 'spice-html5':
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        try:
            # Retrieve connect info from driver, and then decorate with our
            # access info token
            console = self.driver.get_spice_console(context, instance)
            console_auth = objects.ConsoleAuthToken(
                context=context,
                console_type=console_type,
                host=console.host,
                port=console.port,
                internal_access_path=console.internal_access_path,
                instance_uuid=instance.uuid,
                access_url_base=CONF.spice.html5proxy_base_url,
            )
            console_auth.authorize(CONF.consoleauth.token_ttl)
            connect_info = console.get_connection_info(
                console_auth.token, console_auth.access_url)

        except exception.InstanceNotFound:
            if instance.vm_state != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        return connect_info

    @messaging.expected_exceptions(exception.ConsoleTypeInvalid,
                                   exception.InstanceNotReady,
                                   exception.InstanceNotFound,
                                   exception.ConsoleTypeUnavailable,
                                   NotImplementedError)
    @wrap_exception()
    @wrap_instance_fault
    def get_rdp_console(self, context, console_type, instance):
        """Return connection information for a RDP console."""
        context = context.elevated()
        LOG.debug("Getting RDP console", instance=instance)

        if not CONF.rdp.enabled:
            raise exception.ConsoleTypeUnavailable(console_type=console_type)

        if console_type != 'rdp-html5':
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        try:
            # Retrieve connect info from driver, and then decorate with our
            # access info token
            console = self.driver.get_rdp_console(context, instance)
            console_auth = objects.ConsoleAuthToken(
                context=context,
                console_type=console_type,
                host=console.host,
                port=console.port,
                internal_access_path=console.internal_access_path,
                instance_uuid=instance.uuid,
                access_url_base=CONF.rdp.html5_proxy_base_url,
            )
            console_auth.authorize(CONF.consoleauth.token_ttl)
            connect_info = console.get_connection_info(
                console_auth.token, console_auth.access_url)

        except exception.InstanceNotFound:
            if instance.vm_state != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        return connect_info

    @messaging.expected_exceptions(exception.ConsoleTypeInvalid,
                                   exception.InstanceNotReady,
                                   exception.InstanceNotFound,
                                   exception.ConsoleTypeUnavailable,
                                   NotImplementedError)
    @wrap_exception()
    @wrap_instance_fault
    def get_mks_console(self, context, console_type, instance):
        """Return connection information for a MKS console."""
        context = context.elevated()
        LOG.debug("Getting MKS console", instance=instance)

        if not CONF.mks.enabled:
            raise exception.ConsoleTypeUnavailable(console_type=console_type)

        if console_type != 'webmks':
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        try:
            # Retrieve connect info from driver, and then decorate with our
            # access info token
            console = self.driver.get_mks_console(context, instance)
            console_auth = objects.ConsoleAuthToken(
                context=context,
                console_type=console_type,
                host=console.host,
                port=console.port,
                internal_access_path=console.internal_access_path,
                instance_uuid=instance.uuid,
                access_url_base=CONF.mks.mksproxy_base_url,
            )
            console_auth.authorize(CONF.consoleauth.token_ttl)
            connect_info = console.get_connection_info(
                console_auth.token, console_auth.access_url)

        except exception.InstanceNotFound:
            if instance.vm_state != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        return connect_info

    @messaging.expected_exceptions(
        exception.ConsoleTypeInvalid,
        exception.InstanceNotReady,
        exception.InstanceNotFound,
        exception.ConsoleTypeUnavailable,
        exception.SocketPortRangeExhaustedException,
        exception.ImageSerialPortNumberInvalid,
        exception.ImageSerialPortNumberExceedFlavorValue,
        NotImplementedError)
    @wrap_exception()
    @wrap_instance_fault
    def get_serial_console(self, context, console_type, instance):
        """Returns connection information for a serial console."""

        LOG.debug("Getting serial console", instance=instance)

        if not CONF.serial_console.enabled:
            raise exception.ConsoleTypeUnavailable(console_type=console_type)

        context = context.elevated()

        try:
            # Retrieve connect info from driver, and then decorate with our
            # access info token
            console = self.driver.get_serial_console(context, instance)
            console_auth = objects.ConsoleAuthToken(
                context=context,
                console_type=console_type,
                host=console.host,
                port=console.port,
                internal_access_path=console.internal_access_path,
                instance_uuid=instance.uuid,
                access_url_base=CONF.serial_console.base_url,
            )
            console_auth.authorize(CONF.consoleauth.token_ttl)
            connect_info = console.get_connection_info(
                console_auth.token, console_auth.access_url)

        except exception.InstanceNotFound:
            if instance.vm_state != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance.uuid)

        return connect_info

    @messaging.expected_exceptions(exception.ConsoleTypeInvalid,
                                   exception.InstanceNotReady,
                                   exception.InstanceNotFound)
    @wrap_exception()
    @wrap_instance_fault
    def validate_console_port(self, ctxt, instance, port, console_type):
        if console_type == "spice-html5":
            console_info = self.driver.get_spice_console(ctxt, instance)
        elif console_type == "rdp-html5":
            console_info = self.driver.get_rdp_console(ctxt, instance)
        elif console_type == "serial":
            console_info = self.driver.get_serial_console(ctxt, instance)
        elif console_type == "webmks":
            console_info = self.driver.get_mks_console(ctxt, instance)
        else:
            console_info = self.driver.get_vnc_console(ctxt, instance)

        # Some drivers may return an int on console_info.port but the port
        # variable in this method is a string, so cast to be sure we are
        # comparing the correct types.
        return str(console_info.port) == port

    @wrap_exception()
    @reverts_task_state
    @wrap_instance_fault
    def reserve_block_device_name(self, context, instance, device,
                                  volume_id, disk_bus, device_type, tag,
                                  multiattach):
        if (tag and not
                self.driver.capabilities.get('supports_tagged_attach_volume',
                                             False)):
            raise exception.VolumeTaggedAttachNotSupported()

        if (multiattach and not
                self.driver.capabilities.get('supports_multiattach', False)):
            raise exception.MultiattachNotSupportedByVirtDriver(
                volume_id=volume_id)

        @utils.synchronized(instance.uuid)
        def do_reserve():
            bdms = (
                objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid))

            # NOTE(ndipanov): We need to explicitly set all the fields on the
            #                 object so that obj_load_attr does not fail
            new_bdm = objects.BlockDeviceMapping(
                    context=context,
                    source_type='volume', destination_type='volume',
                    instance_uuid=instance.uuid, boot_index=None,
                    volume_id=volume_id,
                    device_name=device, guest_format=None,
                    disk_bus=disk_bus, device_type=device_type, tag=tag)

            new_bdm.device_name = self._get_device_name_for_instance(
                    instance, bdms, new_bdm)

            # NOTE(vish): create bdm here to avoid race condition
            new_bdm.create()
            return new_bdm

        return do_reserve()

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def attach_volume(self, context, instance, bdm):
        """Attach a volume to an instance."""
        driver_bdm = driver_block_device.convert_volume(bdm)

        @utils.synchronized(instance.uuid)
        def do_attach_volume(context, instance, driver_bdm):
            try:
                return self._attach_volume(context, instance, driver_bdm)
            except Exception:
                with excutils.save_and_reraise_exception():
                    bdm.destroy()

        do_attach_volume(context, instance, driver_bdm)

    def _attach_volume(self, context, instance, bdm):
        context = context.elevated()
        LOG.info('Attaching volume %(volume_id)s to %(mountpoint)s',
                 {'volume_id': bdm.volume_id,
                  'mountpoint': bdm['mount_device']},
                 instance=instance)
        compute_utils.notify_about_volume_attach_detach(
            context, instance, self.host,
            action=fields.NotificationAction.VOLUME_ATTACH,
            phase=fields.NotificationPhase.START,
            volume_id=bdm.volume_id)
        try:
            bdm.attach(context, instance, self.volume_api, self.driver,
                       do_driver_attach=True)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception("Failed to attach %(volume_id)s "
                              "at %(mountpoint)s",
                              {'volume_id': bdm.volume_id,
                               'mountpoint': bdm['mount_device']},
                              instance=instance)
                if bdm['attachment_id']:
                    # Try to delete the attachment to make the volume
                    # available again. Note that DriverVolumeBlockDevice
                    # may have already deleted the attachment so ignore
                    # VolumeAttachmentNotFound.
                    try:
                        self.volume_api.attachment_delete(
                            context, bdm['attachment_id'])
                    except exception.VolumeAttachmentNotFound as exc:
                        LOG.debug('Ignoring VolumeAttachmentNotFound: %s',
                                  exc, instance=instance)
                else:
                    self.volume_api.unreserve_volume(context, bdm.volume_id)
                tb = traceback.format_exc()
                compute_utils.notify_about_volume_attach_detach(
                    context, instance, self.host,
                    action=fields.NotificationAction.VOLUME_ATTACH,
                    phase=fields.NotificationPhase.ERROR,
                    exception=e,
                    volume_id=bdm.volume_id, tb=tb)

        info = {'volume_id': bdm.volume_id}
        self._notify_about_instance_usage(
            context, instance, "volume.attach", extra_usage_info=info)
        compute_utils.notify_about_volume_attach_detach(
            context, instance, self.host,
            action=fields.NotificationAction.VOLUME_ATTACH,
            phase=fields.NotificationPhase.END,
            volume_id=bdm.volume_id)

    def _notify_volume_usage_detach(self, context, instance, bdm):
        if CONF.volume_usage_poll_interval <= 0:
            return

        mp = bdm.device_name
        # Handle bootable volumes which will not contain /dev/
        if '/dev/' in mp:
            mp = mp[5:]
        try:
            vol_stats = self.driver.block_stats(instance, mp)
            if vol_stats is None:
                return
        except NotImplementedError:
            return

        LOG.debug("Updating volume usage cache with totals", instance=instance)
        rd_req, rd_bytes, wr_req, wr_bytes, flush_ops = vol_stats
        vol_usage = objects.VolumeUsage(context)
        vol_usage.volume_id = bdm.volume_id
        vol_usage.instance_uuid = instance.uuid
        vol_usage.project_id = instance.project_id
        vol_usage.user_id = instance.user_id
        vol_usage.availability_zone = instance.availability_zone
        vol_usage.curr_reads = rd_req
        vol_usage.curr_read_bytes = rd_bytes
        vol_usage.curr_writes = wr_req
        vol_usage.curr_write_bytes = wr_bytes
        vol_usage.save(update_totals=True)
        self.notifier.info(context, 'volume.usage',
                           compute_utils.usage_volume_info(vol_usage))

    def _detach_volume(self, context, bdm, instance, destroy_bdm=True,
                       attachment_id=None):
        """Detach a volume from an instance.

        :param context: security context
        :param bdm: nova.objects.BlockDeviceMapping volume bdm to detach
        :param instance: the Instance object to detach the volume from
        :param destroy_bdm: if True, the corresponding BDM entry will be marked
                            as deleted. Disabling this is useful for operations
                            like rebuild, when we don't want to destroy BDM
        :param attachment_id: The volume attachment_id for the given instance
                              and volume.
        """
        volume_id = bdm.volume_id
        compute_utils.notify_about_volume_attach_detach(
            context, instance, self.host,
            action=fields.NotificationAction.VOLUME_DETACH,
            phase=fields.NotificationPhase.START,
            volume_id=volume_id)

        self._notify_volume_usage_detach(context, instance, bdm)

        LOG.info('Detaching volume %(volume_id)s',
                 {'volume_id': volume_id}, instance=instance)

        driver_bdm = driver_block_device.convert_volume(bdm)
        driver_bdm.detach(context, instance, self.volume_api, self.driver,
                          attachment_id=attachment_id, destroy_bdm=destroy_bdm)

        info = dict(volume_id=volume_id)
        self._notify_about_instance_usage(
            context, instance, "volume.detach", extra_usage_info=info)
        compute_utils.notify_about_volume_attach_detach(
            context, instance, self.host,
            action=fields.NotificationAction.VOLUME_DETACH,
            phase=fields.NotificationPhase.END,
            volume_id=volume_id)

        if 'tag' in bdm and bdm.tag:
            self._delete_disk_metadata(instance, bdm)
        if destroy_bdm:
            bdm.destroy()

    def _delete_disk_metadata(self, instance, bdm):
        for device in instance.device_metadata.devices:
            if isinstance(device, objects.DiskMetadata):
                if 'serial' in device:
                    if device.serial == bdm.volume_id:
                        instance.device_metadata.devices.remove(device)
                        instance.save()
                        break
                else:
                    # NOTE(artom) We log the entire device object because all
                    # fields are nullable and may not be set
                    LOG.warning('Unable to determine whether to clean up '
                                'device metadata for disk %s', device,
                                instance=instance)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def detach_volume(self, context, volume_id, instance, attachment_id):
        """Detach a volume from an instance.

        :param context: security context
        :param volume_id: the volume id
        :param instance: the Instance object to detach the volume from
        :param attachment_id: The volume attachment_id for the given instance
                              and volume.

        """
        @utils.synchronized(instance.uuid)
        def do_detach_volume(context, volume_id, instance, attachment_id):
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                    context, volume_id, instance.uuid)
            self._detach_volume(context, bdm, instance,
                                attachment_id=attachment_id)

        do_detach_volume(context, volume_id, instance, attachment_id)

    def _init_volume_connection(self, context, new_volume,
                                old_volume_id, connector, bdm,
                                new_attachment_id, mountpoint):
        new_volume_id = new_volume['id']
        if new_attachment_id is None:
            # We're dealing with an old-style attachment so initialize the
            # connection so we can get the connection_info.
            new_cinfo = self.volume_api.initialize_connection(context,
                                                              new_volume_id,
                                                              connector)
        else:
            # Check for multiattach on the new volume and if True, check to
            # see if the virt driver supports multiattach.
            # TODO(mriedem): This is copied from DriverVolumeBlockDevice
            # and should be consolidated into some common code at some point.
            vol_multiattach = new_volume.get('multiattach', False)
            virt_multiattach = self.driver.capabilities.get(
                'supports_multiattach', False)
            if vol_multiattach and not virt_multiattach:
                raise exception.MultiattachNotSupportedByVirtDriver(
                    volume_id=new_volume_id)

            # This is a new style attachment and the API created the new
            # volume attachment and passed the id to the compute over RPC.
            # At this point we need to update the new volume attachment with
            # the host connector, which will give us back the new attachment
            # connection_info.
            new_cinfo = self.volume_api.attachment_update(
                context, new_attachment_id, connector,
                mountpoint)['connection_info']

            if vol_multiattach:
                # This will be used by the volume driver to determine the
                # proper disk configuration.
                new_cinfo['multiattach'] = True

        old_cinfo = jsonutils.loads(bdm['connection_info'])
        if old_cinfo and 'serial' not in old_cinfo:
            old_cinfo['serial'] = old_volume_id
        # NOTE(lyarwood): serial is not always present in the returned
        # connection_info so set it if it is missing as we do in
        # DriverVolumeBlockDevice.attach().
        if 'serial' not in new_cinfo:
            new_cinfo['serial'] = new_volume_id
        return (old_cinfo, new_cinfo)

    def _swap_volume(self, context, instance, bdm, connector,
                     old_volume_id, new_volume, resize_to,
                     new_attachment_id, is_cinder_migration):
        new_volume_id = new_volume['id']
        mountpoint = bdm['device_name']
        failed = False
        new_cinfo = None
        try:
            old_cinfo, new_cinfo = self._init_volume_connection(
                context, new_volume, old_volume_id, connector,
                bdm, new_attachment_id, mountpoint)
            # NOTE(lyarwood): The Libvirt driver, the only virt driver
            # currently implementing swap_volume, will modify the contents of
            # new_cinfo when connect_volume is called. This is then saved to
            # the BDM in swap_volume for future use outside of this flow.
            msg = ("swap_volume: Calling driver volume swap with "
                   "connection infos: new: %(new_cinfo)s; "
                   "old: %(old_cinfo)s" %
                   {'new_cinfo': new_cinfo, 'old_cinfo': old_cinfo})
            # Both new and old info might contain password
            LOG.debug(strutils.mask_password(msg), instance=instance)

            self.driver.swap_volume(context, old_cinfo, new_cinfo, instance,
                                    mountpoint, resize_to)
            if new_attachment_id:
                self.volume_api.attachment_complete(context, new_attachment_id)
            msg = ("swap_volume: Driver volume swap returned, new "
                   "connection_info is now : %(new_cinfo)s" %
                   {'new_cinfo': new_cinfo})
            LOG.debug(strutils.mask_password(msg))
        except Exception as ex:
            failed = True
            with excutils.save_and_reraise_exception():
                tb = traceback.format_exc()
                compute_utils.notify_about_volume_swap(
                    context, instance, self.host,
                    fields.NotificationPhase.ERROR,
                    old_volume_id, new_volume_id, ex, tb)
                if new_cinfo:
                    msg = ("Failed to swap volume %(old_volume_id)s "
                           "for %(new_volume_id)s")
                    LOG.exception(msg, {'old_volume_id': old_volume_id,
                                        'new_volume_id': new_volume_id},
                                  instance=instance)
                else:
                    msg = ("Failed to connect to volume %(volume_id)s "
                           "with volume at %(mountpoint)s")
                    LOG.exception(msg, {'volume_id': new_volume_id,
                                        'mountpoint': bdm['device_name']},
                                  instance=instance)

                # The API marked the volume as 'detaching' for the old volume
                # so we need to roll that back so the volume goes back to
                # 'in-use' state.
                self.volume_api.roll_detaching(context, old_volume_id)

                if new_attachment_id is None:
                    # The API reserved the new volume so it would be in
                    # 'attaching' status, so we need to unreserve it so it
                    # goes back to 'available' status.
                    self.volume_api.unreserve_volume(context, new_volume_id)
                else:
                    # This is a new style attachment for the new volume, which
                    # was created in the API. We just need to delete it here
                    # to put the new volume back into 'available' status.
                    self.volume_api.attachment_delete(
                        context, new_attachment_id)
        finally:
            # TODO(mriedem): This finally block is terribly confusing and is
            # trying to do too much. We should consider removing the finally
            # block and move whatever needs to happen on success and failure
            # into the blocks above for clarity, even if it means a bit of
            # redundant code.
            conn_volume = new_volume_id if failed else old_volume_id
            if new_cinfo:
                LOG.debug("swap_volume: removing Cinder connection "
                          "for volume %(volume)s", {'volume': conn_volume},
                          instance=instance)
                if bdm.attachment_id is None:
                    # This is the pre-3.44 flow for new-style volume
                    # attachments so just terminate the connection.
                    self.volume_api.terminate_connection(context,
                                                         conn_volume,
                                                         connector)
                else:
                    # This is a new style volume attachment. If we failed, then
                    # the new attachment was already deleted above in the
                    # exception block and we have nothing more to do here. If
                    # swap_volume was successful in the driver, then we need to
                    # "detach" the original attachment by deleting it.
                    if not failed:
                        self.volume_api.attachment_delete(
                            context, bdm.attachment_id)

            # Need to make some decisions based on whether this was
            # a Cinder initiated migration or not. The callback to
            # migration completion isn't needed in the case of a
            # nova initiated simple swap of two volume
            # "volume-update" call so skip that. The new attachment
            # scenarios will give us a new attachment record and
            # that's what we want.
            if bdm.attachment_id and not is_cinder_migration:
                # we don't callback to cinder
                comp_ret = {'save_volume_id': new_volume_id}
            else:
                # NOTE(lyarwood): The following call to
                # os-migrate-volume-completion returns a dict containing
                # save_volume_id, this volume id has two possible values :
                # 1. old_volume_id if we are migrating (retyping) volumes
                # 2. new_volume_id if we are swapping between two existing
                #    volumes
                # This volume id is later used to update the volume_id and
                # connection_info['serial'] of the BDM.
                comp_ret = self.volume_api.migrate_volume_completion(
                                                          context,
                                                          old_volume_id,
                                                          new_volume_id,
                                                          error=failed)
                LOG.debug("swap_volume: Cinder migrate_volume_completion "
                          "returned: %(comp_ret)s", {'comp_ret': comp_ret},
                          instance=instance)

        return (comp_ret, new_cinfo)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def swap_volume(self, context, old_volume_id, new_volume_id, instance,
                    new_attachment_id):
        """Swap volume for an instance."""
        context = context.elevated()

        compute_utils.notify_about_volume_swap(
            context, instance, self.host,
            fields.NotificationPhase.START,
            old_volume_id, new_volume_id)

        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                context, old_volume_id, instance.uuid)
        connector = self.driver.get_volume_connector(instance)

        resize_to = 0
        old_volume = self.volume_api.get(context, old_volume_id)
        # Yes this is a tightly-coupled state check of what's going on inside
        # cinder, but we need this while we still support old (v1/v2) and
        # new style attachments (v3.44). Once we drop support for old style
        # attachments we could think about cleaning up the cinder-initiated
        # swap volume API flows.
        is_cinder_migration = (
            True if old_volume['status'] in ('retyping',
                                             'migrating') else False)
        old_vol_size = old_volume['size']
        new_volume = self.volume_api.get(context, new_volume_id)
        new_vol_size = new_volume['size']
        if new_vol_size > old_vol_size:
            resize_to = new_vol_size

        LOG.info('Swapping volume %(old_volume)s for %(new_volume)s',
                 {'old_volume': old_volume_id, 'new_volume': new_volume_id},
                 instance=instance)
        comp_ret, new_cinfo = self._swap_volume(context,
                                                instance,
                                                bdm,
                                                connector,
                                                old_volume_id,
                                                new_volume,
                                                resize_to,
                                                new_attachment_id,
                                                is_cinder_migration)

        # NOTE(lyarwood): Update the BDM with the modified new_cinfo and
        # correct volume_id returned by Cinder.
        save_volume_id = comp_ret['save_volume_id']
        new_cinfo['serial'] = save_volume_id
        values = {
            'connection_info': jsonutils.dumps(new_cinfo),
            'source_type': 'volume',
            'destination_type': 'volume',
            'snapshot_id': None,
            'volume_id': save_volume_id,
            'no_device': None}

        if resize_to:
            values['volume_size'] = resize_to

        if new_attachment_id is not None:
            # This was a volume swap for a new-style attachment so we
            # need to update the BDM attachment_id for the new attachment.
            values['attachment_id'] = new_attachment_id

        LOG.debug("swap_volume: Updating volume %(volume_id)s BDM record with "
                  "%(updates)s", {'volume_id': bdm.volume_id,
                                  'updates': values},
                  instance=instance)
        bdm.update(values)
        bdm.save()

        compute_utils.notify_about_volume_swap(
            context, instance, self.host,
            fields.NotificationPhase.END,
            old_volume_id, new_volume_id)

    @wrap_exception()
    def remove_volume_connection(self, context, volume_id, instance):
        """Remove the volume connection on this host

        Detach the volume from this instance on this host, and if this is
        the cinder v2 flow, call cinder to terminate the connection.
        """
        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                    context, volume_id, instance.uuid)
            driver_bdm = driver_block_device.convert_volume(bdm)
            driver_bdm.driver_detach(context, instance,
                                     self.volume_api, self.driver)
            if bdm.attachment_id is None:
                # cinder v2 api flow
                connector = self.driver.get_volume_connector(instance)
                self.volume_api.terminate_connection(context, volume_id,
                                                     connector)
        except exception.NotFound:
            pass

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def attach_interface(self, context, instance, network_id, port_id,
                         requested_ip, tag):
        """Use hotplug to add an network adapter to an instance."""
        if not self.driver.capabilities.get('supports_attach_interface',
                                            False):
            raise exception.AttachInterfaceNotSupported(
                instance_uuid=instance.uuid)
        if (tag and not
            self.driver.capabilities.get('supports_tagged_attach_interface',
                                         False)):
            raise exception.NetworkInterfaceTaggedAttachNotSupported()

        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.INTERFACE_ATTACH,
            phase=fields.NotificationPhase.START)

        bind_host_id = self.driver.network_binding_host_id(context, instance)
        network_info = self.network_api.allocate_port_for_instance(
            context, instance, port_id, network_id, requested_ip,
            bind_host_id=bind_host_id, tag=tag)
        if len(network_info) != 1:
            LOG.error('allocate_port_for_instance returned %(ports)s '
                      'ports', {'ports': len(network_info)})
            # TODO(elod.illes): an instance.interface_attach.error notification
            # should be sent here
            raise exception.InterfaceAttachFailed(
                    instance_uuid=instance.uuid)
        image_meta = objects.ImageMeta.from_instance(instance)

        try:
            self.driver.attach_interface(context, instance, image_meta,
                                         network_info[0])
        except exception.NovaException as ex:
            port_id = network_info[0].get('id')
            LOG.warning("attach interface failed , try to deallocate "
                        "port %(port_id)s, reason: %(msg)s",
                        {'port_id': port_id, 'msg': ex},
                        instance=instance)
            try:
                self.network_api.deallocate_port_for_instance(
                    context, instance, port_id)
            except Exception:
                LOG.warning("deallocate port %(port_id)s failed",
                            {'port_id': port_id}, instance=instance)

            tb = traceback.format_exc()
            compute_utils.notify_about_instance_action(
                context, instance, self.host,
                action=fields.NotificationAction.INTERFACE_ATTACH,
                phase=fields.NotificationPhase.ERROR,
                exception=ex, tb=tb)

            raise exception.InterfaceAttachFailed(
                instance_uuid=instance.uuid)

        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.INTERFACE_ATTACH,
            phase=fields.NotificationPhase.END)

        return network_info[0]

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def detach_interface(self, context, instance, port_id):
        """Detach a network adapter from an instance."""
        network_info = instance.info_cache.network_info
        condemned = None
        for vif in network_info:
            if vif['id'] == port_id:
                condemned = vif
                break
        if condemned is None:
            raise exception.PortNotFound(_("Port %s is not "
                                           "attached") % port_id)

        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.INTERFACE_DETACH,
            phase=fields.NotificationPhase.START)

        try:
            self.driver.detach_interface(context, instance, condemned)
        except exception.NovaException as ex:
            # If the instance was deleted before the interface was detached,
            # just log it at debug.
            log_level = (logging.DEBUG
                         if isinstance(ex, exception.InstanceNotFound)
                         else logging.WARNING)
            LOG.log(log_level,
                    "Detach interface failed, port_id=%(port_id)s, reason: "
                    "%(msg)s", {'port_id': port_id, 'msg': ex},
                    instance=instance)
            raise exception.InterfaceDetachFailed(instance_uuid=instance.uuid)
        else:
            try:
                self.network_api.deallocate_port_for_instance(
                    context, instance, port_id)
            except Exception as ex:
                with excutils.save_and_reraise_exception():
                    # Since this is a cast operation, log the failure for
                    # triage.
                    LOG.warning('Failed to deallocate port %(port_id)s '
                                'for instance. Error: %(error)s',
                                {'port_id': port_id, 'error': ex},
                                instance=instance)

        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.INTERFACE_DETACH,
            phase=fields.NotificationPhase.END)

    def _get_compute_info(self, context, host):
        return objects.ComputeNode.get_first_node_by_host_for_old_compat(
            context, host)

    @wrap_exception()
    def check_instance_shared_storage(self, ctxt, instance, data):
        """Check if the instance files are shared

        :param ctxt: security context
        :param instance: dict of instance data
        :param data: result of driver.check_instance_shared_storage_local

        Returns True if instance disks located on shared storage and
        False otherwise.
        """
        return self.driver.check_instance_shared_storage_remote(ctxt, data)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def check_can_live_migrate_destination(self, ctxt, instance,
                                           block_migration, disk_over_commit):
        """Check if it is possible to execute live migration.

        This runs checks on the destination host, and then calls
        back to the source host to check the results.

        :param context: security context
        :param instance: dict of instance data
        :param block_migration: if true, prepare for block migration
                                if None, calculate it in driver
        :param disk_over_commit: if true, allow disk over commit
                                 if None, ignore disk usage checking
        :returns: a dict containing migration info
        """
        src_compute_info = obj_base.obj_to_primitive(
            self._get_compute_info(ctxt, instance.host))
        dst_compute_info = obj_base.obj_to_primitive(
            self._get_compute_info(ctxt, CONF.host))
        dest_check_data = self.driver.check_can_live_migrate_destination(ctxt,
            instance, src_compute_info, dst_compute_info,
            block_migration, disk_over_commit)
        LOG.debug('destination check data is %s', dest_check_data)
        try:
            migrate_data = self.compute_rpcapi.\
                                check_can_live_migrate_source(ctxt, instance,
                                                              dest_check_data)
        finally:
            self.driver.cleanup_live_migration_destination_check(ctxt,
                    dest_check_data)
        return migrate_data

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param ctxt: security context
        :param instance: dict of instance data
        :param dest_check_data: result of check_can_live_migrate_destination
        :returns: a dict containing migration info
        """
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            ctxt, instance.uuid)
        is_volume_backed = compute_utils.is_volume_backed_instance(
            ctxt, instance, bdms)
        dest_check_data.is_volume_backed = is_volume_backed
        block_device_info = self._get_instance_block_device_info(
                            ctxt, instance, refresh_conn_info=False, bdms=bdms)
        result = self.driver.check_can_live_migrate_source(ctxt, instance,
                                                           dest_check_data,
                                                           block_device_info)
        LOG.debug('source check data is %s', result)
        return result

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def pre_live_migration(self, context, instance, block_migration, disk,
                           migrate_data):
        """Preparations for live migration at dest host.

        :param context: security context
        :param instance: dict of instance data
        :param block_migration: if true, prepare for block migration
        :param disk: disk info of instance
        :param migrate_data: A dict or LiveMigrateData object holding data
                             required for live migration without shared
                             storage.
        :returns: migrate_data containing additional migration info
        """
        LOG.debug('pre_live_migration data is %s', migrate_data)

        migrate_data.old_vol_attachment_ids = {}
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)
        network_info = self.network_api.get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(
            context, instance, "live_migration.pre.start",
            network_info=network_info)
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_PRE,
            phase=fields.NotificationPhase.START, bdms=bdms)

        connector = self.driver.get_volume_connector(instance)
        try:
            for bdm in bdms:
                if bdm.is_volume and bdm.attachment_id is not None:
                    # This bdm uses the new cinder v3.44 API.
                    # We will create a new attachment for this
                    # volume on this migration destination host. The old
                    # attachment will be deleted on the source host
                    # when the migration succeeds. The old attachment_id
                    # is stored in dict with the key being the bdm.volume_id
                    # so it can be restored on rollback.
                    #
                    # Also note that attachment_update is not needed as we
                    # are providing the connector in the create call.
                    attach_ref = self.volume_api.attachment_create(
                        context, bdm.volume_id, bdm.instance_uuid,
                        connector=connector, mountpoint=bdm.device_name)

                    # save current attachment so we can detach it on success,
                    # or restore it on a rollback.
                    # NOTE(mdbooth): This data is no longer used by the source
                    # host since change I0390c9ff. We can't remove it until we
                    # are sure the source host has been upgraded.
                    migrate_data.old_vol_attachment_ids[bdm.volume_id] = \
                        bdm.attachment_id

                    # update the bdm with the new attachment_id.
                    bdm.attachment_id = attach_ref['id']
                    bdm.save()

            block_device_info = self._get_instance_block_device_info(
                                context, instance, refresh_conn_info=True,
                                bdms=bdms)

            # The driver pre_live_migration will plug vifs on the host. We call
            # plug_vifs before calling ensure_filtering_rules_for_instance, to
            # ensure bridge is set up.
            migrate_data = self.driver.pre_live_migration(context,
                                           instance,
                                           block_device_info,
                                           network_info,
                                           disk,
                                           migrate_data)
            LOG.debug('driver pre_live_migration data is %s', migrate_data)
            # driver.pre_live_migration is what plugs vifs on the destination
            # host so now we can set the wait_for_vif_plugged flag in the
            # migrate_data object which the source compute will use to
            # determine if it should wait for a 'network-vif-plugged' event
            # from neutron before starting the actual guest transfer in the
            # hypervisor
            migrate_data.wait_for_vif_plugged = (
                CONF.compute.live_migration_wait_for_vif_plug)

            # NOTE(tr3buchet): setup networks on destination host
            self.network_api.setup_networks_on_host(context, instance,
                                                             self.host)

            # Creating filters to hypervisors and firewalls.
            # An example is that nova-instance-instance-xxx,
            # which is written to libvirt.xml(Check "virsh nwfilter-list")
            # This nwfilter is necessary on the destination host.
            # In addition, this method is creating filtering rule
            # onto destination host.
            self.driver.ensure_filtering_rules_for_instance(instance,
                                                network_info)
        except Exception:
            # If we raise, migrate_data with the updated attachment ids
            # will not be returned to the source host for rollback.
            # So we need to rollback new attachments here.
            with excutils.save_and_reraise_exception():
                old_attachments = migrate_data.old_vol_attachment_ids
                for bdm in bdms:
                    if (bdm.is_volume and bdm.attachment_id is not None and
                            bdm.volume_id in old_attachments):
                        self.volume_api.attachment_delete(context,
                                                          bdm.attachment_id)
                        bdm.attachment_id = old_attachments[bdm.volume_id]
                        bdm.save()

        # Volume connections are complete, tell cinder that all the
        # attachments have completed.
        for bdm in bdms:
            if bdm.is_volume and bdm.attachment_id is not None:
                self.volume_api.attachment_complete(context,
                                                    bdm.attachment_id)

        self._notify_about_instance_usage(
                     context, instance, "live_migration.pre.end",
                     network_info=network_info)
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_PRE,
            phase=fields.NotificationPhase.END, bdms=bdms)

        LOG.debug('pre_live_migration result data is %s', migrate_data)
        return migrate_data

    @staticmethod
    def _neutron_failed_live_migration_callback(event_name, instance):
        msg = ('Neutron reported failure during live migration '
               'with %(event)s for instance %(uuid)s')
        msg_args = {'event': event_name, 'uuid': instance.uuid}
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfacePlugException(msg % msg_args)
        LOG.error(msg, msg_args)

    @staticmethod
    def _get_neutron_events_for_live_migration(instance):
        # We don't generate events if CONF.vif_plugging_timeout=0
        # meaning that the operator disabled using them.
        if CONF.vif_plugging_timeout and utils.is_neutron():
            return [('network-vif-plugged', vif['id'])
                    for vif in instance.get_network_info()]
        else:
            return []

    def _cleanup_pre_live_migration(self, context, dest, instance,
                                    migration, migrate_data):
        """Helper method for when pre_live_migration fails

        Sets the migration status to "error" and rolls back the live migration
        setup on the destination host.

        :param context: The user request context.
        :type context: nova.context.RequestContext
        :param dest: The live migration destination hostname.
        :type dest: str
        :param instance: The instance being live migrated.
        :type instance: nova.objects.Instance
        :param migration: The migration record tracking this live migration.
        :type migration: nova.objects.Migration
        :param migrate_data: Data about the live migration, populated from
                             the destination host.
        :type migrate_data: Subclass of nova.objects.LiveMigrateData
        """
        self._set_migration_status(migration, 'error')
        # Make sure we set this for _rollback_live_migration()
        # so it can find it, as expected if it was called later
        migrate_data.migration = migration
        self._rollback_live_migration(context, instance, dest,
                                      migrate_data)

    def _do_live_migration(self, context, dest, instance, block_migration,
                           migration, migrate_data):
        # NOTE(danms): We should enhance the RT to account for migrations
        # and use the status field to denote when the accounting has been
        # done on source/destination. For now, this is just here for status
        # reporting
        self._set_migration_status(migration, 'preparing')
        source_bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)

        class _BreakWaitForInstanceEvent(Exception):
            """Used as a signal to stop waiting for the network-vif-plugged
            event when we discover that
            [compute]/live_migration_wait_for_vif_plug is not set on the
            destination.
            """
            pass

        events = self._get_neutron_events_for_live_migration(instance)
        try:
            if ('block_migration' in migrate_data and
                    migrate_data.block_migration):
                block_device_info = self._get_instance_block_device_info(
                    context, instance, bdms=source_bdms)
                disk = self.driver.get_instance_disk_info(
                    instance, block_device_info=block_device_info)
            else:
                disk = None

            deadline = CONF.vif_plugging_timeout
            error_cb = self._neutron_failed_live_migration_callback
            # In order to avoid a race with the vif plugging that the virt
            # driver does on the destination host, we register our events
            # to wait for before calling pre_live_migration. Then if the
            # dest host reports back that we shouldn't wait, we can break
            # out of the context manager using _BreakWaitForInstanceEvent.
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=deadline,
                    error_callback=error_cb):
                with timeutils.StopWatch() as timer:
                    migrate_data = self.compute_rpcapi.pre_live_migration(
                        context, instance,
                        block_migration, disk, dest, migrate_data)
                LOG.info('Took %0.2f seconds for pre_live_migration on '
                         'destination host %s.',
                         timer.elapsed(), dest, instance=instance)
                wait_for_vif_plugged = (
                    'wait_for_vif_plugged' in migrate_data and
                    migrate_data.wait_for_vif_plugged)
                if events and not wait_for_vif_plugged:
                    raise _BreakWaitForInstanceEvent
        except _BreakWaitForInstanceEvent:
            if events:
                LOG.debug('Not waiting for events after pre_live_migration: '
                          '%s. ', events, instance=instance)
            # This is a bit weird, but we need to clear sys.exc_info() so that
            # oslo.log formatting does not inadvertently use it later if an
            # error message is logged without an explicit exc_info. This is
            # only a problem with python 2.
            if six.PY2:
                sys.exc_clear()
        except exception.VirtualInterfacePlugException:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed waiting for network virtual interfaces '
                              'to be plugged on the destination host %s.',
                              dest, instance=instance)
                self._cleanup_pre_live_migration(
                    context, dest, instance, migration, migrate_data)
        except eventlet.timeout.Timeout:
            msg = 'Timed out waiting for events: %s'
            LOG.warning(msg, events, instance=instance)
            if CONF.vif_plugging_is_fatal:
                self._cleanup_pre_live_migration(
                    context, dest, instance, migration, migrate_data)
                raise exception.MigrationError(reason=msg % events)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Pre live migration failed at %s',
                              dest, instance=instance)
                self._cleanup_pre_live_migration(
                    context, dest, instance, migration, migrate_data)

        # NOTE(Kevin_Zheng): Pop the migration from the waiting queue
        # if it exist in the queue, then we are good to moving on, if
        # not, some other process must have aborted it, then we should
        # rollback.
        try:
            self._waiting_live_migrations.pop(instance.uuid)
        except KeyError:
            LOG.debug('Migration %s aborted by another process, rollback.',
                      migration.uuid, instance=instance)
            migrate_data.migration = migration
            self._rollback_live_migration(context, instance, dest,
                                          migrate_data, 'cancelled')
            self._notify_live_migrate_abort_end(context, instance)
            return

        self._set_migration_status(migration, 'running')
        if migrate_data:
            migrate_data.migration = migration

        # NOTE(mdbooth): pre_live_migration will update connection_info and
        # attachment_id on all volume BDMS to reflect the new destination
        # host attachment. We fetch BDMs before that to retain connection_info
        # and attachment_id relating to the source host for post migration
        # cleanup.
        post_live_migration = functools.partial(self._post_live_migration,
                                                source_bdms=source_bdms)

        LOG.debug('live_migration data is %s', migrate_data)
        try:
            self.driver.live_migration(context, instance, dest,
                                       post_live_migration,
                                       self._rollback_live_migration,
                                       block_migration, migrate_data)
        except Exception:
            LOG.exception('Live migration failed.', instance=instance)
            with excutils.save_and_reraise_exception():
                # Put instance and migration into error state,
                # as its almost certainly too late to rollback
                self._set_migration_status(migration, 'error')
                # first refresh instance as it may have got updated by
                # post_live_migration_at_destination
                instance.refresh()
                self._set_instance_obj_error_state(context, instance,
                                                   clean_task_state=True)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def live_migration(self, context, dest, instance, block_migration,
                       migration, migrate_data):
        """Executing live migration.

        :param context: security context
        :param dest: destination host
        :param instance: a nova.objects.instance.Instance object
        :param block_migration: if true, prepare for block migration
        :param migration: an nova.objects.Migration object
        :param migrate_data: implementation specific params

        """
        self._set_migration_status(migration, 'queued')
        # NOTE(Kevin_Zheng): Submit the live_migration job to the pool and
        # put the returned Future object into dict mapped with migration.uuid
        # in order to be able to track and abort it in the future.
        self._waiting_live_migrations[instance.uuid] = (None, None)
        try:
            future = self._live_migration_executor.submit(
                self._do_live_migration, context, dest, instance,
                block_migration, migration, migrate_data)
            self._waiting_live_migrations[instance.uuid] = (migration, future)
        except RuntimeError:
            # ThreadPoolExecutor.submit will raise RuntimeError if the pool
            # is shutdown, which happens in _cleanup_live_migrations_in_pool.
            LOG.info('Migration %s failed to submit as the compute service '
                     'is shutting down.', migration.uuid, instance=instance)
            self._set_migration_status(migration, 'error')
            raise exception.LiveMigrationNotSubmitted(
                migration_uuid=migration.uuid, instance_uuid=instance.uuid)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def live_migration_force_complete(self, context, instance):
        """Force live migration to complete.

        :param context: Security context
        :param instance: The instance that is being migrated
        """

        self._notify_about_instance_usage(
            context, instance, 'live.migration.force.complete.start')
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_FORCE_COMPLETE,
            phase=fields.NotificationPhase.START)
        self.driver.live_migration_force_complete(instance)
        self._notify_about_instance_usage(
            context, instance, 'live.migration.force.complete.end')
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_FORCE_COMPLETE,
            phase=fields.NotificationPhase.END)

    def _notify_live_migrate_abort_end(self, context, instance):
        self._notify_about_instance_usage(
            context, instance, 'live.migration.abort.end')
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_ABORT,
            phase=fields.NotificationPhase.END)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def live_migration_abort(self, context, instance, migration_id):
        """Abort an in-progress live migration.

        :param context: Security context
        :param instance: The instance that is being migrated
        :param migration_id: ID of in-progress live migration

        """
        self._notify_about_instance_usage(
            context, instance, 'live.migration.abort.start')
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_ABORT,
            phase=fields.NotificationPhase.START)
        # NOTE(Kevin_Zheng): Pop the migration out from the queue, this might
        # lead to 3 scenarios:
        # 1. The selected migration is still in queue, and the future.cancel()
        #    succeed, then the abort action is succeed, mark the migration
        #    status to 'cancelled'.
        # 2. The selected migration is still in queue, but the future.cancel()
        #    failed, then the _do_live_migration() has started executing, and
        #    the migration status is 'preparing', then we just pop it from the
        #    queue, and the migration process will handle it later. And the
        #    migration status couldn't be 'running' in this scenario because
        #    if _do_live_migration has started executing and we've already
        #    popped it from the queue and set the migration status to
        #    'running' at this point, popping it here will raise KeyError at
        #    which point we check if it's running and if so, we abort the old
        #    way.
        # 3. The selected migration is not in the queue, then the migration
        #    status is 'running', let the driver handle it.
        try:
            migration, future = (
                self._waiting_live_migrations.pop(instance.uuid))
            if future and future.cancel():
                # If we got here, we've successfully aborted the queued
                # migration and _do_live_migration won't run so we need
                # to set the migration status to cancelled and send the
                # notification. If Future.cancel() fails, it means
                # _do_live_migration is running and the migration status
                # is preparing, and _do_live_migration() itself will attempt
                # to pop the queued migration, hit a KeyError, and rollback,
                # set the migration to cancelled and send the
                # live.migration.abort.end notification.
                self._set_migration_status(migration, 'cancelled')
        except KeyError:
            migration = objects.Migration.get_by_id(context, migration_id)
            if migration.status != 'running':
                raise exception.InvalidMigrationState(
                    migration_id=migration_id, instance_uuid=instance.uuid,
                    state=migration.status, method='abort live migration')
            self.driver.live_migration_abort(instance)
        self._notify_live_migrate_abort_end(context, instance)

    def _live_migration_cleanup_flags(self, migrate_data):
        """Determine whether disks or instance path need to be cleaned up after
        live migration (at source on success, at destination on rollback)

        Block migration needs empty image at destination host before migration
        starts, so if any failure occurs, any empty images has to be deleted.

        Also Volume backed live migration w/o shared storage needs to delete
        newly created instance-xxx dir on the destination as a part of its
        rollback process

        :param migrate_data: implementation specific data
        :returns: (bool, bool) -- do_cleanup, destroy_disks
        """
        # NOTE(pkoniszewski): block migration specific params are set inside
        # migrate_data objects for drivers that expose block live migration
        # information (i.e. Libvirt, Xenapi and HyperV). For other drivers
        # cleanup is not needed.
        do_cleanup = False
        destroy_disks = False
        if isinstance(migrate_data, migrate_data_obj.LibvirtLiveMigrateData):
            # No instance booting at source host, but instance dir
            # must be deleted for preparing next block migration
            # must be deleted for preparing next live migration w/o shared
            # storage
            do_cleanup = not migrate_data.is_shared_instance_path
            destroy_disks = not migrate_data.is_shared_block_storage
        elif isinstance(migrate_data, migrate_data_obj.XenapiLiveMigrateData):
            do_cleanup = migrate_data.block_migration
            destroy_disks = migrate_data.block_migration
        elif isinstance(migrate_data, migrate_data_obj.HyperVLiveMigrateData):
            # NOTE(claudiub): We need to cleanup any zombie Planned VM.
            do_cleanup = True
            destroy_disks = not migrate_data.is_shared_instance_path

        return (do_cleanup, destroy_disks)

    @wrap_exception()
    @wrap_instance_fault
    def _post_live_migration(self, ctxt, instance, dest,
                             block_migration=False, migrate_data=None,
                             source_bdms=None):
        """Post operations for live migration.

        This method is called from live_migration
        and mainly updating database record.

        :param ctxt: security context
        :param instance: instance dict
        :param dest: destination host
        :param block_migration: if true, prepare for block migration
        :param migrate_data: if not None, it is a dict which has data
        :param source_bdms: BDMs prior to modification by the destination
                            compute host. Set by _do_live_migration and not
                            part of the callback interface, so this is never
                            None
        required for live migration without shared storage

        """
        LOG.info('_post_live_migration() is started..',
                 instance=instance)

        # Cleanup source host post live-migration
        block_device_info = self._get_instance_block_device_info(
                            ctxt, instance, bdms=source_bdms)
        self.driver.post_live_migration(ctxt, instance, block_device_info,
                                        migrate_data)

        # Detaching volumes.
        connector = self.driver.get_volume_connector(instance)
        for bdm in source_bdms:
            if bdm.is_volume:
                # Detaching volumes is a call to an external API that can fail.
                # If it does, we need to handle it gracefully so that the call
                # to post_live_migration_at_destination - where we set instance
                # host and task state - still happens. We need to rethink the
                # current approach of setting instance host and task state
                # AFTER a whole bunch of things that could fail in unhandled
                # ways, but that is left as a TODO(artom).
                try:
                    if bdm.attachment_id is None:
                        # Prior to cinder v3.44:
                        # We don't want to actually mark the volume detached,
                        # or delete the bdm, just remove the connection from
                        # this host.
                        #
                        # remove the volume connection without detaching from
                        # hypervisor because the instance is not running
                        # anymore on the current host
                        self.volume_api.terminate_connection(ctxt,
                                                             bdm.volume_id,
                                                             connector)
                    else:
                        # cinder v3.44 api flow - delete the old attachment
                        # for the source host
                        self.volume_api.attachment_delete(ctxt,
                                                          bdm.attachment_id)

                except Exception as e:
                    if bdm.attachment_id is None:
                        LOG.error('Connection for volume %s not terminated on '
                                  'source host %s during post_live_migration: '
                                   '%s', bdm.volume_id, self.host,
                                   six.text_type(e), instance=instance)
                    else:
                        LOG.error('Volume attachment %s not deleted on source '
                                  'host %s during post_live_migration: %s',
                                  bdm.attachment_id, self.host,
                                  six.text_type(e), instance=instance)

        # Releasing vlan.
        # (not necessary in current implementation?)

        network_info = self.network_api.get_instance_nw_info(ctxt, instance)

        self._notify_about_instance_usage(ctxt, instance,
                                          "live_migration._post.start",
                                          network_info=network_info)
        compute_utils.notify_about_instance_action(
            ctxt, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_POST,
            phase=fields.NotificationPhase.START)
        # Releasing security group ingress rule.
        LOG.debug('Calling driver.unfilter_instance from _post_live_migration',
                  instance=instance)
        self.driver.unfilter_instance(instance,
                                      network_info)

        migration = {'source_compute': self.host,
                     'dest_compute': dest, }
        # For neutron, migrate_instance_start will activate the destination
        # host port bindings, if there are any created by conductor before live
        # migration started.
        self.network_api.migrate_instance_start(ctxt,
                                                instance,
                                                migration)

        destroy_vifs = False
        try:
            # It's possible that the vif type changed on the destination
            # host and is already bound and active, so we need to use the
            # stashed source vifs in migrate_data.vifs (if present) to unplug
            # on the source host.
            unplug_nw_info = network_info
            if migrate_data and 'vifs' in migrate_data:
                nw_info = []
                for migrate_vif in migrate_data.vifs:
                    nw_info.append(migrate_vif.source_vif)
                unplug_nw_info = network_model.NetworkInfo.hydrate(nw_info)
                LOG.debug('Calling driver.post_live_migration_at_source '
                          'with original source VIFs from migrate_data: %s',
                          unplug_nw_info, instance=instance)
            self.driver.post_live_migration_at_source(ctxt, instance,
                                                      unplug_nw_info)
        except NotImplementedError as ex:
            LOG.debug(ex, instance=instance)
            # For all hypervisors other than libvirt, there is a possibility
            # they are unplugging networks from source node in the cleanup
            # method
            destroy_vifs = True

        # NOTE(danms): Save source node before calling post method on
        # destination, which will update it
        source_node = instance.node

        # Define domain at destination host, without doing it,
        # pause/suspend/terminate do not work.
        post_at_dest_success = True
        try:
            self.compute_rpcapi.post_live_migration_at_destination(ctxt,
                    instance, block_migration, dest)
        except Exception as error:
            post_at_dest_success = False
            # We don't want to break _post_live_migration() if
            # post_live_migration_at_destination() fails as it should never
            # affect cleaning up source node.
            LOG.exception("Post live migration at destination %s failed",
                          dest, instance=instance, error=error)

        do_cleanup, destroy_disks = self._live_migration_cleanup_flags(
                migrate_data)

        if do_cleanup:
            LOG.debug('Calling driver.cleanup from _post_live_migration',
                      instance=instance)
            self.driver.cleanup(ctxt, instance, unplug_nw_info,
                                destroy_disks=destroy_disks,
                                migrate_data=migrate_data,
                                destroy_vifs=destroy_vifs)

        self.instance_events.clear_events_for_instance(instance)

        # NOTE(timello): make sure we update available resources on source
        # host even before next periodic task.
        self.update_available_resource(ctxt)

        self._update_scheduler_instance_info(ctxt, instance)
        self._notify_about_instance_usage(ctxt, instance,
                                          "live_migration._post.end",
                                          network_info=network_info)
        compute_utils.notify_about_instance_action(
            ctxt, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_POST,
            phase=fields.NotificationPhase.END)
        if post_at_dest_success:
            LOG.info('Migrating instance to %s finished successfully.',
                     dest, instance=instance)

        self._clean_instance_console_tokens(ctxt, instance)
        if migrate_data and migrate_data.obj_attr_is_set('migration'):
            migrate_data.migration.status = 'completed'
            migrate_data.migration.save()
            migration = migrate_data.migration
            rc = self.scheduler_client.reportclient
            # Check to see if our migration has its own allocations
            allocs = rc.get_allocations_for_consumer(ctxt, migration.uuid)
        else:
            # We didn't have data on a migration, which means we can't
            # look up to see if we had new-style migration-based
            # allocations. This should really only happen in cases of
            # a buggy virt driver or some really old component in the
            # system. Log a warning so we know it happened.
            allocs = None
            LOG.warning('Live migration ended with no migrate_data '
                        'record. Unable to clean up migration-based '
                        'allocations which is almost certainly not '
                        'an expected situation.')

        if allocs:
            # We had a migration-based allocation that we need to handle
            self._delete_allocation_after_move(ctxt,
                                               instance,
                                               migrate_data.migration,
                                               instance.flavor,
                                               source_node)
        else:
            # No migration-based allocations, so do the old thing and
            # attempt to clean up any doubled per-instance allocation
            rt = self._get_resource_tracker()
            rt.delete_allocation_for_migrated_instance(
                ctxt, instance, source_node)

    def _consoles_enabled(self):
        """Returns whether a console is enable."""
        return (CONF.vnc.enabled or CONF.spice.enabled or
                CONF.rdp.enabled or CONF.serial_console.enabled or
                CONF.mks.enabled)

    def _clean_instance_console_tokens(self, ctxt, instance):
        """Clean console tokens stored for an instance."""
        # If the database backend isn't in use, don't bother trying to clean
        # tokens. The database backend is not supported for cells v1.
        if not CONF.cells.enable and self._consoles_enabled():
            objects.ConsoleAuthToken.\
                clean_console_auths_for_instance(ctxt, instance.uuid)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def post_live_migration_at_destination(self, context, instance,
                                           block_migration):
        """Post operations for live migration .

        :param context: security context
        :param instance: Instance dict
        :param block_migration: if true, prepare for block migration

        """
        LOG.info('Post operation of migration started',
                 instance=instance)

        # NOTE(tr3buchet): setup networks on destination host
        #                  this is called a second time because
        #                  multi_host does not create the bridge in
        #                  plug_vifs
        # NOTE(mriedem): This is a no-op for neutron.
        self.network_api.setup_networks_on_host(context, instance,
                                                         self.host)
        migration = {'source_compute': instance.host,
                     'dest_compute': self.host, }
        self.network_api.migrate_instance_finish(context,
                                                 instance,
                                                 migration)

        network_info = self.network_api.get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(
                     context, instance, "live_migration.post.dest.start",
                     network_info=network_info)
        compute_utils.notify_about_instance_action(context, instance,
                self.host,
                action=fields.NotificationAction.LIVE_MIGRATION_POST_DEST,
                phase=fields.NotificationPhase.START)
        block_device_info = self._get_instance_block_device_info(context,
                                                                 instance)

        try:
            self.driver.post_live_migration_at_destination(
                context, instance, network_info, block_migration,
                block_device_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                instance.vm_state = vm_states.ERROR
                LOG.error('Unexpected error during post live migration at '
                          'destination host.', instance=instance)
        finally:
            # Restore instance state and update host
            current_power_state = self._get_power_state(context, instance)
            node_name = None
            prev_host = instance.host
            try:
                compute_node = self._get_compute_info(context, self.host)
                node_name = compute_node.hypervisor_hostname
            except exception.ComputeHostNotFound:
                LOG.exception('Failed to get compute_info for %s', self.host)
            finally:
                instance.host = self.host
                instance.power_state = current_power_state
                instance.task_state = None
                instance.node = node_name
                instance.progress = 0
                instance.save(expected_task_state=task_states.MIGRATING)

        # NOTE(tr3buchet): tear down networks on source host (nova-net)
        # NOTE(mriedem): For neutron, this will delete any inactive source
        # host port bindings.
        try:
            self.network_api.setup_networks_on_host(context, instance,
                                                    prev_host, teardown=True)
        except exception.PortBindingDeletionFailed as e:
            # Removing the inactive port bindings from the source host is not
            # critical so just log an error but don't fail.
            LOG.error('Network cleanup failed for source host %s during post '
                      'live migration. You may need to manually clean up '
                      'resources in the network service. Error: %s',
                      prev_host, six.text_type(e))
        # NOTE(vish): this is necessary to update dhcp for nova-network
        # NOTE(mriedem): This is a no-op for neutron.
        self.network_api.setup_networks_on_host(context, instance, self.host)
        self._notify_about_instance_usage(
                     context, instance, "live_migration.post.dest.end",
                     network_info=network_info)
        compute_utils.notify_about_instance_action(context, instance,
                self.host,
                action=fields.NotificationAction.LIVE_MIGRATION_POST_DEST,
                phase=fields.NotificationPhase.END)

    @wrap_exception()
    @wrap_instance_fault
    def _rollback_live_migration(self, context, instance,
                                 dest, migrate_data=None,
                                 migration_status='error'):
        """Recovers Instance/volume state from migrating -> running.

        :param context: security context
        :param instance: nova.objects.instance.Instance object
        :param dest:
            This method is called from live migration src host.
            This param specifies destination host.
        :param migrate_data:
            if not none, contains implementation specific data.
        :param migration_status:
            Contains the status we want to set for the migration object

        """
        if (isinstance(migrate_data, migrate_data_obj.LiveMigrateData) and
              migrate_data.obj_attr_is_set('migration')):
            migration = migrate_data.migration
        else:
            migration = None

        if migration:
            # Remove allocations created in Placement for the dest node.
            # If migration is None, we must be so old we don't have placement,
            # so no need to do something else.
            self._revert_allocation(context, instance, migration)
        else:
            LOG.error('Unable to revert allocations during live migration '
                      'rollback; compute driver did not provide migrate_data',
                      instance=instance)

        instance.task_state = None
        instance.progress = 0
        instance.save(expected_task_state=[task_states.MIGRATING])

        # NOTE(tr3buchet): setup networks on source host (really it's re-setup
        #                  for nova-network)
        # NOTE(mriedem): This is a no-op for neutron.
        self.network_api.setup_networks_on_host(context, instance, self.host)

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
        for bdm in bdms:
            if bdm.is_volume:
                # remove the connection on the destination host
                self.compute_rpcapi.remove_volume_connection(
                        context, instance, bdm.volume_id, dest)

                if bdm.attachment_id:
                    # 3.44 cinder api flow. Set the bdm's
                    # attachment_id to the old attachment of the source
                    # host. If old_attachments is not there, then
                    # there was an error before the new attachment was made.
                    old_attachments = migrate_data.old_vol_attachment_ids \
                        if 'old_vol_attachment_ids' in migrate_data else None
                    if old_attachments and bdm.volume_id in old_attachments:
                        self.volume_api.attachment_delete(context,
                                                          bdm.attachment_id)
                        bdm.attachment_id = old_attachments[bdm.volume_id]
                        bdm.save()

        self._notify_about_instance_usage(context, instance,
                                          "live_migration._rollback.start")
        compute_utils.notify_about_instance_action(context, instance,
                self.host,
                action=fields.NotificationAction.LIVE_MIGRATION_ROLLBACK,
                phase=fields.NotificationPhase.START,
                bdms=bdms)

        do_cleanup, destroy_disks = self._live_migration_cleanup_flags(
                migrate_data)

        if do_cleanup:
            self.compute_rpcapi.rollback_live_migration_at_destination(
                    context, instance, dest, destroy_disks=destroy_disks,
                    migrate_data=migrate_data)
        elif utils.is_neutron():
            # The port binding profiles need to be cleaned up.
            with errors_out_migration_ctxt(migration):
                try:
                    # This call will delete any inactive destination host
                    # port bindings.
                    self.network_api.setup_networks_on_host(
                        context, instance, host=dest, teardown=True)
                except exception.PortBindingDeletionFailed as e:
                    # Removing the inactive port bindings from the destination
                    # host is not critical so just log an error but don't fail.
                    LOG.error(
                        'Network cleanup failed for destination host %s '
                        'during live migration rollback. You may need to '
                        'manually clean up resources in the network service. '
                        'Error: %s', dest, six.text_type(e))
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.exception(
                            'An error occurred while cleaning up networking '
                            'during live migration rollback.',
                            instance=instance)

        self._notify_about_instance_usage(context, instance,
                                          "live_migration._rollback.end")
        compute_utils.notify_about_instance_action(context, instance,
                self.host,
                action=fields.NotificationAction.LIVE_MIGRATION_ROLLBACK,
                phase=fields.NotificationPhase.END,
                bdms=bdms)

        self._set_migration_status(migration, migration_status)

    @wrap_exception()
    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def rollback_live_migration_at_destination(self, context, instance,
                                               destroy_disks,
                                               migrate_data):
        """Cleaning up image directory that is created pre_live_migration.

        :param context: security context
        :param instance: a nova.objects.instance.Instance object sent over rpc
        :param destroy_disks: whether to destroy volumes or not
        :param migrate_data: contains migration info
        """
        network_info = self.network_api.get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(
                      context, instance, "live_migration.rollback.dest.start",
                      network_info=network_info)
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_ROLLBACK_DEST,
            phase=fields.NotificationPhase.START)
        try:
            # NOTE(tr3buchet): tear down networks on dest host (nova-net)
            # NOTE(mriedem): For neutron, this call will delete any
            # destination host port bindings.
            # TODO(mriedem): We should eventually remove this call from
            # this method (rollback_live_migration_at_destination) since this
            # method is only called conditionally based on whether or not the
            # instance is running on shared storage. _rollback_live_migration
            # already calls this method for neutron if we are running on
            # shared storage.
            self.network_api.setup_networks_on_host(context, instance,
                                                    self.host, teardown=True)
        except exception.PortBindingDeletionFailed as e:
            # Removing the inactive port bindings from the destination
            # host is not critical so just log an error but don't fail.
            LOG.error(
                'Network cleanup failed for destination host %s '
                'during live migration rollback. You may need to '
                'manually clean up resources in the network service. '
                'Error: %s', self.host, six.text_type(e))
        except Exception:
            with excutils.save_and_reraise_exception():
                # NOTE(tdurakov): even if teardown networks fails driver
                # should try to rollback live migration on destination.
                LOG.exception('An error occurred while deallocating network.',
                              instance=instance)
        finally:
            # always run this even if setup_networks_on_host fails
            # NOTE(vish): The mapping is passed in so the driver can disconnect
            #             from remote volumes if necessary
            block_device_info = self._get_instance_block_device_info(context,
                                                                     instance)
            self.driver.rollback_live_migration_at_destination(
                context, instance, network_info, block_device_info,
                destroy_disks=destroy_disks, migrate_data=migrate_data)

        self._notify_about_instance_usage(
                        context, instance, "live_migration.rollback.dest.end",
                        network_info=network_info)
        compute_utils.notify_about_instance_action(
            context, instance, self.host,
            action=fields.NotificationAction.LIVE_MIGRATION_ROLLBACK_DEST,
            phase=fields.NotificationPhase.END)

    @periodic_task.periodic_task(
        spacing=CONF.heal_instance_info_cache_interval)
    def _heal_instance_info_cache(self, context):
        """Called periodically.  On every call, try to update the
        info_cache's network information for another instance by
        calling to the network manager.

        This is implemented by keeping a cache of uuids of instances
        that live on this host.  On each call, we pop one off of a
        list, pull the DB record, and try the call to the network API.
        If anything errors don't fail, as it's possible the instance
        has been deleted, etc.
        """
        heal_interval = CONF.heal_instance_info_cache_interval
        if not heal_interval:
            return

        instance_uuids = getattr(self, '_instance_uuids_to_heal', [])
        instance = None

        LOG.debug('Starting heal instance info cache')

        if not instance_uuids:
            # The list of instances to heal is empty so rebuild it
            LOG.debug('Rebuilding the list of instances to heal')
            db_instances = objects.InstanceList.get_by_host(
                context, self.host, expected_attrs=[], use_slave=True)
            for inst in db_instances:
                # We don't want to refresh the cache for instances
                # which are building or deleting so don't put them
                # in the list. If they are building they will get
                # added to the list next time we build it.
                if (inst.vm_state == vm_states.BUILDING):
                    LOG.debug('Skipping network cache update for instance '
                              'because it is Building.', instance=inst)
                    continue
                if (inst.task_state == task_states.DELETING):
                    LOG.debug('Skipping network cache update for instance '
                              'because it is being deleted.', instance=inst)
                    continue

                if not instance:
                    # Save the first one we find so we don't
                    # have to get it again
                    instance = inst
                else:
                    instance_uuids.append(inst['uuid'])

            self._instance_uuids_to_heal = instance_uuids
        else:
            # Find the next valid instance on the list
            while instance_uuids:
                try:
                    inst = objects.Instance.get_by_uuid(
                            context, instance_uuids.pop(0),
                            expected_attrs=['system_metadata', 'info_cache',
                                            'flavor'],
                            use_slave=True)
                except exception.InstanceNotFound:
                    # Instance is gone.  Try to grab another.
                    continue

                # Check the instance hasn't been migrated
                if inst.host != self.host:
                    LOG.debug('Skipping network cache update for instance '
                              'because it has been migrated to another '
                              'host.', instance=inst)
                # Check the instance isn't being deleting
                elif inst.task_state == task_states.DELETING:
                    LOG.debug('Skipping network cache update for instance '
                              'because it is being deleted.', instance=inst)
                else:
                    instance = inst
                    break

        if instance:
            # We have an instance now to refresh
            try:
                # Call to network API to get instance info.. this will
                # force an update to the instance's info_cache
                self.network_api.get_instance_nw_info(context, instance)
                LOG.debug('Updated the network info_cache for instance',
                          instance=instance)
            except exception.InstanceNotFound:
                # Instance is gone.
                LOG.debug('Instance no longer exists. Unable to refresh',
                          instance=instance)
                return
            except exception.InstanceInfoCacheNotFound:
                # InstanceInfoCache is gone.
                LOG.debug('InstanceInfoCache no longer exists. '
                          'Unable to refresh', instance=instance)
            except Exception:
                LOG.error('An error occurred while refreshing the network '
                          'cache.', instance=instance, exc_info=True)
        else:
            LOG.debug("Didn't find any instances for network info cache "
                      "update.")

    @periodic_task.periodic_task
    def _poll_rebooting_instances(self, context):
        if CONF.reboot_timeout > 0:
            filters = {'task_state':
                       [task_states.REBOOTING,
                        task_states.REBOOT_STARTED,
                        task_states.REBOOT_PENDING],
                       'host': self.host}
            rebooting = objects.InstanceList.get_by_filters(
                context, filters, expected_attrs=[], use_slave=True)

            to_poll = []
            for instance in rebooting:
                if timeutils.is_older_than(instance.updated_at,
                                           CONF.reboot_timeout):
                    to_poll.append(instance)

            self.driver.poll_rebooting_instances(CONF.reboot_timeout, to_poll)

    @periodic_task.periodic_task
    def _poll_rescued_instances(self, context):
        if CONF.rescue_timeout > 0:
            filters = {'vm_state': vm_states.RESCUED,
                       'host': self.host}
            rescued_instances = objects.InstanceList.get_by_filters(
                context, filters, expected_attrs=["system_metadata"],
                use_slave=True)

            to_unrescue = []
            for instance in rescued_instances:
                if timeutils.is_older_than(instance.launched_at,
                                           CONF.rescue_timeout):
                    to_unrescue.append(instance)

            for instance in to_unrescue:
                self.compute_api.unrescue(context, instance)

    @periodic_task.periodic_task
    def _poll_unconfirmed_resizes(self, context):
        if CONF.resize_confirm_window == 0:
            return

        migrations = objects.MigrationList.get_unconfirmed_by_dest_compute(
                context, CONF.resize_confirm_window, self.host,
                use_slave=True)

        migrations_info = dict(migration_count=len(migrations),
                confirm_window=CONF.resize_confirm_window)

        if migrations_info["migration_count"] > 0:
            LOG.info("Found %(migration_count)d unconfirmed migrations "
                     "older than %(confirm_window)d seconds",
                     migrations_info)

        def _set_migration_to_error(migration, reason, **kwargs):
            LOG.warning("Setting migration %(migration_id)s to error: "
                        "%(reason)s",
                        {'migration_id': migration['id'], 'reason': reason},
                        **kwargs)
            migration.status = 'error'
            with migration.obj_as_admin():
                migration.save()

        for migration in migrations:
            instance_uuid = migration.instance_uuid
            LOG.info("Automatically confirming migration "
                     "%(migration_id)s for instance %(instance_uuid)s",
                     {'migration_id': migration.id,
                      'instance_uuid': instance_uuid})
            expected_attrs = ['metadata', 'system_metadata']
            try:
                instance = objects.Instance.get_by_uuid(context,
                            instance_uuid, expected_attrs=expected_attrs,
                            use_slave=True)
            except exception.InstanceNotFound:
                reason = (_("Instance %s not found") %
                          instance_uuid)
                _set_migration_to_error(migration, reason)
                continue
            if instance.vm_state == vm_states.ERROR:
                reason = _("In ERROR state")
                _set_migration_to_error(migration, reason,
                                        instance=instance)
                continue
            # race condition: The instance in DELETING state should not be
            # set the migration state to error, otherwise the instance in
            # to be deleted which is in RESIZED state
            # will not be able to confirm resize
            if instance.task_state in [task_states.DELETING,
                                       task_states.SOFT_DELETING]:
                msg = ("Instance being deleted or soft deleted during resize "
                       "confirmation. Skipping.")
                LOG.debug(msg, instance=instance)
                continue

            # race condition: This condition is hit when this method is
            # called between the save of the migration record with a status of
            # finished and the save of the instance object with a state of
            # RESIZED. The migration record should not be set to error.
            if instance.task_state == task_states.RESIZE_FINISH:
                msg = ("Instance still resizing during resize "
                       "confirmation. Skipping.")
                LOG.debug(msg, instance=instance)
                continue

            vm_state = instance.vm_state
            task_state = instance.task_state
            if vm_state != vm_states.RESIZED or task_state is not None:
                reason = (_("In states %(vm_state)s/%(task_state)s, not "
                           "RESIZED/None") %
                          {'vm_state': vm_state,
                           'task_state': task_state})
                _set_migration_to_error(migration, reason,
                                        instance=instance)
                continue
            try:
                self.compute_api.confirm_resize(context, instance,
                                                migration=migration)
            except Exception as e:
                LOG.info("Error auto-confirming resize: %s. "
                         "Will retry later.", e, instance=instance)

    @periodic_task.periodic_task(spacing=CONF.shelved_poll_interval)
    def _poll_shelved_instances(self, context):

        if CONF.shelved_offload_time <= 0:
            return

        filters = {'vm_state': vm_states.SHELVED,
                   'task_state': None,
                   'host': self.host}
        shelved_instances = objects.InstanceList.get_by_filters(
            context, filters=filters, expected_attrs=['system_metadata'],
            use_slave=True)

        to_gc = []
        for instance in shelved_instances:
            sys_meta = instance.system_metadata
            shelved_at = timeutils.parse_strtime(sys_meta['shelved_at'])
            if timeutils.is_older_than(shelved_at, CONF.shelved_offload_time):
                to_gc.append(instance)

        for instance in to_gc:
            try:
                instance.task_state = task_states.SHELVING_OFFLOADING
                instance.save(expected_task_state=(None,))
                self.shelve_offload_instance(context, instance,
                                             clean_shutdown=False)
            except Exception:
                LOG.exception('Periodic task failed to offload instance.',
                              instance=instance)

    @periodic_task.periodic_task
    def _instance_usage_audit(self, context):
        if not CONF.instance_usage_audit:
            return

        begin, end = utils.last_completed_audit_period()
        if objects.TaskLog.get(context, 'instance_usage_audit', begin, end,
                               self.host):
            return

        instances = objects.InstanceList.get_active_by_window_joined(
            context, begin, end, host=self.host,
            expected_attrs=['system_metadata', 'info_cache', 'metadata',
                            'flavor'],
            use_slave=True)
        num_instances = len(instances)
        errors = 0
        successes = 0
        LOG.info("Running instance usage audit for host %(host)s "
                 "from %(begin_time)s to %(end_time)s. "
                 "%(number_instances)s instances.",
                 {'host': self.host,
                  'begin_time': begin,
                  'end_time': end,
                  'number_instances': num_instances})
        start_time = time.time()
        task_log = objects.TaskLog(context)
        task_log.task_name = 'instance_usage_audit'
        task_log.period_beginning = begin
        task_log.period_ending = end
        task_log.host = self.host
        task_log.task_items = num_instances
        task_log.message = 'Instance usage audit started...'
        task_log.begin_task()
        for instance in instances:
            try:
                compute_utils.notify_usage_exists(
                    self.notifier, context, instance, self.host,
                    ignore_missing_network_data=False)
                successes += 1
            except Exception:
                LOG.exception('Failed to generate usage '
                              'audit for instance '
                              'on host %s', self.host,
                              instance=instance)
                errors += 1
        task_log.errors = errors
        task_log.message = (
            'Instance usage audit ran for host %s, %s instances in %s seconds.'
            % (self.host, num_instances, time.time() - start_time))
        task_log.end_task()

    @periodic_task.periodic_task(spacing=CONF.bandwidth_poll_interval)
    def _poll_bandwidth_usage(self, context):

        if not self._bw_usage_supported:
            return

        prev_time, start_time = utils.last_completed_audit_period()

        curr_time = time.time()
        if (curr_time - self._last_bw_usage_poll >
                CONF.bandwidth_poll_interval):
            self._last_bw_usage_poll = curr_time
            LOG.info("Updating bandwidth usage cache")
            cells_update_interval = CONF.cells.bandwidth_update_interval
            if (cells_update_interval > 0 and
                   curr_time - self._last_bw_usage_cell_update >
                           cells_update_interval):
                self._last_bw_usage_cell_update = curr_time
                update_cells = True
            else:
                update_cells = False

            instances = objects.InstanceList.get_by_host(context,
                                                              self.host,
                                                              use_slave=True)
            try:
                bw_counters = self.driver.get_all_bw_counters(instances)
            except NotImplementedError:
                # NOTE(mdragon): Not all hypervisors have bandwidth polling
                # implemented yet.  If they don't it doesn't break anything,
                # they just don't get the info in the usage events.
                # NOTE(PhilDay): Record that its not supported so we can
                # skip fast on future calls rather than waste effort getting
                # the list of instances.
                LOG.info("Bandwidth usage not supported by %(driver)s.",
                         {'driver': CONF.compute_driver})
                self._bw_usage_supported = False
                return

            refreshed = timeutils.utcnow()
            for bw_ctr in bw_counters:
                # Allow switching of greenthreads between queries.
                greenthread.sleep(0)
                bw_in = 0
                bw_out = 0
                last_ctr_in = None
                last_ctr_out = None
                usage = objects.BandwidthUsage.get_by_instance_uuid_and_mac(
                    context, bw_ctr['uuid'], bw_ctr['mac_address'],
                    start_period=start_time, use_slave=True)
                if usage:
                    bw_in = usage.bw_in
                    bw_out = usage.bw_out
                    last_ctr_in = usage.last_ctr_in
                    last_ctr_out = usage.last_ctr_out
                else:
                    usage = (objects.BandwidthUsage.
                             get_by_instance_uuid_and_mac(
                        context, bw_ctr['uuid'], bw_ctr['mac_address'],
                        start_period=prev_time, use_slave=True))
                    if usage:
                        last_ctr_in = usage.last_ctr_in
                        last_ctr_out = usage.last_ctr_out

                if last_ctr_in is not None:
                    if bw_ctr['bw_in'] < last_ctr_in:
                        # counter rollover
                        bw_in += bw_ctr['bw_in']
                    else:
                        bw_in += (bw_ctr['bw_in'] - last_ctr_in)

                if last_ctr_out is not None:
                    if bw_ctr['bw_out'] < last_ctr_out:
                        # counter rollover
                        bw_out += bw_ctr['bw_out']
                    else:
                        bw_out += (bw_ctr['bw_out'] - last_ctr_out)

                objects.BandwidthUsage(context=context).create(
                                              bw_ctr['uuid'],
                                              bw_ctr['mac_address'],
                                              bw_in,
                                              bw_out,
                                              bw_ctr['bw_in'],
                                              bw_ctr['bw_out'],
                                              start_period=start_time,
                                              last_refreshed=refreshed,
                                              update_cells=update_cells)

    def _get_host_volume_bdms(self, context, use_slave=False):
        """Return all block device mappings on a compute host."""
        compute_host_bdms = []
        instances = objects.InstanceList.get_by_host(context, self.host,
            use_slave=use_slave)
        for instance in instances:
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid, use_slave=use_slave)
            instance_bdms = [bdm for bdm in bdms if bdm.is_volume]
            compute_host_bdms.append(dict(instance=instance,
                                          instance_bdms=instance_bdms))

        return compute_host_bdms

    def _update_volume_usage_cache(self, context, vol_usages):
        """Updates the volume usage cache table with a list of stats."""
        for usage in vol_usages:
            # Allow switching of greenthreads between queries.
            greenthread.sleep(0)
            vol_usage = objects.VolumeUsage(context)
            vol_usage.volume_id = usage['volume']
            vol_usage.instance_uuid = usage['instance'].uuid
            vol_usage.project_id = usage['instance'].project_id
            vol_usage.user_id = usage['instance'].user_id
            vol_usage.availability_zone = usage['instance'].availability_zone
            vol_usage.curr_reads = usage['rd_req']
            vol_usage.curr_read_bytes = usage['rd_bytes']
            vol_usage.curr_writes = usage['wr_req']
            vol_usage.curr_write_bytes = usage['wr_bytes']
            vol_usage.save()
            self.notifier.info(context, 'volume.usage',
                               compute_utils.usage_volume_info(vol_usage))

    @periodic_task.periodic_task(spacing=CONF.volume_usage_poll_interval)
    def _poll_volume_usage(self, context):
        if CONF.volume_usage_poll_interval == 0:
            return

        compute_host_bdms = self._get_host_volume_bdms(context,
                                                       use_slave=True)
        if not compute_host_bdms:
            return

        LOG.debug("Updating volume usage cache")
        try:
            vol_usages = self.driver.get_all_volume_usage(context,
                                                          compute_host_bdms)
        except NotImplementedError:
            return

        self._update_volume_usage_cache(context, vol_usages)

    @periodic_task.periodic_task(spacing=CONF.sync_power_state_interval,
                                 run_immediately=True)
    def _sync_power_states(self, context):
        """Align power states between the database and the hypervisor.

        To sync power state data we make a DB call to get the number of
        virtual machines known by the hypervisor and if the number matches the
        number of virtual machines known by the database, we proceed in a lazy
        loop, one database record at a time, checking if the hypervisor has the
        same power state as is in the database.
        """
        db_instances = objects.InstanceList.get_by_host(context, self.host,
                                                        expected_attrs=[],
                                                        use_slave=True)

        try:
            num_vm_instances = self.driver.get_num_instances()
        except exception.VirtDriverNotReady as e:
            # If the virt driver is not ready, like ironic-api not being up
            # yet in the case of ironic, just log it and exit.
            LOG.info('Skipping _sync_power_states periodic task due to: %s', e)
            return

        num_db_instances = len(db_instances)

        if num_vm_instances != num_db_instances:
            LOG.warning("While synchronizing instance power states, found "
                        "%(num_db_instances)s instances in the database "
                        "and %(num_vm_instances)s instances on the "
                        "hypervisor.",
                        {'num_db_instances': num_db_instances,
                         'num_vm_instances': num_vm_instances})

        def _sync(db_instance):
            # NOTE(melwitt): This must be synchronized as we query state from
            #                two separate sources, the driver and the database.
            #                They are set (in stop_instance) and read, in sync.
            @utils.synchronized(db_instance.uuid)
            def query_driver_power_state_and_sync():
                self._query_driver_power_state_and_sync(context, db_instance)

            try:
                query_driver_power_state_and_sync()
            except Exception:
                LOG.exception("Periodic sync_power_state task had an "
                              "error while processing an instance.",
                              instance=db_instance)

            self._syncs_in_progress.pop(db_instance.uuid)

        for db_instance in db_instances:
            # process syncs asynchronously - don't want instance locking to
            # block entire periodic task thread
            uuid = db_instance.uuid
            if uuid in self._syncs_in_progress:
                LOG.debug('Sync already in progress for %s', uuid)
            else:
                LOG.debug('Triggering sync for uuid %s', uuid)
                self._syncs_in_progress[uuid] = True
                self._sync_power_pool.spawn_n(_sync, db_instance)

    def _query_driver_power_state_and_sync(self, context, db_instance):
        if db_instance.task_state is not None:
            LOG.info("During sync_power_state the instance has a "
                     "pending task (%(task)s). Skip.",
                     {'task': db_instance.task_state}, instance=db_instance)
            return
        # No pending tasks. Now try to figure out the real vm_power_state.
        try:
            vm_instance = self.driver.get_info(db_instance)
            vm_power_state = vm_instance.state
        except exception.InstanceNotFound:
            vm_power_state = power_state.NOSTATE
        # Note(maoy): the above get_info call might take a long time,
        # for example, because of a broken libvirt driver.
        try:
            self._sync_instance_power_state(context,
                                            db_instance,
                                            vm_power_state,
                                            use_slave=True)
        except exception.InstanceNotFound:
            # NOTE(hanlind): If the instance gets deleted during sync,
            # silently ignore.
            pass

    def _stop_unexpected_shutdown_instance(self, context, vm_state,
                                           db_instance, orig_db_power_state,
                                           vm_power_state):
        # this is an exceptional case; make sure our data is up
        # to date before slamming through a power off
        # TODO(jroll) remove the check for TypeError here;
        # it's only here to be able to backport this without
        # breaking out-of-tree drivers.
        try:
            vm_instance = self.driver.get_info(db_instance,
                                               use_cache=False)
            vm_power_state = vm_instance.state
        except TypeError:
            LOG.warning("Your virt driver appears to not support the "
                        "'use_cache' parameter to the 'get_info' method; "
                        "please update your virt driver.")

        # if it still looks off, go ahead and call stop()
        if vm_power_state in (power_state.SHUTDOWN,
                              power_state.CRASHED):

            LOG.warning("Instance shutdown by itself. Calling the "
                        "stop API. Current vm_state: %(vm_state)s, "
                        "current task_state: %(task_state)s, "
                        "original DB power_state: %(db_power_state)s, "
                        "current VM power_state: %(vm_power_state)s",
                        {'vm_state': vm_state,
                         'task_state': db_instance.task_state,
                         'db_power_state': orig_db_power_state,
                         'vm_power_state': vm_power_state},
                        instance=db_instance)
            try:
                # Note(maoy): here we call the API instead of
                # brutally updating the vm_state in the database
                # to allow all the hooks and checks to be performed.
                if db_instance.shutdown_terminate:
                    self.compute_api.delete(context, db_instance)
                else:
                    self.compute_api.stop(context, db_instance)
            except Exception:
                # Note(maoy): there is no need to propagate the error
                # because the same power_state will be retrieved next
                # time and retried.
                # For example, there might be another task scheduled.
                LOG.exception("error during stop() in sync_power_state.",
                              instance=db_instance)

    def _sync_instance_power_state(self, context, db_instance, vm_power_state,
                                   use_slave=False):
        """Align instance power state between the database and hypervisor.

        If the instance is not found on the hypervisor, but is in the database,
        then a stop() API will be called on the instance.
        """

        # We re-query the DB to get the latest instance info to minimize
        # (not eliminate) race condition.
        db_instance.refresh(use_slave=use_slave)
        db_power_state = db_instance.power_state
        vm_state = db_instance.vm_state

        if self.host != db_instance.host:
            # on the sending end of nova-compute _sync_power_state
            # may have yielded to the greenthread performing a live
            # migration; this in turn has changed the resident-host
            # for the VM; However, the instance is still active, it
            # is just in the process of migrating to another host.
            # This implies that the compute source must relinquish
            # control to the compute destination.
            LOG.info("During the sync_power process the "
                     "instance has moved from "
                     "host %(src)s to host %(dst)s",
                     {'src': db_instance.host,
                      'dst': self.host},
                     instance=db_instance)
            return
        elif db_instance.task_state is not None:
            # on the receiving end of nova-compute, it could happen
            # that the DB instance already report the new resident
            # but the actual VM has not showed up on the hypervisor
            # yet. In this case, let's allow the loop to continue
            # and run the state sync in a later round
            LOG.info("During sync_power_state the instance has a "
                     "pending task (%(task)s). Skip.",
                     {'task': db_instance.task_state},
                     instance=db_instance)
            return

        orig_db_power_state = db_power_state
        if vm_power_state != db_power_state:
            LOG.info('During _sync_instance_power_state the DB '
                     'power_state (%(db_power_state)s) does not match '
                     'the vm_power_state from the hypervisor '
                     '(%(vm_power_state)s). Updating power_state in the '
                     'DB to match the hypervisor.',
                     {'db_power_state': db_power_state,
                      'vm_power_state': vm_power_state},
                     instance=db_instance)
            # power_state is always updated from hypervisor to db
            db_instance.power_state = vm_power_state
            db_instance.save()
            db_power_state = vm_power_state

        # Note(maoy): Now resolve the discrepancy between vm_state and
        # vm_power_state. We go through all possible vm_states.
        if vm_state in (vm_states.BUILDING,
                        vm_states.RESCUED,
                        vm_states.RESIZED,
                        vm_states.SUSPENDED,
                        vm_states.ERROR):
            # TODO(maoy): we ignore these vm_state for now.
            pass
        elif vm_state == vm_states.ACTIVE:
            # The only rational power state should be RUNNING
            if vm_power_state in (power_state.SHUTDOWN,
                                  power_state.CRASHED):
                self._stop_unexpected_shutdown_instance(
                    context, vm_state, db_instance, orig_db_power_state,
                    vm_power_state)
            elif vm_power_state == power_state.SUSPENDED:
                LOG.warning("Instance is suspended unexpectedly. Calling "
                            "the stop API.", instance=db_instance)
                try:
                    self.compute_api.stop(context, db_instance)
                except Exception:
                    LOG.exception("error during stop() in sync_power_state.",
                                  instance=db_instance)
            elif vm_power_state == power_state.PAUSED:
                # Note(maoy): a VM may get into the paused state not only
                # because the user request via API calls, but also
                # due to (temporary) external instrumentations.
                # Before the virt layer can reliably report the reason,
                # we simply ignore the state discrepancy. In many cases,
                # the VM state will go back to running after the external
                # instrumentation is done. See bug 1097806 for details.
                LOG.warning("Instance is paused unexpectedly. Ignore.",
                            instance=db_instance)
            elif vm_power_state == power_state.NOSTATE:
                # Occasionally, depending on the status of the hypervisor,
                # which could be restarting for example, an instance may
                # not be found.  Therefore just log the condition.
                LOG.warning("Instance is unexpectedly not found. Ignore.",
                            instance=db_instance)
        elif vm_state == vm_states.STOPPED:
            if vm_power_state not in (power_state.NOSTATE,
                                      power_state.SHUTDOWN,
                                      power_state.CRASHED):
                LOG.warning("Instance is not stopped. Calling "
                            "the stop API. Current vm_state: %(vm_state)s,"
                            " current task_state: %(task_state)s, "
                            "original DB power_state: %(db_power_state)s, "
                            "current VM power_state: %(vm_power_state)s",
                            {'vm_state': vm_state,
                             'task_state': db_instance.task_state,
                             'db_power_state': orig_db_power_state,
                             'vm_power_state': vm_power_state},
                            instance=db_instance)
                try:
                    # NOTE(russellb) Force the stop, because normally the
                    # compute API would not allow an attempt to stop a stopped
                    # instance.
                    self.compute_api.force_stop(context, db_instance)
                except Exception:
                    LOG.exception("error during stop() in sync_power_state.",
                                  instance=db_instance)
        elif vm_state == vm_states.PAUSED:
            if vm_power_state in (power_state.SHUTDOWN,
                                  power_state.CRASHED):
                LOG.warning("Paused instance shutdown by itself. Calling "
                            "the stop API.", instance=db_instance)
                try:
                    self.compute_api.force_stop(context, db_instance)
                except Exception:
                    LOG.exception("error during stop() in sync_power_state.",
                                  instance=db_instance)
        elif vm_state in (vm_states.SOFT_DELETED,
                          vm_states.DELETED):
            if vm_power_state not in (power_state.NOSTATE,
                                      power_state.SHUTDOWN):
                # Note(maoy): this should be taken care of periodically in
                # _cleanup_running_deleted_instances().
                LOG.warning("Instance is not (soft-)deleted.",
                            instance=db_instance)

    @periodic_task.periodic_task
    def _reclaim_queued_deletes(self, context):
        """Reclaim instances that are queued for deletion."""
        interval = CONF.reclaim_instance_interval
        if interval <= 0:
            LOG.debug("CONF.reclaim_instance_interval <= 0, skipping...")
            return

        filters = {'vm_state': vm_states.SOFT_DELETED,
                   'task_state': None,
                   'host': self.host}
        instances = objects.InstanceList.get_by_filters(
            context, filters,
            expected_attrs=objects.instance.INSTANCE_DEFAULT_FIELDS,
            use_slave=True)
        for instance in instances:
            if self._deleted_old_enough(instance, interval):
                bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                        context, instance.uuid)
                LOG.info('Reclaiming deleted instance', instance=instance)
                try:
                    self._delete_instance(context, instance, bdms)
                except Exception as e:
                    LOG.warning("Periodic reclaim failed to delete "
                                "instance: %s",
                                e, instance=instance)

    def _get_nodename(self, instance, refresh=False):
        """Helper method to get the name of the first available node
        on this host. This method should not be used with any operations
        on ironic instances since it does not handle multiple nodes.
        """
        node = self.driver.get_available_nodes(refresh=refresh)[0]
        LOG.debug("No node specified, defaulting to %s", node,
                  instance=instance)
        return node

    def _update_available_resource_for_node(self, context, nodename):

        rt = self._get_resource_tracker()
        try:
            rt.update_available_resource(context, nodename)
        except exception.ComputeHostNotFound:
            # NOTE(comstud): We can get to this case if a node was
            # marked 'deleted' in the DB and then re-added with a
            # different auto-increment id. The cached resource
            # tracker tried to update a deleted record and failed.
            # Don't add this resource tracker to the new dict, so
            # that this will resolve itself on the next run.
            LOG.info("Compute node '%s' not found in "
                     "update_available_resource.", nodename)
            # TODO(jaypipes): Yes, this is inefficient to throw away all of the
            # compute nodes to force a rebuild, but this is only temporary
            # until Ironic baremetal node resource providers are tracked
            # properly in the report client and this is a tiny edge case
            # anyway.
            self._resource_tracker = None
            return
        except Exception:
            LOG.exception("Error updating resources for node %(node)s.",
                          {'node': nodename})

    @periodic_task.periodic_task(spacing=CONF.update_resources_interval)
    def update_available_resource(self, context, startup=False):
        """See driver.get_available_resource()

        Periodic process that keeps that the compute host's understanding of
        resource availability and usage in sync with the underlying hypervisor.

        :param context: security context
        :param startup: True if this is being called when the nova-compute
            service is starting, False otherwise.
        """

        compute_nodes_in_db = self._get_compute_nodes_in_db(context,
                                                            use_slave=True,
                                                            startup=startup)
        try:
            nodenames = set(self.driver.get_available_nodes())
        except exception.VirtDriverNotReady:
            LOG.warning("Virt driver is not ready.")
            return

        rt = self._get_resource_tracker()
        # Delete orphan compute node not reported by driver but still in db
        for cn in compute_nodes_in_db:
            if cn.hypervisor_hostname not in nodenames:
                LOG.info("Deleting orphan compute node %(id)s "
                         "hypervisor host is %(hh)s, "
                         "nodes are %(nodes)s",
                         {'id': cn.id, 'hh': cn.hypervisor_hostname,
                          'nodes': nodenames})
                cn.destroy()
                rt.remove_node(cn.hypervisor_hostname)
                # Delete the corresponding resource provider in placement,
                # along with any associated allocations and inventory.
                # TODO(cdent): Move use of reportclient into resource tracker.
                self.scheduler_client.reportclient.delete_resource_provider(
                    context, cn, cascade=True)

        for nodename in nodenames:
            self._update_available_resource_for_node(context, nodename)

    def _get_compute_nodes_in_db(self, context, use_slave=False,
                                 startup=False):
        try:
            return objects.ComputeNodeList.get_all_by_host(context, self.host,
                                                           use_slave=use_slave)
        except exception.NotFound:
            if startup:
                LOG.warning(
                    "No compute node record found for host %s. If this is "
                    "the first time this service is starting on this "
                    "host, then you can ignore this warning.", self.host)
            else:
                LOG.error("No compute node record for host %s", self.host)
            return []

    @periodic_task.periodic_task(
        spacing=CONF.running_deleted_instance_poll_interval)
    def _cleanup_running_deleted_instances(self, context):
        """Cleanup any instances which are erroneously still running after
        having been deleted.

        Valid actions to take are:

            1. noop - do nothing
            2. log - log which instances are erroneously running
            3. reap - shutdown and cleanup any erroneously running instances
            4. shutdown - power off *and disable* any erroneously running
                          instances

        The use-case for this cleanup task is: for various reasons, it may be
        possible for the database to show an instance as deleted but for that
        instance to still be running on a host machine (see bug
        https://bugs.launchpad.net/nova/+bug/911366).

        This cleanup task is a cross-hypervisor utility for finding these
        zombied instances and either logging the discrepancy (likely what you
        should do in production), or automatically reaping the instances (more
        appropriate for dev environments).
        """
        action = CONF.running_deleted_instance_action

        if action == "noop":
            return

        # NOTE(sirp): admin contexts don't ordinarily return deleted records
        with utils.temporary_mutation(context, read_deleted="yes"):
            for instance in self._running_deleted_instances(context):
                if action == "log":
                    LOG.warning("Detected instance with name label "
                                "'%s' which is marked as "
                                "DELETED but still present on host.",
                                instance.name, instance=instance)

                elif action == 'shutdown':
                    LOG.info("Powering off instance with name label "
                             "'%s' which is marked as "
                             "DELETED but still present on host.",
                             instance.name, instance=instance)
                    try:
                        try:
                            # disable starting the instance
                            self.driver.set_bootable(instance, False)
                        except NotImplementedError:
                            LOG.debug("set_bootable is not implemented "
                                      "for the current driver")
                        # and power it off
                        self.driver.power_off(instance)
                    except Exception:
                        LOG.warning("Failed to power off instance",
                                    instance=instance, exc_info=True)

                elif action == 'reap':
                    LOG.info("Destroying instance with name label "
                             "'%s' which is marked as "
                             "DELETED but still present on host.",
                             instance.name, instance=instance)
                    bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                        context, instance.uuid, use_slave=True)
                    self.instance_events.clear_events_for_instance(instance)
                    try:
                        self._shutdown_instance(context, instance, bdms,
                                                notify=False)
                        self._cleanup_volumes(context, instance, bdms,
                                              detach=False)
                    except Exception as e:
                        LOG.warning("Periodic cleanup failed to delete "
                                    "instance: %s",
                                    e, instance=instance)
                else:
                    raise Exception(_("Unrecognized value '%s'"
                                      " for CONF.running_deleted_"
                                      "instance_action") % action)

    def _running_deleted_instances(self, context):
        """Returns a list of instances nova thinks is deleted,
        but the hypervisor thinks is still running.
        """
        timeout = CONF.running_deleted_instance_timeout
        filters = {'deleted': True,
                   'soft_deleted': False}
        instances = self._get_instances_on_driver(context, filters)
        return [i for i in instances if self._deleted_old_enough(i, timeout)]

    def _deleted_old_enough(self, instance, timeout):
        deleted_at = instance.deleted_at
        if deleted_at:
            deleted_at = deleted_at.replace(tzinfo=None)
        return (not deleted_at or timeutils.is_older_than(deleted_at, timeout))

    @contextlib.contextmanager
    def _error_out_instance_on_exception(self, context, instance,
                                         instance_state=vm_states.ACTIVE):
        instance_uuid = instance.uuid
        try:
            yield
        except NotImplementedError as error:
            with excutils.save_and_reraise_exception():
                LOG.info("Setting instance back to %(state)s after: "
                         "%(error)s",
                         {'state': instance_state, 'error': error},
                         instance_uuid=instance_uuid)
                self._instance_update(context, instance,
                                      vm_state=instance_state,
                                      task_state=None)
        except exception.InstanceFaultRollback as error:
            LOG.info("Setting instance back to ACTIVE after: %s",
                     error, instance_uuid=instance_uuid)
            self._instance_update(context, instance,
                                  vm_state=vm_states.ACTIVE,
                                  task_state=None)
            raise error.inner_exception
        except Exception:
            LOG.exception('Setting instance vm_state to ERROR',
                          instance_uuid=instance_uuid)
            with excutils.save_and_reraise_exception():
                self._set_instance_obj_error_state(context, instance)

    @wrap_exception()
    def add_aggregate_host(self, context, aggregate, host, slave_info):
        """Notify hypervisor of change (for hypervisor pools)."""
        try:
            self.driver.add_to_aggregate(context, aggregate, host,
                                         slave_info=slave_info)
        except NotImplementedError:
            LOG.debug('Hypervisor driver does not support '
                      'add_aggregate_host')
        except exception.AggregateError:
            with excutils.save_and_reraise_exception():
                self.driver.undo_aggregate_operation(
                                    context,
                                    aggregate.delete_host,
                                    aggregate, host)

    @wrap_exception()
    def remove_aggregate_host(self, context, host, slave_info, aggregate):
        """Removes a host from a physical hypervisor pool."""
        try:
            self.driver.remove_from_aggregate(context, aggregate, host,
                                              slave_info=slave_info)
        except NotImplementedError:
            LOG.debug('Hypervisor driver does not support '
                      'remove_aggregate_host')
        except (exception.AggregateError,
                exception.InvalidAggregateAction) as e:
            with excutils.save_and_reraise_exception():
                self.driver.undo_aggregate_operation(
                                    context,
                                    aggregate.add_host,
                                    aggregate, host,
                                    isinstance(e, exception.AggregateError))

    def _process_instance_event(self, instance, event):
        _event = self.instance_events.pop_instance_event(instance, event)
        if _event:
            LOG.debug('Processing event %(event)s',
                      {'event': event.key}, instance=instance)
            _event.send(event)
        else:
            # If it's a network-vif-unplugged event and the instance is being
            # deleted then we don't need to make this a warning as it's
            # expected. There are other things which could trigger this like
            # detaching an interface, but we don't have a task state for that.
            if (event.name == 'network-vif-unplugged' and
                    instance.task_state == task_states.DELETING):
                LOG.debug('Received event %s for instance which is being '
                          'deleted.', event.key, instance=instance)
            else:
                LOG.warning('Received unexpected event %(event)s for '
                            'instance with vm_state %(vm_state)s and '
                            'task_state %(task_state)s.',
                            {'event': event.key,
                             'vm_state': instance.vm_state,
                             'task_state': instance.task_state},
                            instance=instance)

    def _process_instance_vif_deleted_event(self, context, instance,
                                            deleted_vif_id):
        # If an attached port is deleted by neutron, it needs to
        # be detached from the instance.
        # And info cache needs to be updated.
        network_info = instance.info_cache.network_info
        for index, vif in enumerate(network_info):
            if vif['id'] == deleted_vif_id:
                LOG.info('Neutron deleted interface %(intf)s; '
                         'detaching it from the instance and '
                         'deleting it from the info cache',
                         {'intf': vif['id']},
                         instance=instance)
                del network_info[index]
                base_net_api.update_instance_cache_with_nw_info(
                                 self.network_api, context,
                                 instance,
                                 nw_info=network_info)
                try:
                    self.driver.detach_interface(context, instance, vif)
                except NotImplementedError:
                    # Not all virt drivers support attach/detach of interfaces
                    # yet (like Ironic), so just ignore this.
                    pass
                except exception.NovaException as ex:
                    # If the instance was deleted before the interface was
                    # detached, just log it at debug.
                    log_level = (logging.DEBUG
                                 if isinstance(ex, exception.InstanceNotFound)
                                 else logging.WARNING)
                    LOG.log(log_level,
                            "Detach interface failed, "
                            "port_id=%(port_id)s, reason: %(msg)s",
                            {'port_id': deleted_vif_id, 'msg': ex},
                            instance=instance)
                break

    @wrap_instance_event(prefix='compute')
    @wrap_instance_fault
    def extend_volume(self, context, instance, extended_volume_id):

        # If an attached volume is extended by cinder, it needs to
        # be extended by virt driver so host can detect its new size.
        # And bdm needs to be updated.
        LOG.debug('Handling volume-extended event for volume %(vol)s',
                  {'vol': extended_volume_id}, instance=instance)

        try:
            bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                   context, extended_volume_id, instance.uuid)
        except exception.NotFound:
            LOG.warning('Extend volume failed, '
                        'volume %(vol)s is not attached to instance.',
                        {'vol': extended_volume_id},
                        instance=instance)
            return

        LOG.info('Cinder extended volume %(vol)s; '
                 'extending it to detect new size',
                 {'vol': extended_volume_id},
                 instance=instance)
        volume = self.volume_api.get(context, bdm.volume_id)

        if bdm.connection_info is None:
            LOG.warning('Extend volume failed, '
                        'attached volume %(vol)s has no connection_info',
                        {'vol': extended_volume_id},
                        instance=instance)
            return

        connection_info = jsonutils.loads(bdm.connection_info)
        bdm.volume_size = volume['size']
        bdm.save()

        if not self.driver.capabilities.get('supports_extend_volume', False):
            raise exception.ExtendVolumeNotSupported()

        try:
            self.driver.extend_volume(connection_info,
                                      instance)
        except Exception as ex:
            LOG.warning('Extend volume failed, '
                        'volume_id=%(volume_id)s, reason: %(msg)s',
                        {'volume_id': extended_volume_id, 'msg': ex},
                        instance=instance)
            raise

    @wrap_exception()
    def external_instance_event(self, context, instances, events):
        # NOTE(danms): Some event types are handled by the manager, such
        # as when we're asked to update the instance's info_cache. If it's
        # not one of those, look for some thread(s) waiting for the event and
        # unblock them if so.
        for event in events:
            instance = [inst for inst in instances
                        if inst.uuid == event.instance_uuid][0]
            LOG.debug('Received event %(event)s',
                      {'event': event.key},
                      instance=instance)
            if event.name == 'network-changed':
                try:
                    LOG.debug('Refreshing instance network info cache due to '
                              'event %s.', event.key, instance=instance)
                    self.network_api.get_instance_nw_info(
                        context, instance, refresh_vif_id=event.tag)
                except exception.NotFound as e:
                    LOG.info('Failed to process external instance event '
                             '%(event)s due to: %(error)s',
                             {'event': event.key, 'error': six.text_type(e)},
                             instance=instance)
            elif event.name == 'network-vif-deleted':
                try:
                    self._process_instance_vif_deleted_event(context,
                                                             instance,
                                                             event.tag)
                except exception.NotFound as e:
                    LOG.info('Failed to process external instance event '
                             '%(event)s due to: %(error)s',
                             {'event': event.key, 'error': six.text_type(e)},
                             instance=instance)
            elif event.name == 'volume-extended':
                self.extend_volume(context, instance, event.tag)
            else:
                self._process_instance_event(instance, event)

    @periodic_task.periodic_task(spacing=CONF.image_cache_manager_interval,
                                 external_process_ok=True)
    def _run_image_cache_manager_pass(self, context):
        """Run a single pass of the image cache manager."""

        if not self.driver.capabilities.get("has_imagecache", False):
            return

        # Determine what other nodes use this storage
        storage_users.register_storage_use(CONF.instances_path, CONF.host)
        nodes = storage_users.get_storage_users(CONF.instances_path)

        # Filter all_instances to only include those nodes which share this
        # storage path.
        # TODO(mikal): this should be further refactored so that the cache
        # cleanup code doesn't know what those instances are, just a remote
        # count, and then this logic should be pushed up the stack.
        filters = {'deleted': False,
                   'soft_deleted': True,
                   'host': nodes}
        filtered_instances = objects.InstanceList.get_by_filters(context,
                                 filters, expected_attrs=[], use_slave=True)

        self.driver.manage_image_cache(context, filtered_instances)

    @periodic_task.periodic_task(spacing=CONF.instance_delete_interval)
    def _run_pending_deletes(self, context):
        """Retry any pending instance file deletes."""
        LOG.debug('Cleaning up deleted instances')
        filters = {'deleted': True,
                   'soft_deleted': False,
                   'host': CONF.host,
                   'cleaned': False}
        attrs = ['system_metadata']
        with utils.temporary_mutation(context, read_deleted='yes'):
            instances = objects.InstanceList.get_by_filters(
                context, filters, expected_attrs=attrs, use_slave=True)
        LOG.debug('There are %d instances to clean', len(instances))

        # TODO(raj_singh): Remove this if condition when min value is
        # introduced to "maximum_instance_delete_attempts" cfg option.
        if CONF.maximum_instance_delete_attempts < 1:
            LOG.warning('Future versions of Nova will restrict the '
                        '"maximum_instance_delete_attempts" config option '
                        'to values >=1. Update your configuration file to '
                        'mitigate future upgrade issues.')

        for instance in instances:
            attempts = int(instance.system_metadata.get('clean_attempts', '0'))
            LOG.debug('Instance has had %(attempts)s of %(max)s '
                      'cleanup attempts',
                      {'attempts': attempts,
                       'max': CONF.maximum_instance_delete_attempts},
                      instance=instance)
            if attempts < CONF.maximum_instance_delete_attempts:
                success = self.driver.delete_instance_files(instance)

                instance.system_metadata['clean_attempts'] = str(attempts + 1)
                if success:
                    instance.cleaned = True
                with utils.temporary_mutation(context, read_deleted='yes'):
                    instance.save()

    @periodic_task.periodic_task(spacing=CONF.instance_delete_interval)
    def _cleanup_incomplete_migrations(self, context):
        """Delete instance files on failed resize/revert-resize operation

        During resize/revert-resize operation, if that instance gets deleted
        in-between then instance files might remain either on source or
        destination compute node because of race condition.
        """
        LOG.debug('Cleaning up deleted instances with incomplete migration ')
        migration_filters = {'host': CONF.host,
                             'status': 'error'}
        migrations = objects.MigrationList.get_by_filters(context,
                                                          migration_filters)

        if not migrations:
            return

        inst_uuid_from_migrations = set([migration.instance_uuid for migration
                                         in migrations])

        inst_filters = {'deleted': True, 'soft_deleted': False,
                        'uuid': inst_uuid_from_migrations}
        attrs = ['info_cache', 'security_groups', 'system_metadata']
        with utils.temporary_mutation(context, read_deleted='yes'):
            instances = objects.InstanceList.get_by_filters(
                context, inst_filters, expected_attrs=attrs, use_slave=True)

        for instance in instances:
            if instance.host != CONF.host:
                for migration in migrations:
                    if instance.uuid == migration.instance_uuid:
                        # Delete instance files if not cleanup properly either
                        # from the source or destination compute nodes when
                        # the instance is deleted during resizing.
                        self.driver.delete_instance_files(instance)
                        try:
                            migration.status = 'failed'
                            with migration.obj_as_admin():
                                migration.save()
                        except exception.MigrationNotFound:
                            LOG.warning("Migration %s is not found.",
                                        migration.id,
                                        instance=instance)
                        break

    @messaging.expected_exceptions(exception.InstanceQuiesceNotSupported,
                                   exception.QemuGuestAgentNotEnabled,
                                   exception.NovaException,
                                   NotImplementedError)
    @wrap_exception()
    def quiesce_instance(self, context, instance):
        """Quiesce an instance on this host."""
        context = context.elevated()
        image_meta = objects.ImageMeta.from_instance(instance)
        self.driver.quiesce(context, instance, image_meta)

    def _wait_for_snapshots_completion(self, context, mapping):
        for mapping_dict in mapping:
            if mapping_dict.get('source_type') == 'snapshot':

                def _wait_snapshot():
                    snapshot = self.volume_api.get_snapshot(
                        context, mapping_dict['snapshot_id'])
                    if snapshot.get('status') != 'creating':
                        raise loopingcall.LoopingCallDone()

                timer = loopingcall.FixedIntervalLoopingCall(_wait_snapshot)
                timer.start(interval=0.5).wait()

    @messaging.expected_exceptions(exception.InstanceQuiesceNotSupported,
                                   exception.QemuGuestAgentNotEnabled,
                                   exception.NovaException,
                                   NotImplementedError)
    @wrap_exception()
    def unquiesce_instance(self, context, instance, mapping=None):
        """Unquiesce an instance on this host.

        If snapshots' image mapping is provided, it waits until snapshots are
        completed before unqueiscing.
        """
        context = context.elevated()
        if mapping:
            try:
                self._wait_for_snapshots_completion(context, mapping)
            except Exception as error:
                LOG.exception("Exception while waiting completion of "
                              "volume snapshots: %s",
                              error, instance=instance)
        image_meta = objects.ImageMeta.from_instance(instance)
        self.driver.unquiesce(context, instance, image_meta)

    @periodic_task.periodic_task(spacing=CONF.instance_delete_interval)
    def _cleanup_expired_console_auth_tokens(self, context):
        """Remove expired console auth tokens for this host.

        Console authorization tokens and their connection data are stored
        in the database when a user asks for a console connection to an
        instance. After a time they expire. We periodically remove any expired
        tokens from the database.
        """
        # If the database backend isn't in use, don't bother looking for
        # expired tokens. The database backend is not supported for cells v1.
        if not CONF.cells.enable:
            objects.ConsoleAuthToken.\
                clean_expired_console_auths_for_host(context, self.host)
