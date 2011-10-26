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

import hashlib
import os

from nova.api.openstack import common
from nova.compute import vm_states
from nova import exception
from nova import log as logging
from nova import utils


LOG = logging.getLogger('nova.api.openstack.views.servers')


class ViewBuilder(object):
    """Model a server response as a python dictionary."""

    def __init__(self, context, addresses_builder, flavor_builder,
                 image_builder, base_url, project_id=""):
        self.context = context
        self.addresses_builder = addresses_builder
        self.flavor_builder = flavor_builder
        self.image_builder = image_builder
        self.base_url = base_url
        self.project_id = project_id

    def build(self, inst, is_detail=False, is_create=False):
        """Return a dict that represenst a server."""
        if inst.get('_is_precooked', False):
            server = dict(server=inst)
        else:
            if is_detail:
                server = self._build_detail(inst)
            elif is_create:
                server = self._build_create(inst)
            else:
                server = self._build_simple(inst)

            self._build_links(server['server'], inst)

        return server

    def _build_simple(self, inst):
        """Return a simple model of a server."""
        return dict(server=dict(id=inst['uuid'], name=inst['display_name']))

    def _build_create(self, inst):
        """Return data that should be returned from a server create."""
        server = dict(server=dict(id=inst['uuid']))
        self._build_links(server['server'], inst)
        return server

    def _build_detail(self, inst):
        """Returns a detailed model of a server."""
        vm_state = inst.get('vm_state', vm_states.BUILDING)
        task_state = inst.get('task_state')

        inst_dict = {
            'id': inst['uuid'],
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
        networks = common.get_networks_for_instance(self.context, inst)
        self._build_addresses(inst_dict, networks)

        inst_dict['created'] = utils.isotime(inst['created_at'])
        inst_dict['updated'] = utils.isotime(inst['updated_at'])

        status = inst_dict.get('status')
        if status in ('ACTIVE', 'BUILD', 'REBUILD', 'RESIZE',
                      'VERIFY_RESIZE'):
            inst_dict['progress'] = inst['progress'] or 0

        inst_dict['accessIPv4'] = inst.get('access_ip_v4') or ""
        inst_dict['accessIPv6'] = inst.get('access_ip_v6') or ""
        inst_dict['key_name'] = inst.get('key_name', '')
        inst_dict['config_drive'] = inst.get('config_drive')

        return dict(server=inst_dict)

    def _build_addresses(self, response, networks):
        """Return the addresses sub-resource of a server."""
        response['addresses'] = self.addresses_builder.build(networks)

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

    def _build_links(self, response, inst):
        href = self.generate_href(inst["uuid"])
        bookmark = self.generate_bookmark(inst["uuid"])

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

    def build_list(self, server_objs, is_detail=False, **kwargs):
        limit = kwargs.get('limit', None)
        servers = []
        servers_links = []

        for server_obj in server_objs:
            servers.append(self.build(server_obj, is_detail)['server'])

        if (len(servers) and limit) and (limit == len(servers)):
            next_link = self.generate_next_link(servers[-1]['id'],
                                                kwargs, is_detail)
            servers_links = [dict(rel='next', href=next_link)]

        reval = dict(servers=servers)
        if len(servers_links) > 0:
            reval['servers_links'] = servers_links
        return reval

    def generate_next_link(self, server_id, params, is_detail=False):
        """ Return an href string with proper limit and marker params"""
        params['marker'] = server_id
        return "%s?%s" % (
            os.path.join(self.base_url, self.project_id, "servers"),
            common.dict_to_query_str(params))

    def generate_href(self, server_id):
        """Create an url that refers to a specific server id."""
        return os.path.join(self.base_url, self.project_id,
                            "servers", str(server_id))

    def generate_bookmark(self, server_id):
        """Create an url that refers to a specific flavor id."""
        return os.path.join(common.remove_version_from_href(self.base_url),
            self.project_id, "servers", str(server_id))
