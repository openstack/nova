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

import mock

from nova import test
from nova.tests import fake_instance
from nova.virt.hyperv import migrationops
from nova.virt.hyperv import vmutils


class MigrationOpsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V MigrationOps class."""

    def setUp(self):
        super(MigrationOpsTestCase, self).setUp()
        self.context = 'fake-context'
        self.flags(force_hyperv_utils_v1=True, group='hyperv')
        self.flags(force_volumeutils_v1=True, group='hyperv')
        self._migrationops = migrationops.MigrationOps()

    def test_check_and_attach_config_drive_unknown_path(self):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.config_drive = 'True'
        self._migrationops._pathutils.lookup_configdrive_path = mock.MagicMock(
            return_value=None)
        self.assertRaises(vmutils.HyperVException,
                          self._migrationops._check_and_attach_config_drive,
                          instance)
