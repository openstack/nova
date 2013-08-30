# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.objects import instance
from nova.objects import pci_device
from nova.pci import pci_manager
from nova.pci import pci_request
from nova import test
from nova.tests.api.openstack import fakes


fake_pci = {
    'compute_node_id': 1,
    'address': '0000:00:00.1',
    'product_id': 'p',
    'vendor_id': 'v',
    'status': 'available'}
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
    'product_id': 'p',
    'vendor_id': 'v',
    'status': 'available',
    'extra_info': '{}',
    }
fake_db_dev_1 = dict(fake_db_dev, vendor_id='v1',
                     product_id='p1', id=2,
                     address='0000:00:00.2')
fake_db_dev_2 = dict(fake_db_dev, id=3, address='0000:00:00.3')
fake_db_devs = [fake_db_dev, fake_db_dev_1, fake_db_dev_2]


fake_pci_requests = [
    {'count': 1,
     'spec': [{'vendor_id': 'v'}]},
    {'count': 1,
     'spec': [{'vendor_id': 'v1'}]}]


class PciDevTrackerTestCase(test.TestCase):
    def _create_fake_instance(self):
        self.inst = instance.Instance()
        self.inst.uuid = 'fake-inst-uuid'
        self.inst.pci_devices = pci_device.PciDeviceList()
        self.inst.vm_state = vm_states.ACTIVE
        self.inst.task_state = None

    def _fake_get_pci_devices(self, ctxt, node_id):
        return fake_db_devs[:]

    def _fake_pci_device_update(self, ctxt, node_id, address, value):
        self.update_called += 1
        self.called_values = value
        fake_return = copy.deepcopy(fake_db_dev)
        return fake_return

    def _fake_pci_device_destroy(self, ctxt, node_id, address):
        self.destroy_called += 1

    def _fake_get_instance_pci_requests(self, instance, prefix=''):
        return self.pci_requests

    def setUp(self):
        super(PciDevTrackerTestCase, self).setUp()
        self.stubs.Set(db, 'pci_device_get_all_by_node',
            self._fake_get_pci_devices)
        self.stubs.Set(pci_request, 'get_instance_pci_requests',
            self._fake_get_instance_pci_requests)
        self._create_fake_instance()
        self.tracker = pci_manager.PciDevTracker(1)

    def test_pcidev_tracker_create(self):
        self.assertEqual(len(self.tracker.pci_devs), 3)
        self.assertEqual(len(self.tracker.free_devs), 3)
        self.assertEqual(self.tracker.stale.keys(), [])
        self.assertEqual(len(self.tracker.stats.pools), 2)
        self.assertEqual(self.tracker.node_id, 1)

    def test_pcidev_tracker_create_no_nodeid(self):
        self.tracker = pci_manager.PciDevTracker()
        self.assertEqual(len(self.tracker.pci_devs), 0)

    def test_get_free_devices_for_requests(self):
        devs = self.tracker.get_free_devices_for_requests(fake_pci_requests)
        self.assertEqual(len(devs), 2)
        self.assertEqual(set([dev['vendor_id'] for dev in devs]),
                         set(['v1', 'v']))

    def test_get_free_devices_for_requests_empty(self):
        devs = self.tracker.get_free_devices_for_requests([])
        self.assertEqual(len(devs), 0)

    def test_get_free_devices_for_requests_meet_partial(self):
        requests = copy.deepcopy(fake_pci_requests)
        requests[1]['count'] = 2
        requests[1]['spec'][0]['vendor_id'] = 'v'
        devs = self.tracker.get_free_devices_for_requests(requests)
        self.assertEqual(len(devs), 0)

    def test_set_hvdev_new_dev(self):
        fake_pci_3 = dict(fake_pci, address='0000:00:00.4', vendor_id='v2')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_1),
                         copy.deepcopy(fake_pci_2), copy.deepcopy(fake_pci_3)]
        self.tracker.set_hvdevs(fake_pci_devs)
        self.assertEqual(len(self.tracker.pci_devs), 4)
        self.assertEqual(set([dev['address'] for
                              dev in self.tracker.pci_devs]),
                         set(['0000:00:00.1', '0000:00:00.2',
                              '0000:00:00.3', '0000:00:00.4']))
        self.assertEqual(set([dev['vendor_id'] for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1', 'v2']))

    def test_set_hvdev_changed(self):
        fake_pci_v2 = dict(fake_pci, address='0000:00:00.2', vendor_id='v1')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_2),
                         copy.deepcopy(fake_pci_v2)]
        self.tracker.set_hvdevs(fake_pci_devs)
        self.assertEqual(set([dev['vendor_id'] for
                             dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    def test_set_hvdev_remove(self):
        self.tracker.set_hvdevs([fake_pci])
        self.assertEqual(len([dev for dev in self.tracker.pci_devs
                              if dev['status'] == 'removed']),
                         2)

    def test_set_hvdev_changed_stal(self):
        self.pci_requests = [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}]
        self.tracker._claim_instance(self.inst)
        fake_pci_3 = dict(fake_pci, address='0000:00:00.2', vendor_id='v2')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_2),
                         copy.deepcopy(fake_pci_3)]
        self.tracker.set_hvdevs(fake_pci_devs)
        self.assertEqual(len(self.tracker.stale), 1)
        self.assertEqual(self.tracker.stale['0000:00:00.2']['vendor_id'], 'v2')

    def test_update_pci_for_instance_active(self):
        self.pci_requests = fake_pci_requests
        self.tracker.update_pci_for_instance(self.inst)
        self.assertEqual(len(self.tracker.free_devs), 1)
        self.assertEqual(self.tracker.free_devs[0]['vendor_id'], 'v')

    def test_update_pci_for_instance_fail(self):
        self.pci_requests = copy.deepcopy(fake_pci_requests)
        self.pci_requests[0]['count'] = 4
        self.assertRaises(exception.PciDeviceRequestFailed,
                          self.tracker.update_pci_for_instance,
                          self.inst)

    def test_update_pci_for_instance_deleted(self):
        self.pci_requests = fake_pci_requests
        self.tracker.update_pci_for_instance(self.inst)
        self.assertEqual(len(self.tracker.free_devs), 1)
        self.inst.vm_state = vm_states.DELETED
        self.tracker.update_pci_for_instance(self.inst)
        self.assertEqual(len(self.tracker.free_devs), 3)
        self.assertEqual(set([dev['vendor_id'] for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    def test_update_pci_for_instance_resize_source(self):
        self.pci_requests = fake_pci_requests
        self.tracker.update_pci_for_instance(self.inst)
        self.assertEqual(len(self.tracker.free_devs), 1)
        self.inst.task_state = task_states.RESIZE_MIGRATED
        self.tracker.update_pci_for_instance(self.inst)
        self.assertEqual(len(self.tracker.free_devs), 3)

    def test_update_pci_for_instance_resize_dest(self):
        self.pci_requests = fake_pci_requests
        self.tracker.update_pci_for_migration(self.inst)
        self.assertEqual(len(self.tracker.free_devs), 1)
        self.assertEqual(len(self.tracker.claims['fake-inst-uuid']), 2)
        self.assertFalse('fake-inst-uuid' in self.tracker.allocations)
        self.inst.task_state = task_states.RESIZE_FINISH
        self.tracker.update_pci_for_instance(self.inst)
        self.assertEqual(len(self.tracker.allocations['fake-inst-uuid']), 2)
        self.assertFalse('fake-inst-uuid' in self.tracker.claims)

    def test_update_pci_for_migration_in(self):
        self.pci_requests = fake_pci_requests
        self.tracker.update_pci_for_migration(self.inst)
        self.assertEqual(len(self.tracker.free_devs), 1)
        self.assertEqual(self.tracker.free_devs[0]['vendor_id'], 'v')

    def test_update_pci_for_migration_out(self):
        self.pci_requests = fake_pci_requests
        self.tracker.update_pci_for_migration(self.inst)
        self.tracker.update_pci_for_migration(self.inst, sign=-1)
        self.assertEqual(len(self.tracker.free_devs), 3)
        self.assertEqual(set([dev['vendor_id'] for
                              dev in self.tracker.pci_devs]),
                         set(['v', 'v1']))

    def test_save(self):
        self.stubs.Set(db, "pci_device_update", self._fake_pci_device_update)
        ctxt = context.get_admin_context()
        fake_pci_v3 = dict(fake_pci, address='0000:00:00.2', vendor_id='v3')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_2),
                         copy.deepcopy(fake_pci_v3)]
        self.tracker.set_hvdevs(fake_pci_devs)
        self.update_called = 0
        self.tracker.save(ctxt)
        self.assertEqual(self.update_called, 3)

    def test_save_removed(self):
        self.stubs.Set(db, "pci_device_update", self._fake_pci_device_update)
        self.stubs.Set(db, "pci_device_destroy", self._fake_pci_device_destroy)
        self.destroy_called = 0
        ctxt = context.get_admin_context()
        self.assertEqual(len(self.tracker.pci_devs), 3)
        dev = self.tracker.pci_devs.objects[0]
        self.update_called = 0
        dev.remove()
        self.tracker.save(ctxt)
        self.assertEqual(len(self.tracker.pci_devs), 2)
        self.assertEqual(self.destroy_called, 1)

    def test_set_compute_node_id(self):
        self.tracker = pci_manager.PciDevTracker()
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_1),
                         copy.deepcopy(fake_pci_2)]
        self.tracker.set_hvdevs(fake_pci_devs)
        self.tracker.set_compute_node_id(1)
        self.assertEqual(self.tracker.node_id, 1)
        self.assertEqual(self.tracker.pci_devs[0].compute_node_id, 1)
        fake_pci_3 = dict(fake_pci, address='0000:00:00.4', vendor_id='v2')
        fake_pci_devs = [copy.deepcopy(fake_pci), copy.deepcopy(fake_pci_1),
                         copy.deepcopy(fake_pci_3), copy.deepcopy(fake_pci_3)]
        self.tracker.set_hvdevs(fake_pci_devs)
        for dev in self.tracker.pci_devs:
            self.assertEqual(dev.compute_node_id, 1)

    def test_clean_usage(self):
        inst_2 = copy.copy(self.inst)
        inst_2.uuid = 'uuid5'
        inst = {'uuid': 'uuid1', 'vm_state': vm_states.BUILDING}
        migr = {'instance_uuid': 'uuid2', 'vm_state': vm_states.BUILDING}
        orph = {'uuid': 'uuid3', 'vm_state': vm_states.BUILDING}

        self.pci_requests = [{'count': 1, 'spec': [{'vendor_id': 'v'}]}]
        self.tracker.update_pci_for_instance(self.inst)
        self.pci_requests = [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}]
        self.tracker.update_pci_for_instance(inst_2)
        self.assertEqual(len(self.tracker.free_devs), 1)
        self.assertEqual(self.tracker.free_devs[0]['vendor_id'], 'v')

        self.tracker.clean_usage([self.inst], [migr], [orph])
        self.assertEqual(len(self.tracker.free_devs), 2)
        self.assertEqual(
            set([dev['vendor_id'] for dev in self.tracker.free_devs]),
            set(['v', 'v1']))

    def test_clean_usage_claims(self):
        inst_2 = copy.copy(self.inst)
        inst_2.uuid = 'uuid5'
        inst = {'uuid': 'uuid1', 'vm_state': vm_states.BUILDING}
        migr = {'instance_uuid': 'uuid2', 'vm_state': vm_states.BUILDING}
        orph = {'uuid': 'uuid3', 'vm_state': vm_states.BUILDING}

        self.pci_requests = [{'count': 1, 'spec': [{'vendor_id': 'v'}]}]
        self.tracker.update_pci_for_instance(self.inst)
        self.pci_requests = [{'count': 1, 'spec': [{'vendor_id': 'v1'}]}]
        self.tracker.update_pci_for_migration(inst_2)
        self.assertEqual(len(self.tracker.free_devs), 1)
        self.tracker.clean_usage([self.inst], [migr], [orph])
        self.assertEqual(len(self.tracker.free_devs), 2)
        self.assertEqual(
            set([dev['vendor_id'] for dev in self.tracker.free_devs]),
            set(['v', 'v1']))


class PciGetInstanceDevs(test.TestCase):
    def test_get_devs_non_object(self):
        def _fake_pci_device_get_by_instance_uuid(context, uuid):
            self._get_by_uuid = True
            return []

        instance = fakes.stub_instance(id=1)
        self.stubs.Set(db, 'pci_device_get_all_by_instance_uuid',
            _fake_pci_device_get_by_instance_uuid)
        self._get_by_uuid = False
        devices = pci_manager.get_instance_pci_devs(instance)
        self.assertEqual(self._get_by_uuid, True)

    def test_get_devs_object(self):
        def _fake_obj_load_attr(foo, attrname):
            if attrname == 'pci_devices':
                self.load_attr_called = True
                foo.pci_devices = None

        inst = fakes.stub_instance(id='1')
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_get')
        db.instance_get(ctxt, '1', columns_to_join=[]
                        ).AndReturn(inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_id(ctxt, '1', expected_attrs=[])
        self.stubs.Set(instance.Instance, 'obj_load_attr',
            _fake_obj_load_attr)

        self.load_attr_called = False
        devices = pci_manager.get_instance_pci_devs(inst)
        self.assertEqual(self.load_attr_called, True)
