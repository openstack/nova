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

import mock
from webob import exc

from nova.api.openstack.compute import pci
from nova.api.openstack import wsgi
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields
from nova.objects import pci_device_pool
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_pci_device
from nova.tests import uuidsentinel as uuids


pci_stats = [{"count": 3,
              "vendor_id": "8086",
              "product_id": "1520",
              "numa_node": 1}]

fake_compute_node = objects.ComputeNode(
    pci_device_pools=pci_device_pool.from_pci_stats(pci_stats))


class FakeResponse(wsgi.ResponseObject):
    pass


class PciServerControllerTestV21(test.NoDBTestCase):
    def setUp(self):
        super(PciServerControllerTestV21, self).setUp()
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
        self.pci_device.claim(self.inst.uuid)
        self.pci_device.allocate(self.inst)

    def _create_fake_instance(self):
        self.inst = objects.Instance()
        self.inst.uuid = uuids.instance
        self.inst.pci_devices = objects.PciDeviceList()

    def _create_fake_pci_device(self):
        def fake_pci_device_get_by_addr(ctxt, id, addr):
            return test_pci_device.fake_db_dev

        ctxt = context.get_admin_context()
        self.stub_out('nova.db.pci_device_get_by_addr',
                      fake_pci_device_get_by_addr)
        self.pci_device = objects.PciDevice.get_by_dev_addr(ctxt, 1, 'a')

    def test_show(self):
        resp = FakeResponse(self.fake_obj, '')
        req = fakes.HTTPRequest.blank('/os-pci/1', use_admin_context=True)

        with mock.patch.object(req, 'get_db_instance',
                               return_value=self.inst) as mock_get_db_inst:
            self.controller.show(req, resp, '1')
            self.assertEqual([{'id': 1}],
                             resp.obj['server']['os-pci:pci_devices'])
            mock_get_db_inst.assert_called_once_with(
                self.fake_obj['server']['id'])

    def test_detail(self):
        resp = FakeResponse(self.fake_list, '')
        req = fakes.HTTPRequest.blank('/os-pci/detail',
                                      use_admin_context=True)

        with mock.patch.object(req, 'get_db_instance',
                               return_value=self.inst) as mock_get_db_inst:
            self.controller.detail(req, resp)
            self.assertEqual([{'id': 1}],
                             resp.obj['servers'][0]['os-pci:pci_devices'])
            mock_get_db_inst.assert_called_once_with(
                self.fake_list['servers'][0]['id'])


class PciHypervisorControllerTestV21(test.NoDBTestCase):
    def setUp(self):
        super(PciHypervisorControllerTestV21, self).setUp()
        self.controller = pci.PciHypervisorController()
        self.fake_objs = dict(hypervisors=[
            dict(id=1,
                 service=dict(id=1, host="compute1"),
                 hypervisor_type="xen",
                 hypervisor_version=3,
                 hypervisor_hostname="hyper1")])
        self.fake_obj = dict(hypervisor=dict(
            id=1,
            service=dict(id=1, host="compute1"),
            hypervisor_type="xen",
            hypervisor_version=3,
            hypervisor_hostname="hyper1"))

    def test_show(self):
        req = fakes.HTTPRequest.blank('/os-hypervisors/1',
                                      use_admin_context=True)
        resp = FakeResponse(self.fake_obj, '')

        with mock.patch.object(req, 'get_db_compute_node',
                               return_value=fake_compute_node
        ) as mock_get_db_node:
            self.controller.show(req, resp, '1')
            self.assertIn('os-pci:pci_stats', resp.obj['hypervisor'])
            self.assertEqual(pci_stats[0],
                             resp.obj['hypervisor']['os-pci:pci_stats'][0])
            mock_get_db_node.assert_called_once_with(
                self.fake_obj['hypervisor']['id'])

    def test_detail(self):
        req = fakes.HTTPRequest.blank('/os-hypervisors/detail',
                                      use_admin_context=True)
        resp = FakeResponse(self.fake_objs, '')

        with mock.patch.object(req, 'get_db_compute_node',
                               return_value=fake_compute_node
        ) as mock_get_db_node:
            self.controller.detail(req, resp)
            self.assertIn('os-pci:pci_stats', resp.obj['hypervisors'][0])
            self.assertEqual(pci_stats[0],
                             resp.obj['hypervisors'][0]['os-pci:pci_stats'][0])
            mock_get_db_node.assert_called_once_with(
                self.fake_objs['hypervisors'][0]['id'])


