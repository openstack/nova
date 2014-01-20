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
from nova.openstack.common import jsonutils


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


def make_hypervisor(elem):
    pci_stats = xmlutil.TemplateElement('%s:pci_stats' % Pci.alias,
                                        colon_ns=True)
    elem.append(pci_stats)
    pci_stat = xmlutil.make_flat_dict('%s:pci_stat' % Pci.alias,
                                      selector='%s:pci_stats' % Pci.alias,
                                      colon_ns=True,
                                      root=pci_stats,
                                      ignore_sub_dicts=True)
    extra = xmlutil.make_flat_dict('extra_info', selector='extra_info')
    pci_stat.append(extra)
    pci_stats.append(pci_stat)


class PciHypervisorTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisor', selector='hypervisor')
        make_hypervisor(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={Pci.alias: Pci.namespace})


class HypervisorDetailTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hypervisors')
        elem = xmlutil.SubTemplateElement(root, 'hypervisor',
                                          selector='hypervisors')
        make_hypervisor(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={Pci.alias: Pci.namespace})


class PciHypervisorController(wsgi.Controller):
    def _extend_hypervisor(self, hypervisor, compute_node):
        hypervisor['%s:pci_stats' % Pci.alias] = jsonutils.loads(
            compute_node['pci_stats'])

    @wsgi.extends
    def show(self, req, resp_obj, id):
        resp_obj.attach(xml=PciHypervisorTemplate())
        hypervisor = resp_obj.obj['hypervisor']
        compute_node = req.get_db_compute_node(hypervisor['id'])
        self._extend_hypervisor(hypervisor, compute_node)

    @wsgi.extends
    def detail(self, req, resp_obj):
        resp_obj.attach(xml=HypervisorDetailTemplate())
        hypervisors = list(resp_obj.obj['hypervisors'])
        for hypervisor in hypervisors:
            compute_node = req.get_db_compute_node(hypervisor['id'])
            self._extend_hypervisor(hypervisor, compute_node)


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
        compute_extension = extensions.ControllerExtension(
            self, 'os-hypervisors', PciHypervisorController())
        return [server_extension, compute_extension]
