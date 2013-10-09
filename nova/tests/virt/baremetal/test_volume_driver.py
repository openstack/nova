# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""Tests for baremetal volume driver."""

from oslo.config import cfg

from nova import exception
from nova import test
from nova.virt.baremetal import volume_driver
from nova.virt import fake
from nova.virt.libvirt import volume as libvirt_volume

CONF = cfg.CONF

SHOW_OUTPUT = """Target 1: iqn.2010-10.org.openstack:volume-00000001
    System information:
        Driver: iscsi
        State: ready
    I_T nexus information:
        I_T nexus: 8
            Initiator: iqn.1993-08.org.debian:01:7780c6a16b4
            Connection: 0
                IP Address: 172.17.12.10
    LUN information:
        LUN: 0
            Type: controller
            SCSI ID: IET     00010000
            SCSI SN: beaf10
            Size: 0 MB, Block size: 1
            Online: Yes
            Removable media: No
            Readonly: No
            Backing store type: null
            Backing store path: None
            Backing store flags:
        LUN: 1
            Type: disk
            SCSI ID: IET     00010001
            SCSI SN: beaf11
            Size: 1074 MB, Block size: 512
            Online: Yes
            Removable media: No
            Readonly: No
            Backing store type: rdwr
            Backing store path: /dev/nova-volumes/volume-00000001
            Backing store flags:
    Account information:
    ACL information:
        ALL
Target 2: iqn.2010-10.org.openstack:volume-00000002
    System information:
        Driver: iscsi
        State: ready
    I_T nexus information:
    LUN information:
        LUN: 0
            Type: controller
            SCSI ID: IET     00020000
            SCSI SN: beaf20
            Size: 0 MB, Block size: 1
            Online: Yes
            Removable media: No
            Readonly: No
            Backing store type: null
            Backing store path: None
            Backing store flags:
        LUN: 1
            Type: disk
            SCSI ID: IET     00020001
            SCSI SN: beaf21
            Size: 2147 MB, Block size: 512
            Online: Yes
            Removable media: No
            Readonly: No
            Backing store type: rdwr
            Backing store path: /dev/nova-volumes/volume-00000002
            Backing store flags:
    Account information:
    ACL information:
        ALL
Target 1000001: iqn.2010-10.org.openstack.baremetal:1000001-dev.vdc
    System information:
        Driver: iscsi
        State: ready
    I_T nexus information:
    LUN information:
        LUN: 0
            Type: controller
            SCSI ID: IET     f42410000
            SCSI SN: beaf10000010
            Size: 0 MB, Block size: 1
            Online: Yes
            Removable media: No
            Readonly: No
            Backing store type: null
            Backing store path: None
            Backing store flags:
        LUN: 1
            Type: disk
            SCSI ID: IET     f42410001
            SCSI SN: beaf10000011
            Size: 1074 MB, Block size: 512
            Online: Yes
            Removable media: No
            Readonly: No
            Backing store type: rdwr
            Backing store path: /dev/disk/by-path/ip-172.17.12.10:3260-iscsi-\
iqn.2010-10.org.openstack:volume-00000001-lun-1
            Backing store flags:
    Account information:
    ACL information:
        ALL
"""


def fake_show_tgtadm():
    return SHOW_OUTPUT


