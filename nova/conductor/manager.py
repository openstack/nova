#    Copyright 2012 IBM Corp.
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

"""Handles database requests from other nova services."""

import copy

from nova.api.ec2 import ec2utils
from nova import block_device
from nova.compute import api as compute_api
from nova.compute import utils as compute_utils
from nova import exception
from nova import manager
from nova import network
from nova.network.security_group import openstack_driver
from nova import notifications
from nova.objects import base as nova_object
from nova.openstack.common.db.sqlalchemy import session as db_session
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils
from nova import quota
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova.scheduler import utils as scheduler_utils

LOG = logging.getLogger(__name__)

# Instead of having a huge list of arguments to instance_update(), we just
# accept a dict of fields to update and use this whitelist to validate it.
allowed_updates = ['task_state', 'vm_state', 'expected_task_state',
                   'power_state', 'access_ip_v4', 'access_ip_v6',
                   'launched_at', 'terminated_at', 'host', 'node',
                   'memory_mb', 'vcpus', 'root_gb', 'ephemeral_gb',
                   'instance_type_id', 'root_device_name', 'launched_on',
                   'progress', 'vm_mode', 'default_ephemeral_device',
                   'default_swap_device', 'root_device_name',
                   'system_metadata', 'updated_at'
                   ]

# Fields that we want to convert back into a datetime object.
datetime_fields = ['launched_at', 'terminated_at', 'updated_at']


