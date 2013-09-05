# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Cloudbase Solutions Srl
# All Rights Reserved.
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

from nova import test

from nova.virt.hyperv import vmutils


class VMUtilsTestCase(test.TestCase):
    """Unit tests for the Hyper-V VMUtils class."""

    _FAKE_VM_NAME = 'fake_vm'
    _FAKE_MEMORY_MB = 2
    _FAKE_VM_PATH = "fake_vm_path"

    def setUp(self):
        self._vmutils = vmutils.VMUtils()
        self._vmutils._conn = mock.MagicMock()

        super(VMUtilsTestCase, self).setUp()

    def test_enable_vm_metrics_collection(self):
        self.assertRaises(NotImplementedError,
                          self._vmutils.enable_vm_metrics_collection,
                          self._FAKE_VM_NAME)

    def _lookup_vm(self):
        mock_vm = mock.MagicMock()
        self._vmutils._lookup_vm_check = mock.MagicMock(
            return_value=mock_vm)
        mock_vm.path_.return_value = self._FAKE_VM_PATH
        return mock_vm

    def test_set_vm_memory_static(self):
        self._test_set_vm_memory_dynamic(1.0)

    def test_set_vm_memory_dynamic(self):
        self._test_set_vm_memory_dynamic(2.0)

    def _test_set_vm_memory_dynamic(self, dynamic_memory_ratio):
        mock_vm = self._lookup_vm()

        mock_s = self._vmutils._conn.Msvm_VirtualSystemSettingData()[0]
        mock_s.SystemType = 3

        mock_vmsetting = mock.MagicMock()
        mock_vmsetting.associators.return_value = [mock_s]

        self._vmutils._modify_virt_resource = mock.MagicMock()

        self._vmutils._set_vm_memory(mock_vm, mock_vmsetting,
                                     self._FAKE_MEMORY_MB,
                                     dynamic_memory_ratio)

        self._vmutils._modify_virt_resource.assert_called_with(
            mock_s, self._FAKE_VM_PATH)

        if dynamic_memory_ratio > 1:
            self.assertTrue(mock_s.DynamicMemoryEnabled)
        else:
            self.assertFalse(mock_s.DynamicMemoryEnabled)
