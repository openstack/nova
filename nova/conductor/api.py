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

"""Handles all requests to the conductor service"""

from nova.conductor import manager
from nova.conductor import rpcapi
from nova import exception as exc
from nova.openstack.common import cfg

conductor_opts = [
    cfg.BoolOpt('use_local',
                default=False,
                help='Perform nova-conductor operations locally'),
    cfg.StrOpt('topic',
               default='conductor',
               help='the topic conductor nodes listen on'),
    cfg.StrOpt('manager',
               default='nova.conductor.manager.ConductorManager',
               help='full class name for the Manager for conductor'),
]
conductor_group = cfg.OptGroup(name='conductor',
                               title='Conductor Options')
CONF = cfg.CONF
CONF.register_group(conductor_group)
CONF.register_opts(conductor_opts, conductor_group)


class LocalAPI(object):
    """A local version of the conductor API that does database updates
    locally instead of via RPC"""

    def __init__(self):
        self._manager = manager.ConductorManager()

    def instance_update(self, context, instance_uuid, **updates):
        """Perform an instance update in the database"""
        return self._manager.instance_update(context, instance_uuid, updates)

    def instance_get_by_uuid(self, context, instance_uuid):
        return self._manager.instance_get_by_uuid(context, instance_uuid)

    def instance_get_all_by_host(self, context, host):
        return self._manager.instance_get_all_by_host(context, host)

    def migration_get(self, context, migration_id):
        return self._manager.migration_get(context, migration_id)

    def migration_update(self, context, migration, status):
        return self._manager.migration_update(context, migration, status)

    def aggregate_host_add(self, context, aggregate, host):
        return self._manager.aggregate_host_add(context, aggregate, host)

    def aggregate_host_delete(self, context, aggregate, host):
        return self._manager.aggregate_host_delete(context, aggregate, host)

    def bw_usage_get(self, context, uuid, start_period, mac):
        return self._manager.bw_usage_update(context, uuid, mac, start_period)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in, bw_out, last_ctr_in, last_ctr_out,
                        last_refreshed=None):
        return self._manager.bw_usage_update(context, uuid, mac, start_period,
                                             bw_in, bw_out,
                                             last_ctr_in, last_ctr_out,
                                             last_refreshed)

    def get_backdoor_port(self, context, host):
        raise exc.InvalidRequest


class API(object):
    """Conductor API that does updates via RPC to the ConductorManager"""

    def __init__(self):
        self.conductor_rpcapi = rpcapi.ConductorAPI()

    def instance_update(self, context, instance_uuid, **updates):
        """Perform an instance update in the database"""
        return self.conductor_rpcapi.instance_update(context, instance_uuid,
                                                     updates)

    def instance_get_by_uuid(self, context, instance_uuid):
        return self.conductor_rpcapi.instance_get_by_uuid(context,
                                                          instance_uuid)

    def instance_get_all_by_host(self, context, host):
        return self.conductor_rpcapi.instance_get_all_by_host(context, host)

    def migration_get(self, context, migration_id):
        return self.conductor_rpcapi.migration_get(context, migration_id)

    def migration_update(self, context, migration, status):
        return self.conductor_rpcapi.migration_update(context, migration,
                                                      status)

    def aggregate_host_add(self, context, aggregate, host):
        return self.conductor_rpcapi.aggregate_host_add(context, aggregate,
                                                        host)

    def aggregate_host_delete(self, context, aggregate, host):
        return self.conductor_rpcapi.aggregate_host_delete(context, aggregate,
                                                           host)

    def bw_usage_get(self, context, uuid, start_period, mac):
        return self.conductor_rpcapi.bw_usage_update(context, uuid, mac,
                                                     start_period)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in, bw_out, last_ctr_in, last_ctr_out,
                        last_refreshed=None):
        return self.conductor_rpcapi.bw_usage_update(
            context, uuid, mac, start_period,
            bw_in, bw_out, last_ctr_in, last_ctr_out,
            last_refreshed)

    #NOTE(mtreinish): This doesn't work on multiple conductors without any
    # topic calculation in conductor_rpcapi. So the host param isn't used
    # currently.
    def get_backdoor_port(self, context, host):
        return self.conductor_rpcapi.get_backdoor_port(context)