class PciControlletestV21(test.NoDBTestCase):
    def setUp(self):
        super(PciControlletestV21, self).setUp()
        self.controller = pci.PciController()

    def test_show(self):
        def fake_pci_device_get_by_id(context, id):
            return test_pci_device.fake_db_dev

        self.stub_out('nova.db.pci_device_get_by_id',
                      fake_pci_device_get_by_id)
        req = fakes.HTTPRequest.blank('/os-pci/1', use_admin_context=True)
        result = self.controller.show(req, '1')
        dist = {'pci_device': {'address': 'a',
                               'compute_node_id': 1,
                               'dev_id': 'i',
                               'extra_info': {},
                               'dev_type': fields.PciDeviceType.STANDARD,
                               'id': 1,
                               'server_uuid': None,
                               'label': 'l',
                               'product_id': 'p',
                               'status': 'available',
                               'vendor_id': 'v'}}
        self.assertEqual(dist, result)

    def test_show_error_id(self):
        def fake_pci_device_get_by_id(context, id):
            raise exception.PciDeviceNotFoundById(id=id)

        self.stub_out('nova.db.pci_device_get_by_id',
                      fake_pci_device_get_by_id)
        req = fakes.HTTPRequest.blank('/os-pci/0', use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, '0')

    def _fake_compute_node_get_all(self, context):
        return [objects.ComputeNode(id=1,
                                    service_id=1,
                                    host='fake',
                                    cpu_info='cpu_info',
                                    disk_available_least=100)]

    def _fake_pci_device_get_all_by_node(self, context, node):
        return [test_pci_device.fake_db_dev, test_pci_device.fake_db_dev_1]

    def test_index(self):
        self.stub_out('nova.db.pci_device_get_all_by_node',
                      self._fake_pci_device_get_all_by_node)

        with mock.patch.object(
                self.controller.host_api, 'compute_node_get_all',
                side_effect=self._fake_compute_node_get_all
        ) as mock_node_get_all:
            req = fakes.HTTPRequest.blank('/os-pci', use_admin_context=True)
            result = self.controller.index(req)
            dist = {'pci_devices': [test_pci_device.fake_db_dev,
                                    test_pci_device.fake_db_dev_1]}
            for i in range(len(result['pci_devices'])):
                self.assertEqual(dist['pci_devices'][i]['vendor_id'],
                                 result['pci_devices'][i]['vendor_id'])
                self.assertEqual(dist['pci_devices'][i]['id'],
                                 result['pci_devices'][i]['id'])
                self.assertEqual(dist['pci_devices'][i]['status'],
                                 result['pci_devices'][i]['status'])
                self.assertEqual(dist['pci_devices'][i]['address'],
                                 result['pci_devices'][i]['address'])
            self.assertEqual(1, mock_node_get_all.call_count)

    def test_detail(self):
        self.stub_out('nova.db.pci_device_get_all_by_node',
                      self._fake_pci_device_get_all_by_node)

        with mock.patch.object(
                self.controller.host_api, 'compute_node_get_all',
                side_effect=self._fake_compute_node_get_all
        ) as mock_node_get_all:
            req = fakes.HTTPRequest.blank('/os-pci/detail',
                                          use_admin_context=True)
            result = self.controller.detail(req)
            dist = {'pci_devices': [test_pci_device.fake_db_dev,
                                    test_pci_device.fake_db_dev_1]}
            for i in range(len(result['pci_devices'])):
                self.assertEqual(dist['pci_devices'][i]['vendor_id'],
                                 result['pci_devices'][i]['vendor_id'])
                self.assertEqual(dist['pci_devices'][i]['id'],
                                 result['pci_devices'][i]['id'])
                self.assertEqual(dist['pci_devices'][i]['label'],
                                 result['pci_devices'][i]['label'])
                self.assertEqual(dist['pci_devices'][i]['dev_id'],
                                 result['pci_devices'][i]['dev_id'])
            self.assertEqual(1, mock_node_get_all.call_count)


class PciControllerPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(PciControllerPolicyEnforcementV21, self).setUp()
        self.controller = pci.PciController()
        self.req = fakes.HTTPRequest.blank('')

    def _test_policy_failed(self, action, *args):
        rule_name = "os_compute_api:os-pci:%s" % action
        rule = {rule_name: "project:non_fake"}
        self.policy.set_rules(rule)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, getattr(self.controller, action),
            self.req, *args)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_policy_failed(self):
        self._test_policy_failed('index')

    def test_detail_policy_failed(self):
        self._test_policy_failed('detail')

    def test_show_policy_failed(self):
        self._test_policy_failed('show', 1)
