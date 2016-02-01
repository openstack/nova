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
from oslo_utils import timeutils

from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import fields
from nova.objects import instance
from nova.objects import pci_device
from nova import test
from nova.tests.unit.objects import test_objects

dev_dict = {
    'compute_node_id': 1,
    'address': 'a',
    'product_id': 'p',
    'vendor_id': 'v',
    'numa_node': 0,
    'dev_type': fields.PciDeviceType.STANDARD,
    'parent_addr': None,
    'status': fields.PciDeviceStatus.AVAILABLE}


fake_db_dev = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'parent_addr': None,
    'id': 1,
    'compute_node_id': 1,
    'address': 'a',
    'vendor_id': 'v',
    'product_id': 'p',
    'numa_node': 0,
    'dev_type': fields.PciDeviceType.STANDARD,
    'status': fields.PciDeviceStatus.AVAILABLE,
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
    'parent_addr': 'a',
    'compute_node_id': 1,
    'address': 'a1',
    'vendor_id': 'v1',
    'product_id': 'p1',
    'numa_node': 1,
    'dev_type': fields.PciDeviceType.STANDARD,
    'status': fields.PciDeviceStatus.AVAILABLE,
    'dev_id': 'i',
    'label': 'l',
    'instance_uuid': None,
    'extra_info': '{}',
    'request_id': None,
    }


fake_db_dev_old = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 2,
    'parent_addr': None,
    'compute_node_id': 1,
    'address': 'a1',
    'vendor_id': 'v1',
    'product_id': 'p1',
    'numa_node': 1,
    'dev_type': fields.PciDeviceType.SRIOV_VF,
    'status': fields.PciDeviceStatus.AVAILABLE,
    'dev_id': 'i',
    'label': 'l',
    'instance_uuid': None,
    'extra_info': '{"phys_function": "blah"}',
    'request_id': None,
    }


