#    Copyright 2013 IBM Corp.
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

import contextlib
import mock

from nova import test
from nova.tests.virt.vmwareapi import stubs
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import volumeops


class VMwareVolumeOpsTestCase(test.NoDBTestCase):

    def setUp(self):

        super(VMwareVolumeOpsTestCase, self).setUp()
        vmwareapi_fake.reset()
        stubs.set_stubs(self.stubs)
        self._session = driver.VMwareAPISession()

        self._volumeops = volumeops.VMwareVolumeOps(self._session)
        self.instance = {'name': 'fake_name', 'uuid': 'fake_uuid'}

    def _test_detach_disk_from_vm(self, destroy_disk=False):
        def fake_call_method(module, method, *args, **kwargs):
            vmdk_detach_config_spec = kwargs.get('spec')
            virtual_device_config = vmdk_detach_config_spec.deviceChange[0]
            self.assertEqual('remove', virtual_device_config.operation)
            self.assertEqual('ns0:VirtualDeviceConfigSpec',
                              virtual_device_config.obj_name)
            if destroy_disk:
                self.assertEqual('destroy',
                                 virtual_device_config.fileOperation)
            else:
                self.assertFalse(hasattr(virtual_device_config,
                                 'fileOperation'))
            return 'fake_configure_task'
        with contextlib.nested(
            mock.patch.object(self._session, '_wait_for_task'),
            mock.patch.object(self._session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            fake_device = vmwareapi_fake.DataObject()
            fake_device.backing = vmwareapi_fake.DataObject()
            fake_device.backing.fileName = 'fake_path'
            fake_device.key = 'fake_key'
            self._volumeops.detach_disk_from_vm('fake_vm_ref', self.instance,
                                                fake_device, destroy_disk)
            _wait_for_task.assert_has_calls([
                   mock.call('fake_configure_task')])

    def test_detach_with_destroy_disk_from_vm(self):
        self._test_detach_disk_from_vm(destroy_disk=True)

    def test_detach_without_destroy_disk_from_vm(self):
        self._test_detach_disk_from_vm(destroy_disk=False)
