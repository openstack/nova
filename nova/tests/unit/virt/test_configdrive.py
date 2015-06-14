#    Copyright 2014 IBM Corp.
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

from oslo_utils import strutils

from nova import test
from nova.virt import configdrive


class ConfigDriveTestCase(test.NoDBTestCase):
    def test_valid_string_values(self):
        for value in (strutils.TRUE_STRINGS + ('always',)):
            self.flags(force_config_drive=value)
            self.assertTrue(configdrive.required_by({}))

    def test_invalid_string_values(self):
        for value in (strutils.FALSE_STRINGS + ('foo',)):
            self.flags(force_config_drive=value)
            self.assertFalse(configdrive.required_by({}))
