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
import time

from nova import db
from nova import flags
from nova import rpc
from nova import utils
from nova import compute
from nova.api.rackspace import base
from webob import exc
from nova import flags

FLAGS = flags.FLAGS

class Controller(base.Controller):
    _serialization_metadata = {
        'application/xml': {
            "plurals": "servers",
            "attributes": {
                "server": [ "id", "imageId", "name", "flavorId", "hostId", 
                            "status", "progress", "addresses", "metadata", 
                            "progress" ]
            }
        }
    }

    def __init__(self):
        self.instdir = compute.InstanceDirectory()

    def index(self, req):
        allowed_keys = [ 'id', 'name']
        return [_entity_inst(inst, allowed_keys) for inst in instdir.all]

    def detail(self, req):
        return [_entity_inst(inst) for inst in instdir.all]

    def show(self, req, id):
        inst = self.instdir.get(id)
        if inst:
            return _entity_inst(inst)
        raise exc.HTTPNotFound()

    def delete(self, req, id):
        instance = self.instdir.get(id)

        if not instance:
            return exc.HTTPNotFound()
        instance.destroy()
        return exc.HTTPAccepted()

    def create(self, req):
        inst = self._build_server_instance(req)
        rpc.cast(
            FLAGS.compute_topic, {
                "method": "run_instance",
                "args": {"instance_id": inst.instance_id}})
        return _entity_inst(inst)

    def update(self, req, id):
        instance = self.instdir.get(instance_id)
        if not instance:
            return exc.HTTPNotFound()
        instance.update(kwargs['server'])
        instance.save()
        return exc.HTTPNoContent()

    def _build_server_instance(self, req):
        """Build instance data structure and save it to the data store."""
        ltime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        inst = {}
        inst['name'] = env['server']['name']
        inst['image_id'] = env['server']['imageId']
        inst['instance_type'] = env['server']['flavorId']
        inst['user_id'] = env['user']['id']

        inst['launch_time'] = ltime
        inst['mac_address'] = utils.generate_mac()

        # TODO(dietz) Do we need any of these?
        inst['project_id'] = env['project']['id']
        inst['reservation_id'] = reservation
        reservation = utils.generate_uid('r')

        address = self.network.allocate_ip(
                    inst['user_id'],
                    inst['project_id'],
                    mac=inst['mac_address'])
        inst['private_dns_name'] = str(address)
        inst['bridge_name'] = network.BridgedNetwork.get_network_for_project(
                                inst['user_id'],
                                inst['project_id'],
                                'default')['bridge_name']

        inst.save()
        return _entity_inst(inst)

    def _entity_inst(self, inst, allowed_keys=None):
        """ Maps everything to Rackspace-like attributes for return"""

        translated_keys = dict(metadata={}, status=state_description,
            id=instance_id, imageId=image_id, flavorId=instance_type,)

        for k,v in translated_keys.iteritems():
            inst[k] = inst[v]

        filtered_keys = ['instance_id', 'state_description', 'state',
            'reservation_id', 'project_id', 'launch_time',
            'bridge_name', 'mac_address', 'user_id']

        for key in filtered_keys:
            del inst[key]

        if allowed_keys:
            for key in inst.keys():
                if key not in allowed_keys:
                    del inst[key]

        return dict(server=inst)
