# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Intel Corp.
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


from nova.api.openstack.compute.plugins.v3 import pci
from nova.api.openstack import wsgi
from nova import context
from nova import db
from nova.objects import instance
from nova.objects import pci_device
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests.objects import test_pci_device


class FakeResponse(wsgi.ResponseObject):
    pass


class PciServerTemplateTest(test.NoDBTestCase):
    def test_pci_server_serializer(self):
        fake_server = {"server": {'os-pci:pci_devices': [{"id": 1}]}}
        expected = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<server xmlns:os-pci="http://docs.openstack.org/compute'
                    '/ext/os-pci/api/v3"><os-pci:pci_devices xmlns:'
                    'os-pci="os-pci"><os-pci:pci_device id="1"/>'
                    '</os-pci:pci_devices></server>'
                    )
        serializer = pci.PciServerTemplate()
        text = serializer.serialize(fake_server)
        self.assertEqual(expected, text)

    def test_pci_servers_serializer(self):
        fake_servers = {"servers": [{'os-pci:pci_devices': [{"id": 1}]},
                                    {'os-pci:pci_devices': [{"id": 2}]}]}
        expected = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<servers xmlns:os-pci="http://docs.openstack.org/'
                    'compute/ext/os-pci/api/v3"><server><os-pci:pci_devices'
                    ' xmlns:os-pci="os-pci"><os-pci:pci_device id="1"/>'
                    '</os-pci:pci_devices></server><server>'
                    '<os-pci:pci_devices xmlns:os-pci="os-pci">'
                    '<os-pci:pci_device id="2"/></os-pci:pci_devices>'
                    '</server></servers>'
                   )
        serializer = pci.PciServersTemplate()
        text = serializer.serialize(fake_servers)
        self.assertEqual(expected, text)


class PciServerControllerTest(test.NoDBTestCase):
    def setUp(self):
        super(PciServerControllerTest, self).setUp()
        self.controller = pci.PciServerController()
        self.fake_obj = {'server': {'addresses': {},
                                    'id': 'fb08',
                                    'name': 'a3',
                                    'status': 'ACTIVE',
                                    'tenant_id': '9a3af784c',
                                    'user_id': 'e992080ac0',
                                    }}
        self.fake_list = {'servers': [{'addresses': {},
                                       'id': 'fb08',
                                       'name': 'a3',
                                       'status': 'ACTIVE',
                                       'tenant_id': '9a3af784c',
                                       'user_id': 'e992080ac',
                                       }]}
        self._create_fake_instance()
        self._create_fake_pci_device()
        self.pci_device.claim(self.inst)
        self.pci_device.allocate(self.inst)

    def _create_fake_instance(self):
        self.inst = instance.Instance()
        self.inst.uuid = 'fake-inst-uuid'
        self.inst.pci_devices = pci_device.PciDeviceList()

    def _create_fake_pci_device(self):
        def fake_pci_device_get_by_addr(ctxt, id, addr):
            return test_pci_device.fake_db_dev

        ctxt = context.get_admin_context()
        self.stubs.Set(db, 'pci_device_get_by_addr',
                       fake_pci_device_get_by_addr)
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')

    def test_show(self):
        def fake_get_db_instance(id):
            return self.inst

        resp = FakeResponse(self.fake_obj, '')
        req = fakes.HTTPRequestV3.blank('/os-pci/1', use_admin_context=True)
        self.stubs.Set(req, 'get_db_instance', fake_get_db_instance)
        self.controller.show(req, resp, '1')
        self.assertEqual([{'id': 1}],
                         resp.obj['server']['os-pci:pci_devices'])

    def test_detail(self):
        def fake_get_db_instance(id):
            return self.inst

        resp = FakeResponse(self.fake_list, '')
        req = fakes.HTTPRequestV3.blank('/os-pci/detail',
                                        use_admin_context=True)
        self.stubs.Set(req, 'get_db_instance', fake_get_db_instance)
        self.controller.detail(req, resp)
        self.assertEqual([{'id': 1}],
                         resp.obj['servers'][0]['os-pci:pci_devices'])
