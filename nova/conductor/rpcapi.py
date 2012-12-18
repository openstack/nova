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

"""Client side of the conductor RPC API"""

from nova.openstack.common import cfg
from nova.openstack.common import jsonutils
import nova.openstack.common.rpc.proxy

CONF = cfg.CONF


class ConductorAPI(nova.openstack.common.rpc.proxy.RpcProxy):
    """Client side of the conductor RPC API

    API version history:

    1.0 - Initial version.
    1.1 - Added migration_update
    1.2 - Added instance_get_by_uuid and instance_get_all_by_host
    1.3 - Added aggregate_host_add and aggregate_host_delete
    1.4 - Added migration_get
    1.5 - Added bw_usage_update
    1.6 - Added get_backdoor_port()
    1.7 - Added aggregate_get_by_host, aggregate_metadata_add,
          and aggregate_metadata_delete
    1.8 - Added security_group_get_by_instance and
          security_group_rule_get_by_security_group
    1.9 - Added provider_fw_rule_get_all
    1.10 - Added agent_build_get_by_triple
    1.11 - Added aggregate_get
    """

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(ConductorAPI, self).__init__(
            topic=CONF.conductor.topic,
            default_version=self.BASE_RPC_API_VERSION)

    def instance_update(self, context, instance_uuid, updates):
        updates_p = jsonutils.to_primitive(updates)
        return self.call(context,
                         self.make_msg('instance_update',
                                       instance_uuid=instance_uuid,
                                       updates=updates_p))

    def instance_get_by_uuid(self, context, instance_uuid):
        msg = self.make_msg('instance_get_by_uuid',
                            instance_uuid=instance_uuid)
        return self.call(context, msg, version='1.2')

    def instance_get_all_by_host(self, context, host):
        msg = self.make_msg('instance_get_all_by_host', host=host)
        return self.call(context, msg, version='1.2')

    def migration_get(self, context, migration_id):
        msg = self.make_msg('migration_get', migration_id=migration_id)
        return self.call(context, msg, version='1.4')

    def migration_update(self, context, migration, status):
        migration_p = jsonutils.to_primitive(migration)
        msg = self.make_msg('migration_update', migration=migration_p,
                            status=status)
        return self.call(context, msg, version='1.1')

    def aggregate_host_add(self, context, aggregate, host):
        aggregate_p = jsonutils.to_primitive(aggregate)
        msg = self.make_msg('aggregate_host_add', aggregate=aggregate_p,
                            host=host)
        return self.call(context, msg, version='1.3')

    def aggregate_host_delete(self, context, aggregate, host):
        aggregate_p = jsonutils.to_primitive(aggregate)
        msg = self.make_msg('aggregate_host_delete', aggregate=aggregate_p,
                            host=host)
        return self.call(context, msg, version='1.3')

    def aggregate_get(self, context, aggregate_id):
        msg = self.make_msg('aggregate_get', aggregate_id=aggregate_id)
        return self.call(context, msg, version='1.11')

    def aggregate_get_by_host(self, context, host, key=None):
        msg = self.make_msg('aggregate_get_by_host', host=host, key=key)
        return self.call(context, msg, version='1.7')

    def aggregate_metadata_add(self, context, aggregate, metadata,
                               set_delete=False):
        aggregate_p = jsonutils.to_primitive(aggregate)
        msg = self.make_msg('aggregate_metadata_add', aggregate=aggregate_p,
                            metadata=metadata,
                            set_delete=set_delete)
        return self.call(context, msg, version='1.7')

    def aggregate_metadata_delete(self, context, aggregate, key):
        aggregate_p = jsonutils.to_primitive(aggregate)
        msg = self.make_msg('aggregate_metadata_delete', aggregate=aggregate_p,
                            key=key)
        return self.call(context, msg, version='1.7')

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in=None, bw_out=None,
                        last_ctr_in=None, last_ctr_out=None,
                        last_refreshed=None):
        msg = self.make_msg('bw_usage_update',
                            uuid=uuid, mac=mac, start_period=start_period,
                            bw_in=bw_in, bw_out=bw_out,
                            last_ctr_in=last_ctr_in, last_ctr_out=last_ctr_out,
                            last_refreshed=last_refreshed)
        return self.call(context, msg, version='1.5')

    def get_backdoor_port(self, context):
        msg = self.make_msg('get_backdoor_port')
        return self.call(context, msg, version='1.6')

    def security_group_get_by_instance(self, context, instance):
        instance_p = jsonutils.to_primitive(instance)
        msg = self.make_msg('security_group_get_by_instance',
                            instance=instance_p)
        return self.call(context, msg, version='1.8')

    def security_group_rule_get_by_security_group(self, context, secgroup):
        secgroup_p = jsonutils.to_primitive(secgroup)
        msg = self.make_msg('security_group_rule_get_by_security_group',
                            secgroup=secgroup_p)
        return self.call(context, msg, version='1.8')

    def provider_fw_rule_get_all(self, context):
        msg = self.make_msg('provider_fw_rule_get_all')
        return self.call(context, msg, version='1.9')

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        msg = self.make_msg('agent_build_get_by_triple',
                            hypervisor=hypervisor, os=os,
                            architecture=architecture)
        return self.call(context, msg, version='1.10')
