# vim: tabstop=6 shiftwidth=4 softtabstop=4

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
import contextlib
import functools
import socket
import sys
import time
import traceback
import uuid

from eventlet import greenthread
from oslo.config import cfg

from nova import block_device
from nova.cells import rpcapi as cells_rpcapi
from nova.cloudpipe import pipelib
from nova import compute
from nova.compute import flavors
from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
from nova import consoleauth
import nova.context
from nova import exception
from nova import hooks
from nova.image import glance
from nova import manager
from nova import network
from nova.network import model as network_model
from nova.network.security_group import openstack_driver
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier
from nova.openstack.common import periodic_task
from nova.openstack.common import rpc
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils
from nova import paths
from nova import quota
from nova import safe_utils
from nova import utils
from nova.virt import driver
from nova.virt import event as virtevent
from nova.virt import storage_users
from nova.virt import virtapi
from nova import volume


compute_opts = [
    cfg.StrOpt('console_host',
               default=socket.gethostname(),
               help='Console proxy host to use to connect '
                    'to instances on this host.'),
    cfg.StrOpt('default_access_ip_network_name',
               default=None,
               help='Name of network to use to set access ips for instances'),
    cfg.BoolOpt('defer_iptables_apply',
                default=False,
                help='Whether to batch up the application of IPTables rules'
                     ' during a host restart and apply all at the end of the'
                     ' init phase'),
    cfg.StrOpt('instances_path',
               default=paths.state_path_def('instances'),
               help='where instances are stored on disk'),
    cfg.BoolOpt('instance_usage_audit',
               default=False,
               help="Generate periodic compute.instance.exists notifications"),
    cfg.IntOpt('live_migration_retry_count',
               default=30,
               help="Number of 1 second retries needed in live_migration"),
    cfg.BoolOpt('resume_guests_state_on_host_boot',
                default=False,
                help='Whether to start guests that were running before the '
                     'host rebooted'),
    cfg.IntOpt('network_allocate_retries',
               default=0,
               help="Number of times to retry network allocation on failures"),
    ]

interval_opts = [
    cfg.IntOpt('bandwidth_poll_interval',
               default=600,
               help='interval to pull bandwidth usage info'),
    cfg.IntOpt('sync_power_state_interval',
               default=600,
               help='interval to sync power states between '
                    'the database and the hypervisor'),
    cfg.IntOpt("heal_instance_info_cache_interval",
               default=60,
               help="Number of seconds between instance info_cache self "
                        "healing updates"),
    cfg.IntOpt('host_state_interval',
               default=120,
               help='Interval in seconds for querying the host status'),
    cfg.IntOpt("image_cache_manager_interval",
               default=2400,
               help='Number of seconds to wait between runs of the image '
                        'cache manager'),
    cfg.IntOpt('reclaim_instance_interval',
               default=0,
               help='Interval in seconds for reclaiming deleted instances'),
    cfg.IntOpt('volume_usage_poll_interval',
               default=0,
               help='Interval in seconds for gathering volume usages'),
    cfg.IntOpt('shelved_poll_interval',
               default=3600,
               help='Interval in seconds for polling shelved instances to '
                    'offload'),
    cfg.IntOpt('shelved_offload_time',
               default=0,
               help='Time in seconds before a shelved instance is eligible '
                    'for removing from a host.  -1 never offload, 0 offload '
                    'when shelved'),
    cfg.IntOpt('instance_delete_interval',
               default=300,
               help=('Interval in seconds for retrying failed instance file '
                     'deletes'))
]

timeout_opts = [
    cfg.IntOpt("reboot_timeout",
               default=0,
               help="Automatically hard reboot an instance if it has been "
                    "stuck in a rebooting state longer than N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("instance_build_timeout",
               default=0,
               help="Amount of time in seconds an instance can be in BUILD "
                    "before going into ERROR status."
                    "Set to 0 to disable."),
    cfg.IntOpt("rescue_timeout",
               default=0,
               help="Automatically unrescue an instance after N seconds. "
                    "Set to 0 to disable."),
    cfg.IntOpt("resize_confirm_window",
               default=0,
               help="Automatically confirm resizes after N seconds. "
                    "Set to 0 to disable."),
]

running_deleted_opts = [
    cfg.StrOpt("running_deleted_instance_action",
               default="log",
               help="Action to take if a running deleted instance is detected."
                    "Valid options are 'noop', 'log' and 'reap'. "
                    "Set to 'noop' to disable."),
    cfg.IntOpt("running_deleted_instance_poll_interval",
               default=1800,
               help="Number of seconds to wait between runs of the cleanup "
                    "task."),
    cfg.IntOpt("running_deleted_instance_timeout",
               default=0,
               help="Number of seconds after being deleted when a running "
                    "instance should be considered eligible for cleanup."),
]

instance_cleaning_opts = [
    cfg.IntOpt('maximum_instance_delete_attempts',
               default=5,
               help=('The number of times to attempt to reap an instance\'s '
                     'files.')),
]

CONF = cfg.CONF
CONF.register_opts(compute_opts)
CONF.register_opts(interval_opts)
CONF.register_opts(timeout_opts)
CONF.register_opts(running_deleted_opts)
CONF.register_opts(instance_cleaning_opts)
CONF.import_opt('allow_resize_to_same_host', 'nova.compute.api')
CONF.import_opt('console_topic', 'nova.console.rpcapi')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('vnc_enabled', 'nova.vnc')
CONF.import_opt('enabled', 'nova.spice', group='spice')
CONF.import_opt('enable', 'nova.cells.opts', group='cells')

LOG = logging.getLogger(__name__)


def publisher_id(host=None):
    return notifier.publisher_id("compute", host)


def reverts_task_state(function):
    """Decorator to revert task_state on failure."""

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        try:
            return function(self, context, *args, **kwargs)
        except exception.UnexpectedTaskStateError:
            # Note(maoy): unexpected task state means the current
            # task is preempted. Do not clear task state in this
            # case.
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Possibly task preempted."))
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self._instance_update(context,
                                          kwargs['instance']['uuid'],
                                          task_state=None)
                except Exception:
                    pass

    return decorated_function


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
            kwargs.update(dict(zip(function.func_code.co_varnames[2:], args)))

            with excutils.save_and_reraise_exception():
                compute_utils.add_instance_fault_from_exc(context,
                        self.conductor_api, kwargs['instance'],
                        e, sys.exc_info())

    return decorated_function


