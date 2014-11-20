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

from nova import context
from nova import db
from nova.objects import instance
from nova.objects import pci_device
from nova.tests.unit.objects import test_objects

dev_dict = {
    'compute_node_id': 1,
    'address': 'a',
    'product_id': 'p',
    'vendor_id': 'v',
    'numa_node': 0,
    'status': 'available'}


fake_db_dev = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 1,
    'compute_node_id': 1,
    'address': 'a',
    'vendor_id': 'v',
    'product_id': 'p',
    'numa_node': 0,
    'dev_type': 't',
    'status': 'available',
    'dev_id': 'i',
    'label': 'l',
    'instance_uuid': None,
    'extra_info': '{}',
    'request_id': None,
    }


fake_db_dev_1 = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 2,
    'compute_node_id': 1,
    'address': 'a1',
    'vendor_id': 'v1',
    'product_id': 'p1',
    'numa_node': 1,
    'dev_type': 't',
    'status': 'available',
    'dev_id': 'i',
    'label': 'l',
    'instance_uuid': None,
    'extra_info': '{}',
    'request_id': None,
    }


class _TestPciDeviceObject(object):
    def _create_fake_instance(self):
        self.inst = instance.Instance()
        self.inst.uuid = 'fake-inst-uuid'
        self.inst.pci_devices = pci_device.PciDeviceList()

    def _create_fake_pci_device(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_by_addr')
        db.pci_device_get_by_addr(ctxt, 1, 'a').AndReturn(fake_db_dev)
        self.mox.ReplayAll()
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')

    def test_create_pci_device(self):
        self.pci_device = pci_device.PciDevice.create(dev_dict)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['compute_node_id', 'product_id', 'vendor_id',
                              'numa_node', 'status', 'address', 'extra_info']))

    def test_pci_device_extra_info(self):
        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['k1'] = 'v1'
        self.dev_dict['k2'] = 'v2'
        self.pci_device = pci_device.PciDevice.create(self.dev_dict)
        extra_value = self.pci_device.extra_info
        self.assertEqual(extra_value.get('k1'), 'v1')
        self.assertEqual(set(extra_value.keys()), set(('k1', 'k2')))
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['compute_node_id', 'address', 'product_id',
                              'vendor_id', 'numa_node', 'status',
                              'extra_info']))

    def test_update_device(self):
        self.pci_device = pci_device.PciDevice.create(dev_dict)
        self.pci_device.obj_reset_changes()
        changes = {'product_id': 'p2', 'vendor_id': 'v2'}
        self.pci_device.update_device(changes)
        self.assertEqual(self.pci_device.vendor_id, 'v2')
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['vendor_id', 'product_id']))

    def test_update_device_same_value(self):
        self.pci_device = pci_device.PciDevice.create(dev_dict)
        self.pci_device.obj_reset_changes()
        changes = {'product_id': 'p', 'vendor_id': 'v2'}
        self.pci_device.update_device(changes)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.vendor_id, 'v2')
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['vendor_id', 'product_id']))

    def test_get_by_dev_addr(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_by_addr')
        db.pci_device_get_by_addr(ctxt, 1, 'a').AndReturn(fake_db_dev)
        self.mox.ReplayAll()
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(), set())
        self.assertRemotes()

    def test_get_by_dev_id(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_by_id')
        db.pci_device_get_by_id(ctxt, 1).AndReturn(fake_db_dev)
        self.mox.ReplayAll()
        self.pci_device = pci_device.PciDevice.get_by_dev_id(ctxt, 1)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(), set())
        self.assertRemotes()

    def test_save(self):
        ctxt = context.get_admin_context()
        self._create_fake_pci_device()
        return_dev = dict(fake_db_dev, status='available',
                          instance_uuid='fake-uuid-3')
        self.pci_device.status = 'allocated'
        self.pci_device.instance_uuid = 'fake-uuid-2'
        expected_updates = dict(status='allocated',
                                instance_uuid='fake-uuid-2')
        self.mox.StubOutWithMock(db, 'pci_device_update')
        db.pci_device_update(ctxt, 1, 'a',
                             expected_updates).AndReturn(return_dev)
        self.mox.ReplayAll()
        self.pci_device.save(ctxt)
        self.assertEqual(self.pci_device.status, 'available')
        self.assertEqual(self.pci_device.instance_uuid,
                         'fake-uuid-3')
        self.assertRemotes()

    def test_save_no_extra_info(self):
        return_dev = dict(fake_db_dev, status='available',
                          instance_uuid='fake-uuid-3')

        def _fake_update(ctxt, node_id, addr, updates):
            self.extra_info = updates.get('extra_info')
            return return_dev

        ctxt = context.get_admin_context()
        self.stubs.Set(db, 'pci_device_update', _fake_update)
        self.pci_device = pci_device.PciDevice.create(dev_dict)
        self.pci_device.save(ctxt)
        self.assertEqual(self.extra_info, '{}')

    def test_save_removed(self):
        ctxt = context.get_admin_context()
        self._create_fake_pci_device()
        self.pci_device.status = 'removed'
        self.mox.StubOutWithMock(db, 'pci_device_destroy')
        db.pci_device_destroy(ctxt, 1, 'a')
        self.mox.ReplayAll()
        self.pci_device.save(ctxt)
        self.assertEqual(self.pci_device.status, 'deleted')
        self.assertRemotes()

    def test_save_deleted(self):
        def _fake_destroy(ctxt, node_id, addr):
            self.called = True

        def _fake_update(ctxt, node_id, addr, updates):
            self.called = True
        ctxt = context.get_admin_context()
        self.stubs.Set(db, 'pci_device_destroy', _fake_destroy)
        self.stubs.Set(db, 'pci_device_update', _fake_update)
        self._create_fake_pci_device()
        self.pci_device.status = 'deleted'
        self.called = False
        self.pci_device.save(ctxt)
        self.assertEqual(self.called, False)

    def test_update_numa_node(self):
        self.pci_device = pci_device.PciDevice.create(dev_dict)
        self.assertEqual(0, self.pci_device.numa_node)

        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['numa_node'] = '1'
        self.pci_device = pci_device.PciDevice.create(self.dev_dict)
        self.assertEqual(1, self.pci_device.numa_node)


