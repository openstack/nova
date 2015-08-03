#    Copyright 2010 OpenStack Foundation
#    Copyright 2012 University Of Minho
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

import os

import mock
from os_brick.initiator import connector
from oslo_concurrency import processutils
from oslo_config import cfg

from nova import exception
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova import utils
from nova.virt.libvirt import host
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import volume

CONF = cfg.CONF
SECRET_UUID = '2a0a0d6c-babf-454d-b93e-9ac9957b95e0'


class FakeSecret(object):

    def __init__(self):
        self.uuid = SECRET_UUID

    def getUUIDString(self):
        return self.uuid

    def UUIDString(self):
        return self.uuid

    def setValue(self, value):
        self.value = value
        return 0

    def getValue(self, value):
        return self.value

    def undefine(self):
        self.value = None
        return 0


class LibvirtVolumeBaseTestCase(test.NoDBTestCase):
    """Contains common setup and helper methods for libvirt volume tests."""

    def setUp(self):
        super(LibvirtVolumeBaseTestCase, self).setUp()
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)

        self.useFixture(fakelibvirt.FakeLibvirtFixture())

        class FakeLibvirtDriver(object):
            def __init__(self):
                self._host = host.Host("qemu:///system")

            def _get_all_block_devices(self):
                return []

        self.fake_conn = FakeLibvirtDriver()
        self.connr = {
            'ip': '127.0.0.1',
            'initiator': 'fake_initiator',
            'host': 'fake_host'
        }
        self.disk_info = {
            "bus": "virtio",
            "dev": "vde",
            "type": "disk",
        }
        self.name = 'volume-00000001'
        self.location = '10.0.2.15:3260'
        self.iqn = 'iqn.2010-10.org.openstack:%s' % self.name
        self.vol = {'id': 1, 'name': self.name}
        self.uuid = '875a8070-d0b9-4949-8b31-104d125c9a64'
        self.user = 'foo'

    def _assertFileTypeEquals(self, tree, file_path):
        self.assertEqual(tree.get('type'), 'file')
        self.assertEqual(tree.find('./source').get('file'), file_path)


