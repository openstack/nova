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

import contextlib
import glob
import os
import time

import eventlet
import fixtures
import mock
from oslo_concurrency import processutils
from oslo_config import cfg

from nova import exception
from nova.storage import linuxscsi
from nova import test
from nova.tests.unit.virt.libvirt import fake_libvirt_utils
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova import utils
from nova.virt.libvirt import host
from nova.virt.libvirt import quobyte
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt import volume

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


class LibvirtVolumeTestCase(test.NoDBTestCase):

    def setUp(self):
        super(LibvirtVolumeTestCase, self).setUp()
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

    def _assertFileTypeEquals(self, tree, file_path):
        self.assertEqual(tree.get('type'), 'file')
        self.assertEqual(tree.find('./source').get('file'), file_path)

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

    def test_rescan_multipath(self):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        libvirt_driver._rescan_multipath()
        expected_multipath_cmd = ('multipath', '-r')
        self.assertIn(expected_multipath_cmd, self.executes)

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
        out = driver._get_target_portals_from_iscsiadm_output(sample_input)
        self.assertEqual(out, targets)

    def test_libvirt_iscsi_get_host_device(self, transport=None):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn)
        iscsi_properties = connection_info['data']
        expected_device = self.generate_device(transport, 1, False)
        if transport:
            self.stubs.Set(glob, 'glob', lambda x: [expected_device])
        device = libvirt_driver._get_host_device(iscsi_properties)
        self.assertEqual(expected_device, device)

    def test_libvirt_iscsi_get_host_device_with_transport(self):
        self.flags(iscsi_transport='fake_transport', group='libvirt')
        self.test_libvirt_iscsi_get_host_device('fake_transport')

    def test_libvirt_iscsi_driver(self, transport=None):
        # NOTE(vish) exists is to make driver assume connecting worked
        self.stubs.Set(os.path, 'exists', lambda x: True)
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn, False, transport)
        if transport is not None:
            self.stubs.Set(libvirt_driver, '_get_host_device',
                           lambda x: self.generate_device(transport, 1, False))
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")
        expected_commands = [('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location),
                             ('iscsiadm', '-m', 'session'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--login'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--op', 'update',
                              '-n', 'node.startup', '-v', 'automatic'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--rescan'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--op', 'update',
                              '-n', 'node.startup', '-v', 'manual'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--logout'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--op', 'delete')]
        self.assertEqual(expected_commands, self.executes)

    def test_libvirt_iscsi_driver_with_transport(self):
        self.flags(iscsi_transport='fake_transport', group='libvirt')
        self.test_libvirt_iscsi_driver('fake_transport')

    def test_libvirt_iscsi_driver_still_in_use(self, transport=None):
        # NOTE(vish) exists is to make driver assume connecting worked
        self.stubs.Set(os.path, 'exists', lambda x: True)
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        dev_name = self.generate_device(transport, 1, True)
        if transport is not None:
            self.stubs.Set(libvirt_driver, '_get_host_device',
                           lambda x: self.generate_device(transport, 1, False))
        devs = [self.generate_device(transport, 2, False)]
        self.stubs.Set(self.fake_conn, '_get_all_block_devices', lambda: devs)
        vol = {'id': 1, 'name': self.name}
        connection_info = self.iscsi_connection(vol, self.location, self.iqn)
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")
        expected_commands = [('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location),
                             ('iscsiadm', '-m', 'session'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--login'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--op', 'update',
                              '-n', 'node.startup', '-v', 'automatic'),
                             ('iscsiadm', '-m', 'node', '-T', self.iqn,
                              '-p', self.location, '--rescan'),
                             ('cp', '/dev/stdin',
                              '/sys/block/%s/device/delete' % dev_name)]
        self.assertEqual(self.executes, expected_commands)

    def test_libvirt_iscsi_driver_still_in_use_with_transport(self):
        self.flags(iscsi_transport='fake_transport', group='libvirt')
        self.test_libvirt_iscsi_driver_still_in_use('fake_transport')

    def test_libvirt_iscsi_driver_disconnect_multipath_error(self,
                                                             transport=None):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        if transport is None:
            prefix = ""
        else:
            prefix = "pci-0000:00:00.0-"
        devs = [self.generate_device(transport, 2, False)]
        iscsi_devs = ['%sip-fake-ip-iscsi-fake-portal-lun-2' % prefix]
        with contextlib.nested(
            mock.patch.object(os.path, 'exists', return_value=True),
            mock.patch.object(self.fake_conn, '_get_all_block_devices',
                              return_value=devs),
            mock.patch.object(libvirt_driver, '_rescan_multipath'),
            mock.patch.object(libvirt_driver, '_run_multipath'),
            mock.patch.object(libvirt_driver, '_get_multipath_device_name',
                        return_value='/dev/mapper/fake-multipath-devname'),
            mock.patch.object(libvirt_driver, '_get_iscsi_devices',
                              return_value=iscsi_devs),
            mock.patch.object(libvirt_driver,
                              '_get_target_portals_from_iscsiadm_output',
                              return_value=[('fake-ip', 'fake-portal')]),
            mock.patch.object(libvirt_driver, '_get_multipath_iqn',
                              return_value='fake-portal'),
        ) as (mock_exists, mock_devices, mock_rescan_multipath,
              mock_run_multipath, mock_device_name, mock_iscsi_devices,
              mock_get_portals, mock_get_iqn):
            mock_run_multipath.side_effect = processutils.ProcessExecutionError
            vol = {'id': 1, 'name': self.name}
            connection_info = self.iscsi_connection(vol, self.location,
                                                    self.iqn)
            libvirt_driver.connect_volume(connection_info, self.disk_info)

            libvirt_driver.use_multipath = True
            libvirt_driver.disconnect_volume(connection_info, "vde")
            mock_run_multipath.assert_called_once_with(
                                            ['-f', 'fake-multipath-devname'],
                                            check_exit_code=[0, 1])

    def test_libvirt_iscsi_driver_get_config(self, transport=None):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        dev_name = self.generate_device(transport, 1, True)
        dev_path = '/dev/disk/by-path/%s' % (dev_name)
        vol = {'id': 1, 'name': self.name}
        connection_info = self.iscsi_connection(vol, self.location,
                                                self.iqn, False, transport)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('block', tree.get('type'))
        self.assertEqual(dev_path, tree.find('./source').get('dev'))

        libvirt_driver.use_multipath = True
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('block', tree.get('type'))
        self.assertEqual(dev_path, tree.find('./source').get('dev'))

    def test_libvirt_iscsi_driver_get_config_with_transport(self):
        self.flags(iscsi_transport = 'fake_transport', group='libvirt')
        self.test_libvirt_iscsi_driver_get_config('fake_transport')

    def test_libvirt_iscsi_driver_multipath_id(self):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        libvirt_driver.use_multipath = True
        self.stubs.Set(libvirt_driver, '_run_iscsiadm_bare',
                       lambda x, check_exit_code: ('',))
        self.stubs.Set(libvirt_driver, '_rescan_iscsi', lambda: None)
        self.stubs.Set(libvirt_driver, '_get_host_device', lambda x: None)
        self.stubs.Set(libvirt_driver, '_rescan_multipath', lambda: None)
        fake_multipath_id = 'fake_multipath_id'
        fake_multipath_device = '/dev/mapper/%s' % fake_multipath_id
        self.stubs.Set(libvirt_driver, '_get_multipath_device_name',
                       lambda x: fake_multipath_device)

        def fake_disconnect_volume_multipath_iscsi(iscsi_properties,
                                                   multipath_device):
            if fake_multipath_device != multipath_device:
                raise Exception('Invalid multipath_device.')

        self.stubs.Set(libvirt_driver, '_disconnect_volume_multipath_iscsi',
                       fake_disconnect_volume_multipath_iscsi)
        with mock.patch.object(os.path, 'exists', return_value=True):
            vol = {'id': 1, 'name': self.name}
            connection_info = self.iscsi_connection(vol, self.location,
                                                    self.iqn)
            libvirt_driver.connect_volume(connection_info,
                                          self.disk_info)
            self.assertEqual(fake_multipath_id,
                             connection_info['data']['multipath_id'])
            libvirt_driver.disconnect_volume(connection_info, "fake")

    def test_sanitize_log_run_iscsiadm(self):
        # Tests that the parameters to the _run_iscsiadm function are sanitized
        # for passwords when logged.
        def fake_debug(*args, **kwargs):
            self.assertIn('node.session.auth.password', args[0])
            self.assertNotIn('scrubme', args[0])

        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn)
        iscsi_properties = connection_info['data']
        with mock.patch.object(volume.LOG, 'debug',
                               side_effect=fake_debug) as debug_mock:
            libvirt_driver._iscsiadm_update(iscsi_properties,
                                            'node.session.auth.password',
                                            'scrubme')
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

    def test_libvirt_iscsi_driver_discovery_chap_enable(self):
        # NOTE(vish) exists is to make driver assume connecting worked
        self.stubs.Set(os.path, 'exists', lambda x: True)
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        libvirt_driver.use_multipath = True
        connection_info = self.iscsi_connection_discovery_chap_enable(
                                                self.vol, self.location,
                                                self.iqn)
        mpdev_filepath = '/dev/mapper/foo'
        libvirt_driver._get_multipath_device_name = lambda x: mpdev_filepath
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        libvirt_driver.disconnect_volume(connection_info, "vde")
        expected_commands = [('iscsiadm', '-m', 'discoverydb',
                              '-t', 'sendtargets',
                              '-p', self.location, '--op', 'update',
                              '-n', 'discovery.sendtargets.auth.authmethod',
                              '-v', 'CHAP',
                              '-n', 'discovery.sendtargets.auth.username',
                              '-v', 'testuser',
                              '-n', 'discovery.sendtargets.auth.password',
                              '-v', '123456'),
                             ('iscsiadm', '-m', 'discoverydb',
                              '-t', 'sendtargets',
                              '-p', self.location, '--discover'),
                             ('iscsiadm', '-m', 'node', '--rescan'),
                             ('iscsiadm', '-m', 'session', '--rescan'),
                             ('multipath', '-r'),
                             ('iscsiadm', '-m', 'node', '--rescan'),
                             ('iscsiadm', '-m', 'session', '--rescan'),
                             ('multipath', '-r'),
                             ('iscsiadm', '-m', 'discoverydb',
                              '-t', 'sendtargets',
                              '-p', self.location, '--op', 'update',
                              '-n', 'discovery.sendtargets.auth.authmethod',
                              '-v', 'CHAP',
                              '-n', 'discovery.sendtargets.auth.username',
                              '-v', 'testuser',
                              '-n', 'discovery.sendtargets.auth.password',
                              '-v', '123456'),
                             ('iscsiadm', '-m', 'discoverydb',
                              '-t', 'sendtargets',
                              '-p', self.location, '--discover'),
                             ('multipath', '-r')]
        self.assertEqual(self.executes, expected_commands)

    def test_libvirt_kvm_volume(self):
        self.stubs.Set(os.path, 'exists', lambda x: True)
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        dev_str = '/dev/disk/by-path/ip-%s-iscsi-%s-lun-1' % (self.location,
                                                              self.iqn)
        self.assertEqual(tree.get('type'), 'block')
        self.assertEqual(tree.find('./source').get('dev'), dev_str)
        libvirt_driver.disconnect_volume(connection_info, 'vde')

    def test_libvirt_kvm_volume_with_multipath(self):
        self.flags(iscsi_use_multipath=True, group='libvirt')
        self.stubs.Set(os.path, 'exists', lambda x: True)
        devs = ['/dev/mapper/sda', '/dev/mapper/sdb']
        self.stubs.Set(self.fake_conn, '_get_all_block_devices', lambda: devs)
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn)
        mpdev_filepath = '/dev/mapper/foo'
        connection_info['data']['device_path'] = mpdev_filepath
        libvirt_driver._get_multipath_device_name = lambda x: mpdev_filepath
        iscsi_devs = ['ip-%s-iscsi-%s-lun-0' % (self.location, self.iqn)]
        self.stubs.Set(libvirt_driver, '_get_iscsi_devices',
                       lambda: iscsi_devs)
        self.stubs.Set(libvirt_driver,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [[self.location, self.iqn]])
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual(tree.find('./source').get('dev'), mpdev_filepath)
        libvirt_driver._get_multipath_iqn = lambda x: self.iqn
        libvirt_driver.disconnect_volume(connection_info, 'vde')
        expected_multipath_cmd = ('multipath', '-f', 'foo')
        self.assertIn(expected_multipath_cmd, self.executes)

    def test_libvirt_kvm_volume_with_multipath_connecting(self):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        ip_iqns = [[self.location, self.iqn],
                   ['10.0.2.16:3260', self.iqn],
                   [self.location,
                    'iqn.2010-10.org.openstack:volume-00000002']]

        with contextlib.nested(
            mock.patch.object(os.path, 'exists', return_value=True),
            mock.patch.object(libvirt_driver, '_run_iscsiadm_bare'),
            mock.patch.object(libvirt_driver,
                              '_get_target_portals_from_iscsiadm_output',
                              return_value=ip_iqns),
            mock.patch.object(libvirt_driver, '_connect_to_iscsi_portal'),
            mock.patch.object(libvirt_driver, '_rescan_iscsi'),
            mock.patch.object(libvirt_driver, '_get_host_device',
                              return_value='fake-device'),
            mock.patch.object(libvirt_driver, '_rescan_multipath'),
            mock.patch.object(libvirt_driver, '_get_multipath_device_name',
                              return_value='/dev/mapper/fake-mpath-devname')
        ) as (mock_exists, mock_run_iscsiadm_bare, mock_get_portals,
              mock_connect_iscsi, mock_rescan_iscsi, mock_host_device,
              mock_rescan_multipath, mock_device_name):
            vol = {'id': 1, 'name': self.name}
            connection_info = self.iscsi_connection(vol, self.location,
                                                    self.iqn)
            libvirt_driver.use_multipath = True
            libvirt_driver.connect_volume(connection_info, self.disk_info)

            # Verify that the supplied iqn is used when it shares the same
            # iqn between multiple portals.
            connection_info = self.iscsi_connection(vol, self.location,
                                                    self.iqn)
            props1 = connection_info['data'].copy()
            props2 = connection_info['data'].copy()
            props2['target_portal'] = '10.0.2.16:3260'
            expected_calls = [mock.call(props1), mock.call(props2),
                              mock.call(props1)]
            self.assertEqual(expected_calls, mock_connect_iscsi.call_args_list)

    def test_libvirt_kvm_volume_with_multipath_still_in_use(self):
        name = 'volume-00000001'
        location = '10.0.2.15:3260'
        iqn = 'iqn.2010-10.org.openstack:%s' % name
        mpdev_filepath = '/dev/mapper/foo'

        def _get_multipath_device_name(path):
            if '%s-lun-1' % iqn in path:
                return mpdev_filepath
            return '/dev/mapper/donotdisconnect'

        self.flags(iscsi_use_multipath=True, group='libvirt')
        self.stubs.Set(os.path, 'exists', lambda x: True)

        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        libvirt_driver._get_multipath_device_name =\
            lambda x: _get_multipath_device_name(x)

        block_devs = ['/dev/disks/by-path/%s-iscsi-%s-lun-2' % (location, iqn)]
        self.stubs.Set(self.fake_conn, '_get_all_block_devices',
                       lambda: block_devs)

        vol = {'id': 1, 'name': name}
        connection_info = self.iscsi_connection(vol, location, iqn)
        connection_info['data']['device_path'] = mpdev_filepath

        libvirt_driver._get_multipath_iqn = lambda x: iqn

        iscsi_devs = ['1.2.3.4-iscsi-%s-lun-1' % iqn,
                      '%s-iscsi-%s-lun-1' % (location, iqn),
                      '%s-iscsi-%s-lun-2' % (location, iqn),
                      'pci-0000:00:00.0-ip-%s-iscsi-%s-lun-3' % (location,
                                                                 iqn)]
        libvirt_driver._get_iscsi_devices = lambda: iscsi_devs

        self.stubs.Set(libvirt_driver,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [[location, iqn]])

        # Set up disconnect volume mock expectations
        self.mox.StubOutWithMock(libvirt_driver, '_delete_device')
        self.mox.StubOutWithMock(libvirt_driver, '_rescan_multipath')
        libvirt_driver._rescan_multipath()
        libvirt_driver._delete_device('/dev/disk/by-path/%s' % iscsi_devs[0])
        libvirt_driver._delete_device('/dev/disk/by-path/%s' % iscsi_devs[1])
        libvirt_driver._rescan_multipath()

        # Ensure that the mpath devices are deleted
        self.mox.ReplayAll()
        libvirt_driver.disconnect_volume(connection_info, 'vde')

    def test_libvirt_kvm_volume_with_multipath_disconnected(self):
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        volumes = [{'name': self.name,
                    'location': self.location,
                    'iqn': self.iqn,
                    'mpdev_filepath': '/dev/mapper/disconnect'},
                   {'name': 'volume-00000002',
                    'location': '10.0.2.15:3260',
                    'iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                    'mpdev_filepath': '/dev/mapper/donotdisconnect'}]
        iscsi_devs = ['ip-%s-iscsi-%s-lun-1' % (volumes[0]['location'],
                                                volumes[0]['iqn']),
                      'ip-%s-iscsi-%s-lun-1' % (volumes[1]['location'],
                                                volumes[1]['iqn'])]

        def _get_multipath_device_name(path):
            if '%s-lun-1' % volumes[0]['iqn'] in path:
                return volumes[0]['mpdev_filepath']
            else:
                return volumes[1]['mpdev_filepath']

        def _get_multipath_iqn(mpdev):
            if volumes[0]['mpdev_filepath'] == mpdev:
                return volumes[0]['iqn']
            else:
                return volumes[1]['iqn']

        with contextlib.nested(
            mock.patch.object(os.path, 'exists', return_value=True),
            mock.patch.object(self.fake_conn, '_get_all_block_devices',
                              retrun_value=[volumes[1]['mpdev_filepath']]),
            mock.patch.object(libvirt_driver, '_get_multipath_device_name',
                              _get_multipath_device_name),
            mock.patch.object(libvirt_driver, '_get_multipath_iqn',
                              _get_multipath_iqn),
            mock.patch.object(libvirt_driver, '_get_iscsi_devices',
                              return_value=iscsi_devs),
            mock.patch.object(libvirt_driver,
                              '_get_target_portals_from_iscsiadm_output',
                              return_value=[[volumes[0]['location'],
                                             volumes[0]['iqn']],
                                            [volumes[1]['location'],
                                             volumes[1]['iqn']]]),
            mock.patch.object(libvirt_driver, '_disconnect_mpath')
        ) as (mock_exists, mock_devices, mock_device_name, mock_get_iqn,
              mock_iscsi_devices, mock_get_portals, mock_disconnect_mpath):
            vol = {'id': 1, 'name': volumes[0]['name']}
            connection_info = self.iscsi_connection(vol,
                                                    volumes[0]['location'],
                                                    volumes[0]['iqn'])
            connection_info['data']['device_path'] =\
                                            volumes[0]['mpdev_filepath']
            libvirt_driver.use_multipath = True
            libvirt_driver.disconnect_volume(connection_info, 'vde')
            # Ensure that the mpath device is disconnected.
            ips_iqns = []
            ips_iqns.append([volumes[0]['location'], volumes[0]['iqn']])
            mock_disconnect_mpath.assert_called_once_with(
                connection_info['data'], ips_iqns)

    def test_libvirt_kvm_volume_with_multipath_getmpdev(self):
        self.flags(iscsi_use_multipath=True, group='libvirt')
        self.stubs.Set(os.path, 'exists', lambda x: True)
        libvirt_driver = volume.LibvirtISCSIVolumeDriver(self.fake_conn)
        name0 = 'volume-00000000'
        iqn0 = 'iqn.2010-10.org.openstack:%s' % name0
        dev0 = '/dev/disk/by-path/ip-%s-iscsi-%s-lun-0' % (self.location, iqn0)
        dev = '/dev/disk/by-path/ip-%s-iscsi-%s-lun-1' % (self.location,
                                                          self.iqn)
        devs = [dev0, dev]
        self.stubs.Set(self.fake_conn, '_get_all_block_devices', lambda: devs)
        connection_info = self.iscsi_connection(self.vol, self.location,
                                                self.iqn)
        mpdev_filepath = '/dev/mapper/foo'
        libvirt_driver._get_multipath_device_name = lambda x: mpdev_filepath
        self.stubs.Set(libvirt_driver,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [['fake_portal1', 'fake_iqn1']])
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual(tree.find('./source').get('dev'), mpdev_filepath)
        libvirt_driver.disconnect_volume(connection_info, 'vde')

    def test_libvirt_kvm_iser_volume_with_multipath(self):
        self.flags(iser_use_multipath=True, group='libvirt')
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(time, 'sleep', lambda x: eventlet.sleep(0.1))
        devs = ['/dev/mapper/sda', '/dev/mapper/sdb']
        self.stubs.Set(self.fake_conn, '_get_all_block_devices', lambda: devs)
        libvirt_driver = volume.LibvirtISERVolumeDriver(self.fake_conn)
        name = 'volume-00000001'
        location = '10.0.2.15:3260'
        iqn = 'iqn.2010-10.org.iser.openstack:%s' % name
        vol = {'id': 1, 'name': name}
        connection_info = self.iser_connection(vol, location, iqn)
        mpdev_filepath = '/dev/mapper/foo'
        connection_info['data']['device_path'] = mpdev_filepath
        disk_info = {
            "bus": "virtio",
            "dev": "vde",
            "type": "disk",
            }
        libvirt_driver._get_multipath_device_name = lambda x: mpdev_filepath
        iscsi_devs = ['ip-%s-iscsi-%s-lun-0' % (location, iqn)]
        self.stubs.Set(libvirt_driver, '_get_iscsi_devices',
                       lambda: iscsi_devs)
        self.stubs.Set(libvirt_driver,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [[location, iqn]])
        self.stubs.Set(libvirt_driver, '_get_host_device',
                       lambda x: self.generate_device('iser', 0, False))

        libvirt_driver.connect_volume(connection_info, disk_info)
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        self.assertEqual(tree.find('./source').get('dev'), mpdev_filepath)
        libvirt_driver._get_multipath_iqn = lambda x: iqn
        libvirt_driver.disconnect_volume(connection_info, 'vde')
        expected_multipath_cmd = ('multipath', '-f', 'foo')
        self.assertIn(expected_multipath_cmd, self.executes)

    def test_libvirt_kvm_iser_volume_with_multipath_getmpdev(self):
        self.flags(iser_use_multipath=True, group='libvirt')
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(time, 'sleep', lambda x: eventlet.sleep(0.1))
        libvirt_driver = volume.LibvirtISERVolumeDriver(self.fake_conn)
        name0 = 'volume-00000000'
        location0 = '10.0.2.15:3260'
        iqn0 = 'iqn.2010-10.org.iser.openstack:%s' % name0
        dev0 = '/dev/disk/by-path/ip-%s-iscsi-%s-lun-0' % (location0, iqn0)
        name = 'volume-00000001'
        location = '10.0.2.15:3260'
        iqn = 'iqn.2010-10.org.iser.openstack:%s' % name
        vol = {'id': 1, 'name': name}
        dev = '/dev/disk/by-path/ip-%s-iscsi-%s-lun-1' % (location, iqn)
        devs = [dev0, dev]
        self.stubs.Set(self.fake_conn, '_get_all_block_devices', lambda: devs)
        self.stubs.Set(libvirt_driver, '_get_iscsi_devices', lambda: [])
        self.stubs.Set(libvirt_driver, '_get_host_device',
                       lambda x: self.generate_device('iser', 1, False))
        connection_info = self.iser_connection(vol, location, iqn)
        mpdev_filepath = '/dev/mapper/foo'
        disk_info = {
            "bus": "virtio",
            "dev": "vde",
            "type": "disk",
            }
        libvirt_driver._get_multipath_device_name = lambda x: mpdev_filepath
        self.stubs.Set(libvirt_driver,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [['fake_portal1', 'fake_iqn1']])
        libvirt_driver.connect_volume(connection_info, disk_info)
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        self.assertEqual(tree.find('./source').get('dev'), mpdev_filepath)
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

    def aoe_connection(self, shelf, lun):
        aoedev = 'e%s.%s' % (shelf, lun)
        aoedevpath = '/dev/etherd/%s' % (aoedev)
        return {
                'driver_volume_type': 'aoe',
                'data': {
                    'target_shelf': shelf,
                    'target_lun': lun,
                    'device_path': aoedevpath
                }
        }

    @mock.patch('os.path.exists', return_value=True)
    def test_libvirt_aoe_driver(self, exists):
        libvirt_driver = volume.LibvirtAOEVolumeDriver(self.fake_conn)
        shelf = '100'
        lun = '1'
        connection_info = self.aoe_connection(shelf, lun)
        aoedev = 'e%s.%s' % (shelf, lun)
        aoedevpath = '/dev/etherd/%s' % (aoedev)
        libvirt_driver.connect_volume(connection_info, self.disk_info)
        exists.assert_called_with(aoedevpath)
        libvirt_driver.disconnect_volume(connection_info, "vde")
        self.assertEqual(aoedevpath, connection_info['data']['device_path'])
        expected_commands = [('aoe-revalidate', aoedev)]
        self.assertEqual(expected_commands, self.executes)

    def test_libvirt_aoe_driver_get_config(self):
        libvirt_driver = volume.LibvirtAOEVolumeDriver(self.fake_conn)
        shelf = '100'
        lun = '1'
        connection_info = self.aoe_connection(shelf, lun)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        aoedevpath = '/dev/etherd/e%s.%s' % (shelf, lun)
        self.assertEqual('block', tree.get('type'))
        self.assertEqual(aoedevpath, tree.find('./source').get('dev'))
        libvirt_driver.disconnect_volume(connection_info, "vde")

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

    def fibrechan_connection(self, volume, location, wwn):
        return {
                'driver_volume_type': 'fibrechan',
                'data': {
                    'volume_id': volume['id'],
                    'target_portal': location,
                    'target_wwn': wwn,
                    'target_lun': 1,
                }
        }

    def test_libvirt_fibrechan_driver(self):
        self.stubs.Set(libvirt_utils, 'get_fc_hbas',
                       fake_libvirt_utils.get_fc_hbas)
        self.stubs.Set(libvirt_utils, 'get_fc_hbas_info',
                       fake_libvirt_utils.get_fc_hbas_info)
        # NOTE(vish) exists is to make driver assume connecting worked
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(os.path, 'realpath', lambda x: '/dev/sdb')
        libvirt_driver = volume.LibvirtFibreChannelVolumeDriver(self.fake_conn)
        multipath_devname = '/dev/md-1'
        devices = {"device": multipath_devname,
                   "id": "1234567890",
                   "devices": [{'device': '/dev/sdb',
                                'address': '1:0:0:1',
                                'host': 1, 'channel': 0,
                                'id': 0, 'lun': 1}]}
        self.stubs.Set(linuxscsi, 'find_multipath_device', lambda x: devices)
        self.stubs.Set(linuxscsi, 'remove_device', lambda x: None)
        # Should work for string, unicode, and list
        wwns = ['1234567890123456', unicode('1234567890123456'),
                ['1234567890123456', '1234567890123457']]
        for wwn in wwns:
            connection_info = self.fibrechan_connection(self.vol,
                                                        self.location, wwn)
            mount_device = "vde"
            libvirt_driver.connect_volume(connection_info, self.disk_info)

            # Test the scenario where multipath_id is returned
            libvirt_driver.disconnect_volume(connection_info, mount_device)
            self.assertEqual(multipath_devname,
                             connection_info['data']['device_path'])
            expected_commands = []
            self.assertEqual(expected_commands, self.executes)
            # Test the scenario where multipath_id is not returned
            connection_info["data"]["devices"] = devices["devices"]
            del connection_info["data"]["multipath_id"]
            libvirt_driver.disconnect_volume(connection_info, mount_device)
            expected_commands = []
            self.assertEqual(expected_commands, self.executes)

        # Should not work for anything other than string, unicode, and list
        connection_info = self.fibrechan_connection(self.vol,
                                                    self.location, 123)
        self.assertRaises(exception.NovaException,
                          libvirt_driver.connect_volume,
                          connection_info, self.disk_info)

        self.stubs.Set(libvirt_utils, 'get_fc_hbas', lambda: [])
        self.stubs.Set(libvirt_utils, 'get_fc_hbas_info', lambda: [])
        self.assertRaises(exception.NovaException,
                          libvirt_driver.connect_volume,
                          connection_info, self.disk_info)

    def test_libvirt_fibrechan_driver_get_config(self):
        libvirt_driver = volume.LibvirtFibreChannelVolumeDriver(self.fake_conn)
        connection_info = self.fibrechan_connection(self.vol,
                                                    self.location, 123)
        connection_info['data']['device_path'] = ("/sys/devices/pci0000:00"
            "/0000:00:03.0/0000:05:00.3/host2/fc_host/host2")
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('block', tree.get('type'))
        self.assertEqual(connection_info['data']['device_path'],
                         tree.find('./source').get('dev'))

    def test_libvirt_fibrechan_getpci_num(self):
        libvirt_driver = volume.LibvirtFibreChannelVolumeDriver(self.fake_conn)
        hba = {'device_path': "/sys/devices/pci0000:00/0000:00:03.0"
                                  "/0000:05:00.3/host2/fc_host/host2"}
        pci_num = libvirt_driver._get_pci_num(hba)
        self.assertEqual("0000:05:00.3", pci_num)

        hba = {'device_path': "/sys/devices/pci0000:00/0000:00:03.0"
                              "/0000:05:00.3/0000:06:00.6/host2/fc_host/host2"}
        pci_num = libvirt_driver._get_pci_num(hba)
        self.assertEqual("0000:06:00.6", pci_num)

    def test_libvirt_scality_driver(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        TEST_MOUNT = os.path.join(tempdir, 'fake_mount')
        TEST_CONFIG = os.path.join(tempdir, 'fake_config')
        TEST_VOLDIR = 'volumes'
        TEST_VOLNAME = 'volume_name'
        TEST_CONN_INFO = {
            'data': {
                'sofs_path': os.path.join(TEST_VOLDIR, TEST_VOLNAME)
            }
        }
        TEST_VOLPATH = os.path.join(TEST_MOUNT,
                                    TEST_VOLDIR,
                                    TEST_VOLNAME)
        open(TEST_CONFIG, "w+").close()
        os.makedirs(os.path.join(TEST_MOUNT, 'sys'))

        def _access_wrapper(path, flags):
            if path == '/sbin/mount.sofs':
                return True
            else:
                return os.access(path, flags)

        self.stubs.Set(os, 'access', _access_wrapper)
        self.flags(scality_sofs_config=TEST_CONFIG,
                   scality_sofs_mount_point=TEST_MOUNT,
                   group='libvirt')
        driver = volume.LibvirtScalityVolumeDriver(self.fake_conn)
        driver.connect_volume(TEST_CONN_INFO, self.disk_info)

        device_path = os.path.join(TEST_MOUNT,
                                   TEST_CONN_INFO['data']['sofs_path'])
        self.assertEqual(device_path,
                         TEST_CONN_INFO['data']['device_path'])

        conf = driver.get_config(TEST_CONN_INFO, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, TEST_VOLPATH)

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
                                    'name': self.name}}
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

    def test_libvirt_gpfs_driver_get_config(self):
        libvirt_driver = volume.LibvirtGPFSVolumeDriver(self.fake_conn)
        connection_info = {
            'driver_volume_type': 'gpfs',
            'data': {
                'device_path': '/gpfs/foo',
            },
            'serial': 'fake_serial',
        }
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual('file', tree.get('type'))
        self.assertEqual('fake_serial', tree.find('./serial').text)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'mount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=False)
    def test_libvirt_quobyte_driver_mount(self,
                                          mock_is_mounted,
                                          mock_mount_volume,
                                          mock_validate_volume
                                          ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()

        self._assertFileTypeEquals(tree, file_path)

        mock_mount_volume.assert_called_once_with(quobyte_volume,
                                                  export_mnt_base,
                                                  mock.ANY)
        mock_validate_volume.assert_called_with(export_mnt_base)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'umount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=True)
    def test_libvirt_quobyte_driver_umount(self, mock_is_mounted,
                                           mock_umount_volume,
                                           mock_validate_volume):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}
        libvirt_driver.connect_volume(connection_info, self.disk_info)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)

        libvirt_driver.disconnect_volume(connection_info, "vde")

        mock_validate_volume.assert_called_once_with(export_mnt_base)
        mock_umount_volume.assert_called_once_with(export_mnt_base)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'umount_volume')
    def test_libvirt_quobyte_driver_already_mounted(self,
                                                    mock_umount_volume,
                                                    mock_validate_volume
                                                    ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        file_path = os.path.join(export_mnt_base, self.name)

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        libvirt_driver.connect_volume(connection_info, self.disk_info)

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self._assertFileTypeEquals(tree, file_path)
        libvirt_driver.disconnect_volume(connection_info, "vde")

        expected_commands = [
            ('findmnt', '--target', export_mnt_base,
             '--source', "quobyte@" + quobyte_volume),
            ('findmnt', '--target', export_mnt_base,
             '--source', "quobyte@" + quobyte_volume),
            ]
        self.assertEqual(expected_commands, self.executes)

        mock_umount_volume.assert_called_once_with(export_mnt_base)
        mock_validate_volume.assert_called_once_with(export_mnt_base)

    @mock.patch.object(quobyte, 'validate_volume')
    @mock.patch.object(quobyte, 'mount_volume')
    @mock.patch.object(libvirt_utils, 'is_mounted', return_value=False)
    def test_libvirt_quobyte_driver_qcow2(self, mock_is_mounted,
                                          mock_mount_volume,
                                          mock_validate_volume
                                          ):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')
        libvirt_driver = volume.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        name = 'volume-00001'
        image_format = 'qcow2'
        quobyte_volume = '192.168.1.1/volume-00001'

        connection_info = {'data': {'export': export_string,
                                    'name': name,
                                    'format': image_format}}

        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        libvirt_driver.connect_volume(connection_info, self.disk_info)
        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertEqual(tree.get('type'), 'file')
        self.assertEqual(tree.find('./driver').get('type'), 'qcow2')

        (mock_mount_volume.
         assert_called_once_with('192.168.1.1/volume-00001',
                                 export_mnt_base,
                                 mock.ANY))
        mock_validate_volume.assert_called_with(export_mnt_base)

        libvirt_driver.disconnect_volume(connection_info, "vde")

    def test_libvirt_quobyte_driver_mount_non_quobyte_volume(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'

        connection_info = {'data': {'export': export_string,
                                    'name': self.name}}

        def exe_side_effect(*cmd, **kwargs):
            if cmd == mock.ANY:
                raise exception.NovaException()

        with mock.patch.object(quobyte,
                               'validate_volume') as mock_execute:
            mock_execute.side_effect = exe_side_effect
            self.assertRaises(exception.NovaException,
                              libvirt_driver.connect_volume,
                              connection_info,
                              self.disk_info)

    def test_libvirt_quobyte_driver_normalize_url_with_protocol(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = 'quobyte://192.168.1.1/volume-00001'
        self.assertEqual(libvirt_driver._normalize_url(export_string),
                         "192.168.1.1/volume-00001")

    def test_libvirt_quobyte_driver_normalize_url_without_protocol(self):
        mnt_base = '/mnt'
        self.flags(quobyte_mount_point_base=mnt_base, group='libvirt')

        libvirt_driver = volume.LibvirtQuobyteVolumeDriver(self.fake_conn)
        export_string = '192.168.1.1/volume-00001'
        self.assertEqual(libvirt_driver._normalize_url(export_string),
                         "192.168.1.1/volume-00001")
