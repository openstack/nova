#    Copyright (C) 2012 Red Hat, Inc.
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

from nova.compute import vm_mode
from nova import exception
from nova import test
from nova.tests.unit import fake_instance


class ComputeVMModeTest(test.NoDBTestCase):

    def _fake_object(self, updates):
        return fake_instance.fake_instance_obj(None, **updates)

    def test_case(self):
        inst = self._fake_object(dict(vm_mode="HVM"))
        mode = vm_mode.get_from_instance(inst)
        self.assertEqual(mode, "hvm")

    def test_legacy_pv(self):
        inst = self._fake_object(dict(vm_mode="pv"))
        mode = vm_mode.get_from_instance(inst)
        self.assertEqual(mode, "xen")

    def test_legacy_hv(self):
        inst = self._fake_object(dict(vm_mode="hv"))
        mode = vm_mode.get_from_instance(inst)
        self.assertEqual(mode, "hvm")

    def test_bogus(self):
        inst = self._fake_object(dict(vm_mode="wibble"))
        self.assertRaises(exception.Invalid,
                          vm_mode.get_from_instance,
                          inst)

    def test_good(self):
        inst = self._fake_object(dict(vm_mode="hvm"))
        mode = vm_mode.get_from_instance(inst)
        self.assertEqual(mode, "hvm")

    def test_name_pv_compat(self):
        mode = vm_mode.canonicalize('pv')
        self.assertEqual(vm_mode.XEN, mode)

    def test_name_hv_compat(self):
        mode = vm_mode.canonicalize('hv')
        self.assertEqual(vm_mode.HVM, mode)

    def test_name_baremetal_compat(self):
        mode = vm_mode.canonicalize('baremetal')
        self.assertEqual(vm_mode.HVM, mode)

    def test_name_hvm(self):
        mode = vm_mode.canonicalize('hvm')
        self.assertEqual(vm_mode.HVM, mode)

    def test_name_none(self):
        mode = vm_mode.canonicalize(None)
        self.assertIsNone(mode)

    def test_name_invalid(self):
        self.assertRaises(exception.InvalidVirtualMachineMode,
                          vm_mode.canonicalize, 'invalid')
