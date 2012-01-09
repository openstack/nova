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
from nova.api.openstack.v2 import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import log as logging
from nova import network


LOG = logging.getLogger("nova.api.openstack.v2.contrib.virtual_interfaces")


vif_nsmap = {None: wsgi.XMLNS_V11}


class VirtualInterfaceTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('virtual_interfaces')
        elem = xmlutil.SubTemplateElement(root, 'virtual_interface',
                                          selector='virtual_interfaces')
        elem.set('id')
        elem.set('mac_address')
        return xmlutil.MasterTemplate(root, 1, nsmap=vif_nsmap)


def _translate_vif_summary_view(_context, vif):
    """Maps keys for VIF summary view."""
    d = {}
    d['id'] = vif['uuid']
    d['mac_address'] = vif['address']
    return d


class ServerVirtualInterfaceController(object):
    """The instance VIF API controller for the Openstack API.
    """

    def __init__(self):
        self.network_api = network.API()
        super(ServerVirtualInterfaceController, self).__init__()

    def _items(self, req, server_id, entity_maker):
        """Returns a list of VIFs, transformed through entity_maker."""
        context = req.environ['nova.context']

        vifs = self.network_api.get_vifs_by_instance(context, server_id)
        limited_list = common.limited(vifs, req)
        res = [entity_maker(context, vif) for vif in limited_list]
        return {'virtual_interfaces': res}

    @wsgi.serializers(xml=VirtualInterfaceTemplate)
    def index(self, req, server_id):
        """Returns the list of VIFs for a given instance."""
        return self._items(req, server_id,
                           entity_maker=_translate_vif_summary_view)


class Virtual_interfaces(extensions.ExtensionDescriptor):
    """Virtual interface support"""

    name = "VirtualInterfaces"
    alias = "virtual_interfaces"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "virtual_interfaces/api/v1.1"
    updated = "2011-08-17T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-virtual-interfaces',
            controller=ServerVirtualInterfaceController(),
            parent=dict(member_name='server', collection_name='servers'))
        resources.append(res)

        return resources
