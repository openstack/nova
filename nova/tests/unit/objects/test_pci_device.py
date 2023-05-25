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
from unittest import mock

from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova import context
from nova.db.main import api as db
from nova.db.main import models as db_models
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
    'status': fields.PciDeviceStatus.AVAILABLE,
    'parent_addr': None,
}


fake_db_dev = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'parent_addr': None,
    'id': 1,
    'uuid': uuids.pci_dev1,
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
    'uuid': uuids.pci_dev2,
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
    'uuid': uuids.pci_dev2,
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
        self.inst.uuid = uuids.instance
        self.inst.pci_devices = pci_device.PciDeviceList()

    @mock.patch.object(db, 'pci_device_get_by_addr')
    def _create_fake_pci_device(self, mock_get, ctxt=None):
        if not ctxt:
            ctxt = context.get_admin_context()
        mock_get.return_value = fake_db_dev
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')
        mock_get.assert_called_once_with(ctxt, 1, 'a')

    def test_create_pci_device(self):
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['compute_node_id', 'product_id', 'vendor_id',
                              'numa_node', 'status', 'address', 'extra_info',
                              'dev_type', 'parent_addr', 'uuid']))

    def test_pci_device_extra_info(self):
        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['k1'] = 'v1'
        self.dev_dict['k2'] = 'v2'
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        extra_value = self.pci_device.extra_info
        self.assertEqual(extra_value.get('k1'), self.dev_dict['k1'])
        self.assertEqual(set(extra_value.keys()), set(('k1', 'k2')))
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['compute_node_id', 'address', 'product_id',
                              'vendor_id', 'numa_node', 'status', 'uuid',
                              'extra_info', 'dev_type', 'parent_addr']))

    def test_pci_device_extra_info_with_dict(self):
        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['k1'] = {'sub_k1': ['val1', 'val2']}
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        extra_value = self.pci_device.extra_info
        self.assertEqual(jsonutils.loads(extra_value.get('k1')),
                         self.dev_dict['k1'])
        self.assertEqual(set(extra_value.keys()), set(['k1']))
        self.assertEqual(self.pci_device.obj_what_changed(),
                         set(['compute_node_id', 'address', 'product_id',
                              'vendor_id', 'numa_node', 'status', 'uuid',
                              'extra_info', 'dev_type', 'parent_addr']))

    def test_pci_device_extra_info_card_serial_number(self):
        self.dev_dict = copy.copy(dev_dict)
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        self.assertIsNone(self.pci_device.card_serial_number)

        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['capabilities'] = {'vpd': {'card_serial_number': '42'}}
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        self.assertEqual(self.pci_device.card_serial_number, '42')

    def test_pci_device_extra_info_network_capabilities(self):
        self.dev_dict = copy.copy(dev_dict)
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        self.assertEqual(self.pci_device.network_caps, [])

        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['capabilities'] = {'network': ['sg', 'tso', 'tx']}
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        self.assertEqual(self.pci_device.network_caps, ['sg', 'tso', 'tx'])

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

    @mock.patch.object(db, 'pci_device_get_by_addr')
    def test_get_by_dev_addr(self, mock_get):
        ctxt = context.get_admin_context()
        mock_get.return_value = fake_db_dev
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(), set())
        mock_get.assert_called_once_with(ctxt, 1, 'a')

    @mock.patch.object(db, 'pci_device_get_by_id')
    def test_get_by_dev_id(self, mock_get):
        ctxt = context.get_admin_context()
        mock_get.return_value = fake_db_dev
        self.pci_device = pci_device.PciDevice.get_by_dev_id(ctxt, 1)
        self.assertEqual(self.pci_device.product_id, 'p')
        self.assertEqual(self.pci_device.obj_what_changed(), set())
        mock_get.assert_called_once_with(ctxt, 1)

    def test_from_db_obj_pre_1_5_format(self):
        ctxt = context.get_admin_context()
        fake_dev_pre_1_5 = copy.deepcopy(fake_db_dev_old)
        fake_dev_pre_1_5['status'] = fields.PciDeviceStatus.UNAVAILABLE
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_dev_pre_1_5)
        self.assertRaises(exception.ObjectActionError,
                          dev.obj_to_primitive, '1.4')

    @mock.patch.object(objects.PciDevice, '_create_uuid',
                       return_value=uuids.pci_dev1)
    def test_from_db_obj_missing_uuid(self, mock_create_uuid):
        """Ensure a UUID is generated if it's not present."""
        ctxt = context.get_admin_context()
        fake_dev_no_uuid = copy.deepcopy(fake_db_dev)
        fake_dev_no_uuid['uuid'] = None

        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_dev_no_uuid)

        # UUID should have been populated
        self.assertIn('uuid', dev)
        self.assertIsNotNone(dev.uuid)
        self.assertEqual(1, mock_create_uuid.call_count)

    def test_dev_type_vdpa_1_6_fails(self):
        ctxt = context.get_admin_context()
        fake_dev = copy.deepcopy(fake_db_dev)
        fake_dev['dev_type'] = fields.PciDeviceType.VDPA
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_dev)
        self.assertRaises(exception.ObjectActionError,
                          dev.obj_to_primitive, '1.6')

    def test_dev_type_vdpa_1_6(self):
        ctxt = context.get_admin_context()
        fake_dev = copy.deepcopy(fake_db_dev)
        fake_dev['dev_type'] = fields.PciDeviceType.STANDARD
        dev = pci_device.PciDevice._from_db_object(
            ctxt, pci_device.PciDevice(), fake_dev)
        dev.obj_make_compatible(dev.obj_to_primitive(), '1.6')
        self.assertEqual(dev.dev_type, fake_dev['dev_type'])

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

    @mock.patch.object(db, 'pci_device_update')
    def test_save(self, mock_update):
        ctxt = context.get_admin_context()
        self._create_fake_pci_device(ctxt=ctxt)
        return_dev = dict(fake_db_dev, status=fields.PciDeviceStatus.AVAILABLE,
                          instance_uuid=uuids.instance3)
        self.pci_device.status = fields.PciDeviceStatus.ALLOCATED
        self.pci_device.instance_uuid = uuids.instance2
        expected_updates = dict(status=fields.PciDeviceStatus.ALLOCATED,
                                instance_uuid=uuids.instance2)
        mock_update.return_value = return_dev
        self.pci_device.save()
        self.assertEqual(self.pci_device.status,
                         fields.PciDeviceStatus.AVAILABLE)
        self.assertEqual(self.pci_device.instance_uuid,
                         uuids.instance3)
        mock_update.assert_called_once_with(ctxt, 1, 'a', expected_updates)

    def test_save_no_extra_info(self):
        return_dev = dict(fake_db_dev, status=fields.PciDeviceStatus.AVAILABLE,
                          instance_uuid=uuids.instance3)

        def _fake_update(ctxt, node_id, addr, updates):
            self.extra_info = updates.get('extra_info')
            return return_dev

        ctxt = context.get_admin_context()
        self.stub_out('nova.db.main.api.pci_device_update', _fake_update)
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.pci_device._context = ctxt
        self.pci_device.save()
        self.assertEqual(self.extra_info, '{}')

    @mock.patch.object(db, 'pci_device_destroy')
    def test_save_removed(self, mock_destroy):
        ctxt = context.get_admin_context()
        self._create_fake_pci_device(ctxt=ctxt)
        self.pci_device.status = fields.PciDeviceStatus.REMOVED
        self.pci_device.save()
        self.assertEqual(self.pci_device.status,
                         fields.PciDeviceStatus.DELETED)
        mock_destroy.assert_called_once_with(ctxt, 1, 'a')

    def test_save_deleted(self):
        def _fake_destroy(ctxt, node_id, addr):
            self.called = True

        def _fake_update(ctxt, node_id, addr, updates):
            self.called = True
        self.stub_out('nova.db.main.api.pci_device_destroy', _fake_destroy)
        self.stub_out('nova.db.main.api.pci_device_update', _fake_update)
        self._create_fake_pci_device()
        self.pci_device.status = fields.PciDeviceStatus.DELETED
        self.called = False
        self.pci_device.save()
        self.assertFalse(self.called)

    def test_update_numa_node(self):
        self.pci_device = pci_device.PciDevice.create(None, dev_dict)
        self.assertEqual(0, self.pci_device.numa_node)

        self.dev_dict = copy.copy(dev_dict)
        self.dev_dict['numa_node'] = '1'
        self.pci_device = pci_device.PciDevice.create(None, self.dev_dict)
        self.assertEqual(1, self.pci_device.numa_node)

    @mock.patch('oslo_utils.uuidutils.generate_uuid',
                return_value=uuids.pci_dev1)
    def test_pci_device_equivalent(self, mock_uuid):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        self.assertEqual(pci_device1, pci_device2)

    @mock.patch('oslo_utils.uuidutils.generate_uuid',
                return_value=uuids.pci_dev1)
    def test_pci_device_equivalent_with_ignore_field(self, mock_uuid):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2.updated_at = timeutils.utcnow()
        self.assertEqual(pci_device1, pci_device2)

    @mock.patch('oslo_utils.uuidutils.generate_uuid',
                return_value=uuids.pci_dev1)
    def test_pci_device_not_equivalent1(self, mock_uuid):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        dev_dict2 = copy.copy(dev_dict)
        dev_dict2['address'] = 'b'
        pci_device2 = pci_device.PciDevice.create(None, dev_dict2)
        self.assertNotEqual(pci_device1, pci_device2)

    @mock.patch('oslo_utils.uuidutils.generate_uuid',
                return_value=uuids.pci_dev1)
    def test_pci_device_not_equivalent2(self, mock_uuid):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        delattr(pci_device2, 'address')
        self.assertNotEqual(pci_device1, pci_device2)

    @mock.patch('oslo_utils.uuidutils.generate_uuid',
                return_value=uuids.pci_dev1)
    def test_pci_device_not_equivalent_with_none(self, mock_uuid):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        pci_device2 = pci_device.PciDevice.create(None, dev_dict)
        pci_device1.instance_uuid = 'aaa'
        pci_device2.instance_uuid = None
        self.assertNotEqual(pci_device1, pci_device2)

    @mock.patch('oslo_utils.uuidutils.generate_uuid',
                return_value=uuids.pci_dev1)
    def test_pci_device_not_equivalent_with_not_pci_device(self, mock_uuid):
        pci_device1 = pci_device.PciDevice.create(None, dev_dict)
        self.assertIsNotNone(pci_device1)
        self.assertNotEqual(pci_device1, 'foo')
        self.assertNotEqual(pci_device1, 1)
        self.assertNotEqual(pci_device1, objects.PciDeviceList())

    def test_claim_device(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst.uuid)
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
        devobj.claim(self.inst.uuid)
        devobj.allocate(self.inst)
        self.assertEqual(devobj.status,
                         fields.PciDeviceStatus.ALLOCATED)
        self.assertEqual(devobj.instance_uuid, uuids.instance)
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
        inst_2.uuid = uuids.instance_2
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst.uuid)
        self.assertRaises(exception.PciDeviceInvalidOwner,
                          devobj.allocate, inst_2)

    def test_free_claimed_device(self):
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst.uuid)
        devobj.free(self.inst)
        self.assertEqual(devobj.status,
                         fields.PciDeviceStatus.AVAILABLE)
        self.assertIsNone(devobj.instance_uuid)

    def test_free_allocated_device(self):
        self._create_fake_instance()
        ctx = context.get_admin_context()
        devobj = pci_device.PciDevice._from_db_object(
                ctx, pci_device.PciDevice(), fake_db_dev)
        devobj.claim(self.inst.uuid)
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
        devobj.claim(self.inst.uuid)
        self.assertRaises(exception.PciDeviceInvalidStatus, devobj.remove)

    def test_remove_device_fail_owned_with_unavailable_state(self):
        # This test creates an PCI device in an invalid state. This should
        # not happen in any known scenario. But we want to be save not to allow
        # removing a device that has an owner. See bug 1969496 for more details
        self._create_fake_instance()
        devobj = pci_device.PciDevice.create(None, dev_dict)
        devobj.claim(self.inst.uuid)
        devobj.status = fields.PciDeviceStatus.UNAVAILABLE
        self.assertRaises(exception.PciDeviceInvalidOwner, devobj.remove)


