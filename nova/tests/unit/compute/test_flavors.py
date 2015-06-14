# Copyright 2014 IBM Corp.
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

"""Tests for flavor basic functions"""

from nova.compute import flavors
from nova import exception
from nova import test


class ExtraSpecTestCase(test.NoDBTestCase):
    def _flavor_validate_extra_spec_keys_invalid_input(self, key_name_list):
        self.assertRaises(exception.InvalidInput,
            flavors.validate_extra_spec_keys, key_name_list)

    def test_flavor_validate_extra_spec_keys_invalid_input(self):
        lists = [['', ], ['*', ], ['+', ]]
        for x in lists:
            self._flavor_validate_extra_spec_keys_invalid_input(x)

    def test_flavor_validate_extra_spec_keys(self):
        key_name_list = ['abc', 'ab c', 'a-b-c', 'a_b-c', 'a:bc']
        flavors.validate_extra_spec_keys(key_name_list)


class CreateFlavorTestCase(test.NoDBTestCase):
    def test_create_flavor_ram_error(self):
        args = ("ram_test", "9999999999", "1", "10", "1")
        try:
            flavors.create(*args)
            self.fail("Be sure this will never be executed.")
        except exception.InvalidInput as e:
            self.assertIn("ram", e.message)

    def test_create_flavor_disk_error(self):
        args = ("disk_test", "1024", "1", "9999999999", "1")
        try:
            flavors.create(*args)
            self.fail("Be sure this will never be executed.")
        except exception.InvalidInput as e:
            self.assertIn("disk", e.message)

    def test_create_flavor_ephemeral_error(self):
        args = ("ephemeral_test", "1024", "1", "10", "9999999999")
        try:
            flavors.create(*args)
            self.fail("Be sure this will never be executed.")
        except exception.InvalidInput as e:
            self.assertIn("ephemeral", e.message)
