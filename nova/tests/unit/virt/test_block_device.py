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

import mock
from os_brick import encryptors
from oslo_serialization import jsonutils

from nova import block_device
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit import matchers
from nova.tests import uuidsentinel as uuids
from nova.virt import block_device as driver_block_device
from nova.virt import driver
from nova.virt import fake as fake_virt
from nova.volume import cinder


class TestDriverBlockDevice(test.NoDBTestCase):
    # This is used to signal if we're dealing with a new style volume
    # attachment (Cinder v3.44 flow).
    attachment_id = None

    driver_classes = {
        'swap': driver_block_device.DriverSwapBlockDevice,
        'ephemeral': driver_block_device.DriverEphemeralBlockDevice,
        'volume': driver_block_device.DriverVolumeBlockDevice,
        'snapshot': driver_block_device.DriverSnapshotBlockDevice,
        'image': driver_block_device.DriverImageBlockDevice,
        'blank': driver_block_device.DriverBlankBlockDevice
    }

    swap_bdm_dict = block_device.BlockDeviceDict(
        {'id': 1, 'instance_uuid': uuids.instance,
         'device_name': '/dev/sdb1',
         'source_type': 'blank',
         'destination_type': 'local',
         'delete_on_termination': True,
         'guest_format': 'swap',
         'disk_bus': 'scsi',
         'volume_size': 2,
         'boot_index': -1})

    swap_driver_bdm = {
        'device_name': '/dev/sdb1',
        'swap_size': 2,
        'disk_bus': 'scsi'}

    swap_legacy_driver_bdm = {
        'device_name': '/dev/sdb1',
        'swap_size': 2}

    ephemeral_bdm_dict = block_device.BlockDeviceDict(
        {'id': 2, 'instance_uuid': uuids.instance,
         'device_name': '/dev/sdc1',
         'source_type': 'blank',
         'destination_type': 'local',
         'disk_bus': 'scsi',
         'device_type': 'disk',
         'volume_size': 4,
         'guest_format': 'ext4',
         'delete_on_termination': True,
         'boot_index': -1})

    ephemeral_driver_bdm = {
        'device_name': '/dev/sdc1',
        'size': 4,
        'device_type': 'disk',
        'guest_format': 'ext4',
        'disk_bus': 'scsi'}

    ephemeral_legacy_driver_bdm = {
        'device_name': '/dev/sdc1',
        'size': 4,
        'virtual_name': 'ephemeral0',
        'num': 0}

    volume_bdm_dict = block_device.BlockDeviceDict(
        {'id': 3, 'instance_uuid': uuids.instance,
         'device_name': '/dev/sda1',
         'source_type': 'volume',
         'disk_bus': 'scsi',
         'device_type': 'disk',
         'volume_size': 8,
         'destination_type': 'volume',
         'volume_id': 'fake-volume-id-1',
         'guest_format': 'ext4',
         'connection_info': '{"fake": "connection_info"}',
         'delete_on_termination': False,
         'boot_index': 0})

    volume_driver_bdm = {
        'mount_device': '/dev/sda1',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': False,
        'disk_bus': 'scsi',
        'device_type': 'disk',
        'guest_format': 'ext4',
        'boot_index': 0}

    volume_legacy_driver_bdm = {
        'mount_device': '/dev/sda1',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': False}

    snapshot_bdm_dict = block_device.BlockDeviceDict(
        {'id': 4, 'instance_uuid': uuids.instance,
         'device_name': '/dev/sda2',
         'delete_on_termination': True,
         'volume_size': 3,
         'disk_bus': 'scsi',
         'device_type': 'disk',
         'source_type': 'snapshot',
         'destination_type': 'volume',
         'connection_info': '{"fake": "connection_info"}',
         'snapshot_id': 'fake-snapshot-id-1',
         'volume_id': 'fake-volume-id-2',
         'boot_index': -1})

    snapshot_driver_bdm = {
        'mount_device': '/dev/sda2',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': True,
        'disk_bus': 'scsi',
        'device_type': 'disk',
        'guest_format': None,
        'boot_index': -1}

    snapshot_legacy_driver_bdm = {
        'mount_device': '/dev/sda2',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': True}

    image_bdm_dict = block_device.BlockDeviceDict(
        {'id': 5, 'instance_uuid': uuids.instance,
         'device_name': '/dev/sda2',
         'delete_on_termination': True,
         'volume_size': 1,
         'disk_bus': 'scsi',
         'device_type': 'disk',
         'source_type': 'image',
         'destination_type': 'volume',
         'connection_info': '{"fake": "connection_info"}',
         'image_id': 'fake-image-id-1',
         'volume_id': 'fake-volume-id-2',
         'boot_index': -1})

    image_driver_bdm = {
        'mount_device': '/dev/sda2',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': True,
        'disk_bus': 'scsi',
        'device_type': 'disk',
        'guest_format': None,
        'boot_index': -1}

    image_legacy_driver_bdm = {
        'mount_device': '/dev/sda2',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': True}

    blank_bdm_dict = block_device.BlockDeviceDict(
        {'id': 6, 'instance_uuid': uuids.instance,
         'device_name': '/dev/sda2',
         'delete_on_termination': True,
         'volume_size': 3,
         'disk_bus': 'scsi',
         'device_type': 'disk',
         'source_type': 'blank',
         'destination_type': 'volume',
         'connection_info': '{"fake": "connection_info"}',
         'snapshot_id': 'fake-snapshot-id-1',
         'volume_id': 'fake-volume-id-2',
         'boot_index': -1})

    blank_driver_bdm = {
        'mount_device': '/dev/sda2',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': True,
        'disk_bus': 'scsi',
        'device_type': 'disk',
        'guest_format': None,
        'boot_index': -1}

    blank_legacy_driver_bdm = {
        'mount_device': '/dev/sda2',
        'connection_info': {"fake": "connection_info"},
        'delete_on_termination': True}

    def setUp(self):
        super(TestDriverBlockDevice, self).setUp()
        self.volume_api = self.mox.CreateMock(cinder.API)
        self.virt_driver = self.mox.CreateMock(driver.ComputeDriver)
        self.context = context.RequestContext('fake_user',
                                              'fake_project')
        # create bdm objects for testing
        self.swap_bdm = fake_block_device.fake_bdm_object(
            self.context, self.swap_bdm_dict)
        self.ephemeral_bdm = fake_block_device.fake_bdm_object(
            self.context, self.ephemeral_bdm_dict)
        self.volume_bdm = fake_block_device.fake_bdm_object(
            self.context, self.volume_bdm_dict)
        self.snapshot_bdm = fake_block_device.fake_bdm_object(
            self.context, self.snapshot_bdm_dict)
        self.image_bdm = fake_block_device.fake_bdm_object(
            self.context, self.image_bdm_dict)
        self.blank_bdm = fake_block_device.fake_bdm_object(
            self.context, self.blank_bdm_dict)

        # Set the attachment_id on our fake class variables which we have
        # to do in setUp so that any attachment_id set by a subclass will
        # be used properly.
        for name in ('volume', 'snapshot', 'image', 'blank'):
            for attr in ('%s_bdm', '%s_driver_bdm'):
                bdm = getattr(self, attr % name)
                bdm['attachment_id'] = self.attachment_id

    @mock.patch('nova.virt.block_device.LOG')
    @mock.patch('os_brick.encryptors')
    def test_driver_detach_passes_failed(self, enc, log):
        virt = mock.MagicMock()
        virt.detach_volume.side_effect = exception.DeviceDetachFailed(
            device='sda', reason='because testing')
        driver_bdm = self.driver_classes['volume'](self.volume_bdm)
        inst = mock.MagicMock(),
        vol_api = mock.MagicMock()

        # Make sure we pass through DeviceDetachFailed,
        # but don't log it as an exception, just a warning
        self.assertRaises(exception.DeviceDetachFailed,
                          driver_bdm.driver_detach,
                          self.context, inst, vol_api, virt)
        self.assertFalse(log.exception.called)
        self.assertTrue(log.warning.called)
        vol_api.roll_detaching.assert_called_once_with(self.context,
                                                       driver_bdm.volume_id)

    def test_no_device_raises(self):
        for name, cls in self.driver_classes.items():
            bdm = fake_block_device.fake_bdm_object(
                    self.context, {'no_device': True})
            self.assertRaises(driver_block_device._NotTransformable,
                              cls, bdm)

    def _test_driver_device(self, name):
        db_bdm = getattr(self, "%s_bdm" % name)
        test_bdm = self.driver_classes[name](db_bdm)
        self.assertThat(test_bdm, matchers.DictMatches(
            getattr(self, "%s_driver_bdm" % name)))

        for k, v in db_bdm.items():
            field_val = getattr(test_bdm._bdm_obj, k)
            if isinstance(field_val, bool):
                v = bool(v)
            self.assertEqual(field_val, v)

        self.assertThat(test_bdm.legacy(),
                        matchers.DictMatches(
                            getattr(self, "%s_legacy_driver_bdm" % name)))

        # Test passthru attributes
        for passthru in test_bdm._proxy_as_attr:
            self.assertEqual(getattr(test_bdm, passthru),
                             getattr(test_bdm._bdm_obj, passthru))

        # Make sure that all others raise _invalidType
        for other_name, cls in self.driver_classes.items():
            if other_name == name:
                continue
            self.assertRaises(driver_block_device._InvalidType,
                              cls,
                              getattr(self, '%s_bdm' % name))

        # Test the save method
        with mock.patch.object(test_bdm._bdm_obj, 'save') as save_mock:
            for fld, alias in test_bdm._update_on_save.items():
                # We can't set fake values on enums, like device_type,
                # so skip those.
                if not isinstance(test_bdm._bdm_obj.fields[fld],
                                  fields.BaseEnumField):
                    test_bdm[alias or fld] = 'fake_changed_value'
            test_bdm.save()
            for fld, alias in test_bdm._update_on_save.items():
                self.assertEqual(test_bdm[alias or fld],
                                 getattr(test_bdm._bdm_obj, fld))

            save_mock.assert_called_once_with()

        def check_save():
            self.assertEqual(set([]), test_bdm._bdm_obj.obj_what_changed())

        # Test that nothing is set on the object if there are no actual changes
        test_bdm._bdm_obj.obj_reset_changes()
        with mock.patch.object(test_bdm._bdm_obj, 'save') as save_mock:
            save_mock.side_effect = check_save
            test_bdm.save()

    def _test_driver_default_size(self, name):
        size = 'swap_size' if name == 'swap' else 'size'
        no_size_bdm = getattr(self, "%s_bdm_dict" % name).copy()
        no_size_bdm['volume_size'] = None

        driver_bdm = self.driver_classes[name](
            fake_block_device.fake_bdm_object(self.context, no_size_bdm))
        self.assertEqual(driver_bdm[size], 0)

        del no_size_bdm['volume_size']

        driver_bdm = self.driver_classes[name](
            fake_block_device.fake_bdm_object(self.context, no_size_bdm))
        self.assertEqual(driver_bdm[size], 0)

    def test_driver_swap_block_device(self):
        self._test_driver_device("swap")

    def test_driver_swap_default_size(self):
        self._test_driver_default_size('swap')

    def test_driver_ephemeral_block_device(self):
        self._test_driver_device("ephemeral")

    def test_driver_ephemeral_default_size(self):
        self._test_driver_default_size('ephemeral')

    def test_driver_volume_block_device(self):
        self._test_driver_device("volume")

        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        self.assertEqual(test_bdm['connection_info'],
                         jsonutils.loads(test_bdm._bdm_obj.connection_info))
        self.assertEqual(test_bdm._bdm_obj.id, 3)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-1')
        self.assertEqual(test_bdm.volume_size, 8)

    def test_driver_snapshot_block_device(self):
        self._test_driver_device("snapshot")

        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)
        self.assertEqual(test_bdm._bdm_obj.id, 4)
        self.assertEqual(test_bdm.snapshot_id, 'fake-snapshot-id-1')
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')
        self.assertEqual(test_bdm.volume_size, 3)

    def test_driver_image_block_device(self):
        self._test_driver_device('image')

        test_bdm = self.driver_classes['image'](
            self.image_bdm)
        self.assertEqual(test_bdm._bdm_obj.id, 5)
        self.assertEqual(test_bdm.image_id, 'fake-image-id-1')
        self.assertEqual(test_bdm.volume_size, 1)

    def test_driver_image_block_device_destination_local(self):
        self._test_driver_device('image')
        bdm = self.image_bdm_dict.copy()
        bdm['destination_type'] = 'local'
        self.assertRaises(driver_block_device._InvalidType,
                          self.driver_classes['image'],
                          fake_block_device.fake_bdm_object(self.context, bdm))

    def test_driver_blank_block_device(self):
        self._test_driver_device('blank')

        test_bdm = self.driver_classes['blank'](
            self.blank_bdm)
        self.assertEqual(6, test_bdm._bdm_obj.id)
        self.assertEqual('fake-volume-id-2', test_bdm.volume_id)
        self.assertEqual(3, test_bdm.volume_size)

    def _test_call_wait_func(self, delete_on_termination, delete_fail=False):
        test_bdm = self.driver_classes['volume'](self.volume_bdm)
        test_bdm['delete_on_termination'] = delete_on_termination
        with mock.patch.object(self.volume_api, 'delete') as vol_delete:
            wait_func = mock.MagicMock()
            mock_exception = exception.VolumeNotCreated(volume_id='fake-id',
                                                        seconds=1,
                                                        attempts=1,
                                                        volume_status='error')
            wait_func.side_effect = mock_exception

            if delete_on_termination and delete_fail:
                vol_delete.side_effect = Exception()

            self.assertRaises(exception.VolumeNotCreated,
                              test_bdm._call_wait_func,
                              context=self.context,
                              wait_func=wait_func,
                              volume_api=self.volume_api,
                              volume_id='fake-id')
            self.assertEqual(delete_on_termination, vol_delete.called)

    def test_call_wait_delete_volume(self):
        self._test_call_wait_func(True)

    def test_call_wait_delete_volume_fail(self):
        self._test_call_wait_func(True, True)

    def test_call_wait_no_delete_volume(self):
        self._test_call_wait_func(False)

    def test_volume_delete_attachment(self, include_shared_targets=False):
        attachment_id = uuids.attachment
        driver_bdm = self.driver_classes['volume'](self.volume_bdm)
        driver_bdm['attachment_id'] = attachment_id

        elevated_context = self.context.elevated()
        instance_detail = {'id': '123', 'uuid': uuids.uuid,
                           'availability_zone': None}
        instance = fake_instance.fake_instance_obj(self.context,
                                                   **instance_detail)
        connector = {'ip': 'fake_ip', 'host': 'fake_host'}
        volume = {'id': driver_bdm.volume_id,
                  'attach_status': 'attached',
                  'status': 'in-use'}
        if include_shared_targets:
            volume['shared_targets'] = True
            volume['service_uuid'] = uuids.service_uuid

        with test.nested(
            mock.patch.object(driver_bdm, '_get_volume', return_value=volume),
            mock.patch.object(self.virt_driver, 'get_volume_connector',
                              return_value=connector),
            mock.patch('nova.utils.synchronized',
                side_effect=lambda a: lambda f: lambda *args: f(*args)),
            mock.patch.object(self.volume_api, 'attachment_delete'),
        ) as (mock_get_volume, mock_get_connector, mock_sync, vapi_attach_del):

            driver_bdm.detach(elevated_context, instance,
                              self.volume_api, self.virt_driver,
                              attachment_id=attachment_id)

            if include_shared_targets:
                mock_sync.assert_called_once_with((uuids.service_uuid))
            vapi_attach_del.assert_called_once_with(elevated_context,
                                                    attachment_id)

    def test_volume_delete_attachment_with_shared_targets(self):
        self.test_volume_delete_attachment(include_shared_targets=True)

    def _test_volume_attach(self, driver_bdm, bdm_dict,
                            fake_volume, fail_check_av_zone=False,
                            driver_attach=False, fail_driver_attach=False,
                            volume_attach=True, fail_volume_attach=False,
                            access_mode='rw', availability_zone=None,
                            multiattach=False, driver_multi_attach=False,
                            fail_with_virt_driver=False,
                            include_shared_targets=False):
        if driver_multi_attach:
            self.virt_driver.capabilities['supports_multiattach'] = True
        else:
            self.virt_driver.capabilities['supports_multiattach'] = False
        elevated_context = self.context.elevated()
        self.stubs.Set(self.context, 'elevated',
                       lambda: elevated_context)
        self.mox.StubOutWithMock(driver_bdm._bdm_obj, 'save')
        self.mox.StubOutWithMock(encryptors, 'get_encryption_metadata')
        instance_detail = {'id': '123', 'uuid': uuids.uuid,
                           'availability_zone': availability_zone}
        instance = fake_instance.fake_instance_obj(self.context,
                                                   **instance_detail)
        connector = {'ip': 'fake_ip', 'host': 'fake_host'}
        connection_info = {'data': {'access_mode': access_mode}}
        expected_conn_info = {'data': {'access_mode': access_mode},
                              'serial': fake_volume['id']}
        if multiattach and driver_multi_attach:
            expected_conn_info['multiattach'] = True
        enc_data = {'fake': 'enc_data'}

        if include_shared_targets:
            fake_volume['shared_targets'] = True
            fake_volume['service_uuid'] = uuids.service_uuid
            self.volume_api.get(
                self.context, fake_volume['id'],
                microversion='3.48').AndReturn(fake_volume)
        else:
            # First call to get() fails because the API isn't new enough.
            self.volume_api.get(
                self.context, fake_volume['id'], microversion='3.48').AndRaise(
                    exception.CinderAPIVersionNotAvailable(version='3.48'))
            # So we fallback to the old call.
            self.volume_api.get(self.context,
                                fake_volume['id']).AndReturn(fake_volume)

        if not fail_check_av_zone:
            self.volume_api.check_availability_zone(self.context,
                                fake_volume,
                                instance=instance).AndReturn(None)
        else:
            self.volume_api.check_availability_zone(self.context,
                                fake_volume,
                                instance=instance).AndRaise(
                                        test.TestingException)
            # The @update_db decorator will save any changes.
            driver_bdm._bdm_obj.save().AndReturn(None)
            return instance, expected_conn_info

        self.virt_driver.get_volume_connector(instance).AndReturn(connector)

        if fail_with_virt_driver:
            driver_bdm._bdm_obj.save().AndReturn(None)
            return instance, expected_conn_info

        if self.attachment_id is None:
            self.volume_api.initialize_connection(
                elevated_context, fake_volume['id'],
                connector).AndReturn(connection_info)
        else:
            self.volume_api.attachment_update(
                elevated_context, self.attachment_id, connector,
                bdm_dict['device_name']).AndReturn(
                    {'connection_info': connection_info})

        if driver_attach:
            encryptors.get_encryption_metadata(
                    elevated_context, self.volume_api, fake_volume['id'],
                    connection_info).AndReturn(enc_data)
            if not fail_driver_attach:
                self.virt_driver.attach_volume(
                        elevated_context, expected_conn_info, instance,
                        bdm_dict['device_name'],
                        disk_bus=bdm_dict['disk_bus'],
                        device_type=bdm_dict['device_type'],
                        encryption=enc_data).AndReturn(None)
            else:
                self.virt_driver.attach_volume(
                        elevated_context, expected_conn_info, instance,
                        bdm_dict['device_name'],
                        disk_bus=bdm_dict['disk_bus'],
                        device_type=bdm_dict['device_type'],
                        encryption=enc_data).AndRaise(test.TestingException)
                if self.attachment_id is None:
                    self.volume_api.terminate_connection(
                            elevated_context, fake_volume['id'],
                            connector).AndReturn(None)
                else:
                    self.volume_api.attachment_delete(
                        elevated_context, self.attachment_id).AndReturn(None)
                # The @update_db decorator will save any changes.
                driver_bdm._bdm_obj.save().AndReturn(None)
                return instance, expected_conn_info

        if volume_attach:
            # save updates before marking the volume as in-use
            driver_bdm._bdm_obj.save().AndReturn(None)
            if not fail_volume_attach:
                if self.attachment_id is None:
                    self.volume_api.attach(elevated_context, fake_volume['id'],
                                           uuids.uuid, bdm_dict['device_name'],
                                            mode=access_mode).AndReturn(None)
                else:
                    self.volume_api.attachment_complete(
                        elevated_context, self.attachment_id).AndReturn(None)
            else:
                if self.attachment_id is None:
                    self.volume_api.attach(elevated_context, fake_volume['id'],
                                           uuids.uuid, bdm_dict['device_name'],
                                            mode=access_mode).AndRaise(
                                                test.TestingException)
                    if driver_attach:
                        self.virt_driver.detach_volume(
                            self.context, expected_conn_info, instance,
                            bdm_dict['device_name'],
                            encryption=enc_data).AndReturn(None)
                    self.volume_api.terminate_connection(
                        elevated_context, fake_volume['id'],
                        connector).AndReturn(None)
                    self.volume_api.detach(elevated_context,
                                           fake_volume['id']).AndReturn(None)
                else:
                    self.volume_api.attachment_complete(
                        elevated_context, self.attachment_id).AndRaise(
                            test.TestingException)
                    self.volume_api.attachment_delete(
                        elevated_context, self.attachment_id).AndReturn(None)

        # The @update_db decorator will save any changes.
        driver_bdm._bdm_obj.save().AndReturn(None)
        return instance, expected_conn_info

    def test_volume_attach(self, include_shared_targets=False):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume,
                include_shared_targets=include_shared_targets)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_volume_attach_with_shared_targets(self):
        self.test_volume_attach(include_shared_targets=True)

    def test_volume_attach_ro(self):
        test_bdm = self.driver_classes['volume'](self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, access_mode='ro')

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_volume_attach_update_size(self):
        test_bdm = self.driver_classes['volume'](self.volume_bdm)
        test_bdm.volume_size = None
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached',
                  'size': 42}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver)
        self.assertEqual(expected_conn_info, test_bdm['connection_info'])
        self.assertEqual(42, test_bdm.volume_size)

    def test_volume_attach_check_av_zone_fails(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1'}

        instance, _ = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, fail_check_av_zone=True)
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException, test_bdm.attach, self.context,
                         instance, self.volume_api, self.virt_driver)

    def test_volume_no_volume_attach(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, driver_attach=False)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver,
                        do_driver_attach=False)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_volume_attach_no_check_driver_attach(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, driver_attach=True)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver,
                        do_driver_attach=True)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_volume_attach_driver_attach_fails(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1'}

        instance, _ = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, driver_attach=True,
                fail_driver_attach=True)
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException, test_bdm.attach, self.context,
                         instance, self.volume_api, self.virt_driver,
                         do_driver_attach=True)

    @mock.patch('nova.objects.BlockDeviceMapping.save')
    @mock.patch('nova.volume.cinder.API')
    @mock.patch('os_brick.encryptors.get_encryption_metadata',
                return_value={})
    def test_volume_attach_volume_attach_fails(self, mock_get_encryption,
                                               mock_volume_api, mock_bdm_save):
        """Tests that attaching the volume fails and driver rollback occurs."""
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}
        mock_volume_api.get.return_value = volume
        instance = fake_instance.fake_instance_obj(self.context)
        virt_driver = fake_virt.SmallFakeDriver(virtapi=mock.MagicMock())

        fake_conn_info = {
            'serial': volume['id'],
            'data': {
                'foo': 'bar'
            }
        }
        if self.attachment_id:
            mock_volume_api.attachment_update.return_value = {
                'connection_info': fake_conn_info
            }
            mock_volume_api.attachment_complete.side_effect = (
                test.TestingException)
        else:
            # legacy flow, stub out the volume_api accordingly
            mock_volume_api.attach.side_effect = test.TestingException
            mock_volume_api.initialize_connection.return_value = fake_conn_info

        with mock.patch.object(virt_driver, 'detach_volume') as drvr_detach:
            with mock.patch.object(self.context, 'elevated',
                                   return_value=self.context):
                self.assertRaises(test.TestingException, test_bdm.attach,
                                  self.context, instance, mock_volume_api,
                                  virt_driver, do_driver_attach=True)

        drvr_detach.assert_called_once_with(
            self.context, fake_conn_info, instance,
            self.volume_bdm.device_name,
            encryption=mock_get_encryption.return_value)

        if self.attachment_id:
            mock_volume_api.attachment_delete.assert_called_once_with(
                self.context, self.attachment_id)
        else:
            mock_volume_api.terminate_connection.assert_called_once_with(
                self.context, volume['id'],
                virt_driver.get_volume_connector(instance))
            mock_volume_api.detach.assert_called_once_with(
                self.context, volume['id'])

        self.assertEqual(2, mock_bdm_save.call_count)

    def test_volume_attach_no_driver_attach_volume_attach_fails(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, _ = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, fail_volume_attach=True)
        self.mox.ReplayAll()

        self.assertRaises(test.TestingException, test_bdm.attach, self.context,
                         instance, self.volume_api, self.virt_driver,
                         do_driver_attach=False)

    def test_refresh_connection(self):
        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        instance = {'id': 'fake_id', 'uuid': uuids.uuid}
        connector = {'ip': 'fake_ip', 'host': 'fake_host'}
        connection_info = {'data': {'multipath_id': 'fake_multipath_id'}}
        expected_conn_info = {'data': {'multipath_id': 'fake_multipath_id'},
                              'serial': 'fake-volume-id-2'}

        self.mox.StubOutWithMock(test_bdm._bdm_obj, 'save')

        if self.attachment_id is None:
            self.virt_driver.get_volume_connector(instance).AndReturn(
                connector)
            self.volume_api.initialize_connection(
                self.context, test_bdm.volume_id,
                connector).AndReturn(connection_info)
        else:
            self.volume_api.attachment_get(
                self.context, self.attachment_id).AndReturn(
                    {'connection_info': connection_info})
        test_bdm._bdm_obj.save().AndReturn(None)

        self.mox.ReplayAll()

        test_bdm.refresh_connection_info(self.context, instance,
                                         self.volume_api, self.virt_driver)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_snapshot_attach_no_volume(self):
        no_volume_snapshot = self.snapshot_bdm_dict.copy()
        no_volume_snapshot['volume_id'] = None
        test_bdm = self.driver_classes['snapshot'](
                fake_block_device.fake_bdm_object(
                        self.context, no_volume_snapshot))
        # When we create a volume, we attach it using the old flow.
        self.attachment_id = None

        snapshot = {'id': 'fake-volume-id-1',
                    'attach_status': 'detached'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        wait_func = self.mox.CreateMockAnything()

        self.volume_api.get_snapshot(self.context,
                                     'fake-snapshot-id-1').AndReturn(snapshot)
        self.volume_api.create(self.context, 3, '', '', snapshot,
                               availability_zone=None).AndReturn(volume)
        wait_func(self.context, 'fake-volume-id-2').AndReturn(None)
        instance, expected_conn_info = self._test_volume_attach(
               test_bdm, no_volume_snapshot, volume)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, wait_func)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_snapshot_attach_no_volume_cinder_cross_az_attach_false(self):
        # Tests that the volume created from the snapshot has the same AZ as
        # the instance.
        self.flags(cross_az_attach=False, group='cinder')
        no_volume_snapshot = self.snapshot_bdm_dict.copy()
        no_volume_snapshot['volume_id'] = None
        test_bdm = self.driver_classes['snapshot'](
                fake_block_device.fake_bdm_object(
                        self.context, no_volume_snapshot))
        # When we create a volume, we attach it using the old flow.
        self.attachment_id = None

        snapshot = {'id': 'fake-volume-id-1',
                    'attach_status': 'detached'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        wait_func = self.mox.CreateMockAnything()

        self.volume_api.get_snapshot(self.context,
                                     'fake-snapshot-id-1').AndReturn(snapshot)
        self.volume_api.create(self.context, 3, '', '', snapshot,
                               availability_zone='test-az').AndReturn(volume)
        wait_func(self.context, 'fake-volume-id-2').AndReturn(None)
        instance, expected_conn_info = self._test_volume_attach(
               test_bdm, no_volume_snapshot, volume,
               availability_zone='test-az')
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, wait_func)
        self.assertEqual('fake-volume-id-2', test_bdm.volume_id)

    def test_snapshot_attach_fail_volume(self):
        fail_volume_snapshot = self.snapshot_bdm_dict.copy()
        fail_volume_snapshot['volume_id'] = None
        test_bdm = self.driver_classes['snapshot'](
                fake_block_device.fake_bdm_object(
                        self.context, fail_volume_snapshot))

        snapshot = {'id': 'fake-volume-id-1',
                    'attach_status': 'detached'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx,
                                                   **{'uuid': uuids.uuid})
        with test.nested(
            mock.patch.object(self.volume_api, 'get_snapshot',
                              return_value=snapshot),
            mock.patch.object(self.volume_api, 'create', return_value=volume),
            mock.patch.object(self.volume_api, 'delete'),
        ) as (vol_get_snap, vol_create, vol_delete):
            wait_func = mock.MagicMock()
            mock_exception = exception.VolumeNotCreated(volume_id=volume['id'],
                                                        seconds=1,
                                                        attempts=1,
                                                        volume_status='error')
            wait_func.side_effect = mock_exception
            self.assertRaises(exception.VolumeNotCreated,
                              test_bdm.attach, context=self.context,
                              instance=instance,
                              volume_api=self.volume_api,
                              virt_driver=self.virt_driver,
                              wait_func=wait_func)

            vol_get_snap.assert_called_once_with(
                self.context, 'fake-snapshot-id-1')
            vol_create.assert_called_once_with(
                self.context, 3, '', '', snapshot, availability_zone=None)
            vol_delete.assert_called_once_with(self.context, volume['id'])

    def test_snapshot_attach_volume(self):
        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        instance = {'id': 'fake_id', 'uuid': uuids.uuid}

        volume_class = self.driver_classes['volume']
        self.mox.StubOutWithMock(volume_class, 'attach')

        # Make sure theses are not called
        self.mox.StubOutWithMock(self.volume_api, 'get_snapshot')
        self.mox.StubOutWithMock(self.volume_api, 'create')

        volume_class.attach(self.context, instance, self.volume_api,
                            self.virt_driver).AndReturn(None)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_image_attach_no_volume(self):
        no_volume_image = self.image_bdm_dict.copy()
        no_volume_image['volume_id'] = None
        test_bdm = self.driver_classes['image'](
                fake_block_device.fake_bdm_object(
                        self.context, no_volume_image))
        # When we create a volume, we attach it using the old flow.
        self.attachment_id = None

        image = {'id': 'fake-image-id-1'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        wait_func = self.mox.CreateMockAnything()

        self.volume_api.create(self.context, 1, '', '', image_id=image['id'],
                               availability_zone=None).AndReturn(volume)
        wait_func(self.context, 'fake-volume-id-2').AndReturn(None)
        instance, expected_conn_info = self._test_volume_attach(
               test_bdm, no_volume_image, volume)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, wait_func)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_image_attach_no_volume_cinder_cross_az_attach_false(self):
        # Tests that the volume created from the image has the same AZ as the
        # instance.
        self.flags(cross_az_attach=False, group='cinder')
        no_volume_image = self.image_bdm_dict.copy()
        no_volume_image['volume_id'] = None
        test_bdm = self.driver_classes['image'](
                fake_block_device.fake_bdm_object(
                        self.context, no_volume_image))
        # When we create a volume, we attach it using the old flow.
        self.attachment_id = None

        image = {'id': 'fake-image-id-1'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        wait_func = self.mox.CreateMockAnything()

        self.volume_api.create(self.context, 1, '', '', image_id=image['id'],
                               availability_zone='test-az').AndReturn(volume)
        wait_func(self.context, 'fake-volume-id-2').AndReturn(None)
        instance, expected_conn_info = self._test_volume_attach(
               test_bdm, no_volume_image, volume,
               availability_zone='test-az')
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, wait_func)
        self.assertEqual('fake-volume-id-2', test_bdm.volume_id)

    def test_image_attach_fail_volume(self):
        fail_volume_image = self.image_bdm_dict.copy()
        fail_volume_image['volume_id'] = None
        test_bdm = self.driver_classes['image'](
                fake_block_device.fake_bdm_object(
                        self.context, fail_volume_image))

        image = {'id': 'fake-image-id-1'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx,
                                                   **{'uuid': uuids.uuid})
        with test.nested(
            mock.patch.object(self.volume_api, 'create', return_value=volume),
            mock.patch.object(self.volume_api, 'delete'),
        ) as (vol_create, vol_delete):
            wait_func = mock.MagicMock()
            mock_exception = exception.VolumeNotCreated(volume_id=volume['id'],
                                                        seconds=1,
                                                        attempts=1,
                                                        volume_status='error')
            wait_func.side_effect = mock_exception
            self.assertRaises(exception.VolumeNotCreated,
                              test_bdm.attach, context=self.context,
                              instance=instance,
                              volume_api=self.volume_api,
                              virt_driver=self.virt_driver,
                              wait_func=wait_func)

            vol_create.assert_called_once_with(
                self.context, 1, '', '', image_id=image['id'],
                availability_zone=None)
            vol_delete.assert_called_once_with(self.context, volume['id'])

    def test_image_attach_volume(self):
        test_bdm = self.driver_classes['image'](
            self.image_bdm)

        instance = {'id': 'fake_id', 'uuid': uuids.uuid}

        volume_class = self.driver_classes['volume']
        self.mox.StubOutWithMock(volume_class, 'attach')

        # Make sure theses are not called
        self.mox.StubOutWithMock(self.volume_api, 'get_snapshot')
        self.mox.StubOutWithMock(self.volume_api, 'create')

        volume_class.attach(self.context, instance, self.volume_api,
                            self.virt_driver).AndReturn(None)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_blank_attach_fail_volume(self):
        no_blank_volume = self.blank_bdm_dict.copy()
        no_blank_volume['volume_id'] = None
        test_bdm = self.driver_classes['blank'](
                fake_block_device.fake_bdm_object(
                        self.context, no_blank_volume))
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx,
                                                   **{'uuid': uuids.uuid})
        volume = {'id': 'fake-volume-id-2',
                  'display_name': '%s-blank-vol' % uuids.uuid}

        with test.nested(
            mock.patch.object(self.volume_api, 'create', return_value=volume),
            mock.patch.object(self.volume_api, 'delete'),
        ) as (vol_create, vol_delete):
            wait_func = mock.MagicMock()
            mock_exception = exception.VolumeNotCreated(volume_id=volume['id'],
                                                        seconds=1,
                                                        attempts=1,
                                                        volume_status='error')
            wait_func.side_effect = mock_exception
            self.assertRaises(exception.VolumeNotCreated,
                              test_bdm.attach, context=self.context,
                              instance=instance,
                              volume_api=self.volume_api,
                              virt_driver=self.virt_driver,
                              wait_func=wait_func)

            vol_create.assert_called_once_with(
                self.context, test_bdm.volume_size,
                '%s-blank-vol' % uuids.uuid,
                '', availability_zone=None)
            vol_delete.assert_called_once_with(
                self.context, volume['id'])

    def test_blank_attach_volume(self):
        no_blank_volume = self.blank_bdm_dict.copy()
        no_blank_volume['volume_id'] = None
        test_bdm = self.driver_classes['blank'](
                fake_block_device.fake_bdm_object(
                        self.context, no_blank_volume))
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx,
                                                   **{'uuid': uuids.uuid})
        volume_class = self.driver_classes['volume']
        volume = {'id': 'fake-volume-id-2',
                  'display_name': '%s-blank-vol' % uuids.uuid}

        with test.nested(
            mock.patch.object(self.volume_api, 'create', return_value=volume),
            mock.patch.object(volume_class, 'attach')
        ) as (vol_create, vol_attach):
            test_bdm.attach(self.context, instance, self.volume_api,
                            self.virt_driver)

            vol_create.assert_called_once_with(
                self.context, test_bdm.volume_size,
                '%s-blank-vol' % uuids.uuid,
                '', availability_zone=None)
            vol_attach.assert_called_once_with(self.context, instance,
                                               self.volume_api,
                                               self.virt_driver)
            self.assertEqual('fake-volume-id-2', test_bdm.volume_id)

    def test_blank_attach_volume_cinder_cross_az_attach_false(self):
        # Tests that the blank volume created is in the same availability zone
        # as the instance.
        self.flags(cross_az_attach=False, group='cinder')
        no_blank_volume = self.blank_bdm_dict.copy()
        no_blank_volume['volume_id'] = None
        test_bdm = self.driver_classes['blank'](
                fake_block_device.fake_bdm_object(
                        self.context, no_blank_volume))
        updates = {'uuid': uuids.uuid, 'availability_zone': 'test-az'}
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx,
                                                   **updates)
        volume_class = self.driver_classes['volume']
        volume = {'id': 'fake-volume-id-2',
                  'display_name': '%s-blank-vol' % uuids.uuid}

        with mock.patch.object(self.volume_api, 'create',
                               return_value=volume) as vol_create:
            with mock.patch.object(volume_class, 'attach') as vol_attach:
                test_bdm.attach(self.context, instance, self.volume_api,
                                self.virt_driver)

                vol_create.assert_called_once_with(
                    self.context, test_bdm.volume_size,
                    '%s-blank-vol' % uuids.uuid,
                    '', availability_zone='test-az')
                vol_attach.assert_called_once_with(self.context, instance,
                                                   self.volume_api,
                                                   self.virt_driver)
                self.assertEqual('fake-volume-id-2', test_bdm.volume_id)

    def test_convert_block_devices(self):
        bdms = objects.BlockDeviceMappingList(
                objects=[self.volume_bdm, self.ephemeral_bdm])
        converted = driver_block_device._convert_block_devices(
            self.driver_classes['volume'], bdms)
        self.assertEqual(converted, [self.volume_driver_bdm])

    def test_convert_all_volumes(self):
        converted = driver_block_device.convert_all_volumes()
        self.assertEqual([], converted)

        converted = driver_block_device.convert_all_volumes(
            self.volume_bdm, self.ephemeral_bdm, self.image_bdm,
            self.blank_bdm, self.snapshot_bdm)
        self.assertEqual(converted, [self.volume_driver_bdm,
                                     self.image_driver_bdm,
                                     self.blank_driver_bdm,
                                     self.snapshot_driver_bdm])

    def test_convert_volume(self):
        self.assertIsNone(driver_block_device.convert_volume(self.swap_bdm))
        self.assertEqual(self.volume_driver_bdm,
                         driver_block_device.convert_volume(self.volume_bdm))
        self.assertEqual(self.snapshot_driver_bdm,
                         driver_block_device.convert_volume(self.snapshot_bdm))

    def test_legacy_block_devices(self):
        test_snapshot = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        block_device_mapping = [test_snapshot, test_snapshot]
        legacy_bdm = driver_block_device.legacy_block_devices(
            block_device_mapping)
        self.assertEqual(legacy_bdm, [self.snapshot_legacy_driver_bdm,
                                       self.snapshot_legacy_driver_bdm])

        # Test that the ephemerals work as expected
        test_ephemerals = [self.driver_classes['ephemeral'](
            self.ephemeral_bdm) for _ in range(2)]
        expected = [self.ephemeral_legacy_driver_bdm.copy()
                             for _ in range(2)]
        expected[0]['virtual_name'] = 'ephemeral0'
        expected[0]['num'] = 0
        expected[1]['virtual_name'] = 'ephemeral1'
        expected[1]['num'] = 1
        legacy_ephemerals = driver_block_device.legacy_block_devices(
            test_ephemerals)
        self.assertEqual(expected, legacy_ephemerals)

    def test_get_swap(self):
        swap = [self.swap_driver_bdm]
        legacy_swap = [self.swap_legacy_driver_bdm]
        no_swap = [self.volume_driver_bdm]

        self.assertEqual(swap[0], driver_block_device.get_swap(swap))
        self.assertEqual(legacy_swap[0],
                          driver_block_device.get_swap(legacy_swap))
        self.assertIsNone(driver_block_device.get_swap(no_swap))
        self.assertIsNone(driver_block_device.get_swap([]))

    def test_is_implemented(self):
        for bdm in (self.image_bdm, self.volume_bdm, self.swap_bdm,
                    self.ephemeral_bdm, self.snapshot_bdm):
            self.assertTrue(driver_block_device.is_implemented(bdm))
        local_image = self.image_bdm_dict.copy()
        local_image['destination_type'] = 'local'
        self.assertFalse(driver_block_device.is_implemented(
            fake_block_device.fake_bdm_object(self.context, local_image)))

    def test_is_block_device_mapping(self):
        test_swap = self.driver_classes['swap'](self.swap_bdm)
        test_ephemeral = self.driver_classes['ephemeral'](self.ephemeral_bdm)
        test_image = self.driver_classes['image'](self.image_bdm)
        test_snapshot = self.driver_classes['snapshot'](self.snapshot_bdm)
        test_volume = self.driver_classes['volume'](self.volume_bdm)
        test_blank = self.driver_classes['blank'](self.blank_bdm)

        for bdm in (test_image, test_snapshot, test_volume, test_blank):
            self.assertTrue(driver_block_device.is_block_device_mapping(
                bdm._bdm_obj))

        for bdm in (test_swap, test_ephemeral):
            self.assertFalse(driver_block_device.is_block_device_mapping(
                bdm._bdm_obj))

    def test_get_volume_create_az_cinder_cross_az_attach_true(self):
        # Tests  that we get None back if cinder.cross_az_attach=True even if
        # the instance has an AZ assigned. Note that since cross_az_attach
        # defaults to True we don't need to set a flag explicitly for the test.
        updates = {'availability_zone': 'test-az'}
        instance = fake_instance.fake_instance_obj(self.context, **updates)
        self.assertIsNone(
            driver_block_device._get_volume_create_az_value(instance))

    def test_refresh_conn_infos(self):
        # Only DriverVolumeBlockDevice derived devices should refresh their
        # connection_info during a refresh_conn_infos call.
        test_volume = mock.MagicMock(
            spec=driver_block_device.DriverVolumeBlockDevice)
        test_image = mock.MagicMock(
            spec=driver_block_device.DriverImageBlockDevice)
        test_snapshot = mock.MagicMock(
            spec=driver_block_device.DriverSnapshotBlockDevice)
        test_blank = mock.MagicMock(
            spec=driver_block_device.DriverBlankBlockDevice)
        test_eph = mock.MagicMock(
            spec=driver_block_device.DriverEphemeralBlockDevice)
        test_swap = mock.MagicMock(
            spec=driver_block_device.DriverSwapBlockDevice)
        block_device_mapping = [test_volume, test_image, test_eph,
                                test_snapshot, test_swap, test_blank]
        driver_block_device.refresh_conn_infos(block_device_mapping,
                                               mock.sentinel.refresh_context,
                                               mock.sentinel.refresh_instance,
                                               mock.sentinel.refresh_vol_api,
                                               mock.sentinel.refresh_virt_drv)
        for test_mock in [test_volume, test_image, test_snapshot, test_blank]:
            test_mock.refresh_connection_info.assert_called_once_with(
                mock.sentinel.refresh_context,
                mock.sentinel.refresh_instance,
                mock.sentinel.refresh_vol_api,
                mock.sentinel.refresh_virt_drv)
        # NOTE(lyarwood): Can't think of a better way of testing this as we
        # can't assert_not_called if the method isn't in the spec.
        self.assertFalse(hasattr(test_eph, 'refresh_connection_info'))
        self.assertFalse(hasattr(test_swap, 'refresh_connection_info'))

    def test_proxy_as_attr(self):
        class A(driver_block_device.DriverBlockDevice):
            pass

            def _transform(self):
                pass

        class B(A):
            _proxy_as_attr_inherited = set('B')

        class C(A):
            _proxy_as_attr_inherited = set('C')

        class D(B):
            _proxy_as_attr_inherited = set('D')

        class E(B, C):
            _proxy_as_attr_inherited = set('E')

        bdm = objects.BlockDeviceMapping(self.context, no_device=False)
        self.assertEqual(set(['uuid']), A(bdm)._proxy_as_attr)
        self.assertEqual(set(['uuid', 'B']), B(bdm)._proxy_as_attr)
        self.assertEqual(set(['uuid', 'C']), C(bdm)._proxy_as_attr)
        self.assertEqual(set(['uuid', 'B', 'D']), D(bdm)._proxy_as_attr)
        self.assertEqual(set(['uuid', 'B', 'C', 'E']), E(bdm)._proxy_as_attr)


