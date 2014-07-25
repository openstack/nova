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

from nova.compute import hvtype
from nova import exception
from nova import test


class HvTypeTest(test.NoDBTestCase):

    def test_valid_string(self):
        self.assertTrue(hvtype.is_valid("vmware"))

    def test_valid_constant(self):
        self.assertTrue(hvtype.is_valid(hvtype.QEMU))

    def test_valid_bogus(self):
        self.assertFalse(hvtype.is_valid("acmehypervisor"))

    def test_canonicalize_none(self):
        self.assertIsNone(hvtype.canonicalize(None))

    def test_canonicalize_case(self):
        self.assertEqual(hvtype.QEMU, hvtype.canonicalize("QeMu"))

    def test_canonicalize_xapi(self):
        self.assertEqual(hvtype.XEN, hvtype.canonicalize("xapi"))

    def test_canonicalize_invalid(self):
        self.assertRaises(exception.InvalidHypervisorVirtType,
                          hvtype.canonicalize,
                          "wibble")
