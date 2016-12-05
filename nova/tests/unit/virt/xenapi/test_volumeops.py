# Copyright (c) 2012 Citrix Systems, Inc.
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

from nova import exception
from nova import test
from nova.tests.unit.virt.xenapi import stubs
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import volumeops


class VolumeOpsTestBase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(VolumeOpsTestBase, self).setUp()
        self._setup_mock_volumeops()

    def _setup_mock_volumeops(self):
        self.session = stubs.FakeSessionForVolumeTests('fake_uri')
        self.ops = volumeops.VolumeOps(self.session)


class VolumeDetachTestCase(VolumeOpsTestBase):
    @mock.patch.object(volumeops.vm_utils, 'lookup', return_value='vmref')
    @mock.patch.object(volumeops.volume_utils, 'find_vbd_by_number',
                       return_value='vbdref')
    @mock.patch.object(volumeops.vm_utils, 'is_vm_shutdown',
                       return_value=False)
    @mock.patch.object(volumeops.vm_utils, 'unplug_vbd')
    @mock.patch.object(volumeops.vm_utils, 'destroy_vbd')
    @mock.patch.object(volumeops.volume_utils, 'get_device_number',
                       return_value='devnumber')
    @mock.patch.object(volumeops.volume_utils, 'find_sr_from_vbd',
                       return_value='srref')
    @mock.patch.object(volumeops.volume_utils, 'purge_sr')
    def test_detach_volume_call(self, mock_purge, mock_find_sr,
                                mock_get_device_num, mock_destroy_vbd,
                                mock_unplug_vbd, mock_is_vm, mock_find_vbd,
                                mock_lookup):

        ops = volumeops.VolumeOps('session')

        ops.detach_volume(
            dict(driver_volume_type='iscsi', data='conn_data'),
            'instance_1', 'mountpoint')

        mock_lookup.assert_called_once_with('session', 'instance_1')
        mock_get_device_num.assert_called_once_with('mountpoint')
        mock_find_vbd.assert_called_once_with('session', 'vmref', 'devnumber')
        mock_is_vm.assert_called_once_with('session', 'vmref')
        mock_unplug_vbd.assert_called_once_with('session', 'vbdref', 'vmref')
        mock_destroy_vbd.assert_called_once_with('session', 'vbdref')
        mock_find_sr.assert_called_once_with('session', 'vbdref')
        mock_purge.assert_called_once_with('session', 'srref')

    @mock.patch.object(volumeops.VolumeOps, "_detach_vbds_and_srs")
    @mock.patch.object(volume_utils, "find_vbd_by_number")
    @mock.patch.object(vm_utils, "vm_ref_or_raise")
    def test_detach_volume(self, mock_vm, mock_vbd, mock_detach):
        mock_vm.return_value = "vm_ref"
        mock_vbd.return_value = "vbd_ref"

        self.ops.detach_volume({}, "name", "/dev/xvdd")

        mock_vm.assert_called_once_with(self.session, "name")
        mock_vbd.assert_called_once_with(self.session, "vm_ref", 3)
        mock_detach.assert_called_once_with("vm_ref", ["vbd_ref"])

    @mock.patch.object(volumeops.VolumeOps, "_detach_vbds_and_srs")
    @mock.patch.object(volume_utils, "find_vbd_by_number")
    @mock.patch.object(vm_utils, "vm_ref_or_raise")
    def test_detach_volume_skips_error_skip_attach(self, mock_vm, mock_vbd,
                                                   mock_detach):
        mock_vm.return_value = "vm_ref"
        mock_vbd.return_value = None

        self.ops.detach_volume({}, "name", "/dev/xvdd")

        self.assertFalse(mock_detach.called)

    @mock.patch.object(volumeops.VolumeOps, "_detach_vbds_and_srs")
    @mock.patch.object(volume_utils, "find_vbd_by_number")
    @mock.patch.object(vm_utils, "vm_ref_or_raise")
    def test_detach_volume_raises(self, mock_vm, mock_vbd,
                                  mock_detach):
        mock_vm.return_value = "vm_ref"
        mock_vbd.side_effect = test.TestingException

        self.assertRaises(test.TestingException,
                          self.ops.detach_volume, {}, "name", "/dev/xvdd")
        self.assertFalse(mock_detach.called)

    @mock.patch.object(volume_utils, "purge_sr")
    @mock.patch.object(vm_utils, "destroy_vbd")
    @mock.patch.object(volume_utils, "find_sr_from_vbd")
    @mock.patch.object(vm_utils, "unplug_vbd")
    @mock.patch.object(vm_utils, "is_vm_shutdown")
    def test_detach_vbds_and_srs_not_shutdown(self, mock_shutdown, mock_unplug,
            mock_find_sr, mock_destroy, mock_purge):
        mock_shutdown.return_value = False
        mock_find_sr.return_value = "sr_ref"

        self.ops._detach_vbds_and_srs("vm_ref", ["vbd_ref"])

        mock_shutdown.assert_called_once_with(self.session, "vm_ref")
        mock_find_sr.assert_called_once_with(self.session, "vbd_ref")
        mock_unplug.assert_called_once_with(self.session, "vbd_ref", "vm_ref")
        mock_destroy.assert_called_once_with(self.session, "vbd_ref")
        mock_purge.assert_called_once_with(self.session, "sr_ref")

    @mock.patch.object(volume_utils, "purge_sr")
    @mock.patch.object(vm_utils, "destroy_vbd")
    @mock.patch.object(volume_utils, "find_sr_from_vbd")
    @mock.patch.object(vm_utils, "unplug_vbd")
    @mock.patch.object(vm_utils, "is_vm_shutdown")
    def test_detach_vbds_and_srs_is_shutdown(self, mock_shutdown, mock_unplug,
            mock_find_sr, mock_destroy, mock_purge):
        mock_shutdown.return_value = True
        mock_find_sr.return_value = "sr_ref"

        self.ops._detach_vbds_and_srs("vm_ref", ["vbd_ref_1", "vbd_ref_2"])

        expected = [mock.call(self.session, "vbd_ref_1"),
                    mock.call(self.session, "vbd_ref_2")]
        self.assertEqual(expected, mock_destroy.call_args_list)
        mock_purge.assert_called_with(self.session, "sr_ref")
        self.assertFalse(mock_unplug.called)

    @mock.patch.object(volumeops.VolumeOps, "_detach_vbds_and_srs")
    @mock.patch.object(volumeops.VolumeOps, "_get_all_volume_vbd_refs")
    def test_detach_all_no_volumes(self, mock_get_all, mock_detach):
        mock_get_all.return_value = []

        self.ops.detach_all("vm_ref")

        mock_get_all.assert_called_once_with("vm_ref")
        self.assertFalse(mock_detach.called)

    @mock.patch.object(volumeops.VolumeOps, "_detach_vbds_and_srs")
    @mock.patch.object(volumeops.VolumeOps, "_get_all_volume_vbd_refs")
    def test_detach_all_volumes(self, mock_get_all, mock_detach):
        mock_get_all.return_value = ["1"]

        self.ops.detach_all("vm_ref")

        mock_get_all.assert_called_once_with("vm_ref")
        mock_detach.assert_called_once_with("vm_ref", ["1"])

    def test_get_all_volume_vbd_refs_no_vbds(self):
        with mock.patch.object(self.session.VM, "get_VBDs") as mock_get:
            with mock.patch.object(self.session.VBD,
                                   "get_other_config") as mock_conf:
                mock_get.return_value = []

                result = self.ops._get_all_volume_vbd_refs("vm_ref")

                self.assertEqual([], list(result))
                mock_get.assert_called_once_with("vm_ref")
                self.assertFalse(mock_conf.called)

    def test_get_all_volume_vbd_refs_no_volumes(self):
        with mock.patch.object(self.session.VM, "get_VBDs") as mock_get:
            with mock.patch.object(self.session.VBD,
                                   "get_other_config") as mock_conf:
                mock_get.return_value = ["1"]
                mock_conf.return_value = {}

                result = self.ops._get_all_volume_vbd_refs("vm_ref")

                self.assertEqual([], list(result))
                mock_get.assert_called_once_with("vm_ref")
                mock_conf.assert_called_once_with("1")

    def test_get_all_volume_vbd_refs_with_volumes(self):
        with mock.patch.object(self.session.VM, "get_VBDs") as mock_get:
            with mock.patch.object(self.session.VBD,
                                   "get_other_config") as mock_conf:
                mock_get.return_value = ["1", "2"]
                mock_conf.return_value = {"osvol": True}

                result = self.ops._get_all_volume_vbd_refs("vm_ref")

                self.assertEqual(["1", "2"], list(result))
                mock_get.assert_called_once_with("vm_ref")


