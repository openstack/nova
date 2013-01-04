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

from nova import test
from nova.tests.xenapi import stubs
from nova.virt.xenapi import volumeops


class VolumeAttachTestCase(test.TestCase):
    def test_attach_volume_call(self):
        ops = volumeops.VolumeOps('session')
        self.mox.StubOutWithMock(ops, 'connect_volume')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'vm_ref_or_raise')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'get_device_number')

        volumeops.vm_utils.vm_ref_or_raise('session', 'instance_1').AndReturn(
            'vmref')

        volumeops.volume_utils.get_device_number('mountpoint').AndReturn(
            'devnumber')

        ops.connect_volume(
            'conn_data', 'devnumber', 'instance_1', 'vmref', hotplug=True)

        self.mox.ReplayAll()
        ops.attach_volume(
            dict(driver_volume_type='iscsi', data='conn_data'),
            'instance_1', 'mountpoint')

    def test_attach_volume_no_hotplug(self):
        ops = volumeops.VolumeOps('session')
        self.mox.StubOutWithMock(ops, 'connect_volume')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'vm_ref_or_raise')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'get_device_number')

        volumeops.vm_utils.vm_ref_or_raise('session', 'instance_1').AndReturn(
            'vmref')

        volumeops.volume_utils.get_device_number('mountpoint').AndReturn(
            'devnumber')

        ops.connect_volume(
            'conn_data', 'devnumber', 'instance_1', 'vmref', hotplug=False)

        self.mox.ReplayAll()
        ops.attach_volume(
            dict(driver_volume_type='iscsi', data='conn_data'),
            'instance_1', 'mountpoint', hotplug=False)

    def test_connect_volume_no_hotplug(self):
        session = stubs.FakeSessionForVolumeTests('fake_uri')
        ops = volumeops.VolumeOps(session)
        instance_name = 'instance_1'
        sr_uuid = '1'
        sr_label = 'Disk-for:%s' % instance_name
        sr_params = ''
        sr_ref = 'sr_ref'
        vdi_uuid = '2'
        vdi_ref = 'vdi_ref'
        vbd_ref = 'vbd_ref'
        connection_data = {'vdi_uuid': vdi_uuid}
        vm_ref = 'vm_ref'
        dev_number = 1

        called = {'xenapi': False}

        def fake_call_xenapi(self, *args, **kwargs):
            # Only used for VBD.plug in this code path.
            called['xenapi'] = True
            raise Exception()

        self.stubs.Set(ops._session, 'call_xenapi', fake_call_xenapi)

        self.mox.StubOutWithMock(volumeops.volume_utils, 'parse_sr_info')
        self.mox.StubOutWithMock(ops, 'introduce_sr')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'introduce_vdi')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'create_vbd')

        volumeops.volume_utils.parse_sr_info(
            connection_data, sr_label).AndReturn(
                tuple([sr_uuid, sr_label, sr_params]))

        ops.introduce_sr(sr_uuid, sr_label, sr_params).AndReturn(sr_ref)

        volumeops.volume_utils.introduce_vdi(
            session, sr_ref, vdi_uuid, None).AndReturn(vdi_ref)

        volumeops.vm_utils.create_vbd(
            session, vm_ref, vdi_ref, dev_number,
            bootable=False, osvol=True).AndReturn(vbd_ref)

        self.mox.ReplayAll()

        ops.connect_volume(connection_data, dev_number, instance_name,
                           vm_ref, hotplug=False)

        self.assertEquals(False, called['xenapi'])
