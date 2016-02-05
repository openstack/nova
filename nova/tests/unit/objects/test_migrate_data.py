#    Copyright 2015 Red Hat, Inc.
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

from nova import objects
from nova.objects import migrate_data
from nova.tests.unit.objects import test_objects


class _TestLiveMigrateData(object):
    def test_to_legacy_dict(self):
        obj = migrate_data.LiveMigrateData(is_volume_backed=False)
        self.assertEqual({'is_volume_backed': False},
                         obj.to_legacy_dict())

    def test_from_legacy_dict(self):
        obj = migrate_data.LiveMigrateData()
        obj.from_legacy_dict({'is_volume_backed': False, 'ignore': 'foo'})
        self.assertFalse(obj.is_volume_backed)

    def test_from_legacy_dict_migration(self):
        migration = objects.Migration()
        obj = migrate_data.LiveMigrateData()
        obj.from_legacy_dict({'is_volume_backed': False, 'ignore': 'foo',
                              'migration': migration})
        self.assertFalse(obj.is_volume_backed)
        self.assertIsInstance(obj.migration, objects.Migration)

    def test_legacy_with_pre_live_migration_result(self):
        obj = migrate_data.LiveMigrateData(is_volume_backed=False)
        self.assertEqual({'pre_live_migration_result': {},
                          'is_volume_backed': False},
                         obj.to_legacy_dict(pre_migration_result=True))

    def test_detect_implementation_none(self):
        legacy = migrate_data.LiveMigrateData().to_legacy_dict()
        self.assertIsInstance(
            migrate_data.LiveMigrateData.detect_implementation(legacy),
            migrate_data.LiveMigrateData)

    def test_detect_implementation_libvirt(self):
        legacy = migrate_data.LibvirtLiveMigrateData(
            instance_relative_path='foo').to_legacy_dict()
        self.assertIsInstance(
            migrate_data.LiveMigrateData.detect_implementation(legacy),
            migrate_data.LibvirtLiveMigrateData)

    def test_detect_implementation_libvirt_early(self):
        legacy = migrate_data.LibvirtLiveMigrateData(
            image_type='foo').to_legacy_dict()
        self.assertIsInstance(
            migrate_data.LiveMigrateData.detect_implementation(legacy),
            migrate_data.LibvirtLiveMigrateData)

    def test_detect_implementation_xenapi(self):
        legacy = migrate_data.XenapiLiveMigrateData(
            migrate_send_data={},
            destination_sr_ref='foo').to_legacy_dict()
        self.assertIsInstance(
            migrate_data.LiveMigrateData.detect_implementation(legacy),
            migrate_data.XenapiLiveMigrateData)


class TestLiveMigrateData(test_objects._LocalTest,
                          _TestLiveMigrateData):
    pass


class TestRemoteLiveMigrateData(test_objects._RemoteTest,
                                _TestLiveMigrateData):
    pass


class _TestLibvirtLiveMigrateData(object):
    def test_bdm_to_disk_info(self):
        obj = migrate_data.LibvirtLiveMigrateBDMInfo(
            serial='foo', bus='scsi', dev='sda', type='disk')
        expected_info = {
            'dev': 'sda',
            'bus': 'scsi',
            'type': 'disk',
        }
        self.assertEqual(expected_info, obj.as_disk_info())
        obj.format = 'raw'
        obj.boot_index = 1
        expected_info['format'] = 'raw'
        expected_info['boot_index'] = '1'
        self.assertEqual(expected_info, obj.as_disk_info())

    def test_to_legacy_dict(self):
        obj = migrate_data.LibvirtLiveMigrateData(
            is_volume_backed=False,
            filename='foo',
            image_type='rbd',
            block_migration=False,
            disk_over_commit=False,
            disk_available_mb=123,
            is_shared_instance_path=False,
            is_shared_block_storage=False,
            instance_relative_path='foo/bar')
        expected = {
            'is_volume_backed': False,
            'filename': 'foo',
            'image_type': 'rbd',
            'block_migration': False,
            'disk_over_commit': False,
            'disk_available_mb': 123,
            'is_shared_instance_path': False,
            'is_shared_block_storage': False,
            'instance_relative_path': 'foo/bar',
        }
        self.assertEqual(expected, obj.to_legacy_dict())

    def test_from_legacy_dict(self):
        obj = migrate_data.LibvirtLiveMigrateData(
            is_volume_backed=False,
            filename='foo',
            image_type='rbd',
            block_migration=False,
            disk_over_commit=False,
            disk_available_mb=123,
            is_shared_instance_path=False,
            is_shared_block_storage=False,
            instance_relative_path='foo/bar')
        legacy = obj.to_legacy_dict()
        legacy['ignore_this_thing'] = True
        obj2 = migrate_data.LibvirtLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertEqual(obj.filename, obj2.filename)

    def test_to_legacy_dict_with_pre_result(self):
        test_bdmi = migrate_data.LibvirtLiveMigrateBDMInfo(
            serial='123',
            bus='scsi',
            dev='/dev/sda',
            type='disk',
            format='qcow2',
            boot_index=1,
            connection_info='myinfo')
        obj = migrate_data.LibvirtLiveMigrateData(
            is_volume_backed=False,
            filename='foo',
            image_type='rbd',
            block_migration=False,
            disk_over_commit=False,
            disk_available_mb=123,
            is_shared_instance_path=False,
            is_shared_block_storage=False,
            instance_relative_path='foo/bar',
            graphics_listen_addr_vnc='127.0.0.1',
            serial_listen_addr='127.0.0.1',
            bdms=[test_bdmi])
        legacy = obj.to_legacy_dict(pre_migration_result=True)
        self.assertIn('pre_live_migration_result', legacy)
        expected = {
            'graphics_listen_addrs': {'vnc': '127.0.0.1',
                                      'spice': None},
            'target_connect_addr': None,
            'serial_listen_addr': '127.0.0.1',
            'volume': {
                '123': {
                    'connection_info': 'myinfo',
                    'disk_info': {
                        'bus': 'scsi',
                        'dev': '/dev/sda',
                        'type': 'disk',
                        'format': 'qcow2',
                        'boot_index': '1',
                    }
                }
            }
        }
        self.assertEqual(expected, legacy['pre_live_migration_result'])

    def test_from_legacy_with_pre_result(self):
        test_bdmi = migrate_data.LibvirtLiveMigrateBDMInfo(
            serial='123',
            bus='scsi',
            dev='/dev/sda',
            type='disk',
            format='qcow2',
            boot_index=1,
            connection_info='myinfo')
        obj = migrate_data.LibvirtLiveMigrateData(
            is_volume_backed=False,
            filename='foo',
            image_type='rbd',
            block_migration=False,
            disk_over_commit=False,
            disk_available_mb=123,
            is_shared_instance_path=False,
            is_shared_block_storage=False,
            instance_relative_path='foo/bar',
            graphics_listen_addrs={'vnc': '127.0.0.1'},
            serial_listen_addr='127.0.0.1',
            bdms=[test_bdmi])
        obj2 = migrate_data.LibvirtLiveMigrateData()
        obj2.from_legacy_dict(obj.to_legacy_dict(pre_migration_result=True))
        self.assertEqual(obj.to_legacy_dict(),
                         obj2.to_legacy_dict())
        self.assertEqual(obj.bdms[0].serial, obj2.bdms[0].serial)