class TestPciDeviceObject(test_objects._LocalTest,
                          _TestPciDeviceObject):
    pass


class TestPciDeviceObjectRemote(test_objects._RemoteTest,
                                _TestPciDeviceObject):
    pass


fake_pci_devs = [fake_db_dev, fake_db_dev_1]


class _TestPciDeviceListObject(object):
    def test_get_by_compute_node(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_all_by_node')
        db.pci_device_get_all_by_node(ctxt, 1).AndReturn(fake_pci_devs)
        self.mox.ReplayAll()
        devs = pci_device.PciDeviceList.get_by_compute_node(ctxt, 1)
        for i in range(len(fake_pci_devs)):
            self.assertIsInstance(devs[i], pci_device.PciDevice)
            self.assertEqual(fake_pci_devs[i]['vendor_id'], devs[i].vendor_id)
        self.assertRemotes()

    def test_get_by_instance_uuid(self):
        ctxt = context.get_admin_context()
        fake_db_1 = dict(fake_db_dev, address='a1',
                         status='allocated', instance_uuid='1')
        fake_db_2 = dict(fake_db_dev, address='a2',
                         status='allocated', instance_uuid='1')
        self.mox.StubOutWithMock(db, 'pci_device_get_all_by_instance_uuid')
        db.pci_device_get_all_by_instance_uuid(ctxt, '1').AndReturn(
            [fake_db_1, fake_db_2])
        self.mox.ReplayAll()
        devs = pci_device.PciDeviceList.get_by_instance_uuid(ctxt, '1')
        self.assertEqual(len(devs), 2)
        for i in range(len(fake_pci_devs)):
            self.assertIsInstance(devs[i], pci_device.PciDevice)
        self.assertEqual(devs[0].vendor_id, 'v')
        self.assertEqual(devs[1].vendor_id, 'v')
        self.assertRemotes()


class TestPciDeviceListObject(test_objects._LocalTest,
                                  _TestPciDeviceListObject):
    pass


class TestPciDeviceListObjectRemote(test_objects._RemoteTest,
                              _TestPciDeviceListObject):
    pass
