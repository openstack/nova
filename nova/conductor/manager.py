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

"""Handles database requests from other nova services"""

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
    """Mission: TBD"""

    RPC_API_VERSION = '1.11'

    def __init__(self, *args, **kwargs):
        super(ConductorManager, self).__init__(service_name='conductor',
                                               *args, **kwargs)

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
    def instance_get_by_uuid(self, context, instance_uuid):
        return jsonutils.to_primitive(
            self.db.instance_get_by_uuid(context, instance_uuid))

    def instance_get_all_by_host(self, context, host):
        return jsonutils.to_primitive(
            self.db.instance_get_all_by_host(context.elevated(), host))

    @rpc_common.client_exceptions(exception.MigrationNotFound)
    def migration_get(self, context, migration_id):
        migration_ref = self.db.migration_get(context.elevated(),
                                              migration_id)
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
