# Copyright (c) 2014 OpenStack Foundation
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
"""
Tests For BaremetalHostManager
"""
import mock

from nova.scheduler import baremetal_host_manager
from nova.scheduler import host_manager
from nova import test


class BaremetalHostManagerTestCase(test.NoDBTestCase):
    """Test case for BaremetalHostManager class."""

    def setUp(self):
        super(BaremetalHostManagerTestCase, self).setUp()
        self.host_manager = baremetal_host_manager.BaremetalHostManager()

    @mock.patch.object(baremetal_host_manager.BaremetalNodeState,
                       'update_from_compute_node')
    def test_create_baremetal_node_state(self, update_mock):
        compute = {'cpu_info': 'baremetal cpu'}
        host_state = self.host_manager.host_state_cls('fake-host', 'fake-node',
                                                      compute)
        self.assertIs(baremetal_host_manager.BaremetalNodeState,
                      type(host_state))

    @mock.patch.object(host_manager.HostState, 'update_from_compute_node')
    def test_create_non_baremetal_host_state(self, update_mock):
        compute = {'cpu_info': 'other cpu'}
        host_state = self.host_manager.host_state_cls('fake-host', 'fake-node',
                                                      compute)
        self.assertIs(host_manager.HostState, type(host_state))
