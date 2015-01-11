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

import contextlib

import mock
from oslo_serialization import jsonutils

from nova import block_device
from nova import context
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import matchers
from nova.virt import block_device as driver_block_device
from nova.virt import driver
from nova.volume import cinder
from nova.volume import encryptors


class TestDriverBlockDevice(test.NoDBTestCase):
    driver_classes = {
        'swap': driver_block_device.DriverSwapBlockDevice,
        'ephemeral': driver_block_device.DriverEphemeralBlockDevice,
        'volume': driver_block_device.DriverVolumeBlockDevice,
        'snapshot': driver_block_device.DriverSnapshotBlockDevice,
        'image': driver_block_device.DriverImageBlockDevice,
        'blank': driver_block_device.DriverBlankBlockDevice
    }

    swap_bdm = block_device.BlockDeviceDict(
        {'id': 1, 'instance_uuid': 'fake-instance',
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

    ephemeral_bdm = block_device.BlockDeviceDict(
        {'id': 2, 'instance_uuid': 'fake-instance',
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

    volume_bdm = block_device.BlockDeviceDict(
        {'id': 3, 'instance_uuid': 'fake-instance',
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

    snapshot_bdm = block_device.BlockDeviceDict(
        {'id': 4, 'instance_uuid': 'fake-instance',
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

    image_bdm = block_device.BlockDeviceDict(
        {'id': 5, 'instance_uuid': 'fake-instance',
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

    blank_bdm = block_device.BlockDeviceDict(
        {'id': 6, 'instance_uuid': 'fake-instance',
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

    def test_no_device_raises(self):
        for name, cls in self.driver_classes.items():
            self.assertRaises(driver_block_device._NotTransformable,
                              cls, {'no_device': True})

    def _test_driver_device(self, name):
        db_bdm = getattr(self, "%s_bdm" % name)
        test_bdm = self.driver_classes[name](db_bdm)
        self.assertThat(test_bdm, matchers.DictMatches(
            getattr(self, "%s_driver_bdm" % name)))

        for k, v in db_bdm.iteritems():
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
        for other_name, cls in self.driver_classes.iteritems():
            if other_name == name:
                continue
            self.assertRaises(driver_block_device._InvalidType,
                              cls,
                              getattr(self, '%s_bdm' % name))

        # Test the save method
        with mock.patch.object(test_bdm._bdm_obj, 'save') as save_mock:
            test_bdm.save()
            for fld, alias in test_bdm._update_on_save.iteritems():
                self.assertEqual(test_bdm[alias or fld],
                                 getattr(test_bdm._bdm_obj, fld))

            save_mock.assert_called_once_with()

    def _test_driver_default_size(self, name):
        size = 'swap_size' if name == 'swap' else 'size'
        no_size_bdm = getattr(self, "%s_bdm" % name).copy()
        no_size_bdm['volume_size'] = None

        driver_bdm = self.driver_classes[name](no_size_bdm)
        self.assertEqual(driver_bdm[size], 0)

        del no_size_bdm['volume_size']

        driver_bdm = self.driver_classes[name](no_size_bdm)
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
        bdm = self.image_bdm.copy()
        bdm['destination_type'] = 'local'
        self.assertRaises(driver_block_device._InvalidType,
                          self.driver_classes['image'], bdm)

    def test_driver_blank_block_device(self):
        self._test_driver_device('blank')

        test_bdm = self.driver_classes['blank'](
            self.blank_bdm)
        self.assertEqual(6, test_bdm._bdm_obj.id)
        self.assertEqual('fake-volume-id-2', test_bdm.volume_id)
        self.assertEqual(3, test_bdm.volume_size)

    def _test_volume_attach(self, driver_bdm, bdm_dict,
                            fake_volume, check_attach=True,
                            fail_check_attach=False, driver_attach=False,
                            fail_driver_attach=False, volume_attach=True,
                            access_mode='rw'):
        elevated_context = self.context.elevated()
        self.stubs.Set(self.context, 'elevated',
                       lambda: elevated_context)
        self.mox.StubOutWithMock(driver_bdm._bdm_obj, 'save')
        self.mox.StubOutWithMock(encryptors, 'get_encryption_metadata')
        instance_detail = {'id': '123', 'uuid': 'fake_uuid'}
        instance = fake_instance.fake_instance_obj(self.context,
                                                   **instance_detail)
        connector = {'ip': 'fake_ip', 'host': 'fake_host'}
        connection_info = {'data': {'access_mode': access_mode}}
        expected_conn_info = {'data': {'access_mode': access_mode},
                              'serial': fake_volume['id']}
        enc_data = {'fake': 'enc_data'}

        self.volume_api.get(self.context,
                            fake_volume['id']).AndReturn(fake_volume)
        if check_attach:
            if not fail_check_attach:
                self.volume_api.check_attach(self.context, fake_volume,
                                    instance=instance).AndReturn(None)
            else:
                self.volume_api.check_attach(self.context, fake_volume,
                                    instance=instance).AndRaise(
                                            test.TestingException)
                return instance, expected_conn_info

        self.virt_driver.get_volume_connector(instance).AndReturn(connector)
        self.volume_api.initialize_connection(
            elevated_context, fake_volume['id'],
            connector).AndReturn(connection_info)
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
                self.volume_api.terminate_connection(
                        elevated_context, fake_volume['id'],
                        expected_conn_info).AndReturn(None)
                return instance, expected_conn_info

        if volume_attach:
            self.volume_api.attach(elevated_context, fake_volume['id'],
                                   'fake_uuid', bdm_dict['device_name'],
                                   mode=access_mode).AndReturn(None)
        driver_bdm._bdm_obj.save().AndReturn(None)
        return instance, expected_conn_info

    def test_volume_attach(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

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

    def check_volume_attach_check_attach_fails(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1'}

        instance, _ = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, fail_check_attach=True)
        self.mox.ReplayAll()

        self.asserRaises(test.TestingException, test_bdm.attach, self.context,
                         instance, self.volume_api, self.virt_driver)

    def test_volume_no_volume_attach(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, check_attach=False,
                driver_attach=False)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver,
                        do_check_attach=False, do_driver_attach=False)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_volume_attach_no_check_driver_attach(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1',
                  'attach_status': 'detached'}

        instance, expected_conn_info = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, check_attach=False,
                driver_attach=True)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver,
                        do_check_attach=False, do_driver_attach=True)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def check_volume_attach_driver_attach_fails(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        volume = {'id': 'fake-volume-id-1'}

        instance, _ = self._test_volume_attach(
                test_bdm, self.volume_bdm, volume, fail_check_attach=True)
        self.mox.ReplayAll()

        self.asserRaises(test.TestingException, test_bdm.attach, self.context,
                         instance, self.volume_api, self.virt_driver,
                         do_driver_attach=True)

    def test_refresh_connection(self):
        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        instance = {'id': 'fake_id', 'uuid': 'fake_uuid'}
        connector = {'ip': 'fake_ip', 'host': 'fake_host'}
        connection_info = {'data': {'multipath_id': 'fake_multipath_id'}}
        expected_conn_info = {'data': {'multipath_id': 'fake_multipath_id'},
                              'serial': 'fake-volume-id-2'}

        self.mox.StubOutWithMock(test_bdm._bdm_obj, 'save')

        self.virt_driver.get_volume_connector(instance).AndReturn(connector)
        self.volume_api.initialize_connection(
            self.context, test_bdm.volume_id,
            connector).AndReturn(connection_info)
        test_bdm._bdm_obj.save().AndReturn(None)

        self.mox.ReplayAll()

        test_bdm.refresh_connection_info(self.context, instance,
                                         self.volume_api, self.virt_driver)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_snapshot_attach_no_volume(self):
        no_volume_snapshot = self.snapshot_bdm.copy()
        no_volume_snapshot['volume_id'] = None
        test_bdm = self.driver_classes['snapshot'](no_volume_snapshot)

        snapshot = {'id': 'fake-volume-id-1',
                    'attach_status': 'detached'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        wait_func = self.mox.CreateMockAnything()

        self.volume_api.get_snapshot(self.context,
                                     'fake-snapshot-id-1').AndReturn(snapshot)
        self.volume_api.create(self.context, 3,
                               '', '', snapshot).AndReturn(volume)
        wait_func(self.context, 'fake-volume-id-2').AndReturn(None)
        instance, expected_conn_info = self._test_volume_attach(
               test_bdm, no_volume_snapshot, volume)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, wait_func)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_snapshot_attach_volume(self):
        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        instance = {'id': 'fake_id', 'uuid': 'fake_uuid'}

        volume_class = self.driver_classes['volume']
        self.mox.StubOutWithMock(volume_class, 'attach')

        # Make sure theses are not called
        self.mox.StubOutWithMock(self.volume_api, 'get_snapshot')
        self.mox.StubOutWithMock(self.volume_api, 'create')

        volume_class.attach(self.context, instance, self.volume_api,
                            self.virt_driver, do_check_attach=True
                            ).AndReturn(None)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_image_attach_no_volume(self):
        no_volume_image = self.image_bdm.copy()
        no_volume_image['volume_id'] = None
        test_bdm = self.driver_classes['image'](no_volume_image)

        image = {'id': 'fake-image-id-1'}
        volume = {'id': 'fake-volume-id-2',
                  'attach_status': 'detached'}

        wait_func = self.mox.CreateMockAnything()

        self.volume_api.create(self.context, 1,
                               '', '', image_id=image['id']).AndReturn(volume)
        wait_func(self.context, 'fake-volume-id-2').AndReturn(None)
        instance, expected_conn_info = self._test_volume_attach(
               test_bdm, no_volume_image, volume)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, wait_func)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_image_attach_volume(self):
        test_bdm = self.driver_classes['image'](
            self.image_bdm)

        instance = {'id': 'fake_id', 'uuid': 'fake_uuid'}

        volume_class = self.driver_classes['volume']
        self.mox.StubOutWithMock(volume_class, 'attach')

        # Make sure theses are not called
        self.mox.StubOutWithMock(self.volume_api, 'get_snapshot')
        self.mox.StubOutWithMock(self.volume_api, 'create')

        volume_class.attach(self.context, instance, self.volume_api,
                            self.virt_driver, do_check_attach=True
                            ).AndReturn(None)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver)
        self.assertEqual(test_bdm.volume_id, 'fake-volume-id-2')

    def test_blank_attach_volume(self):
        no_blank_volume = self.blank_bdm.copy()
        no_blank_volume['volume_id'] = None
        test_bdm = self.driver_classes['blank'](no_blank_volume)
        instance = fake_instance.fake_instance_obj(mock.sentinel.ctx,
                                                   **{'uuid': 'fake-uuid'})
        volume_class = self.driver_classes['volume']
        volume = {'id': 'fake-volume-id-2',
                  'display_name': 'fake-uuid-blank-vol'}

        with contextlib.nested(
            mock.patch.object(self.volume_api, 'create', return_value=volume),
            mock.patch.object(volume_class, 'attach')
        ) as (vol_create, vol_attach):
            test_bdm.attach(self.context, instance, self.volume_api,
                            self.virt_driver)

            vol_create.assert_called_once_with(self.context,
                                               test_bdm.volume_size,
                                               'fake-uuid-blank-vol',
                                               '')
            vol_attach.assert_called_once_with(self.context, instance,
                                               self.volume_api,
                                               self.virt_driver,
                                               do_check_attach=True)
            self.assertEqual('fake-volume-id-2', test_bdm.volume_id)

    def test_convert_block_devices(self):
        converted = driver_block_device._convert_block_devices(
            self.driver_classes['volume'],
            [self.volume_bdm, self.ephemeral_bdm])
        self.assertEqual(converted, [self.volume_driver_bdm])

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
            self.ephemeral_bdm) for _ in xrange(2)]
        expected = [self.ephemeral_legacy_driver_bdm.copy()
                             for _ in xrange(2)]
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
        local_image = self.image_bdm.copy()
        local_image['destination_type'] = 'local'
        self.assertFalse(driver_block_device.is_implemented(local_image))

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
