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

import collections
import mock

from nova import exception
from nova import test
from nova.tests.virt.xenapi import stubs
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import volumeops


class VolumeAttachTestCase(test.NoDBTestCase):
    def test_detach_volume_call(self):
        registered_calls = []

        def regcall(label):
            def side_effect(*args, **kwargs):
                registered_calls.append(label)
            return side_effect

        ops = volumeops.VolumeOps('session')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'lookup')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'find_vbd_by_number')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'is_vm_shutdown')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'unplug_vbd')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'destroy_vbd')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'get_device_number')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'find_sr_from_vbd')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'purge_sr')

        volumeops.vm_utils.lookup('session', 'instance_1').AndReturn(
            'vmref')

        volumeops.volume_utils.get_device_number('mountpoint').AndReturn(
            'devnumber')

        volumeops.vm_utils.find_vbd_by_number(
            'session', 'vmref', 'devnumber').AndReturn('vbdref')

        volumeops.vm_utils.is_vm_shutdown('session', 'vmref').AndReturn(
            False)

        volumeops.vm_utils.unplug_vbd('session', 'vbdref', 'vmref')

        volumeops.vm_utils.destroy_vbd('session', 'vbdref').WithSideEffects(
            regcall('destroy_vbd'))

        volumeops.volume_utils.find_sr_from_vbd(
            'session', 'vbdref').WithSideEffects(
                regcall('find_sr_from_vbd')).AndReturn('srref')

        volumeops.volume_utils.purge_sr('session', 'srref')

        self.mox.ReplayAll()

        ops.detach_volume(
            dict(driver_volume_type='iscsi', data='conn_data'),
            'instance_1', 'mountpoint')

        self.assertEqual(
            ['find_sr_from_vbd', 'destroy_vbd'], registered_calls)

    def test_attach_volume_call(self):
        ops = volumeops.VolumeOps('session')
        self.mox.StubOutWithMock(ops, '_attach_volume')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'vm_ref_or_raise')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'get_device_number')

        connection_info = dict(driver_volume_type='iscsi', data='conn_data')

        volumeops.vm_utils.vm_ref_or_raise('session', 'instance_1').AndReturn(
            'vmref')

        volumeops.volume_utils.get_device_number('mountpoint').AndReturn(
            'devnumber')

        ops._connect_volume(
            connection_info, 'devnumber', 'instance_1', 'vmref',
            hotplug=True).AndReturn(('sruuid', 'vdiuuid'))

        self.mox.ReplayAll()
        ops.attach_volume(
            connection_info,
            'instance_1', 'mountpoint')

    def test_attach_volume_no_hotplug(self):
        ops = volumeops.VolumeOps('session')
        self.mox.StubOutWithMock(ops, '_attach_volume')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'vm_ref_or_raise')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'get_device_number')

        connection_info = dict(driver_volume_type='iscsi', data='conn_data')

        volumeops.vm_utils.vm_ref_or_raise('session', 'instance_1').AndReturn(
            'vmref')

        volumeops.volume_utils.get_device_number('mountpoint').AndReturn(
            'devnumber')

        ops._attach_volume(
            connection_info, 'vmref', 'instance_1', 'devnumber',
            False).AndReturn(('sruuid', 'vdiuuid'))

        self.mox.ReplayAll()
        ops.attach_volume(
            connection_info,
            'instance_1', 'mountpoint', hotplug=False)

    def _test_connect_volume(self, hotplug, vm_running, plugged):
        session = stubs.FakeSessionForVolumeTests('fake_uri')
        ops = volumeops.VolumeOps(session)

        self.mox.StubOutWithMock(volumeops.volume_utils, 'parse_sr_info')
        self.mox.StubOutWithMock(
            volumeops.volume_utils, 'find_sr_by_uuid')
        self.mox.StubOutWithMock(
            volumeops.volume_utils, 'introduce_sr')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'introduce_vdi')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'create_vbd')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'is_vm_shutdown')
        self.mox.StubOutWithMock(ops._session.VBD, 'plug')
        self.mox.StubOutWithMock(ops._session.VDI, 'get_uuid')

        instance_name = 'instance_1'
        sr_uuid = '1'
        sr_label = 'Disk-for:%s' % instance_name
        sr_params = ''
        sr_ref = 'sr_ref'
        vdi_uuid = '2'
        vdi_ref = 'vdi_ref'
        vbd_ref = 'vbd_ref'
        connection_data = {'vdi_uuid': vdi_uuid}
        connection_info = {'data': connection_data,
                           'driver_volume_type': 'iscsi'}
        vm_ref = 'vm_ref'
        dev_number = 1

        volumeops.volume_utils.parse_sr_info(
            connection_data, sr_label).AndReturn(
                tuple([sr_uuid, sr_label, sr_params]))
        volumeops.volume_utils.find_sr_by_uuid(session, sr_uuid).AndReturn(
                None)
        volumeops.volume_utils.introduce_sr(
            session, sr_uuid, sr_label, sr_params).AndReturn(sr_ref)
        volumeops.volume_utils.introduce_vdi(
            session, sr_ref, vdi_uuid=vdi_uuid).AndReturn(vdi_ref)
        volumeops.vm_utils.create_vbd(
            session, vm_ref, vdi_ref, dev_number,
            bootable=False, osvol=True).AndReturn(vbd_ref)
        if hotplug:
            volumeops.vm_utils.is_vm_shutdown(session,
                vm_ref).AndReturn(not vm_running)
        if plugged:
            ops._session.VBD.plug(vbd_ref, vm_ref)
        ops._session.VDI.get_uuid(vdi_ref).AndReturn(vdi_uuid)

        self.mox.ReplayAll()

        result = ops._connect_volume(connection_info, dev_number,
            instance_name, vm_ref, hotplug=hotplug)
        self.assertEqual((sr_uuid, vdi_uuid), result)

    def test_connect_volume_no_hotplug_vm_running(self):
        self._test_connect_volume(hotplug=False, vm_running=True,
                                   plugged=False)

    def test_connect_volume_no_hotplug_vm_not_running(self):
        self._test_connect_volume(hotplug=False, vm_running=False,
                                   plugged=False)

    def test_connect_volume_hotplug_vm_stopped(self):
        self._test_connect_volume(hotplug=True, vm_running=False,
                                   plugged=False)

    def test_connect_volume_hotplug_vm_running(self):
        self._test_connect_volume(hotplug=True, vm_running=True,
                                   plugged=True)

    def test_connect_volume(self):
        session = stubs.FakeSessionForVolumeTests('fake_uri')
        ops = volumeops.VolumeOps(session)
        sr_uuid = '1'
        sr_label = 'Disk-for:None'
        sr_params = ''
        sr_ref = 'sr_ref'
        vdi_uuid = '2'
        vdi_ref = 'vdi_ref'
        connection_data = {'vdi_uuid': vdi_uuid}
        connection_info = {'data': connection_data,
                           'driver_volume_type': 'iscsi'}

        called = collections.defaultdict(bool)

        def fake_call_xenapi(self, method, *args, **kwargs):
            called[method] = True

        self.stubs.Set(ops._session, 'call_xenapi', fake_call_xenapi)

        self.mox.StubOutWithMock(volumeops.volume_utils, 'parse_sr_info')
        volumeops.volume_utils.parse_sr_info(
            connection_data, sr_label).AndReturn(
                tuple([sr_uuid, sr_label, sr_params]))

        self.mox.StubOutWithMock(
            volumeops.volume_utils, 'find_sr_by_uuid')
        volumeops.volume_utils.find_sr_by_uuid(session, sr_uuid).AndReturn(
                None)

        self.mox.StubOutWithMock(
            volumeops.volume_utils, 'introduce_sr')
        volumeops.volume_utils.introduce_sr(
            session, sr_uuid, sr_label, sr_params).AndReturn(sr_ref)

        self.mox.StubOutWithMock(volumeops.volume_utils, 'introduce_vdi')
        volumeops.volume_utils.introduce_vdi(
            session, sr_ref, vdi_uuid=vdi_uuid).AndReturn(vdi_ref)

        self.mox.ReplayAll()

        ops.connect_volume(connection_info)

        self.assertEqual(False, called['VBD.plug'])


