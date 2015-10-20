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

from nova import objects
from nova import test
from nova.virt import configdrive


class ConfigDriveTestCase(test.NoDBTestCase):
    def test_instance_force(self):
        self.flags(force_config_drive=False)

        instance = objects.Instance(
            config_drive="yes",
            system_metadata={
                "image_img_config_drive": "mandatory",
            }
        )

        self.assertTrue(configdrive.required_by(instance))

    def test_image_meta_force(self):
        self.flags(force_config_drive=False)

        instance = objects.Instance(
            config_drive=None,
            system_metadata={
                "image_img_config_drive": "mandatory",
            }
        )

        self.assertTrue(configdrive.required_by(instance))

    def test_config_flag_force(self):
        self.flags(force_config_drive=True)

        instance = objects.Instance(
            config_drive=None,
            system_metadata={
                "image_img_config_drive": "optional",
            }
        )

        self.assertTrue(configdrive.required_by(instance))

    def test_no_config_drive(self):
        self.flags(force_config_drive=False)

        instance = objects.Instance(
            config_drive=None,
            system_metadata={
                "image_img_config_drive": "optional",
            }
        )

        self.assertFalse(configdrive.required_by(instance))