class TestPciDeviceObject(test_objects._LocalTest,
                          _TestPciDeviceObject):
    pass


class TestPciDeviceObjectRemote(test_objects._RemoteTest,
                                _TestPciDeviceObject):
    pass


fake_pci_devs = [fake_db_dev, fake_db_dev_1]


class _TestPciDeviceListObject(object):

    def test_create_pci_device_list(self):
        ctxt = context.get_admin_context()
        devobj = pci_device.PciDevice.create(ctxt, dev_dict)
        pci_device_list = objects.PciDeviceList(
            context=ctxt, objects=[devobj])
        self.assertEqual(1, len(pci_device_list))
        self.assertIsInstance(pci_device_list[0], pci_device.PciDevice)

    @mock.patch.object(db, 'pci_device_get_all_by_node')
    def test_get_by_compute_node(self, mock_get):
        ctxt = context.get_admin_context()
        mock_get.return_value = fake_pci_devs
        devs = pci_device.PciDeviceList.get_by_compute_node(ctxt, 1)
        for i in range(len(fake_pci_devs)):
            self.assertIsInstance(devs[i], pci_device.PciDevice)
            self.assertEqual(fake_pci_devs[i]['vendor_id'], devs[i].vendor_id)
        mock_get.assert_called_once_with(ctxt, 1)

    @mock.patch.object(db, 'pci_device_get_all_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        ctxt = context.get_admin_context()
        fake_db_1 = dict(fake_db_dev, address='a1',
                         status=fields.PciDeviceStatus.ALLOCATED,
                         instance_uuid='1')
        fake_db_2 = dict(fake_db_dev, address='a2',
                         status=fields.PciDeviceStatus.ALLOCATED,
                         instance_uuid='1')
        mock_get.return_value = [fake_db_1, fake_db_2]
        devs = pci_device.PciDeviceList.get_by_instance_uuid(ctxt, '1')
        self.assertEqual(len(devs), 2)
        for i in range(len(fake_pci_devs)):
            self.assertIsInstance(devs[i], pci_device.PciDevice)
        self.assertEqual(devs[0].vendor_id, 'v')
        self.assertEqual(devs[1].vendor_id, 'v')
        mock_get.assert_called_once_with(ctxt, '1')


class TestPciDeviceListObject(test_objects._LocalTest,
                                  _TestPciDeviceListObject):
    pass


class TestPciDeviceListObjectRemote(test_objects._RemoteTest,
                              _TestPciDeviceListObject):
    pass


class _TestSRIOVPciDeviceObject(object):
    def _create_pci_devices(self, vf_product_id=1515, pf_product_id=1528,
                            num_pfs=2, num_vfs=8, num_vdpa=0):
        self.sriov_pf_devices = []
        for dev in range(num_pfs):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0000:81:00.%d' % dev,
                'vendor_id': '8086',
                'product_id': '%d' % pf_product_id,
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.SRIOV_PF,
                'parent_addr': None,
                'numa_node': 0
            }
            pci_dev_obj = objects.PciDevice.create(None, pci_dev)
            pci_dev_obj.id = dev + 81
            pci_dev_obj.child_devices = []
            self.sriov_pf_devices.append(pci_dev_obj)

        self.sriov_vf_devices = []
        for dev in range(num_vfs):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0000:81:10.%d' % dev,
                'vendor_id': '8086',
                'product_id': '%d' % vf_product_id,
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.SRIOV_VF,
                'parent_addr': '0000:81:00.%d' % int(dev / 4),
                'numa_node': 0
            }
            pci_dev_obj = objects.PciDevice.create(None, pci_dev)
            pci_dev_obj.id = dev + 1
            pci_dev_obj.parent_device = self.sriov_pf_devices[int(dev / 4)]
            pci_dev_obj.parent_device.child_devices.append(pci_dev_obj)
            self.sriov_vf_devices.append(pci_dev_obj)

        self.sriov_vdpa_devices = []
        for dev in range(num_vdpa):
            pci_dev = {
                'compute_node_id': 1,
                'address': '0000:81:11.%d' % dev,
                'vendor_id': '8086',
                'product_id': '%d' % vf_product_id,
                'status': 'available',
                'request_id': None,
                'dev_type': fields.PciDeviceType.VDPA,
                'parent_addr': '0000:81:00.%d' % (dev % num_pfs),
                'numa_node': 0
            }
            pci_dev_obj = objects.PciDevice.create(None, pci_dev)
            pci_dev_obj.id = dev + 1
            pci_dev_obj.parent_device = self.sriov_pf_devices[dev % num_pfs]
            pci_dev_obj.parent_device.child_devices.append(pci_dev_obj)
            self.sriov_vdpa_devices.append(pci_dev_obj)

    def _create_fake_instance(self):
        self.inst = instance.Instance()
        self.inst.uuid = uuids.instance
        self.inst.pci_devices = pci_device.PciDeviceList()

    @mock.patch.object(db, 'pci_device_get_by_addr')
    def _create_fake_pci_device(self, mock_get, ctxt=None):
        if not ctxt:
            ctxt = context.get_admin_context()
        mock_get.return_value = fake_db_dev
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')
        mock_get.assert_called_once_with(ctxt, 1, 'a')

    def _get_children_by_parent_address(self, addr):
        vf_devs = []
        for dev in self.sriov_vf_devices:
            if dev.parent_addr == addr:
                vf_devs.append(dev)
        return vf_devs

    def _get_parent_by_address(self, addr):
        for dev in self.sriov_pf_devices:
            if dev.address == addr:
                return dev

    def test_claim_PF(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_pf_devices[0]
        devobj.claim(self.inst.uuid)
        self.assertEqual(devobj.status, fields.PciDeviceStatus.CLAIMED)
        self.assertEqual(devobj.instance_uuid, self.inst.uuid)
        self.assertEqual(len(self.inst.pci_devices), 0)
        # check if the all the dependants are UNCLAIMABLE
        self.assertTrue(all(
            [dev.status == fields.PciDeviceStatus.UNCLAIMABLE for
             dev in self._get_children_by_parent_address(
                 self.sriov_pf_devices[0].address)]))

    def test_claim_VF(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_vf_devices[0]
        devobj.claim(self.inst.uuid)
        self.assertEqual(devobj.status, fields.PciDeviceStatus.CLAIMED)
        self.assertEqual(devobj.instance_uuid, self.inst.uuid)
        self.assertEqual(len(self.inst.pci_devices), 0)

        # check if parent device status has been changed to UNCLAIMABLE
        parent = self._get_parent_by_address(devobj.parent_addr)
        self.assertEqual(fields.PciDeviceStatus.UNCLAIMABLE, parent.status)

    def test_claim_VDPA(self):
        self._create_fake_instance()
        self._create_pci_devices(num_pfs=1, num_vfs=0, num_vdpa=2)
        devobj = self.sriov_vdpa_devices[0]
        devobj.claim(self.inst.uuid)
        self.assertEqual(devobj.status, fields.PciDeviceStatus.CLAIMED)
        self.assertEqual(devobj.instance_uuid, self.inst.uuid)
        self.assertEqual(len(self.inst.pci_devices), 0)

        # check if parent device status has been changed to UNCLAIMABLE
        parent = self._get_parent_by_address(devobj.parent_addr)
        self.assertEqual(fields.PciDeviceStatus.UNCLAIMABLE, parent.status)

    def test_allocate_PF(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_pf_devices[0]
        devobj.claim(self.inst.uuid)
        devobj.allocate(self.inst)
        self.assertEqual(devobj.status, fields.PciDeviceStatus.ALLOCATED)
        self.assertEqual(devobj.instance_uuid, self.inst.uuid)
        self.assertEqual(len(self.inst.pci_devices), 1)
        # check if the all the dependants are UNAVAILABLE
        self.assertTrue(all(
                [dev.status == fields.PciDeviceStatus.UNAVAILABLE for
                dev in self._get_children_by_parent_address(
                                    self.sriov_pf_devices[0].address)]))

    def test_allocate_VF(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_vf_devices[0]
        devobj.claim(self.inst.uuid)
        devobj.allocate(self.inst)
        self.assertEqual(devobj.status, fields.PciDeviceStatus.ALLOCATED)
        self.assertEqual(devobj.instance_uuid, self.inst.uuid)
        self.assertEqual(len(self.inst.pci_devices), 1)

        # check if parent device status has been changed to UNAVAILABLE
        parent = self._get_parent_by_address(devobj.parent_addr)
        self.assertEqual(fields.PciDeviceStatus.UNAVAILABLE, parent.status)

    def test_allocate_VDPA(self):
        self._create_fake_instance()
        self._create_pci_devices(num_pfs=1, num_vfs=0, num_vdpa=2)
        devobj = self.sriov_vdpa_devices[0]
        devobj.claim(self.inst.uuid)
        devobj.allocate(self.inst)
        self.assertEqual(devobj.status, fields.PciDeviceStatus.ALLOCATED)
        self.assertEqual(devobj.instance_uuid, self.inst.uuid)
        self.assertEqual(len(self.inst.pci_devices), 1)

        # check if parent device status has been changed to UNAVAILABLE
        parent = self._get_parent_by_address(devobj.parent_addr)
        self.assertEqual(fields.PciDeviceStatus.UNAVAILABLE, parent.status)

    def test_claim_PF_fail(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_pf_devices[0]
        self.sriov_vf_devices[0].status = fields.PciDeviceStatus.CLAIMED

        self.assertRaises(
            exception.PciDeviceVFInvalidStatus, devobj.claim, self.inst)

    def test_claim_PF_fail_VDPA(self):
        self._create_fake_instance()
        self._create_pci_devices(num_pfs=1, num_vfs=0, num_vdpa=2)
        devobj = self.sriov_pf_devices[0]
        self.sriov_vdpa_devices[0].status = fields.PciDeviceStatus.CLAIMED

        self.assertRaises(
            exception.PciDeviceVFInvalidStatus, devobj.claim, self.inst)

    def test_claim_VF_fail(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_vf_devices[0]
        parent = self._get_parent_by_address(devobj.parent_addr)
        parent.status = fields.PciDeviceStatus.CLAIMED

        self.assertRaises(
            exception.PciDevicePFInvalidStatus, devobj.claim, self.inst)

    def test_claim_VDPA_fail(self):
        self._create_fake_instance()
        self._create_pci_devices(num_pfs=1, num_vfs=0, num_vdpa=2)
        devobj = self.sriov_vdpa_devices[0]
        parent = self._get_parent_by_address(devobj.parent_addr)
        parent.status = fields.PciDeviceStatus.CLAIMED
        self.assertRaises(
            exception.PciDevicePFInvalidStatus, devobj.claim, self.inst)

    def test_allocate_PF_fail(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_pf_devices[0]
        self.sriov_vf_devices[0].status = fields.PciDeviceStatus.CLAIMED

        self.assertRaises(
            exception.PciDeviceVFInvalidStatus, devobj.allocate, self.inst)

    def test_allocate_VF_fail(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_vf_devices[0]
        parent = self._get_parent_by_address(devobj.parent_addr)
        parent.status = fields.PciDeviceStatus.CLAIMED

        self.assertRaises(
            exception.PciDevicePFInvalidStatus, devobj.allocate, self.inst)

    def test_allocate_PF_fail_VDPA(self):
        self._create_fake_instance()
        self._create_pci_devices(num_pfs=1, num_vfs=0, num_vdpa=2)
        devobj = self.sriov_pf_devices[0]
        self.sriov_vdpa_devices[0].status = fields.PciDeviceStatus.CLAIMED

        self.assertRaises(
            exception.PciDeviceVFInvalidStatus, devobj.allocate, self.inst)

    def test_allocate_VDPA_fail(self):
        self._create_fake_instance()
        self._create_pci_devices(num_pfs=1, num_vfs=0, num_vdpa=2)
        devobj = self.sriov_vdpa_devices[0]
        parent = self._get_parent_by_address(devobj.parent_addr)
        parent.status = fields.PciDeviceStatus.CLAIMED

        self.assertRaises(
            exception.PciDevicePFInvalidStatus, devobj.allocate, self.inst)

    def test_free_allocated_PF(self):
        self._create_fake_instance()
        self._create_pci_devices()
        devobj = self.sriov_pf_devices[0]
        devobj.claim(self.inst.uuid)
        devobj.allocate(self.inst)
        devobj.free(self.inst)
        self.assertEqual(devobj.status, fields.PciDeviceStatus.AVAILABLE)
        self.assertIsNone(devobj.instance_uuid)
        # check if the all the dependants are AVAILABLE
        self.assertTrue(all(
            [dev.status == fields.PciDeviceStatus.AVAILABLE for
             dev in self._get_children_by_parent_address(
                 self.sriov_pf_devices[0].address)]))

    def test_free_allocated_VF(self):
        self._create_fake_instance()
        self._create_pci_devices()
        vf = self.sriov_vf_devices[0]
        dependents = self._get_children_by_parent_address(vf.parent_addr)
        for devobj in dependents:
            devobj.claim(self.inst.uuid)
            devobj.allocate(self.inst)
            self.assertEqual(devobj.status, fields.PciDeviceStatus.ALLOCATED)
        for devobj in dependents[:-1]:
            devobj.free(self.inst)
            # check if parent device status is still UNAVAILABLE
            parent = self._get_parent_by_address(devobj.parent_addr)
            self.assertEqual(
                fields.PciDeviceStatus.UNAVAILABLE, parent.status)
        devobj = dependents[-1]
        devobj.free(self.inst)
        # check if parent device status is now AVAILABLE
        parent = self._get_parent_by_address(devobj.parent_addr)
        self.assertEqual(
            fields.PciDeviceStatus.AVAILABLE, parent.status)

    def test_free_allocated_VDPA(self):
        self._create_fake_instance()
        self._create_pci_devices(num_pfs=2, num_vfs=0, num_vdpa=8)
        vdpa = self.sriov_vdpa_devices[0]
        dependents = self._get_children_by_parent_address(vdpa.parent_addr)
        for devobj in dependents:
            devobj.claim(self.inst.uuid)
            devobj.allocate(self.inst)
            self.assertEqual(devobj.status, fields.PciDeviceStatus.ALLOCATED)
        for devobj in dependents[:-1]:
            devobj.free(self.inst)
            # check if parent device status is still UNAVAILABLE
            parent = self._get_parent_by_address(devobj.parent_addr)
            self.assertEqual(
                fields.PciDeviceStatus.UNAVAILABLE, parent.status)
        for devobj in dependents[-1:]:
            devobj.free(self.inst)
            # check if parent device status is now AVAILABLE
            parent = self._get_parent_by_address(devobj.parent_addr)
            self.assertEqual(
                fields.PciDeviceStatus.AVAILABLE, parent.status)


class TestSRIOVPciDeviceListObject(test_objects._LocalTest,
                                  _TestSRIOVPciDeviceObject):
    pass


class TestSRIOVPciDeviceListObjectRemote(test_objects._RemoteTest,
                              _TestSRIOVPciDeviceObject):
    pass


class TestPciDeviceUUIDMigration(test.TestCase):
    def setUp(self):
        super(TestPciDeviceUUIDMigration, self).setUp()
        self.context = context.RequestContext('fake-user-id',
                                              'fake-project-id')

    @staticmethod
    @db.pick_context_manager_writer
    def _create_db_dev(context, deleted=False, **updates):
        """Create a PCI device with no UUID."""
        values = copy.copy(dev_dict)
        # 'PciDeviceList.get_by_instance_uuid' expected devices to be allocated
        values['status'] = fields.PciDeviceStatus.ALLOCATED
        values['label'] = 'l'  # Why is this necessary?
        values['instance_uuid'] = uuids.instance_uuid
        values['extra_info'] = '{}'
        values.update(updates)

        dev_ref = db_models.PciDevice()
        dev_ref.update(values)
        dev_ref.save(context.session)

        if deleted:
            dev_ref.soft_delete(context.session)

        return dev_ref

    @mock.patch.object(objects.PciDevice, '_create_uuid',
            wraps=objects.PciDevice._create_uuid)
    def test_populate_uuid(self, mock_create_uuid):
        self._create_db_dev(self.context)
        devs = objects.PciDeviceList.get_by_instance_uuid(
            self.context, uuids.instance_uuid)

        # UUID should have been populated and object shouldn't be dirty
        self.assertIn('uuid', devs[0])
        self.assertIsNotNone(devs[0].uuid)
        self.assertNotIn('uuid', devs[0].obj_what_changed())

        uuid = devs[0].uuid

        devs = objects.PciDeviceList.get_by_instance_uuid(
            self.context, uuids.instance_uuid)

        # UUID should not have changed
        self.assertEqual(uuid, devs[0].uuid)
        self.assertEqual(1, mock_create_uuid.call_count)

    def test_create_uuid_race(self):
        # If threads read a legacy PCI device object concurrently, we can end
        # up calling _create_uuid multiple times. Assert that calling
        # _create_uuid multiple times yields the same uuid.

        # NOTE(mdbooth): _create_uuid handles all forms of race, including any
        # amount of overlapping. I have not attempted to write unit tests for
        # all potential execution orders. This test is sufficient to
        # demonstrate that the compare-and-swap works correctly, and we trust
        # the correctness of the database for the rest.

        db_dev = self._create_db_dev(self.context)
        uuid1 = objects.PciDevice._create_uuid(self.context, db_dev.id)

        dev = objects.PciDeviceList.get_by_instance_uuid(
            self.context, uuids.instance_uuid)[0]
        self.assertEqual(uuid1, dev.uuid)

        # We would only ever call this twice if we raced
        # This is also testing that the compare-and-swap doesn't overwrite an
        # existing uuid if we hit that race.
        uuid2 = objects.PciDevice._create_uuid(self.context, dev.id)

        self.assertEqual(uuid1, uuid2)

    def _assert_online_migration(self, expected_total, expected_done,
                                 limit=10):
        total, done = objects.PciDevice.populate_dev_uuids(
            self.context, limit)
        self.assertEqual(expected_total, total)
        self.assertEqual(expected_done, done)

    def test_online_migration(self):
        self._assert_online_migration(0, 0)

        # Create 2 PCI devices, one with a uuid and one without. We need to
        # specify an address due to unique constraints in the database
        self._create_db_dev(self.context, address='a', uuid=None)
        self._create_db_dev(self.context, address='b', uuid=uuids.dev_uuid)

        # Run the online migration. We should find 1 and update 1
        self._assert_online_migration(1, 1)

        # Fetch the BDMs and check we didn't modify the uuid of bdm2
        devs = objects.PciDeviceList.get_by_instance_uuid(
            self.context, uuids.instance_uuid)
        dev_uuids = [dev.uuid for dev in devs]
        self.assertIn(uuids.dev_uuid, dev_uuids)
        self.assertNotIn(None, dev_uuids)

        # Run the online migration again to see nothing was processed
        self._assert_online_migration(0, 0)

        # Assert that we assign a uuid to a deleted bdm.
        self._create_db_dev(self.context, address='c', deleted=True)
        self._assert_online_migration(1, 1)

        # Test that we don't migrate more than the limit
        for i in range(0, 3):
            self._create_db_dev(self.context, address=str(i))
        self._assert_online_migration(2, 2, limit=2)
