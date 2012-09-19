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
from nova.openstack.common import jsonutils
import nova.openstack.common.rpc.proxy


FLAGS = flags.FLAGS


class SchedulerAPI(nova.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the scheduler rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Changes to prep_resize():
                - remove instance_uuid, add instance
                - remove instance_type_id, add instance_type
                - remove topic, it was unused
        1.2 - Remove topic from run_instance, it was unused
        1.3 - Remove instance_id, add instance to live_migration
        1.4 - Remove update_db from prep_resize
        1.5 - Add reservations argument to prep_resize()
        1.6 - Remove reservations argument to run_instance()
        1.7 - Add create_volume() method, remove topic from live_migration()

        2.0 - Remove 1.x backwards compat
        2.1 - Add image_id to create_volume()
        2.2 - Remove reservations argument to create_volume()
    '''

    #
    # NOTE(russellb): This is the default minimum version that the server
    # (manager) side must implement unless otherwise specified using a version
    # argument to self.call()/cast()/etc. here.  It should be left as X.0 where
    # X is the current major API version (1.0, 2.0, ...).  For more information
    # about rpc API versioning, see the docs in
    # openstack/common/rpc/dispatcher.py.
    #
    BASE_RPC_API_VERSION = '2.0'

    def __init__(self):
        super(SchedulerAPI, self).__init__(topic=FLAGS.scheduler_topic,
                default_version=self.BASE_RPC_API_VERSION)

    def run_instance(self, ctxt, request_spec, admin_password,
            injected_files, requested_networks, is_first_time,
            filter_properties):
        return self.cast(ctxt, self.make_msg('run_instance',
                request_spec=request_spec, admin_password=admin_password,
                injected_files=injected_files,
                requested_networks=requested_networks,
                is_first_time=is_first_time,
                filter_properties=filter_properties))

    def prep_resize(self, ctxt, instance, instance_type, image,
            request_spec, filter_properties, reservations):
        instance_p = jsonutils.to_primitive(instance)
        instance_type_p = jsonutils.to_primitive(instance_type)
        self.cast(ctxt, self.make_msg('prep_resize',
                instance=instance_p, instance_type=instance_type_p,
                image=image, request_spec=request_spec,
                filter_properties=filter_properties,
                reservations=reservations))

    def show_host_resources(self, ctxt, host):
        return self.call(ctxt, self.make_msg('show_host_resources', host=host))

    def live_migration(self, ctxt, block_migration, disk_over_commit,
            instance, dest):
        # NOTE(comstud): Call vs cast so we can get exceptions back, otherwise
        # this call in the scheduler driver doesn't return anything.
        instance_p = jsonutils.to_primitive(instance)
        return self.call(ctxt, self.make_msg('live_migration',
                block_migration=block_migration,
                disk_over_commit=disk_over_commit, instance=instance_p,
                dest=dest))

    def create_volume(self, ctxt, volume_id, snapshot_id, image_id):
        self.cast(ctxt,
                  self.make_msg('create_volume',
                                volume_id=volume_id, snapshot_id=snapshot_id,
                                image_id=image_id),
                  version='2.2')

    def update_service_capabilities(self, ctxt, service_name, host,
            capabilities):
        self.fanout_cast(ctxt, self.make_msg('update_service_capabilities',
                service_name=service_name, host=host,
                capabilities=capabilities))