class TestLibvirtLiveMigrateData(test_objects._LocalTest,
                                 _TestLibvirtLiveMigrateData):
    pass


class TestRemoteLibvirtLiveMigrateData(test_objects._RemoteTest,
                                       _TestLibvirtLiveMigrateData):
    pass


class _TestXenapiLiveMigrateData(object):
    def test_to_legacy_dict(self):
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            block_migration=False,
            destination_sr_ref='foo',
            migrate_send_data={'key': 'val'},
            sr_uuid_map={'apple': 'banana'})
        expected = {
            'is_volume_backed': False,
            'block_migration': False,
            'migrate_data': {
                'destination_sr_ref': 'foo',
                'migrate_send_data': {'key': 'val'},
            }
        }
        self.assertEqual(expected, obj.to_legacy_dict())

    def test_from_legacy_dict(self):
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            block_migration=False,
            destination_sr_ref='foo',
            migrate_send_data={'key': 'val'},
            sr_uuid_map={'apple': 'banana'})
        legacy = obj.to_legacy_dict()
        legacy['ignore_this_thing'] = True
        obj2 = migrate_data.XenapiLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertEqual(obj.destination_sr_ref, obj2.destination_sr_ref)

    def test_to_legacy_dict_missing_attrs(self):
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            destination_sr_ref='foo',
            sr_uuid_map={'apple': 'banana'})
        expected = {
            'is_volume_backed': False,
        }
        self.assertEqual(expected, obj.to_legacy_dict())
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            destination_sr_ref='foo')
        expected = {
            'is_volume_backed': False,
            'pre_live_migration_result': {
                'sr_uuid_map': {},
            },
        }
        self.assertEqual(expected, obj.to_legacy_dict(True))

    def test_from_legacy_dict_missing_attrs(self):
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            destination_sr_ref='foo',
            sr_uuid_map={'apple': 'banana'})
        legacy = obj.to_legacy_dict()
        obj2 = migrate_data.XenapiLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertFalse(obj2.block_migration)
        self.assertNotIn('migrate_send_data', obj2)
        self.assertNotIn('sr_uuid_map', obj2)

    def test_to_legacy_with_pre_result(self):
        obj = migrate_data.XenapiLiveMigrateData(
            sr_uuid_map={'a': 'b'})
        self.assertNotIn('sr_uuid_map', obj.to_legacy_dict())
        legacy = obj.to_legacy_dict(True)
        self.assertEqual(
            {'a': 'b'},
            legacy['pre_live_migration_result']['sr_uuid_map'])
        obj2 = migrate_data.XenapiLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertEqual({'a': 'b'}, obj2.sr_uuid_map)


class TestXenapiLiveMigrateData(test_objects._LocalTest,
                                _TestXenapiLiveMigrateData):
    pass


class TestRemoteXenapiLiveMigrateData(test_objects._RemoteTest,
                                      _TestXenapiLiveMigrateData):
    pass
