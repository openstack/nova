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
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context
from nova.db import api as db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import models as db_models
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
            'uuid': uuids.bdm,
            'instance_uuid': instance.get('uuid') or uuids.instance,
            'attachment_id': None,
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

    def test_save(self):
        fake_bdm = self.fake_bdm()
        with mock.patch.object(db, 'block_device_mapping_update',
                               return_value=fake_bdm) as bdm_update_mock:
            bdm_object = objects.BlockDeviceMapping(context=self.context)
            bdm_object.id = 123
            bdm_object.volume_id = 'fake_volume_id'
            bdm_object.save()

            bdm_update_mock.assert_called_once_with(
                    self.context, 123, {'volume_id': 'fake_volume_id'},
                    legacy=False)

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
    def test_get_by_volume_instance_uuid_mismatch(self, get_by_vol_id):
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

    def _test_create_mocked(self, update_or_create=False):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': uuids.instance,
                  'attachment_id': None}
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict(values)

        with test.nested(
            mock.patch.object(
                    db, 'block_device_mapping_create', return_value=fake_bdm),
            mock.patch.object(
                    db, 'block_device_mapping_update_or_create',
                    return_value=fake_bdm),
        ) as (bdm_create_mock, bdm_update_or_create_mock):
            bdm = objects.BlockDeviceMapping(context=self.context, **values)
            if update_or_create:
                method = bdm.update_or_create
            else:
                method = bdm.create

            method()
            if update_or_create:
                bdm_update_or_create_mock.assert_called_once_with(
                        self.context, values, legacy=False)
            else:
                bdm_create_mock.assert_called_once_with(
                        self.context, values, legacy=False)

    def test_create(self):
        self._test_create_mocked()

    def test_update_or_create(self):
        self._test_create_mocked(update_or_create=True)

    def test_create_fails(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': uuids.instance}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        bdm.create()

        self.assertRaises(exception.ObjectActionError,
                          bdm.create)

    def test_create_fails_instance(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': uuids.instance,
                  'instance': objects.Instance()}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        self.assertRaises(exception.ObjectActionError,
                          bdm.create)

    def test_destroy(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume', 'id': 1,
                  'instance_uuid': uuids.instance, 'device_name': 'fake'}
        with mock.patch.object(db, 'block_device_mapping_destroy') as bdm_del:
            bdm = objects.BlockDeviceMapping(context=self.context, **values)
            bdm.destroy()
            bdm_del.assert_called_once_with(self.context, values['id'])

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

    def test_obj_load_attr_not_instance(self):
        """Tests that lazy-loading something other than the instance field
        results in an error.
        """
        bdm = objects.BlockDeviceMapping(self.context, **self.fake_bdm())
        self.assertRaises(exception.ObjectActionError,
                          bdm.obj_load_attr, 'invalid')

    def test_obj_load_attr_orphaned(self):
        """Tests that lazy-loading the instance field on an orphaned BDM
        results in an error.
        """
        bdm = objects.BlockDeviceMapping(context=None, **self.fake_bdm())
        self.assertRaises(exception.OrphanedObjectError, bdm.obj_load_attr,
                          'instance')

    @mock.patch.object(objects.Instance, 'get_by_uuid',
                       return_value=objects.Instance(uuid=uuids.instance))
    def test_obj_load_attr_instance(self, mock_inst_get_by_uuid):
        """Tests lazy-loading the instance field."""
        bdm = objects.BlockDeviceMapping(self.context, **self.fake_bdm())
        self.assertEqual(mock_inst_get_by_uuid.return_value, bdm.instance)
        mock_inst_get_by_uuid.assert_called_once_with(
            self.context, bdm.instance_uuid)

    def test_obj_make_compatible_pre_1_17(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': uuids.instance, 'tag': 'fake-tag'}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        data = lambda x: x['nova_object.data']
        primitive = data(bdm.obj_to_primitive(target_version='1.17'))
        self.assertIn('tag', primitive)
        primitive = data(bdm.obj_to_primitive(target_version='1.16'))
        self.assertNotIn('tag', primitive)
        self.assertIn('volume_id', primitive)

    def test_obj_make_compatible_pre_1_18(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': uuids.instance,
                  'attachment_id': uuids.attachment_id}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        data = lambda x: x['nova_object.data']
        primitive = data(bdm.obj_to_primitive(target_version='1.17'))
        self.assertNotIn('attachment_id', primitive)
        self.assertIn('volume_id', primitive)

    def test_obj_make_compatible_pre_1_19(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': uuids.instance, 'uuid': uuids.bdm}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        data = lambda x: x['nova_object.data']
        primitive = data(bdm.obj_to_primitive(target_version='1.18'))
        self.assertNotIn('uuid', primitive)
        self.assertIn('volume_id', primitive)

    def test_obj_make_compatible_pre_1_20(self):
        values = {'source_type': 'volume', 'volume_id': 'fake-vol-id',
                  'destination_type': 'volume',
                  'instance_uuid': uuids.instance,
                  'volume_type': 'fake-lvm-1'}
        bdm = objects.BlockDeviceMapping(context=self.context, **values)
        data = lambda x: x['nova_object.data']
        primitive = data(bdm.obj_to_primitive(target_version='1.19'))
        self.assertNotIn('volume_type', primitive)
        self.assertIn('volume_id', primitive)


class TestBlockDeviceMappingUUIDMigration(test.TestCase):
    def setUp(self):
        super(TestBlockDeviceMappingUUIDMigration, self).setUp()
        self.context = context.RequestContext('fake-user-id',
                                              'fake-project-id')

        self.orig_create_uuid = \
            objects.BlockDeviceMapping._create_uuid

    @staticmethod
    @db_api.pick_context_manager_writer
    def _create_legacy_bdm(context, deleted=False):
        # Create a BDM with no uuid
        values = {'instance_uuid': uuids.instance_uuid}
        bdm_ref = db_models.BlockDeviceMapping()
        bdm_ref.update(values)
        bdm_ref.save(context.session)

        if deleted:
            bdm_ref.soft_delete(context.session)

        return bdm_ref

    @mock.patch.object(objects.BlockDeviceMapping, '_create_uuid')
    def test_populate_uuid(self, mock_create_uuid):
        mock_create_uuid.side_effect = self.orig_create_uuid

        self._create_legacy_bdm(self.context)
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, uuids.instance_uuid)

        # UUID should have been populated
        uuid = bdms[0].uuid
        self.assertIsNotNone(uuid)

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, uuids.instance_uuid)

        # UUID should not have changed
        self.assertEqual(uuid, bdms[0].uuid)
        self.assertEqual(1, mock_create_uuid.call_count)

    def test_create_uuid_race(self):
        # If threads read a legacy BDM object concurrently, we can end up
        # calling _create_uuid multiple times. Assert that calling _create_uuid
        # multiple times yields the same uuid.

        # NOTE(mdbooth): _create_uuid handles all forms of race, including any
        # amount of overlapping. I have not attempted to write unit tests for
        # all potential execution orders. This test is sufficient to
        # demonstrate that the compare-and-swap works correctly, and we trust
        # the correctness of the database for the rest.

        db_bdm = self._create_legacy_bdm(self.context)
        uuid1 = objects.BlockDeviceMapping._create_uuid(self.context,
                                                        db_bdm['id'])

        bdm = objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, uuids.instance_uuid)[0]
        self.assertEqual(uuid1, bdm.uuid)

        # We would only ever call this twice if we raced
        # This is also testing that the compare-and-swap doesn't overwrite an
        # existing uuid if we hit that race.
        uuid2 = objects.BlockDeviceMapping._create_uuid(self.context,
                                                        bdm['id'])

        self.assertEqual(uuid1, uuid2)

    def _assert_online_migration(self, expected_total, expected_done,
                                 limit=10):
        total, done = objects.BlockDeviceMapping.populate_uuids(
                self.context, limit)
        self.assertEqual(expected_total, total)
        self.assertEqual(expected_done, done)

    def test_online_migration(self):
        self._assert_online_migration(0, 0)

        # Create 2 BDMs, one with a uuid and one without
        self._create_legacy_bdm(self.context)
        db_api.block_device_mapping_create(self.context,
                {'uuid': uuids.bdm2, 'instance_uuid': uuids.instance_uuid},
                legacy=False)

        # Run the online migration. We should find 1 and update 1
        self._assert_online_migration(1, 1)

        # Fetch the BDMs and check we didn't modify the uuid of bdm2
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, uuids.instance_uuid)
        bdm_uuids = [bdm.uuid for bdm in bdms]
        self.assertIn(uuids.bdm2, bdm_uuids)
        self.assertNotIn(None, bdm_uuids)

        # Run the online migration again to see nothing was processed
        self._assert_online_migration(0, 0)

        # Assert that we assign a uuid to a deleted bdm.
        self._create_legacy_bdm(self.context, deleted=True)
        self._assert_online_migration(1, 1)

        # Test that we don't migrate more than the limit
        for i in range(0, 3):
            self._create_legacy_bdm(self.context)
        self._assert_online_migration(2, 2, limit=2)