class BareMetalVolumeTestCase(test.NoDBTestCase):

    def setUp(self):
        super(BareMetalVolumeTestCase, self).setUp()
        self.stubs.Set(volume_driver, '_show_tgtadm', fake_show_tgtadm)

    def test_list_backingstore_path(self):
        l = volume_driver._list_backingstore_path()
        self.assertEqual(len(l), 3)
        self.assertIn('/dev/nova-volumes/volume-00000001', l)
        self.assertIn('/dev/nova-volumes/volume-00000002', l)
        self.assertIn('/dev/disk/by-path/ip-172.17.12.10:3260-iscsi-'
                      'iqn.2010-10.org.openstack:volume-00000001-lun-1', l)

    def test_get_next_tid(self):
        tid = volume_driver._get_next_tid()
        self.assertEqual(1000002, tid)

    def test_find_tid_found(self):
        tid = volume_driver._find_tid(
                'iqn.2010-10.org.openstack.baremetal:1000001-dev.vdc')
        self.assertEqual(1000001, tid)

    def test_find_tid_not_found(self):
        tid = volume_driver._find_tid(
                'iqn.2010-10.org.openstack.baremetal:1000002-dev.vdc')
        self.assertIsNone(tid)

    def test_get_iqn(self):
        self.flags(iscsi_iqn_prefix='iqn.2012-12.a.b', group='baremetal')
        iqn = volume_driver._get_iqn('instname', '/dev/vdx')
        self.assertEqual('iqn.2012-12.a.b:instname-dev-vdx', iqn)


class FakeConf(object):
    def __init__(self, source_path):
        self.source_path = source_path


