#    Copyright (C) 2014 Red Hat, Inc.
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

from nova.compute import hv_type
from nova import exception
from nova import test


class HvTypeTest(test.NoDBTestCase):

    def test_valid_string(self):
        self.assertTrue(hv_type.is_valid("vmware"))

    def test_valid_constant(self):
        self.assertTrue(hv_type.is_valid(hv_type.QEMU))

    def test_valid_docker(self):
        self.assertTrue(hv_type.is_valid("docker"))

    def test_valid_lxd(self):
        self.assertTrue(hv_type.is_valid("lxd"))

    def test_valid_vz(self):
        self.assertTrue(hv_type.is_valid(hv_type.VIRTUOZZO))

    def test_valid_bogus(self):
        self.assertFalse(hv_type.is_valid("acmehypervisor"))

    def test_canonicalize_none(self):
        self.assertIsNone(hv_type.canonicalize(None))

    def test_canonicalize_case(self):
        self.assertEqual(hv_type.QEMU, hv_type.canonicalize("QeMu"))

    def test_canonicalize_xapi(self):
        self.assertEqual(hv_type.XEN, hv_type.canonicalize("xapi"))

    def test_canonicalize_invalid(self):
        self.assertRaises(exception.InvalidHypervisorVirtType,
                          hv_type.canonicalize,
                          "wibble")
