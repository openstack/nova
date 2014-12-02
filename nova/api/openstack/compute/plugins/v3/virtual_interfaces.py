# Copyright (C) 2011 Midokura KK
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

"""The virtual interfaces extension."""

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import network


ALIAS = 'os-virtual-interfaces'
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


def _translate_vif_summary_view(_context, vif):
    """Maps keys for VIF summary view."""
    d = {}
    d['id'] = vif['uuid']
    d['mac_address'] = vif['address']
    return d


class ServerVirtualInterfaceController(wsgi.Controller):
    """The instance VIF API controller for the OpenStack API.
    """

    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(ServerVirtualInterfaceController, self).__init__()

    def _items(self, req, server_id, entity_maker):
        """Returns a list of VIFs, transformed through entity_maker."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id,
                                       want_objects=True)

        vifs = self.network_api.get_vifs_by_instance(context, instance)
        limited_list = common.limited(vifs, req)
        res = [entity_maker(context, vif) for vif in limited_list]
        return {'virtual_interfaces': res}

    @extensions.expected_errors((404))
    def index(self, req, server_id):
        """Returns the list of VIFs for a given instance."""
        authorize(req.environ['nova.context'])
        return self._items(req, server_id,
                           entity_maker=_translate_vif_summary_view)


class VirtualInterfaces(extensions.V3APIExtensionBase):
    """Virtual interface support."""

    name = "VirtualInterfaces"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            ALIAS,
            controller=ServerVirtualInterfaceController(),
            parent=dict(member_name='server', collection_name='servers'))
        resources.append(res)

        return resources

    def get_controller_extensions(self):
        return []
