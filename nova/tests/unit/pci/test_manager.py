# Copyright (c) 2012 OpenStack Foundation
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

import copy

import mock
from oslo_serialization import jsonutils

import nova
from nova.compute import vm_states
from nova import context
from nova import objects
from nova.objects import fields
from nova.pci import manager
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.pci import fakes as pci_fakes


fake_pci = {
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'product_id': 'p',
    'vendor_id': 'v',
    'request_id': None,
    'status': fields.PciDeviceStatus.AVAILABLE,
    'numa_node': 0}
fake_pci_1 = dict(fake_pci, address='0000:00:00.2',
                  product_id='p1', vendor_id='v1')
fake_pci_2 = dict(fake_pci, address='0000:00:00.3')


fake_db_dev = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 1,
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'vendor_id': 'v',
    'product_id': 'p',
    'numa_node': 1,
    'dev_type': fields.PciDeviceType.STANDARD,
    'status': fields.PciDeviceStatus.AVAILABLE,
    'dev_id': 'i',
    'label': 'l',
    'instance_uuid': None,
    'extra_info': '{}',
    'request_id': None,
    }
fake_db_dev_1 = dict(fake_db_dev, vendor_id='v1',
                     product_id='p1', id=2,
                     address='0000:00:00.2',
                     numa_node=0)
fake_db_dev_2 = dict(fake_db_dev, id=3, address='0000:00:00.3',
                     numa_node=None)
fake_db_devs = [fake_db_dev, fake_db_dev_1, fake_db_dev_2]


fake_pci_requests = [
    {'count': 1,
     'spec': [{'vendor_id': 'v'}]},
    {'count': 1,
     'spec': [{'vendor_id': 'v1'}]}]


