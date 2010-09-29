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

import datetime
import time

from webob import exc

from nova import flags
from nova import rpc
from nova import utils
from nova import wsgi
from nova.api.rackspace import _id_translator
from nova.compute import power_state
from nova.wsgi import Serializer
import nova.image.service

FLAGS = flags.FLAGS

flags.DEFINE_string('rs_network_manager', 'nova.network.manager.FlatManager',
    'Networking for rackspace')

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
        user_id = req.environ['nova.context']['user']['id']
        instance_list = self.db_driver.instance_get_all_by_user(None, user_id)
        res = [_entity_inst(inst)['server'] for inst in instance_list]
        return _entity_list(res)

    def detail(self, req):
        """ Returns a list of server details for a given user """
        user_id = req.environ['nova.context']['user']['id']
        res = [_entity_detail(inst)['server'] for inst in 
                self.db_driver.instance_get_all_by_user(None, user_id)]
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
        user_id = req.environ['nova.context']['user']['id']

        inst_dict = self._deserialize(req.body, req)
        
        if not inst_dict:
            return exc.HTTPUnprocessableEntity()

        instance = self.db_driver.instance_get(None, id)
        if not instance or instance.user_id != user_id:
            return exc.HTTPNotFound()

        self.db_driver.instance_update(None, id, 
            _filter_params(inst_dict['server']))
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
        user_id = req.environ['nova.context']['user']['id']

        inst['rs_id'] = _new_rs_id(user_id)
        image_id = env['server']['imageId']
        
        opaque_id = translator_instance().from_rs_id(image_id)

        inst['name'] = env['server']['name']
        inst['image_id'] = opaque_id
        inst['instance_type'] = env['server']['flavorId']
        inst['user_id'] = user_id
        inst['launch_time'] = ltime
        inst['mac_address'] = utils.generate_mac()

        #TODO(dietz) These are the attributes I'm unsure of
        inst['state_description'] = 'scheduling'
        inst['kernel_id'] = ''
        inst['ramdisk_id'] = ''
        inst['reservation_id'] = utils.generate_uid('r')
        inst['key_data'] = ''
        inst['key_name'] = ''
        inst['security_group'] = ''

        # Flavor related attributes
        inst['instance_type'] = ''
        inst['memory_mb'] = ''
        inst['vcpus'] = ''
        inst['local_gb'] = ''

        

        #TODO(dietz): This seems necessary. How do these apply across
        #the Rackspace implementation?
        inst['project_id'] = ''

        self.network_manager = utils.import_object(FLAGS.rs_network_manager)
        
        address = self.network_manager.allocate_fixed_ip( None, inst['id']) 

        ref = self.db_driver.instance_create(None, inst)
        inst['id'] = ref.id
        
        return inst

    
