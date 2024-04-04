#    Copyright 2010 OpenStack Foundation
#    Copyright 2012 University Of Minho
#    Copyright 2014-2015 Red Hat, Inc
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

from unittest import mock

from oslo_service import fixture as service_fixture
from oslo_utils import encodeutils

from nova import context
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host


class GuestTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GuestTestCase, self).setUp()

        self.useFixture(nova_fixtures.LibvirtFixture())
        self.host = host.Host("qemu:///system")
        self.context = context.get_admin_context()

        self.domain = mock.Mock(spec=fakelibvirt.virDomain)
        self.guest = libvirt_guest.Guest(self.domain)

        # Make RetryDecorator not actually sleep on retries
        self.useFixture(service_fixture.SleepFixture())

    def test_repr(self):
        self.domain.ID.return_value = 99
        self.domain.UUIDString.return_value = "UUID"
        self.domain.name.return_value = "foo"
        self.assertEqual("<Guest 99 foo UUID>", repr(self.guest))

    @mock.patch.object(fakelibvirt.Connection, 'defineXML')
    def test_create(self, mock_define):
        libvirt_guest.Guest.create("xml", self.host)
        mock_define.assert_called_once_with("xml")

    @mock.patch.object(libvirt_guest.LOG, 'error')
    @mock.patch.object(fakelibvirt.Connection, 'defineXML')
    def test_create_exception(self, mock_define, mock_log):
        fake_xml = '<test>this is a test</test>'
        mock_define.side_effect = test.TestingException
        self.assertRaises(test.TestingException,
                          libvirt_guest.Guest.create,
                          fake_xml, self.host)
        # ensure the XML is logged
        self.assertIn(fake_xml, str(mock_log.call_args[0]))

    def test_launch(self):
        self.guest.launch()
        self.domain.createWithFlags.assert_called_once_with(0)

    def test_launch_and_pause(self):
        self.guest.launch(pause=True)
        self.domain.createWithFlags.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_START_PAUSED)

    @mock.patch.object(libvirt_guest.LOG, 'exception')
    @mock.patch.object(encodeutils, 'safe_decode')
    def test_launch_exception(self, mock_safe_decode, mock_log):
        fake_xml = '<test>this is a test</test>'
        self.domain.createWithFlags.side_effect = test.TestingException
        mock_safe_decode.return_value = fake_xml
        self.assertRaises(test.TestingException, self.guest.launch)
        self.assertEqual(1, mock_safe_decode.called)
        # ensure the XML is logged
        self.assertIn(fake_xml, str(mock_log.call_args[0]))

    def test_shutdown(self):
        self.domain.shutdown = mock.MagicMock()
        self.guest.shutdown()
        self.domain.shutdown.assert_called_once_with()

    def test_get_interfaces(self):
        self.domain.XMLDesc.return_value = """<domain>
  <devices>
    <interface type="network">
      <target dev="vnet0"/>
    </interface>
    <interface type="network">
      <target dev="vnet1"/>
    </interface>
  </devices>
</domain>"""
        self.assertEqual(["vnet0", "vnet1"], self.guest.get_interfaces())

    def test_get_interfaces_exception(self):
        self.domain.XMLDesc.return_value = "<bad xml>"
        self.assertEqual([], self.guest.get_interfaces())

    def test_poweroff(self):
        self.guest.poweroff()
        self.domain.destroy.assert_called_once_with()

    def test_resume(self):
        self.guest.resume()
        self.domain.resume.assert_called_once_with()

    @mock.patch('time.time', return_value=1234567890.125)
    def test_time_sync_no_errors(self, time_mock):
        self.domain.setTime.side_effect = fakelibvirt.libvirtError('error')
        self.guest.sync_guest_time()
        self.domain.setTime.assert_called_once_with(time={
                                                    'nseconds': 125000000,
                                                    'seconds': 1234567890})

    def test_get_vcpus_info(self):
        self.domain.vcpus.return_value = ([(0, 1, int(10290000000), 2)],
                                     [(True, True)])
        vcpus = list(self.guest.get_vcpus_info())
        self.assertEqual(0, vcpus[0].id)
        self.assertEqual(2, vcpus[0].cpu)
        self.assertEqual(1, vcpus[0].state)
        self.assertEqual(int(10290000000), vcpus[0].time)

    def test_delete_configuration(self):
        self.guest.delete_configuration()
        self.domain.undefineFlags.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE |
            fakelibvirt.VIR_DOMAIN_UNDEFINE_NVRAM)

    def test_delete_configuration_exception(self):
        self.domain.undefineFlags.side_effect = fakelibvirt.libvirtError(
            'oops')
        self.domain.ID.return_value = 1
        self.guest.delete_configuration()
        self.domain.undefine.assert_called_once_with()

    def test_attach_device(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.attach_device(conf)
        self.domain.attachDeviceFlags.assert_called_once_with(
            "</xml>", flags=0)

    def test_attach_device_persistent(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.attach_device(conf, persistent=True)
        self.domain.attachDeviceFlags.assert_called_once_with(
            "</xml>", flags=fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG)

    def test_attach_device_live(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.attach_device(conf, live=True)
        self.domain.attachDeviceFlags.assert_called_once_with(
            "</xml>", flags=fakelibvirt.VIR_DOMAIN_AFFECT_LIVE)

    def test_attach_device_persistent_live(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.attach_device(conf, persistent=True, live=True)
        self.domain.attachDeviceFlags.assert_called_once_with(
            "</xml>", flags=(fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG |
                             fakelibvirt.VIR_DOMAIN_AFFECT_LIVE))

    def test_detach_device(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.detach_device(conf)
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=0)

    def test_detach_device_persistent(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.detach_device(conf, persistent=True)
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG)

    def test_detach_device_live(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.detach_device(conf, live=True)
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=fakelibvirt.VIR_DOMAIN_AFFECT_LIVE)

    def test_detach_device_persistent_live(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.guest.detach_device(conf, persistent=True, live=True)
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=(fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG |
                             fakelibvirt.VIR_DOMAIN_AFFECT_LIVE))

    def test_get_xml_desc(self):
        self.guest.get_xml_desc()
        self.domain.XMLDesc.assert_called_once_with(flags=0)

    def test_get_xml_desc_dump_inactive(self):
        self.guest.get_xml_desc(dump_inactive=True)
        self.domain.XMLDesc.assert_called_once_with(
            flags=fakelibvirt.VIR_DOMAIN_XML_INACTIVE)

    def test_get_xml_desc_dump_sensitive(self):
        self.guest.get_xml_desc(dump_sensitive=True)
        self.domain.XMLDesc.assert_called_once_with(
            flags=fakelibvirt.VIR_DOMAIN_XML_SECURE)

    def test_get_xml_desc_dump_inactive_dump_sensitive(self):
        self.guest.get_xml_desc(dump_inactive=True, dump_sensitive=True)
        self.domain.XMLDesc.assert_called_once_with(
            flags=(fakelibvirt.VIR_DOMAIN_XML_INACTIVE |
                   fakelibvirt.VIR_DOMAIN_XML_SECURE))

    def test_get_xml_desc_dump_migratable(self):
        self.guest.get_xml_desc(dump_migratable=True)
        self.domain.XMLDesc.assert_called_once_with(
            flags=fakelibvirt.VIR_DOMAIN_XML_MIGRATABLE)

    def test_has_persistent_configuration(self):
        self.assertTrue(
            self.guest.has_persistent_configuration())
        self.domain.isPersistent.assert_called_once_with()

    def test_save_memory_state(self):
        self.guest.save_memory_state()
        self.domain.managedSave.assert_called_once_with(0)

    def test_get_block_device(self):
        disk = 'vda'
        gblock = self.guest.get_block_device(disk)
        self.assertEqual(disk, gblock._disk)
        self.assertEqual(self.guest, gblock._guest)

    def test_set_user_password(self):
        self.guest.set_user_password("foo", "123")
        self.domain.setUserPassword.assert_called_once_with("foo", "123", 0)

    def test_get_config(self):
        xml = "<domain type='kvm'><name>fake</name></domain>"
        self.domain.XMLDesc.return_value = xml
        result = self.guest.get_config()
        self.assertIsInstance(result, vconfig.LibvirtConfigGuest)
        self.assertEqual('kvm', result.virt_type)
        self.assertEqual('fake', result.name)

    def test_get_device_by_alias(self):
        xml = """
<domain type='qemu'>
  <name>QEMUGuest1</name>
  <uuid>c7a5fdbd-edaf-9455-926a-d65c16db1809</uuid>
  <memory unit='KiB'>219136</memory>
  <currentMemory unit='KiB'>219136</currentMemory>
  <vcpu placement='static'>1</vcpu>
  <os>
    <type arch='i686' machine='pc'>hvm</type>
    <boot dev='hd'/>
  </os>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>destroy</on_crash>
  <devices>
    <emulator>/usr/bin/qemu</emulator>
    <disk type='block' device='disk'>
      <alias name="qemu-disk1"/>
      <driver name='qemu' type='raw'/>
      <source dev='/dev/HostVG/QEMUGuest2'/>
      <target dev='hda' bus='ide'/>
      <address type='drive' controller='0' bus='0' target='0' unit='0'/>
    </disk>
    <disk type='network' device='disk'>
      <alias name="ua-netdisk"/>
      <driver name='qemu' type='raw'/>
      <auth username='myname'>
        <secret type='iscsi' usage='mycluster_myname'/>
      </auth>
      <source protocol='iscsi' name='iqn.1992-01.com.example'>
        <host name='example.org' port='6000'/>
      </source>
      <target dev='vda' bus='virtio'/>
    </disk>
    <disk type='network' device='disk'>
      <driver name='qemu' type='raw'/>
      <source protocol='iscsi' name='iqn.1992-01.com.example/1'>
        <host name='example.org' port='6000'/>
      </source>
      <target dev='vdb' bus='virtio'/>
    </disk>
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x06' slot='0x12' function='0x5'/>
      </source>
    </hostdev>
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x06' slot='0x12' function='0x6'/>
      </source>
    </hostdev>
    <interface type="bridge">
      <mac address="fa:16:3e:f9:af:ae"/>
      <model type="virtio"/>
      <driver name="qemu"/>
      <source bridge="qbr84008d03-11"/>
      <target dev="tap84008d03-11"/>
    </interface>
    <controller type='usb' index='0'/>
    <controller type='pci' index='0' model='pci-root'/>
    <memballoon model='none'/>
  </devices>
</domain>
"""
        self.domain.XMLDesc.return_value = xml

        dev = self.guest.get_device_by_alias('qemu-disk1')
        self.assertIsInstance(dev, vconfig.LibvirtConfigGuestDisk)
        self.assertEqual('hda', dev.target_dev)

        dev = self.guest.get_device_by_alias('ua-netdisk')
        self.assertIsInstance(dev, vconfig.LibvirtConfigGuestDisk)
        self.assertEqual('vda', dev.target_dev)

        self.assertIsNone(self.guest.get_device_by_alias('nope'))

    def test_get_devices(self):
        xml = """
<domain type='qemu'>
  <name>QEMUGuest1</name>
  <uuid>c7a5fdbd-edaf-9455-926a-d65c16db1809</uuid>
  <memory unit='KiB'>219136</memory>
  <currentMemory unit='KiB'>219136</currentMemory>
  <vcpu placement='static'>1</vcpu>
  <os>
    <type arch='i686' machine='pc'>hvm</type>
    <boot dev='hd'/>
  </os>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>destroy</on_crash>
  <devices>
    <emulator>/usr/bin/qemu</emulator>
    <disk type='block' device='disk'>
      <driver name='qemu' type='raw'/>
      <source dev='/dev/HostVG/QEMUGuest2'/>
      <target dev='hda' bus='ide'/>
      <address type='drive' controller='0' bus='0' target='0' unit='0'/>
    </disk>
    <disk type='network' device='disk'>
      <driver name='qemu' type='raw'/>
      <auth username='myname'>
        <secret type='iscsi' usage='mycluster_myname'/>
      </auth>
      <source protocol='iscsi' name='iqn.1992-01.com.example'>
        <host name='example.org' port='6000'/>
      </source>
      <target dev='vda' bus='virtio'/>
    </disk>
    <disk type='network' device='disk'>
      <driver name='qemu' type='raw'/>
      <source protocol='iscsi' name='iqn.1992-01.com.example/1'>
        <host name='example.org' port='6000'/>
      </source>
      <target dev='vdb' bus='virtio'/>
    </disk>
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x06' slot='0x12' function='0x5'/>
      </source>
    </hostdev>
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x06' slot='0x12' function='0x6'/>
      </source>
    </hostdev>
    <interface type="bridge">
      <mac address="fa:16:3e:f9:af:ae"/>
      <model type="virtio"/>
      <driver name="qemu"/>
      <source bridge="qbr84008d03-11"/>
      <target dev="tap84008d03-11"/>
    </interface>
    <controller type='usb' index='0'/>
    <controller type='pci' index='0' model='pci-root'/>
    <memballoon model='none'/>
  </devices>
</domain>
"""

        self.domain.XMLDesc.return_value = xml

        devs = self.guest.get_all_devices()
        # Only currently parse <disk>, <hostdev> and <interface> elements
        # hence we're not counting the controller/memballoon
        self.assertEqual(6, len(devs))
        self.assertIsInstance(devs[0], vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(devs[1], vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(devs[2], vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(devs[3], vconfig.LibvirtConfigGuestHostdev)
        self.assertIsInstance(devs[4], vconfig.LibvirtConfigGuestHostdev)
        self.assertIsInstance(devs[5], vconfig.LibvirtConfigGuestInterface)

        devs = self.guest.get_all_devices(vconfig.LibvirtConfigGuestDisk)
        self.assertEqual(3, len(devs))
        self.assertIsInstance(devs[0], vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(devs[1], vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(devs[2], vconfig.LibvirtConfigGuestDisk)

        devs = self.guest.get_all_disks()
        self.assertEqual(3, len(devs))
        self.assertIsInstance(devs[0], vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(devs[1], vconfig.LibvirtConfigGuestDisk)
        self.assertIsInstance(devs[2], vconfig.LibvirtConfigGuestDisk)

        devs = self.guest.get_all_devices(vconfig.LibvirtConfigGuestHostdev)
        self.assertEqual(2, len(devs))
        self.assertIsInstance(devs[0], vconfig.LibvirtConfigGuestHostdev)
        self.assertIsInstance(devs[1], vconfig.LibvirtConfigGuestHostdev)

        devs = self.guest.get_all_devices(vconfig.LibvirtConfigGuestInterface)
        self.assertEqual(1, len(devs))
        self.assertIsInstance(devs[0], vconfig.LibvirtConfigGuestInterface)

        cfg = vconfig.LibvirtConfigGuestInterface()
        cfg.parse_str("""
            <interface type="bridge">
              <mac address="fa:16:3e:f9:af:ae"/>
              <model type="virtio"/>
              <driver name="qemu"/>
              <source bridge="qbr84008d03-11"/>
              <target dev="tap84008d03-11"/>
              </interface>""")
        self.assertIsNotNone(
            self.guest.get_interface_by_cfg(cfg))
        self.assertIsNone(self.guest.get_interface_by_cfg(None))
        self.domain.XMLDesc.assert_has_calls([mock.call(0)] * 6)

        # now check if the persistent config can be queried too
        self.domain.XMLDesc.reset_mock()
        devs = self.guest.get_all_devices(
            devtype=None, from_persistent_config=True)
        self.domain.XMLDesc.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_XML_INACTIVE)

    def test_get_interface_by_cfg_persistent_domain(self):
        self.domain.XMLDesc.return_value = """<domain>
  <devices>
    <interface type="bridge">
      <mac address="fa:16:3e:f9:af:ae"/>
      <model type="virtio"/>
      <driver name="qemu"/>
      <source bridge="qbr84008d03-11"/>
      <target dev="tap84008d03-11"/>
    </interface>
  </devices>
</domain>"""
        cfg = vconfig.LibvirtConfigGuestInterface()
        cfg.parse_str("""
            <interface type="bridge">
              <mac address="fa:16:3e:f9:af:ae"/>
              <model type="virtio"/>
              <driver name="qemu"/>
              <source bridge="qbr84008d03-11"/>
              <target dev="tap84008d03-11"/>
              </interface>""")
        self.assertIsNotNone(
            self.guest.get_interface_by_cfg(
                cfg, from_persistent_config=True))
        cfg = vconfig.LibvirtConfigGuestInterface()
        # NOTE(sean-k-mooney): a default constructed object is not valid
        # to pass to get_interface_by_cfg as so we just modify the xml to
        # make it not match
        cfg.parse_str("""
            <interface type="wont_match">
              <mac address="fa:16:3e:f9:af:ae"/>
              <model type="virtio"/>
              <driver name="qemu"/>
              <source bridge="qbr84008d03-11"/>
              <target dev="tap84008d03-11"/>
              </interface>""")
        self.assertIsNone(
            self.guest.get_interface_by_cfg(
                cfg,
                from_persistent_config=True))
        self.domain.XMLDesc.assert_has_calls(
            [
                mock.call(fakelibvirt.VIR_DOMAIN_XML_INACTIVE),
                mock.call(fakelibvirt.VIR_DOMAIN_XML_INACTIVE),
            ]
        )

    def test_get_interface_by_cfg_vhostuser(self):
        self.domain.XMLDesc.return_value = """<domain>
  <devices>
    <interface type="vhostuser">
      <mac address='fa:16:3e:55:3e:e4'/>
      <source type='unix' path='/var/run/openvswitch/vhued80c655-4e'
       mode='server'/>
      <target dev='vhued80c655-4e'/>
      <model type='virtio'/>
      <alias name='net0'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x03'
       function='0x0'/>
    </interface>
  </devices>
</domain>"""
        cfg = vconfig.LibvirtConfigGuestInterface()
        cfg.parse_str("""<interface type="vhostuser">
  <mac address='fa:16:3e:55:3e:e4'/>
  <model type="virtio"/>
  <source type='unix' path='/var/run/openvswitch/vhued80c655-4e'
   mode='server'/>
  <alias name='net0'/>
  <address type='pci' domain='0x0000' bus='0x00' slot='0x03' function='0x0'/>
  </interface>""")
        self.assertIsNotNone(
            self.guest.get_interface_by_cfg(cfg))
        self.assertIsNone(self.guest.get_interface_by_cfg(None))

    def test_get_interface_by_cfg_hostdev_pci(self):
        self.domain.XMLDesc.return_value = """<domain>
            <devices>
                <hostdev mode='subsystem' type='pci' managed='yes'>
                <driver name='vfio'/>
                <source>
                <address domain='0x0000' bus='0x81' slot='0x00'
                    function='0x1'/>
                </source>
                <alias name='hostdev0'/>
                <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
                    function='0x0'/>
                </hostdev>
            </devices>
        </domain>"""
        cfg = vconfig.LibvirtConfigGuestHostdevPCI()
        cfg.parse_str("""
            <hostdev mode='subsystem' type='pci' managed='yes'>
            <driver name='vfio'/>
            <source>
            <address domain='0x0000' bus='0x81' slot='0x00' function='0x1'/>
            </source>
            </hostdev>""")
        self.assertIsNotNone(
            self.guest.get_interface_by_cfg(cfg))

        cfg.parse_str("""
            <hostdev mode='subsystem' type='pci' managed='yes'>
            <driver name='vfio'/>
            <source>
            <address domain='0000' bus='81' slot='00' function='1'/>
            </source>
            </hostdev>""")
        self.assertIsNotNone(
            self.guest.get_interface_by_cfg(cfg))

        self.assertIsNone(self.guest.get_interface_by_cfg(None))

    def test_get_info(self):
        self.domain.info.return_value = (1, 2, 3, 4, 5)
        self.domain.ID.return_value = 6
        info = self.guest.get_info(self.host)
        self.domain.info.assert_called_once_with()
        self.assertEqual(1, info.state)
        self.assertEqual(6, info.internal_id)

    def test_get_power_state(self):
        self.domain.info.return_value = (1, 2, 3, 4, 5)
        power = self.guest.get_power_state(self.host)
        self.assertEqual(1, power)

    def test_is_active_when_domain_is_active(self):
        with mock.patch.object(self.domain, "isActive", return_value=True):
            self.assertTrue(self.guest.is_active())

    def test_is_active_when_domain_not_active(self):
        with mock.patch.object(self.domain, "isActive", return_value=False):
            self.assertFalse(self.guest.is_active())

    def test_freeze_filesystems(self):
        self.guest.freeze_filesystems()
        self.domain.fsFreeze.assert_called_once_with()

    def test_thaw_filesystems(self):
        self.guest.thaw_filesystems()
        self.domain.fsThaw.assert_called_once_with()

    def _conf_snapshot(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestSnapshotDisk)
        conf.to_xml.return_value = '<disk/>'
        return conf

    def test_snapshot(self):
        conf = self._conf_snapshot()
        self.guest.snapshot(conf)
        self.domain.snapshotCreateXML('<disk/>', flags=0)
        conf.to_xml.assert_called_once_with()

    def test_snapshot_no_metadata(self):
        conf = self._conf_snapshot()
        self.guest.snapshot(conf, no_metadata=True)
        self.domain.snapshotCreateXML(
            '<disk/>',
            flags=fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA)
        conf.to_xml.assert_called_once_with()

    def test_snapshot_disk_only(self):
        conf = self._conf_snapshot()
        self.guest.snapshot(conf, disk_only=True)
        self.domain.snapshotCreateXML(
            '<disk/>', flags=fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY)
        conf.to_xml.assert_called_once_with()

    def test_snapshot_reuse_ext(self):
        conf = self._conf_snapshot()
        self.guest.snapshot(conf, reuse_ext=True)
        self.domain.snapshotCreateXML(
            '<disk/>', flags=fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT)
        conf.to_xml.assert_called_once_with()

    def test_snapshot_quiesce(self):
        conf = self._conf_snapshot()
        self.guest.snapshot(conf, quiesce=True)
        self.domain.snapshotCreateXML(
            '<disk/>', flags=fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE)
        conf.to_xml.assert_called_once_with()

    def test_snapshot_all(self):
        conf = self._conf_snapshot()
        self.guest.snapshot(conf, no_metadata=True,
                            disk_only=True, reuse_ext=True,
                            quiesce=True)
        self.domain.snapshotCreateXML(
            '<disk/>', flags=(
                fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT |
                fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY |
                fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA |
                fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE))
        conf.to_xml.assert_called_once_with()

    def test_pause(self):
        self.guest.pause()
        self.domain.suspend.assert_called_once_with()

    def test_migrate_v3(self):
        self.guest.migrate('an-uri', flags=1, migrate_uri='dest-uri',
                           migrate_disks='disk1',
                           destination_xml='</xml>',
                           bandwidth=2)
        self.domain.migrateToURI3.assert_called_once_with(
                'an-uri', flags=1, params={'migrate_uri': 'dest-uri',
                                           'migrate_disks': 'disk1',
                                           'destination_xml': '</xml>',
                                           'persistent_xml': '</xml>',
                                           'bandwidth': 2})

    def test_abort_job(self):
        self.guest.abort_job()
        self.domain.abortJob.assert_called_once_with()

    def test_migrate_configure_max_downtime(self):
        self.guest.migrate_configure_max_downtime(1000)
        self.domain.migrateSetMaxDowntime.assert_called_once_with(1000)

    def test_set_metadata(self):
        meta = mock.Mock(spec=vconfig.LibvirtConfigGuestMetaNovaInstance)
        meta.to_xml.return_value = "</xml>"
        self.guest.set_metadata(meta)
        self.domain.setMetadata.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_METADATA_ELEMENT, "</xml>", "instance",
            vconfig.NOVA_NS, flags=0)

    def test_set_metadata_persistent(self):
        meta = mock.Mock(spec=vconfig.LibvirtConfigGuestMetaNovaInstance)
        meta.to_xml.return_value = "</xml>"
        self.guest.set_metadata(meta, persistent=True)
        self.domain.setMetadata.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_METADATA_ELEMENT, "</xml>", "instance",
            vconfig.NOVA_NS, flags=fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG)

    def test_set_metadata_device_live(self):
        meta = mock.Mock(spec=vconfig.LibvirtConfigGuestMetaNovaInstance)
        meta.to_xml.return_value = "</xml>"
        self.guest.set_metadata(meta, live=True)
        self.domain.setMetadata.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_METADATA_ELEMENT, "</xml>", "instance",
            vconfig.NOVA_NS, flags=fakelibvirt.VIR_DOMAIN_AFFECT_LIVE)

    def test_set_metadata_persistent_live(self):
        meta = mock.Mock(spec=vconfig.LibvirtConfigGuestMetaNovaInstance)
        meta.to_xml.return_value = "</xml>"
        self.guest.set_metadata(meta, persistent=True, live=True)
        self.domain.setMetadata.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_METADATA_ELEMENT, "</xml>", "instance",
            vconfig.NOVA_NS, flags=fakelibvirt.VIR_DOMAIN_AFFECT_LIVE |
                                   fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG)

    def test_get_disk_xml(self):
        dom_xml = """
              <domain type="kvm">
                <devices>
                  <disk type="file">
                     <source file="disk1_file"/>
                     <target dev="vda" bus="virtio"/>
                     <serial>0e38683e-f0af-418f-a3f1-6b67ea0f919d</serial>
                  </disk>
                  <disk type="block">
                    <source dev="/path/to/dev/1"/>
                    <target dev="vdb" bus="virtio" serial="1234"/>
                  </disk>
                </devices>
              </domain>
              """

        diska_xml = """<disk type="file" device="disk">
  <source file="disk1_file"/>
  <target bus="virtio" dev="vda"/>
  <serial>0e38683e-f0af-418f-a3f1-6b67ea0f919d</serial>
</disk>"""

        diskb_xml = """<disk type="block" device="disk">
  <source dev="/path/to/dev/1"/>
  <target bus="virtio" dev="vdb"/>
</disk>"""

        dom = mock.MagicMock()
        dom.XMLDesc.return_value = dom_xml
        guest = libvirt_guest.Guest(dom)

        # NOTE(gcb): etree.tostring(node) returns an extra line with
        # some white spaces, need to strip it.
        actual_diska_xml = guest.get_disk('vda').to_xml()
        self.assertXmlEqual(diska_xml, actual_diska_xml)

        actual_diskb_xml = guest.get_disk('vdb').to_xml()
        self.assertXmlEqual(diskb_xml, actual_diskb_xml)

        self.assertIsNone(guest.get_disk('vdc'))

        dom.XMLDesc.assert_has_calls([mock.call(0)] * 3)

    def test_get_disk_xml_from_persistent_config(self):
        dom_xml = """
              <domain type="kvm">
                <devices>
                  <disk type="file">
                     <source file="disk1_file"/>
                     <target dev="vda" bus="virtio"/>
                     <serial>0e38683e-f0af-418f-a3f1-6b67ea0f919d</serial>
                  </disk>
                  <disk type="block">
                    <source dev="/path/to/dev/1"/>
                    <target dev="vdb" bus="virtio" serial="1234"/>
                  </disk>
                </devices>
              </domain>
              """

        diska_xml = """<disk type="file" device="disk">
  <source file="disk1_file"/>
  <target bus="virtio" dev="vda"/>
  <serial>0e38683e-f0af-418f-a3f1-6b67ea0f919d</serial>
</disk>"""

        dom = mock.MagicMock()
        dom.XMLDesc.return_value = dom_xml
        guest = libvirt_guest.Guest(dom)

        actual_diska_xml = guest.get_disk(
            'vda', from_persistent_config=True).to_xml()
        self.assertXmlEqual(diska_xml, actual_diska_xml)
        dom.XMLDesc.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_XML_INACTIVE)


class GuestBlockTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GuestBlockTestCase, self).setUp()

        self.useFixture(nova_fixtures.LibvirtFixture())
        self.host = host.Host("qemu:///system")
        self.context = context.get_admin_context()

        self.domain = mock.Mock(spec=fakelibvirt.virDomain)
        self.guest = libvirt_guest.Guest(self.domain)
        self.gblock = self.guest.get_block_device('vda')

    def test_abort_job(self):
        self.gblock.abort_job()
        self.domain.blockJobAbort.assert_called_once_with('vda', flags=0)

    def test_abort_job_async(self):
        self.gblock.abort_job(async_=True)
        self.domain.blockJobAbort.assert_called_once_with(
            'vda', flags=fakelibvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_ASYNC)

    def test_abort_job_pivot(self):
        self.gblock.abort_job(pivot=True)
        self.domain.blockJobAbort.assert_called_once_with(
            'vda', flags=fakelibvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT)

    def test_get_job_info(self):
        self.domain.blockJobInfo.return_value = {
            "type": 1,
            "bandwidth": 18,
            "cur": 66,
            "end": 100}

        info = self.gblock.get_job_info()
        self.assertEqual(1, info.job)
        self.assertEqual(18, info.bandwidth)
        self.assertEqual(66, info.cur)
        self.assertEqual(100, info.end)
        self.domain.blockJobInfo.assert_called_once_with('vda', flags=0)

    def test_resize(self):
        self.gblock.resize(10)
        self.domain.blockResize.assert_called_once_with('vda', 10, flags=1)

    def test_rebase(self):
        self.gblock.rebase("foo")
        self.domain.blockRebase.assert_called_once_with(
            'vda', "foo", 0, flags=0)

    def test_rebase_shallow(self):
        self.gblock.rebase("foo", shallow=True)
        self.domain.blockRebase.assert_called_once_with(
            'vda', "foo", 0, flags=fakelibvirt.VIR_DOMAIN_BLOCK_REBASE_SHALLOW)

    def test_rebase_reuse_ext(self):
        self.gblock.rebase("foo", reuse_ext=True)
        self.domain.blockRebase.assert_called_once_with(
            'vda', "foo", 0,
            flags=fakelibvirt.VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT)

    def test_rebase_copy(self):
        self.gblock.rebase("foo", copy=True)
        self.domain.blockRebase.assert_called_once_with(
            'vda', "foo", 0,
            flags=fakelibvirt.VIR_DOMAIN_BLOCK_REBASE_COPY)

    def test_rebase_relative(self):
        self.gblock.rebase("foo", relative=True)
        self.domain.blockRebase.assert_called_once_with(
            'vda', "foo", 0,
            flags=fakelibvirt.VIR_DOMAIN_BLOCK_REBASE_RELATIVE)

    def test_rebase_copy_dev(self):
        self.gblock.rebase("foo", copy_dev=True)
        self.domain.blockRebase.assert_called_once_with(
            'vda', "foo", 0,
            flags=fakelibvirt.VIR_DOMAIN_BLOCK_REBASE_COPY_DEV)

    def test_commit(self):
        self.gblock.commit("foo", "top")
        self.domain.blockCommit.assert_called_once_with(
            'vda', "foo", "top", 0, flags=0)

    def test_commit_relative(self):
        self.gblock.commit("foo", "top", relative=True)
        self.domain.blockCommit.assert_called_once_with(
            'vda', "foo", "top", 0,
            flags=fakelibvirt.VIR_DOMAIN_BLOCK_COMMIT_RELATIVE)

    def test_is_job_complete_cur_end_zeros(self):
        self.domain.blockJobInfo.return_value = {
            "type": 4,
            "bandwidth": 18,
            "cur": 0,
            "end": 0}
        is_complete = self.gblock.is_job_complete()
        self.assertFalse(is_complete)

    def test_is_job_complete_current_lower_than_end(self):
        self.domain.blockJobInfo.return_value = {
            "type": 4,
            "bandwidth": 18,
            "cur": 95,
            "end": 100}
        is_complete = self.gblock.is_job_complete()
        self.assertFalse(is_complete)

    def test_is_job_complete_not_ready(self):
        gblock = self.guest.get_block_device('vda')
        disk = vconfig.LibvirtConfigGuestDisk()
        disk.mirror = vconfig.LibvirtConfigGuestDiskMirror()
        with mock.patch.object(self.guest, 'get_disk', return_value=disk):
            self.domain.blockJobInfo.return_value = {
                "type": 4,
                "bandwidth": 18,
                "cur": 100,
                "end": 100}
            is_complete = gblock.is_job_complete()
            self.assertFalse(is_complete)

    def test_is_job_complete_ready(self):
        gblock = self.guest.get_block_device('vda')
        disk = vconfig.LibvirtConfigGuestDisk()
        disk.mirror = vconfig.LibvirtConfigGuestDiskMirror()
        disk.mirror.ready = 'yes'
        with mock.patch.object(self.guest, 'get_disk', return_value=disk):
            self.domain.blockJobInfo.return_value = {
                "type": 4,
                "bandwidth": 18,
                "cur": 100,
                "end": 100}
            is_complete = gblock.is_job_complete()
            self.assertTrue(is_complete)

    def test_is_job_complete_no_job(self):
        self.domain.blockJobInfo.return_value = {}
        is_complete = self.gblock.is_job_complete()
        self.assertTrue(is_complete)

    def test_is_job_complete_exception(self):
        self.domain.blockJobInfo.side_effect = fakelibvirt.libvirtError('fake')
        self.assertRaises(fakelibvirt.libvirtError,
                          self.gblock.is_job_complete)

    def test_blockStats(self):
        self.gblock.blockStats()
        self.domain.blockStats.assert_called_once_with('vda')


class JobInfoTestCase(test.NoDBTestCase):

    def setUp(self):
        super(JobInfoTestCase, self).setUp()

        self.useFixture(nova_fixtures.LibvirtFixture())

        self.conn = fakelibvirt.openAuth("qemu:///system",
                                         [[], lambda: True])
        xml = ("<domain type='kvm'>"
               "  <name>instance-0000000a</name>"
               "</domain>")
        self.dom = self.conn.createXML(xml, 0)
        self.guest = libvirt_guest.Guest(self.dom)
        libvirt_guest.JobInfo._have_job_stats = True

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_stats(self, mock_stats, mock_info):
        mock_stats.return_value = {
            "type": fakelibvirt.VIR_DOMAIN_JOB_UNBOUNDED,
            "memory_total": 75,
            "memory_processed": 50,
            "memory_remaining": 33,
            "some_new_libvirt_stat_we_dont_know_about": 83
        }

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_UNBOUNDED, info.type)
        self.assertEqual(75, info.memory_total)
        self.assertEqual(50, info.memory_processed)
        self.assertEqual(33, info.memory_remaining)
        self.assertEqual(0, info.disk_total)
        self.assertEqual(0, info.disk_processed)
        self.assertEqual(0, info.disk_remaining)

        mock_stats.assert_called_once_with()
        self.assertFalse(mock_info.called)

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_info_no_support(self, mock_stats, mock_info):
        mock_stats.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "virDomainGetJobStats not implemented",
            fakelibvirt.VIR_ERR_NO_SUPPORT)

        mock_info.return_value = [
            fakelibvirt.VIR_DOMAIN_JOB_UNBOUNDED,
            100, 99, 10, 11, 12, 75, 50, 33, 1, 2, 3]

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_UNBOUNDED, info.type)
        self.assertEqual(100, info.time_elapsed)
        self.assertEqual(99, info.time_remaining)
        self.assertEqual(10, info.data_total)
        self.assertEqual(11, info.data_processed)
        self.assertEqual(12, info.data_remaining)
        self.assertEqual(75, info.memory_total)
        self.assertEqual(50, info.memory_processed)
        self.assertEqual(33, info.memory_remaining)
        self.assertEqual(1, info.disk_total)
        self.assertEqual(2, info.disk_processed)
        self.assertEqual(3, info.disk_remaining)

        mock_stats.assert_called_once_with()
        mock_info.assert_called_once_with()

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_info_attr_error(self, mock_stats, mock_info):
        mock_stats.side_effect = AttributeError("No such API")

        mock_info.return_value = [
            fakelibvirt.VIR_DOMAIN_JOB_UNBOUNDED,
            100, 99, 10, 11, 12, 75, 50, 33, 1, 2, 3]

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_UNBOUNDED, info.type)
        self.assertEqual(100, info.time_elapsed)
        self.assertEqual(99, info.time_remaining)
        self.assertEqual(10, info.data_total)
        self.assertEqual(11, info.data_processed)
        self.assertEqual(12, info.data_remaining)
        self.assertEqual(75, info.memory_total)
        self.assertEqual(50, info.memory_processed)
        self.assertEqual(33, info.memory_remaining)
        self.assertEqual(1, info.disk_total)
        self.assertEqual(2, info.disk_processed)
        self.assertEqual(3, info.disk_remaining)

        mock_stats.assert_called_once_with()
        mock_info.assert_called_once_with()

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_stats_no_domain(self, mock_stats, mock_info):
        mock_stats.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "No such domain with UUID blah",
            fakelibvirt.VIR_ERR_NO_DOMAIN)

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_COMPLETED, info.type)
        self.assertEqual(0, info.time_elapsed)
        self.assertEqual(0, info.time_remaining)
        self.assertEqual(0, info.memory_total)
        self.assertEqual(0, info.memory_processed)
        self.assertEqual(0, info.memory_remaining)

        mock_stats.assert_called_once_with()
        self.assertFalse(mock_info.called)

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_info_no_domain(self, mock_stats, mock_info):
        mock_stats.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "virDomainGetJobStats not implemented",
            fakelibvirt.VIR_ERR_NO_SUPPORT)

        mock_info.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "No such domain with UUID blah",
            fakelibvirt.VIR_ERR_NO_DOMAIN)

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_COMPLETED, info.type)
        self.assertEqual(0, info.time_elapsed)
        self.assertEqual(0, info.time_remaining)
        self.assertEqual(0, info.memory_total)
        self.assertEqual(0, info.memory_processed)
        self.assertEqual(0, info.memory_remaining)

        mock_stats.assert_called_once_with()
        mock_info.assert_called_once_with()

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_stats_operation_invalid(self, mock_stats, mock_info):
        mock_stats.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "Domain is not running",
            fakelibvirt.VIR_ERR_OPERATION_INVALID)

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_COMPLETED, info.type)
        self.assertEqual(0, info.time_elapsed)
        self.assertEqual(0, info.time_remaining)
        self.assertEqual(0, info.memory_total)
        self.assertEqual(0, info.memory_processed)
        self.assertEqual(0, info.memory_remaining)

        mock_stats.assert_called_once_with()
        self.assertFalse(mock_info.called)

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_info_operation_invalid(self, mock_stats, mock_info):
        mock_stats.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "virDomainGetJobStats not implemented",
            fakelibvirt.VIR_ERR_NO_SUPPORT)

        mock_info.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "Domain is not running",
            fakelibvirt.VIR_ERR_OPERATION_INVALID)

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_COMPLETED, info.type)
        self.assertEqual(0, info.time_elapsed)
        self.assertEqual(0, info.time_remaining)
        self.assertEqual(0, info.memory_total)
        self.assertEqual(0, info.memory_processed)
        self.assertEqual(0, info.memory_remaining)

        mock_stats.assert_called_once_with()
        mock_info.assert_called_once_with()

    @mock.patch.object(fakelibvirt.virDomain, "jobInfo")
    @mock.patch.object(fakelibvirt.virDomain, "jobStats")
    def test_job_stats_no_ram(self, mock_stats, mock_info):
        mock_stats.side_effect = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            "internal error: migration was active, but no RAM info was set",
            error_code=fakelibvirt.VIR_ERR_INTERNAL_ERROR,
            error_message="migration was active, but no RAM info was set")

        info = self.guest.get_job_info()

        self.assertIsInstance(info, libvirt_guest.JobInfo)
        self.assertEqual(fakelibvirt.VIR_DOMAIN_JOB_NONE, info.type)
        self.assertEqual(0, info.time_elapsed)
        self.assertEqual(0, info.time_remaining)
        self.assertEqual(0, info.memory_total)
        self.assertEqual(0, info.memory_processed)
        self.assertEqual(0, info.memory_remaining)

        mock_stats.assert_called_once_with()
        self.assertFalse(mock_info.called)
