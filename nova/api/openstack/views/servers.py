# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
# Copyright 2011 Piston Cloud Computing, Inc.
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
import hashlib
import os

from nova import exception
from nova.api.openstack import common
from nova.api.openstack.views import addresses as addresses_view
from nova.api.openstack.views import flavors as flavors_view
from nova.api.openstack.views import images as images_view
from nova import utils
from nova.compute import vm_states


class ViewBuilder(object):
    """Model a server response as a python dictionary.

    Public methods: build
    Abstract methods: _build_image, _build_flavor

    """

    def __init__(self, addresses_builder):
        self.addresses_builder = addresses_builder

    def build(self, inst, is_detail):
        """Return a dict that represenst a server."""
        if inst.get('_is_precooked', False):
            server = dict(server=inst)
        else:
            if is_detail:
                server = self._build_detail(inst)
            else:
                server = self._build_simple(inst)

            self._build_extra(server['server'], inst)

        return server

    def _build_simple(self, inst):
        """Return a simple model of a server."""
        return dict(server=dict(id=inst['id'], name=inst['display_name']))

    def _build_detail(self, inst):
        """Returns a detailed model of a server."""
        vm_state = inst.get('vm_state', vm_states.BUILDING)
        task_state = inst.get('task_state')

        inst_dict = {
            'id': inst['id'],
            'name': inst['display_name'],
            'user_id': inst.get('user_id', ''),
            'tenant_id': inst.get('project_id', ''),
            'status': common.status_from_state(vm_state, task_state)}

        # Return the metadata as a dictionary
        metadata = {}
        for item in inst.get('metadata', []):
            metadata[item['key']] = str(item['value'])
        inst_dict['metadata'] = metadata

        inst_dict['hostId'] = ''
        if inst.get('host'):
            inst_dict['hostId'] = hashlib.sha224(inst['host']).hexdigest()

        self._build_image(inst_dict, inst)
        self._build_flavor(inst_dict, inst)
        self._build_addresses(inst_dict, inst)

        return dict(server=inst_dict)

    def _build_addresses(self, response, inst):
        """Return the addresses sub-resource of a server."""
        raise NotImplementedError()

    def _build_image(self, response, inst):
        """Return the image sub-resource of a server."""
        raise NotImplementedError()

    def _build_flavor(self, response, inst):
        """Return the flavor sub-resource of a server."""
        raise NotImplementedError()

    def _build_extra(self, response, inst):
        pass


class ViewBuilderV10(ViewBuilder):
    """Model an Openstack API V1.0 server response."""

    def _build_extra(self, response, inst):
        response['uuid'] = inst['uuid']

    def _build_image(self, response, inst):
        if inst.get('image_ref', None):
            image_ref = inst['image_ref']
            if str(image_ref).startswith('http'):
                raise exception.ListingImageRefsNotSupported()
            response['imageId'] = int(image_ref)

    def _build_flavor(self, response, inst):
        if inst.get('instance_type', None):
            response['flavorId'] = inst['instance_type']['flavorid']

    def _build_addresses(self, response, inst):
        response['addresses'] = self.addresses_builder.build(inst)


class ViewBuilderV11(ViewBuilder):
    """Model an Openstack API V1.0 server response."""
    def __init__(self, addresses_builder, flavor_builder, image_builder,
                 base_url, project_id=""):
        ViewBuilder.__init__(self, addresses_builder)
        self.flavor_builder = flavor_builder
        self.image_builder = image_builder
        self.base_url = base_url
        self.project_id = project_id

    def _build_detail(self, inst):
        response = super(ViewBuilderV11, self)._build_detail(inst)
        response['server']['created'] = utils.isotime(inst['created_at'])
        response['server']['updated'] = utils.isotime(inst['updated_at'])
        if 'status' in response['server']:
            if response['server']['status'] == "ACTIVE":
                response['server']['progress'] = 100
            elif response['server']['status'] == "BUILD":
                response['server']['progress'] = 0

        response['server']['accessIPv4'] = inst.get('access_ip_v4') or ""
        response['server']['accessIPv6'] = inst.get('access_ip_v6') or ""
        response['server']['key_name'] = inst.get('key_name', '')
        response['server']['config_drive'] = inst.get('config_drive')

        return response

    def _build_image(self, response, inst):
        if inst.get("image_ref", None):
            image_href = inst['image_ref']
            image_id = str(common.get_id_from_href(image_href))
            _bookmark = self.image_builder.generate_bookmark(image_id)
            response['image'] = {
                "id": image_id,
                "links": [
                    {
                        "rel": "bookmark",
                        "href": _bookmark,
                    },
                ]
            }

    def _build_flavor(self, response, inst):
        if inst.get("instance_type", None):
            flavor_id = inst["instance_type"]['flavorid']
            flavor_ref = self.flavor_builder.generate_href(flavor_id)
            flavor_bookmark = self.flavor_builder.generate_bookmark(flavor_id)
            response["flavor"] = {
                "id": str(common.get_id_from_href(flavor_ref)),
                "links": [
                    {
                        "rel": "bookmark",
                        "href": flavor_bookmark,
                    },
                ]
            }

    def _build_addresses(self, response, inst):
        interfaces = inst.get('virtual_interfaces', [])
        response['addresses'] = self.addresses_builder.build(interfaces)

    def _build_extra(self, response, inst):
        self._build_links(response, inst)
        response['uuid'] = inst['uuid']

    def _build_links(self, response, inst):
        href = self.generate_href(inst["id"])
        bookmark = self.generate_bookmark(inst["id"])

        links = [
            {
                "rel": "self",
                "href": href,
            },
            {
                "rel": "bookmark",
                "href": bookmark,
            },
        ]

        response["links"] = links

    def generate_href(self, server_id):
        """Create an url that refers to a specific server id."""
        return os.path.join(self.base_url, self.project_id,
                            "servers", str(server_id))

    def generate_bookmark(self, server_id):
        """Create an url that refers to a specific flavor id."""
        return os.path.join(common.remove_version_from_href(self.base_url),
            self.project_id, "servers", str(server_id))