class AttachVolumeTestCase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(AttachVolumeTestCase, self).setUp()
        self._setup_mock_volumeops()
        self.vms = []

    def _setup_mock_volumeops(self):
        self.session = stubs.FakeSessionForVolumeTests('fake_uri')
        self.ops = volumeops.VolumeOps(self.session)

    @mock.patch.object(volumeops.VolumeOps, "_attach_volume")
    @mock.patch.object(vm_utils, "vm_ref_or_raise")
    def test_attach_volume_default_hotplug(self, mock_get_vm, mock_attach):
        mock_get_vm.return_value = "vm_ref"

        self.ops.attach_volume({}, "instance_name", "/dev/xvda")

        mock_attach.assert_called_once_with({}, "vm_ref", "instance_name", 0,
                                            True)

    @mock.patch.object(volumeops.VolumeOps, "_attach_volume")
    @mock.patch.object(vm_utils, "vm_ref_or_raise")
    def test_attach_volume_hotplug(self, mock_get_vm, mock_attach):
        mock_get_vm.return_value = "vm_ref"

        self.ops.attach_volume({}, "instance_name", "/dev/xvda", False)

        mock_attach.assert_called_once_with({}, "vm_ref", "instance_name", 0,
                                            False)

    @mock.patch.object(volumeops.VolumeOps, "_attach_volume")
    def test_attach_volume_default_hotplug(self, mock_attach):
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

    def test_check_is_supported_driver_type_pass_iscsi(self):
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

    @mock.patch.object(vm_utils, "is_vm_shutdown")
    @mock.patch.object(vm_utils, "create_vbd")
    def test_attach_volume_to_vm_plug(self, mock_vbd, mock_shutdown):
        mock_vbd.return_value = "vbd"
        mock_shutdown.return_value = False

        with mock.patch.object(self.session.VBD, "plug") as mock_plug:
            self.ops._attach_volume_to_vm("vdi", "vm", "name", 2, True)
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
            self.ops._attach_volume_to_vm("vdi", "vm", "name", 2, True)
            self.assertFalse(mock_plug.called)

        mock_vbd.assert_called_once_with(self.session, "vm", "vdi", 2,
                                         bootable=False, osvol=True)
        mock_shutdown.assert_called_once_with(self.session, "vm")

    @mock.patch.object(vm_utils, "is_vm_shutdown")
    @mock.patch.object(vm_utils, "create_vbd")
    def test_attach_volume_to_vm_no_hotplug(self, mock_vbd, mock_shutdown):
        mock_vbd.return_value = "vbd"

        with mock.patch.object(self.session.VBD, "plug") as mock_plug:
            self.ops._attach_volume_to_vm("vdi", "vm", "name", 2, False)
            self.assertFalse(mock_plug.called)

        mock_vbd.assert_called_once_with(self.session, "vm", "vdi", 2,
                                         bootable=False, osvol=True)
        self.assertFalse(mock_shutdown.called)
