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

import sys

import mock
from oslo_utils import encodeutils
import six
import testtools

from nova import context
from nova import exception
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host


if sys.version_info > (3,):
    long = int


class GuestTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GuestTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.host = host.Host("qemu:///system")
        self.context = context.get_admin_context()

        self.domain = mock.Mock(spec=fakelibvirt.virDomain)
        self.guest = libvirt_guest.Guest(self.domain)

    def test_repr(self):
        self.domain.ID.return_value = 99
        self.domain.UUIDString.return_value = "UUID"
        self.domain.name.return_value = "foo"
        self.assertEqual("<Guest 99 foo UUID>", repr(self.guest))

    @mock.patch.object(fakelibvirt.Connection, 'defineXML')
    def test_create(self, mock_define):
        libvirt_guest.Guest.create("xml", self.host)
        mock_define.assert_called_once_with("xml")

    @mock.patch.object(fakelibvirt.Connection, 'defineXML')
    def test_create_exception(self, mock_define):
        mock_define.side_effect = test.TestingException
        self.assertRaises(test.TestingException,
                          libvirt_guest.Guest.create,
                          "foo", self.host)

    def test_launch(self):
        self.guest.launch()
        self.domain.createWithFlags.assert_called_once_with(0)

    def test_launch_and_pause(self):
        self.guest.launch(pause=True)
        self.domain.createWithFlags.assert_called_once_with(
            fakelibvirt.VIR_DOMAIN_START_PAUSED)

    def test_shutdown(self):
        self.domain.shutdown = mock.MagicMock()
        self.guest.shutdown()
        self.domain.shutdown.assert_called_once_with()

    @mock.patch.object(encodeutils, 'safe_decode')
    def test_launch_exception(self, mock_safe_decode):
        self.domain.createWithFlags.side_effect = test.TestingException
        mock_safe_decode.return_value = "</xml>"
        self.assertRaises(test.TestingException, self.guest.launch)
        self.assertEqual(1, mock_safe_decode.called)

    @mock.patch('nova.privsep.libvirt.enable_hairpin')
    @mock.patch.object(libvirt_guest.Guest, 'get_interfaces')
    def test_enable_hairpin(self, mock_get_interfaces, mock_writefile):
        mock_get_interfaces.return_value = ["vnet0", "vnet1"]
        self.guest.enable_hairpin()
        mock_writefile.assert_has_calls([
            mock.call('vnet0'),
            mock.call('vnet1')]
        )

    @mock.patch.object(encodeutils, 'safe_decode')
    @mock.patch('nova.privsep.libvirt.enable_hairpin')
    @mock.patch.object(libvirt_guest.Guest, 'get_interfaces')
    def test_enable_hairpin_exception(self, mock_get_interfaces,
                            mock_writefile, mock_safe_decode):
        mock_get_interfaces.return_value = ["foo"]
        mock_writefile.side_effect = test.TestingException

        self.assertRaises(test.TestingException, self.guest.enable_hairpin)
        self.assertEqual(1, mock_safe_decode.called)

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
            fakelibvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)

    def test_delete_configuration_with_nvram(self):
        self.guest.delete_configuration(support_uefi=True)
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

    def test_detach_device_with_retry_from_transient_domain(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        get_config = mock.Mock()
        get_config.side_effect = [conf, conf, None]
        dev_path = "/dev/vdb"
        self.domain.isPersistent.return_value = False
        retry_detach = self.guest.detach_device_with_retry(
            get_config, dev_path, live=True, inc_sleep_time=.01)
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=fakelibvirt.VIR_DOMAIN_AFFECT_LIVE)
        self.domain.detachDeviceFlags.reset_mock()
        retry_detach()
        self.assertEqual(1, self.domain.detachDeviceFlags.call_count)

    def test_detach_device_with_retry_detach_success(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        get_config = mock.Mock()
        # Force multiple retries of detach
        get_config.side_effect = [conf, conf, conf, None]
        dev_path = "/dev/vdb"
        self.domain.isPersistent.return_value = True

        retry_detach = self.guest.detach_device_with_retry(
            get_config, dev_path, live=True, inc_sleep_time=.01)
        # Ensure we've only done the initial detach call
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=(fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG |
                             fakelibvirt.VIR_DOMAIN_AFFECT_LIVE))

        get_config.assert_called_with(dev_path)

        # Some time later, we can do the wait/retry to ensure detach succeeds
        self.domain.detachDeviceFlags.reset_mock()
        retry_detach()
        # Should have two retries before we pretend device is detached
        self.assertEqual(2, self.domain.detachDeviceFlags.call_count)

    def test_detach_device_with_retry_detach_failure(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        # Continue to return some value for the disk config
        get_config = mock.Mock(return_value=conf)
        self.domain.isPersistent.return_value = True

        retry_detach = self.guest.detach_device_with_retry(
            get_config, "/dev/vdb", live=True, inc_sleep_time=.01,
            max_retry_count=3)
        # Ensure we've only done the initial detach call
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=(fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG |
                             fakelibvirt.VIR_DOMAIN_AFFECT_LIVE))

        # Some time later, we can do the wait/retry to ensure detach
        self.domain.detachDeviceFlags.reset_mock()
        # Should hit max # of retries
        self.assertRaises(exception.DeviceDetachFailed, retry_detach)
        self.assertEqual(4, self.domain.detachDeviceFlags.call_count)

    def test_detach_device_with_retry_device_not_found(self):
        get_config = mock.Mock(return_value=None)
        self.domain.isPersistent.return_value = True
        ex = self.assertRaises(
            exception.DeviceNotFound, self.guest.detach_device_with_retry,
            get_config, "/dev/vdb", live=True)
        self.assertIn("/dev/vdb", six.text_type(ex))

    def test_detach_device_with_retry_device_not_found_alt_name(self):
        """Tests to make sure we use the alternative name in errors."""
        get_config = mock.Mock(return_value=None)
        self.domain.isPersistent.return_value = True
        ex = self.assertRaises(
            exception.DeviceNotFound, self.guest.detach_device_with_retry,
            get_config, mock.sentinel.device, live=True,
            alternative_device_name='foo')
        self.assertIn('foo', six.text_type(ex))

    @mock.patch.object(libvirt_guest.Guest, "detach_device")
    def test_detach_device_with_retry_operation_failed(self, mock_detach):
        # This simulates a retry of the transient/live domain detach
        # failing because the device is not found
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.domain.isPersistent.return_value = True

        get_config = mock.Mock(return_value=conf)
        fake_device = "vdb"
        fake_exc = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError, "",
            error_message="operation failed: disk vdb not found",
            error_code=fakelibvirt.VIR_ERR_OPERATION_FAILED,
            error_domain=fakelibvirt.VIR_FROM_DOMAIN)
        mock_detach.side_effect = [None, fake_exc]
        retry_detach = self.guest.detach_device_with_retry(
            get_config, fake_device, live=True,
            inc_sleep_time=.01, max_retry_count=3)
        # Some time later, we can do the wait/retry to ensure detach
        self.assertRaises(exception.DeviceNotFound, retry_detach)

    def test_detach_device_with_retry_invalid_argument(self):
        # This simulates a persistent domain detach failing because
        # the device is not found
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.domain.isPersistent.return_value = True

        get_config = mock.Mock()
        # Simulate the persistent domain attach attempt followed by the live
        # domain attach attempt and success
        get_config.side_effect = [conf, conf, None]
        fake_device = "vdb"
        fake_exc = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError, "",
            error_message="invalid argument: no target device vdb",
            error_code=fakelibvirt.VIR_ERR_INVALID_ARG,
            error_domain=fakelibvirt.VIR_FROM_DOMAIN)
        # Detach from persistent raises not found, detach from live succeeds
        self.domain.detachDeviceFlags.side_effect = [fake_exc, None]
        retry_detach = self.guest.detach_device_with_retry(get_config,
            fake_device, live=True, inc_sleep_time=.01, max_retry_count=3)
        # We should have tried to detach from the persistent domain
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=(fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG |
                             fakelibvirt.VIR_DOMAIN_AFFECT_LIVE))
        # During the retry detach, should detach from the live domain
        self.domain.detachDeviceFlags.reset_mock()
        retry_detach()
        # We should have tried to detach from the live domain
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=fakelibvirt.VIR_DOMAIN_AFFECT_LIVE)

    def test_detach_device_with_retry_invalid_argument_no_live(self):
        # This simulates a persistent domain detach failing because
        # the device is not found
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        self.domain.isPersistent.return_value = True

        get_config = mock.Mock()
        # Simulate the persistent domain attach attempt
        get_config.return_value = conf
        fake_device = "vdb"
        fake_exc = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError, "",
            error_message="invalid argument: no target device vdb",
            error_code=fakelibvirt.VIR_ERR_INVALID_ARG,
            error_domain=fakelibvirt.VIR_FROM_DOMAIN)
        # Detach from persistent raises not found
        self.domain.detachDeviceFlags.side_effect = fake_exc
        self.assertRaises(exception.DeviceNotFound,
            self.guest.detach_device_with_retry, get_config,
            fake_device, live=False, inc_sleep_time=.01, max_retry_count=3)
        # We should have tried to detach from the persistent domain
        self.domain.detachDeviceFlags.assert_called_once_with(
            "</xml>", flags=fakelibvirt.VIR_DOMAIN_AFFECT_CONFIG)

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
                fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT
                | fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
                | fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA
                | fakelibvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE))
        conf.to_xml.assert_called_once_with()

    def test_pause(self):
        self.guest.pause()
        self.domain.suspend.assert_called_once_with()

    def test_migrate_v1(self):
        self.guest.migrate('an-uri', flags=1, bandwidth=2)
        self.domain.migrateToURI.assert_called_once_with(
            'an-uri', flags=1, bandwidth=2)

    def test_migrate_v2(self):
        self.guest.migrate('an-uri', domain_xml='</xml>', flags=1, bandwidth=2)
        self.domain.migrateToURI2.assert_called_once_with(
            'an-uri', miguri=None, dxml='</xml>', flags=1, bandwidth=2)

    def test_migrate_v3(self):
        self.guest.migrate('an-uri', domain_xml='</xml>',
                           params={'p1': 'v1'}, flags=1, bandwidth=2)
        self.domain.migrateToURI3.assert_called_once_with(
            'an-uri', flags=1, params={'p1': 'v1', 'bandwidth': 2})

    @testtools.skipIf(not six.PY2, 'libvirt python3 bindings accept unicode')
    def test_migrate_v3_unicode(self):
        dest_xml_template = "<domain type='qemu'><name>%s</name></domain>"
        name = u'\u00CD\u00F1st\u00E1\u00F1c\u00E9'
        dest_xml = dest_xml_template % name
        expect_dest_xml = dest_xml_template % encodeutils.to_utf8(name)
        self.guest.migrate('an-uri', domain_xml=dest_xml,
                           params={'p1': u'v1', 'p2': 'v2', 'p3': 3,
                                   'destination_xml': dest_xml},
                           flags=1, bandwidth=2)
        self.domain.migrateToURI3.assert_called_once_with(
                'an-uri', flags=1, params={'p1': 'v1', 'p2': 'v2', 'p3': 3,
                                           'destination_xml': expect_dest_xml,
                                           'bandwidth': 2})

    def test_abort_job(self):
        self.guest.abort_job()
        self.domain.abortJob.assert_called_once_with()

    def test_migrate_configure_max_downtime(self):
        self.guest.migrate_configure_max_downtime(1000)
        self.domain.migrateSetMaxDowntime.assert_called_once_with(1000)

    def test_migrate_configure_max_speed(self):
        self.guest.migrate_configure_max_speed(1000)
        self.domain.migrateSetMaxSpeed.assert_called_once_with(1000)


class GuestBlockTestCase(test.NoDBTestCase):

    def setUp(self):
        super(GuestBlockTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.host = host.Host("qemu:///system")
        self.context = context.get_admin_context()

        self.domain = mock.Mock(spec=fakelibvirt.virDomain)
        self.guest = libvirt_guest.Guest(self.domain)
        self.gblock = self.guest.get_block_device('vda')

    def test_abort_job(self):
        self.gblock.abort_job()
        self.domain.blockJobAbort.assert_called_once_with('vda', flags=0)

    def test_abort_job_async(self):
        self.gblock.abort_job(async=True)
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
        self.domain.blockResize.assert_called_once_with('vda', 10)

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


class JobInfoTestCase(test.NoDBTestCase):

    def setUp(self):
        super(JobInfoTestCase, self).setUp()

        self.useFixture(fakelibvirt.FakeLibvirtFixture())

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
