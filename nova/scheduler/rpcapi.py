# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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

"""
Client side of the scheduler manager RPC API.
"""

from nova import flags
import nova.openstack.common.rpc.proxy


FLAGS = flags.FLAGS


class SchedulerAPI(nova.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the scheduler rpc API.

    API version history:

        1.0 - Initial version.
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(SchedulerAPI, self).__init__(topic=FLAGS.scheduler_topic,
                default_version=self.BASE_RPC_API_VERSION)

    def run_instance(self, ctxt, topic, request_spec, admin_password,
            injected_files, requested_networks, is_first_time,
            filter_properties, reservations, call=True):
        rpc_method = self.call if call else self.cast
        return rpc_method(ctxt, self.make_msg('run_instance', topic=topic,
                request_spec=request_spec, admin_password=admin_password,
                injected_files=injected_files,
                requested_networks=requested_networks,
                is_first_time=is_first_time,
                filter_properties=filter_properties,
                reservations=reservations))

    def prep_resize(self, ctxt, topic, instance_uuid, instance_type_id, image,
            update_db, request_spec, filter_properties):
        self.cast(ctxt, self.make_msg('prep_resize', topic=topic,
                instance_uuid=instance_uuid, instance_type_id=instance_type_id,
                image=image, update_db=update_db, request_spec=request_spec,
                filter_properties=filter_properties))

    def show_host_resources(self, ctxt, host):
        return self.call(ctxt, self.make_msg('show_host_resources', host=host))

    def live_migration(self, ctxt, block_migration, disk_over_commit,
            instance_id, dest, topic):
        # NOTE(comstud): Call vs cast so we can get exceptions back, otherwise
        # this call in the scheduler driver doesn't return anything.
        return self.call(ctxt, self.make_msg('live_migration',
                block_migration=block_migration,
                disk_over_commit=disk_over_commit, instance_id=instance_id,
                dest=dest, topic=topic))

    def update_service_capabilities(self, ctxt, service_name, host,
            capabilities):
        self.fanout_cast(ctxt, self.make_msg('update_service_capabilities',
                service_name=service_name, host=host,
                capabilities=capabilities))
