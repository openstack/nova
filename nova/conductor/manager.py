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

from nova import exception
from nova import manager
from nova import notifications
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils


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
                   ]

# Fields that we want to convert back into a datetime object.
datetime_fields = ['launched_at', 'terminated_at']


class ConductorManager(manager.SchedulerDependentManager):
    """Mission: TBD."""

    RPC_API_VERSION = '1.37'

    def __init__(self, *args, **kwargs):
        super(ConductorManager, self).__init__(service_name='conductor',
                                               *args, **kwargs)

    def ping(self, context, arg):
        return jsonutils.to_primitive({'service': 'conductor', 'arg': arg})

    @rpc_common.client_exceptions(KeyError, ValueError,
                                  exception.InvalidUUID,
                                  exception.InstanceNotFound,
                                  exception.UnexpectedTaskStateError)
    def instance_update(self, context, instance_uuid, updates):
        for key, value in updates.iteritems():
            if key not in allowed_updates:
                LOG.error(_("Instance update attempted for "
                            "'%(key)s' on %(instance_uuid)s") % locals())
                raise KeyError("unexpected update keyword '%s'" % key)
            if key in datetime_fields and isinstance(value, basestring):
                updates[key] = timeutils.parse_strtime(value)

        old_ref, instance_ref = self.db.instance_update_and_get_original(
            context, instance_uuid, updates)
        notifications.send_update(context, old_ref, instance_ref)
        return jsonutils.to_primitive(instance_ref)

    @rpc_common.client_exceptions(exception.InstanceNotFound)
    def instance_get(self, context, instance_id):
        return jsonutils.to_primitive(
            self.db.instance_get(context, instance_id))

    @rpc_common.client_exceptions(exception.InstanceNotFound)
    def instance_get_by_uuid(self, context, instance_uuid):
        return jsonutils.to_primitive(
            self.db.instance_get_by_uuid(context, instance_uuid))

    def instance_get_all(self, context):
        return jsonutils.to_primitive(self.db.instance_get_all(context))

    def instance_get_all_by_host(self, context, host, node=None):
        if node is not None:
            result = self.db.instance_get_all_by_host_and_node(
                context.elevated(), host, node)
        else:
            result = self.db.instance_get_all_by_host(context.elevated(), host)
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

    def get_backdoor_port(self, context):
        return self.backdoor_port

    def security_group_get_by_instance(self, context, instance):
        group = self.db.security_group_get_by_instance(context,
                                                       instance['id'])
        return jsonutils.to_primitive(group)

    def security_group_rule_get_by_security_group(self, context, secgroup):
        rule = self.db.security_group_rule_get_by_security_group(
            context, secgroup['id'])
        return jsonutils.to_primitive(rule)

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

    def block_device_mapping_get_all_by_instance(self, context, instance):
        bdms = self.db.block_device_mapping_get_all_by_instance(
            context, instance['uuid'])
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
                                    sort_dir):
        result = self.db.instance_get_all_by_filters(context, filters,
                                                     sort_key, sort_dir)
        return jsonutils.to_primitive(result)

    def instance_get_all_hung_in_rebooting(self, context, timeout):
        result = self.db.instance_get_all_hung_in_rebooting(context, timeout)
        return jsonutils.to_primitive(result)

    def instance_get_active_by_window(self, context, begin, end=None,
                                      project_id=None, host=None):
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

    def vol_get_usage_by_time(self, context, start_time):
        result = self.db.vol_get_usage_by_time(context, start_time)
        return jsonutils.to_primitive(result)

    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed=None,
                         update_totals=False):
        self.db.vol_usage_update(context, vol_id, rd_req, rd_bytes, wr_req,
                                 wr_bytes, instance['uuid'], last_refreshed,
                                 update_totals)

    @rpc_common.client_exceptions(exception.HostBinaryNotFound)
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
