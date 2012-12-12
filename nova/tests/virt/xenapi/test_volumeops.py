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
from nova.virt.xenapi import volumeops


class VolumeAttachTestCase(test.TestCase):
    def test_connect_volume_call(self):
        ops = volumeops.VolumeOps('session')
        self.mox.StubOutWithMock(ops, 'connect_volume')
        self.mox.StubOutWithMock(volumeops.vm_utils, 'vm_ref_or_raise')
        self.mox.StubOutWithMock(volumeops.volume_utils, 'get_device_number')

        volumeops.vm_utils.vm_ref_or_raise('session', 'instance_1').AndReturn(
            'vmref')

        volumeops.volume_utils.get_device_number('mountpoint').AndReturn(
            'devnumber')

        ops.connect_volume('conn_data', 'devnumber', 'instance_1', 'vmref')

        self.mox.ReplayAll()
        ops.attach_volume(
            dict(driver_volume_type='iscsi', data='conn_data'),
            'instance_1', 'mountpoint')
