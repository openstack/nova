# Copyright 2016 HPE, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

import nova.network
import nova.network.security_group.openstack_driver as sgapi
import nova.test


class SecurityGroupAPIConfigTest(nova.test.NoDBTestCase):

    @mock.patch('oslo_utils.importutils.import_object')
    def test_caches(self, mock_import):
        sgapi.DRIVER_CACHE = None
        for _ in range(2):
            self.assertIsNotNone(sgapi.get_openstack_security_group_driver())
        mock_import.assert_called_once_with(sgapi.NEUTRON_DRIVER)
