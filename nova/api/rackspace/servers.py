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

from webob import exc

from nova import flags
from nova import rpc
from nova import utils
from nova import wsgi
from nova.api.rackspace import _id_translator
from nova.compute import power_state
import nova.api.rackspace
import nova.image.service

FLAGS = flags.FLAGS



def translator_instance():
    """ Helper method for initializing the image id translator """
    service = nova.image.service.ImageService.load()
    return _id_translator.RackspaceAPIIdTranslator(
            "image", service.__class__.__name__)

def _filter_params(inst_dict):
    """ Extracts all updatable parameters for a server update request """
    keys = ['name', 'adminPass']
    new_attrs = {}
    for k in keys:
        if inst_dict.has_key(k):
            new_attrs[k] = inst_dict[k]
    return new_attrs

def _entity_list(entities):
    """ Coerces a list of servers into proper dictionary format """
    return dict(servers=entities)

def _entity_detail(inst):
    """ Maps everything to Rackspace-like attributes for return"""
    power_mapping = { 
        power_state.NOSTATE:  'build', 
        power_state.RUNNING:  'active',
        power_state.BLOCKED:  'active',
        power_state.PAUSED:   'suspended',
        power_state.SHUTDOWN: 'active',
        power_state.SHUTOFF:  'active',
        power_state.CRASHED:  'error'
    }
    inst_dict = {}

    mapped_keys = dict(status='state', imageId='image_id', 
        flavorId='instance_type', name='server_name', id='id')

    for k, v in mapped_keys.iteritems():
        inst_dict[k] = inst[v]

    inst_dict['status'] = power_mapping[inst_dict['status']]
    inst_dict['addresses'] = dict(public=[], private=[])
    inst_dict['metadata'] = {}
    inst_dict['hostId'] = ''

    return dict(server=inst_dict)

def _entity_inst(inst):
    """ Filters all model attributes save for id and name """
    return dict(server=dict(id=inst['id'], name=inst['server_name']))

class Controller(wsgi.Controller):
    """ The Server API controller for the Openstack API """
    

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
        self.db_driver = utils.import_object(db_driver)
        super(Controller, self).__init__()

    def index(self, req):
        """ Returns a list of server names and ids for a given user """
        return self._items(req, entity_maker=_entity_inst)

    def detail(self, req):
        """ Returns a list of server details for a given user """
        return self._items(req, entity_maker=_entity_detail)

    def _items(self, req, entity_maker):
        """Returns a list of servers for a given user.

        entity_maker - either _entity_detail or _entity_inst
        """
        user_id = req.environ['nova.context']['user']['id']
        instance_list = self.db_driver.instance_get_all_by_user(None, user_id)
        limited_list = nova.api.rackspace.limited(instance_list, req)
        res = [entity_maker(inst)['server'] for inst in limited_list]
        return _entity_list(res)

    def show(self, req, id):
        """ Returns server details by server id """
        user_id = req.environ['nova.context']['user']['id']
        inst = self.db_driver.instance_get(None, id)
        if inst:
            if inst.user_id == user_id:
                return _entity_detail(inst)
        raise exc.HTTPNotFound()

    def delete(self, req, id):
        """ Destroys a server """
        user_id = req.environ['nova.context']['user']['id']
        instance = self.db_driver.instance_get(None, id)
        if instance and instance['user_id'] == user_id:
            self.db_driver.instance_destroy(None, id)
            return exc.HTTPAccepted()
        return exc.HTTPNotFound()

    def create(self, req):
        """ Creates a new server for a given user """
        if not req.environ.has_key('inst_dict'):
            return exc.HTTPUnprocessableEntity()

        inst = self._build_server_instance(req)

        rpc.cast(
            FLAGS.compute_topic, {
                "method": "run_instance",
                "args": {"instance_id": inst['id']}})
        return _entity_inst(inst)

    def update(self, req, id):
        """ Updates the server name or password """
        if not req.environ.has_key('inst_dict'):
            return exc.HTTPUnprocessableEntity()

        instance = self.db_driver.instance_get(None, id)
        if not instance:
            return exc.HTTPNotFound()

        attrs = req.environ['nova.context'].get('model_attributes', None)
        if attrs:
            self.db_driver.instance_update(None, id, _filter_params(attrs))
        return exc.HTTPNoContent()

    def action(self, req, id):
        """ multi-purpose method used to reboot, rebuild, and 
        resize a server """
        if not req.environ.has_key('inst_dict'):
            return exc.HTTPUnprocessableEntity()

    def _build_server_instance(self, req):
        """Build instance data structure and save it to the data store."""
        ltime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        inst = {}

        env = req.environ['inst_dict']

        image_id = env['server']['imageId']
        opaque_id = translator_instance().from_rs_id(image_id)

        inst['name'] = env['server']['server_name']
        inst['image_id'] = opaque_id
        inst['instance_type'] = env['server']['flavorId']

        user_id = req.environ['nova.context']['user']['id']
        inst['user_id'] = user_id

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

        ref = self.db_driver.instance_create(None, inst)
        inst['id'] = ref.id
        
        return inst

    
