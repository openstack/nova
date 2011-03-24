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
import nova.compute
import nova.context
from nova.api.openstack import common
from nova.api.openstack.views import addresses as addresses_view
from nova.api.openstack.views import flavors as flavors_view
from nova.api.openstack.views import images as images_view
from nova import utils


class ViewBuilder(object):
    """Model a server response as a python dictionary.

    Public methods: build
    Abstract methods: _build_image, _build_flavor

    """

    def __init__(self, addresses_builder):
        self.addresses_builder = addresses_builder

    def build(self, inst, is_detail):
        """Return a dict that represenst a server."""
        if is_detail:
            return self._build_detail(inst)
        else:
            return self._build_simple(inst)

    def _build_simple(self, inst):
        """Return a simple model of a server."""
        return dict(server=dict(id=inst['id'], name=inst['display_name']))

    def _build_detail(self, inst):
        """Returns a detailed model of a server."""
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

        inst_dict = {
            'id': int(inst['id']),
            'name': inst['display_name'],
            'addresses': self.addresses_builder.build(inst),
            'status': power_mapping[inst.get('state')]}

        ctxt = nova.context.get_admin_context()
        compute_api = nova.compute.API()
        if compute_api.has_finished_migration(ctxt, inst['id']):
            inst_dict['status'] = 'resize-confirm'

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
        """Return the image sub-resource of a server."""
        raise NotImplementedError()

    def _build_flavor(self, response, inst):
        """Return the flavor sub-resource of a server."""
        raise NotImplementedError()


class ViewBuilderV10(ViewBuilder):
    """Model an Openstack API V1.0 server response."""

    def _build_image(self, response, inst):
        response['imageId'] = inst['image_id']

    def _build_flavor(self, response, inst):
        response['flavorId'] = inst['instance_type']


class ViewBuilderV11(ViewBuilder):
    """Model an Openstack API V1.0 server response."""

    def __init__(self, addresses_builder, flavor_builder, image_builder):
        ViewBuilder.__init__(self, addresses_builder)
        self.flavor_builder = flavor_builder
        self.image_builder = image_builder

    def _build_image(self, response, inst):
        image_id = inst["image_id"]
        response["imageRef"] = self.image_builder.generate_href(image_id)

    def _build_flavor(self, response, inst):
        flavor_id = inst["instance_type"]
        response["flavorRef"] = self.flavor_builder.generate_href(flavor_id)
