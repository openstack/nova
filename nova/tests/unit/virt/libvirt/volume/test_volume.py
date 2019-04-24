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

import ddt
import mock

from nova import exception
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt import fake
from nova.virt.libvirt import driver
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


class LibvirtBaseVolumeDriverSubclassSignatureTestCase(
        test.SubclassSignatureTestCase):
    def _get_base_class(self):
        # We do this because it has the side-effect of loading all the
        # volume drivers
        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        driver.LibvirtDriver(fake.FakeVirtAPI(), False)

        return volume.LibvirtBaseVolumeDriver


class LibvirtVolumeBaseTestCase(test.NoDBTestCase):
    """Contains common setup and helper methods for libvirt volume tests."""

    def setUp(self):
        super(LibvirtVolumeBaseTestCase, self).setUp()
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stub_out('nova.utils.execute', fake_execute)

        self.useFixture(fakelibvirt.FakeLibvirtFixture())

        self.fake_host = host.Host("qemu:///system")

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
        self.assertEqual('file', tree.get('type'))
        self.assertEqual(file_path, tree.find('./source').get('file'))


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


@ddt.ddt
class LibvirtVolumeTestCase(LibvirtISCSIVolumeBaseTestCase):

    def _assertDiskInfoEquals(self, tree, disk_info):
        self.assertEqual(disk_info['type'], tree.get('device'))
        self.assertEqual(disk_info['bus'], tree.find('./target').get('bus'))
        self.assertEqual(disk_info['dev'], tree.find('./target').get('dev'))

    def _test_libvirt_volume_driver_disk_info(self):
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
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
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
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
        self.assertIsNone(tree.find("driver[@discard]"))

    def test_libvirt_volume_driver_blockio(self):
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
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
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
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
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
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

    @mock.patch('nova.virt.libvirt.host.Host.has_min_version')
    def test_libvirt_volume_driver_discard_true(self, mock_has_min_version):
        # Check the discard attrib is present in driver section
        mock_has_min_version.return_value = True
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
        connection_info = {
            'driver_volume_type': 'fake',
            'data': {
                'device_path': '/foo',
                'discard': True,
            },
            'serial': 'fake_serial',
        }

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        driver_node = tree.find("driver[@discard]")
        self.assertIsNotNone(driver_node)
        self.assertEqual('unmap', driver_node.attrib['discard'])

    def test_libvirt_volume_driver_discard_false(self):
        # Check the discard attrib is not present in driver section
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
        connection_info = {
            'driver_volume_type': 'fake',
            'data': {
                'device_path': '/foo',
                'discard': False,
            },
            'serial': 'fake_serial',
        }

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()
        self.assertIsNone(tree.find("driver[@discard]"))

    @ddt.data(5, None)
    def test_libvirt_volume_driver_address_tag_scsi_unit(self, disk_unit):
        # The address tag should be set if bus is scsi and unit is set.
        # Otherwise, it should not be set at all.
        libvirt_driver = volume.LibvirtVolumeDriver(self.fake_host)
        connection_info = {'data': {'device_path': '/foo'}}
        disk_info = {'bus': 'scsi', 'dev': 'sda', 'type': 'disk'}
        if disk_unit:
            disk_info['unit'] = disk_unit
        conf = libvirt_driver.get_config(connection_info, disk_info)
        tree = conf.format_dom()
        address = tree.find('address')
        if disk_unit:
            self.assertEqual('0', address.attrib['controller'])
            self.assertEqual(str(disk_unit), address.attrib['unit'])
        else:
            self.assertIsNone(address)
