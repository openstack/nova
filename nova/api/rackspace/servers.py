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

import webob
from webob import exc

from nova import flags
from nova import rpc
from nova import utils
from nova import wsgi
from nova.api import cloud
from nova.api.rackspace import _id_translator
from nova.api.rackspace import context
from nova.api.rackspace import faults
from nova.compute import instance_types
from nova.compute import power_state
import nova.api.rackspace
import nova.image.service

FLAGS = flags.FLAGS

def _instance_id_translator():
    """ Helper method for initializing an id translator for Rackspace instance
    ids """
    return _id_translator.RackspaceAPIIdTranslator( "instance", 'nova')

def _image_service():
    """ Helper method for initializing the image id translator """
    service = nova.image.service.ImageService.load()
    return (service, _id_translator.RackspaceAPIIdTranslator(
            "image", service.__class__.__name__))

def _filter_params(inst_dict):
    """ Extracts all updatable parameters for a server update request """
    keys = dict(name='name', admin_pass='adminPass')
    new_attrs = {}
    for k, v in keys.items():
        if inst_dict.has_key(v):
            new_attrs[k] = inst_dict[v]
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
        inst = self.db_driver.instance_get_by_internal_id(None, int(id))
        if inst:
            if inst.user_id == user_id:
                return _entity_detail(inst)
        raise faults.Fault(exc.HTTPNotFound())

    def delete(self, req, id):
        """ Destroys a server """
        user_id = req.environ['nova.context']['user']['id']
        instance = self.db_driver.instance_get_by_internal_id(None, int(id))
        if instance and instance['user_id'] == user_id:
            self.db_driver.instance_destroy(None, id)
            return faults.Fault(exc.HTTPAccepted())
        return faults.Fault(exc.HTTPNotFound())

    def create(self, req):
        """ Creates a new server for a given user """

        env = self._deserialize(req.body, req)
        if not env:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        #try:
        inst = self._build_server_instance(req, env)
        #except Exception, e:
        #    return faults.Fault(exc.HTTPUnprocessableEntity())

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
            return faults.Fault(exc.HTTPUnprocessableEntity())

        instance = self.db_driver.instance_get_by_internal_id(None, int(id))
        if not instance or instance.user_id != user_id:
            return faults.Fault(exc.HTTPNotFound())

        self.db_driver.instance_update(None, int(id), 
            _filter_params(inst_dict['server']))
        return faults.Fault(exc.HTTPNoContent())

    def action(self, req, id):
        """ multi-purpose method used to reboot, rebuild, and 
        resize a server """
        input_dict = self._deserialize(req.body, req)
        try:
            reboot_type = input_dict['reboot']['type']
        except Exception:
            raise faults.Fault(webob.exc.HTTPNotImplemented())
        opaque_id = _instance_id_translator().from_rs_id(int(id))
        cloud.reboot(opaque_id)

    def _build_server_instance(self, req, env):
        """Build instance data structure and save it to the data store."""
        ltime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        inst = {}

        user_id = req.environ['nova.context']['user']['id']

        flavor_id = env['server']['flavorId']

        instance_type, flavor = [(k, v) for k, v in
            instance_types.INSTANCE_TYPES.iteritems()
            if v['flavorid'] == flavor_id][0]

        image_id = env['server']['imageId']
        
        img_service, image_id_trans = _image_service()

        opaque_image_id = image_id_trans.to_rs_id(image_id)        
        image = img_service.show(opaque_image_id)

        if not image: 
            raise Exception, "Image not found"

        inst['server_name'] = env['server']['name']
        inst['image_id'] = opaque_image_id
        inst['user_id'] = user_id
        inst['launch_time'] = ltime
        inst['mac_address'] = utils.generate_mac()
        inst['project_id'] = user_id

        inst['state_description'] = 'scheduling'
        inst['kernel_id'] = image.get('kernelId', FLAGS.default_kernel)
        inst['ramdisk_id'] = image.get('ramdiskId', FLAGS.default_ramdisk)
        inst['reservation_id'] = utils.generate_uid('r')

        inst['display_name'] = env['server']['name']
        inst['display_description'] = env['server']['name']

        #TODO(dietz) this may be ill advised
        key_pair_ref = self.db_driver.key_pair_get_all_by_user(
            None, user_id)[0]

        inst['key_data'] = key_pair_ref['public_key']
        inst['key_name'] = key_pair_ref['name']

        #TODO(dietz) stolen from ec2 api, see TODO there
        inst['security_group'] = 'default'

        # Flavor related attributes
        inst['instance_type'] = instance_type
        inst['memory_mb'] = flavor['memory_mb']
        inst['vcpus'] = flavor['vcpus']
        inst['local_gb'] = flavor['local_gb']

        ref = self.db_driver.instance_create(None, inst)
        inst['id'] = ref.internal_id
        
        # TODO(dietz): this isn't explicitly necessary, but the networking
        # calls depend on an object with a project_id property, and therefore
        # should be cleaned up later
        api_context = context.APIRequestContext(user_id)
    
        inst['mac_address'] = utils.generate_mac()
        
        #TODO(dietz) is this necessary? 
        inst['launch_index'] = 0

        inst['hostname'] = str(ref.internal_id)
        self.db_driver.instance_update(None, inst['id'], inst)

        network_manager = utils.import_object(FLAGS.network_manager)
        address = network_manager.allocate_fixed_ip(api_context,
            inst['id'])

        # TODO(vish): This probably should be done in the scheduler
        #             network is setup when host is assigned
        network_topic = self._get_network_topic(user_id)
        rpc.call(network_topic,
                 {"method": "setup_fixed_ip",
                  "args": {"context": None,
                           "address": address}})
        return inst

    def _get_network_topic(self, user_id):
        """Retrieves the network host for a project"""
        network_ref = self.db_driver.project_get_network(None, 
            user_id)
        host = network_ref['host']
        if not host:
            host = rpc.call(FLAGS.network_topic,
                                  {"method": "set_network_host",
                                   "args": {"context": None,
                                            "project_id": user_id}})
        return self.db_driver.queue_get_for(None, FLAGS.network_topic, host)
