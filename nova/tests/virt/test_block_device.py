# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import block_device
from nova.conductor import api as conductor_api
from nova import context
from nova.openstack.common import jsonutils
from nova import test
from nova.tests import matchers
from nova.virt import block_device as driver_block_device
from nova.virt import driver
from nova.volume import cinder


class TestDriverBlockDevice(test.TestCase):
    driver_classes = {
        'swap': driver_block_device.DriverSwapBlockDevice,
        'ephemeral': driver_block_device.DriverEphemeralBlockDevice,
        'volume': driver_block_device.DriverVolumeBlockDevice,
        'snapshot': driver_block_device.DriverSnapshotBlockDevice
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

    def setUp(self):
        super(TestDriverBlockDevice, self).setUp()
        self.volume_api = self.mox.CreateMock(cinder.API)
        self.virt_driver = self.mox.CreateMock(driver.ComputeDriver)
        self.db_api = self.mox.CreateMock(conductor_api.API)
        self.context = context.RequestContext('fake_user',
                                              'fake_project')

    def test_driver_block_device_base_class(self):
        self.base_class_transform_called = False

        class DummyBlockDevice(driver_block_device.DriverBlockDevice):
            _fields = set(['foo', 'bar'])
            _legacy_fields = set(['foo', 'baz'])

            def _transform(inst, bdm):
                self.base_class_transform_called = True

        dummy_device = DummyBlockDevice({'foo': 'foo_val', 'id': 42})
        self.assertTrue(self.base_class_transform_called)
        self.assertThat(dummy_device, matchers.DictMatches(
            {'foo': None, 'bar': None}))
        self.assertEquals(dummy_device.id, 42)
        self.assertThat(dummy_device.legacy(), matchers.DictMatches(
            {'foo': None, 'baz': None}))

        self.assertRaises(driver_block_device._NotTransformable,
                          DummyBlockDevice, {'no_device': True})

    def _test_driver_device(self, name):
        test_bdm = self.driver_classes[name](
            getattr(self, "%s_bdm" % name))
        self.assertThat(test_bdm, matchers.DictMatches(
            getattr(self, "%s_driver_bdm" % name)))
        self.assertThat(test_bdm.legacy(),
                        matchers.DictMatches(
                            getattr(self, "%s_legacy_driver_bdm" % name)))
        # Make sure that all others raise _invalidType
        for other_name, cls in self.driver_classes.iteritems():
            if other_name == name:
                continue
            self.assertRaises(driver_block_device._InvalidType,
                              cls,
                              getattr(self, '%s_bdm' % name))

    def test_driver_swap_block_device(self):
        self._test_driver_device("swap")

    def test_driver_ephemeral_block_device(self):
        self._test_driver_device("ephemeral")

    def test_driver_volume_block_device(self):
        self._test_driver_device("volume")

        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        self.assertEquals(test_bdm.id, 3)
        self.assertEquals(test_bdm.volume_id, 'fake-volume-id-1')
        self.assertEquals(test_bdm.volume_size, 8)

    def test_driver_snapshot_block_device(self):
        self._test_driver_device("snapshot")

        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)
        self.assertEquals(test_bdm.id, 4)
        self.assertEquals(test_bdm.snapshot_id, 'fake-snapshot-id-1')
        self.assertEquals(test_bdm.volume_id, 'fake-volume-id-2')
        self.assertEquals(test_bdm.volume_size, 3)

    def test_volume_attach(self):
        test_bdm = self.driver_classes['volume'](
            self.volume_bdm)
        elevated_context = self.context.elevated()
        self.stubs.Set(self.context, 'elevated',
                       lambda: elevated_context)

        instance = {'id': 'fake_id', 'uuid': 'fake_uuid'}
        volume = {'id': 'fake-volume-id-1'}
        connector = {'ip': 'fake_ip', 'host': 'fake_host'}
        connection_info = {'data': 'fake_data'}
        expected_conn_info = {'data': 'fake_data',
                              'serial': 'fake-volume-id-1'}

        self.volume_api.get(self.context,
                            'fake-volume-id-1').AndReturn(volume)
        self.volume_api.check_attach(self.context, volume,
                                instance=instance).AndReturn(None)
        self.virt_driver.get_volume_connector(instance).AndReturn(connector)
        self.volume_api.initialize_connection(
            elevated_context, volume['id'],
            connector).AndReturn(connection_info)
        self.volume_api.attach(elevated_context, 'fake-volume-id-1',
                          'fake_uuid', '/dev/sda1').AndReturn(None)
        self.db_api.block_device_mapping_update(elevated_context, 3,
                {'connection_info': jsonutils.dumps(expected_conn_info)})

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance,
                        self.volume_api, self.virt_driver, self.db_api)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_refresh_connection(self):
        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        instance = {'id': 'fake_id', 'uuid': 'fake_uuid'}
        connector = {'ip': 'fake_ip', 'host': 'fake_host'}
        connection_info = {'data': 'fake_data'}
        expected_conn_info = {'data': 'fake_data',
                              'serial': 'fake-volume-id-2'}

        self.virt_driver.get_volume_connector(instance).AndReturn(connector)
        self.volume_api.initialize_connection(
            self.context, test_bdm.volume_id,
            connector).AndReturn(connection_info)
        self.db_api.block_device_mapping_update(self.context, 4,
                {'connection_info': jsonutils.dumps(expected_conn_info)})

        self.mox.ReplayAll()

        test_bdm.refresh_connection_info(self.context, instance,
                                         self.volume_api, self.virt_driver,
                                         self.db_api)
        self.assertThat(test_bdm['connection_info'],
                        matchers.DictMatches(expected_conn_info))

    def test_snapshot_attach_no_volume(self):
        no_volume_snapshot = self.snapshot_bdm.copy()
        no_volume_snapshot['volume_id'] = None
        test_bdm = self.driver_classes['snapshot'](no_volume_snapshot)

        instance = {'id': 'fake_id', 'uuid': 'fake_uuid'}
        snapshot = {'id': 'fake-snapshot-id-1'}
        volume = {'id': 'fake-volume-id-2'}

        wait_func = self.mox.CreateMockAnything()
        volume_class = self.driver_classes['volume']
        self.mox.StubOutWithMock(volume_class, 'attach')

        self.volume_api.get_snapshot(self.context,
                                     'fake-snapshot-id-1').AndReturn(snapshot)
        self.volume_api.create(self.context, 3,
                               '', '', snapshot).AndReturn(volume)
        wait_func(self.context, 'fake-volume-id-2').AndReturn(None)
        self.db_api.block_device_mapping_update(
            self.context, 4, {'volume_id': 'fake-volume-id-2'}).AndReturn(None)
        volume_class.attach(self.context, instance, self.volume_api,
                            self.virt_driver, self.db_api).AndReturn(None)

        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, self.db_api, wait_func)
        self.assertEquals(test_bdm.volume_id, 'fake-volume-id-2')

    def test_snapshot_attach_volume(self):
        test_bdm = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        instance = {'id': 'fake_id', 'uuid': 'fake_uuid'}

        volume_class = self.driver_classes['volume']
        self.mox.StubOutWithMock(volume_class, 'attach')

        # Make sure theses are not called
        self.mox.StubOutWithMock(self.volume_api, 'get_snapshot')
        self.mox.StubOutWithMock(self.volume_api, 'create')
        self.mox.StubOutWithMock(self.db_api,
                                 'block_device_mapping_update')

        volume_class.attach(self.context, instance, self.volume_api,
                            self.virt_driver, self.db_api).AndReturn(None)
        self.mox.ReplayAll()

        test_bdm.attach(self.context, instance, self.volume_api,
                        self.virt_driver, self.db_api)
        self.assertEquals(test_bdm.volume_id, 'fake-volume-id-2')

    def test_convert_block_devices(self):
        converted = driver_block_device._convert_block_devices(
            self.driver_classes['volume'],
            [self.volume_bdm, self.ephemeral_bdm])
        self.assertEquals(converted, [self.volume_driver_bdm])

    def test_legacy_block_devices(self):
        test_snapshot = self.driver_classes['snapshot'](
            self.snapshot_bdm)

        block_device_mapping = [test_snapshot, test_snapshot]
        legacy_bdm = driver_block_device.legacy_block_devices(
            block_device_mapping)
        self.assertEquals(legacy_bdm, [self.snapshot_legacy_driver_bdm,
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
        self.assertEquals(expected, legacy_ephemerals)

    def test_get_swap(self):
        swap = [self.swap_driver_bdm]
        legacy_swap = [self.swap_legacy_driver_bdm]
        no_swap = [self.volume_driver_bdm]

        self.assertEquals(swap[0], driver_block_device.get_swap(swap))
        self.assertEquals(legacy_swap[0],
                          driver_block_device.get_swap(legacy_swap))
        self.assertEquals(no_swap, driver_block_device.get_swap(no_swap))
        self.assertEquals(None, driver_block_device.get_swap([]))