class LibvirtVolumeTestCase(LibvirtVolumeBaseTestCase):

    def _assertNetworkAndProtocolEquals(self, tree):
        self.assertEqual(tree.get('type'), 'network')
        self.assertEqual(tree.find('./source').get('protocol'), 'rbd')
        rbd_name = '%s/%s' % ('rbd', self.name)
        self.assertEqual(tree.find('./source').get('name'), rbd_name)

    def _assertISCSINetworkAndProtocolEquals(self, tree):
        self.assertEqual(tree.get('type'), 'network')
        self.assertEqual(tree.find('./source').get('protocol'), 'iscsi')
        iscsi_name = '%s/%s' % (self.iqn, self.vol['id'])
        self.assertEqual(tree.find('./source').get('name'), iscsi_name)

    def _assertDiskInfoEquals(self, tree, disk_info):
        self.assertEqual(tree.get('device'), disk_info['type'])
        self.assertEqual(tree.find('./target').get('bus'),
                         disk_info['bus'])
        self.assertEqual(tree.find('./target').get('dev'),
                         disk_info['dev'])

    def _test_libvirt_volume_driver_disk_info(self):
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_conn)
        connection_info = {
            'driver_volume_type': 'fake',
            'data': {
                'device_path': '/foo',
            },
            'serial': 'fake_serial',
        }
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertDiskInfoEquals(tree, self.disk_info)

    def test_libvirt_volume_disk_info_type(self):
        self.disk_info['type'] = 'cdrom'
        self._test_libvirt_volume_driver_disk_info()

    def test_libvirt_volume_disk_info_dev(self):
        self.disk_info['dev'] = 'hdc'
        self._test_libvirt_volume_driver_disk_info()

    def test_libvirt_volume_disk_info_bus(self):
        self.disk_info['bus'] = 'scsi'
        self._test_libvirt_volume_driver_disk_info()

    def test_libvirt_volume_driver_serial(self):
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_conn)
        connection_info = {
            'driver_volume_type': 'fake',
            'data': {
                'device_path': '/foo',
            },
            'serial': 'fake_serial',
        }
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('block', tree.get('type'))
        self.assertEqual('fake_serial', tree.find('./serial').text)
        self.assertIsNone(tree.find('./blockio'))

    def test_libvirt_volume_driver_blockio(self):
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_conn)
        connection_info = {
            'driver_volume_type': 'fake',
            'data': {
                'device_path': '/foo',
                'logical_block_size': '4096',
                'physical_block_size': '4096',
                },
            'serial': 'fake_serial',
            }
        disk_info = {
            "bus": "virtio",
            "dev": "vde",
            "type": "disk",
            }
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        blockio = tree.find('./blockio')
        self.assertEqual('4096', blockio.get('logical_block_size'))
        self.assertEqual('4096', blockio.get('physical_block_size'))

    def test_libvirt_volume_driver_iotune(self):
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_conn)
        connection_info = {
            'driver_volume_type': 'fake',
            'data': {
                "device_path": "/foo",
                'qos_specs': 'bar',
                },
            }
        disk_info = {
            "bus": "virtio",
            "dev": "vde",
            "type": "disk",
            }
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        iotune = tree.find('./iotune')
        # ensure invalid qos_specs is ignored
        self.assertIsNone(iotune)

        specs = {
            'total_bytes_sec': '102400',
            'read_bytes_sec': '51200',
            'write_bytes_sec': '0',
            'total_iops_sec': '0',
            'read_iops_sec': '200',
            'write_iops_sec': '200',
        }
        del connection_info['data']['qos_specs']
        connection_info['data'].update(dict(qos_specs=specs))
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        self.assertEqual('102400', tree.find('./iotune/total_bytes_sec').text)
        self.assertEqual('51200', tree.find('./iotune/read_bytes_sec').text)
        self.assertEqual('0', tree.find('./iotune/write_bytes_sec').text)
        self.assertEqual('0', tree.find('./iotune/total_iops_sec').text)
        self.assertEqual('200', tree.find('./iotune/read_iops_sec').text)
        self.assertEqual('200', tree.find('./iotune/write_iops_sec').text)

    def test_libvirt_volume_driver_readonly(self):
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_conn)
        connection_info = {
            'driver_volume_type': 'fake',
            'data': {
                "device_path": "/foo",
                'access_mode': 'bar',
                },
            }
        disk_info = {
            "bus": "virtio",
            "dev": "vde",
            "type": "disk",
            }
        self.assertRaises(exception.InvalidVolumeAccessMode,
                          libvirt_driver.get_config,
                          connection_info, self.disk_info)

        connection_info['data']['access_mode'] = 'rw'
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        readonly = tree.find('./readonly')
        self.assertIsNone(readonly)

        connection_info['data']['access_mode'] = 'ro'
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        readonly = tree.find('./readonly')
        self.assertIsNotNone(readonly)

    def iscsi_connection(self, volume, location, iqn, auth=False,
                         transport=None):
        dev_name = 'ip-%s-iscsi-%s-lun-1' % (location, iqn)
        if transport is not None:
            dev_name = 'pci-0000:00:00.0-' + dev_name
        dev_path = '/dev/disk/by-path/%s' % (dev_name)
        ret = {
                'driver_volume_type': 'iscsi',
                'data': {
                    'volume_id': volume['id'],
                    'target_portal': location,
                    'target_iqn': iqn,
                    'target_lun': 1,
                    'device_path': dev_path,
                    'qos_specs': {
                        'total_bytes_sec': '102400',
                        'read_iops_sec': '200',
                        }
                }
        }
        if auth:
            ret['data']['auth_method'] = 'CHAP'
            ret['data']['auth_username'] = 'foo'
            ret['data']['auth_password'] = 'bar'
        return ret

    def iscsi_connection_discovery_chap_enable(self, volume, location, iqn):
        dev_name = 'ip-%s-iscsi-%s-lun-1' % (location, iqn)
        dev_path = '/dev/disk/by-path/%s' % (dev_name)
        return {
                'driver_volume_type': 'iscsi',
                'data': {
                    'volume_id': volume['id'],
                    'target_portal': location,
                    'target_iqn': iqn,
                    'target_lun': 1,
                    'device_path': dev_path,
                    'discovery_auth_method': 'CHAP',
                    'discovery_auth_username': "testuser",
                    'discovery_auth_password': '123456',
                    'qos_specs': {
                        'total_bytes_sec': '102400',
                        'read_iops_sec': '200',
                        }
                }
        }

    def generate_device(self, transport=None, lun=1, short=False):
        dev_format = "ip-%s-iscsi-%s-lun-%s" % (self.location, self.iqn, lun)
        if transport:
            dev_format = "pci-0000:00:00.0-" + dev_format
        if short:
            return dev_format
        fake_dev_path = "/dev/disk/by-path/" + dev_format
        return fake_dev_path

    def test_iscsiadm_discover_parsing(self):
        # Ensure that parsing iscsiadm discover ignores cruft.

        targets = [
            ["192.168.204.82:3260,1",
             ("iqn.2010-10.org.openstack:volume-"
              "f9b12623-6ce3-4dac-a71f-09ad4249bdd3")],
            ["192.168.204.82:3261,1",
             ("iqn.2010-10.org.openstack:volume-"
              "f9b12623-6ce3-4dac-a71f-09ad4249bdd4")]]

        # This slight wonkiness brought to you by pep8, as the actual
        # example output runs about 97 chars wide.
        sample_input = """Loading iscsi modules: done
Starting iSCSI initiator service: done
Setting up iSCSI targets: unused
%s %s
%s %s
""" % (targets[0][0], targets[0][1], targets[1][0], targets[1][1])
        driver = volume.LibvirtISCSIVolumeDriver("none")
        out = driver.connector._get_target_portals_from_iscsiadm_output(
            sample_input)
        self.assertEqual(out, targets)

    def test_libvirt_iscsi_driver(self, transport=None):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.ISCSIConnector)

    def test_sanitize_log_run_iscsiadm(self):
        # Tests that the parameters to the os-brick connector's
        # _run_iscsiadm function are sanitized for passwords when logged.
        def fake_debug(*args, **kwargs):
            self.assertIn('node.session.auth.password', args[0])
            self.assertNotIn('scrubme', args[0])

        def fake_execute(*args, **kwargs):
            return (None, None)

        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        libvirt_driver.connector.set_execute(fake_execute)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn)
        iscsi_properties = connection_info['data']
        with mock.patch.object(connector.LOG, 'debug',
                               side_effect=fake_debug) as debug_mock:
            libvirt_driver.connector._iscsiadm_update(
                iscsi_properties, 'node.session.auth.password', 'scrubme')

            # we don't care what the log message is, we just want to make sure
            # our stub method is called which asserts the password is scrubbed
            self.assertTrue(debug_mock.called)

    def iser_connection(self, volume, location, iqn):
        return {
                'driver_volume_type': 'iser',
                'data': {
                    'volume_id': volume['id'],
                    'target_portal': location,
                    'target_iqn': iqn,
                    'target_lun': 1,
                }
        }

    def sheepdog_connection(self, volume):
        return {
            'driver_volume_type': 'sheepdog',
            'data': {
                'name': volume['name']
            }
        }

    def test_libvirt_sheepdog_driver(self):
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.sheepdog_connection(self.vol)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual(tree.get('type'), 'network')
        self.assertEqual(tree.find('./source').get('protocol'), 'sheepdog')
        self.assertEqual(tree.find('./source').get('name'), self.name)
        libvirt_driver.disconnect_volume(connection_info, "vde")

    def rbd_connection(self, volume):
        return {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % ('rbd', volume['name']),
                'auth_enabled': CONF.libvirt.rbd_secret_uuid is not None,
                'auth_username': CONF.libvirt.rbd_user,
                'secret_type': 'ceph',
                'secret_uuid': CONF.libvirt.rbd_secret_uuid,
                'qos_specs': {
                    'total_bytes_sec': '1048576',
                    'read_iops_sec': '500',
                    }
            }
        }

    def test_libvirt_rbd_driver(self):
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.rbd_connection(self.vol)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertIsNone(tree.find('./source/auth'))
        self.assertEqual('1048576', tree.find('./iotune/total_bytes_sec').text)
        self.assertEqual('500', tree.find('./iotune/read_iops_sec').text)
        libvirt_driver.disconnect_volume(connection_info, "vde")

    def test_libvirt_rbd_driver_hosts(self):
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.rbd_connection(self.vol)
        hosts = ['example.com', '1.2.3.4', '::1']
        ports = [None, '6790', '6791']
        connection_info['data']['hosts'] = hosts
        connection_info['data']['ports'] = ports
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertIsNone(tree.find('./source/auth'))
        found_hosts = tree.findall('./source/host')
        self.assertEqual([host.get('name') for host in found_hosts], hosts)
        self.assertEqual([host.get('port') for host in found_hosts], ports)
        libvirt_driver.disconnect_volume(connection_info, "vde")

    def test_libvirt_rbd_driver_auth_enabled(self):
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = True
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertEqual(tree.find('./auth').get('username'), self.user)
        self.assertEqual(tree.find('./auth/secret').get('type'), secret_type)
        self.assertEqual(tree.find('./auth/secret').get('uuid'), self.uuid)
        libvirt_driver.disconnect_volume(connection_info, "vde")

    def test_libvirt_rbd_driver_auth_enabled_flags_override(self):
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = True
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        flags_uuid = '37152720-1785-11e2-a740-af0c1d8b8e4b'
        flags_user = 'bar'
        self.flags(rbd_user=flags_user,
                   rbd_secret_uuid=flags_uuid,
                   group='libvirt')

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertEqual(tree.find('./auth').get('username'), flags_user)
        self.assertEqual(tree.find('./auth/secret').get('type'), secret_type)
        self.assertEqual(tree.find('./auth/secret').get('uuid'), flags_uuid)
        libvirt_driver.disconnect_volume(connection_info, "vde")

    def test_libvirt_rbd_driver_auth_disabled(self):
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = False
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertIsNone(tree.find('./auth'))
        libvirt_driver.disconnect_volume(connection_info, "vde")

    def test_libvirt_rbd_driver_auth_disabled_flags_override(self):
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.rbd_connection(self.vol)
        secret_type = 'ceph'
        connection_info['data']['auth_enabled'] = False
        connection_info['data']['auth_username'] = self.user
        connection_info['data']['secret_type'] = secret_type
        connection_info['data']['secret_uuid'] = self.uuid

        # NOTE: Supplying the rbd_secret_uuid will enable authentication
        # locally in nova-compute even if not enabled in nova-volume/cinder
        flags_uuid = '37152720-1785-11e2-a740-af0c1d8b8e4b'
        flags_user = 'bar'
        self.flags(rbd_user=flags_user,
                   rbd_secret_uuid=flags_uuid,
                   group='libvirt')

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertNetworkAndProtocolEquals(tree)
        self.assertEqual(tree.find('./auth').get('username'), flags_user)
        self.assertEqual(tree.find('./auth/secret').get('type'), secret_type)
        self.assertEqual(tree.find('./auth/secret').get('uuid'), flags_uuid)
        libvirt_driver.disconnect_volume(connection_info, "vde")

    @mock.patch.object(host.Host, 'find_secret')
    @mock.patch.object(host.Host, 'create_secret')
    @mock.patch.object(host.Host, 'delete_secret')
    def test_libvirt_iscsi_net_driver(self, mock_delete, mock_create,
                                      mock_find):
        mock_find.return_value = FakeSecret()
        mock_create.return_value = FakeSecret()
        libvirt_driver = volume.LibvirtNetVolumeDriver(self.fake_conn)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn, auth=True)
        secret_type = 'iscsi'
        flags_user = connection_info['data']['auth_username']
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertISCSINetworkAndProtocolEquals(tree)
        self.assertEqual(tree.find('./auth').get('username'), flags_user)
        self.assertEqual(tree.find('./auth/secret').get('type'), secret_type)
        self.assertEqual(tree.find('./auth/secret').get('uuid'), SECRET_UUID)
        libvirt_driver.disconnect_volume(connection_info, 'vde')

    def test_libvirt_nfs_driver(self):
        # NOTE(vish) exists is to make driver assume connecting worked
        mnt_base = '/mnt'
        self.flags(nfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtNFSVolumeDriver(self.fake_conn)
        self.stubs.Set(libvirt_utils, 'is_mounted', lambda x, d: False)

        export_string = '192.168.1.1:/nfs/share1'
        export_mnt_base = os.path.join(mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        device_path = os.path.join(export_mnt_base,
                                   connection_info['data']['name'])
        self.assertEqual(device_path, connection_info['data']['device_path'])
        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'nfs', export_string, export_mnt_base),
            ('umount', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)

    @mock.patch.object(volume.utils, 'execute')
    @mock.patch.object(volume.LOG, 'debug')
    @mock.patch.object(volume.LOG, 'exception')
    def test_libvirt_nfs_driver_umount_error(self, mock_LOG_exception,
                                        mock_LOG_debug, mock_utils_exe):
        export_string = '192.168.1.1:/nfs/share1'
        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver = volume.LibvirtNFSVolumeDriver(self.fake_conn)
        mock_utils_exe.side_effect = processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: device is busy.')
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertTrue(mock_LOG_debug.called)
        mock_utils_exe.side_effect = processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: target is busy.')
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertTrue(mock_LOG_debug.called)
        mock_utils_exe.side_effect = processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: Other error.')
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertTrue(mock_LOG_exception.called)

    def test_libvirt_nfs_driver_get_config(self):
        libvirt_driver = volume.LibvirtNFSVolumeDriver(self.fake_conn)
        mnt_base = '/mnt'
        self.flags(nfs_mount_point_base=mnt_base, group='libvirt')
        export_string = '192.168.1.1:/nfs/share1'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(export_string))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'device_path': file_path}}
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)
        self.assertEqual('raw', tree.find('./driver').get('type'))

    def test_libvirt_nfs_driver_already_mounted(self):
        # NOTE(vish) exists is to make driver assume connecting worked
        mnt_base = '/mnt'
        self.flags(nfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtNFSVolumeDriver(self.fake_conn)

        export_string = '192.168.1.1:/nfs/share1'
        export_mnt_base = os.path.join(mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('findmnt', '--target', export_mnt_base, '--source',
             export_string),
            ('umount', export_mnt_base)]
        self.assertEqual(self.executes, expected_commands)

    def test_libvirt_nfs_driver_with_opts(self):
        mnt_base = '/mnt'
        self.flags(nfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtNFSVolumeDriver(self.fake_conn)
        self.stubs.Set(libvirt_utils, 'is_mounted', lambda x, d: False)
        export_string = '192.168.1.1:/nfs/share1'
        options = '-o intr,nfsvers=3'
        export_mnt_base = os.path.join(mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': options}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'nfs', '-o', 'intr,nfsvers=3',
             export_string, export_mnt_base),
            ('umount', export_mnt_base),
        ]
        self.assertEqual(expected_commands, self.executes)

    @mock.patch('os.path.exists', return_value=True)
    def test_libvirt_aoe_driver(self, exists):
        libvirt_driver = volume.LibvirtAOEVolumeDriver(self.fake_conn)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.AoEConnector)

    def test_libvirt_glusterfs_driver(self):
        mnt_base = '/mnt'
        self.flags(glusterfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtGlusterfsVolumeDriver(self.fake_conn)
        self.stubs.Set(libvirt_utils, 'is_mounted', lambda x, d: False)
        export_string = '192.168.1.1:/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        device_path = os.path.join(export_mnt_base,
                                   connection_info['data']['name'])
        self.assertEqual(device_path, connection_info['data']['device_path'])
        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'glusterfs', export_string, export_mnt_base),
            ('umount', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)

    def test_libvirt_glusterfs_driver_get_config(self):
        mnt_base = '/mnt'
        self.flags(glusterfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtGlusterfsVolumeDriver(self.fake_conn)
        export_string = '192.168.1.1:/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(export_string))
        file_path = os.path.join(export_mnt_base, self.name)

        # Test default format - raw
        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'device_path': file_path}}
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)
        self.assertEqual('raw', tree.find('./driver').get('type'))

        # Test specified format - qcow2
        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'device_path': file_path,
                                    'format': 'qcow2'}}
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)
        self.assertEqual('qcow2', tree.find('./driver').get('type'))

    def test_libvirt_glusterfs_driver_already_mounted(self):
        mnt_base = '/mnt'
        self.flags(glusterfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtGlusterfsVolumeDriver(self.fake_conn)
        export_string = '192.168.1.1:/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('findmnt', '--target', export_mnt_base,
             '--source', export_string),
            ('umount', export_mnt_base)]
        self.assertEqual(self.executes, expected_commands)

    def test_libvirt_glusterfs_driver_with_opts(self):
        mnt_base = '/mnt'
        self.flags(glusterfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtGlusterfsVolumeDriver(self.fake_conn)
        self.stubs.Set(libvirt_utils, 'is_mounted', lambda x, d: False)
        export_string = '192.168.1.1:/volume-00001'
        options = '-o backupvolfile-server=192.168.1.2'
        export_mnt_base = os.path.join(mnt_base,
                utils.get_hash_str(export_string))

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': options}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'glusterfs',
             '-o', 'backupvolfile-server=192.168.1.2',
             export_string, export_mnt_base),
            ('umount', export_mnt_base),
        ]
        self.assertEqual(self.executes, expected_commands)

    def test_libvirt_glusterfs_libgfapi(self):
        self.flags(qemu_allowed_storage_drivers=['gluster'], group='libvirt')
        libvirt_driver = volume.LibvirtGlusterfsVolumeDriver(self.fake_conn)
        self.stubs.Set(libvirt_utils, 'is_mounted', lambda x, d: False)
        export_string = '192.168.1.1:/volume-00001'
        name = 'volume-00001'

        connection_info = {'data': {'export': export_string, 'name': name}}

        disk_info = {
            "dev": "vde",
            "type": "disk",
            "bus": "virtio",
        }

        libvirt_driver.connect_volume(connection_info, disk_info)
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        self.assertEqual(tree.get('type'), 'network')
        self.assertEqual(tree.find('./driver').get('type'), 'raw')

        source = tree.find('./source')
        self.assertEqual(source.get('protocol'), 'gluster')
        self.assertEqual(source.get('name'), 'volume-00001/volume-00001')
        self.assertEqual(source.find('./host').get('name'), '192.168.1.1')
        self.assertEqual(source.find('./host').get('port'), '24007')

        libvirt_driver.disconnect_volume(connection_info, "vde")

    @mock.patch.object(libvirt_utils, 'is_mounted')
    def test_libvirt_smbfs_driver(self, mock_is_mounted):
        mnt_base = '/mnt'
        self.flags(smbfs_mount_point_base=mnt_base, group='libvirt')
        mock_is_mounted.return_value = False

        libvirt_driver = volume.LibvirtSMBFSVolumeDriver(self.fake_conn)
        export_string = '//192.168.1.1/volumes'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(export_string))
        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': None}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'cifs', '-o', 'username=guest',
             export_string, export_mnt_base),
            ('umount', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)

    def test_libvirt_smbfs_driver_already_mounted(self):
        mnt_base = '/mnt'
        self.flags(smbfs_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtSMBFSVolumeDriver(self.fake_conn)
        export_string = '//192.168.1.1/volumes'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(export_string))
        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('findmnt', '--target', export_mnt_base,
             '--source', export_string),
            ('umount', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)

    def test_libvirt_smbfs_driver_get_config(self):
        mnt_base = '/mnt'
        self.flags(smbfs_mount_point_base=mnt_base, group='libvirt')
        libvirt_driver = volume.LibvirtSMBFSVolumeDriver(self.fake_conn)
        export_string = '//192.168.1.1/volumes'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(export_string))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'device_path': file_path}}
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)

    @mock.patch.object(libvirt_utils, 'is_mounted')
    def test_libvirt_smbfs_driver_with_opts(self, mock_is_mounted):
        mnt_base = '/mnt'
        self.flags(smbfs_mount_point_base=mnt_base, group='libvirt')
        mock_is_mounted.return_value = False

        libvirt_driver = volume.LibvirtSMBFSVolumeDriver(self.fake_conn)
        export_string = '//192.168.1.1/volumes'
        options = '-o user=guest,uid=107,gid=105'
        export_mnt_base = os.path.join(mnt_base,
            utils.get_hash_str(export_string))
        connection_info = {'data': {'export': export_string,
                                    'name': self.name,
                                    'options': options}}

        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('mkdir', '-p', export_mnt_base),
            ('mount', '-t', 'cifs', '-o', 'user=guest,uid=107,gid=105',
             export_string, export_mnt_base),
            ('umount', export_mnt_base)]
        self.assertEqual(expected_commands, self.executes)
