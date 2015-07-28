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

import mock
from os_brick.initiator import connector

from nova import exception
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova import utils
from nova.virt.libvirt import host
from nova.virt.libvirt.volume import volume

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


class LibvirtISCSIVolumeBaseTestCase(LibvirtVolumeBaseTestCase):
    """Contains common setup and helper methods for iSCSI volume tests."""

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


class LibvirtVolumeTestCase(LibvirtISCSIVolumeBaseTestCase):

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
