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

from nova.openstack.common import jsonutils
from nova.scheduler import baremetal_host_manager
from nova.scheduler import host_manager
from nova import test


class BaremetalHostManagerTestCase(test.NoDBTestCase):
    """Test case for BaremetalHostManager class."""

    def setUp(self):
        super(BaremetalHostManagerTestCase, self).setUp()
        self.host_manager = baremetal_host_manager.BaremetalHostManager()

    def test_manager_public_api_signatures(self):
        self.assertPublicAPISignatures(host_manager.HostManager(),
                                       self.host_manager)

    def test_state_public_api_signatures(self):
        self.assertPublicAPISignatures(
            host_manager.HostState("dummy",
                                   "dummy"),
            baremetal_host_manager.BaremetalNodeState("dummy",
                                                      "dummy")
        )

    @mock.patch.object(baremetal_host_manager.BaremetalNodeState, '__init__')
    def test_create_baremetal_node_state(self, init_mock):
        init_mock.return_value = None
        compute = {'cpu_info': 'baremetal cpu'}
        host_state = self.host_manager.host_state_cls('fake-host', 'fake-node',
                                                      compute=compute)
        self.assertIs(baremetal_host_manager.BaremetalNodeState,
                      type(host_state))

    @mock.patch.object(host_manager.HostState, '__init__')
    def test_create_non_baremetal_host_state(self, init_mock):
        init_mock.return_value = None
        compute = {'cpu_info': 'other cpu'}
        host_state = self.host_manager.host_state_cls('fake-host', 'fake-node',
                                                      compute=compute)
        self.assertIs(host_manager.HostState, type(host_state))


class BaremetalNodeStateTestCase(test.NoDBTestCase):
    """Test case for BaremetalNodeState class."""

    def test_update_from_compute_node(self):
        stats = {'cpu_arch': 'cpu_arch'}
        json_stats = jsonutils.dumps(stats)
        compute_node = {'memory_mb': 1024, 'free_disk_gb': 10,
                        'free_ram_mb': 1024, 'vcpus': 1, 'vcpus_used': 0,
                        'stats': json_stats}

        host = baremetal_host_manager.BaremetalNodeState('fakehost',
                                                         'fakenode')
        host.update_from_compute_node(compute_node)

        self.assertEqual(compute_node['free_ram_mb'], host.free_ram_mb)
        self.assertEqual(compute_node['memory_mb'], host.total_usable_ram_mb)
        self.assertEqual(compute_node['free_disk_gb'] * 1024,
                         host.free_disk_mb)
        self.assertEqual(compute_node['vcpus'], host.vcpus_total)
        self.assertEqual(compute_node['vcpus_used'], host.vcpus_used)
        self.assertEqual(stats, host.stats)
