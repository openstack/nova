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
    1.12 - Added block_device_mapping_update_or_create
    1.13 - Added block_device_mapping_get_all_by_instance
    1.14 - Added block_device_mapping_destroy
    1.15 - Added instance_get_all_by_filters and
           instance_get_all_hung_in_rebooting and
           instance_get_active_by_window
           Deprecated instance_get_all_by_host
    1.16 - Added instance_destroy
    1.17 - Added instance_info_cache_delete
    1.18 - Added instance_type_get
    1.19 - Added vol_get_usage_by_time and vol_usage_update
    1.20 - Added migration_get_unconfirmed_by_dest_compute
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

    def migration_get(self, context, migration_id):
        msg = self.make_msg('migration_get', migration_id=migration_id)
        return self.call(context, msg, version='1.4')

    def migration_get_unconfirmed_by_dest_compute(self, context,
                                                  confirm_window,
                                                  dest_compute):
        msg = self.make_msg('migration_get_unconfirmed_by_dest_compute',
                            confirm_window=confirm_window,
                            dest_compute=dest_compute)
        return self.call(context, msg, version='1.20')

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

    def block_device_mapping_update_or_create(self, context, values,
                                              create=None):
        msg = self.make_msg('block_device_mapping_update_or_create',
                            values=values, create=create)
        return self.call(context, msg, version='1.12')

    def block_device_mapping_get_all_by_instance(self, context, instance):
        instance_p = jsonutils.to_primitive(instance)
        msg = self.make_msg('block_device_mapping_get_all_by_instance',
                            instance=instance_p)
        return self.call(context, msg, version='1.13')

    def block_device_mapping_destroy(self, context, bdms=None,
                                     instance=None, volume_id=None,
                                     device_name=None):
        bdms_p = jsonutils.to_primitive(bdms)
        instance_p = jsonutils.to_primitive(instance)
        msg = self.make_msg('block_device_mapping_destroy',
                            bdms=bdms_p,
                            instance=instance_p, volume_id=volume_id,
                            device_name=device_name)
        return self.call(context, msg, version='1.14')

    def instance_get_all_by_filters(self, context, filters, sort_key,
                                    sort_dir):
        msg = self.make_msg('instance_get_all_by_filters',
                            filters=filters, sort_key=sort_key,
                            sort_dir=sort_dir)
        return self.call(context, msg, version='1.15')

    def instance_get_all_hung_in_rebooting(self, context, timeout):
        msg = self.make_msg('instance_get_all_hung_in_rebooting',
                            timeout=timeout)
        return self.call(context, msg, version='1.15')

    def instance_get_active_by_window(self, context, begin, end=None,
                                      project_id=None, host=None):
        msg = self.make_msg('instance_get_active_by_window',
                            begin=begin, end=end, project_id=project_id,
                            host=host)
        return self.call(context, msg, version='1.15')

    def instance_destroy(self, context, instance):
        instance_p = jsonutils.to_primitive(instance)
        msg = self.make_msg('instance_destroy', instance=instance_p)
        self.call(context, msg, version='1.16')

    def instance_info_cache_delete(self, context, instance):
        instance_p = jsonutils.to_primitive(instance)
        msg = self.make_msg('instance_info_cache_delete', instance=instance_p)
        self.call(context, msg, version='1.17')

    def instance_type_get(self, context, instance_type_id):
        msg = self.make_msg('instance_type_get',
                            instance_type_id=instance_type_id)
        return self.call(context, msg, version='1.18')

    def vol_get_usage_by_time(self, context, start_time):
        start_time_p = jsonutils.to_primitive(start_time)
        msg = self.make_msg('vol_get_usage_by_time', start_time=start_time_p)
        return self.call(context, msg, version='1.19')

    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed=None,
                         update_totals=False):
        instance_p = jsonutils.to_primitive(instance)
        msg = self.make_msg('vol_usage_update', vol_id=vol_id, rd_req=rd_req,
                            rd_bytes=rd_bytes, wr_req=wr_req,
                            wr_bytes=wr_bytes,
                            instance=instance_p, last_refreshed=last_refreshed,
                            update_totals=update_totals)
        return self.call(context, msg, version='1.19')