class PciDevTrackerTestCase(test.NoDBTestCase):
    def _create_fake_instance(self):
        self.inst = objects.Instance()
        self.inst.uuid = 'fake-inst-uuid'
        self.inst.pci_devices = objects.PciDeviceList()
        self.inst.vm_state = vm_states.ACTIVE
        self.inst.task_state = None
        self.inst.numa_topology = None

    def _fake_get_pci_devices(self, ctxt, node_id):
        return fake_db_devs[:]

    def _fake_pci_device_update(self, ctxt, node_id, address, value):
        self.update_called += 1
        self.called_values = value
        fake_return = copy.deepcopy(fake_db_dev)
        return fake_return

    def _fake_pci_device_destroy(self, ctxt, node_id, address):
        self.destroy_called += 1

    def _create_pci_requests_object(self, mock_get, requests):
        pci_reqs = []
        for request in requests:
            pci_req_obj = objects.InstancePCIRequest(count=request['count'],
                                                     spec=request['spec'])
            pci_reqs.append(pci_req_obj)
        mock_get.return_value = objects.InstancePCIRequests(requests=pci_reqs)

    def setUp(self):
        super(PciDevTrackerTestCase, self).setUp()
        self.fake_context = context.get_admin_context()
        self.stub_out('nova.db.pci_device_get_all_by_node',
            self._fake_get_pci_devices)
        # The fake_pci_whitelist must be called before creating the fake
        # devices
        patcher = pci_fakes.fake_pci_whitelist()
        self.addCleanup(patcher.stop)
        self._create_fake_instance()
        self.tracker = manager.PciDevTracker(self.fake_context, 1)

    def test_pcidev_tracker_create(self):
        self.assertEqual(len(self.tracker.pci_devs), 3)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 3)
        self.assertEqual(self.tracker.stale.keys(), [])
        self.assertEqual(len(self.tracker.stats.pools), 3)
        self.assertEqual(self.tracker.node_id, 1)

    @mock.patch.object(nova.objects.PciDeviceList, 'get_by_compute_node')
    def test_pcidev_tracker_create_no_nodeid(self, mock_get_cn):
        self.tracker = manager.PciDevTracker(self.fake_context)
        self.assertEqual(len(self.tracker.pci_devs), 0)
        self.assertFalse(mock_get_cn.called)

    @mock.patch.object(nova.objects.PciDeviceList, 'get_by_compute_node')
    def test_pcidev_tracker_create_with_nodeid(self, mock_get_cn):
        self.tracker = manager.PciDevTracker(self.fake_context, node_id=1)
        mock_get_cn.assert_called_once_with(self.fake_context, 1)

    @mock.patch('nova.pci.whitelist.Whitelist.device_assignable',
                return_value=True)
    def test_update_devices_from_hypervisor_resources(self, _mock_dev_assign):
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_2)]
        fake_pci_devs_json = jsonutils.dumps(fake_pci_devs)
        tracker = manager.PciDevTracker(self.fake_context)
        tracker.update_devices_from_hypervisor_resources(fake_pci_devs_json)
        self.assertEqual(2, len(tracker.pci_devs))

    def test_set_hvdev_new_dev(self):
        fake_pci_3 = dict(fake_pci, address='0000:00:00.4', vendor_id='v2')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_1),
                         copy.deepcopy(fake_pci_2), copy.deepcopy(fake_pci_3)]
        self.tracker._set_hvdevs(fake_pci_devs)
        self.assertEqual(len(self.tracker.pci_devs), 4)
        self.assertEqual(set([dev.address for
                              dev in self.tracker.pci_devs]),
                         set(['0000:00:00.1', '0000:00:00.2',
                              '0000:00:00.3', '0000:00:00.4']))
        self.assertEqual(set([dev.vendor_id for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1', 'v2']))

    def test_set_hvdev_changed(self):
        fake_pci_v2 = dict(fake_pci, address='0000:00:00.2', vendor_id='v1')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_2),
                         copy.deepcopy(fake_pci_v2)]
        self.tracker._set_hvdevs(fake_pci_devs)
        self.assertEqual(set([dev.vendor_id for
                             dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    def test_set_hvdev_remove(self):
        self.tracker._set_hvdevs([fake_pci])
        self.assertEqual(len([dev for dev in self.tracker.pci_devs
                              if dev.status == 'removed']),
                         2)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_set_hvdev_changed_stal(self, mock_get):
        self._create_pci_requests_object(mock_get,
            [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}])
        self.tracker._claim_instance(mock.sentinel.context, self.inst)
        fake_pci_3 = dict(fake_pci, address='0000:00:00.2', vendor_id='v2')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_2),
                         copy.deepcopy(fake_pci_3)]
        self.tracker._set_hvdevs(fake_pci_devs)
        self.assertEqual(len(self.tracker.stale), 1)
        self.assertEqual(self.tracker.stale['0000:00:00.2']['vendor_id'], 'v2')

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_update_pci_for_instance_active(self, mock_get):

        self._create_pci_requests_object(mock_get, fake_pci_requests)
        self.tracker.claim_instance(None, self.inst)
        self.assertEqual(len(self.tracker.claims[self.inst['uuid']]), 2)
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)
        self.assertEqual(len(self.tracker.allocations[self.inst['uuid']]), 2)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.assertEqual(free_devs[0].vendor_id, 'v')

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_update_pci_for_instance_fail(self, mock_get):
        pci_requests = copy.deepcopy(fake_pci_requests)
        pci_requests[0]['count'] = 4
        self._create_pci_requests_object(mock_get, pci_requests)
        self.tracker.claim_instance(None, self.inst)
        self.assertEqual(len(self.tracker.claims[self.inst['uuid']]), 0)
        devs = self.tracker.update_pci_for_instance(None,
                                                    self.inst,
                                                    sign=1)
        self.assertEqual(len(self.tracker.allocations[self.inst['uuid']]), 0)
        self.assertIsNone(devs)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_pci_claim_instance_with_numa(self, mock_get):
        fake_db_dev_3 = dict(fake_db_dev_1, id=4, address='0000:00:00.4')
        fake_devs_numa = copy.deepcopy(fake_db_devs)
        fake_devs_numa.append(fake_db_dev_3)
        self.tracker = manager.PciDevTracker(1)
        self.tracker._set_hvdevs(fake_devs_numa)
        pci_requests = copy.deepcopy(fake_pci_requests)[:1]
        pci_requests[0]['count'] = 2
        self._create_pci_requests_object(mock_get, pci_requests)
        self.inst.numa_topology = objects.InstanceNUMATopology(
                    cells=[objects.InstanceNUMACell(
                        id=1, cpuset=set([1, 2]), memory=512)])
        self.tracker.claim_instance(None, self.inst)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(2, len(free_devs))
        self.assertEqual('v1', free_devs[0].vendor_id)
        self.assertEqual('v1', free_devs[1].vendor_id)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_pci_claim_instance_with_numa_fail(self, mock_get):
        self._create_pci_requests_object(mock_get, fake_pci_requests)
        self.inst.numa_topology = objects.InstanceNUMATopology(
                    cells=[objects.InstanceNUMACell(
                        id=1, cpuset=set([1, 2]), memory=512)])
        self.assertIsNone(self.tracker.claim_instance(None, self.inst))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_update_pci_for_instance_deleted(self, mock_get):
        self._create_pci_requests_object(mock_get, fake_pci_requests)
        self.tracker.claim_instance(None, self.inst)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.inst.vm_state = vm_states.DELETED
        self.tracker.update_pci_for_instance(None, self.inst, -1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 3)
        self.assertEqual(set([dev.vendor_id for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_update_pci_for_migration_in(self, mock_get):
        self._create_pci_requests_object(mock_get, fake_pci_requests)
        self.tracker.update_pci_for_migration(None, self.inst)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.assertEqual(free_devs[0].vendor_id, 'v')

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_update_pci_for_migration_out(self, mock_get):
        self._create_pci_requests_object(mock_get, fake_pci_requests)
        self.tracker.update_pci_for_migration(None, self.inst)
        self.tracker.update_pci_for_migration(None, self.inst, sign=-1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 3)
        self.assertEqual(set([dev.vendor_id for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    def test_save(self):
        self.stub_out(
                'nova.db.pci_device_update',
                self._fake_pci_device_update)
        fake_pci_v3 = dict(fake_pci, address='0000:00:00.2', vendor_id='v3')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_2),
                         copy.deepcopy(fake_pci_v3)]
        self.tracker._set_hvdevs(fake_pci_devs)
        self.update_called = 0
        self.tracker.save(self.fake_context)
        self.assertEqual(self.update_called, 3)

    def test_save_removed(self):
        self.stub_out(
                'nova.db.pci_device_update',
                self._fake_pci_device_update)
        self.stub_out(
                'nova.db.pci_device_destroy',
                self._fake_pci_device_destroy)
        self.destroy_called = 0
        self.assertEqual(len(self.tracker.pci_devs), 3)
        dev = self.tracker.pci_devs[0]
        self.update_called = 0
        dev.remove()
        self.tracker.save(self.fake_context)
        self.assertEqual(len(self.tracker.pci_devs), 2)
        self.assertEqual(self.destroy_called, 1)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_clean_usage(self, mock_get):
        inst_2 = copy.copy(self.inst)
        inst_2.uuid = 'uuid5'
        migr = {'instance_uuid': 'uuid2', 'vm_state': vm_states.BUILDING}
        orph = {'uuid': 'uuid3', 'vm_state': vm_states.BUILDING}

        self._create_pci_requests_object(mock_get,
            [{'count': 1, 'spec': [{'vendor_id': 'v'}]}])
        self.tracker.claim_instance(None, self.inst)
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)
        self._create_pci_requests_object(mock_get,
            [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}])
        self.tracker.claim_instance(None, inst_2)
        self.tracker.update_pci_for_instance(None, inst_2, sign=1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.assertEqual(free_devs[0].vendor_id, 'v')

        self.tracker.clean_usage([self.inst], [migr], [orph])
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 2)
        self.assertEqual(
            set([dev.vendor_id for dev in free_devs]),
            set(['v', 'v1']))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_clean_usage_claims(self, mock_get):
        inst_2 = copy.copy(self.inst)
        inst_2.uuid = 'uuid5'
        migr = {'instance_uuid': 'uuid2', 'vm_state': vm_states.BUILDING}
        orph = {'uuid': 'uuid3', 'vm_state': vm_states.BUILDING}

        self._create_pci_requests_object(mock_get,
            [{'count': 1, 'spec': [{'vendor_id': 'v'}]}])
        self.tracker.claim_instance(None, self.inst)
        self.tracker.update_pci_for_instance(None, self.inst, sign=1)
        self._create_pci_requests_object(mock_get,
            [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}])
        self.tracker.update_pci_for_migration(None, inst_2)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 1)
        self.tracker.clean_usage([self.inst], [migr], [orph])
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(len(free_devs), 2)
        self.assertEqual(
            set([dev.vendor_id for dev in free_devs]),
            set(['v', 'v1']))

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_clean_usage_no_request_match_no_claims(self, mock_get):
        # Tests the case that there is no match for the request so the
        # claims mapping is set to None for the instance when the tracker
        # calls clean_usage.
        self._create_pci_requests_object(mock_get, [])
        self.tracker.update_pci_for_migration(None, instance=self.inst, sign=1)
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(3, len(free_devs))
        self.tracker.clean_usage([], [], [])
        free_devs = self.tracker.pci_stats.get_free_devs()
        self.assertEqual(3, len(free_devs))
        self.assertEqual(
            set([dev.address for dev in free_devs]),
            set(['0000:00:00.1', '0000:00:00.2', '0000:00:00.3']))


class PciGetInstanceDevs(test.TestCase):
    def setUp(self):
        super(PciGetInstanceDevs, self).setUp()
        self.fake_context = context.get_admin_context()

    @mock.patch('nova.db.instance_get')
    def test_get_devs_object(self, mock_instance_get):
        def _fake_obj_load_attr(foo, attrname):
            if attrname == 'pci_devices':
                self.load_attr_called = True
                foo.pci_devices = objects.PciDeviceList()

        inst = fakes.stub_instance(id='1')
        mock_instance_get.return_value = inst
        inst = objects.Instance.get_by_id(self.fake_context, '1',
                                          expected_attrs=[])
        self.stub_out(
                'nova.objects.Instance.obj_load_attr',
                _fake_obj_load_attr)

        self.load_attr_called = False
        manager.get_instance_pci_devs(inst)
        self.assertEqual(self.load_attr_called, True)
        mock_instance_get.assert_called_with(self.fake_context, '1',
                columns_to_join=[])