class ConductorManager(manager.Manager):
    """Mission: Conduct things.

    The methods in the base API for nova-conductor are various proxy operations
    performed on behalf of the nova-compute service running on compute nodes.
    Compute nodes are not allowed to directly access the database, so this set
    of methods allows them to get specific work done without locally accessing
    the database.

    The nova-conductor service also exposes an API in the 'compute_task'
    namespace.  See the ComputeTaskManager class for details.
    """

    RPC_API_VERSION = '1.51'

    def __init__(self, *args, **kwargs):
        super(ConductorManager, self).__init__(service_name='conductor',
                                               *args, **kwargs)
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())
        self._network_api = None
        self._compute_api = None
        self.compute_task_mgr = ComputeTaskManager()
        self.quotas = quota.QUOTAS

    def create_rpc_dispatcher(self, *args, **kwargs):
        kwargs['additional_apis'] = [self.compute_task_mgr]
        return super(ConductorManager, self).create_rpc_dispatcher(*args,
                **kwargs)

    @property
    def network_api(self):
        # NOTE(danms): We need to instantiate our network_api on first use
        # to avoid the circular dependency that exists between our init
        # and network_api's
        if self._network_api is None:
            self._network_api = network.API()
        return self._network_api

    @property
    def compute_api(self):
        if self._compute_api is None:
            self._compute_api = compute_api.API()
        return self._compute_api

    def ping(self, context, arg):
        # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
        # now a part of the base rpc API.
        return jsonutils.to_primitive({'service': 'conductor', 'arg': arg})

    @rpc_common.client_exceptions(KeyError, ValueError,
                                  exception.InvalidUUID,
                                  exception.InstanceNotFound,
                                  exception.UnexpectedTaskStateError)
    def instance_update(self, context, instance_uuid,
                        updates, service=None):
        for key, value in updates.iteritems():
            if key not in allowed_updates:
                LOG.error(_("Instance update attempted for "
                            "'%(key)s' on %(instance_uuid)s") % locals())
                raise KeyError("unexpected update keyword '%s'" % key)
            if key in datetime_fields and isinstance(value, basestring):
                updates[key] = timeutils.parse_strtime(value)

        old_ref, instance_ref = self.db.instance_update_and_get_original(
            context, instance_uuid, updates)
        notifications.send_update(context, old_ref, instance_ref, service)
        return jsonutils.to_primitive(instance_ref)

    @rpc_common.client_exceptions(exception.InstanceNotFound)
    def instance_get(self, context, instance_id):
        return jsonutils.to_primitive(
            self.db.instance_get(context, instance_id))

    @rpc_common.client_exceptions(exception.InstanceNotFound)
    def instance_get_by_uuid(self, context, instance_uuid,
                             columns_to_join=None):
        return jsonutils.to_primitive(
            self.db.instance_get_by_uuid(context, instance_uuid,
                columns_to_join))

    # NOTE(hanlind): This method can be removed in v2.0 of the RPC API.
    def instance_get_all(self, context):
        return jsonutils.to_primitive(self.db.instance_get_all(context))

    def instance_get_all_by_host(self, context, host, node=None,
                                 columns_to_join=None):
        if node is not None:
            result = self.db.instance_get_all_by_host_and_node(
                context.elevated(), host, node)
        else:
            result = self.db.instance_get_all_by_host(context.elevated(), host,
                                                      columns_to_join)
        return jsonutils.to_primitive(result)

    @rpc_common.client_exceptions(exception.MigrationNotFound)
    def migration_get(self, context, migration_id):
        migration_ref = self.db.migration_get(context.elevated(),
                                              migration_id)
        return jsonutils.to_primitive(migration_ref)

    def migration_get_unconfirmed_by_dest_compute(self, context,
                                                  confirm_window,
                                                  dest_compute):
        migrations = self.db.migration_get_unconfirmed_by_dest_compute(
            context, confirm_window, dest_compute)
        return jsonutils.to_primitive(migrations)

    def migration_get_in_progress_by_host_and_node(self, context,
                                                   host, node):
        migrations = self.db.migration_get_in_progress_by_host_and_node(
            context, host, node)
        return jsonutils.to_primitive(migrations)

    def migration_create(self, context, instance, values):
        values.update({'instance_uuid': instance['uuid'],
                       'source_compute': instance['host'],
                       'source_node': instance['node']})
        migration_ref = self.db.migration_create(context.elevated(), values)
        return jsonutils.to_primitive(migration_ref)

    @rpc_common.client_exceptions(exception.MigrationNotFound)
    def migration_update(self, context, migration, status):
        migration_ref = self.db.migration_update(context.elevated(),
                                                 migration['id'],
                                                 {'status': status})
        return jsonutils.to_primitive(migration_ref)

    @rpc_common.client_exceptions(exception.AggregateHostExists)
    def aggregate_host_add(self, context, aggregate, host):
        host_ref = self.db.aggregate_host_add(context.elevated(),
                aggregate['id'], host)

        return jsonutils.to_primitive(host_ref)

    @rpc_common.client_exceptions(exception.AggregateHostNotFound)
    def aggregate_host_delete(self, context, aggregate, host):
        self.db.aggregate_host_delete(context.elevated(),
                aggregate['id'], host)

    @rpc_common.client_exceptions(exception.AggregateNotFound)
    def aggregate_get(self, context, aggregate_id):
        aggregate = self.db.aggregate_get(context.elevated(), aggregate_id)
        return jsonutils.to_primitive(aggregate)

    def aggregate_get_by_host(self, context, host, key=None):
        aggregates = self.db.aggregate_get_by_host(context.elevated(),
                                                   host, key)
        return jsonutils.to_primitive(aggregates)

    def aggregate_metadata_add(self, context, aggregate, metadata,
                               set_delete=False):
        new_metadata = self.db.aggregate_metadata_add(context.elevated(),
                                                      aggregate['id'],
                                                      metadata, set_delete)
        return jsonutils.to_primitive(new_metadata)

    @rpc_common.client_exceptions(exception.AggregateMetadataNotFound)
    def aggregate_metadata_delete(self, context, aggregate, key):
        self.db.aggregate_metadata_delete(context.elevated(),
                                          aggregate['id'], key)

    def aggregate_metadata_get_by_host(self, context, host,
                                       key='availability_zone'):
        result = self.db.aggregate_metadata_get_by_host(context, host, key)
        return jsonutils.to_primitive(result)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in=None, bw_out=None,
                        last_ctr_in=None, last_ctr_out=None,
                        last_refreshed=None):
        if [bw_in, bw_out, last_ctr_in, last_ctr_out].count(None) != 4:
            self.db.bw_usage_update(context, uuid, mac, start_period,
                                    bw_in, bw_out, last_ctr_in, last_ctr_out,
                                    last_refreshed)
        usage = self.db.bw_usage_get(context, uuid, start_period, mac)
        return jsonutils.to_primitive(usage)

    # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
    # deprecated in favor of the method in the base API.
    def get_backdoor_port(self, context):
        return self.backdoor_port

    def security_group_get_by_instance(self, context, instance):
        group = self.db.security_group_get_by_instance(context,
                                                       instance['id'])
        return jsonutils.to_primitive(group)

    def security_group_rule_get_by_security_group(self, context, secgroup):
        rules = self.db.security_group_rule_get_by_security_group(
            context, secgroup['id'])
        return jsonutils.to_primitive(rules, max_depth=4)

    def provider_fw_rule_get_all(self, context):
        rules = self.db.provider_fw_rule_get_all(context)
        return jsonutils.to_primitive(rules)

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        info = self.db.agent_build_get_by_triple(context, hypervisor, os,
                                                 architecture)
        return jsonutils.to_primitive(info)

    def block_device_mapping_update_or_create(self, context, values,
                                              create=None):
        if create is None:
            self.db.block_device_mapping_update_or_create(context, values)
        elif create is True:
            self.db.block_device_mapping_create(context, values)
        else:
            self.db.block_device_mapping_update(context, values['id'], values)

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy=True):
        bdms = self.db.block_device_mapping_get_all_by_instance(
            context, instance['uuid'])
        if legacy:
            bdms = block_device.legacy_mapping(bdms)
        return jsonutils.to_primitive(bdms)

    def block_device_mapping_destroy(self, context, bdms=None,
                                     instance=None, volume_id=None,
                                     device_name=None):
        if bdms is not None:
            for bdm in bdms:
                self.db.block_device_mapping_destroy(context, bdm['id'])
        elif instance is not None and volume_id is not None:
            self.db.block_device_mapping_destroy_by_instance_and_volume(
                context, instance['uuid'], volume_id)
        elif instance is not None and device_name is not None:
            self.db.block_device_mapping_destroy_by_instance_and_device(
                context, instance['uuid'], device_name)
        else:
            # NOTE(danms): This shouldn't happen
            raise exception.Invalid(_("Invalid block_device_mapping_destroy"
                                      " invocation"))

    def instance_get_all_by_filters(self, context, filters, sort_key,
                                    sort_dir, columns_to_join=None):
        result = self.db.instance_get_all_by_filters(
            context, filters, sort_key, sort_dir,
            columns_to_join=columns_to_join)
        return jsonutils.to_primitive(result)

    # NOTE(hanlind): This method can be removed in v2.0 of the RPC API.
    def instance_get_all_hung_in_rebooting(self, context, timeout):
        result = self.db.instance_get_all_hung_in_rebooting(context, timeout)
        return jsonutils.to_primitive(result)

    def instance_get_active_by_window(self, context, begin, end=None,
                                      project_id=None, host=None):
        # Unused, but cannot remove until major RPC version bump
        result = self.db.instance_get_active_by_window(context, begin, end,
                                                       project_id, host)
        return jsonutils.to_primitive(result)

    def instance_get_active_by_window_joined(self, context, begin, end=None,
                                             project_id=None, host=None):
        result = self.db.instance_get_active_by_window_joined(
            context, begin, end, project_id, host)
        return jsonutils.to_primitive(result)

    def instance_destroy(self, context, instance):
        self.db.instance_destroy(context, instance['uuid'])

    def instance_info_cache_delete(self, context, instance):
        self.db.instance_info_cache_delete(context, instance['uuid'])

    def instance_info_cache_update(self, context, instance, values):
        self.db.instance_info_cache_update(context, instance['uuid'],
                                           values)

    def instance_type_get(self, context, instance_type_id):
        result = self.db.instance_type_get(context, instance_type_id)
        return jsonutils.to_primitive(result)

    def instance_fault_create(self, context, values):
        result = self.db.instance_fault_create(context, values)
        return jsonutils.to_primitive(result)

    # NOTE(kerrin): This method can be removed in v2.0 of the RPC API.
    def vol_get_usage_by_time(self, context, start_time):
        result = self.db.vol_get_usage_by_time(context, start_time)
        return jsonutils.to_primitive(result)

    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed=None,
                         update_totals=False):
        # The session object is needed here, as the vol_usage object returned
        # needs to bound to it in order to refresh its data
        session = db_session.get_session()
        vol_usage = self.db.vol_usage_update(context, vol_id,
                                             rd_req, rd_bytes,
                                             wr_req, wr_bytes,
                                             instance['uuid'],
                                             instance['project_id'],
                                             instance['user_id'],
                                             instance['availability_zone'],
                                             last_refreshed, update_totals,
                                             session)

        # We have just updated the database, so send the notification now
        notifier.notify(context, 'conductor.%s' % self.host, 'volume.usage',
                        notifier.INFO,
                        compute_utils.usage_volume_info(vol_usage))

    @rpc_common.client_exceptions(exception.ComputeHostNotFound,
                                  exception.HostBinaryNotFound)
    def service_get_all_by(self, context, topic=None, host=None, binary=None):
        if not any((topic, host, binary)):
            result = self.db.service_get_all(context)
        elif all((topic, host)):
            if topic == 'compute':
                result = self.db.service_get_by_compute_host(context, host)
                # FIXME(comstud) Potentially remove this on bump to v2.0
                result = [result]
            else:
                result = self.db.service_get_by_host_and_topic(context,
                                                               host, topic)
        elif all((host, binary)):
            result = self.db.service_get_by_args(context, host, binary)
        elif topic:
            result = self.db.service_get_all_by_topic(context, topic)
        elif host:
            result = self.db.service_get_all_by_host(context, host)

        return jsonutils.to_primitive(result)

    def action_event_start(self, context, values):
        evt = self.db.action_event_start(context, values)
        return jsonutils.to_primitive(evt)

    def action_event_finish(self, context, values):
        evt = self.db.action_event_finish(context, values)
        return jsonutils.to_primitive(evt)

    def service_create(self, context, values):
        svc = self.db.service_create(context, values)
        return jsonutils.to_primitive(svc)

    @rpc_common.client_exceptions(exception.ServiceNotFound)
    def service_destroy(self, context, service_id):
        self.db.service_destroy(context, service_id)

    def compute_node_create(self, context, values):
        result = self.db.compute_node_create(context, values)
        return jsonutils.to_primitive(result)

    def compute_node_update(self, context, node, values, prune_stats=False):
        result = self.db.compute_node_update(context, node['id'], values,
                                             prune_stats)
        return jsonutils.to_primitive(result)

    def compute_node_delete(self, context, node):
        result = self.db.compute_node_delete(context, node['id'])
        return jsonutils.to_primitive(result)

    @rpc_common.client_exceptions(exception.ServiceNotFound)
    def service_update(self, context, service, values):
        svc = self.db.service_update(context, service['id'], values)
        return jsonutils.to_primitive(svc)

    def task_log_get(self, context, task_name, begin, end, host, state=None):
        result = self.db.task_log_get(context, task_name, begin, end, host,
                                      state)
        return jsonutils.to_primitive(result)

    def task_log_begin_task(self, context, task_name, begin, end, host,
                            task_items=None, message=None):
        result = self.db.task_log_begin_task(context.elevated(), task_name,
                                             begin, end, host, task_items,
                                             message)
        return jsonutils.to_primitive(result)

    def task_log_end_task(self, context, task_name, begin, end, host,
                          errors, message=None):
        result = self.db.task_log_end_task(context.elevated(), task_name,
                                           begin, end, host, errors, message)
        return jsonutils.to_primitive(result)

    def notify_usage_exists(self, context, instance, current_period=False,
                            ignore_missing_network_data=True,
                            system_metadata=None, extra_usage_info=None):
        compute_utils.notify_usage_exists(context, instance, current_period,
                                          ignore_missing_network_data,
                                          system_metadata, extra_usage_info)

    def security_groups_trigger_handler(self, context, event, args):
        self.security_group_api.trigger_handler(event, context, *args)

    def security_groups_trigger_members_refresh(self, context, group_ids):
        self.security_group_api.trigger_members_refresh(context, group_ids)

    def network_migrate_instance_start(self, context, instance, migration):
        self.network_api.migrate_instance_start(context, instance, migration)

    def network_migrate_instance_finish(self, context, instance, migration):
        self.network_api.migrate_instance_finish(context, instance, migration)

    def quota_commit(self, context, reservations, project_id=None):
        quota.QUOTAS.commit(context, reservations, project_id=project_id)

    def quota_rollback(self, context, reservations, project_id=None):
        quota.QUOTAS.rollback(context, reservations, project_id=project_id)

    def get_ec2_ids(self, context, instance):
        ec2_ids = {}

        ec2_ids['instance-id'] = ec2utils.id_to_ec2_inst_id(instance['uuid'])
        ec2_ids['ami-id'] = ec2utils.glance_id_to_ec2_id(context,
                                                         instance['image_ref'])
        for image_type in ['kernel', 'ramdisk']:
            if '%s_id' % image_type in instance:
                image_id = instance['%s_id' % image_type]
                ec2_image_type = ec2utils.image_type(image_type)
                ec2_id = ec2utils.glance_id_to_ec2_id(context, image_id,
                                                      ec2_image_type)
                ec2_ids['%s-id' % image_type] = ec2_id

        return ec2_ids

    def compute_stop(self, context, instance, do_cast=True):
        self.compute_api.stop(context, instance, do_cast)

    def compute_confirm_resize(self, context, instance, migration_ref):
        self.compute_api.confirm_resize(context, instance, migration_ref)

    def compute_unrescue(self, context, instance):
        self.compute_api.unrescue(context, instance)

    def object_class_action(self, context, objname, objmethod,
                            objver, args, kwargs):
        """Perform a classmethod action on an object."""
        objclass = nova_object.NovaObject.obj_class_from_name(objname,
                                                              objver)
        return getattr(objclass, objmethod)(context, *args, **kwargs)

    def object_action(self, context, objinst, objmethod, args, kwargs):
        """Perform an action on an object."""
        oldobj = copy.copy(objinst)
        result = getattr(objinst, objmethod)(context, *args, **kwargs)
        updates = dict()
        # NOTE(danms): Diff the object with the one passed to us and
        # generate a list of changes to forward back
        for field in objinst.fields:
            if not hasattr(objinst, nova_object.get_attrname(field)):
                # Avoid demand-loading anything
                continue
            if oldobj[field] != objinst[field]:
                updates[field] = objinst._attr_to_primitive(field)
        # This is safe since a field named this would conflict with the
        # method anyway
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result


