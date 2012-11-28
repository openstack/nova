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
