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

import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova import objects


ALIAS = 'os-pci'
instance_authorize = extensions.soft_extension_authorizer(
    'compute', 'v3:' + ALIAS + ':pci_servers')

authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)

PCI_ADMIN_KEYS = ['id', 'address', 'vendor_id', 'product_id', 'status',
                  'compute_node_id']
PCI_DETAIL_KEYS = ['dev_type', 'label', 'instance_uuid', 'dev_id',
                   'extra_info']


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
            server = resp_obj.obj['server']
            instance = req.get_db_instance(server['id'])
            self._extend_server(server, instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if instance_authorize(context):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                instance = req.get_db_instance(server['id'])
                self._extend_server(server, instance)


class PciHypervisorController(wsgi.Controller):
    def _extend_hypervisor(self, hypervisor, compute_node):
        if compute_node.pci_device_pools is not None:
            pci_pools = [pci_pool.to_dict()
                         for pci_pool in compute_node.pci_device_pools]
        else:
            pci_pools = []
        hypervisor['%s:pci_stats' % Pci.alias] = pci_pools

    @wsgi.extends
    def show(self, req, resp_obj, id):
        hypervisor = resp_obj.obj['hypervisor']
        compute_node = req.get_db_compute_node(hypervisor['id'])
        self._extend_hypervisor(hypervisor, compute_node)

    @wsgi.extends
    def detail(self, req, resp_obj):
        hypervisors = list(resp_obj.obj['hypervisors'])
        for hypervisor in hypervisors:
            compute_node = req.get_db_compute_node(hypervisor['id'])
            self._extend_hypervisor(hypervisor, compute_node)


class PciController(wsgi.Controller):

    def __init__(self):
        self.host_api = compute.HostAPI()

    def _view_pcidevice(self, device, detail=False):
        dev_dict = {}
        for key in PCI_ADMIN_KEYS:
            dev_dict[key] = device[key]
        if detail:
            for field in PCI_DETAIL_KEYS:
                if field == 'instance_uuid':
                    dev_dict['server_uuid'] = device[field]
                else:
                    dev_dict[field] = device[field]
        return dev_dict

    def _get_all_nodes_pci_devices(self, req, detail, action):
        context = req.environ['nova.context']
        authorize(context, action=action)
        compute_nodes = self.host_api.compute_node_get_all(context)
        results = []
        for node in compute_nodes:
            pci_devs = objects.PciDeviceList.get_by_compute_node(
                context, node['id'])
            results.extend([self._view_pcidevice(dev, detail)
                            for dev in pci_devs])
        return results

    @extensions.expected_errors(())
    def detail(self, req):
        results = self._get_all_nodes_pci_devices(req, True, 'detail')
        return dict(pci_devices=results)

    @extensions.expected_errors(404)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context, action='show')
        try:
            pci_dev = objects.PciDevice.get_by_dev_id(context, id)
        except exception.PciDeviceNotFoundById as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        result = self._view_pcidevice(pci_dev, True)
        return dict(pci_device=result)

    @extensions.expected_errors(())
    def index(self, req):
        results = self._get_all_nodes_pci_devices(req, False, 'index')
        return dict(pci_devices=results)


class Pci(extensions.V3APIExtensionBase):
    """Pci access support."""
    name = "PciAccess"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = [extensions.ResourceExtension(ALIAS,
                     PciController(),
                     collection_actions={'detail': 'GET'})]
        return resources

    def get_controller_extensions(self):
        server_extension = extensions.ControllerExtension(
            self, 'servers', PciServerController())
        compute_extension = extensions.ControllerExtension(
            self, 'os-hypervisors', PciHypervisorController())
        return [server_extension, compute_extension]
