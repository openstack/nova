# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import test
from nova.tests.virt.xenapi import stubs
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

        volumeops.vm_utils.unplug_vbd('session', 'vbdref')

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

        self.assertEquals(
            ['find_sr_from_vbd', 'destroy_vbd'], registered_calls)

    def test_attach_volume_call(self):
        ops = volumeops.VolumeOps('session')
        self.mox.StubOutWithMock(ops, '_connect_volume')
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
        self.mox.StubOutWithMock(ops, '_connect_volume')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'vm_ref_or_raise')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'get_device_number')

        connection_info = dict(driver_volume_type='iscsi', data='conn_data')

        volumeops.vm_utils.vm_ref_or_raise('session', 'instance_1').AndReturn(
            'vmref')

        volumeops.volume_utils.get_device_number('mountpoint').AndReturn(
            'devnumber')

        ops._connect_volume(
            connection_info, 'devnumber', 'instance_1', 'vmref',
            hotplug=False).AndReturn(('sruuid', 'vdiuuid'))

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
        self.mox.StubOutWithMock(ops._session, 'call_xenapi')

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
        volumeops.vm_utils.is_vm_shutdown(session,
            vm_ref).AndReturn(not vm_running)
        if plugged:
            ops._session.call_xenapi("VBD.plug", vbd_ref)
        ops._session.call_xenapi("VDI.get_uuid",
            vdi_ref).AndReturn(vdi_uuid)

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
        vbd_ref = 'vbd_ref'
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

        self.assertEquals(False, called['VBD.plug'])