class TestBlockDeviceMappingObject(test_objects._LocalTest,
                                   _TestBlockDeviceMappingObject):
    pass


class TestRemoteBlockDeviceMappingObject(test_objects._RemoteTest,
                                         _TestBlockDeviceMappingObject):
    pass


class _TestBlockDeviceMappingListObject(object):
    def fake_bdm(self, bdm_id, boot_index=-1, instance_uuid=uuids.instance):
        fake_bdm = fake_block_device.FakeDbBlockDeviceDict({
            'id': bdm_id,
            'boot_index': boot_index,
            'instance_uuid': instance_uuid,
            'attachment_id': None,
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
            self.context, [uuids.instance])
        self.assertEqual([uuids.instance], list(bdms_by_uuid.keys()))
        self.assertIsInstance(
            bdms_by_uuid[uuids.instance], objects.BlockDeviceMappingList)
        for faked, got in zip(fakes, bdms_by_uuid[uuids.instance]):
            self.assertIsInstance(got, objects.BlockDeviceMapping)
            self.assertEqual(faked['id'], got.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance_uuids')
    def test_bdms_by_instance_uuid_no_result(self, get_all_by_inst_uuids):
        get_all_by_inst_uuids.return_value = None
        bdms_by_uuid = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
            self.context, [uuids.instance])
        self.assertEqual({}, bdms_by_uuid)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance_uuids')
    def test_get_by_instance_uuids(self, get_all_by_inst_uuids):
        fakes = [self.fake_bdm(123), self.fake_bdm(456)]
        get_all_by_inst_uuids.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuids(
            self.context, [uuids.instance])
        for faked, got in zip(fakes, bdm_list):
            self.assertIsInstance(got, objects.BlockDeviceMapping)
            self.assertEqual(faked['id'], got.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance_uuids')
    def test_get_by_instance_uuids_no_result(self, get_all_by_inst_uuids):
        get_all_by_inst_uuids.return_value = None
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuids(
            self.context, [uuids.instance])
        self.assertEqual(0, len(bdm_list))

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_get_by_instance_uuid(self, get_all_by_inst):
        fakes = [self.fake_bdm(123), self.fake_bdm(456)]
        get_all_by_inst.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, uuids.instance)
        for faked, got in zip(fakes, bdm_list):
            self.assertIsInstance(got, objects.BlockDeviceMapping)
            self.assertEqual(faked['id'], got.id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_get_by_instance_uuid_no_result(self, get_all_by_inst):
        get_all_by_inst.return_value = None
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, uuids.instance)
        self.assertEqual(0, len(bdm_list))

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_root_bdm(self, get_all_by_inst):
        fakes = [self.fake_bdm(123), self.fake_bdm(456, boot_index=0)]
        get_all_by_inst.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, uuids.instance)
        self.assertEqual(456, bdm_list.root_bdm().id)

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_root_bdm_empty_bdm_list(self, get_all_by_inst):
        get_all_by_inst.return_value = None
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, uuids.instance)
        self.assertIsNone(bdm_list.root_bdm())

    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance')
    def test_root_bdm_undefined(self, get_all_by_inst):
        fakes = [
            self.fake_bdm(123, instance_uuid=uuids.instance_1),
            self.fake_bdm(456, instance_uuid=uuids.instance_2)
        ]
        get_all_by_inst.return_value = fakes
        bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, uuids.bdm_instance)
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
