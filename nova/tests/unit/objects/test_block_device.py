#    Copyright 2013 Red Hat Inc.
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
import six

from nova.cells import rpcapi as cells_rpcapi
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import block_device as block_device_obj
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_objects


class _TestBlockDeviceMappingObject(object):
    def fake_bdm(self, instance=None):
        instance = instance or {}
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict({
            'id': 123,
            'instance_uuid': instance.get('uuid') or 'fake-instance',
            'device_name': '/dev/sda2',
            'source_type': 'snapshot',
            'destination_type': 'volume',
            'connection_info': "{'fake': 'connection_info'}",
            'snapshot_id': 'fake-snapshot-id-1',
            'boot_index': -1
        })
        if instance:
            fake_bdm['instance'] = instance
        return fake_bdm

    def _test_save(self, cell_type=None, update_device_name=False):
        if cell_type:
            self.flags(enable=True, cell_type=cell_type, group='cells')
        else:
            self.flags(enable=False, group='cells')

        create = False
        fake_bdm = self.fake_bdm()
        with test.nested(
            mock.patch.object(
                db, 'block_device_mapping_update', return_value=fake_bdm),
            mock.patch.object(
                cells_rpcapi.CellsAPI, 'bdm_update_or_create_at_top')
        ) as (bdm_update_mock, cells_update_mock):
            bdm_object = objects.BlockDeviceMapping(context=self.context)
            bdm_object.id = 123
            bdm_object.volume_id = 'fake_volume_id'
            if update_device_name:
                bdm_object.device_name = '/dev/vda'
                create = None
            bdm_object.save()

            if update_device_name:
                bdm_update_mock.assert_called_once_with(
                        self.context, 123,
                        {'volume_id': 'fake_volume_id',
                         'device_name': '/dev/vda'},
                        legacy=False)
            else:
                bdm_update_mock.assert_called_once_with(
                        self.context, 123, {'volume_id': 'fake_volume_id'},
                        legacy=False)
            if cell_type != 'compute':
                self.assertFalse(cells_update_mock.called)
            else:
                self.assertEqual(1, cells_update_mock.call_count)
                self.assertTrue(len(cells_update_mock.call_args[0]) > 1)
                self.assertIsInstance(cells_update_mock.call_args[0][1],
                                      block_device_obj.BlockDeviceMapping)
                self.assertEqual({'create': create},
                                 cells_update_mock.call_args[1])

    def test_save_nocells(self):
        self._test_save()

    def test_save_apicell(self):
        self._test_save(cell_type='api')

    def test_save_computecell(self):
        self._test_save(cell_type='compute')

    def test_save_computecell_device_name_changed(self):
        self._test_save(cell_type='compute', update_device_name=True)

    def test_save_instance_changed(self):
        bdm_object = objects.BlockDeviceMapping(context=self.context)
        bdm_object.instance = objects.Instance()
        self.assertRaises(exception.ObjectActionError,
                          bdm_object.save)

    @mock.patch.object(db, 'block_device_mapping_update', return_value=None)
    def test_save_not_found(self, bdm_update):
        bdm_object = objects.BlockDeviceMapping(context=self.context)
        bdm_object.id = 123
        self.assertRaises(exception.BDMNotFound, bdm_object.save)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_volume_id')
    def test_get_by_volume_id(self, get_by_vol_id):
        # NOTE(danms): Include two results to make sure the first was picked.
        # An invalid second item shouldn't be touched -- if it is, it'll
        # fail from_db_object().
        get_by_vol_id.return_value = [self.fake_bdm(),
                                      None]

        vol_bdm = objects.BlockDeviceMapping.get_by_volume_id(
                self.context, 'fake-volume-id')
        for attr in block_device_obj.BLOCK_DEVICE_OPTIONAL_ATTRS:
            self.assertFalse(vol_bdm.obj_attr_is_set(attr))

    @mock.patch.object(db, 'block_device_mapping_get_all_by_volume_id')
    def test_get_by_volume_id_not_found(self, get_by_vol_id):
        get_by_vol_id.return_value = None

        self.assertRaises(exception.VolumeBDMNotFound,
                          objects.BlockDeviceMapping.get_by_volume_id,
                          self.context, 'fake-volume-id')

    @mock.patch.object(db, 'block_device_mapping_get_all_by_volume_id')
    def test_get_by_volume_instance_uuid_missmatch(self, get_by_vol_id):
        fake_bdm_vol = self.fake_bdm(instance={'uuid': 'other-fake-instance'})
        get_by_vol_id.return_value = [fake_bdm_vol]

        self.assertRaises(exception.InvalidVolume,
                          objects.BlockDeviceMapping.get_by_volume_id,
                          self.context, 'fake-volume-id',
                          instance_uuid='fake-instance')

    @mock.patch.object(db, 'block_device_mapping_get_all_by_volume_id')
    def test_get_by_volume_id_with_expected(self, get_by_vol_id):
        get_by_vol_id.return_value = [self.fake_bdm(
                fake_instance.fake_db_instance())]

        vol_bdm = objects.BlockDeviceMapping.get_by_volume_id(
                self.context, 'fake-volume-id', expected_attrs=['instance'])
        for attr in block_device_obj.BLOCK_DEVICE_OPTIONAL_ATTRS:
            self.assertTrue(vol_bdm.obj_attr_is_set(attr))
        get_by_vol_id.assert_called_once_with(self.context, 'fake-volume-id',
                                              ['instance'])

    @mock.patch.object(db, 'block_device_mapping_get_all_by_volume_id')
    def test_get_by_volume_returned_single(self, get_all):
        fake_bdm_vol = self.fake_bdm()
        get_all.return_value = [fake_bdm_vol]
        vol_bdm = objects.BlockDeviceMapping.get_by_volume(
                self.context, 'fake-volume-id')
        self.assertEqual(fake_bdm_vol['id'], vol_bdm.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_volume_id')
    def test_get_by_volume_returned_multiple(self, get_all):
        fake_bdm_vol1 = self.fake_bdm()
        fake_bdm_vol2 = self.fake_bdm()
        get_all.return_value = [fake_bdm_vol1, fake_bdm_vol2]
        self.assertRaises(exception.VolumeBDMIsMultiAttach,
                          objects.BlockDeviceMapping.get_by_volume,
                          self.context, 'fake-volume-id')

    @mock.patch.object(db,
                       'block_device_mapping_get_by_instance_and_volume_id')
    def test_get_by_instance_and_volume_id(self, mock_get):
        fake_inst = fake_instance.fake_db_instance()
        mock_get.return_value = self.fake_bdm(fake_inst)

        obj_bdm = objects.BlockDeviceMapping
        vol_bdm = obj_bdm.get_by_volume_and_instance(
            self.context, 'fake-volume-id', 'fake-instance-id')
        for attr in block_device_obj.BLOCK_DEVICE_OPTIONAL_ATTRS:
            self.assertFalse(vol_bdm.obj_attr_is_set(attr))

    @mock.patch.object(db,
                       'block_device_mapping_get_by_instance_and_volume_id')
    def test_test_get_by_instance_and_volume_id_with_expected(self, mock_get):
        fake_inst = fake_instance.fake_db_instance()
        mock_get.return_value = self.fake_bdm(fake_inst)

        obj_bdm = objects.BlockDeviceMapping
        vol_bdm = obj_bdm.get_by_volume_and_instance(
            self.context, 'fake-volume-id', fake_inst['uuid'],
            expected_attrs=['instance'])
        for attr in block_device_obj.BLOCK_DEVICE_OPTIONAL_ATTRS:
            self.assertTrue(vol_bdm.obj_attr_is_set(attr))
        mock_get.assert_called_once_with(self.context, 'fake-volume-id',
                                         fake_inst['uuid'], ['instance'])

    @mock.patch.object(db,
                       'block_device_mapping_get_by_instance_and_volume_id')
    def test_get_by_instance_and_volume_id_not_found(self, mock_get):
        mock_get.return_value = None

        obj_bdm = objects.BlockDeviceMapping
        self.assertRaises(exception.VolumeBDMNotFound,
                          obj_bdm.get_by_volume_and_instance,
                          self.context, 'fake-volume-id', 'fake-instance-id')

    def _test_create_mocked(self, cell_type=None, update_or_create=False,
            device_name=None):
        if cell_type:
            self.flags(enable=True, cell_type=cell_type, group='cells')
        else:
            self.flags(enable=False, group='cells')
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance'}
        if device_name:
            values['device_name'] = device_name
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(values)

        with test.nested(
            mock.patch.object(
                    db, 'block_device_mapping_create', return_value=fake_bdm),
            mock.patch.object(
                    db, 'block_device_mapping_update_or_create',
                    return_value=fake_bdm),
            mock.patch.object(cells_rpcapi.CellsAPI,
                              'bdm_update_or_create_at_top')
        ) as (bdm_create_mock, bdm_update_or_create_mock, cells_update_mock):
            bdm = objects.BlockDeviceMapping(context=self.context, **values)
            if update_or_create:
                method = bdm.update_or_create
            else:
                method = bdm.create

            if cell_type == 'api':
                self.assertRaises(exception.ObjectActionError,
                                  method)
            else:
                method()
                if update_or_create:
                    bdm_update_or_create_mock.assert_called_once_with(
                            self.context, values, legacy=False)
                else:
                    bdm_create_mock.assert_called_once_with(
                            self.context, values, legacy=False)
                if cell_type == 'compute' and 'device_name' in values:
                    self.assertEqual(1, cells_update_mock.call_count)
                    self.assertTrue(len(cells_update_mock.call_args[0]) > 1)
                    self.assertEqual(self.context,
                                     cells_update_mock.call_args[0][0])
                    self.assertIsInstance(cells_update_mock.call_args[0][1],
                                          block_device_obj.BlockDeviceMapping)
                    self.assertEqual({'create': update_or_create or None},
                                     cells_update_mock.call_args[1])
                else:
                    self.assertFalse(cells_update_mock.called)

    def test_create_nocells(self):
        self._test_create_mocked()

    def test_update_or_create(self):
        self._test_create_mocked(update_or_create=True)

    def test_create_apicell(self):
        self._test_create_mocked(cell_type='api')

    def test_update_or_create_apicell(self):
        self._test_create_mocked(cell_type='api', update_or_create=True)

    def test_create_computecell(self):
        self._test_create_mocked(cell_type='compute')

    def test_update_or_create_computecell(self):
        self._test_create_mocked(cell_type='compute', update_or_create=True)

    def test_device_name_compute_cell(self):
        self._test_create_mocked(cell_type='compute', device_name='/dev/xvdb')

    def test_create(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance'}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        with mock.patch.object(cells_rpcapi.CellsAPI,
                               'bdm_update_or_create_at_top'):
            bdm.create()

        for k, v in six.iteritems(values):
            self.assertEqual(v, getattr(bdm, k))

    def test_create_fails(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance'}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        bdm.create()

        self.assertRaises(exception.ObjectActionError,
                          bdm.create)

    def test_create_fails_instance(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance',
                  'instance': objects.Instance()}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        self.assertRaises(exception.ObjectActionError,
                          bdm.create)

    def _test_destroy_mocked(self, cell_type=None):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume', 'id': 1,
                  'instance_uuid': 'fake-instance', 'device_name': 'fake'}
        if cell_type:
            self.flags(enable=True, cell_type=cell_type, group='cells')
        else:
            self.flags(enable=False, group='cells')
        with test.nested(
            mock.patch.object(db, 'block_device_mapping_destroy'),
            mock.patch.object(cells_rpcapi.CellsAPI, 'bdm_destroy_at_top')
        ) as (bdm_del, cells_destroy):
            bdm = objects.BlockDeviceMapping(context=self.context, **values)
            bdm.destroy()
            bdm_del.assert_called_once_with(self.context, values['id'])
            if cell_type != 'compute':
                self.assertFalse(cells_destroy.called)
            else:
                cells_destroy.assert_called_once_with(
                    self.context, values['instance_uuid'],
                    device_name=values['device_name'],
                    volume_id=values['volume_id'])

    def test_destroy_nocells(self):
        self._test_destroy_mocked()

    def test_destroy_apicell(self):
        self._test_destroy_mocked(cell_type='api')

    def test_destroy_computecell(self):
        self._test_destroy_mocked(cell_type='compute')

    def test_is_image_true(self):
        bdm = objects.BlockDeviceMapping(context=self.context,
                                         source_type='image')
        self.assertTrue(bdm.is_image)

    def test_is_image_false(self):
        bdm = objects.BlockDeviceMapping(context=self.context,
                                         source_type='snapshot')
        self.assertFalse(bdm.is_image)

    def test_is_volume_true(self):
        bdm = objects.BlockDeviceMapping(context=self.context,
                                         destination_type='volume')
        self.assertTrue(bdm.is_volume)

    def test_is_volume_false(self):
        bdm = objects.BlockDeviceMapping(context=self.context,
                                         destination_type='local')
        self.assertFalse(bdm.is_volume)


class TestBlockDeviceMappingObject(test_objects._LocalTest,
                                   _TestBlockDeviceMappingObject):
    pass


class TestRemoteBlockDeviceMappingObject(test_objects._RemoteTest,
                                         _TestBlockDeviceMappingObject):
    pass


class _TestBlockDeviceMappingListObject(object):
    def fake_bdm(self, bdm_id, boot_index=-1, instance_uuid='fake-instance'):
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict({
            'id': bdm_id,
            'boot_index': boot_index,
            'instance_uuid': instance_uuid,
            'device_name': '/dev/sda2',
            'source_type': 'snapshot',
            'destination_type': 'volume',
            'connection_info': "{'fake': 'connection_info'}",
            'snapshot_id': 'fake-snapshot-id-1',
        })
        return fake_bdm

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance_uuids')
    def test_bdms_by_instance_uuid(self, get_all_by_inst_uuids):
        fakes = [self.fake_bdm(123), self.fake_bdm(456)]
        get_all_by_inst_uuids.return_value = fakes
        bdms_by_uuid = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
            self.context, ['fake-instance'])
        self.assertEqual(['fake-instance'], list(bdms_by_uuid.keys()))
        self.assertIsInstance(
            bdms_by_uuid['fake-instance'], objects.BlockDeviceMappingList)
        for faked, got in zip(fakes, bdms_by_uuid['fake-instance']):
            self.assertIsInstance(got, objects.BlockDeviceMapping)
            self.assertEqual(faked['id'], got.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance_uuids')
    def test_bdms_by_instance_uuid_no_result(self, get_all_by_inst_uuids):
        get_all_by_inst_uuids.return_value = None
        bdms_by_uuid = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
            self.context, ['fake-instance'])
        self.assertEqual({}, bdms_by_uuid)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance_uuids')
    def test_get_by_instance_uuids(self, get_all_by_inst_uuids):
        fakes = [self.fake_bdm(123), self.fake_bdm(456)]
        get_all_by_inst_uuids.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuids(
            self.context, ['fake-instance'])
        for faked, got in zip(fakes, bdm_list):
            self.assertIsInstance(got, objects.BlockDeviceMapping)
            self.assertEqual(faked['id'], got.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance_uuids')
    def test_get_by_instance_uuids_no_result(self, get_all_by_inst_uuids):
        get_all_by_inst_uuids.return_value = None
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuids(
            self.context, ['fake-instance'])
        self.assertEqual(0, len(bdm_list))

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_get_by_instance_uuid(self, get_all_by_inst):
        fakes = [self.fake_bdm(123), self.fake_bdm(456)]
        get_all_by_inst.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, 'fake-instance')
        for faked, got in zip(fakes, bdm_list):
            self.assertIsInstance(got, objects.BlockDeviceMapping)
            self.assertEqual(faked['id'], got.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_get_by_instance_uuid_no_result(self, get_all_by_inst):
        get_all_by_inst.return_value = None
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, 'fake-instance')
        self.assertEqual(0, len(bdm_list))

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_root_bdm(self, get_all_by_inst):
        fakes = [self.fake_bdm(123), self.fake_bdm(456, boot_index=0)]
        get_all_by_inst.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, 'fake-instance')
        self.assertEqual(456, bdm_list.root_bdm().id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_root_bdm_empty_bdm_list(self, get_all_by_inst):
        get_all_by_inst.return_value = None
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, 'fake-instance')
        self.assertIsNone(bdm_list.root_bdm())

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_root_bdm_undefined(self, get_all_by_inst):
        fakes = [
            self.fake_bdm(123, instance_uuid='uuid_1'),
            self.fake_bdm(456, instance_uuid='uuid_2')
        ]
        get_all_by_inst.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, 'fake-instance')
        self.assertRaises(exception.UndefinedRootBDM, bdm_list.root_bdm)


class TestBlockDeviceMappingListObject(test_objects._LocalTest,
                                       _TestBlockDeviceMappingListObject):
    pass


class TestRemoteBlockDeviceMappingListObject(
        test_objects._RemoteTest, _TestBlockDeviceMappingListObject):
    pass


class TestBlockDeviceUtils(test.NoDBTestCase):
    def test_make_list_from_dicts(self):
        ctx = context.get_admin_context()
        dicts = [{'id': 1}, {'id': 2}]
        objs = block_device_obj.block_device_make_list_from_dicts(ctx,
                                                                  dicts)
        self.assertIsInstance(objs, block_device_obj.BlockDeviceMappingList)
        self.assertEqual(2, len(objs))
        self.assertEqual(1, objs[0].id)
        self.assertEqual(2, objs[1].id)

    def test_make_list_from_dicts_empty(self):
        ctx = context.get_admin_context()
        objs = block_device_obj.block_device_make_list_from_dicts(ctx, [])
        self.assertIsInstance(objs, block_device_obj.BlockDeviceMappingList)
        self.assertEqual(0, len(objs))
