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
from oslo_config import cfg
from oslo_utils import encodeutils

from nova import context
from nova import exception
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova import utils
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host


host.libvirt = fakelibvirt
libvirt_guest.libvirt = fakelibvirt

CONF = cfg.CONF

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

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(libvirt_guest.Guest, 'get_interfaces')
    def test_enable_hairpin(self, mock_get_interfaces, mock_execute):
        mock_get_interfaces.return_value = ["vnet0", "vnet1"]
        self.guest.enable_hairpin()
        mock_execute.assert_has_calls([
            mock.call(
                'tee', '/sys/class/net/vnet0/brport/hairpin_mode',
                run_as_root=True, process_input='1', check_exit_code=[0, 1]),
            mock.call(
                'tee', '/sys/class/net/vnet1/brport/hairpin_mode',
                run_as_root=True, process_input='1', check_exit_code=[0, 1])])

    @mock.patch.object(encodeutils, 'safe_decode')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(libvirt_guest.Guest, 'get_interfaces')
    def test_enable_hairpin_exception(self, mock_get_interfaces,
                            mock_execute, mock_safe_decode):
        mock_get_interfaces.return_value = ["foo"]
        mock_execute.side_effect = test.TestingException('oops')

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

    def test_detach_device_with_retry_detach_success(self):
        conf = mock.Mock(spec=vconfig.LibvirtConfigGuestDevice)
        conf.to_xml.return_value = "</xml>"
        get_config = mock.Mock()
        # Force multiple retries of detach
        get_config.side_effect = [conf, conf, conf, None]
        dev_path = "/dev/vdb"

        retry_detach = self.guest.detach_device_with_retry(
            get_config, dev_path, persistent=True, live=True,
            inc_sleep_time=.01)
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

        retry_detach = self.guest.detach_device_with_retry(
            get_config, "/dev/vdb", persistent=True, live=True,
            inc_sleep_time=.01, max_retry_count=3)
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
        self.assertRaises(
            exception.DeviceNotFound, self.guest.detach_device_with_retry,
            get_config, "/dev/vdb", persistent=True, live=True)

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

        self.assertIsNotNone(
            self.guest.get_interface_by_mac('fa:16:3e:f9:af:ae'))
        self.assertIsNone(self.guest.get_interface_by_mac(None))

    def test_get_info(self):
        self.domain.info.return_value = (1, 2, 3, 4, 5)
        self.domain.ID.return_value = 6
        info = self.guest.get_info(self.host)
        self.domain.info.assert_called_once_with()
        self.assertEqual(1, info.state)
        self.assertEqual(2, info.max_mem_kb)
        self.assertEqual(3, info.mem_kb)
        self.assertEqual(4, info.num_cpu)
        self.assertEqual(5, info.cpu_time_ns)
        self.assertEqual(6, info.id)

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

    def test_commit(self):
        self.gblock.commit("foo", "top")
        self.domain.blockCommit.assert_called_once_with(
            'vda', "foo", "top", 0, flags=0)

    def test_commit_relative(self):
        self.gblock.commit("foo", "top", relative=True)
        self.domain.blockCommit.assert_called_once_with(
            'vda', "foo", "top", 0,
            flags=fakelibvirt.VIR_DOMAIN_BLOCK_COMMIT_RELATIVE)

    def test_wait_for_job(self):
        self.domain.blockJobInfo.return_value = {
            "type": 4,
            "bandwidth": 18,
            "cur": 95,
            "end": 100}
        in_progress = self.gblock.wait_for_job()
        self.assertTrue(in_progress)

        self.domain.blockJobInfo.return_value = {
            "type": 4,
            "bandwidth": 18,
            "cur": 100,
            "end": 100}
        in_progress = self.gblock.wait_for_job()
        self.assertFalse(in_progress)

        self.domain.blockJobInfo.return_value = {"type": 0}
        in_progress = self.gblock.wait_for_job(wait_for_job_clean=True)
        self.assertFalse(in_progress)

    def test_wait_for_job_arbort_on_error(self):
        self.domain.blockJobInfo.return_value = -1
        self.assertRaises(
            exception.NovaException,
            self.gblock.wait_for_job, abort_on_error=True)
