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

from nova.compute import vm_states
from nova import exception
from nova import test
from nova.tests.unit.virt.vmwareapi import fake as vmwareapi_fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import vm_util
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

    def _fake_call_get_dynamic_property(self, uuid, result):
        def fake_call_method(vim, method, vm_ref, type, prop):
            expected_prop = 'config.extraConfig["volume-%s"]' % uuid
            self.assertEqual('VirtualMachine', type)
            self.assertEqual(expected_prop, prop)
            return result
        return fake_call_method

    def test_get_volume_uuid(self):
        vm_ref = mock.Mock()
        uuid = '1234'
        opt_val = vmwareapi_fake.OptionValue('volume-%s' % uuid, 'volume-val')
        fake_call = self._fake_call_get_dynamic_property(uuid, opt_val)
        with mock.patch.object(self._session, "_call_method", fake_call):
            val = self._volumeops._get_volume_uuid(vm_ref, uuid)
            self.assertEqual('volume-val', val)

    def test_get_volume_uuid_not_found(self):
        vm_ref = mock.Mock()
        uuid = '1234'
        fake_call = self._fake_call_get_dynamic_property(uuid, None)
        with mock.patch.object(self._session, "_call_method", fake_call):
            val = self._volumeops._get_volume_uuid(vm_ref, uuid)
            self.assertIsNone(val)

    def test_attach_volume_vmdk_invalid(self):
        connection_info = {'driver_volume_type': 'vmdk',
                           'serial': 'volume-fake-id',
                           'data': {'volume': 'vm-10',
                                    'volume_id': 'volume-fake-id'}}
        instance = mock.MagicMock(name='fake-name', vm_state=vm_states.ACTIVE)
        path_and_type = ('fake-path', 'ide', 'preallocated')
        with contextlib.nested(
            mock.patch.object(vm_util, 'get_vm_ref'),
            mock.patch.object(self._volumeops, '_get_volume_ref'),
            mock.patch.object(vm_util, 'get_vmdk_path_and_adapter_type',
                              return_value=path_and_type)
        ) as (get_vm_ref, get_volume_ref, get_vmdk_path_and_adapter_type):
            self.assertRaises(exception.Invalid,
                self._volumeops._attach_volume_vmdk, connection_info,
                instance)

            get_vm_ref.assert_called_once_with(self._volumeops._session,
                                               instance)
            get_volume_ref.assert_called_once_with(
                connection_info['data']['volume'])
            self.assertTrue(get_vmdk_path_and_adapter_type.called)

    def test_detach_volume_vmdk_invalid(self):
        connection_info = {'driver_volume_type': 'vmdk',
                           'serial': 'volume-fake-id',
                           'data': {'volume': 'vm-10',
                                    'volume_id': 'volume-fake-id'}}
        instance = mock.MagicMock(name='fake-name', vm_state=vm_states.ACTIVE)
        path_and_type = ('fake-path', 'ide', 'preallocated')
        with contextlib.nested(
            mock.patch.object(vm_util, 'get_vm_ref',
                              return_value=mock.sentinel.vm_ref),
            mock.patch.object(self._volumeops, '_get_volume_ref'),
            mock.patch.object(self._volumeops,
                              '_get_vmdk_backed_disk_device'),
            mock.patch.object(vm_util, 'get_vmdk_path_and_adapter_type',
                              return_value=path_and_type)
        ) as (get_vm_ref, get_volume_ref, get_vmdk_backed_disk_device,
              get_vmdk_path_and_adapter_type):
            self.assertRaises(exception.Invalid,
                self._volumeops._detach_volume_vmdk, connection_info,
                instance)

            get_vm_ref.assert_called_once_with(self._volumeops._session,
                                               instance)
            get_volume_ref.assert_called_once_with(
                connection_info['data']['volume'])
            get_vmdk_backed_disk_device.assert_called_once_with(
                mock.sentinel.vm_ref, connection_info['data'])
            self.assertTrue(get_vmdk_path_and_adapter_type.called)
