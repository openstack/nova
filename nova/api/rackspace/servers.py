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
import nova.image.service
from nova import wsgi
from nova import db
from nova import flags
from nova import rpc
from nova import utils
from nova import compute
from nova import flags
from nova.compute import power_state
from nova.api.rackspace import _id_translator
from webob import exc

FLAGS = flags.FLAGS

class Controller(wsgi.Controller):

    _power_mapping = { 
        power_state.NOSTATE:  'build', 
        power_state.RUNNING:  'active',
        power_state.BLOCKED:  'active',
        power_state.PAUSED:   'suspended',
        power_state.SHUTDOWN: 'active',
        power_state.SHUTOFF:  'active',
        power_state.CRASHED:  'error'
    }

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "server": [ "id", "imageId", "name", "flavorId", "hostId", 
                            "status", "progress", "progress" ]
            }
        }
    }

    def __init__(self, db_driver=None):
        if not db_driver:
            db_driver = FLAGS.db_driver
        self.db = utils.import_object(db_driver)

    def index(self, req):
        instance_list = self.db.instance_get_all(None)
        res = [self._entity_inst(inst)['server'] for inst in instance_list]
        return self._entity_list(res)

    def detail(self, req):
        res = [self._entity_detail(inst)['server'] for inst in 
                self.db.instance_get_all(None)]
        return self._entity_list(res)

    def show(self, req, id):
        user = req.environ['nova.context']['user']
        inst = self.db.instance_get(None, id)
        if inst:
            return self._entity_detail(inst)
        raise exc.HTTPNotFound()

    def delete(self, req, id):
        instance = self.db.instance_get(None, id)
        if not instance:
            return exc.HTTPNotFound()
        self.db.instance_destroy(None, id)
        return exc.HTTPAccepted()

    def create(self, req):
        inst = self._build_server_instance(req)
        rpc.cast(
            FLAGS.compute_topic, {
                "method": "run_instance",
                "args": {"instance_id": inst.id}})
        return _entity_inst(inst)

    def update(self, req, id):
        instance = self.db.instance_get(None, id)
        if not instance:
            return exc.HTTPNotFound()

        attrs = req.environ['nova.context'].get('model_attributes', None)
        if attrs:
            self.db.instance_update(None, id, attrs)
        return exc.HTTPNoContent()

    def action(self, req, id):
        """ multi-purpose method used to reboot, rebuild, and 
        resize a server """
        return {}

    def _id_translator(self):
        service = nova.image.service.ImageService.load()
        return _id_translator.RackspaceAPIIdTranslator(
            "image", self.service.__class__.__name__)

    def _build_server_instance(self, req):
        """Build instance data structure and save it to the data store."""
        ltime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        inst = {}

        image_id = env['server']['imageId']
        opaque_id = self._id_translator.from_rs_id(image_id)

        inst['name'] = env['server']['name']
        inst['image_id'] = opaque_id
        inst['instance_type'] = env['server']['flavorId']
        inst['user_id'] = env['user']['id']

        inst['launch_time'] = ltime
        inst['mac_address'] = utils.generate_mac()

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

        self.db.instance_create(None, inst)
        return inst

    def _filter_params(self, inst_dict):
        pass

    def _entity_list(self, entities):
        return dict(servers=entities)

    def _entity_detail(self, inst):
        """ Maps everything to Rackspace-like attributes for return"""
        inst_dict = {}

        mapped_keys = dict(status='state', imageId='image_id', 
            flavorId='instance_type', name='name', id='id')

        for k,v in mapped_keys.iteritems():
            inst_dict[k] = inst[v]

        inst_dict['status'] = Controller._power_mapping[inst_dict['status']]
        inst_dict['addresses'] = dict(public=[], private=[])
        inst_dict['metadata'] = {}
        inst_dict['hostId'] = ''

        return dict(server=inst_dict)

    def _entity_inst(self, inst):
        """ Filters all model attributes save for id and name """
        return dict(server=dict(id=inst['id'], name=inst['name']))