class AttachVolumeTestCase(VolumeOpsTestBase):
    @mock.patch.object(volumeops.VolumeOps, "_attach_volume")
    @mock.patch.object(vm_utils, "vm_ref_or_raise")
    def test_attach_volume_default_hotplug(self, mock_get_vm, mock_attach):
        mock_get_vm.return_value = "vm_ref"

        self.ops.attach_volume({}, "instance_name", "/dev/xvda")

        mock_attach.assert_called_once_with({}, "vm_ref", "instance_name",
                                            '/dev/xvda', True)

    @mock.patch.object(volumeops.VolumeOps, "_attach_volume")
    @mock.patch.object(vm_utils, "vm_ref_or_raise")
    def test_attach_volume_hotplug(self, mock_get_vm, mock_attach):
        mock_get_vm.return_value = "vm_ref"

        self.ops.attach_volume({}, "instance_name", "/dev/xvda", False)

        mock_attach.assert_called_once_with({}, "vm_ref", "instance_name",
                                            '/dev/xvda', False)

    @mock.patch.object(volumeops.VolumeOps, "_attach_volume")
    def test_attach_volume_default_hotplug_connect_volume(self, mock_attach):
        self.ops.connect_volume({})
        mock_attach.assert_called_once_with({})

    @mock.patch.object(volumeops.VolumeOps, "_check_is_supported_driver_type")
    @mock.patch.object(volumeops.VolumeOps, "_connect_to_volume_provider")
    @mock.patch.object(volumeops.VolumeOps, "_connect_hypervisor_to_volume")
    @mock.patch.object(volumeops.VolumeOps, "_attach_volume_to_vm")
    def test_attach_volume_with_defaults(self, mock_attach, mock_hypervisor,
                                         mock_provider, mock_driver):
        connection_info = {"data": {}}
        with mock.patch.object(self.session.VDI, "get_uuid") as mock_vdi:
            mock_provider.return_value = ("sr_ref", "sr_uuid")
            mock_vdi.return_value = "vdi_uuid"

            result = self.ops._attach_volume(connection_info)

            self.assertEqual(result, ("sr_uuid", "vdi_uuid"))

        mock_driver.assert_called_once_with(connection_info)
        mock_provider.assert_called_once_with({}, None)
        mock_hypervisor.assert_called_once_with("sr_ref", {})
        self.assertFalse(mock_attach.called)

    @mock.patch.object(volumeops.VolumeOps, "_check_is_supported_driver_type")
    @mock.patch.object(volumeops.VolumeOps, "_connect_to_volume_provider")
    @mock.patch.object(volumeops.VolumeOps, "_connect_hypervisor_to_volume")
    @mock.patch.object(volumeops.VolumeOps, "_attach_volume_to_vm")
    def test_attach_volume_with_hot_attach(self, mock_attach, mock_hypervisor,
                                           mock_provider, mock_driver):
        connection_info = {"data": {}}
        with mock.patch.object(self.session.VDI, "get_uuid") as mock_vdi:
            mock_provider.return_value = ("sr_ref", "sr_uuid")
            mock_hypervisor.return_value = "vdi_ref"
            mock_vdi.return_value = "vdi_uuid"

            result = self.ops._attach_volume(connection_info, "vm_ref",
                        "name", 2, True)

            self.assertEqual(result, ("sr_uuid", "vdi_uuid"))

        mock_driver.assert_called_once_with(connection_info)
        mock_provider.assert_called_once_with({}, "name")
        mock_hypervisor.assert_called_once_with("sr_ref", {})
        mock_attach.assert_called_once_with("vdi_ref", "vm_ref", "name", 2,
                                            True)

    @mock.patch.object(volume_utils, "forget_sr")
    @mock.patch.object(volumeops.VolumeOps, "_check_is_supported_driver_type")
    @mock.patch.object(volumeops.VolumeOps, "_connect_to_volume_provider")
    @mock.patch.object(volumeops.VolumeOps, "_connect_hypervisor_to_volume")
    @mock.patch.object(volumeops.VolumeOps, "_attach_volume_to_vm")
    def test_attach_volume_cleanup(self, mock_attach, mock_hypervisor,
                                   mock_provider, mock_driver, mock_forget):
        connection_info = {"data": {}}
        mock_provider.return_value = ("sr_ref", "sr_uuid")
        mock_hypervisor.side_effect = test.TestingException

        self.assertRaises(test.TestingException,
                          self.ops._attach_volume, connection_info)

        mock_driver.assert_called_once_with(connection_info)
        mock_provider.assert_called_once_with({}, None)
        mock_hypervisor.assert_called_once_with("sr_ref", {})
        mock_forget.assert_called_once_with(self.session, "sr_ref")
        self.assertFalse(mock_attach.called)

    def test_check_is_supported_driver_type_pass_iscsi(self):
        conn_info = {"driver_volume_type": "iscsi"}
        self.ops._check_is_supported_driver_type(conn_info)

    def test_check_is_supported_driver_type_pass_xensm(self):
        conn_info = {"driver_volume_type": "xensm"}
        self.ops._check_is_supported_driver_type(conn_info)

    def test_check_is_supported_driver_type_pass_bad(self):
        conn_info = {"driver_volume_type": "bad"}
        self.assertRaises(exception.VolumeDriverNotFound,
                          self.ops._check_is_supported_driver_type, conn_info)

    @mock.patch.object(volume_utils, "introduce_sr")
    @mock.patch.object(volume_utils, "find_sr_by_uuid")
    @mock.patch.object(volume_utils, "parse_sr_info")
    def test_connect_to_volume_provider_new_sr(self, mock_parse, mock_find_sr,
                                               mock_introduce_sr):
        mock_parse.return_value = ("uuid", "label", "params")
        mock_find_sr.return_value = None
        mock_introduce_sr.return_value = "sr_ref"

        ref, uuid = self.ops._connect_to_volume_provider({}, "name")

        self.assertEqual("sr_ref", ref)
        self.assertEqual("uuid", uuid)
        mock_parse.assert_called_once_with({}, "Disk-for:name")
        mock_find_sr.assert_called_once_with(self.session, "uuid")
        mock_introduce_sr.assert_called_once_with(self.session, "uuid",
                                                  "label", "params")

    @mock.patch.object(volume_utils, "introduce_sr")
    @mock.patch.object(volume_utils, "find_sr_by_uuid")
    @mock.patch.object(volume_utils, "parse_sr_info")
    def test_connect_to_volume_provider_old_sr(self, mock_parse, mock_find_sr,
                                               mock_introduce_sr):
        mock_parse.return_value = ("uuid", "label", "params")
        mock_find_sr.return_value = "sr_ref"

        ref, uuid = self.ops._connect_to_volume_provider({}, "name")

        self.assertEqual("sr_ref", ref)
        self.assertEqual("uuid", uuid)
        mock_parse.assert_called_once_with({}, "Disk-for:name")
        mock_find_sr.assert_called_once_with(self.session, "uuid")
        self.assertFalse(mock_introduce_sr.called)

    @mock.patch.object(volume_utils, "introduce_vdi")
    def test_connect_hypervisor_to_volume_regular(self, mock_intro):
        mock_intro.return_value = "vdi"

        result = self.ops._connect_hypervisor_to_volume("sr", {})

        self.assertEqual("vdi", result)
        mock_intro.assert_called_once_with(self.session, "sr")

    @mock.patch.object(volume_utils, "introduce_vdi")
    def test_connect_hypervisor_to_volume_vdi(self, mock_intro):
        mock_intro.return_value = "vdi"

        conn = {"vdi_uuid": "id"}
        result = self.ops._connect_hypervisor_to_volume("sr", conn)

        self.assertEqual("vdi", result)
        mock_intro.assert_called_once_with(self.session, "sr",
                                           vdi_uuid="id")

    @mock.patch.object(volume_utils, "introduce_vdi")
    def test_connect_hypervisor_to_volume_lun(self, mock_intro):
        mock_intro.return_value = "vdi"

        conn = {"target_lun": "lun"}
        result = self.ops._connect_hypervisor_to_volume("sr", conn)

        self.assertEqual("vdi", result)
        mock_intro.assert_called_once_with(self.session, "sr",
                                           target_lun="lun")

    @mock.patch.object(volume_utils, "introduce_vdi")
    @mock.patch.object(volumeops.LOG, 'debug')
    def test_connect_hypervisor_to_volume_mask_password(self, mock_debug,
                                                        mock_intro):
        # Tests that the connection_data is scrubbed before logging.
        data = {'auth_password': 'verybadpass'}
        self.ops._connect_hypervisor_to_volume("sr", data)
        self.assertTrue(mock_debug.called, 'LOG.debug was not called')
        password_logged = False
        for call in mock_debug.call_args_list:
            # The call object is a tuple of (args, kwargs)
            if 'verybadpass' in call[0]:
                password_logged = True
                break
        self.assertFalse(password_logged, 'connection_data was not scrubbed')

    @mock.patch.object(vm_utils, "is_vm_shutdown")
    @mock.patch.object(vm_utils, "create_vbd")
    def test_attach_volume_to_vm_plug(self, mock_vbd, mock_shutdown):
        mock_vbd.return_value = "vbd"
        mock_shutdown.return_value = False

        with mock.patch.object(self.session.VBD, "plug") as mock_plug:
            self.ops._attach_volume_to_vm("vdi", "vm", "name", '/dev/2', True)
            mock_plug.assert_called_once_with("vbd", "vm")

        mock_vbd.assert_called_once_with(self.session, "vm", "vdi", 2,
                                         bootable=False, osvol=True)
        mock_shutdown.assert_called_once_with(self.session, "vm")

    @mock.patch.object(vm_utils, "is_vm_shutdown")
    @mock.patch.object(vm_utils, "create_vbd")
    def test_attach_volume_to_vm_no_plug(self, mock_vbd, mock_shutdown):
        mock_vbd.return_value = "vbd"
        mock_shutdown.return_value = True

        with mock.patch.object(self.session.VBD, "plug") as mock_plug:
            self.ops._attach_volume_to_vm("vdi", "vm", "name", '/dev/2', True)
            self.assertFalse(mock_plug.called)

        mock_vbd.assert_called_once_with(self.session, "vm", "vdi", 2,
                                         bootable=False, osvol=True)
        mock_shutdown.assert_called_once_with(self.session, "vm")

    @mock.patch.object(vm_utils, "is_vm_shutdown")
    @mock.patch.object(vm_utils, "create_vbd")
    def test_attach_volume_to_vm_no_hotplug(self, mock_vbd, mock_shutdown):
        mock_vbd.return_value = "vbd"

        with mock.patch.object(self.session.VBD, "plug") as mock_plug:
            self.ops._attach_volume_to_vm("vdi", "vm", "name", '/dev/2', False)
            self.assertFalse(mock_plug.called)

        mock_vbd.assert_called_once_with(self.session, "vm", "vdi", 2,
                                         bootable=False, osvol=True)
        self.assertFalse(mock_shutdown.called)


