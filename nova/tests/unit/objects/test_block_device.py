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

import contextlib

import mock

from nova.cells import rpcapi as cells_rpcapi
from nova import db
from nova import exception
from nova import objects
from nova.objects import block_device as block_device_obj
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

    def _test_save(self, cell_type=None):
        if cell_type:
            self.flags(enable=True, cell_type=cell_type, group='cells')
        else:
            self.flags(enable=False, group='cells')

        fake_bdm = self.fake_bdm()
        with contextlib.nested(
            mock.patch.object(
                db, 'block_device_mapping_update', return_value=fake_bdm),
            mock.patch.object(
                cells_rpcapi.CellsAPI, 'bdm_update_or_create_at_top')
        ) as (bdm_update_mock, cells_update_mock):
            bdm_object = objects.BlockDeviceMapping(context=self.context)
            bdm_object.id = 123
            bdm_object.volume_id = 'fake_volume_id'
            bdm_object.save()

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
                self.assertEqual(cells_update_mock.call_args[1], {})

    def test_save_nocells(self):
        self._test_save()

    def test_save_apicell(self):
        self._test_save(cell_type='api')

    def test_save_computecell(self):
        self._test_save(cell_type='compute')

    def test_save_instance_changed(self):
        bdm_object = objects.BlockDeviceMapping()
        bdm_object.instance = objects.Instance()
        self.assertRaises(exception.ObjectActionError,
                          bdm_object.save, self.context)

    @mock.patch.object(db, 'block_device_mapping_get_by_volume_id')
    def test_get_by_volume_id(self, get_by_vol_id):
        get_by_vol_id.return_value = self.fake_bdm()

        vol_bdm = objects.BlockDeviceMapping.get_by_volume_id(
                self.context, 'fake-volume-id')
        for attr in block_device_obj.BLOCK_DEVICE_OPTIONAL_ATTRS:
            self.assertFalse(vol_bdm.obj_attr_is_set(attr))
        self.assertRemotes()

    @mock.patch.object(db, 'block_device_mapping_get_by_volume_id')
    def test_get_by_volume_id_not_found(self, get_by_vol_id):
        get_by_vol_id.return_value = None

        self.assertRaises(exception.VolumeBDMNotFound,
                          objects.BlockDeviceMapping.get_by_volume_id,
                          self.context, 'fake-volume-id')

    @mock.patch.object(db, 'block_device_mapping_get_by_volume_id')
    def test_get_by_volume_instance_uuid_missmatch(self, get_by_vol_id):
        fake_bdm_vol = self.fake_bdm(instance={'uuid': 'other-fake-instance'})
        get_by_vol_id.return_value = fake_bdm_vol

        self.assertRaises(exception.InvalidVolume,
                          objects.BlockDeviceMapping.get_by_volume_id,
                          self.context, 'fake-volume-id',
                          instance_uuid='fake-instance')

    @mock.patch.object(db, 'block_device_mapping_get_by_volume_id')
    def test_get_by_volume_id_with_expected(self, get_by_vol_id):
        get_by_vol_id.return_value = self.fake_bdm(
                fake_instance.fake_db_instance())

        vol_bdm = objects.BlockDeviceMapping.get_by_volume_id(
                self.context, 'fake-volume-id', expected_attrs=['instance'])
        for attr in block_device_obj.BLOCK_DEVICE_OPTIONAL_ATTRS:
            self.assertTrue(vol_bdm.obj_attr_is_set(attr))
        get_by_vol_id.assert_called_once_with(self.context, 'fake-volume-id',
                                              ['instance'])
        self.assertRemotes()

    def _test_create_mocked(self, cell_type=None, update_or_create=False):
        if cell_type:
            self.flags(enable=True, cell_type=cell_type, group='cells')
        else:
            self.flags(enable=False, group='cells')
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance'}
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(values)

        with contextlib.nested(
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
                if cell_type == 'compute':
                    self.assertEqual(1, cells_update_mock.call_count)
                    self.assertTrue(len(cells_update_mock.call_args[0]) > 1)
                    self.assertEqual(cells_update_mock.call_args[0][0],
                                     self.context)
                    self.assertIsInstance(cells_update_mock.call_args[0][1],
                                          block_device_obj.BlockDeviceMapping)
                    self.assertEqual(cells_update_mock.call_args[1],
                                     {'create': update_or_create or None})
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

    def test_create(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance'}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        with mock.patch.object(cells_rpcapi.CellsAPI,
                               'bdm_update_or_create_at_top'):
            bdm.create()

        for k, v in values.iteritems():
            self.assertEqual(v, getattr(bdm, k))

    def test_create_fails(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance'}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        bdm.create()

        self.assertRaises(exception.ObjectActionError,
                          bdm.create, self.context)

    def test_create_fails_instance(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': 'fake-instance',
                  'instance': objects.Instance()}
        bdm = objects.BlockDeviceMapping(**values)
        self.assertRaises(exception.ObjectActionError,
                          bdm.create, self.context)

    def _test_destroy_mocked(self, cell_type=None):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume', 'id': 1,
                  'instance_uuid': 'fake-instance', 'device_name': 'fake'}
        if cell_type:
            self.flags(enable=True, cell_type=cell_type, group='cells')
        else:
            self.flags(enable=False, group='cells')
        with contextlib.nested(
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


class TestBlockDeviceMappingObject(test_objects._LocalTest,
                                   _TestBlockDeviceMappingObject):
    pass


class TestRemoteBlockDeviceMappingObject(test_objects._RemoteTest,
                                         _TestBlockDeviceMappingObject):
    pass


class _TestBlockDeviceMappingListObject(object):
    def fake_bdm(self, bdm_id):
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict({
            'id': bdm_id, 'instance_uuid': 'fake-instance',
            'device_name': '/dev/sda2',
            'source_type': 'snapshot',
            'destination_type': 'volume',
            'connection_info': "{'fake': 'connection_info'}",
            'snapshot_id': 'fake-snapshot-id-1',
            'boot_index': -1,
        })
        return fake_bdm

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_get_by_instance_uuid(self, get_all_by_inst):
        fakes = [self.fake_bdm(123), self.fake_bdm(456)]
        get_all_by_inst.return_value = fakes
        bdm_list = (
                objects.BlockDeviceMappingList.get_by_instance_uuid(
                    self.context, 'fake_instance_uuid'))
        for faked, got in zip(fakes, bdm_list):
            self.assertIsInstance(got, objects.BlockDeviceMapping)
            self.assertEqual(faked['id'], got.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_get_by_instance_uuid_no_result(self, get_all_by_inst):
        get_all_by_inst.return_value = None
        bdm_list = (
                objects.BlockDeviceMappingList.get_by_instance_uuid(
                    self.context, 'fake_instance_uuid'))
        self.assertEqual(0, len(bdm_list))

    def test_root_volume_metadata(self):
        fake_volume = {
                'volume_image_metadata': {'vol_test_key': 'vol_test_value'}}

        class FakeVolumeApi(object):
            def get(*args, **kwargs):
                return fake_volume

        block_device_mapping = block_device_obj.block_device_make_list(None, [
            fake_block_device.FakeDbBlockDeviceDict(
                {'id': 1,
                 'boot_index': 0,
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'volume_id': 'fake_volume_id',
                 'delete_on_termination': False})])

        volume_meta = block_device_mapping.root_metadata(
            self.context, None, FakeVolumeApi())
        self.assertEqual(fake_volume['volume_image_metadata'], volume_meta)

    def test_root_image_metadata(self):
        fake_image = {'properties': {'img_test_key': 'img_test_value'}}

        class FakeImageApi(object):
            def show(*args, **kwargs):
                return fake_image

        block_device_mapping = block_device_obj.block_device_make_list(None, [
            fake_block_device.FakeDbBlockDeviceDict(
                {'id': 1,
                 'boot_index': 0,
                 'source_type': 'image',
                 'destination_type': 'local',
                 'image_id': "fake-image",
                 'delete_on_termination': True})])

        image_meta = block_device_mapping.root_metadata(
            self.context, FakeImageApi(), None)
        self.assertEqual(fake_image['properties'], image_meta)


class TestBlockDeviceMappingListObject(test_objects._LocalTest,
                                       _TestBlockDeviceMappingListObject):
    pass


class TestRemoteBlockDeviceMappingListObject(
        test_objects._RemoteTest, _TestBlockDeviceMappingListObject):
    pass
