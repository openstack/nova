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

import os

import mock

from nova.compute import arch
from nova import exception
from nova import test


class ArchTest(test.NoDBTestCase):

    @mock.patch.object(os, "uname")
    def test_host(self, mock_uname):
        os.uname.return_value = (
            'Linux',
            'localhost.localdomain',
            '3.14.8-200.fc20.x86_64',
            '#1 SMP Mon Jun 16 21:57:53 UTC 2014',
            'i686'
        )

        self.assertEqual(arch.I686, arch.from_host())

    def test_valid_string(self):
        self.assertTrue(arch.is_valid("x86_64"))

    def test_valid_constant(self):
        self.assertTrue(arch.is_valid(arch.X86_64))

    def test_valid_bogus(self):
        self.assertFalse(arch.is_valid("x86_64wibble"))

    def test_canonicalize_i386(self):
        self.assertEqual(arch.I686, arch.canonicalize("i386"))

    def test_canonicalize_amd64(self):
        self.assertEqual(arch.X86_64, arch.canonicalize("amd64"))

    def test_canonicalize_case(self):
        self.assertEqual(arch.X86_64, arch.canonicalize("X86_64"))

    def test_canonicalize_compat_xen1(self):
        self.assertEqual(arch.I686, arch.canonicalize("x86_32"))

    def test_canonicalize_compat_xen2(self):
        self.assertEqual(arch.I686, arch.canonicalize("x86_32p"))

    def test_canonicalize_bogus(self):
        self.assertRaises(exception.InvalidArchitectureName,
                          arch.canonicalize,
                          "x86_64wibble")