class ComputeTaskManager(object):
    """Namespace for compute methods.

    This class presents an rpc API for nova-conductor under the 'compute_task'
    namespace.  The methods here are compute operations that are invoked
    by the API service.  These methods see the operation to completion, which
    may involve coordinating activities on multiple compute nodes.
    """

    RPC_API_NAMESPACE = 'compute_task'
    RPC_API_VERSION = '1.2'

    def __init__(self):
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()

    @rpc_common.client_exceptions(exception.NoValidHost,
                                  exception.ComputeServiceUnavailable,
                                  exception.InvalidHypervisorType,
                                  exception.UnableToMigrateToSelf,
                                  exception.DestinationHypervisorTooOld,
                                  exception.InvalidLocalStorage,
                                  exception.InvalidSharedStorage,
                                  exception.MigrationPreCheckError)
    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
                  flavor, block_migration, disk_over_commit):
        if not live or rebuild or (flavor != None):
            raise NotImplementedError()

        destination = scheduler_hint.get("host")
        self.scheduler_rpcapi.live_migration(context, block_migration,
                disk_over_commit, instance, destination)

    def build_instances(self, context, instances, image, filter_properties,
            admin_password, injected_files, requested_networks,
            security_groups, block_device_mapping):
        request_spec = scheduler_utils.build_request_spec(image, instances)
        # NOTE(alaski): For compatibility until a new scheduler method is used.
        request_spec.update({'block_device_mapping': block_device_mapping,
                             'security_group': security_groups})
        self.scheduler_rpcapi.run_instance(context, request_spec=request_spec,
                admin_password=admin_password, injected_files=injected_files,
                requested_networks=requested_networks, is_first_time=True,
                filter_properties=filter_properties)
