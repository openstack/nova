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

from oslo_serialization import jsonutils
from oslo_versionedobjects import base as ovo_base

from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.objects import migrate_data
from nova import test
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


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

    def test_obj_make_compatible(self):
        props = {
            'serial_listen_addr': '127.0.0.1',
            'serial_listen_ports': [1000, 10001, 10002, 10003],
            'wait_for_vif_plugged': True
        }

        obj = migrate_data.LibvirtLiveMigrateData(**props)
        primitive = obj.obj_to_primitive()
        self.assertIn('serial_listen_ports', primitive['nova_object.data'])
        self.assertIn('wait_for_vif_plugged', primitive['nova_object.data'])
        obj.obj_make_compatible(primitive['nova_object.data'], '1.5')
        self.assertNotIn('wait_for_vif_plugged', primitive['nova_object.data'])
        obj.obj_make_compatible(primitive['nova_object.data'], '1.1')
        self.assertNotIn('serial_listen_ports', primitive['nova_object.data'])


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
            bdms=[test_bdmi],
            dst_wants_file_backed_memory=True,
            file_backed_memory_discard=True)
        obj2 = migrate_data.LibvirtLiveMigrateData()
        obj2.from_legacy_dict(obj.to_legacy_dict(pre_migration_result=True))
        self.assertEqual(obj.to_legacy_dict(),
                         obj2.to_legacy_dict())
        self.assertEqual(obj.bdms[0].serial, obj2.bdms[0].serial)

    def test_obj_make_compatible(self):
        obj = migrate_data.LibvirtLiveMigrateData(
            src_supports_native_luks=True,
            old_vol_attachment_ids={uuids.volume: uuids.attachment},
            supported_perf_events=[],
            serial_listen_addr='127.0.0.1',
            target_connect_addr='127.0.0.1',
            dst_wants_file_backed_memory=False,
            file_backed_memory_discard=False)

        data = lambda x: x['nova_object.data']

        primitive = data(obj.obj_to_primitive())
        self.assertIn('file_backed_memory_discard', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.0'))
        self.assertNotIn('target_connect_addr', primitive)
        self.assertNotIn('supported_perf_events', primitive)
        self.assertNotIn('old_vol_attachment_ids', primitive)
        self.assertNotIn('src_supports_native_luks', primitive)
        self.assertNotIn('dst_wants_file_backed_memory', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.1'))
        self.assertNotIn('serial_listen_ports', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.2'))
        self.assertNotIn('supported_perf_events', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.3'))
        self.assertNotIn('old_vol_attachment_ids', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.4'))
        self.assertNotIn('src_supports_native_luks', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.6'))
        self.assertNotIn('dst_wants_file_backed_memory', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.7'))
        self.assertNotIn('file_backed_memory_discard', primitive)

    def test_bdm_obj_make_compatible(self):
        obj = migrate_data.LibvirtLiveMigrateBDMInfo(
            encryption_secret_uuid=uuids.encryption_secret_uuid)
        primitive = obj.obj_to_primitive(target_version='1.0')
        self.assertNotIn('encryption_secret_uuid', primitive)

    def test_vif_migrate_data(self):
        source_vif = network_model.VIF(
            id=uuids.port_id,
            network=network_model.Network(id=uuids.network_id),
            type=network_model.VIF_TYPE_OVS,
            vnic_type=network_model.VNIC_TYPE_NORMAL,
            active=True,
            profile={'migrating_to': 'dest-host'})
        vif_details_dict = {'port_filter': True}
        profile_dict = {'trusted': False}
        vif_data = objects.VIFMigrateData(
            port_id=uuids.port_id,
            vnic_type=network_model.VNIC_TYPE_NORMAL,
            vif_type=network_model.VIF_TYPE_BRIDGE,
            vif_details=vif_details_dict, profile=profile_dict,
            host='dest-host', source_vif=source_vif)
        # Make sure the vif_details and profile fields are converted and
        # stored properly.
        self.assertEqual(
            jsonutils.dumps(vif_details_dict), vif_data.vif_details_json)
        self.assertEqual(
            jsonutils.dumps(profile_dict), vif_data.profile_json)
        self.assertDictEqual(vif_details_dict, vif_data.vif_details)
        self.assertDictEqual(profile_dict, vif_data.profile)
        obj = migrate_data.LibvirtLiveMigrateData(
            file_backed_memory_discard=False)
        obj.vifs = [vif_data]
        manifest = ovo_base.obj_tree_get_versions(obj.obj_name())
        primitive = obj.obj_to_primitive(target_version='1.8',
                                         version_manifest=manifest)
        self.assertIn(
            'file_backed_memory_discard', primitive['nova_object.data'])
        self.assertNotIn('vifs', primitive['nova_object.data'])


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
            sr_uuid_map={'apple': 'banana'},
            vif_uuid_map={'orange': 'lemon'})
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
            sr_uuid_map={'apple': 'banana'},
            vif_uuid_map={'orange': 'lemon'})
        legacy = obj.to_legacy_dict()
        legacy['ignore_this_thing'] = True
        obj2 = migrate_data.XenapiLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertEqual(obj.destination_sr_ref, obj2.destination_sr_ref)

    def test_to_legacy_dict_missing_attrs(self):
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            destination_sr_ref='foo',
            sr_uuid_map={'apple': 'banana'},
            vif_uuid_map={'orange': 'lemon'})
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
                'vif_uuid_map': {},
            },
        }
        self.assertEqual(expected, obj.to_legacy_dict(True))

    def test_from_legacy_dict_missing_attrs(self):
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            destination_sr_ref='foo',
            sr_uuid_map={'apple': 'banana'},
            vif_uuid_map={'orange': 'lemon'})
        legacy = obj.to_legacy_dict()
        obj2 = migrate_data.XenapiLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertFalse(obj2.block_migration)
        self.assertNotIn('migrate_send_data', obj2)
        self.assertNotIn('sr_uuid_map', obj2)
        self.assertNotIn('vif_uuid_map', obj2)

    def test_to_legacy_with_pre_result(self):
        obj = migrate_data.XenapiLiveMigrateData(
            sr_uuid_map={'a': 'b'},
            vif_uuid_map={'c': 'd'})
        self.assertNotIn('sr_uuid_map', obj.to_legacy_dict())
        self.assertNotIn('vi_uuid_map', obj.to_legacy_dict())
        legacy = obj.to_legacy_dict(True)
        self.assertEqual(
            {'a': 'b'},
            legacy['pre_live_migration_result']['sr_uuid_map'])
        self.assertEqual(
            {'c': 'd'},
            legacy['pre_live_migration_result']['vif_uuid_map']
        )
        obj2 = migrate_data.XenapiLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertEqual({'a': 'b'}, obj2.sr_uuid_map)
        self.assertEqual({'c': 'd'}, obj2.vif_uuid_map)

    def test_obj_make_compatible(self):
        obj = migrate_data.XenapiLiveMigrateData(
            is_volume_backed=False,
            block_migration=False,
            destination_sr_ref='foo',
            migrate_send_data={'key': 'val'},
            sr_uuid_map={'apple': 'banana'},
            vif_uuid_map={'orange': 'lemon'},
            old_vol_attachment_ids={uuids.volume: uuids.attachment},
            wait_for_vif_plugged=True)
        primitive = obj.obj_to_primitive('1.0')
        self.assertNotIn('vif_uuid_map', primitive['nova_object.data'])
        primitive2 = obj.obj_to_primitive('1.1')
        self.assertIn('vif_uuid_map', primitive2['nova_object.data'])
        self.assertNotIn('old_vol_attachment_ids', primitive2)
        primitive3 = obj.obj_to_primitive('1.2')['nova_object.data']
        self.assertNotIn('wait_for_vif_plugged', primitive3)


class TestXenapiLiveMigrateData(test_objects._LocalTest,
                                _TestXenapiLiveMigrateData):
    pass


class TestRemoteXenapiLiveMigrateData(test_objects._RemoteTest,
                                      _TestXenapiLiveMigrateData):
    pass


class _TestHyperVLiveMigrateData(object):
    def test_obj_make_compatible(self):
        obj = migrate_data.HyperVLiveMigrateData(
            is_shared_instance_path=True,
            old_vol_attachment_ids={'yes': 'no'},
            wait_for_vif_plugged=True)

        data = lambda x: x['nova_object.data']

        primitive = data(obj.obj_to_primitive())
        self.assertIn('is_shared_instance_path', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.0'))
        self.assertNotIn('is_shared_instance_path', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.1'))
        self.assertNotIn('old_vol_attachment_ids', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.2'))
        self.assertNotIn('wait_for_vif_plugged', primitive)

    def test_to_legacy_dict(self):
        obj = migrate_data.HyperVLiveMigrateData(
            is_shared_instance_path=False)
        expected = {
            'is_shared_instance_path': False,
        }
        self.assertEqual(expected, obj.to_legacy_dict())

    def test_from_legacy_dict(self):
        obj = migrate_data.HyperVLiveMigrateData(
            is_shared_instance_path=False)
        legacy = obj.to_legacy_dict()
        obj2 = migrate_data.HyperVLiveMigrateData()
        obj2.from_legacy_dict(legacy)
        self.assertEqual(obj.is_shared_instance_path,
                         obj2.is_shared_instance_path)


class TestHyperVLiveMigrateData(test_objects._LocalTest,
                                _TestHyperVLiveMigrateData):
    pass


class TestRemoteHyperVLiveMigrateData(test_objects._RemoteTest,
                                      _TestHyperVLiveMigrateData):
    pass


class _TestPowerVMLiveMigrateData(object):
    @staticmethod
    def _mk_obj():
        return migrate_data.PowerVMLiveMigrateData(
            host_mig_data=dict(one=2),
            dest_ip='1.2.3.4',
            dest_user_id='a_user',
            dest_sys_name='a_sys',
            public_key='a_key',
            dest_proc_compat='POWER7',
            vol_data=dict(three=4),
            vea_vlan_mappings=dict(five=6),
            old_vol_attachment_ids=dict(seven=8),
            wait_for_vif_plugged=True)

    @staticmethod
    def _mk_leg():
        return {
            'host_mig_data': {'one': '2'},
            'dest_ip': '1.2.3.4',
            'dest_user_id': 'a_user',
            'dest_sys_name': 'a_sys',
            'public_key': 'a_key',
            'dest_proc_compat': 'POWER7',
            'vol_data': {'three': '4'},
            'vea_vlan_mappings': {'five': '6'},
            'old_vol_attachment_ids': {'seven': '8'},
            'wait_for_vif_plugged': True
        }

    def test_migrate_data(self):
        obj = self._mk_obj()
        self.assertEqual('a_key', obj.public_key)
        obj.public_key = 'key2'
        self.assertEqual('key2', obj.public_key)

    def test_obj_make_compatible(self):
        obj = self._mk_obj()

        data = lambda x: x['nova_object.data']

        primitive = data(obj.obj_to_primitive())
        self.assertIn('vea_vlan_mappings', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.0'))
        self.assertNotIn('vea_vlan_mappings', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.1'))
        self.assertNotIn('old_vol_attachment_ids', primitive)
        primitive = data(obj.obj_to_primitive(target_version='1.2'))
        self.assertNotIn('wait_for_vif_plugged', primitive)

    def test_to_legacy_dict(self):
        self.assertEqual(self._mk_leg(), self._mk_obj().to_legacy_dict())

    def test_from_legacy_dict(self):
        obj = self._mk_obj()
        leg = self._mk_leg()
        obj2 = migrate_data.PowerVMLiveMigrateData()
        obj2.from_legacy_dict(leg)
        for field in leg:
            self.assertEqual(getattr(obj, field), getattr(obj2, field))


class TestPowerVMLiveMigrateData(test_objects._LocalTest,
                                 _TestPowerVMLiveMigrateData):
    pass


class TestRemotePowerVMLiveMigrateData(test_objects._RemoteTest,
                                      _TestPowerVMLiveMigrateData):
    pass


class TestVIFMigrateData(test.NoDBTestCase):

    def test_get_dest_vif_source_vif_not_set(self):
        migrate_vif = objects.VIFMigrateData(
            port_id=uuids.port_id, vnic_type=network_model.VNIC_TYPE_NORMAL,
            vif_type=network_model.VIF_TYPE_OVS, vif_details={},
            profile={}, host='fake-dest-host')
        self.assertRaises(
            exception.ObjectActionError, migrate_vif.get_dest_vif)

    def test_get_dest_vif(self):
        source_vif = network_model.VIF(
            id=uuids.port_id, type=network_model.VIF_TYPE_OVS, details={},
            vnic_type=network_model.VNIC_TYPE_DIRECT, profile={'foo': 'bar'},
            ovs_interfaceid=uuids.ovs_interfaceid)
        migrate_vif = objects.VIFMigrateData(
            port_id=uuids.port_id, vnic_type=network_model.VNIC_TYPE_NORMAL,
            vif_type=network_model.VIF_TYPE_BRIDGE, vif_details={'bar': 'baz'},
            profile={}, host='fake-dest-host', source_vif=source_vif)
        dest_vif = migrate_vif.get_dest_vif()
        self.assertEqual(migrate_vif.port_id, dest_vif['id'])
        self.assertEqual(migrate_vif.vnic_type, dest_vif['vnic_type'])
        self.assertEqual(migrate_vif.vif_type, dest_vif['type'])
        self.assertEqual(migrate_vif.vif_details, dest_vif['details'])
        self.assertEqual(migrate_vif.profile, dest_vif['profile'])
        self.assertEqual(uuids.ovs_interfaceid, dest_vif['ovs_interfaceid'])
