#  Copyright 2014 IBM Corp.
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

from nova import exception
from nova import test
from nova.tests import fake_instance
from nova.virt.hyperv import vmops


class VMOpsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VMOps class."""

    def __init__(self, test_case_name):
        super(VMOpsTestCase, self).__init__(test_case_name)

    def setUp(self):
        super(VMOpsTestCase, self).setUp()
        self.context = 'fake-context'
        self.flags(force_hyperv_utils_v1=True, group='hyperv')
        self.flags(force_volumeutils_v1=True, group='hyperv')
        self._vmops = vmops.VMOps()

    def test_attach_config_drive(self):
        instance = fake_instance.fake_instance_obj(self.context)
        self.assertRaises(exception.InvalidDiskFormat,
                          self._vmops.attach_config_drive,
                          instance, 'C:/fake_instance_dir/configdrive.xxx')
