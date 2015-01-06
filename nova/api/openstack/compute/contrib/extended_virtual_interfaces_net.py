# Copyright 2013 IBM Corp.
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


from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import network

authorize = extensions.soft_extension_authorizer('compute', 'extended_vif_net')


class ExtendedServerVIFNetController(wsgi.Controller):
    def __init__(self):
        super(ExtendedServerVIFNetController, self).__init__()
        self.network_api = network.API()

    @wsgi.extends
    def index(self, req, resp_obj, server_id):
        key = "%s:net_id" % Extended_virtual_interfaces_net.alias
        context = req.environ['nova.context']
        if authorize(context):
            for vif in resp_obj.obj['virtual_interfaces']:
                vif1 = self.network_api.get_vif_by_mac_address(context,
                                                           vif['mac_address'])
                vif[key] = vif1['net_uuid']


class Extended_virtual_interfaces_net(extensions.ExtensionDescriptor):
    """Adds network id parameter to the virtual interface list."""

    name = "ExtendedVIFNet"
    alias = "OS-EXT-VIF-NET"
    namespace = ("http://docs.openstack.org/compute/ext/"
                "extended-virtual-interfaces-net/api/v1.1")
    updated = "2013-03-07T00:00:00Z"

    def get_controller_extensions(self):
        controller = ExtendedServerVIFNetController()
        extension = extensions.ControllerExtension(self,
                                                   'os-virtual-interfaces',
                                                   controller)
        return [extension]