class TestDriverBlockDeviceNewFlow(TestDriverBlockDevice):
    """Virt block_device tests for the Cinder 3.44 volume attach flow
    where a volume BDM has an attachment_id.
    """
    attachment_id = uuids.attachment_id

    def test_volume_attach_multiattach(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'multiattach': True,
                  'attach_status': 'attached',
                  'status': 'in-use',
                  'attachments': {'fake_instance_2':
                                  {'mountpoint': '/dev/vdc'}}}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, multiattach=True,
                driver_multi_attach=True)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_volume_attach_multiattach_no_virt_driver_support(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'multiattach': True,
                  'attach_status': 'attached',
                  'status': 'in-use',
                  'attachments': {'fake_instance_2':
                                  {'mountpoint': '/dev/vdc'}}}

        instance, _ = self._test_volume_attach(test_bdm, self.volume_bdm,
                                               volume, multiattach=True,
                                               fail_with_virt_driver=True)

        self.mox.ReplayAll()

        self.assertRaises(exception.MultiattachNotSupportedByVirtDriver,
                          test_bdm.attach, self.context, instance,
                          self.volume_api, self.virt_driver)

    @mock.patch('nova.objects.BlockDeviceMapping.save')
    def test_refresh_connection_preserve_multiattach(self, mock_bdm_save):
        """Tests that we've already attached a multiattach-capable volume
        and when refreshing the connection_info from the attachment record,
        the multiattach flag in the bdm.connection_info is preserved.
        """
        test_bdm = self.driver_classes['volume'](self.volume_bdm)
        test_bdm['connection_info']['multiattach'] = True
        volume_api = mock.Mock()
        volume_api.attachment_get.return_value = {
            'connection_info': {
                'data': {
                    'some': 'goodies'
                }
            }
        }

        test_bdm.refresh_connection_info(
            self.context, mock.sentinel.instance,
            volume_api, mock.sentinel.virt_driver)
        volume_api.attachment_get.assert_called_once_with(
            self.context, self.attachment_id)
        mock_bdm_save.assert_called_once_with()
        expected_connection_info = {
            'data': {
                'some': 'goodies'
            },
            'serial': self.volume_bdm.volume_id,
            'multiattach': True
        }
        self.assertDictEqual(expected_connection_info,
                             test_bdm['connection_info'])


class TestGetVolumeId(test.NoDBTestCase):

    def test_get_volume_id_none_found(self):
        self.assertIsNone(driver_block_device.get_volume_id(None))
        self.assertIsNone(driver_block_device.get_volume_id({}))
        self.assertIsNone(driver_block_device.get_volume_id({'data': {}}))

    def test_get_volume_id_found_volume_id_no_serial(self):
        self.assertEqual(uuids.volume_id,
                         driver_block_device.get_volume_id(
                             {'data': {'volume_id': uuids.volume_id}}))

    def test_get_volume_id_found_no_volume_id_serial(self):
        self.assertEqual(uuids.serial,
                         driver_block_device.get_volume_id(
                             {'serial': uuids.serial}))

    def test_get_volume_id_found_both(self):
        # volume_id is taken over serial
        self.assertEqual(uuids.volume_id,
                         driver_block_device.get_volume_id(
                             {'serial': uuids.serial,
                              'data': {'volume_id': uuids.volume_id}}))