class _TestPciDeviceObject(object):
    def _create_fake_instance(self):
        self.inst = instance.Instance()
        self.inst.uuid = 'fake-inst-uuid'
        self.inst.pci_devices = pci_device.PciDeviceList()

    def _create_fake_pci_device(self, ctxt=None):
        if not ctxt:
            ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_by_addr')
        db.pci_device_get_by_addr(ctxt, 1, 'a').AndReturn(fake_db_dev)
        self.mox.ReplayAll()
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')

    def test_create_pci_device(self):
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['compute_node_id', 'product_id', 'vendor_id',
                              'numa_node', 'status', 'address', 'extra_info',
                              'dev_type', 'parent_addr']))

    def test_pci_device_extra_info(self):
        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['k1'] = 'v1'
        self.dev_dict['k2'] = 'v2'
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        extra_value = self.pci_device.extra_info
        self.assertEqual(extra_value.get('k1'), 'v1')
        self.assertEqual(set(extra_value.keys()), set(('k1', 'k2')))
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['compute_node_id', 'address', 'product_id',
                              'vendor_id', 'numa_node', 'status',
                              'extra_info', 'dev_type', 'parent_addr']))

    def test_update_device(self):
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.pci_device.obj_reset_changes()
        changes = {'product_id': 'p2', 'vendor_id': 'v2'}
        self.pci_device.update_device(changes)
        self.assertEqual(self.pci_device.vendor_id, 'v2')
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['vendor_id', 'product_id', 'parent_addr']))

    def test_update_device_same_value(self):
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.pci_device.obj_reset_changes()
        changes = {'product_id': 'p', 'vendor_id': 'v2'}
        self.pci_device.update_device(changes)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.vendor_id, 'v2')
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['vendor_id', 'product_id', 'parent_addr']))

    def test_get_by_dev_addr(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_by_addr')
        db.pci_device_get_by_addr(ctxt, 1, 'a').AndReturn(fake_db_dev)
        self.mox.ReplayAll()
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(), set())

    def test_get_by_dev_id(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_by_id')
        db.pci_device_get_by_id(ctxt, 1).AndReturn(fake_db_dev)
        self.mox.ReplayAll()
        self.pci_device = pci_device.PciDevice.get_by_dev_id(ctxt, 1)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(), set())

    def test_from_db_obj_pre_1_4_format(self):
        ctxt = context.get_admin_context()
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_db_dev_old)
        self.assertEqual('blah', dev.parent_addr)
        self.assertEqual({'phys_function': 'blah'}, dev.extra_info)

    def test_from_db_obj_pre_1_5_format(self):
        ctxt = context.get_admin_context()
        fake_dev_pre_1_5 = copy.deepcopy(fake_db_dev_old)
        fake_dev_pre_1_5['status'] = fields.PciDeviceStatus.UNAVAILABLE
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_dev_pre_1_5)
        self.assertRaises(exception.ObjectActionError,
                          dev.obj_to_primitive, '1.4')

    def test_save_empty_parent_addr(self):
        ctxt = context.get_admin_context()
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_db_dev)
        dev.parent_addr = None
        with mock.patch.object(db, 'pci_device_update',
                               return_value=fake_db_dev):
            dev.save()
            self.assertIsNone(dev.parent_addr)
            self.assertEqual({}, dev.extra_info)

    def test_save(self):
        ctxt = context.get_admin_context()
        self._create_fake_pci_device(ctxt=ctxt)
        return_dev = dict(fake_db_dev, status=fields.PciDeviceStatus.AVAILABLE,
                          instance_uuid='fake-uuid-3')
        self.pci_device.status = fields.PciDeviceStatus.ALLOCATED
        self.pci_device.instance_uuid = 'fake-uuid-2'
        expected_updates = dict(status=fields.PciDeviceStatus.ALLOCATED,
                                instance_uuid='fake-uuid-2')
        self.mox.StubOutWithMock(db, 'pci_device_update')
        db.pci_device_update(ctxt, 1, 'a',
                             expected_updates).AndReturn(return_dev)
        self.mox.ReplayAll()
        self.pci_device.save()
        self.assertEqual(self.pci_device.status,
                         fields.PciDeviceStatus.AVAILABLE)
        self.assertEqual(self.pci_device.instance_uuid,
                         'fake-uuid-3')

    def test_save_no_extra_info(self):
        return_dev = dict(fake_db_dev, status=fields.PciDeviceStatus.AVAILABLE,
                          instance_uuid='fake-uuid-3')

        def _fake_update(ctxt, node_id, addr, updates):
            self.extra_info = updates.get('extra_info')
            return return_dev

        ctxt = context.get_admin_context()
        self.stub_out('nova.db.pci_device_update', _fake_update)
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.pci_device._context = ctxt
        self.pci_device.save()
        self.assertEqual(self.extra_info, '{}')

    def test_save_removed(self):
        ctxt = context.get_admin_context()
        self._create_fake_pci_device(ctxt=ctxt)
        self.pci_device.status = fields.PciDeviceStatus.REMOVED
        self.mox.StubOutWithMock(db, 'pci_device_destroy')
        db.pci_device_destroy(ctxt, 1, 'a')
        self.mox.ReplayAll()
        self.pci_device.save()
        self.assertEqual(self.pci_device.status,
                         fields.PciDeviceStatus.DELETED)

    def test_save_deleted(self):
        def _fake_destroy(ctxt, node_id, addr):
            self.called = True

        def _fake_update(ctxt, node_id, addr, updates):
            self.called = True
        self.stub_out('nova.db.pci_device_destroy', _fake_destroy)
        self.stub_out('nova.db.pci_device_update', _fake_update)
        self._create_fake_pci_device()
        self.pci_device.status = fields.PciDeviceStatus.DELETED
        self.called = False
        self.pci_device.save()
        self.assertFalse(self.called)

    @mock.patch.object(objects.Service, 'get_minimum_version', return_value=4)
    def test_save_migrate_parent_addr(self, get_min_ver_mock):
        ctxt = context.get_admin_context()
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_db_dev_old)
        with mock.patch.object(db, 'pci_device_update',
                               return_value=fake_db_dev_old) as update_mock:
            dev.save()
            update_mock.assert_called_once_with(
                ctxt, dev.compute_node_id, dev.address,
                {'extra_info': '{}', 'parent_addr': 'blah'})

    @mock.patch.object(objects.Service, 'get_minimum_version', return_value=4)
    def test_save_migrate_parent_addr_updated(self, get_min_ver_mock):
        ctxt = context.get_admin_context()
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_db_dev_old)
        # Note that the pci manager code will never update parent_addr alone,
        # but we want to make it future proof so we guard against it
        dev.parent_addr = 'doh!'
        with mock.patch.object(db, 'pci_device_update',
                               return_value=fake_db_dev_old) as update_mock:
            dev.save()
            update_mock.assert_called_once_with(
                ctxt, dev.compute_node_id, dev.address,
                {'extra_info': '{}', 'parent_addr': 'doh!'})

    @mock.patch.object(objects.Service, 'get_minimum_version', return_value=2)
    def test_save_dont_migrate_parent_addr(self, get_min_ver_mock):
        ctxt = context.get_admin_context()
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_db_dev_old)
        dev.extra_info['other'] = "blahtoo"
        with mock.patch.object(db, 'pci_device_update',
                               return_value=fake_db_dev_old) as update_mock:
            dev.save()
            self.assertEqual("blah",
                             update_mock.call_args[0][3]['parent_addr'])
            self.assertIn("phys_function",
                          update_mock.call_args[0][3]['extra_info'])
            self.assertIn("other",
                          update_mock.call_args[0][3]['extra_info'])

    def test_update_numa_node(self):
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.assertEqual(0, self.pci_device.numa_node)

        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['numa_node'] = '1'
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        self.assertEqual(1, self.pci_device.numa_node)

    def test_pci_device_equivalent(self):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        self.assertEqual(pci_device1, pci_device2)

    def test_pci_device_equivalent_with_ignore_field(self):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2.updated_at = timeutils.utcnow()
        self.assertEqual(pci_device1, pci_device2)

    def test_pci_device_not_equivalent1(self):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        dev_dict2 = copy.copy(dev_dict)
        dev_dict2['address'] = 'b'
        pci_device2 = pci_device.PciDevice.create(None, dev_dict2)
        self.assertNotEqual(pci_device1, pci_device2)

    def test_pci_device_not_equivalent2(self):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        delattr(pci_device2, 'address')
        self.assertNotEqual(pci_device1, pci_device2)

    def test_pci_device_not_equivalent_with_none(self):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        pci_device1.instance_uuid = 'aaa'
        pci_device2.instance_uuid = None
        self.assertNotEqual(pci_device1, pci_device2)

    def test_claim_device(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst)
        self.assertEqual(devobj.status,
                         fields.PciDeviceStatus.CLAIMED)
        self.assertEqual(devobj.instance_uuid,
                         self.inst.uuid)
        self.assertEqual(len(self.inst.pci_devices), 0)

    def test_claim_device_fail(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.status = fields.PciDeviceStatus.ALLOCATED
        self.assertRaises(exception.PciDeviceInvalidStatus,
                          devobj.claim, self.inst)

    def test_allocate_device(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst)
        devobj.allocate(self.inst)
        self.assertEqual(devobj.status,
                         fields.PciDeviceStatus.ALLOCATED)
        self.assertEqual(devobj.instance_uuid, 'fake-inst-uuid')
        self.assertEqual(len(self.inst.pci_devices), 1)
        self.assertEqual(self.inst.pci_devices[0].vendor_id,
                         'v')
        self.assertEqual(self.inst.pci_devices[0].status,
                         fields.PciDeviceStatus.ALLOCATED)

    def test_allocate_device_fail_status(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.status = 'removed'
        self.assertRaises(exception.PciDeviceInvalidStatus,
                          devobj.allocate, self.inst)

    def test_allocate_device_fail_owner(self):
        self._create_fake_instance()
        inst_2 = instance.Instance()
        inst_2.uuid = 'fake-inst-uuid-2'
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst)
        self.assertRaises(exception.PciDeviceInvalidOwner,
                          devobj.allocate, inst_2)

    def test_free_claimed_device(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst)
        devobj.free(self.inst)
        self.assertEqual(devobj.status,
                         fields.PciDeviceStatus.AVAILABLE)
        self.assertIsNone(devobj.instance_uuid)

    def test_free_allocated_device(self):
        self._create_fake_instance()
        ctx = context.get_admin_context()
        devobj = pci_device.PciDevice._from_db_object(
                ctx, pci_device.PciDevice(), fake_db_dev)
        devobj.claim(self.inst)
        devobj.allocate(self.inst)
        self.assertEqual(len(self.inst.pci_devices), 1)
        devobj.free(self.inst)
        self.assertEqual(len(self.inst.pci_devices), 0)
        self.assertEqual(devobj.status,
                         fields.PciDeviceStatus.AVAILABLE)
        self.assertIsNone(devobj.instance_uuid)

    def test_free_device_fail(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.status = fields.PciDeviceStatus.REMOVED
        self.assertRaises(exception.PciDeviceInvalidStatus, devobj.free)

    def test_remove_device(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.remove()
        self.assertEqual(devobj.status, fields.PciDeviceStatus.REMOVED)
        self.assertIsNone(devobj.instance_uuid)

    def test_remove_device_fail(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst)
        self.assertRaises(exception.PciDeviceInvalidStatus, devobj.remove)


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

    def test_get_by_instance_uuid(self):
        ctxt = context.get_admin_context()
        fake_db_1 = dict(fake_db_dev, address='a1',
                         status=fields.PciDeviceStatus.ALLOCATED,
                         instance_uuid='1')
        fake_db_2 = dict(fake_db_dev, address='a2',
                         status=fields.PciDeviceStatus.ALLOCATED,
                         instance_uuid='1')
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


class TestPciDeviceListObject(test_objects._LocalTest,
                                  _TestPciDeviceListObject):
    pass


class TestPciDeviceListObjectRemote(test_objects._RemoteTest,
                              _TestPciDeviceListObject):
    pass


class _TestSRIOVPciDeviceObject(object):
    def _create_pci_devices(self, vf_product_id=1515, pf_product_id=1528,
                            num_pfs=2, num_vfs=8):
        self.sriov_pf_devices = []
        for dev in range(num_pfs):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:81:00.%d' % dev,
                       'vendor_id': '8086',
                       'product_id': '%d' % pf_product_id,
                       'status': 'available',
                       'request_id': None,
                       'dev_type': fields.PciDeviceType.SRIOV_PF,
                       'parent_addr': None,
                       'numa_node': 0}
            pci_dev_obj = objects.PciDevice.create(None, pci_dev)
            pci_dev_obj.id = num_pfs + 81
            self.sriov_pf_devices.append(pci_dev_obj)

        self.sriov_vf_devices = []
        for dev in range(num_vfs):
            pci_dev = {'compute_node_id': 1,
                       'address': '0000:81:10.%d' % dev,
                       'vendor_id': '8086',
                       'product_id': '%d' % vf_product_id,
                       'status': 'available',
                       'request_id': None,
                       'dev_type': fields.PciDeviceType.SRIOV_VF,
                       'parent_addr': '0000:81:00.%d' % int(dev / 4),
                       'numa_node': 0}
            pci_dev_obj = objects.PciDevice.create(None, pci_dev)
            pci_dev_obj.id = num_vfs + 1
            self.sriov_vf_devices.append(pci_dev_obj)

    def _create_fake_instance(self):
        self.inst = instance.Instance()
        self.inst.uuid = 'fake-inst-uuid'
        self.inst.pci_devices = pci_device.PciDeviceList()

    def _create_fake_pci_device(self, ctxt=None):
        if not ctxt:
            ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'pci_device_get_by_addr')
        db.pci_device_get_by_addr(ctxt, 1, 'a').AndReturn(fake_db_dev)
        self.mox.ReplayAll()
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')

    def _fake_get_by_parent_address(self, ctxt, node_id, addr):
        vf_devs = []
        for dev in self.sriov_vf_devices:
            if dev.parent_addr == addr:
                vf_devs.append(dev)
        return vf_devs

    def _fake_pci_device_get_by_addr(self, ctxt, id, addr):
        for dev in self.sriov_pf_devices:
            if dev.address == addr:
                return dev

    def test_claim_PF(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDeviceList, 'get_by_parent_address',
                               side_effect=self._fake_get_by_parent_address):
            self._create_pci_devices()
            devobj = self.sriov_pf_devices[0]
            devobj.claim(self.inst)
            self.assertEqual(devobj.status,
                             fields.PciDeviceStatus.CLAIMED)
            self.assertEqual(devobj.instance_uuid,
                             self.inst.uuid)
            self.assertEqual(len(self.inst.pci_devices), 0)
            # check if the all the dependants are UNCLAIMABLE
            self.assertTrue(all(
                 [dev.status == fields.PciDeviceStatus.UNCLAIMABLE for
                  dev in self._fake_get_by_parent_address(None, None,
                                        self.sriov_pf_devices[0].address)]))

    def test_claim_VF(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDevice, 'get_by_dev_addr',
                               side_effect=self._fake_pci_device_get_by_addr):
            self._create_pci_devices()
            devobj = self.sriov_vf_devices[0]
            devobj.claim(self.inst)
            self.assertEqual(devobj.status,
                             fields.PciDeviceStatus.CLAIMED)
            self.assertEqual(devobj.instance_uuid,
                             self.inst.uuid)
            self.assertEqual(len(self.inst.pci_devices), 0)

            # check if parent device status has been changed to UNCLAIMABLE
            parent = self._fake_pci_device_get_by_addr(None, None,
                                                       devobj.parent_addr)
            self.assertTrue(fields.PciDeviceStatus.UNCLAIMABLE, parent.status)

    def test_allocate_PF(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDeviceList, 'get_by_parent_address',
                               side_effect=self._fake_get_by_parent_address):
            self._create_pci_devices()
            devobj = self.sriov_pf_devices[0]
            devobj.claim(self.inst)
            devobj.allocate(self.inst)
            self.assertEqual(devobj.status,
                             fields.PciDeviceStatus.ALLOCATED)
            self.assertEqual(devobj.instance_uuid,
                             self.inst.uuid)
            self.assertEqual(len(self.inst.pci_devices), 1)
            # check if the all the dependants are UNAVAILABLE
            self.assertTrue(all(
                 [dev.status == fields.PciDeviceStatus.UNAVAILABLE for
                  dev in self._fake_get_by_parent_address(None, None,
                                        self.sriov_pf_devices[0].address)]))

    def test_allocate_VF(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDevice, 'get_by_dev_addr',
                               side_effect=self._fake_pci_device_get_by_addr):
            self._create_pci_devices()
            devobj = self.sriov_vf_devices[0]
            devobj.claim(self.inst)
            devobj.allocate(self.inst)
            self.assertEqual(devobj.status,
                             fields.PciDeviceStatus.ALLOCATED)
            self.assertEqual(devobj.instance_uuid,
                             self.inst.uuid)
            self.assertEqual(len(self.inst.pci_devices), 1)

            # check if parent device status has been changed to UNAVAILABLE
            parent = self._fake_pci_device_get_by_addr(None, None,
                                                       devobj.parent_addr)
            self.assertTrue(fields.PciDeviceStatus.UNAVAILABLE, parent.status)

    def test_claim_PF_fail(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDeviceList, 'get_by_parent_address',
                               side_effect=self._fake_get_by_parent_address):
            self._create_pci_devices()
            devobj = self.sriov_pf_devices[0]
            self.sriov_vf_devices[0].status = fields.PciDeviceStatus.CLAIMED

            self.assertRaises(exception.PciDeviceVFInvalidStatus,
                              devobj.claim, self.inst)

    def test_claim_VF_fail(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDevice, 'get_by_dev_addr',
                               side_effect=self._fake_pci_device_get_by_addr):
            self._create_pci_devices()
            devobj = self.sriov_vf_devices[0]
            parent = self._fake_pci_device_get_by_addr(None, None,
                                                       devobj.parent_addr)
            parent.status = fields.PciDeviceStatus.CLAIMED

            self.assertRaises(exception.PciDevicePFInvalidStatus,
                              devobj.claim, self.inst)

    def test_allocate_PF_fail(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDeviceList, 'get_by_parent_address',
                               side_effect=self._fake_get_by_parent_address):
            self._create_pci_devices()
            devobj = self.sriov_pf_devices[0]
            self.sriov_vf_devices[0].status = fields.PciDeviceStatus.CLAIMED

            self.assertRaises(exception.PciDeviceVFInvalidStatus,
                              devobj.allocate, self.inst)

    def test_allocate_VF_fail(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDevice, 'get_by_dev_addr',
                               side_effect=self._fake_pci_device_get_by_addr):
            self._create_pci_devices()
            devobj = self.sriov_vf_devices[0]
            parent = self._fake_pci_device_get_by_addr(None, None,
                                                       devobj.parent_addr)
            parent.status = fields.PciDeviceStatus.CLAIMED

            self.assertRaises(exception.PciDevicePFInvalidStatus,
                              devobj.allocate, self.inst)

    def test_free_allocated_PF(self):
        self._create_fake_instance()
        with mock.patch.object(objects.PciDeviceList, 'get_by_parent_address',
                               side_effect=self._fake_get_by_parent_address):
            self._create_pci_devices()
            devobj = self.sriov_pf_devices[0]
            devobj.claim(self.inst)
            devobj.allocate(self.inst)
            devobj.free(self.inst)
            self.assertEqual(devobj.status,
                             fields.PciDeviceStatus.AVAILABLE)
            self.assertIsNone(devobj.instance_uuid)
            # check if the all the dependants are AVAILABLE
            self.assertTrue(all(
                 [dev.status == fields.PciDeviceStatus.AVAILABLE for
                  dev in self._fake_get_by_parent_address(None, None,
                                        self.sriov_pf_devices[0].address)]))

    def test_free_allocated_VF(self):
        self._create_fake_instance()
        with test.nested(
            mock.patch.object(objects.PciDevice, 'get_by_dev_addr',
                               side_effect=self._fake_pci_device_get_by_addr),
            mock.patch.object(objects.PciDeviceList, 'get_by_parent_address',
                               side_effect=self._fake_get_by_parent_address)):
            self._create_pci_devices()
            vf = self.sriov_vf_devices[0]
            dependents = self._fake_get_by_parent_address(None, None,
                                                          vf.parent_addr)
            for devobj in dependents:
                devobj.claim(self.inst)
                devobj.allocate(self.inst)
                self.assertEqual(devobj.status,
                                 fields.PciDeviceStatus.ALLOCATED)
            for devobj in dependents[:3]:
                devobj.free(self.inst)
                # check if parent device status is still UNAVAILABLE
                parent = self._fake_pci_device_get_by_addr(None, None,
                                                           devobj.parent_addr)
                self.assertTrue(fields.PciDeviceStatus.UNAVAILABLE,
                                parent.status)
            for devobj in dependents[3:]:
                devobj.free(self.inst)
                # check if parent device status is now AVAILABLE
                parent = self._fake_pci_device_get_by_addr(None, None,
                                                           devobj.parent_addr)
                self.assertTrue(fields.PciDeviceStatus.AVAILABLE,
                                parent.status)


class TestSRIOVPciDeviceListObject(test_objects._LocalTest,
                                  _TestSRIOVPciDeviceObject):
    pass


class TestSRIOVPciDeviceListObjectRemote(test_objects._RemoteTest,
                              _TestSRIOVPciDeviceObject):
    pass