class BareMetalLibVirtVolumeDriverTestCase(test.TestCase):

    def setUp(self):
        super(BareMetalLibVirtVolumeDriverTestCase, self).setUp()
        self.flags(volume_drivers=[
                'fake=nova.virt.libvirt.volume.LibvirtFakeVolumeDriver',
                'fake2=nova.virt.libvirt.volume.LibvirtFakeVolumeDriver',
                ], group='libvirt')
        self.driver = volume_driver.LibvirtVolumeDriver(fake.FakeVirtAPI())
        self.disk_info = {
            'dev': 'vdc',
            'bus': 'baremetal',
            'type': 'baremetal',
            }
        self.connection_info = {'driver_volume_type': 'fake'}
        self.mount_point = '/dev/vdc'
        self.mount_device = 'vdc'
        self.source_path = '/dev/sdx'
        self.instance = {'uuid': '12345678-1234-1234-1234-123467890123456',
                         'name': 'instance-00000001'}
        self.fixed_ips = [{'address': '10.2.3.4'},
                          {'address': '172.16.17.18'},
                         ]
        self.iqn = 'iqn.fake:instance-00000001-dev-vdc'
        self.tid = 100

    def test_init_loads_volume_drivers(self):
        self.assertEqual(type(self.driver.volume_drivers['fake']),
                         libvirt_volume.LibvirtFakeVolumeDriver)
        self.assertEqual(type(self.driver.volume_drivers['fake2']),
                         libvirt_volume.LibvirtFakeVolumeDriver)
        self.assertEqual(len(self.driver.volume_drivers), 2)

    def test_fake_connect_volume(self):
        """Check connect_volume returns without exceptions."""
        self.driver._volume_driver_method('connect_volume',
                                          self.connection_info,
                                          self.disk_info)

    def test_volume_driver_method_ok(self):
        fake_driver = self.driver.volume_drivers['fake']
        self.mox.StubOutWithMock(fake_driver, 'connect_volume')
        fake_driver.connect_volume(self.connection_info, self.disk_info)
        self.mox.ReplayAll()
        self.driver._volume_driver_method('connect_volume',
                                          self.connection_info,
                                          self.disk_info)

    def test_volume_driver_method_driver_type_not_found(self):
        self.connection_info['driver_volume_type'] = 'qwerty'
        self.assertRaises(exception.VolumeDriverNotFound,
                          self.driver._volume_driver_method,
                          'connect_volume',
                          self.connection_info,
                          self.disk_info)

    def test_connect_volume(self):
        self.mox.StubOutWithMock(self.driver, '_volume_driver_method')
        self.driver._volume_driver_method('connect_volume',
                                          self.connection_info,
                                          self.disk_info)
        self.mox.ReplayAll()
        self.driver._connect_volume(self.connection_info, self.disk_info)

    def test_disconnect_volume(self):
        self.mox.StubOutWithMock(self.driver, '_volume_driver_method')
        self.driver._volume_driver_method('disconnect_volume',
                                          self.connection_info,
                                          self.mount_device)
        self.mox.ReplayAll()
        self.driver._disconnect_volume(self.connection_info, self.mount_device)

    def test_publish_iscsi(self):
        self.mox.StubOutWithMock(volume_driver, '_get_iqn')
        self.mox.StubOutWithMock(volume_driver, '_get_next_tid')
        self.mox.StubOutWithMock(volume_driver, '_create_iscsi_export_tgtadm')
        self.mox.StubOutWithMock(volume_driver, '_allow_iscsi_tgtadm')
        volume_driver._get_iqn(self.instance['name'], self.mount_point).\
                AndReturn(self.iqn)
        volume_driver._get_next_tid().AndReturn(self.tid)
        volume_driver._create_iscsi_export_tgtadm(self.source_path,
                                                  self.tid,
                                                  self.iqn)
        volume_driver._allow_iscsi_tgtadm(self.tid,
                                          self.fixed_ips[0]['address'])
        volume_driver._allow_iscsi_tgtadm(self.tid,
                                          self.fixed_ips[1]['address'])
        self.mox.ReplayAll()
        self.driver._publish_iscsi(self.instance,
                                   self.mount_point,
                                   self.fixed_ips,
                                   self.source_path)

    def test_depublish_iscsi_ok(self):
        self.mox.StubOutWithMock(volume_driver, '_get_iqn')
        self.mox.StubOutWithMock(volume_driver, '_find_tid')
        self.mox.StubOutWithMock(volume_driver, '_delete_iscsi_export_tgtadm')
        volume_driver._get_iqn(self.instance['name'], self.mount_point).\
                AndReturn(self.iqn)
        volume_driver._find_tid(self.iqn).AndReturn(self.tid)
        volume_driver._delete_iscsi_export_tgtadm(self.tid)
        self.mox.ReplayAll()
        self.driver._depublish_iscsi(self.instance, self.mount_point)

    def test_depublish_iscsi_do_nothing_if_tid_is_not_found(self):
        self.mox.StubOutWithMock(volume_driver, '_get_iqn')
        self.mox.StubOutWithMock(volume_driver, '_find_tid')
        volume_driver._get_iqn(self.instance['name'], self.mount_point).\
                AndReturn(self.iqn)
        volume_driver._find_tid(self.iqn).AndReturn(None)
        self.mox.ReplayAll()
        self.driver._depublish_iscsi(self.instance, self.mount_point)

    def test_attach_volume(self):
        self.mox.StubOutWithMock(volume_driver, '_get_fixed_ips')
        self.mox.StubOutWithMock(self.driver, '_connect_volume')
        self.mox.StubOutWithMock(self.driver, '_publish_iscsi')
        volume_driver._get_fixed_ips(self.instance).AndReturn(self.fixed_ips)
        self.driver._connect_volume(self.connection_info, self.disk_info).\
                AndReturn(FakeConf(self.source_path))
        self.driver._publish_iscsi(self.instance, self.mount_point,
                                   self.fixed_ips, self.source_path)
        self.mox.ReplayAll()
        self.driver.attach_volume(self.connection_info,
                                  self.instance,
                                  self.mount_point)

    def test_detach_volume(self):
        self.mox.StubOutWithMock(volume_driver, '_get_iqn')
        self.mox.StubOutWithMock(volume_driver, '_find_tid')
        self.mox.StubOutWithMock(volume_driver, '_delete_iscsi_export_tgtadm')
        self.mox.StubOutWithMock(self.driver, '_disconnect_volume')
        volume_driver._get_iqn(self.instance['name'], self.mount_point).\
                AndReturn(self.iqn)
        volume_driver._find_tid(self.iqn).AndReturn(self.tid)
        volume_driver._delete_iscsi_export_tgtadm(self.tid)
        self.driver._disconnect_volume(self.connection_info,
                                       self.mount_device)
        self.mox.ReplayAll()
        self.driver.detach_volume(self.connection_info,
                                  self.instance,
                                  self.mount_point)
