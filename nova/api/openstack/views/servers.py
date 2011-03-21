# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

import hashlib
from nova.compute import power_state
from nova.api.openstack import common
from nova.api.openstack.views import addresses as addresses_view
from nova.api.openstack.views import flavors as flavors_view
from nova.api.openstack.views import images as images_view
from nova import utils


class ViewBuilder(object):
    '''
    Models a server response as a python dictionary.
    Abstract methods: _build_image, _build_flavor
    '''

    def __init__(self, addresses_builder):
        self.addresses_builder = addresses_builder

    def build(self, inst, is_detail):
        """
        Coerces into dictionary format, mapping everything to
        Rackspace-like attributes for return
        """
        if is_detail:
            return self._build_detail(inst)
        else:
            return self._build_simple(inst)

    def _build_simple(self, inst):
            return dict(server=dict(id=inst['id'], name=inst['display_name']))

    def _build_detail(self, inst):
        power_mapping = {
            None: 'build',
            power_state.NOSTATE: 'build',
            power_state.RUNNING: 'active',
            power_state.BLOCKED: 'active',
            power_state.SUSPENDED: 'suspended',
            power_state.PAUSED: 'paused',
            power_state.SHUTDOWN: 'active',
            power_state.SHUTOFF: 'active',
            power_state.CRASHED: 'error',
            power_state.FAILED: 'error'}
        inst_dict = {}

        inst_dict['id'] = int(inst['id'])
        inst_dict['name'] = inst['display_name']
        inst_dict['status'] = power_mapping[inst.get('state')]
        inst_dict['addresses'] = self.addresses_builder.build(inst)

        # Return the metadata as a dictionary
        metadata = {}
        for item in inst.get('metadata', []):
            metadata[item['key']] = item['value']
        inst_dict['metadata'] = metadata

        inst_dict['hostId'] = ''
        if inst.get('host'):
            inst_dict['hostId'] = hashlib.sha224(inst['host']).hexdigest()

        self._build_image(inst_dict, inst)
        self._build_flavor(inst_dict, inst)

        return dict(server=inst_dict)

    def _build_image(self, response, inst):
        raise NotImplementedError()

    def _build_flavor(self, response, inst):
        raise NotImplementedError()


class ViewBuilderV10(ViewBuilder):
    def _build_image(self, response, inst):
        if inst.get('image_id') != None:
            response['imageId'] = inst['image_id']

    def _build_flavor(self, response, inst):
        if inst.get('instance_type') != None:
            response['flavorId'] = inst['instance_type']


class ViewBuilderV11(ViewBuilder):
    def __init__(self, addresses_builder, flavor_builder, image_builder):
        ViewBuilder.__init__(self, addresses_builder)
        self.flavor_builder = flavor_builder
        self.image_builder = image_builder

    def _build_image(self, response, inst):
        if inst.get('image_id') == None:
            return
        image_id = inst["image_id"]
        response["imageRef"] = self.image_builder.generate_href(image_id)

    def _build_flavor(self, response, inst):
        if inst.get('instance_type') == None:
            return
        flavor_id = inst["instance_type"]
        response["flavorRef"] = self.flavor_builder.generate_href(flavor_id)