class FindBadVolumeTestCase(VolumeOpsTestBase):
    @mock.patch.object(volumeops.VolumeOps, "_get_all_volume_vbd_refs")
    def test_find_bad_volumes_no_vbds(self, mock_get_all):
        mock_get_all.return_value = []

        result = self.ops.find_bad_volumes("vm_ref")

        mock_get_all.assert_called_once_with("vm_ref")
        self.assertEqual([], result)

    @mock.patch.object(volume_utils, "find_sr_from_vbd")
    @mock.patch.object(volumeops.VolumeOps, "_get_all_volume_vbd_refs")
    def test_find_bad_volumes_no_bad_vbds(self, mock_get_all, mock_find_sr):
        mock_get_all.return_value = ["1", "2"]
        mock_find_sr.return_value = "sr_ref"

        with mock.patch.object(self.session.SR, "scan") as mock_scan:
            result = self.ops.find_bad_volumes("vm_ref")

            mock_get_all.assert_called_once_with("vm_ref")
            expected_find = [mock.call(self.session, "1"),
                             mock.call(self.session, "2")]
            self.assertEqual(expected_find, mock_find_sr.call_args_list)
            expected_scan = [mock.call("sr_ref"), mock.call("sr_ref")]
            self.assertEqual(expected_scan, mock_scan.call_args_list)
            self.assertEqual([], result)

    @mock.patch.object(volume_utils, "find_sr_from_vbd")
    @mock.patch.object(volumeops.VolumeOps, "_get_all_volume_vbd_refs")
    def test_find_bad_volumes_bad_vbds(self, mock_get_all, mock_find_sr):
        mock_get_all.return_value = ["vbd_ref"]
        mock_find_sr.return_value = "sr_ref"

        class FakeException(Exception):
            details = ['SR_BACKEND_FAILURE_40', "", "", ""]

        session = mock.Mock()
        session.XenAPI.Failure = FakeException
        self.ops._session = session

        with mock.patch.object(session.SR, "scan") as mock_scan:
            with mock.patch.object(session.VBD,
                                   "get_device") as mock_get:
                mock_scan.side_effect = FakeException
                mock_get.return_value = "xvdb"

                result = self.ops.find_bad_volumes("vm_ref")

                mock_get_all.assert_called_once_with("vm_ref")
                mock_scan.assert_called_once_with("sr_ref")
                mock_get.assert_called_once_with("vbd_ref")
                self.assertEqual(["/dev/xvdb"], result)

    @mock.patch.object(volume_utils, "find_sr_from_vbd")
    @mock.patch.object(volumeops.VolumeOps, "_get_all_volume_vbd_refs")
    def test_find_bad_volumes_raises(self, mock_get_all, mock_find_sr):
        mock_get_all.return_value = ["vbd_ref"]
        mock_find_sr.return_value = "sr_ref"

        class FakeException(Exception):
            details = ['foo', "", "", ""]

        session = mock.Mock()
        session.XenAPI.Failure = FakeException
        self.ops._session = session

        with mock.patch.object(session.SR, "scan") as mock_scan:
            with mock.patch.object(session.VBD,
                                   "get_device") as mock_get:
                mock_scan.side_effect = FakeException
                mock_get.return_value = "xvdb"

                self.assertRaises(FakeException,
                                  self.ops.find_bad_volumes, "vm_ref")
                mock_scan.assert_called_once_with("sr_ref")


