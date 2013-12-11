# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Intel Corporation
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


from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil


ALIAS = 'os-pci'
instance_authorize = extensions.soft_extension_authorizer(
    'compute', 'v3:' + ALIAS + ':pci_servers')


def make_server(elem):
    pci_devices = xmlutil.TemplateElement('%s:pci_devices' % Pci.alias,
                                          colon_ns=True)
    elem.append(pci_devices)
    device = xmlutil.SubTemplateElement(pci_devices,
                                        '%s:pci_device' % Pci.alias,
                                        selector='%s:pci_devices' % Pci.alias,
                                        colon_ns=True)
    device.set('id')


class PciServerTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={Pci.alias: Pci.namespace})


class PciServersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={Pci.alias: Pci.namespace})


class PciServerController(wsgi.Controller):
    def _extend_server(self, server, instance):
        dev_id = []
        for dev in instance.pci_devices:
            dev_id.append({'id': dev['id']})
        server['%s:pci_devices' % Pci.alias] = dev_id

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if instance_authorize(context):
            resp_obj.attach(xml=PciServerTemplate())
            server = resp_obj.obj['server']
            instance = req.get_db_instance(server['id'])
            self._extend_server(server, instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if instance_authorize(context):
            resp_obj.attach(xml=PciServersTemplate())
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                instance = req.get_db_instance(server['id'])
                self._extend_server(server, instance)


class Pci(extensions.V3APIExtensionBase):
    """Pci access support."""
    name = "PCIAccess"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/%s/api/v3" % ALIAS
    version = 1

    def get_resources(self):
        return []

    def get_controller_extensions(self):
        server_extension = extensions.ControllerExtension(
            self, 'servers', PciServerController())
        return [server_extension]
