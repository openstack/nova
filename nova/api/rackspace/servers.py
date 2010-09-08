# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from nova import rpc
from nova.api.rackspace import base

# FIXME(vish): convert from old usage of instance directory

class Controller(base.Controller):
    entity_name = 'servers'

    def index(self, **kwargs):
        instances = []
        for inst in compute.InstanceDirectory().all:
            instances.append(instance_details(inst))

    def show(self, **kwargs):
        instance_id = kwargs['id']
        return compute.InstanceDirectory().get(instance_id)

    def delete(self, **kwargs):
        instance_id = kwargs['id']
        instance = compute.InstanceDirectory().get(instance_id)
        if not instance:
            raise ServerNotFound("The requested server was not found")
        instance.destroy()
        return True

    def create(self, **kwargs):
        inst = self.build_server_instance(kwargs['server'])
        rpc.cast(
            FLAGS.compute_topic, {
                "method": "run_instance",
                "args": {"instance_id": inst.instance_id}})

    def update(self, **kwargs):
        instance_id = kwargs['id']
        instance = compute.InstanceDirectory().get(instance_id)
        if not instance:
            raise ServerNotFound("The requested server was not found")
        instance.update(kwargs['server'])
        instance.save()

    def build_server_instance(self, env):
        """Build instance data structure and save it to the data store."""
        reservation = utils.generate_uid('r')
        ltime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        inst = self.instdir.new()
        inst['name'] = env['server']['name']
        inst['image_id'] = env['server']['imageId']
        inst['instance_type'] = env['server']['flavorId']
        inst['user_id'] = env['user']['id']
        inst['project_id'] = env['project']['id']
        inst['reservation_id'] = reservation
        inst['launch_time'] = ltime
        inst['mac_address'] = utils.generate_mac()
        address = self.network.allocate_ip(
                    inst['user_id'],
                    inst['project_id'],
                    mac=inst['mac_address'])
        inst['private_dns_name'] = str(address)
        inst['bridge_name'] = network.BridgedNetwork.get_network_for_project(
                                inst['user_id'],
                                inst['project_id'],
                                'default')['bridge_name']
        # key_data, key_name, ami_launch_index
        # TODO(todd): key data or root password
        inst.save()
        return inst