class CleanupFromVDIsTestCase(VolumeOpsTestBase):
    def _check_find_purge_calls(self, find_sr_from_vdi, purge_sr, vdi_refs,
            sr_refs):
        find_sr_calls = [mock.call(self.ops._session, vdi_ref) for vdi_ref
                in vdi_refs]
        find_sr_from_vdi.assert_has_calls(find_sr_calls)
        purge_sr_calls = [mock.call(self.ops._session, sr_ref) for sr_ref
                in sr_refs]
        purge_sr.assert_has_calls(purge_sr_calls)

    @mock.patch.object(volume_utils, 'find_sr_from_vdi')
    @mock.patch.object(volume_utils, 'purge_sr')
    def test_safe_cleanup_from_vdis(self, purge_sr, find_sr_from_vdi):
        vdi_refs = ['vdi_ref1', 'vdi_ref2']
        sr_refs = ['sr_ref1', 'sr_ref2']
        find_sr_from_vdi.side_effect = sr_refs
        self.ops.safe_cleanup_from_vdis(vdi_refs)

        self._check_find_purge_calls(find_sr_from_vdi, purge_sr, vdi_refs,
                sr_refs)

    @mock.patch.object(volume_utils, 'find_sr_from_vdi',
            side_effect=[exception.StorageError(reason=''), 'sr_ref2'])
    @mock.patch.object(volume_utils, 'purge_sr')
    def test_safe_cleanup_from_vdis_handles_find_sr_exception(self, purge_sr,
            find_sr_from_vdi):
        vdi_refs = ['vdi_ref1', 'vdi_ref2']
        sr_refs = ['sr_ref2']
        find_sr_from_vdi.side_effect = [exception.StorageError(reason=''),
                sr_refs[0]]
        self.ops.safe_cleanup_from_vdis(vdi_refs)

        self._check_find_purge_calls(find_sr_from_vdi, purge_sr, vdi_refs,
                sr_refs)

    @mock.patch.object(volume_utils, 'find_sr_from_vdi')
    @mock.patch.object(volume_utils, 'purge_sr')
    def test_safe_cleanup_from_vdis_handles_purge_sr_exception(self, purge_sr,
            find_sr_from_vdi):
        vdi_refs = ['vdi_ref1', 'vdi_ref2']
        sr_refs = ['sr_ref1', 'sr_ref2']
        find_sr_from_vdi.side_effect = sr_refs
        purge_sr.side_effect = [test.TestingException, None]
        self.ops.safe_cleanup_from_vdis(vdi_refs)

        self._check_find_purge_calls(find_sr_from_vdi, purge_sr, vdi_refs,
                sr_refs)