def wrap_instance_event(function):
    """Wraps a method to log the event taken on the instance, and result.

    This decorator wraps a method to log the start and result of an event, as
    part of an action taken on an instance.
    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        wrapped_func = utils.get_wrapped_function(function)
        keyed_args = safe_utils.getcallargs(wrapped_func, context, *args,
                                       **kwargs)
        instance_uuid = keyed_args['instance']['uuid']

        event_name = 'compute_{0}'.format(function.func_name)
        with compute_utils.EventReporter(context, self.conductor_api,
                                         event_name, instance_uuid):

            function(self, context, *args, **kwargs)

    return decorated_function


# TODO(danms): Remove me after havana
def object_compat(function):
    """Wraps a method that expects a new-world instance

    This provides compatibility for callers passing old-style dict
    instances.
    """

    @functools.wraps(function)
    def decorated_function(self, context, *args, **kwargs):
        metas = ['metadata', 'system_metadata']
        try:
            instance = kwargs['instance']
        except KeyError:
            instance = args[0]
            args = args[1:]
        if isinstance(instance, dict):
            instance = instance_obj.Instance._from_db_object(
                context, instance_obj.Instance(), instance,
                expected_attrs=metas)
            instance._context = context
        kwargs['instance'] = instance

        return function(self, context, *args, **kwargs)

    return decorated_function


def _get_image_meta(context, image_ref):
    image_service, image_id = glance.get_remote_image_service(context,
                                                              image_ref)
    return image_service.show(context, image_id)


class ComputeVirtAPI(virtapi.VirtAPI):
    def __init__(self, compute):
        super(ComputeVirtAPI, self).__init__()
        self._compute = compute

    def instance_update(self, context, instance_uuid, updates):
        return self._compute._instance_update(context,
                                              instance_uuid,
                                              **updates)

    def aggregate_get_by_host(self, context, host, key=None):
        return self._compute.conductor_api.aggregate_get_by_host(context,
                                                                 host, key=key)

    def aggregate_metadata_add(self, context, aggregate, metadata,
                               set_delete=False):
        return self._compute.conductor_api.aggregate_metadata_add(
            context, aggregate, metadata, set_delete=set_delete)

    def aggregate_metadata_delete(self, context, aggregate, key):
        return self._compute.conductor_api.aggregate_metadata_delete(
            context, aggregate, key)

    def security_group_get_by_instance(self, context, instance):
        return self._compute.conductor_api.security_group_get_by_instance(
            context, instance)

    def security_group_rule_get_by_security_group(self, context,
                                                  security_group):
        return (self._compute.conductor_api.
                security_group_rule_get_by_security_group(context,
                                                          security_group))

    def provider_fw_rule_get_all(self, context):
        return self._compute.conductor_api.provider_fw_rule_get_all(context)

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        return self._compute.conductor_api.agent_build_get_by_triple(
            context, hypervisor, os, architecture)

    def instance_type_get(self, context, instance_type_id):
        return self._compute.conductor_api.instance_type_get(context,
                                                             instance_type_id)


class ComputeManager(manager.SchedulerDependentManager):
    """Manages the running instances from creation to destruction."""

    RPC_API_VERSION = '2.36'

    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        self.virtapi = ComputeVirtAPI(self)
        self.network_api = network.API()
        self.volume_api = volume.API()
        self._last_host_check = 0
        self._last_bw_usage_poll = 0
        self._last_vol_usage_poll = 0
        self._last_info_cache_heal = 0
        self._last_bw_usage_cell_update = 0
        self.compute_api = compute.API()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.conductor_api = conductor.API()
        self.is_neutron_security_groups = (
            openstack_driver.is_neutron_security_groups())
        self.consoleauth_rpcapi = consoleauth.rpcapi.ConsoleAuthAPI()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        self._resource_tracker_dict = {}

        super(ComputeManager, self).__init__(service_name="compute",
                                             *args, **kwargs)

        # NOTE(russellb) Load the driver last.  It may call back into the
        # compute manager via the virtapi, so we want it to be fully
        # initialized before that happens.
        self.driver = driver.load_compute_driver(self.virtapi, compute_driver)

    def _get_resource_tracker(self, nodename):
        rt = self._resource_tracker_dict.get(nodename)
        if not rt:
            if nodename not in self.driver.get_available_nodes():
                raise exception.NovaException(
                    _("%s is not a valid node managed by this "
                      "compute host.") % nodename)

            rt = resource_tracker.ResourceTracker(self.host,
                                                  self.driver,
                                                  nodename)
            self._resource_tracker_dict[nodename] = rt
        return rt

    def _instance_update(self, context, instance_uuid, **kwargs):
        """Update an instance in the database using kwargs as value."""

        instance_ref = self.conductor_api.instance_update(context,
                                                          instance_uuid,
                                                          **kwargs)
        if (instance_ref['host'] == self.host and
                instance_ref['node'] in self.driver.get_available_nodes()):

            rt = self._get_resource_tracker(instance_ref.get('node'))
            rt.update_usage(context, instance_ref)

        return instance_ref

    def _set_instance_error_state(self, context, instance_uuid):
        try:
            self._instance_update(context, instance_uuid,
                                  vm_state=vm_states.ERROR)
        except exception.InstanceNotFound:
            LOG.debug(_('Instance has been destroyed from under us while '
                        'trying to set it to ERROR'),
                      instance_uuid=instance_uuid)

    def _set_instance_obj_error_state(self, context, instance):
        try:
            instance.vm_state = vm_states.ERROR
            instance.save()
        except exception.InstanceNotFound:
            LOG.debug(_('Instance has been destroyed from under us while '
                        'trying to set it to ERROR'),
                      instance_uuid=instance.uuid)

    def _get_instances_on_driver(self, context, filters=None,
                                 columns_to_join=None):
        """Return a list of instance records for the instances found
        on the hypervisor which satisfy the specified filters. If filters=None
        return a list of instance records for all the instances found on the
        hypervisor.
        """
        if not filters:
            filters = {}
        try:
            driver_uuids = self.driver.list_instance_uuids()
            filters['uuid'] = driver_uuids
            local_instances = self.conductor_api.instance_get_all_by_filters(
                    context, filters, columns_to_join=columns_to_join)
            return local_instances
        except NotImplementedError:
            pass

        # The driver doesn't support uuids listing, so we'll have
        # to brute force.
        driver_instances = self.driver.list_instances()
        instances = self.conductor_api.instance_get_all_by_filters(
            context, filters, columns_to_join=columns_to_join)
        name_map = dict((instance['name'], instance) for instance in instances)
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
        evacuated to another host. Check that the instances reported
        by the driver are still associated with this host.  If they are
        not, destroy them.
        """
        our_host = self.host
        filters = {'deleted': False}
        local_instances = self._get_instances_on_driver(context, filters)
        for instance in local_instances:
            instance_host = instance['host']
            if instance_host != our_host:
                LOG.info(_('Deleting instance as its host ('
                           '%(instance_host)s) is not equal to our '
                           'host (%(our_host)s).'),
                         {'instance_host': instance_host,
                          'our_host': our_host}, instance=instance)
                destroy_disks = False
                try:
                    network_info = self._get_instance_nw_info(context,
                                                              instance)
                    bdi = self._get_instance_volume_block_device_info(context,
                                                                      instance)
                    destroy_disks = not (self._is_instance_storage_shared(
                                                            context, instance))
                except exception.InstanceNotFound:
                    network_info = network_model.NetworkInfo()
                    bdi = {}
                    LOG.info(_('Instance has been marked deleted already, '
                               'removing it from the hypervisor.'),
                             instance=instance)
                    # always destroy disks if the instance was deleted
                    destroy_disks = True
                self.driver.destroy(instance,
                                    self._legacy_nw_info(network_info),
                                    bdi, destroy_disks)

    def _is_instance_storage_shared(self, context, instance):
        shared_storage = True
        data = None
        try:
            data = self.driver.check_instance_shared_storage_local(context,
                                                       instance)
            if data:
                shared_storage = (self.compute_rpcapi.
                                  check_instance_shared_storage(context,
                                  instance,
                                  data))
        except NotImplementedError:
            LOG.warning(_('Hypervisor driver does not support '
                          'instance shared storage check, '
                          'assuming it\'s not on shared storage'),
                        instance=instance)
            shared_storage = False
        except Exception:
            LOG.exception(_('Failed to check if instance shared'),
                      instance=instance)
        finally:
            if data:
                self.driver.check_instance_shared_storage_cleanup(context,
                                                                  data)
        return shared_storage

    def _complete_partial_deletion(self, context, instance):
        """
        Complete deletion for instances in DELETED status but not marked as
        deleted in the DB
        """
        self.conductor_api.instance_destroy(context, instance)
        project_id = instance['project_id']
        if (instance.get('user_id', None) and
                (context.user_id != instance['user_id'])):
            user_id = instance['user_id']
        else:
            user_id = context.user_id
        system_meta = utils.metadata_to_dict(instance['system_metadata'])
        bdms = self._get_instance_volume_bdms(context, instance)
        instance_vcpus = instance['vcpus']
        instance_memory_mb = instance['memory_mb']
        reservations = quota.QUOTAS.reserve(context,
                                            project_id=project_id,
                                            user_id=user_id,
                                            instances=-1,
                                            cores=-instance_vcpus,
                                            ram=-instance_memory_mb)
        self._complete_deletion(context,
                                instance,
                                bdms,
                                reservations,
                                project_id,
                                system_meta,
                                user_id=user_id)

    def _complete_deletion(self, context, instance, bdms,
                           reservations, prj_id, system_meta, user_id=None):

        self._quota_commit(context, reservations, project_id=prj_id,
                           user_id=user_id)
        # ensure block device mappings are not leaked
        self.conductor_api.block_device_mapping_destroy(context, bdms)

        # NOTE(ndipanov): Delete the dummy image BDM as well. This will not
        #                 be needed once the manager code is using the image
        if instance['image_ref']:
            # Do not convert to legacy here - we want them all
            leftover_bdm = \
                self.conductor_api.block_device_mapping_get_all_by_instance(
                    context, obj_base.obj_to_primitive(instance))
            self.conductor_api.block_device_mapping_destroy(context,
                                                            leftover_bdm)

        self._notify_about_instance_usage(context, instance, "delete.end",
                system_metadata=system_meta)

        if CONF.vnc_enabled or CONF.spice.enabled:
            if CONF.cells.enable:
                self.cells_rpcapi.consoleauth_delete_tokens(context,
                        instance['uuid'])
            else:
                self.consoleauth_rpcapi.delete_tokens_for_instance(context,
                        instance['uuid'])

    def _init_instance(self, context, instance):
        '''Initialize this instance during service init.'''

        # instance was supposed to shut down - don't attempt
        # recovery in any case
        if instance['vm_state'] == vm_states.SOFT_DELETED:
            return

        if instance['vm_state'] == vm_states.DELETED:
            try:
                self._complete_partial_deletion(context, instance)
            except Exception:
                # we don't want that an exception blocks the init_host
                msg = _('Failed to complete a deletion')
                LOG.exception(msg, instance=instance)
            finally:
                return

        net_info = compute_utils.get_nw_info_for_instance(instance)

        # We're calling plug_vifs to ensure bridge and iptables
        # rules exist. This needs to be called for each instance.
        legacy_net_info = self._legacy_nw_info(net_info)

        # Keep compatibility with folsom, update networkinfo and
        # add vif type to instance_info_cache.
        if (legacy_net_info and
                isinstance(legacy_net_info[0], tuple) and
                legacy_net_info[0][1].get('vif_type') is None):
            # Call to network API to get instance info, this will
            # force an update to the instance's info_cache
            retry_time = 0
            # Continue retrying until _get_instance_nw_info() succeeds.
            while True:
                try:
                    net_info = self._get_instance_nw_info(context, instance)
                    break
                except Exception:
                    # Retry in an exponential backoff fashion
                    # capped at 60 seconds.
                    if retry_time < 60:
                        retry_time += 6
                    LOG.exception(_("Error raised getting network info for "
                                    "instance %(instance_uuid)s. Retrying "
                                    "in %(retry_time)s seconds."),
                                    {'instance_uuid': instance['uuid'],
                                     'retry_time': retry_time})
                    time.sleep(retry_time)
            legacy_net_info = self._legacy_nw_info(net_info)
        self.driver.plug_vifs(instance, legacy_net_info)

        if instance['task_state'] == task_states.RESIZE_MIGRATING:
            # We crashed during resize/migration, so roll back for safety
            try:
                # NOTE(mriedem): check old_vm_state for STOPPED here, if it's
                # not in system_metadata we default to True for backwards
                # compatibility
                sys_meta = utils.instance_sys_meta(instance)
                power_on = sys_meta.get('old_vm_state') != vm_states.STOPPED

                block_dev_info = self._get_instance_volume_block_device_info(
                            context, instance)

                self.driver.finish_revert_migration(
                    instance, self._legacy_nw_info(net_info),
                    block_dev_info, power_on)

            except Exception as e:
                LOG.exception(_('Failed to revert crashed migration'),
                              instance=instance)
            finally:
                LOG.info(_('Instance found in migrating state during '
                           'startup. Resetting task_state'),
                         instance=instance)
                instance = self._instance_update(context, instance['uuid'],
                                                 task_state=None)

        db_state = instance['power_state']
        drv_state = self._get_power_state(context, instance)
        expect_running = (db_state == power_state.RUNNING and
                          drv_state != db_state)

        LOG.debug(_('Current state is %(drv_state)s, state in DB is '
                    '%(db_state)s.'),
                  {'drv_state': drv_state, 'db_state': db_state},
                  instance=instance)

        if expect_running and CONF.resume_guests_state_on_host_boot:
            LOG.info(_('Rebooting instance after nova-compute restart.'),
                     instance=instance)

            block_device_info = \
                self._get_instance_volume_block_device_info(
                    context, instance)

            try:
                self.driver.resume_state_on_host_boot(
                        context,
                        instance,
                        self._legacy_nw_info(net_info),
                        block_device_info)
            except NotImplementedError:
                LOG.warning(_('Hypervisor driver does not support '
                              'resume guests'), instance=instance)
            except Exception:
                # NOTE(vish): The instance failed to resume, so we set the
                #             instance to error and attempt to continue.
                LOG.warning(_('Failed to resume instance'), instance=instance)
                self._set_instance_error_state(context, instance['uuid'])

        elif drv_state == power_state.RUNNING:
            # VMwareAPI drivers will raise an exception
            try:
                self.driver.ensure_filtering_rules_for_instance(
                                       instance,
                                       self._legacy_nw_info(net_info))
            except NotImplementedError:
                LOG.warning(_('Hypervisor driver does not support '
                              'firewall rules'), instance=instance)

    def handle_lifecycle_event(self, event):
        LOG.info(_("Lifecycle event %(state)d on VM %(uuid)s") %
                  {'state': event.get_transition(),
                   'uuid': event.get_instance_uuid()})
        context = nova.context.get_admin_context()
        instance = instance_obj.Instance.get_by_uuid(
            context, event.get_instance_uuid())
        vm_power_state = None
        if event.get_transition() == virtevent.EVENT_LIFECYCLE_STOPPED:
            vm_power_state = power_state.SHUTDOWN
        elif event.get_transition() == virtevent.EVENT_LIFECYCLE_STARTED:
            vm_power_state = power_state.RUNNING
        elif event.get_transition() == virtevent.EVENT_LIFECYCLE_PAUSED:
            vm_power_state = power_state.PAUSED
        elif event.get_transition() == virtevent.EVENT_LIFECYCLE_RESUMED:
            vm_power_state = power_state.RUNNING
        else:
            LOG.warning(_("Unexpected power state %d") %
                        event.get_transition())

        if vm_power_state is not None:
            self._sync_instance_power_state(context,
                                            instance,
                                            vm_power_state)

    def handle_events(self, event):
        if isinstance(event, virtevent.LifecycleEvent):
            try:
                self.handle_lifecycle_event(event)
            except exception.InstanceNotFound:
                LOG.debug(_("Event %s arrived for non-existent instance. The "
                            "instance was probably deleted.") % event)
        else:
            LOG.debug(_("Ignoring event %s") % event)

    def init_virt_events(self):
        self.driver.register_event_listener(self.handle_events)

    def init_host(self):
        """Initialization for a standalone compute service."""
        self.driver.init_host(host=self.host)
        context = nova.context.get_admin_context()
        instances = instance_obj.InstanceList.get_by_host(
            context, self.host, expected_attrs=['info_cache'])

        if CONF.defer_iptables_apply:
            self.driver.filter_defer_apply_on()

        self.init_virt_events()

        try:
            # checking that instance was not already evacuated to other host
            self._destroy_evacuated_instances(context)
            for instance in instances:
                self._init_instance(context, instance)
        finally:
            if CONF.defer_iptables_apply:
                self.driver.filter_defer_apply_off()

        self._report_driver_status(context)
        self.publish_service_capabilities(context)

    def pre_start_hook(self, **kwargs):
        """After the service is initialized, but before we fully bring
        the service up by listening on RPC queues, make sure to update
        our available resources.
        """
        self.update_available_resource(nova.context.get_admin_context())

    def _get_power_state(self, context, instance):
        """Retrieve the power state for the given instance."""
        LOG.debug(_('Checking state'), instance=instance)
        try:
            return self.driver.get_info(instance)["state"]
        except exception.NotFound:
            return power_state.NOSTATE

    # NOTE(russellb) This method can be removed in 3.0 of this API.  It is
    # deprecated in favor of the method in the base API.
    def get_backdoor_port(self, context):
        """Return backdoor port for eventlet_backdoor."""
        return self.backdoor_port

    def get_console_topic(self, context):
        """Retrieves the console host for a project on this host.

        Currently this is just set in the flags for each compute host.

        """
        #TODO(mdragon): perhaps make this variable by console_type?
        return rpc.queue_get_for(context,
                                 CONF.console_topic,
                                 CONF.console_host)

    def get_console_pool_info(self, context, console_type):
        return self.driver.get_console_pool_info(console_type)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def refresh_security_group_rules(self, context, security_group_id):
        """Tell the virtualization driver to refresh security group rules.

        Passes straight through to the virtualization driver.

        """
        return self.driver.refresh_security_group_rules(security_group_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def refresh_security_group_members(self, context, security_group_id):
        """Tell the virtualization driver to refresh security group members.

        Passes straight through to the virtualization driver.

        """
        return self.driver.refresh_security_group_members(security_group_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def refresh_instance_security_rules(self, context, instance):
        """Tell the virtualization driver to refresh security rules for
        an instance.

        Passes straight through to the virtualization driver.

        Synchronise the call beacuse we may still be in the middle of
        creating the instance.
        """
        @utils.synchronized(instance['uuid'])
        def _sync_refresh():
            return self.driver.refresh_instance_security_rules(instance)
        return _sync_refresh()

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def refresh_provider_fw_rules(self, context):
        """This call passes straight through to the virtualization driver."""
        return self.driver.refresh_provider_fw_rules()

    def _get_instance_nw_info(self, context, instance):
        """Get a list of dictionaries of network data of an instance."""
        if (not hasattr(instance, 'system_metadata') or
                len(instance['system_metadata']) == 0):
            # NOTE(danms): Several places in the code look up instances without
            # pulling system_metadata for performance, and call this function.
            # If we get an instance without it, re-fetch so that the call
            # to network_api (which requires it for instance_type) will
            # succeed.
            instance = self.conductor_api.instance_get_by_uuid(
                context, instance['uuid'])
        network_info = self.network_api.get_instance_nw_info(context,
                                                             instance)
        return network_info

    def _legacy_nw_info(self, network_info):
        """Converts the model nw_info object to legacy style."""
        if self.driver.legacy_nwinfo():
            network_info = network_info.legacy()
        return network_info

    def _await_block_device_map_created(self, context, vol_id, max_tries=30,
                                        wait_between=1):
        # TODO(yamahata): creating volume simultaneously
        #                 reduces creation time?
        # TODO(yamahata): eliminate dumb polling
        # TODO(harlowja): make the max_tries configurable or dynamic?
        attempts = 0
        start = time.time()
        while attempts < max_tries:
            volume = self.volume_api.get(context, vol_id)
            volume_status = volume['status']
            if volume_status != 'creating':
                if volume_status != 'available':
                    LOG.warn(_("Volume id: %s finished being created but was"
                               " not set as 'available'"), vol_id)
                # NOTE(harlowja): return how many attempts were tried
                return attempts + 1
            greenthread.sleep(wait_between)
            attempts += 1
        # NOTE(harlowja): Should only happen if we ran out of attempts
        raise exception.VolumeNotCreated(volume_id=vol_id,
                                         seconds=int(time.time() - start),
                                         attempts=attempts)

    def _setup_block_device_mapping(self, context, instance, bdms):
        """setup volumes for block device mapping."""
        block_device_mapping = []
        swap = None
        ephemerals = []
        for bdm in bdms:
            LOG.debug(_('Setting up bdm %s'), bdm, instance=instance)

            if bdm['no_device']:
                continue
            if bdm['virtual_name']:
                virtual_name = bdm['virtual_name']
                device_name = bdm['device_name']
                assert block_device.is_swap_or_ephemeral(virtual_name)
                if virtual_name == 'swap':
                    swap = {'device_name': device_name,
                            'swap_size': bdm['volume_size']}
                elif block_device.is_ephemeral(virtual_name):
                    eph = {'num': block_device.ephemeral_num(virtual_name),
                           'virtual_name': virtual_name,
                           'device_name': device_name,
                           'size': bdm['volume_size']}
                    ephemerals.append(eph)
                continue

            if ((bdm['snapshot_id'] is not None) and
                    (bdm['volume_id'] is None)):
                # TODO(yamahata): default name and description
                snapshot = self.volume_api.get_snapshot(context,
                                                        bdm['snapshot_id'])
                vol = self.volume_api.create(context, bdm['volume_size'],
                                             '', '', snapshot)
                self._await_block_device_map_created(context, vol['id'])
                self.conductor_api.block_device_mapping_update(
                    context, bdm['id'], {'volume_id': vol['id']})
                bdm['volume_id'] = vol['id']

            if bdm['volume_id'] is not None:
                volume = self.volume_api.get(context, bdm['volume_id'])
                self.volume_api.check_attach(context, volume,
                                             instance=instance)
                cinfo = self._attach_volume_boot(context,
                                                 instance,
                                                 volume,
                                                 bdm['device_name'])
                if 'serial' not in cinfo:
                    cinfo['serial'] = bdm['volume_id']
                self.conductor_api.block_device_mapping_update(
                        context, bdm['id'],
                        {'connection_info': jsonutils.dumps(cinfo)})
                bdmap = {'connection_info': cinfo,
                         'mount_device': bdm['device_name'],
                         'delete_on_termination': bdm['delete_on_termination']}
                block_device_mapping.append(bdmap)

        block_device_info = {
            'root_device_name': instance['root_device_name'],
            'swap': swap,
            'ephemerals': ephemerals,
            'block_device_mapping': block_device_mapping
        }

        return block_device_info

    def _decode_files(self, injected_files):
        """Base64 decode the list of files to inject."""
        if not injected_files:
            return []

        def _decode(f):
            path, contents = f
            try:
                decoded = base64.b64decode(contents)
                return path, decoded
            except TypeError:
                raise exception.Base64Exception(path=path)

        return [_decode(f) for f in injected_files]

    def _run_instance(self, context, request_spec,
                      filter_properties, requested_networks, injected_files,
                      admin_password, is_first_time, node, instance):
        """Launch a new instance with specified options."""

        extra_usage_info = {}

        def notify(status, msg=None, **kwargs):
            """Send a create.{start,error,end} notification."""
            type_ = "create.%(status)s" % dict(status=status)
            info = extra_usage_info.copy()
            if not msg:
                msg = ""
            info['message'] = msg
            self._notify_about_instance_usage(context, instance, type_,
                    extra_usage_info=info, **kwargs)

        try:
            image_meta = self._prebuild_instance(context, instance)
            if image_meta:
                extra_usage_info = {"image_name": image_meta['name']}

            notify("start")  # notify that build is starting

            instance, network_info = self._build_instance(context,
                    request_spec, filter_properties, requested_networks,
                    injected_files, admin_password, is_first_time, node,
                    instance, image_meta)
            notify("end", msg=_("Success"), network_info=network_info)

        except exception.RescheduledException as e:
            # Instance build encountered an error, and has been rescheduled.
            notify("error", msg=unicode(e))  # notify that build failed

        except exception.BuildAbortException as e:
            # Instance build aborted due to a non-failure
            LOG.info(e)
            notify("end", msg=unicode(e))  # notify that build is done

        except Exception as e:
            # Instance build encountered a non-recoverable error:
            with excutils.save_and_reraise_exception():
                self._set_instance_error_state(context, instance['uuid'])
                notify("error", msg=unicode(e))  # notify that build failed

    def _prebuild_instance(self, context, instance):
        self._check_instance_exists(context, instance)

        try:
            self._start_building(context, instance)
        except exception.InstanceNotFound:
            msg = _("Instance disappeared before we could start it")
            # Quickly bail out of here
            raise exception.BuildAbortException(instance_uuid=instance['uuid'],
                    reason=msg)

        if instance['image_ref']:
            image_meta = _get_image_meta(context, instance['image_ref'])
        else:
            # Instance was started from volume - so no image ref
            image_meta = {}

        return image_meta

    def _build_instance(self, context, request_spec, filter_properties,
            requested_networks, injected_files, admin_password, is_first_time,
            node, instance, image_meta):
        context = context.elevated()

        # If neutron security groups pass requested security
        # groups to allocate_for_instance()
        if request_spec and self.is_neutron_security_groups:
            security_groups = request_spec.get('security_group')
        else:
            security_groups = []

        if node is None:
            node = self.driver.get_available_nodes()[0]
            LOG.debug(_("No node specified, defaulting to %s"), node)

        network_info = None
        bdms = self.conductor_api.block_device_mapping_get_all_by_instance(
            context, instance)

        # b64 decode the files to inject:
        injected_files_orig = injected_files
        injected_files = self._decode_files(injected_files)

        rt = self._get_resource_tracker(node)
        try:
            limits = filter_properties.get('limits', {})
            with rt.instance_claim(context, instance, limits):
                macs = self.driver.macs_for_instance(instance)

                network_info = self._allocate_network(context, instance,
                        requested_networks, macs, security_groups)

                self._instance_update(
                        context, instance['uuid'],
                        vm_state=vm_states.BUILDING,
                        task_state=task_states.BLOCK_DEVICE_MAPPING)

                block_device_info = self._prep_block_device(
                        context, instance, bdms)

                set_access_ip = (is_first_time and
                                 not instance['access_ip_v4'] and
                                 not instance['access_ip_v6'])

                instance = self._spawn(context, instance, image_meta,
                                       network_info, block_device_info,
                                       injected_files, admin_password,
                                       set_access_ip=set_access_ip)
        except exception.InstanceNotFound:
            # the instance got deleted during the spawn
            # Make sure the async call finishes
            msg = _("Instance disappeared during build")
            if network_info is not None:
                network_info.wait(do_raise=False)
            try:
                self._deallocate_network(context, instance)
            except Exception:
                msg = _('Failed to dealloc network '
                        'for deleted instance')
                LOG.exception(msg, instance=instance)
            raise exception.BuildAbortException(
                instance_uuid=instance['uuid'],
                reason=msg)
        except exception.UnexpectedTaskStateError as e:
            exc_info = sys.exc_info()
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            actual_task_state = e.kwargs.get('actual', None)
            if actual_task_state == 'deleting':
                msg = _('Instance was deleted during spawn.')
                LOG.debug(msg, instance=instance)
                raise exception.BuildAbortException(
                        instance_uuid=instance['uuid'], reason=msg)
            else:
                raise exc_info[0], exc_info[1], exc_info[2]
        except Exception:
            exc_info = sys.exc_info()
            # try to re-schedule instance:
            # Make sure the async call finishes
            if network_info is not None:
                network_info.wait(do_raise=False)
            rescheduled = self._reschedule_or_error(context, instance,
                    exc_info, requested_networks, admin_password,
                    injected_files_orig, is_first_time, request_spec,
                    filter_properties, bdms)
            if rescheduled:
                # log the original build error
                self._log_original_error(exc_info, instance['uuid'])
                raise exception.RescheduledException(
                        instance_uuid=instance['uuid'],
                        reason=unicode(exc_info[1]))
            else:
                # not re-scheduling, go to error:
                raise exc_info[0], exc_info[1], exc_info[2]

        # spawn success
        return instance, network_info

    def _log_original_error(self, exc_info, instance_uuid):
        type_, value, tb = exc_info
        LOG.error(_('Error: %s') %
                  traceback.format_exception(type_, value, tb),
                  instance_uuid=instance_uuid)

    def _reschedule_or_error(self, context, instance, exc_info,
            requested_networks, admin_password, injected_files, is_first_time,
            request_spec, filter_properties, bdms=None):
        """Try to re-schedule the build or re-raise the original build error to
        error out the instance.
        """
        instance_uuid = instance['uuid']
        rescheduled = False

        compute_utils.add_instance_fault_from_exc(context, self.conductor_api,
                instance, exc_info[1], exc_info=exc_info)

        try:
            LOG.debug(_("Clean up resource before rescheduling."),
                      instance=instance)
            if bdms is None:
                capi = self.conductor_api
                bdms = capi.block_device_mapping_get_all_by_instance(context,
                                                                     instance)
            self._shutdown_instance(context, instance,
                                    bdms, requested_networks)
            self._cleanup_volumes(context, instance['uuid'], bdms)
        except Exception:
            # do not attempt retry if clean up failed:
            with excutils.save_and_reraise_exception():
                self._log_original_error(exc_info, instance_uuid)

        try:
            method_args = (request_spec, admin_password, injected_files,
                    requested_networks, is_first_time, filter_properties)
            task_state = task_states.SCHEDULING

            rescheduled = self._reschedule(context, request_spec,
                    filter_properties, instance['uuid'],
                    self.scheduler_rpcapi.run_instance, method_args,
                    task_state, exc_info)

        except Exception:
            rescheduled = False
            LOG.exception(_("Error trying to reschedule"),
                          instance_uuid=instance_uuid)

        return rescheduled

    def _reschedule(self, context, request_spec, filter_properties,
            instance_uuid, scheduler_method, method_args, task_state,
            exc_info=None):
        """Attempt to re-schedule a compute operation."""

        retry = filter_properties.get('retry', None)
        if not retry:
            # no retry information, do not reschedule.
            LOG.debug(_("Retry info not present, will not reschedule"),
                      instance_uuid=instance_uuid)
            return

        if not request_spec:
            LOG.debug(_("No request spec, will not reschedule"),
                      instance_uuid=instance_uuid)
            return

        request_spec['instance_uuids'] = [instance_uuid]

        LOG.debug(_("Re-scheduling %(method)s: attempt %(num)d") %
                {'method': scheduler_method.func_name,
                 'num': retry['num_attempts']}, instance_uuid=instance_uuid)

        # reset the task state:
        self._instance_update(context, instance_uuid, task_state=task_state)

        if exc_info:
            # stringify to avoid circular ref problem in json serialization:
            retry['exc'] = traceback.format_exception(*exc_info)

        scheduler_method(context, *method_args)
        return True

    @periodic_task.periodic_task
    def _check_instance_build_time(self, context):
        """Ensure that instances are not stuck in build."""
        timeout = CONF.instance_build_timeout
        if timeout == 0:
            return

        filters = {'vm_state': vm_states.BUILDING,
                   'host': self.host}
        building_insts = self.conductor_api.instance_get_all_by_filters(
            context, filters, columns_to_join=[])

        for instance in building_insts:
            if timeutils.is_older_than(instance['created_at'], timeout):
                self._set_instance_error_state(context, instance['uuid'])
                LOG.warn(_("Instance build timed out. Set to error state."),
                         instance=instance)

    def _check_instance_exists(self, context, instance):
        """Ensure an instance with the same name is not already present."""
        if self.driver.instance_exists(instance['name']):
            raise exception.InstanceExists(name=instance['name'])

    def _start_building(self, context, instance):
        """Save the host and launched_on fields and log appropriately."""
        LOG.audit(_('Starting instance...'), context=context,
                  instance=instance)
        self._instance_update(context, instance['uuid'],
                              vm_state=vm_states.BUILDING,
                              task_state=None,
                              expected_task_state=(task_states.SCHEDULING,
                                                   None))

    def _allocate_network_async(self, context, instance, requested_networks,
                                macs, security_groups, is_vpn):
        """Method used to allocate networks in the background.

        Broken out for testing.
        """
        LOG.debug(_("Allocating IP information in the background."),
                  instance=instance)
        retries = CONF.network_allocate_retries
        if retries < 0:
            LOG.warn(_("Treating negative config value (%(retries)s) for "
                       "'network_allocate_retries' as 0."),
                     {'retries': retries})
        attempts = retries > 1 and retries + 1 or 1
        retry_time = 1
        for attempt in range(1, attempts + 1):
            try:
                nwinfo = self.network_api.allocate_for_instance(
                        context, instance, vpn=is_vpn,
                        requested_networks=requested_networks,
                        macs=macs,
                        conductor_api=self.conductor_api,
                        security_groups=security_groups)
                LOG.debug(_('Instance network_info: |%s|'), nwinfo,
                          instance=instance)
                return nwinfo
            except Exception:
                exc_info = sys.exc_info()
                log_info = {'attempt': attempt,
                            'attempts': attempts}
                if attempt == attempts:
                    LOG.exception(_('Instance failed network setup '
                                    'after %(attempts)d attempt(s)'),
                                  log_info)
                    raise exc_info[0], exc_info[1], exc_info[2]
                LOG.warn(_('Instance failed network setup '
                           '(attempt %(attempt)d of %(attempts)d)'),
                         log_info, instance=instance)
                time.sleep(retry_time)
                retry_time *= 2
                if retry_time > 30:
                    retry_time = 30
        # Not reached.

    def _allocate_network(self, context, instance, requested_networks, macs,
                          security_groups):
        """Start network allocation asynchronously.  Return an instance
        of NetworkInfoAsyncWrapper that can be used to retrieve the
        allocated networks when the operation has finished.
        """
        # NOTE(comstud): Since we're allocating networks asynchronously,
        # this task state has little meaning, as we won't be in this
        # state for very long.
        instance = self._instance_update(context, instance['uuid'],
                                         vm_state=vm_states.BUILDING,
                                         task_state=task_states.NETWORKING,
                                         expected_task_state=None)
        is_vpn = pipelib.is_vpn_image(instance['image_ref'])
        return network_model.NetworkInfoAsyncWrapper(
                self._allocate_network_async, context, instance,
                requested_networks, macs, security_groups, is_vpn)

    def _prep_block_device(self, context, instance, bdms):
        """Set up the block device for an instance with error logging."""
        try:
            return self._setup_block_device_mapping(context, instance, bdms)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Instance failed block device setup'),
                              instance=instance)

    def _spawn(self, context, instance, image_meta, network_info,
               block_device_info, injected_files, admin_password,
               set_access_ip=False):
        """Spawn an instance with error logging and update its power state."""
        instance = self._instance_update(context, instance['uuid'],
                vm_state=vm_states.BUILDING,
                task_state=task_states.SPAWNING,
                expected_task_state=task_states.BLOCK_DEVICE_MAPPING)
        try:
            self.driver.spawn(context, instance, image_meta,
                              injected_files, admin_password,
                              self._legacy_nw_info(network_info),
                              block_device_info)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Instance failed to spawn'), instance=instance)

        current_power_state = self._get_power_state(context, instance)

        update_data = dict(power_state=current_power_state,
                           vm_state=vm_states.ACTIVE,
                           task_state=None,
                           expected_task_state=task_states.SPAWNING,
                           launched_at=timeutils.utcnow())

        def _set_access_ip_values():
            """Add access ip values for a given instance.

            If CONF.default_access_ip_network_name is set, this method will
            grab the corresponding network and set the access ip values
            accordingly. Note that when there are multiple ips to choose
            from, an arbitrary one will be chosen.
            """

            network_name = CONF.default_access_ip_network_name
            if not network_name:
                return

            for vif in network_info:
                if vif['network']['label'] == network_name:
                    for ip in vif.fixed_ips():
                        if ip['version'] == 4:
                            update_data['access_ip_v4'] = ip['address']
                        if ip['version'] == 6:
                            update_data['access_ip_v6'] = ip['address']
                    return

        if set_access_ip:
            _set_access_ip_values()

        return self._instance_update(context, instance['uuid'],
                                     **update_data)

    def _notify_about_instance_usage(self, context, instance, event_suffix,
                                     network_info=None, system_metadata=None,
                                     extra_usage_info=None):
        # NOTE(sirp): The only thing this wrapper function does extra is handle
        # the passing in of `self.host`. Ordinarily this will just be
        # CONF.host`, but `Manager`'s gets a chance to override this in its
        # `__init__`.
        compute_utils.notify_about_instance_usage(
                context, instance, event_suffix, network_info=network_info,
                system_metadata=system_metadata,
                extra_usage_info=extra_usage_info, host=self.host)

    def _deallocate_network(self, context, instance,
                            requested_networks=None):
        LOG.debug(_('Deallocating network for instance'), instance=instance)
        self.network_api.deallocate_for_instance(
            context, instance, requested_networks=requested_networks)

    def _get_volume_bdms(self, bdms):
        """Return only bdms that have a volume_id."""
        return [bdm for bdm in bdms if bdm['volume_id']]

    # NOTE(danms): Legacy interface for digging up volumes in the database
    def _get_instance_volume_bdms(self, context, instance):
        return self._get_volume_bdms(
            self.conductor_api.block_device_mapping_get_all_by_instance(
                context, instance))

    def _get_instance_volume_bdm(self, context, instance, volume_id):
        bdms = self._get_instance_volume_bdms(context, instance)
        for bdm in bdms:
            # NOTE(vish): Comparing as strings because the os_api doesn't
            #             convert to integer and we may wish to support uuids
            #             in the future.
            if str(bdm['volume_id']) == str(volume_id):
                return bdm

    # NOTE(danms): This is a transitional interface until all the callers
    # can provide their own bdms
    def _get_instance_volume_block_device_info(self, context, instance,
                                               bdms=None):
        if bdms is None:
            bdms = self._get_instance_volume_bdms(context, instance)
        return self._get_volume_block_device_info(bdms)

    def _get_volume_block_device_info(self, bdms):
        block_device_mapping = []
        for bdm in bdms:
            try:
                cinfo = jsonutils.loads(bdm['connection_info'])
                if cinfo and 'serial' not in cinfo:
                    cinfo['serial'] = bdm['volume_id']
                bdmap = {'connection_info': cinfo,
                         'mount_device': bdm['device_name'],
                         'delete_on_termination': bdm['delete_on_termination']}
                block_device_mapping.append(bdmap)
            except TypeError:
                # if the block_device_mapping has no value in connection_info
                # (returned as None), don't include in the mapping
                pass
        # NOTE(vish): The mapping is passed in so the driver can disconnect
        #             from remote volumes if necessary
        return {'block_device_mapping': block_device_mapping}

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def run_instance(self, context, instance, request_spec=None,
                     filter_properties=None, requested_networks=None,
                     injected_files=None, admin_password=None,
                     is_first_time=False, node=None):

        if filter_properties is None:
            filter_properties = {}

        @utils.synchronized(instance['uuid'])
        def do_run_instance():
            self._run_instance(context, request_spec,
                    filter_properties, requested_networks, injected_files,
                    admin_password, is_first_time, node, instance)
        do_run_instance()

    def _try_deallocate_network(self, context, instance,
                                requested_networks=None):
        try:
            # tear down allocated network structure
            self._deallocate_network(context, instance, requested_networks)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Failed to deallocate network for instance.'),
                          instance=instance)
                self._set_instance_error_state(context, instance['uuid'])

    def _shutdown_instance(self, context, instance,
                           bdms, requested_networks=None):
        """Shutdown an instance on this host."""
        context = context.elevated()
        LOG.audit(_('%(action_str)s instance') % {'action_str': 'Terminating'},
                  context=context, instance=instance)

        self._notify_about_instance_usage(context, instance, "shutdown.start")

        # get network info before tearing down
        try:
            network_info = self._get_instance_nw_info(context, instance)
        except (exception.NetworkNotFound, exception.NoMoreFixedIps):
            network_info = network_model.NetworkInfo()

        # NOTE(vish) get bdms before destroying the instance
        vol_bdms = self._get_volume_bdms(bdms)
        block_device_info = self._get_instance_volume_block_device_info(
            context, instance, bdms=bdms)

        # NOTE(melwitt): attempt driver destroy before releasing ip, may
        #                want to keep ip allocated for certain failures
        try:
            self.driver.destroy(instance, self._legacy_nw_info(network_info),
                                block_device_info)
        except exception.InstancePowerOffFailure:
            # if the instance can't power off, don't release the ip
            with excutils.save_and_reraise_exception():
                pass
        except Exception:
            with excutils.save_and_reraise_exception():
                # deallocate ip and fail without proceeding to
                # volume api calls, preserving current behavior
                self._try_deallocate_network(context, instance,
                                             requested_networks)

        self._try_deallocate_network(context, instance, requested_networks)

        for bdm in vol_bdms:
            try:
                # NOTE(vish): actual driver detach done in driver.destroy, so
                #             just tell nova-volume that we are done with it.
                connector = self.driver.get_volume_connector(instance)
                self.volume_api.terminate_connection(context,
                                                     bdm['volume_id'],
                                                     connector)
                self.volume_api.detach(context, bdm['volume_id'])
            except exception.DiskNotFound as exc:
                LOG.warn(_('Ignoring DiskNotFound: %s') % exc,
                         instance=instance)
            except exception.VolumeNotFound as exc:
                LOG.warn(_('Ignoring VolumeNotFound: %s') % exc,
                         instance=instance)

        self._notify_about_instance_usage(context, instance, "shutdown.end")

    def _cleanup_volumes(self, context, instance_uuid, bdms):
        for bdm in bdms:
            LOG.debug(_("terminating bdm %s") % bdm,
                      instance_uuid=instance_uuid)
            if bdm['volume_id'] and bdm['delete_on_termination']:
                self.volume_api.delete(context, bdm['volume_id'])
            # NOTE(vish): bdms will be deleted on instance destroy

    @hooks.add_hook("delete_instance")
    def _delete_instance(self, context, instance, bdms,
                         reservations=None):
        """Delete an instance on this host.  Commit or rollback quotas
        as necessary.
        """
        instance_uuid = instance['uuid']
        image = instance['image_ref']

        if context.is_admin and context.project_id != instance['project_id']:
            project_id = instance['project_id']
        else:
            project_id = context.project_id
        if context.user_id != instance['user_id']:
            user_id = instance['user_id']
        else:
            user_id = context.user_id

        was_soft_deleted = instance['vm_state'] == vm_states.SOFT_DELETED
        if was_soft_deleted:
            # Instances in SOFT_DELETED vm_state have already had quotas
            # decremented.
            try:
                self._quota_rollback(context, reservations,
                                     project_id=project_id,
                                     user_id=user_id)
            except Exception:
                pass
            reservations = None

        try:
            db_inst = obj_base.obj_to_primitive(instance)
            self.conductor_api.instance_info_cache_delete(context, db_inst)
            self._notify_about_instance_usage(context, instance,
                                              "delete.start")
            self._shutdown_instance(context, db_inst, bdms)
            # NOTE(vish): We have already deleted the instance, so we have
            #             to ignore problems cleaning up the volumes. It
            #             would be nice to let the user know somehow that
            #             the volume deletion failed, but it is not
            #             acceptable to have an instance that can not be
            #             deleted. Perhaps this could be reworked in the
            #             future to set an instance fault the first time
            #             and to only ignore the failure if the instance
            #             is already in ERROR.
            try:
                self._cleanup_volumes(context, instance_uuid, bdms)
            except Exception as exc:
                err_str = _("Ignoring volume cleanup failure due to %s")
                LOG.warn(err_str % exc, instance=instance)
            # if a delete task succeed, always update vm state and task
            # state without expecting task state to be DELETING
            instance.vm_state = vm_states.DELETED
            instance.task_state = None
            instance.terminated_at = timeutils.utcnow()
            system_meta = utils.instance_sys_meta(instance)
            self.conductor_api.instance_destroy(
                context, obj_base.obj_to_primitive(instance))
        except Exception:
            with excutils.save_and_reraise_exception():
                self._quota_rollback(context, reservations,
                                     project_id=project_id,
                                     user_id=user_id)

        self._complete_deletion(context,
                                instance,
                                bdms,
                                reservations,
                                project_id,
                                system_meta,
                                user_id=user_id)

    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_event
    @wrap_instance_fault
    def terminate_instance(self, context, instance, bdms=None,
                           reservations=None):
        """Terminate an instance on this host."""
        # Note(eglynn): we do not decorate this action with reverts_task_state
        # because a failure during termination should leave the task state as
        # DELETING, as a signal to the API layer that a subsequent deletion
        # attempt should not result in a further decrement of the quota_usages
        # in_use count (see bug 1046236).

        # NOTE(danms): remove this compatibility in the future
        if not bdms:
            bdms = self._get_instance_volume_bdms(context, instance)

        @utils.synchronized(instance['uuid'])
        def do_terminate_instance(instance, bdms):
            try:
                self._delete_instance(context, instance, bdms,
                                      reservations=reservations)
            except exception.InstanceTerminationFailure as error:
                LOG.error(_('%s. Setting instance vm_state to ERROR'),
                          error, instance=instance)
                self._set_instance_error_state(context, instance['uuid'])
            except exception.InstanceNotFound as e:
                LOG.warn(e, instance=instance)

        do_terminate_instance(instance, bdms)

    # NOTE(johannes): This is probably better named power_off_instance
    # so it matches the driver method, but because of other issues, we
    # can't use that name in grizzly.
    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def stop_instance(self, context, instance):
        """Stopping an instance on this host."""
        self._notify_about_instance_usage(context, instance, "power_off.start")
        self.driver.power_off(instance)
        current_power_state = self._get_power_state(context, instance)
        instance.power_state = current_power_state
        instance.vm_state = vm_states.STOPPED
        instance.task_state = None
        instance.save(expected_task_state=(task_states.POWERING_OFF,
                                           task_states.STOPPING))
        self._notify_about_instance_usage(context, instance, "power_off.end")

    def _power_on(self, context, instance):
        network_info = self._get_instance_nw_info(context, instance)
        block_device_info = self._get_instance_volume_block_device_info(
                                context, instance)
        self.driver.power_on(context, instance,
                             self._legacy_nw_info(network_info),
                             block_device_info)

    # NOTE(johannes): This is probably better named power_on_instance
    # so it matches the driver method, but because of other issues, we
    # can't use that name in grizzly.
    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def start_instance(self, context, instance):
        """Starting an instance on this host."""
        self._notify_about_instance_usage(context, instance, "power_on.start")
        self._power_on(context, instance)
        current_power_state = self._get_power_state(context, instance)
        instance.power_state = current_power_state
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.save(expected_task_state=(task_states.POWERING_ON,
                                           task_states.STARTING))
        self._notify_about_instance_usage(context, instance, "power_on.end")

    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def soft_delete_instance(self, context, instance, reservations=None):
        """Soft delete an instance on this host."""

        if context.is_admin and context.project_id != instance['project_id']:
            project_id = instance['project_id']
        else:
            project_id = context.project_id
        if context.user_id != instance['user_id']:
            user_id = instance['user_id']
        else:
            user_id = context.user_id

        try:
            self._notify_about_instance_usage(context, instance,
                                              "soft_delete.start")
            db_inst = obj_base.obj_to_primitive(instance)
            try:
                self.driver.soft_delete(db_inst)
            except NotImplementedError:
                # Fallback to just powering off the instance if the
                # hypervisor doesn't implement the soft_delete method
                self.driver.power_off(instance)
            current_power_state = self._get_power_state(context, db_inst)
            instance.power_state = current_power_state
            instance.vm_state = vm_states.SOFT_DELETED
            instance.task_state = None
            instance.save(expected_task_state=[task_states.SOFT_DELETING])
        except Exception:
            with excutils.save_and_reraise_exception():
                self._quota_rollback(context, reservations,
                                     project_id=project_id,
                                     user_id=user_id)
        self._quota_commit(context, reservations, project_id=project_id,
                           user_id=user_id)
        self._notify_about_instance_usage(context, instance, "soft_delete.end")

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def restore_instance(self, context, instance):
        """Restore a soft-deleted instance on this host."""
        self._notify_about_instance_usage(context, instance, "restore.start")
        try:
            self.driver.restore(instance)
        except NotImplementedError:
            # Fallback to just powering on the instance if the hypervisor
            # doesn't implement the restore method
            self._power_on(context, instance)
        current_power_state = self._get_power_state(context, instance)
        instance = self._instance_update(context, instance['uuid'],
                power_state=current_power_state,
                vm_state=vm_states.ACTIVE,
                expected_task_state=task_states.RESTORING,
                task_state=None)
        self._notify_about_instance_usage(context, instance, "restore.end")

    # NOTE(johannes): In the folsom release, power_off_instance was poorly
    # named. It was the main entry point to soft delete an instance. That
    # has been changed to soft_delete_instance now, but power_off_instance
    # will need to stick around for compatibility in grizzly.
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def power_off_instance(self, context, instance):
        """Power off an instance on this host."""
        self.soft_delete_instance(context, instance)

    # NOTE(johannes): In the folsom release, power_on_instance was poorly
    # named. It was the main entry point to restore a soft deleted instance.
    # That has been changed to restore_instance now, but power_on_instance
    # will need to stick around for compatibility in grizzly.
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def power_on_instance(self, context, instance):
        """Power on an instance on this host."""
        self.restore_instance(context, instance)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata=None,
                         bdms=None, recreate=False, on_shared_storage=False):
        """Destroy and re-make this instance.

        A 'rebuild' effectively purges all existing data from the system and
        remakes the VM with given 'metadata' and 'personalities'.

        :param context: `nova.RequestContext` object
        :param instance: Instance dict
        :param orig_image_ref: Original image_ref before rebuild
        :param image_ref: New image_ref for rebuild
        :param injected_files: Files to inject
        :param new_pass: password to set on rebuilt instance
        :param orig_sys_metadata: instance system metadata from pre-rebuild
        :param bdms: block-device-mappings to use for rebuild
        :param recreate: True if instance should be recreated with same disk
        :param on_shared_storage: True if instance files on shared storage
        """
        context = context.elevated()

        orig_vm_state = instance['vm_state']
        with self._error_out_instance_on_exception(context, instance['uuid']):
            LOG.audit(_("Rebuilding instance"), context=context,
                      instance=instance)

            if recreate:
                if not self.driver.capabilities["supports_recreate"]:
                    raise exception.InstanceRecreateNotSupported

                self._check_instance_exists(context, instance)

                # To cover case when admin expects that instance files are on
                # shared storage, but not accessible and vice versa
                if on_shared_storage != self.driver.instance_on_disk(instance):
                    raise exception.InvalidSharedStorage(
                            _("Invalid state of instance files on shared"
                              " storage"))

                if on_shared_storage:
                    LOG.info(_('disk on shared storage, recreating using'
                               ' existing disk'))
                else:
                    image_ref = orig_image_ref = instance['image_ref']
                    LOG.info(_("disk not on shared storagerebuilding from:"
                               " '%s'") % str(image_ref))

                # NOTE(mriedem): On a recreate (evacuate), we need to update
                # the instance's host and node properties to reflect it's
                # destination node for the recreate.
                node_name = None
                try:
                    compute_node = self._get_compute_info(context, self.host)
                    node_name = compute_node['hypervisor_hostname']
                except exception.NotFound:
                    LOG.exception(_('Failed to get compute_info for %s') %
                                  self.host)
                finally:
                    instance = self._instance_update(
                            context, instance['uuid'], host=self.host,
                            node=node_name)

            if image_ref:
                image_meta = _get_image_meta(context, image_ref)
            else:
                image_meta = {}

            # This instance.exists message should contain the original
            # image_ref, not the new one.  Since the DB has been updated
            # to point to the new one... we have to override it.
            orig_image_ref_url = glance.generate_image_url(orig_image_ref)
            extra_usage_info = {'image_ref_url': orig_image_ref_url}
            self.conductor_api.notify_usage_exists(context, instance,
                    current_period=True, system_metadata=orig_sys_metadata,
                    extra_usage_info=extra_usage_info)

            # This message should contain the new image_ref
            extra_usage_info = {'image_name': image_meta.get('name', '')}
            self._notify_about_instance_usage(context, instance,
                    "rebuild.start", extra_usage_info=extra_usage_info)

            instance = self._instance_update(
                    context, instance['uuid'],
                    power_state=self._get_power_state(context, instance),
                    task_state=task_states.REBUILDING,
                    expected_task_state=task_states.REBUILDING)

            if recreate:
                self.network_api.setup_networks_on_host(
                        context, instance, self.host)

            network_info = self._get_instance_nw_info(context, instance)

            if bdms is None:
                bdms = self.conductor_api.\
                        block_device_mapping_get_all_by_instance(
                                context, instance)

            # NOTE(sirp): this detach is necessary b/c we will reattach the
            # volumes in _prep_block_devices below.
            for bdm in self._get_volume_bdms(bdms):
                self.volume_api.detach(context, bdm['volume_id'])

            if not recreate:
                block_device_info = self._get_volume_block_device_info(
                        self._get_volume_bdms(bdms))
                self.driver.destroy(instance,
                                    self._legacy_nw_info(network_info),
                                    block_device_info=block_device_info)

            instance = self._instance_update(
                    context, instance['uuid'],
                    task_state=task_states.REBUILD_BLOCK_DEVICE_MAPPING,
                    expected_task_state=task_states.REBUILDING)

            block_device_info = self._prep_block_device(
                    context, instance, bdms)

            instance['injected_files'] = injected_files

            instance = self._instance_update(
                    context, instance['uuid'],
                    task_state=task_states.REBUILD_SPAWNING,
                    expected_task_state=
                        task_states.REBUILD_BLOCK_DEVICE_MAPPING)

            self.driver.spawn(context, instance, image_meta,
                              [], new_pass,
                              network_info=self._legacy_nw_info(network_info),
                              block_device_info=block_device_info)

            instance = self._instance_update(
                    context, instance['uuid'],
                    power_state=self._get_power_state(context, instance),
                    vm_state=vm_states.ACTIVE,
                    task_state=None,
                    expected_task_state=task_states.REBUILD_SPAWNING,
                    launched_at=timeutils.utcnow())

            LOG.info(_("bringing vm to original state: '%s'") % orig_vm_state)
            if orig_vm_state == vm_states.STOPPED:
                instance = self._instance_update(context, instance['uuid'],
                                 vm_state=vm_states.ACTIVE,
                                 task_state=task_states.STOPPING,
                                 terminated_at=timeutils.utcnow(),
                                 progress=0)
                self.stop_instance(context, instance=instance)

            self._notify_about_instance_usage(
                    context, instance, "rebuild.end",
                    network_info=network_info,
                    extra_usage_info=extra_usage_info)

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
                LOG.info(_("Detaching from volume api: %s") % volume_id)
                volume = self.volume_api.get(context, volume_id)
                self.volume_api.check_detach(context, volume)
                self.volume_api.begin_detaching(context, volume_id)

                # Manager-detach
                self.detach_volume(context, volume_id, instance)

    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def reboot_instance(self, context, instance,
                        block_device_info=None,
                        network_info=None,
                        reboot_type="SOFT"):
        """Reboot an instance on this host."""
        context = context.elevated()
        LOG.audit(_("Rebooting instance"), context=context, instance=instance)

        # NOTE(danms): remove these when RPC API < 2.5 compatibility
        # is no longer needed
        if block_device_info is None:
            block_device_info = self._get_instance_volume_block_device_info(
                                context, instance)
        network_info = self._get_instance_nw_info(context, instance)

        self._notify_about_instance_usage(context, instance, "reboot.start")

        current_power_state = self._get_power_state(context, instance)

        instance.power_state = current_power_state
        instance.save()

        if instance['power_state'] != power_state.RUNNING:
            state = instance['power_state']
            running = power_state.RUNNING
            LOG.warn(_('trying to reboot a non-running instance:'
                       ' (state: %(state)s expected: %(running)s)'),
                     {'state': state, 'running': running},
                     context=context, instance=instance)

        def bad_volumes_callback(bad_devices):
            self._handle_bad_volumes_detached(
                    context, instance, bad_devices, block_device_info)

        try:
            # Don't change it out of rescue mode
            if instance['vm_state'] == vm_states.RESCUED:
                new_vm_state = vm_states.RESCUED
            else:
                new_vm_state = vm_states.ACTIVE
            new_power_state = None

            self.driver.reboot(context, instance,
                               self._legacy_nw_info(network_info),
                               reboot_type,
                               block_device_info=block_device_info,
                               bad_volumes_callback=bad_volumes_callback)

        except Exception as error:
            # Can't use save_and_reraise as we don't know yet if we
            # will re-raise or not
            type_, value, tb = sys.exc_info()

            compute_utils.add_instance_fault_from_exc(context,
                            self.conductor_api, instance, error,
                            sys.exc_info())

            # if the reboot failed but the VM is running don't
            # put it into an error state
            new_power_state = self._get_power_state(context, instance)
            if new_power_state == power_state.RUNNING:
                LOG.warning(_('Reboot failed but instance is running'),
                            context=context, instance=instance)
            else:
                LOG.error(_('Cannot reboot instance: %s'), error,
                          context=context, instance=instance)
                self._set_instance_obj_error_state(context, instance)
                raise type_, value, tb

        if not new_power_state:
            new_power_state = self._get_power_state(context, instance)
        try:
            instance.power_state = new_power_state
            instance.vm_state = new_vm_state
            instance.task_state = None
            instance.save()
        except exception.InstanceNotFound:
            LOG.warn(_("Instance disappeared during reboot"),
                     context=context, instance=instance)

        self._notify_about_instance_usage(context, instance, "reboot.end")

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def live_snapshot_instance(self, context, image_id, instance):
        """Live snapshot an instance on this host.

        :param context: security context
        :param image_id: glance.db.sqlalchemy.models.Image.Id
        :param instance: an Instance dict
        """
        context = context.elevated()

        current_power_state = self._get_power_state(context, instance)
        instance = self._instance_update(context, instance['uuid'],
                power_state=current_power_state)

        LOG.audit(_('instance live snapshotting'), context=context,
                  instance=instance)

        if instance['power_state'] != power_state.RUNNING:
            state = instance['power_state']
            running = power_state.RUNNING
            LOG.warn(_('trying to snapshot a non-running '
                       'instance: (state: %(state)s '
                       'expected: %(running)s)') %
                     {'state': state, 'running': running},
                     instance=instance)

        self._notify_about_instance_usage(
                context, instance, "live_snapshot.start")

        expected_task_state = task_states.IMAGE_LIVE_SNAPSHOT

        def update_task_state(task_state, expected_state=expected_task_state):
            return self._instance_update(context, instance['uuid'],
                    task_state=task_state,
                    expected_task_state=expected_state)

        self.driver.live_snapshot(context, instance, image_id,
                                  update_task_state)
        # The instance could have changed from the driver.  But since
        # we're doing a fresh update here, we'll grab the changes.

        instance = self._instance_update(context, instance['uuid'],
                task_state=None,
                expected_task_state=task_states.IMAGE_UPLOADING)

        self._notify_about_instance_usage(
                context, instance, "live_snapshot.end")

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def snapshot_instance(self, context, image_id, instance,
                          image_type='snapshot', backup_type=None,
                          rotation=None):
        """Snapshot an instance on this host.

        :param context: security context
        :param instance: an Instance dict
        :param image_id: glance.db.sqlalchemy.models.Image.Id
        :param image_type: snapshot | backup
        :param backup_type: daily | weekly
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        """
        context = context.elevated()

        current_power_state = self._get_power_state(context, instance)
        try:
            instance = self._instance_update(context, instance['uuid'],
                                             power_state=current_power_state)
            LOG.audit(_('instance snapshotting'), context=context,
                  instance=instance)

            if instance['power_state'] != power_state.RUNNING:
                state = instance['power_state']
                running = power_state.RUNNING
                LOG.warn(_('trying to snapshot a non-running instance: '
                       '(state: %(state)s expected: %(running)s)'),
                     {'state': state, 'running': running},
                     instance=instance)

            self._notify_about_instance_usage(
                context, instance, "snapshot.start")

            if image_type == 'snapshot':
                expected_task_state = task_states.IMAGE_SNAPSHOT

            elif image_type == 'backup':
                expected_task_state = task_states.IMAGE_BACKUP

            def update_task_state(task_state,
                                  expected_state=expected_task_state):
                return self._instance_update(context, instance['uuid'],
                                         task_state=task_state,
                                         expected_task_state=expected_state
                )

            self.driver.snapshot(context, instance, image_id,
                                 update_task_state)
            # The instance could have changed from the driver.  But since
            # we're doing a fresh update here, we'll grab the changes.

            instance = self._instance_update(context, instance['uuid'],
                                             task_state=None,
                                             expected_task_state=
                                             task_states.IMAGE_UPLOADING)

            if image_type == 'snapshot' and rotation:
                raise exception.ImageRotationNotAllowed()

            elif image_type == 'backup' and rotation >= 0:
                self._rotate_backups(context, instance, backup_type, rotation)

            elif image_type == 'backup':
                raise exception.RotationRequiredForBackup()

            self._notify_about_instance_usage(context, instance,
                                               "snapshot.end")

        except exception.InstanceNotFound:
            # the instance got deleted during the snapshot
            # Quickly bail out of here
            msg = _("Instance disappeared during snapshot")
            LOG.debug(msg, instance=instance)
        except exception.UnexpectedTaskStateError as e:
            actual_task_state = e.kwargs.get('actual', None)
            if actual_task_state == 'deleting':
                msg = _('Instance was deleted during snapshot.')
                LOG.debug(msg, instance=instance)
            else:
                raise

    @wrap_instance_fault
    def _rotate_backups(self, context, instance, backup_type, rotation):
        """Delete excess backups associated to an instance.

        Instances are allowed a fixed number of backups (the rotation number);
        this method deletes the oldest backups that exceed the rotation
        threshold.

        :param context: security context
        :param instance: Instance dict
        :param backup_type: daily | weekly
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        """
        image_service = glance.get_default_image_service()
        filters = {'property-image_type': 'backup',
                   'property-backup_type': backup_type,
                   'property-instance_uuid': instance['uuid']}

        images = image_service.detail(context, filters=filters,
                                      sort_key='created_at', sort_dir='desc')
        num_images = len(images)
        LOG.debug(_("Found %(num_images)d images (rotation: %(rotation)d)"),
                  {'num_images': num_images, 'rotation': rotation},
                  instance=instance)

        if num_images > rotation:
            # NOTE(sirp): this deletes all backups that exceed the rotation
            # limit
            excess = len(images) - rotation
            LOG.debug(_("Rotating out %d backups"), excess,
                      instance=instance)
            for i in xrange(excess):
                image = images.pop()
                image_id = image['id']
                LOG.debug(_("Deleting image %s"), image_id,
                          instance=instance)
                image_service.delete(context, image_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def set_admin_password(self, context, instance, new_pass=None):
        """Set the root/admin password for an instance on this host.

        This is generally only called by API password resets after an
        image has been built.
        """

        context = context.elevated()
        if new_pass is None:
            # Generate a random password
            new_pass = utils.generate_password()

        current_power_state = self._get_power_state(context, instance)
        expected_state = power_state.RUNNING

        if current_power_state != expected_state:
            self._instance_update(context, instance['uuid'],
                                  task_state=None,
                                  expected_task_state=task_states.
                                  UPDATING_PASSWORD)
            _msg = _('Failed to set admin password. Instance %s is not'
                     ' running') % instance["uuid"]
            raise exception.InstancePasswordSetFailed(
                instance=instance['uuid'], reason=_msg)
        else:
            try:
                self.driver.set_admin_password(instance, new_pass)
                LOG.audit(_("Root password set"), instance=instance)
                self._instance_update(context,
                                      instance['uuid'],
                                      task_state=None,
                                      expected_task_state=task_states.
                                      UPDATING_PASSWORD)
            except NotImplementedError:
                _msg = _('set_admin_password is not implemented '
                         'by this driver or guest instance.')
                LOG.warn(_msg, instance=instance)
                self._instance_update(context,
                                      instance['uuid'],
                                      task_state=None,
                                      expected_task_state=task_states.
                                      UPDATING_PASSWORD)
                raise NotImplementedError(_msg)
            except exception.UnexpectedTaskStateError:
                # interrupted by another (most likely delete) task
                # do not retry
                raise
            except Exception as e:
                # Catch all here because this could be anything.
                LOG.exception(_('set_admin_password failed: %s') % e,
                              instance=instance)
                self._set_instance_error_state(context,
                                               instance['uuid'])
                # We create a new exception here so that we won't
                # potentially reveal password information to the
                # API caller.  The real exception is logged above
                _msg = _('error setting admin password')
                raise exception.InstancePasswordSetFailed(
                    instance=instance['uuid'], reason=_msg)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def inject_file(self, context, path, file_contents, instance):
        """Write a file to the specified path in an instance on this host."""
        context = context.elevated()
        current_power_state = self._get_power_state(context, instance)
        expected_state = power_state.RUNNING
        if current_power_state != expected_state:
            LOG.warn(_('trying to inject a file into a non-running (state: '
                       '%(current_state)s expected: %(expected_state)s)'),
                     {'current_state': current_power_state,
                      'expected_state': expected_state},
                     instance=instance)
        LOG.audit(_('injecting file to %s'), path,
                    instance=instance)
        self.driver.inject_file(instance, path, file_contents)

    def _get_rescue_image_ref(self, context, instance):
        """Determine what image should be used to boot the rescue VM."""
        system_meta = utils.instance_sys_meta(instance)

        rescue_image_ref = system_meta.get('image_base_image_ref')

        # 1. First try to use base image associated with instance's current
        #    image.
        #
        # The idea here is to provide the customer with a rescue environment
        # which they are familiar with. So, if they built their instance off of
        # a Debian image, their rescue VM wil also be Debian.
        if rescue_image_ref:
            return rescue_image_ref

        # 2. As a last resort, use instance's current image
        LOG.warn(_('Unable to find a different image to use for rescue VM,'
                   ' using instance\'s current image'))
        return instance['image_ref']

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    def rescue_instance(self, context, instance, rescue_password=None):
        """
        Rescue an instance on this host.
        :param rescue_password: password to set on rescue instance
        """
        context = context.elevated()
        LOG.audit(_('Rescuing'), context=context, instance=instance)

        admin_password = (rescue_password if rescue_password else
                      utils.generate_password())

        network_info = self._get_instance_nw_info(context, instance)

        rescue_image_ref = self._get_rescue_image_ref(context, instance)

        if rescue_image_ref:
            rescue_image_meta = _get_image_meta(context, rescue_image_ref)
        else:
            rescue_image_meta = {}

        try:
            self.driver.rescue(context, instance,
                               self._legacy_nw_info(network_info),
                               rescue_image_meta, admin_password)
        except Exception as e:
            LOG.exception(_("Error trying to Rescue Instance"),
                          instance=instance)
            raise exception.InstanceNotRescuable(
                instance_id=instance['uuid'],
                reason=_("Driver Error: %s") % unicode(e))

        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance['uuid'],
                              vm_state=vm_states.RESCUED,
                              task_state=None,
                              power_state=current_power_state,
                              launched_at=timeutils.utcnow(),
                              expected_task_state=task_states.RESCUING)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def unrescue_instance(self, context, instance):
        """Rescue an instance on this host."""
        context = context.elevated()
        LOG.audit(_('Unrescuing'), context=context, instance=instance)

        network_info = self._get_instance_nw_info(context, instance)

        with self._error_out_instance_on_exception(context, instance['uuid']):
            self.driver.unrescue(instance,
                                 self._legacy_nw_info(network_info))

        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance['uuid'],
                              vm_state=vm_states.ACTIVE,
                              task_state=None,
                              expected_task_state=task_states.UNRESCUING,
                              power_state=current_power_state)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def change_instance_metadata(self, context, diff, instance):
        """Update the metadata published to the instance."""
        LOG.debug(_("Changing instance metadata according to %r"),
                  diff, instance=instance)
        self.driver.change_instance_metadata(context, instance, diff)

    def _cleanup_stored_instance_types(self, migration, instance,
                                       restore_old=False):
        """Clean up "old" and "new" instance_type information stored in
        instance's system_metadata. Optionally update the "current"
        instance_type to the saved old one first.

        Returns the updated system_metadata as a dict, as well as the
        post-cleanup current instance type.
        """
        sys_meta = utils.instance_sys_meta(instance)
        if restore_old:
            instance_type = flavors.extract_flavor(instance, 'old_')
            sys_meta = flavors.save_flavor_info(sys_meta, instance_type)
        else:
            instance_type = flavors.extract_flavor(instance)

        flavors.delete_flavor_info(sys_meta, 'old_')
        flavors.delete_flavor_info(sys_meta, 'new_')

        return sys_meta, instance_type

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_event
    @wrap_instance_fault
    def confirm_resize(self, context, instance, reservations=None,
                       migration=None, migration_id=None):
        """Destroys the source instance."""
        if not migration:
            migration = self.conductor_api.migration_get(context, migration_id)

        self._notify_about_instance_usage(context, instance,
                                          "resize.confirm.start")

        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            # NOTE(danms): delete stashed migration information
            sys_meta, instance_type = self._cleanup_stored_instance_types(
                migration, instance)
            sys_meta.pop('old_vm_state', None)
            self._instance_update(context, instance['uuid'],
                                  system_metadata=sys_meta)

            # NOTE(tr3buchet): tear down networks on source host
            self.network_api.setup_networks_on_host(context, instance,
                               migration['source_compute'], teardown=True)

            network_info = self._get_instance_nw_info(context, instance)
            self.driver.confirm_migration(migration, instance,
                                          self._legacy_nw_info(network_info))

            self.conductor_api.migration_update(context, migration,
                                                'confirmed')

            rt = self._get_resource_tracker(migration['source_node'])
            rt.drop_resize_claim(instance, prefix='old_')

            # NOTE(mriedem): The old_vm_state could be STOPPED but the user
            # might have manually powered up the instance to confirm the
            # resize/migrate, so we need to check the current power state
            # on the instance and set the vm_state appropriately. We default
            # to ACTIVE because if the power state is not SHUTDOWN, we
            # assume _sync_instance_power_state will clean it up.
            p_state = instance['power_state']
            vm_state = None
            if p_state == power_state.SHUTDOWN:
                vm_state = vm_states.STOPPED
                LOG.debug("Resized/migrated instance is powered off. "
                          "Setting vm_state to '%s'." % vm_state,
                          instance=instance)
            else:
                vm_state = vm_states.ACTIVE

            instance = self._instance_update(context, instance['uuid'],
                                             vm_state=vm_state,
                                             task_state=None,
                                             expected_task_state=[None,
                                             task_states.DELETING])

            self._notify_about_instance_usage(
                context, instance, "resize.confirm.end",
                network_info=network_info)

            self._quota_commit(context, reservations)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def revert_resize(self, context, instance, migration=None,
                      migration_id=None, reservations=None):
        """Destroys the new instance on the destination machine.

        Reverts the model changes, and powers on the old instance on the
        source machine.

        """
        if not migration:
            migration = self.conductor_api.migration_get(context, migration_id)

        # NOTE(comstud): A revert_resize is essentially a resize back to
        # the old size, so we need to send a usage event here.
        self.conductor_api.notify_usage_exists(
                context, instance, current_period=True)

        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            # NOTE(tr3buchet): tear down networks on destination host
            self.network_api.setup_networks_on_host(context, instance,
                                                    teardown=True)

            self.conductor_api.network_migrate_instance_start(context,
                                                              instance,
                                                              migration)

            network_info = self._get_instance_nw_info(context, instance)
            block_device_info = self._get_instance_volume_block_device_info(
                                context, instance)

            self.driver.destroy(instance, self._legacy_nw_info(network_info),
                                block_device_info)

            self._terminate_volume_connections(context, instance)

            self.conductor_api.migration_update(context, migration, 'reverted')

            rt = self._get_resource_tracker(instance.get('node'))
            rt.drop_resize_claim(instance)

            self.compute_rpcapi.finish_revert_resize(context, instance,
                    migration, migration['source_compute'],
                    reservations)

    def _refresh_block_device_connection_info(self, context, instance):
        """After some operations, the IQN or CHAP, for example, may have
        changed. This call updates the DB with the latest connection info.
        """
        bdms = self._get_instance_volume_bdms(context, instance)

        if not bdms:
            return bdms

        connector = self.driver.get_volume_connector(instance)

        for bdm in bdms:
            cinfo = self.volume_api.initialize_connection(
                    context, bdm['volume_id'], connector)

            self.conductor_api.block_device_mapping_update(
                context, bdm['id'],
                {'connection_info': jsonutils.dumps(cinfo)})

        return bdms

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def finish_revert_resize(self, context, instance, reservations=None,
                             migration=None, migration_id=None):
        """Finishes the second half of reverting a resize.

        Bring the original source instance state back (active/shutoff) and
        revert the resized attributes in the database.

        """
        if not migration:
            migration = self.conductor_api.migration_get(context, migration_id)

        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            network_info = self._get_instance_nw_info(context, instance)

            self._notify_about_instance_usage(
                    context, instance, "resize.revert.start")

            sys_meta, instance_type = self._cleanup_stored_instance_types(
                migration, instance, True)

            # NOTE(mriedem): delete stashed old_vm_state information; we
            # default to ACTIVE for backwards compability if old_vm_state is
            # not set
            old_vm_state = sys_meta.pop('old_vm_state', vm_states.ACTIVE)

            instance = self._instance_update(context,
                                  instance['uuid'],
                                  memory_mb=instance_type['memory_mb'],
                                  vcpus=instance_type['vcpus'],
                                  root_gb=instance_type['root_gb'],
                                  ephemeral_gb=instance_type['ephemeral_gb'],
                                  instance_type_id=instance_type['id'],
                                  host=migration['source_compute'],
                                  node=migration['source_node'],
                                  system_metadata=sys_meta)
            self.network_api.setup_networks_on_host(context, instance,
                                            migration['source_compute'])

            bdms = self._refresh_block_device_connection_info(
                    context, instance)

            block_device_info = self._get_instance_volume_block_device_info(
                    context, instance, bdms=bdms)

            power_on = old_vm_state != vm_states.STOPPED
            self.driver.finish_revert_migration(instance,
                                       self._legacy_nw_info(network_info),
                                       block_device_info, power_on)

            # Just roll back the record. There's no need to resize down since
            # the 'old' VM already has the preferred attributes
            instance = self._instance_update(context,
                    instance['uuid'], launched_at=timeutils.utcnow(),
                    expected_task_state=task_states.RESIZE_REVERTING)

            self.conductor_api.network_migrate_instance_finish(context,
                                                               instance,
                                                               migration)

            # if the original vm state was STOPPED, set it back to STOPPED
            LOG.info(_("Updating instance to original state: '%s'") %
                     old_vm_state)
            if power_on:
                instance = self._instance_update(context, instance['uuid'],
                        vm_state=vm_states.ACTIVE, task_state=None)
            else:
                instance = self._instance_update(
                        context, instance['uuid'],
                        task_state=task_states.STOPPING)
                self.stop_instance(context, instance=instance)

            self._notify_about_instance_usage(
                    context, instance, "resize.revert.end")

            self._quota_commit(context, reservations)

    def _quota_commit(self, context, reservations, project_id=None,
                      user_id=None):
        if reservations:
            self.conductor_api.quota_commit(context, reservations,
                                            project_id=project_id,
                                            user_id=user_id)

    def _quota_rollback(self, context, reservations, project_id=None,
                        user_id=None):
        if reservations:
            self.conductor_api.quota_rollback(context, reservations,
                                              project_id=project_id,
                                              user_id=user_id)

    def _prep_resize(self, context, image, instance, instance_type,
            reservations, request_spec, filter_properties, node):

        if not filter_properties:
            filter_properties = {}

        if not instance['host']:
            self._set_instance_error_state(context, instance['uuid'])
            msg = _('Instance has no source host')
            raise exception.MigrationError(msg)

        same_host = instance['host'] == self.host
        if same_host and not CONF.allow_resize_to_same_host:
            self._set_instance_error_state(context, instance['uuid'])
            msg = _('destination same as source!')
            raise exception.MigrationError(msg)

        # NOTE(danms): Stash the new instance_type to avoid having to
        # look it up in the database later
        sys_meta = utils.instance_sys_meta(instance)
        flavors.save_flavor_info(sys_meta, instance_type, prefix='new_')
        # NOTE(mriedem): Stash the old vm_state so we can set the
        # resized/reverted instance back to the same state later.
        vm_state = instance['vm_state']
        LOG.debug('Stashing vm_state: %s' % vm_state, instance=instance)
        sys_meta['old_vm_state'] = vm_state
        instance = self._instance_update(context, instance['uuid'],
                                         system_metadata=sys_meta)

        limits = filter_properties.get('limits', {})
        rt = self._get_resource_tracker(node)
        with rt.resize_claim(context, instance, instance_type, limits=limits) \
                as claim:
            migration_ref = claim.migration

            LOG.audit(_('Migrating'), context=context,
                    instance=instance)
            self.compute_rpcapi.resize_instance(context, instance,
                    migration_ref, image, instance_type, reservations)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def prep_resize(self, context, image, instance, instance_type,
                    reservations=None, request_spec=None,
                    filter_properties=None, node=None):
        """Initiates the process of moving a running instance to another host.

        Possibly changes the RAM and disk size in the process.

        """
        if node is None:
            node = self.driver.get_available_nodes()[0]
            LOG.debug(_("No node specified, defaulting to %s"), node)

        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            self.conductor_api.notify_usage_exists(
                    context, instance, current_period=True)
            self._notify_about_instance_usage(
                    context, instance, "resize.prep.start")
            try:
                self._prep_resize(context, image, instance, instance_type,
                        reservations, request_spec, filter_properties, node)
            except Exception:
                # try to re-schedule the resize elsewhere:
                exc_info = sys.exc_info()
                self._reschedule_resize_or_reraise(context, image, instance,
                        exc_info, instance_type, reservations, request_spec,
                        filter_properties)
            finally:
                extra_usage_info = dict(
                        new_instance_type=instance_type['name'],
                        new_instance_type_id=instance_type['id'])

                self._notify_about_instance_usage(
                    context, instance, "resize.prep.end",
                    extra_usage_info=extra_usage_info)

    def _reschedule_resize_or_reraise(self, context, image, instance, exc_info,
            instance_type, reservations, request_spec, filter_properties):
        """Try to re-schedule the resize or re-raise the original error to
        error out the instance.
        """
        if not request_spec:
            request_spec = {}
        if not filter_properties:
            filter_properties = {}

        rescheduled = False
        instance_uuid = instance['uuid']

        compute_utils.add_instance_fault_from_exc(context, self.conductor_api,
                instance, exc_info[0], exc_info=exc_info)

        try:
            scheduler_method = self.scheduler_rpcapi.prep_resize
            method_args = (instance, instance_type, image, request_spec,
                           filter_properties, reservations)
            task_state = task_states.RESIZE_PREP

            rescheduled = self._reschedule(context, request_spec,
                    filter_properties, instance_uuid, scheduler_method,
                    method_args, task_state, exc_info)
        except Exception:
            rescheduled = False
            LOG.exception(_("Error trying to reschedule"),
                          instance_uuid=instance_uuid)

        if rescheduled:
            # log the original build error
            self._log_original_error(exc_info, instance_uuid)
        else:
            # not re-scheduling
            raise exc_info[0], exc_info[1], exc_info[2]

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def resize_instance(self, context, instance, image,
                        reservations=None, migration=None, migration_id=None,
                        instance_type=None):
        """Starts the migration of a running instance to another host."""
        if not migration:
            migration = self.conductor_api.migration_get(context, migration_id)
        with self._error_out_instance_on_exception(context, instance['uuid'],
                                                   reservations):
            if not instance_type:
                instance_type = self.conductor_api.instance_type_get(context,
                        migration['new_instance_type_id'])

            network_info = self._get_instance_nw_info(context, instance)

            migration = self.conductor_api.migration_update(context,
                    migration, 'migrating')

            instance = self._instance_update(context, instance['uuid'],
                    task_state=task_states.RESIZE_MIGRATING,
                    expected_task_state=task_states.RESIZE_PREP)

            self._notify_about_instance_usage(
                context, instance, "resize.start", network_info=network_info)

            block_device_info = self._get_instance_volume_block_device_info(
                                context, instance)

            disk_info = self.driver.migrate_disk_and_power_off(
                    context, instance, migration['dest_host'],
                    instance_type, self._legacy_nw_info(network_info),
                    block_device_info)

            self._terminate_volume_connections(context, instance)

            self.conductor_api.network_migrate_instance_start(context,
                                                              instance,
                                                              migration)

            migration = self.conductor_api.migration_update(context,
                    migration, 'post-migrating')

            instance = self._instance_update(context, instance['uuid'],
                    host=migration['dest_compute'],
                    node=migration['dest_node'],
                    task_state=task_states.RESIZE_MIGRATED,
                    expected_task_state=task_states.
                    RESIZE_MIGRATING)

            self.compute_rpcapi.finish_resize(context, instance,
                    migration, image, disk_info,
                    migration['dest_compute'], reservations)

            self._notify_about_instance_usage(context, instance, "resize.end",
                                              network_info=network_info)

    def _terminate_volume_connections(self, context, instance):
        bdms = self._get_instance_volume_bdms(context, instance)
        if bdms:
            connector = self.driver.get_volume_connector(instance)
            for bdm in bdms:
                self.volume_api.terminate_connection(context, bdm['volume_id'],
                                                     connector)

    def _finish_resize(self, context, instance, migration, disk_info,
                       image):
        resize_instance = False
        old_instance_type_id = migration['old_instance_type_id']
        new_instance_type_id = migration['new_instance_type_id']
        old_instance_type = flavors.extract_flavor(instance)
        sys_meta = utils.instance_sys_meta(instance)
        # NOTE(mriedem): Get the old_vm_state so we know if we should
        # power on the instance. If old_vm_sate is not set we need to default
        # to ACTIVE for backwards compatibility
        old_vm_state = sys_meta.get('old_vm_state', vm_states.ACTIVE)
        flavors.save_flavor_info(sys_meta,
                                 old_instance_type,
                                 prefix='old_')
        if old_instance_type_id != new_instance_type_id:
            instance_type = flavors.extract_flavor(instance,
                                                                 prefix='new_')
            flavors.save_flavor_info(sys_meta, instance_type)

            instance = self._instance_update(
                    context,
                    instance['uuid'],
                    instance_type_id=instance_type['id'],
                    memory_mb=instance_type['memory_mb'],
                    vcpus=instance_type['vcpus'],
                    root_gb=instance_type['root_gb'],
                    ephemeral_gb=instance_type['ephemeral_gb'],
                    system_metadata=dict(sys_meta))

            resize_instance = True

        # NOTE(tr3buchet): setup networks on destination host
        self.network_api.setup_networks_on_host(context, instance,
                                                migration['dest_compute'])

        self.conductor_api.network_migrate_instance_finish(context,
                                                           instance,
                                                           migration)

        network_info = self._get_instance_nw_info(context, instance)

        instance = self._instance_update(context, instance['uuid'],
                              task_state=task_states.RESIZE_FINISH,
                              expected_task_state=task_states.RESIZE_MIGRATED,
                              system_metadata=sys_meta)

        self._notify_about_instance_usage(
            context, instance, "finish_resize.start",
            network_info=network_info)

        bdms = self._refresh_block_device_connection_info(context, instance)

        block_device_info = self._get_instance_volume_block_device_info(
                            context, instance, bdms=bdms)

        # NOTE(mriedem): If the original vm_state was STOPPED, we don't
        # automatically power on the instance after it's migrated
        power_on = old_vm_state != vm_states.STOPPED
        self.driver.finish_migration(context, migration, instance,
                                     disk_info,
                                     self._legacy_nw_info(network_info),
                                     image, resize_instance,
                                     block_device_info, power_on)

        migration = self.conductor_api.migration_update(context,
                migration, 'finished')

        instance = self._instance_update(context,
                                         instance['uuid'],
                                         vm_state=vm_states.RESIZED,
                                         launched_at=timeutils.utcnow(),
                                         task_state=None,
                                         expected_task_state=task_states.
                                             RESIZE_FINISH)

        self._notify_about_instance_usage(
            context, instance, "finish_resize.end",
            network_info=network_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def finish_resize(self, context, disk_info, image, instance,
                      reservations=None, migration=None, migration_id=None):
        """Completes the migration process.

        Sets up the newly transferred disk and turns on the instance at its
        new host machine.

        """
        if not migration:
            migration = self.conductor_api.migration_get(context, migration_id)
        try:
            self._finish_resize(context, instance, migration,
                                disk_info, image)
            self._quota_commit(context, reservations)
        except Exception as error:
            with excutils.save_and_reraise_exception():
                try:
                    self._quota_rollback(context, reservations)
                except Exception as qr_error:
                    LOG.exception(_("Failed to rollback quota for failed "
                                    "finish_resize: %s"),
                                  qr_error, instance=instance)
                LOG.error(_('%s. Setting instance vm_state to ERROR') % error,
                          instance=instance)
                self._set_instance_error_state(context, instance['uuid'])

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def add_fixed_ip_to_instance(self, context, network_id, instance):
        """Calls network_api to add new fixed_ip to instance
        then injects the new network info and resets instance networking.

        """
        self._notify_about_instance_usage(
                context, instance, "create_ip.start")

        self.network_api.add_fixed_ip_to_instance(context, instance,
                network_id, conductor_api=self.conductor_api)

        network_info = self._inject_network_info(context, instance=instance)
        self.reset_network(context, instance)

        # NOTE(russellb) We just want to bump updated_at.  See bug 1143466.
        self._instance_update(context, instance['uuid'],
                updated_at=timeutils.utcnow())

        self._notify_about_instance_usage(
            context, instance, "create_ip.end", network_info=network_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def remove_fixed_ip_from_instance(self, context, address, instance):
        """Calls network_api to remove existing fixed_ip from instance
        by injecting the altered network info and resetting
        instance networking.
        """
        self._notify_about_instance_usage(
                context, instance, "delete_ip.start")

        self.network_api.remove_fixed_ip_from_instance(context, instance,
                address, conductor_api=self.conductor_api)

        network_info = self._inject_network_info(context,
                                                 instance=instance)
        self.reset_network(context, instance)

        # NOTE(russellb) We just want to bump updated_at.  See bug 1143466.
        self._instance_update(context, instance['uuid'],
                updated_at=timeutils.utcnow())

        self._notify_about_instance_usage(
            context, instance, "delete_ip.end", network_info=network_info)

    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def pause_instance(self, context, instance):
        """Pause an instance on this host."""
        context = context.elevated()
        LOG.audit(_('Pausing'), context=context, instance=instance)
        self.driver.pause(instance)
        current_power_state = self._get_power_state(context, instance)
        instance.power_state = current_power_state
        instance.vm_state = vm_states.PAUSED
        instance.task_state = None
        instance.save(expected_task_state=task_states.PAUSING)

    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def unpause_instance(self, context, instance):
        """Unpause a paused instance on this host."""
        context = context.elevated()
        LOG.audit(_('Unpausing'), context=context, instance=instance)
        self.driver.unpause(instance)
        current_power_state = self._get_power_state(context, instance)
        instance.power_state = current_power_state
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.save(expected_task_state=task_states.UNPAUSING)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def host_power_action(self, context, host=None, action=None):
        """Reboots, shuts down or powers up the host."""
        return self.driver.host_power_action(host, action)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def host_maintenance_mode(self, context, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        return self.driver.host_maintenance_mode(host, mode)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def set_host_enabled(self, context, host=None, enabled=None):
        """Sets the specified host's ability to accept new instances."""
        return self.driver.set_host_enabled(host, enabled)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def get_host_uptime(self, context):
        """Returns the result of calling "uptime" on the target host."""
        return self.driver.get_host_uptime(self.host)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_diagnostics(self, context, instance):
        """Retrieve diagnostics for an instance on this host."""
        current_power_state = self._get_power_state(context, instance)
        if current_power_state == power_state.RUNNING:
            LOG.audit(_("Retrieving diagnostics"), context=context,
                      instance=instance)
            return self.driver.get_diagnostics(instance)

    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def suspend_instance(self, context, instance):
        """Suspend the given instance."""
        context = context.elevated()

        with self._error_out_instance_on_exception(context, instance['uuid']):
            self.driver.suspend(instance)
        current_power_state = self._get_power_state(context, instance)
        instance.power_state = current_power_state
        instance.vm_state = vm_states.SUSPENDED
        instance.task_state = None
        instance.save(expected_task_state=task_states.SUSPENDING)
        self._notify_about_instance_usage(context, instance, 'suspend')

    @object_compat
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def resume_instance(self, context, instance):
        """Resume the given suspended instance."""
        context = context.elevated()
        LOG.audit(_('Resuming'), context=context, instance=instance)

        network_info = self._get_instance_nw_info(context, instance)
        block_device_info = self._get_instance_volume_block_device_info(
                            context, instance)

        self.driver.resume(instance, self._legacy_nw_info(network_info),
                           block_device_info)

        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.save(expected_task_state=task_states.RESUMING)
        self._notify_about_instance_usage(context, instance, 'resume')

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def shelve_instance(self, context, instance, image_id):
        """Shelve an instance.

        This should be used when you want to take a snapshot of the instance.
        It also adds system_metadata that can be used by a periodic task to
        offload the shelved instance after a period of time.

        :param context: request context
        :param instance: an Instance object
        :param image_id: an image id to snapshot to.
        """
        self.conductor_api.notify_usage_exists(
            context, obj_base.obj_to_primitive(instance),
            current_period=True)
        self._notify_about_instance_usage(context, instance, 'shelve.start')

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

        self.driver.power_off(instance)
        current_power_state = self._get_power_state(context, instance)
        self.driver.snapshot(context, instance, image_id, update_task_state)

        instance.system_metadata['shelved_at'] = timeutils.strtime()
        instance.system_metadata['shelved_image_id'] = image_id
        instance.system_metadata['shelved_host'] = self.host
        instance.vm_state = vm_states.SHELVED
        instance.task_state = None
        if CONF.shelved_offload_time == 0:
            instance.task_state = task_states.SHELVING_OFFLOADING
        instance.power_state = current_power_state
        instance.save(expected_task_state=[
                task_states.SHELVING,
                task_states.SHELVING_IMAGE_UPLOADING])

        if CONF.shelved_offload_time == 0:
            self.shelve_offload_instance(context, instance)

        self._notify_about_instance_usage(context, instance, 'shelve.end')

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def shelve_offload_instance(self, context, instance):
        """Remove a shelved instance from the hypervisor.

        This frees up those resources for use by other instances, but may lead
        to slower unshelve times for this instance.  This method is used by
        volume backed instances since restoring them doesn't involve the
        potentially large download of an image.

        :param context: request context
        :param instance: an Instance dict
        """
        self._notify_about_instance_usage(context, instance,
                'shelve_offload.start')

        self.driver.power_off(instance)
        current_power_state = self._get_power_state(context, instance)

        network_info = self._get_instance_nw_info(context, instance)
        block_device_info = self._get_instance_volume_block_device_info(
                context, instance)
        self.driver.destroy(instance, self._legacy_nw_info(network_info),
                block_device_info)

        instance.power_state = current_power_state
        instance.host = None
        instance.node = None
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = None
        instance.save(expected_task_state=[task_states.SHELVING,
                                           task_states.SHELVING_OFFLOADING])
        self._notify_about_instance_usage(context, instance,
                'shelve_offload.end')

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_event
    @wrap_instance_fault
    def unshelve_instance(self, context, instance, image=None):
        """Unshelve the instance.

        :param context: request context
        :param instance: an Instance dict
        :param image: an image to build from.  If None we assume a
            volume backed instance.
        """
        @utils.synchronized(instance['uuid'])
        def do_unshelve_instance():
            self._unshelve_instance(context, instance, image)
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

    def _unshelve_instance(self, context, instance, image):
        self._notify_about_instance_usage(context, instance, 'unshelve.start')
        instance.task_state = task_states.SPAWNING
        instance.save()

        network_info = self._get_instance_nw_info(context, instance)
        bdms = self.conductor_api.block_device_mapping_get_all_by_instance(
                context, instance)
        block_device_info = self._prep_block_device(context, instance, bdms)
        scrubbed_keys = self._unshelve_instance_key_scrub(instance)
        try:
            self.driver.spawn(context, instance, image, injected_files=[],
                    admin_password=None,
                    network_info=self._legacy_nw_info(network_info),
                    block_device_info=block_device_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Instance failed to spawn'), instance=instance)

        if image:
            image_service = glance.get_default_image_service()
            image_service.delete(context, image['id'])

        self._unshelve_instance_key_restore(instance, scrubbed_keys)
        instance.power_state = self._get_power_state(context, instance)
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.launched_at = timeutils.utcnow()
        instance.save(expected_task_state=task_states.SPAWNING)
        self._notify_about_instance_usage(context, instance, 'unshelve.end')

    @reverts_task_state
    @wrap_instance_fault
    def reset_network(self, context, instance):
        """Reset networking on the given instance."""
        LOG.debug(_('Reset network'), context=context, instance=instance)
        self.driver.reset_network(instance)

    def _inject_network_info(self, context, instance):
        """Inject network info for the given instance."""
        LOG.debug(_('Inject network info'), context=context, instance=instance)

        network_info = self._get_instance_nw_info(context, instance)
        LOG.debug(_('network_info to inject: |%s|'), network_info,
                  instance=instance)

        self.driver.inject_network_info(instance,
                                        self._legacy_nw_info(network_info))
        return network_info

    @wrap_instance_fault
    def inject_network_info(self, context, instance):
        """Inject network info, but don't return the info."""
        self._inject_network_info(context, instance)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_console_output(self, context, instance, tail_length=None):
        """Send the console output for the given instance."""
        context = context.elevated()
        LOG.audit(_("Get console output"), context=context,
                  instance=instance)
        output = self.driver.get_console_output(instance)

        if tail_length is not None:
            output = self._tail_log(output, tail_length)

        return output.decode('utf-8', 'replace').encode('ascii', 'replace')

    def _tail_log(self, log, length):
        try:
            length = int(length)
        except ValueError:
            length = 0

        if length == 0:
            return ''
        else:
            return '\n'.join(log.split('\n')[-int(length):])

    @rpc_common.client_exceptions(exception.ConsoleTypeInvalid,
            exception.InstanceNotReady, exception.InstanceNotFound)
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_vnc_console(self, context, console_type, instance):
        """Return connection information for a vnc console."""
        context = context.elevated()
        LOG.debug(_("Getting vnc console"), instance=instance)
        token = str(uuid.uuid4())

        if not CONF.vnc_enabled:
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        if console_type == 'novnc':
            # For essex, novncproxy_base_url must include the full path
            # including the html file (like http://myhost/vnc_auto.html)
            access_url = '%s?token=%s' % (CONF.novncproxy_base_url, token)
        elif console_type == 'xvpvnc':
            access_url = '%s?token=%s' % (CONF.xvpvncproxy_base_url, token)
        else:
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        try:
            # Retrieve connect info from driver, and then decorate with our
            # access info token
            connect_info = self.driver.get_vnc_console(instance)
            connect_info['token'] = token
            connect_info['access_url'] = access_url
        except exception.InstanceNotFound:
            if instance['vm_state'] != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance['uuid'])

        return connect_info

    @rpc_common.client_exceptions(exception.ConsoleTypeInvalid,
            exception.InstanceNotReady, exception.InstanceNotFound)
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_spice_console(self, context, console_type, instance):
        """Return connection information for a spice console."""
        context = context.elevated()
        LOG.debug(_("Getting spice console"), instance=instance)
        token = str(uuid.uuid4())

        if not CONF.spice.enabled:
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        if console_type == 'spice-html5':
            # For essex, spicehtml5proxy_base_url must include the full path
            # including the html file (like http://myhost/spice_auto.html)
            access_url = '%s?token=%s' % (CONF.spice.html5proxy_base_url,
                                          token)
        else:
            raise exception.ConsoleTypeInvalid(console_type=console_type)

        try:
            # Retrieve connect info from driver, and then decorate with our
            # access info token
            connect_info = self.driver.get_spice_console(instance)
            connect_info['token'] = token
            connect_info['access_url'] = access_url
        except exception.InstanceNotFound:
            if instance['vm_state'] != vm_states.BUILDING:
                raise
            raise exception.InstanceNotReady(instance_id=instance['uuid'])

        return connect_info

    @rpc_common.client_exceptions(exception.ConsoleTypeInvalid,
            exception.InstanceNotReady, exception.InstanceNotFound)
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def validate_console_port(self, ctxt, instance, port, console_type):
        if console_type == "spice-html5":
            console_info = self.driver.get_spice_console(instance)
        else:
            console_info = self.driver.get_vnc_console(instance)

        return console_info['port'] == port

    def _attach_volume_boot(self, context, instance, volume, mountpoint):
        """Attach a volume to an instance at boot time. So actual attach
        is done by instance creation.
        """

        instance_id = instance['id']
        instance_uuid = instance['uuid']
        volume_id = volume['id']
        context = context.elevated()
        LOG.audit(_('Booting with volume %(volume_id)s at %(mountpoint)s'),
                  {'volume_id': volume_id, 'mountpoint': mountpoint},
                  context=context, instance=instance)
        connector = self.driver.get_volume_connector(instance)
        connection_info = self.volume_api.initialize_connection(context,
                                                                volume_id,
                                                                connector)
        self.volume_api.attach(context, volume_id, instance_uuid, mountpoint)
        return connection_info

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def reserve_block_device_name(self, context, instance, device,
                                  volume_id=None):

        @utils.synchronized(instance['uuid'])
        def do_reserve():
            bdms = self.conductor_api.block_device_mapping_get_all_by_instance(
                context, instance)

            device_name = compute_utils.get_device_name_for_instance(
                    context, instance, bdms, device)

            # NOTE(vish): create bdm here to avoid race condition
            values = {'instance_uuid': instance['uuid'],
                      'volume_id': volume_id or 'reserved',
                      'device_name': device_name}

            self.conductor_api.block_device_mapping_create(context, values)

            return device_name

        return do_reserve()

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def attach_volume(self, context, volume_id, mountpoint, instance):
        """Attach a volume to an instance."""
        try:
            return self._attach_volume(context, volume_id,
                                       mountpoint, instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                capi = self.conductor_api
                capi.block_device_mapping_destroy_by_instance_and_device(
                        context, instance, mountpoint)

    def _attach_volume(self, context, volume_id, mountpoint, instance):
        context = context.elevated()
        LOG.audit(_('Attaching volume %(volume_id)s to %(mountpoint)s'),
                  {'volume_id': volume_id, 'mountpoint': mountpoint},
                  context=context, instance=instance)
        try:
            connector = self.driver.get_volume_connector(instance)
            connection_info = self.volume_api.initialize_connection(context,
                                                                    volume_id,
                                                                    connector)
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Failed to connect to volume %(volume_id)s "
                                "while attaching at %(mountpoint)s"),
                              {'volume_id': volume_id,
                               'mountpoint': mountpoint},
                              context=context, instance=instance)
                self.volume_api.unreserve_volume(context, volume_id)

        if 'serial' not in connection_info:
            connection_info['serial'] = volume_id

        try:
            self.driver.attach_volume(connection_info,
                                      instance,
                                      mountpoint)
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Failed to attach volume %(volume_id)s "
                                "at %(mountpoint)s") %
                              {'volume_id': volume_id,
                               'mountpoint': mountpoint},
                              context=context, instance=instance)
                self.volume_api.terminate_connection(context,
                                                     volume_id,
                                                     connector)

        self.volume_api.attach(context,
                               volume_id,
                               instance['uuid'],
                               mountpoint)
        values = {
            'instance_uuid': instance['uuid'],
            'connection_info': jsonutils.dumps(connection_info),
            'device_name': mountpoint,
            'delete_on_termination': False,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': volume_id,
            'volume_size': None,
            'no_device': None}
        self.conductor_api.block_device_mapping_update_or_create(context,
                                                                 values)
        info = dict(volume_id=volume_id)
        self._notify_about_instance_usage(
            context, instance, "volume.attach", extra_usage_info=info)

    def _detach_volume(self, context, instance, bdm):
        """Do the actual driver detach using block device mapping."""
        mp = bdm['device_name']
        volume_id = bdm['volume_id']

        LOG.audit(_('Detach volume %(volume_id)s from mountpoint %(mp)s'),
                  {'volume_id': volume_id, 'mp': mp},
                  context=context, instance=instance)

        connection_info = jsonutils.loads(bdm['connection_info'])
        # NOTE(vish): We currently don't use the serial when disconnecting,
        #             but added for completeness in case we ever do.
        if connection_info and 'serial' not in connection_info:
            connection_info['serial'] = volume_id
        try:
            if not self.driver.instance_exists(instance['name']):
                LOG.warn(_('Detaching volume from unknown instance'),
                         context=context, instance=instance)
            self.driver.detach_volume(connection_info,
                                      instance,
                                      mp)
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Failed to detach volume %(volume_id)s '
                                'from %(mp)s'),
                              {'volume_id': volume_id, 'mp': mp},
                              context=context, instance=instance)
                self.volume_api.roll_detaching(context, volume_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def detach_volume(self, context, volume_id, instance):
        """Detach a volume from an instance."""
        bdm = self._get_instance_volume_bdm(context, instance, volume_id)
        if CONF.volume_usage_poll_interval > 0:
            vol_stats = []
            mp = bdm['device_name']
            # Handle bootable volumes which will not contain /dev/
            if '/dev/' in mp:
                mp = mp[5:]
            try:
                vol_stats = self.driver.block_stats(instance['name'], mp)
            except NotImplementedError:
                pass

            if vol_stats:
                LOG.debug(_("Updating volume usage cache with totals"))
                rd_req, rd_bytes, wr_req, wr_bytes, flush_ops = vol_stats
                self.conductor_api.vol_usage_update(context, volume_id,
                                                    rd_req, rd_bytes,
                                                    wr_req, wr_bytes,
                                                    instance,
                                                    update_totals=True)

        self._detach_volume(context, instance, bdm)
        connector = self.driver.get_volume_connector(instance)
        self.volume_api.terminate_connection(context, volume_id, connector)
        self.volume_api.detach(context.elevated(), volume_id)
        self.conductor_api.block_device_mapping_destroy_by_instance_and_volume(
            context, instance, volume_id)
        info = dict(volume_id=volume_id)
        self._notify_about_instance_usage(
            context, instance, "volume.detach", extra_usage_info=info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @reverts_task_state
    @wrap_instance_fault
    def swap_volume(self, context, old_volume_id, new_volume_id, instance):
        """Swap volume for an instance."""
        context = context.elevated()
        bdm = self._get_instance_volume_bdm(context, instance, old_volume_id)
        mountpoint = bdm['device_name']
        connector = self.driver.get_volume_connector(instance)
        volume = self.volume_api.get(context, new_volume_id)
        try:
            new_cinfo = self.volume_api.initialize_connection(context,
                                                              volume,
                                                              connector)
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                msg = _("Failed to connect to volume %(volume_id)s "
                        "with volume at %(mountpoint)s")
                LOG.exception(msg % {'volume_id': new_volume_id,
                                     'mountpoint': mountpoint},
                              context=context,
                              instance=instance)
                self.volume_api.unreserve_volume(context, volume)

        old_cinfo = jsonutils.loads(bdm['connection_info'])
        if old_cinfo and 'serial' not in old_cinfo:
            old_cinfo['serial'] = old_volume_id
        new_cinfo['serial'] = old_cinfo['serial']

        try:
            self.driver.swap_volume(old_cinfo, new_cinfo, instance, mountpoint)
        except Exception:  # pylint: disable=W0702
            with excutils.save_and_reraise_exception():
                msg = _("Failed to swap volume %(old_volume_id)s "
                        "for %(new_volume_id)s")
                LOG.exception(msg % {'old_volume_id': old_volume_id,
                                     'new_volume_id': new_volume_id},
                              context=context,
                              instance=instance)
                self.volume_api.terminate_connection(context,
                                                     volume,
                                                     connector)
        self.volume_api.attach(context,
                               volume,
                               instance['uuid'],
                               mountpoint)
        # Remove old connection
        volume = self.volume_api.get(context, old_volume_id)
        self.volume_api.terminate_connection(context, volume, connector)
        self.volume_api.detach(context.elevated(), volume)
        # Update bdm
        values = {
            'instance_uuid': instance['uuid'],
            'connection_info': jsonutils.dumps(new_cinfo),
            'device_name': mountpoint,
            'delete_on_termination': False,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': new_volume_id,
            'volume_size': None,
            'no_device': None}
        self.conductor_api.block_device_mapping_update_or_create(context,
                                                                 values)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def remove_volume_connection(self, context, volume_id, instance):
        """Remove a volume connection using the volume api."""
        # NOTE(vish): We don't want to actually mark the volume
        #             detached, or delete the bdm, just remove the
        #             connection from this host.
        try:
            bdm = self._get_instance_volume_bdm(context, instance, volume_id)
            self._detach_volume(context, instance, bdm)
            connector = self.driver.get_volume_connector(instance)
            self.volume_api.terminate_connection(context, volume_id, connector)
        except exception.NotFound:
            pass

    def attach_interface(self, context, instance, network_id, port_id,
                         requested_ip=None):
        """Use hotplug to add an network adapter to an instance."""
        network_info = self.network_api.allocate_port_for_instance(
            context, instance, port_id, network_id, requested_ip,
            conductor_api=self.conductor_api)
        if len(network_info) != 1:
            LOG.error(_('allocate_port_for_instance returned %(ports)s ports')
                      % dict(ports=len(network_info)))
            raise exception.InterfaceAttachFailed(instance=instance)
        image_meta = _get_image_meta(context, instance['image_ref'])
        legacy_net_info = self._legacy_nw_info(network_info)
        (network, mapping) = legacy_net_info[0]
        self.driver.attach_interface(instance, image_meta, legacy_net_info)
        return legacy_net_info[0]

    def detach_interface(self, context, instance, port_id):
        """Detach an network adapter from an instance."""
        # FIXME(comstud): Why does this need elevated context?
        network_info = self._get_instance_nw_info(context.elevated(),
                                                  instance)
        legacy_nwinfo = self._legacy_nw_info(network_info)
        condemned = None
        for (network, mapping) in legacy_nwinfo:
            if mapping['vif_uuid'] == port_id:
                condemned = (network, mapping)
                break
        if condemned is None:
            raise exception.PortNotFound(_("Port %s is not "
                                           "attached") % port_id)

        self.network_api.deallocate_port_for_instance(context, instance,
            port_id, conductor_api=self.conductor_api)
        self.driver.detach_interface(instance, [condemned])

    def _get_compute_info(self, context, host):
        compute_node_ref = self.conductor_api.service_get_by_compute_host(
            context, host)
        try:
            return compute_node_ref['compute_node'][0]
        except IndexError:
            raise exception.NotFound(_("Host %s not found") % host)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def check_instance_shared_storage(self, ctxt, instance, data):
        """Check if the instance files are shared

        :param context: security context
        :param data: result of driver.check_instance_shared_storage_local

        Returns True if instance disks located on shared storage and
        False otherwise.
        """
        return self.driver.check_instance_shared_storage_remote(ctxt, data)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def check_can_live_migrate_destination(self, ctxt, instance,
                                           block_migration=False,
                                           disk_over_commit=False):
        """Check if it is possible to execute live migration.

        This runs checks on the destination host, and then calls
        back to the source host to check the results.

        :param context: security context
        :param instance: dict of instance data
        :param block_migration: if true, prepare for block migration
        :param disk_over_commit: if true, allow disk over commit
        :returns: a dict containing migration info
        """
        src_compute_info = self._get_compute_info(ctxt, instance['host'])
        dst_compute_info = self._get_compute_info(ctxt, CONF.host)
        dest_check_data = self.driver.check_can_live_migrate_destination(ctxt,
            instance, src_compute_info, dst_compute_info,
            block_migration, disk_over_commit)
        migrate_data = {}
        try:
            migrate_data = self.compute_rpcapi.\
                                check_can_live_migrate_source(ctxt, instance,
                                                              dest_check_data)
        finally:
            self.driver.check_can_live_migrate_destination_cleanup(ctxt,
                    dest_check_data)
        if 'migrate_data' in dest_check_data:
            migrate_data.update(dest_check_data['migrate_data'])
        return migrate_data

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param context: security context
        :param instance: dict of instance data
        :param dest_check_data: result of check_can_live_migrate_destination
        :returns: a dict containing migration info
        """
        capi = self.conductor_api
        bdms = capi.block_device_mapping_get_all_by_instance(ctxt, instance)

        is_volume_backed = self.compute_api.is_volume_backed_instance(ctxt,
                                                                      instance,
                                                                      bdms)
        dest_check_data['is_volume_backed'] = is_volume_backed
        return self.driver.check_can_live_migrate_source(ctxt, instance,
                                                         dest_check_data)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def pre_live_migration(self, context, instance,
                           block_migration=False, disk=None,
                           migrate_data=None):
        """Preparations for live migration at dest host.

        :param context: security context
        :param instance: dict of instance data
        :param block_migration: if true, prepare for block migration
        :param migrate_data : if not None, it is a dict which holds data
        required for live migration without shared storage.

        """
        bdms = self._refresh_block_device_connection_info(context, instance)

        block_device_info = self._get_instance_volume_block_device_info(
                            context, instance, bdms=bdms)

        network_info = self._get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(
                     context, instance, "live_migration.pre.start",
                     network_info=network_info)

        # TODO(tr3buchet): figure out how on the earth this is necessary
        fixed_ips = network_info.fixed_ips()
        if not fixed_ips:
            raise exception.FixedIpNotFoundForInstance(
                                       instance_uuid=instance['uuid'])

        pre_live_migration_data = self.driver.pre_live_migration(context,
                                       instance,
                                       block_device_info,
                                       self._legacy_nw_info(network_info),
                                       disk,
                                       migrate_data)

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
                                            self._legacy_nw_info(network_info))

        self._notify_about_instance_usage(
                     context, instance, "live_migration.pre.end",
                     network_info=network_info)

        return pre_live_migration_data

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def live_migration(self, context, dest, instance,
                       block_migration=False, migrate_data=None):
        """Executing live migration.

        :param context: security context
        :param instance: instance dict
        :param dest: destination host
        :param block_migration: if true, prepare for block migration
        :param migrate_data: implementation specific params

        """
        # Create a local copy since we'll be modifying the dictionary
        migrate_data = dict(migrate_data or {})
        try:
            if block_migration:
                disk = self.driver.get_instance_disk_info(instance['name'])
            else:
                disk = None

            pre_migration_data = self.compute_rpcapi.pre_live_migration(
                context, instance,
                block_migration, disk, dest, migrate_data)
            migrate_data['pre_live_migration_result'] = pre_migration_data

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Pre live migration failed at %s'),
                              dest, instance=instance)
                self._rollback_live_migration(context, instance, dest,
                                              block_migration, migrate_data)

        # Executing live migration
        # live_migration might raises exceptions, but
        # nothing must be recovered in this version.
        self.driver.live_migration(context, instance, dest,
                                   self._post_live_migration,
                                   self._rollback_live_migration,
                                   block_migration, migrate_data)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def _post_live_migration(self, ctxt, instance_ref,
                            dest, block_migration=False, migrate_data=None):
        """Post operations for live migration.

        This method is called from live_migration
        and mainly updating database record.

        :param ctxt: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance
        :param dest: destination host
        :param block_migration: if true, prepare for block migration
        :param migrate_data: if not None, it is a dict which has data
        required for live migration without shared storage

        """
        LOG.info(_('_post_live_migration() is started..'),
                 instance=instance_ref)

        # Detaching volumes.
        connector = self.driver.get_volume_connector(instance_ref)
        for bdm in self._get_instance_volume_bdms(ctxt, instance_ref):
            # NOTE(vish): We don't want to actually mark the volume
            #             detached, or delete the bdm, just remove the
            #             connection from this host.

            # remove the volume connection without detaching from hypervisor
            # because the instance is not running anymore on the current host
            self.volume_api.terminate_connection(ctxt, bdm['volume_id'],
                                                 connector)

        # Releasing vlan.
        # (not necessary in current implementation?)

        network_info = self._get_instance_nw_info(ctxt, instance_ref)

        self._notify_about_instance_usage(ctxt, instance_ref,
                                          "live_migration._post.start",
                                          network_info=network_info)
        # Releasing security group ingress rule.
        self.driver.unfilter_instance(instance_ref,
                                      self._legacy_nw_info(network_info))

        migration = {'source_compute': self.host,
                     'dest_compute': dest, }
        self.conductor_api.network_migrate_instance_start(ctxt,
                                                          instance_ref,
                                                          migration)

        # Define domain at destination host, without doing it,
        # pause/suspend/terminate do not work.
        self.compute_rpcapi.post_live_migration_at_destination(ctxt,
                instance_ref, block_migration, dest)

        # No instance booting at source host, but instance dir
        # must be deleted for preparing next block migration
        # must be deleted for preparing next live migration w/o shared storage
        is_shared_storage = True
        if migrate_data:
            is_shared_storage = migrate_data.get('is_shared_storage', True)
        if block_migration or not is_shared_storage:
            self.driver.destroy(instance_ref,
                                self._legacy_nw_info(network_info))
        else:
            # self.driver.destroy() usually performs  vif unplugging
            # but we must do it explicitly here when block_migration
            # is false, as the network devices at the source must be
            # torn down
            self.driver.unplug_vifs(instance_ref,
                                    self._legacy_nw_info(network_info))

        # NOTE(tr3buchet): tear down networks on source host
        self.network_api.setup_networks_on_host(ctxt, instance_ref,
                                                self.host, teardown=True)

        self._notify_about_instance_usage(ctxt, instance_ref,
                                          "live_migration._post.end",
                                          network_info=network_info)
        LOG.info(_('Migrating instance to %s finished successfully.'),
                 dest, instance=instance_ref)
        LOG.info(_("You may see the error \"libvirt: QEMU error: "
                   "Domain not found: no domain with matching name.\" "
                   "This error can be safely ignored."),
                 instance=instance_ref)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def post_live_migration_at_destination(self, context, instance,
                                           block_migration=False):
        """Post operations for live migration .

        :param context: security context
        :param instance: Instance dict
        :param block_migration: if true, prepare for block migration

        """
        LOG.info(_('Post operation of migration started'),
                 instance=instance)

        # NOTE(tr3buchet): setup networks on destination host
        #                  this is called a second time because
        #                  multi_host does not create the bridge in
        #                  plug_vifs
        self.network_api.setup_networks_on_host(context, instance,
                                                         self.host)
        migration = {'source_compute': instance['host'],
                     'dest_compute': self.host, }
        self.conductor_api.network_migrate_instance_finish(context,
                                                           instance,
                                                           migration)

        network_info = self._get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(
                     context, instance, "live_migration.post.dest.start",
                     network_info=network_info)
        block_device_info = self._get_instance_volume_block_device_info(
                            context, instance)

        self.driver.post_live_migration_at_destination(context, instance,
                                            self._legacy_nw_info(network_info),
                                            block_migration, block_device_info)
        # Restore instance state
        current_power_state = self._get_power_state(context, instance)
        node_name = None
        try:
            compute_node = self._get_compute_info(context, self.host)
            node_name = compute_node['hypervisor_hostname']
        except exception.NotFound:
            LOG.exception(_('Failed to get compute_info for %s') % self.host)
        finally:
            instance = self._instance_update(context, instance['uuid'],
                    host=self.host, power_state=current_power_state,
                    vm_state=vm_states.ACTIVE, task_state=None,
                    expected_task_state=task_states.MIGRATING,
                    node=node_name)

        # NOTE(vish): this is necessary to update dhcp
        self.network_api.setup_networks_on_host(context, instance, self.host)
        self._notify_about_instance_usage(
                     context, instance, "live_migration.post.dest.end",
                     network_info=network_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def _rollback_live_migration(self, context, instance,
                                 dest, block_migration, migrate_data=None):
        """Recovers Instance/volume state from migrating -> running.

        :param context: security context
        :param instance: nova.db.sqlalchemy.models.Instance
        :param dest:
            This method is called from live migration src host.
            This param specifies destination host.
        :param block_migration: if true, prepare for block migration
        :param migrate_data:
            if not none, contains implementation specific data.

        """
        host = instance['host']
        instance = self._instance_update(context, instance['uuid'],
                host=host, vm_state=vm_states.ACTIVE,
                task_state=None, expected_task_state=task_states.MIGRATING)

        # NOTE(tr3buchet): setup networks on source host (really it's re-setup)
        self.network_api.setup_networks_on_host(context, instance, self.host)

        for bdm in self._get_instance_volume_bdms(context, instance):
            volume_id = bdm['volume_id']
            self.compute_rpcapi.remove_volume_connection(context, instance,
                    volume_id, dest)

        self._notify_about_instance_usage(context, instance,
                                          "live_migration._rollback.start")

        # Block migration needs empty image at destination host
        # before migration starts, so if any failure occurs,
        # any empty images has to be deleted.
        # Also Volume backed live migration w/o shared storage needs to delete
        # newly created instance-xxx dir on the destination as a part of its
        # rollback process
        is_volume_backed = False
        is_shared_storage = True
        if migrate_data:
            is_volume_backed = migrate_data.get('is_volume_backed', False)
            is_shared_storage = migrate_data.get('is_shared_storage', True)
        if block_migration or (is_volume_backed and not is_shared_storage):
            self.compute_rpcapi.rollback_live_migration_at_destination(context,
                    instance, dest)

        self._notify_about_instance_usage(context, instance,
                                          "live_migration._rollback.end")

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def rollback_live_migration_at_destination(self, context, instance):
        """Cleaning up image directory that is created pre_live_migration.

        :param context: security context
        :param instance: an Instance dict sent over rpc
        """
        network_info = self._get_instance_nw_info(context, instance)
        self._notify_about_instance_usage(
                      context, instance, "live_migration.rollback.dest.start",
                      network_info=network_info)

        # NOTE(tr3buchet): tear down networks on destination host
        self.network_api.setup_networks_on_host(context, instance,
                                                self.host, teardown=True)

        # NOTE(vish): The mapping is passed in so the driver can disconnect
        #             from remote volumes if necessary
        block_device_info = self._get_instance_volume_block_device_info(
                            context, instance)
        self.driver.destroy(instance, self._legacy_nw_info(network_info),
                            block_device_info)
        self._notify_about_instance_usage(
                        context, instance, "live_migration.rollback.dest.end",
                        network_info=network_info)

    @periodic_task.periodic_task
    def _heal_instance_info_cache(self, context):
        """Called periodically.  On every call, try to update the
        info_cache's network information for another instance by
        calling to the network manager.

        This is implemented by keeping a cache of uuids of instances
        that live on this host.  On each call, we pop one off of a
        list, pull the DB record, and try the call to the network API.
        If anything errors, we don't care.  It's possible the instance
        has been deleted, etc.
        """
        heal_interval = CONF.heal_instance_info_cache_interval
        if not heal_interval:
            return
        curr_time = time.time()
        if self._last_info_cache_heal + heal_interval > curr_time:
            return
        self._last_info_cache_heal = curr_time

        instance_uuids = getattr(self, '_instance_uuids_to_heal', None)
        instance = None

        while not instance or instance['host'] != self.host:
            if instance_uuids:
                try:
                    instance = instance_obj.Instance.get_by_uuid(
                        context, instance_uuids.pop(0))
                except exception.InstanceNotFound:
                    # Instance is gone.  Try to grab another.
                    continue
            else:
                # No more in our copy of uuids.  Pull from the DB.
                db_instances = instance_obj.InstanceList.get_by_host(
                    context, self.host, expected_attrs=[])
                if not db_instances:
                    # None.. just return.
                    return
                instance = db_instances[0]
                instance_uuids = [inst['uuid'] for inst in db_instances[1:]]
                self._instance_uuids_to_heal = instance_uuids

        # We have an instance now and it's ours
        try:
            # Call to network API to get instance info.. this will
            # force an update to the instance's info_cache
            self._get_instance_nw_info(context, instance)
            LOG.debug(_('Updated the info_cache for instance'),
                      instance=instance)
        except Exception:
            # We don't care about any failures
            pass

    @periodic_task.periodic_task
    def _poll_rebooting_instances(self, context):
        if CONF.reboot_timeout > 0:
            filters = {'task_state': task_states.REBOOTING,
                       'host': self.host}
            rebooting = instance_obj.InstanceList.get_by_filters(
                context, filters, expected_attrs=[])

            to_poll = []
            for instance in rebooting:
                if timeutils.is_older_than(instance['updated_at'],
                                           CONF.reboot_timeout):
                    to_poll.append(instance)

            self.driver.poll_rebooting_instances(CONF.reboot_timeout, to_poll)

    @periodic_task.periodic_task
    def _poll_rescued_instances(self, context):
        if CONF.rescue_timeout > 0:
            filters = {'vm_state': vm_states.RESCUED,
                       'host': self.host}
            rescued_instances = self.conductor_api.instance_get_all_by_filters(
                context, filters, columns_to_join=[])

            to_unrescue = []
            for instance in rescued_instances:
                if timeutils.is_older_than(instance['launched_at'],
                                           CONF.rescue_timeout):
                    to_unrescue.append(instance)

            for instance in to_unrescue:
                self.conductor_api.compute_unrescue(context, instance)

    @periodic_task.periodic_task
    def _poll_unconfirmed_resizes(self, context):
        if CONF.resize_confirm_window == 0:
            return

        capi = self.conductor_api
        migrations = capi.migration_get_unconfirmed_by_dest_compute(
                context, CONF.resize_confirm_window, self.host)

        migrations_info = dict(migration_count=len(migrations),
                confirm_window=CONF.resize_confirm_window)

        if migrations_info["migration_count"] > 0:
            LOG.info(_("Found %(migration_count)d unconfirmed migrations "
                       "older than %(confirm_window)d seconds"),
                     migrations_info)

        def _set_migration_to_error(migration, reason, **kwargs):
            LOG.warn(_("Setting migration %(migration_id)s to error: "
                       "%(reason)s"),
                     {'migration_id': migration['id'], 'reason': reason},
                     **kwargs)
            self.conductor_api.migration_update(context, migration,
                                                'error')

        for migration in migrations:
            instance_uuid = migration['instance_uuid']
            LOG.info(_("Automatically confirming migration "
                       "%(migration_id)s for instance %(instance_uuid)s"),
                     {'migration_id': migration['id'],
                      'instance_uuid': instance_uuid})
            try:
                instance = instance_obj.Instance.get_by_uuid(context,
                                                             instance_uuid)
            except exception.InstanceNotFound:
                reason = (_("Instance %s not found") %
                          instance_uuid)
                _set_migration_to_error(migration, reason)
                continue
            if instance['vm_state'] == vm_states.ERROR:
                reason = _("In ERROR state")
                _set_migration_to_error(migration, reason,
                                        instance=instance)
                continue
            vm_state = instance['vm_state']
            task_state = instance['task_state']
            if vm_state != vm_states.RESIZED or task_state is not None:
                reason = (_("In states %(vm_state)s/%(task_state)s, not "
                           "RESIZED/None") %
                          {'vm_state': vm_state,
                           'task_state': task_state})
                _set_migration_to_error(migration, reason,
                                        instance=instance)
                continue
            try:
                self.conductor_api.compute_confirm_resize(
                    context, instance, migration_ref=migration)
            except Exception as e:
                LOG.error(_("Error auto-confirming resize: %s. "
                            "Will retry later.") % e, instance=instance)

    @periodic_task.periodic_task(spacing=CONF.shelved_poll_interval)
    def _poll_shelved_instances(self, context):
        if CONF.shelved_offload_time <= 0:
            return

        filters = {'vm_state': vm_states.SHELVED,
                   'host': self.host}
        shelved_instances = instance_obj.InstanceList.get_by_filters(
            context, filters=filters, expected_attrs=['system_metadata'])

        to_gc = []
        for instance in shelved_instances:
            sys_meta = instance.system_metadata
            shelved_at = timeutils.parse_strtime(sys_meta['shelved_at'])
            if timeutils.is_older_than(shelved_at, CONF.shelved_offload_time):
                to_gc.append(instance)

        for instance in to_gc:
            try:
                instance.task_state = task_states.SHELVING_OFFLOADING
                instance.save()
                self.shelve_offload_instance(context, instance)
            except Exception:
                LOG.exception(_('Periodic task failed to offload instance.'),
                        instance=instance)

    @periodic_task.periodic_task
    def _instance_usage_audit(self, context):
        if not CONF.instance_usage_audit:
            return

        if compute_utils.has_audit_been_run(context,
                                            self.conductor_api,
                                            self.host):
            return

        begin, end = utils.last_completed_audit_period()
        capi = self.conductor_api
        instances = capi.instance_get_active_by_window_joined(
            context, begin, end, host=self.host)
        num_instances = len(instances)
        errors = 0
        successes = 0
        LOG.info(_("Running instance usage audit for"
                   " host %(host)s from %(begin_time)s to "
                   "%(end_time)s. %(number_instances)s"
                   " instances."),
                 dict(host=self.host,
                      begin_time=begin,
                      end_time=end,
                      number_instances=num_instances))
        start_time = time.time()
        compute_utils.start_instance_usage_audit(context,
                                      self.conductor_api,
                                      begin, end,
                                      self.host, num_instances)
        for instance in instances:
            try:
                self.conductor_api.notify_usage_exists(
                    context, instance,
                    ignore_missing_network_data=False)
                successes += 1
            except Exception:
                LOG.exception(_('Failed to generate usage '
                                'audit for instance '
                                'on host %s') % self.host,
                              instance=instance)
                errors += 1
        compute_utils.finish_instance_usage_audit(context,
                                      self.conductor_api,
                                      begin, end,
                                      self.host, errors,
                                      "Instance usage audit ran "
                                      "for host %s, %s instances "
                                      "in %s seconds." % (
                                      self.host,
                                      num_instances,
                                      time.time() - start_time))

    @periodic_task.periodic_task
    def _poll_bandwidth_usage(self, context):
        prev_time, start_time = utils.last_completed_audit_period()

        curr_time = time.time()
        if (curr_time - self._last_bw_usage_poll >
                CONF.bandwidth_poll_interval):
            self._last_bw_usage_poll = curr_time
            LOG.info(_("Updating bandwidth usage cache"))
            cells_update_interval = CONF.cells.bandwidth_update_interval
            if (cells_update_interval > 0 and
                   curr_time - self._last_bw_usage_cell_update >
                           cells_update_interval):
                self._last_bw_usage_cell_update = curr_time
                update_cells = True
            else:
                update_cells = False

            instances = self.conductor_api.instance_get_all_by_host(
                context, self.host, columns_to_join=[])
            try:
                bw_counters = self.driver.get_all_bw_counters(instances)
            except NotImplementedError:
                # NOTE(mdragon): Not all hypervisors have bandwidth polling
                # implemented yet.  If they don't it doesn't break anything,
                # they just don't get the info in the usage events.
                return

            refreshed = timeutils.utcnow()
            for bw_ctr in bw_counters:
                # Allow switching of greenthreads between queries.
                greenthread.sleep(0)
                bw_in = 0
                bw_out = 0
                last_ctr_in = None
                last_ctr_out = None
                usage = self.conductor_api.bw_usage_get(context,
                                                        bw_ctr['uuid'],
                                                        start_time,
                                                        bw_ctr['mac_address'])
                if usage:
                    bw_in = usage['bw_in']
                    bw_out = usage['bw_out']
                    last_ctr_in = usage['last_ctr_in']
                    last_ctr_out = usage['last_ctr_out']
                else:
                    usage = self.conductor_api.bw_usage_get(
                        context, bw_ctr['uuid'], prev_time,
                        bw_ctr['mac_address'])
                    if usage:
                        last_ctr_in = usage['last_ctr_in']
                        last_ctr_out = usage['last_ctr_out']

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

                self.conductor_api.bw_usage_update(context,
                                                   bw_ctr['uuid'],
                                                   bw_ctr['mac_address'],
                                                   start_time,
                                                   bw_in,
                                                   bw_out,
                                                   bw_ctr['bw_in'],
                                                   bw_ctr['bw_out'],
                                                   last_refreshed=refreshed,
                                                   update_cells=update_cells)

    def _get_host_volume_bdms(self, context, host):
        """Return all block device mappings on a compute host."""
        compute_host_bdms = []
        instances = self.conductor_api.instance_get_all_by_host(context,
                                                                self.host)
        for instance in instances:
            instance_bdms = self._get_instance_volume_bdms(context, instance)
            compute_host_bdms.append(dict(instance=instance,
                                          instance_bdms=instance_bdms))

        return compute_host_bdms

    def _update_volume_usage_cache(self, context, vol_usages):
        """Updates the volume usage cache table with a list of stats."""
        for usage in vol_usages:
            # Allow switching of greenthreads between queries.
            greenthread.sleep(0)
            self.conductor_api.vol_usage_update(context, usage['volume'],
                                                usage['rd_req'],
                                                usage['rd_bytes'],
                                                usage['wr_req'],
                                                usage['wr_bytes'],
                                                usage['instance'])

    @periodic_task.periodic_task
    def _poll_volume_usage(self, context, start_time=None):
        if CONF.volume_usage_poll_interval == 0:
            return

        if not start_time:
            start_time = utils.last_completed_audit_period()[1]

        curr_time = time.time()
        if (curr_time - self._last_vol_usage_poll) < \
                CONF.volume_usage_poll_interval:
            return

        self._last_vol_usage_poll = curr_time
        compute_host_bdms = self._get_host_volume_bdms(context, self.host)
        if not compute_host_bdms:
            return

        LOG.debug(_("Updating volume usage cache"))
        try:
            vol_usages = self.driver.get_all_volume_usage(context,
                                                          compute_host_bdms)
        except NotImplementedError:
            return

        self._update_volume_usage_cache(context, vol_usages)

    @periodic_task.periodic_task
    def _report_driver_status(self, context):
        curr_time = time.time()
        if curr_time - self._last_host_check > CONF.host_state_interval:
            self._last_host_check = curr_time
            LOG.info(_("Updating host status"))
            # This will grab info about the host and queue it
            # to be sent to the Schedulers.
            capabilities = self.driver.get_host_stats(refresh=True)
            for capability in (capabilities if isinstance(capabilities, list)
                               else [capabilities]):
                capability['host_ip'] = CONF.my_ip
            self.update_service_capabilities(capabilities)

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
        db_instances = instance_obj.InstanceList.get_by_host(context,
                                                             self.host)

        num_vm_instances = self.driver.get_num_instances()
        num_db_instances = len(db_instances)

        if num_vm_instances != num_db_instances:
            LOG.warn(_("Found %(num_db_instances)s in the database and "
                       "%(num_vm_instances)s on the hypervisor."),
                     {'num_db_instances': num_db_instances,
                      'num_vm_instances': num_vm_instances})

        for db_instance in db_instances:
            if db_instance['task_state'] is not None:
                LOG.info(_("During sync_power_state the instance has a "
                           "pending task. Skip."), instance=db_instance)
                continue
            # No pending tasks. Now try to figure out the real vm_power_state.
            try:
                vm_instance = self.driver.get_info(db_instance)
                vm_power_state = vm_instance['state']
            except exception.InstanceNotFound:
                vm_power_state = power_state.NOSTATE
            # Note(maoy): the above get_info call might take a long time,
            # for example, because of a broken libvirt driver.
            self._sync_instance_power_state(context,
                                            db_instance,
                                            vm_power_state)

    def _sync_instance_power_state(self, context, db_instance, vm_power_state):
        """Align instance power state between the database and hypervisor.

        If the instance is not found on the hypervisor, but is in the database,
        then a stop() API will be called on the instance.
        """

        # We re-query the DB to get the latest instance info to minimize
        # (not eliminate) race condition.
        db_instance.refresh()
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
            LOG.info(_("During the sync_power process the "
                       "instance has moved from "
                       "host %(src)s to host %(dst)s") %
                       {'src': self.host,
                        'dst': db_instance.host},
                     instance=db_instance)
            return
        elif db_instance.task_state is not None:
            # on the receiving end of nova-compute, it could happen
            # that the DB instance already report the new resident
            # but the actual VM has not showed up on the hypervisor
            # yet. In this case, let's allow the loop to continue
            # and run the state sync in a later round
            LOG.info(_("During sync_power_state the instance has a "
                       "pending task. Skip."), instance=db_instance)
            return

        if vm_power_state != db_power_state:
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
                        vm_states.PAUSED,
                        vm_states.ERROR):
            # TODO(maoy): we ignore these vm_state for now.
            pass
        elif vm_state == vm_states.ACTIVE:
            # The only rational power state should be RUNNING
            if vm_power_state in (power_state.SHUTDOWN,
                                  power_state.CRASHED):
                LOG.warn(_("Instance shutdown by itself. Calling "
                           "the stop API."), instance=db_instance)
                try:
                    # Note(maoy): here we call the API instead of
                    # brutally updating the vm_state in the database
                    # to allow all the hooks and checks to be performed.
                    self.conductor_api.compute_stop(context, db_instance)
                except Exception:
                    # Note(maoy): there is no need to propagate the error
                    # because the same power_state will be retrieved next
                    # time and retried.
                    # For example, there might be another task scheduled.
                    LOG.exception(_("error during stop() in "
                                    "sync_power_state."),
                                  instance=db_instance)
            elif vm_power_state == power_state.SUSPENDED:
                LOG.warn(_("Instance is suspended unexpectedly. Calling "
                           "the stop API."), instance=db_instance)
                try:
                    self.conductor_api.compute_stop(context, db_instance)
                except Exception:
                    LOG.exception(_("error during stop() in "
                                    "sync_power_state."),
                                  instance=db_instance)
            elif vm_power_state == power_state.PAUSED:
                # Note(maoy): a VM may get into the paused state not only
                # because the user request via API calls, but also
                # due to (temporary) external instrumentations.
                # Before the virt layer can reliably report the reason,
                # we simply ignore the state discrepancy. In many cases,
                # the VM state will go back to running after the external
                # instrumentation is done. See bug 1097806 for details.
                LOG.warn(_("Instance is paused unexpectedly. Ignore."),
                         instance=db_instance)
            elif vm_power_state == power_state.NOSTATE:
                # Occasionally, depending on the status of the hypervisor,
                # which could be restarting for example, an instance may
                # not be found.  Therefore just log the condidtion.
                LOG.warn(_("Instance is unexpectedly not found. Ignore."),
                         instance=db_instance)
        elif vm_state == vm_states.STOPPED:
            if vm_power_state not in (power_state.NOSTATE,
                                      power_state.SHUTDOWN,
                                      power_state.CRASHED):
                LOG.warn(_("Instance is not stopped. Calling "
                           "the stop API."), instance=db_instance)
                try:
                    # Note(maoy): this assumes that the stop API is
                    # idempotent.
                    self.conductor_api.compute_stop(context, db_instance)
                except Exception:
                    LOG.exception(_("error during stop() in "
                                    "sync_power_state."),
                                  instance=db_instance)
        elif vm_state in (vm_states.SOFT_DELETED,
                          vm_states.DELETED):
            if vm_power_state not in (power_state.NOSTATE,
                                      power_state.SHUTDOWN):
                # Note(maoy): this should be taken care of periodically in
                # _cleanup_running_deleted_instances().
                LOG.warn(_("Instance is not (soft-)deleted."),
                         instance=db_instance)

    @periodic_task.periodic_task
    def _reclaim_queued_deletes(self, context):
        """Reclaim instances that are queued for deletion."""
        interval = CONF.reclaim_instance_interval
        if interval <= 0:
            LOG.debug(_("CONF.reclaim_instance_interval <= 0, skipping..."))
            return

        filters = {'vm_state': vm_states.SOFT_DELETED,
                   'task_state': None,
                   'host': self.host}
        instances = instance_obj.InstanceList.get_by_filters(
            context, filters,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)
        for instance in instances:
            if self._deleted_old_enough(instance, interval):
                capi = self.conductor_api
                bdms = capi.block_device_mapping_get_all_by_instance(
                    context, instance)
                LOG.info(_('Reclaiming deleted instance'), instance=instance)
                # NOTE(comstud): Quotas were already accounted for when
                # the instance was soft deleted, so there's no need to
                # pass reservations here.
                try:
                    self._delete_instance(context, instance, bdms)
                except Exception as e:
                    LOG.warning(_("Periodic reclaim failed to delete "
                                  "instance: %s"),
                                unicode(e), instance=instance)

    @periodic_task.periodic_task
    def update_available_resource(self, context):
        """See driver.get_available_resource()

        Periodic process that keeps that the compute host's understanding of
        resource availability and usage in sync with the underlying hypervisor.

        :param context: security context
        """
        new_resource_tracker_dict = {}
        nodenames = set(self.driver.get_available_nodes())
        for nodename in nodenames:
            rt = self._get_resource_tracker(nodename)
            rt.update_available_resource(context)
            new_resource_tracker_dict[nodename] = rt

        # Delete orphan compute node not reported by driver but still in db
        compute_nodes_in_db = self._get_compute_nodes_in_db(context)

        for cn in compute_nodes_in_db:
            if cn.get('hypervisor_hostname') not in nodenames:
                LOG.audit(_("Deleting orphan compute node %s") % cn['id'])
                self.conductor_api.compute_node_delete(context, cn)

        self._resource_tracker_dict = new_resource_tracker_dict

    def _get_compute_nodes_in_db(self, context):
        service_ref = self.conductor_api.service_get_by_compute_host(
            context, self.host)

        if not service_ref:
            LOG.error(_("No service record for host %s"), self.host)
            return []

        return service_ref['compute_node']

    @periodic_task.periodic_task(
        spacing=CONF.running_deleted_instance_poll_interval)
    def _cleanup_running_deleted_instances(self, context):
        """Cleanup any instances which are erroneously still running after
        having been deleted.

        Valid actions to take are:

            1. noop - do nothing
            2. log - log which instances are erroneously running
            3. reap - shutdown and cleanup any erroneously running instances

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
                capi = self.conductor_api
                bdms = capi.block_device_mapping_get_all_by_instance(
                    context, instance)

                if action == "log":
                    LOG.warning(_("Detected instance with name label "
                                  "'%s' which is marked as "
                                  "DELETED but still present on host."),
                                instance['name'], instance=instance)

                elif action == 'reap':
                    LOG.info(_("Destroying instance with name label "
                               "'%s' which is marked as "
                               "DELETED but still present on host."),
                             instance['name'], instance=instance)
                    try:
                        self._shutdown_instance(context, instance, bdms)
                        self._cleanup_volumes(context, instance['uuid'], bdms)
                    except Exception as e:
                        LOG.warning(_("Periodic cleanup failed to delete "
                                      "instance: %s"),
                                    unicode(e), instance=instance)
                else:
                    raise Exception(_("Unrecognized value '%s'"
                                      " for CONF.running_deleted_"
                                      "instance_action"), action,
                                    instance=instance)

    def _running_deleted_instances(self, context):
        """Returns a list of instances nova thinks is deleted,
        but the hypervisor thinks is still running.
        """
        timeout = CONF.running_deleted_instance_timeout
        filters = {'deleted': True,
                   'soft_deleted': False,
                   'host': self.host}
        instances = self._get_instances_on_driver(context, filters)
        return [i for i in instances if self._deleted_old_enough(i, timeout)]

    def _deleted_old_enough(self, instance, timeout):
        deleted_at = instance['deleted_at']
        if isinstance(instance, obj_base.NovaObject) and deleted_at:
            deleted_at = deleted_at.replace(tzinfo=None)
        return (not deleted_at or timeutils.is_older_than(deleted_at, timeout))

    @contextlib.contextmanager
    def _error_out_instance_on_exception(self, context, instance_uuid,
                                        reservations=None):
        try:
            yield
        except exception.InstanceFaultRollback as error:
            self._quota_rollback(context, reservations)
            LOG.info(_("Setting instance back to ACTIVE after: %s"),
                     error, instance_uuid=instance_uuid)
            self._instance_update(context, instance_uuid,
                                  vm_state=vm_states.ACTIVE,
                                  task_state=None)
            raise error.inner_exception
        except Exception as error:
            with excutils.save_and_reraise_exception():
                self._quota_rollback(context, reservations)
                LOG.error(_('%s. Setting instance vm_state to ERROR'),
                          error, instance_uuid=instance_uuid)
                self._set_instance_error_state(context, instance_uuid)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def add_aggregate_host(self, context, host, slave_info=None,
                           aggregate=None, aggregate_id=None):
        """Notify hypervisor of change (for hypervisor pools)."""
        if not aggregate:
            aggregate = self.conductor_api.aggregate_get(context, aggregate_id)

        try:
            self.driver.add_to_aggregate(context, aggregate, host,
                                         slave_info=slave_info)
        except exception.AggregateError:
            with excutils.save_and_reraise_exception():
                self.driver.undo_aggregate_operation(
                                    context,
                                    self.conductor_api.aggregate_host_delete,
                                    aggregate, host)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def remove_aggregate_host(self, context, host, slave_info=None,
                              aggregate=None, aggregate_id=None):
        """Removes a host from a physical hypervisor pool."""
        if not aggregate:
            aggregate = self.conductor_api.aggregate_get(context, aggregate_id)

        try:
            self.driver.remove_from_aggregate(context, aggregate, host,
                                              slave_info=slave_info)
        except (exception.AggregateError,
                exception.InvalidAggregateAction) as e:
            with excutils.save_and_reraise_exception():
                self.driver.undo_aggregate_operation(
                                    context,
                                    self.conductor_api.aggregate_host_add,
                                    aggregate, host,
                                    isinstance(e, exception.AggregateError))

    @periodic_task.periodic_task(spacing=CONF.image_cache_manager_interval,
                                 external_process_ok=True)
    def _run_image_cache_manager_pass(self, context):
        """Run a single pass of the image cache manager."""

        if not self.driver.capabilities["has_imagecache"]:
            return
        if CONF.image_cache_manager_interval == 0:
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
        filtered_instances = self.conductor_api.instance_get_all_by_filters(
            context, filters, columns_to_join=[])

        self.driver.manage_image_cache(context, filtered_instances)

    @periodic_task.periodic_task(spacing=CONF.instance_delete_interval)
    def _run_pending_deletes(self, context):
        """Retry any pending instance file deletes."""
        if CONF.instance_delete_interval == 0:
            return

        LOG.debug(_('Cleaning up deleted instances'))
        filters = {'deleted': True,
                   'host': CONF.host,
                   'cleaned': False}
        attrs = ['info_cache', 'security_groups', 'system_metadata']
        with utils.temporary_mutation(context, read_deleted='yes'):
            instances = instance_obj.InstanceList.get_by_filters(
                context, filters, expected_attrs=attrs)
        LOG.debug(_('There are %d instances to clean'), len(instances))

        for instance in instances:
            attempts = int(instance.system_metadata.get('clean_attempts', '0'))
            LOG.debug(_('Instance has had %(attempts)s of %(max)s '
                        'cleanup attempts'),
                        {'attempts': attempts,
                         'max': CONF.maximum_instance_delete_attempts},
                         instance=instance)
            if attempts < CONF.maximum_instance_delete_attempts:
                success = self.driver.delete_instance_files(instance)

                instance.system_metadata['clean_attempts'] = str(attempts + 1)
                if success:
                    instance.cleaned = True
                with utils.temporary_mutation(context, read_deleted='yes'):
                    instance.save(context)
