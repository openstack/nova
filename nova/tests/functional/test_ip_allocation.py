# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.tests.functional import integrated_helpers


class IPAllocationTests(integrated_helpers._IntegratedTestBase):
    """Test behavior with various IP allocation policies.

    This mainly exists to test the 'deferred' and 'none' policies.
    """
    compute_driver = 'fake.MediumFakeDriver'
    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        super().setUp()

        # add a port with an ip_allocation of 'none'
        port = {
            'name': '',
            'description': '',
            'network_id': self.neutron.network_1['id'],
            'admin_state_up': True,
            'status': 'ACTIVE',
            'mac_address': 'ee:94:88:57:d5:7a',
            # The ip_allocation is 'none', so fixed_ips should be null
            'fixed_ips': [],
            'tenant_id': self.neutron.tenant_id,
            'project_id': self.neutron.tenant_id,
            'device_id': '',
            'binding:profile': {},
            'binding:vnic_type': 'normal',
            'binding:vif_type': 'ovs',
            'binding:vif_details': {},
            'ip_allocation': 'none',
        }
        created_port = self.neutron.create_port({'port': port})
        self.port_id = created_port['port']['id']

    def test_boot_with_none_policy(self):
        """Create a port with the 'none' policy."""
        self._create_server(
            networks=[{'port': self.port_id}])
