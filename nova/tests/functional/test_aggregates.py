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

from nova.tests.functional import integrated_helpers


class AggregatesTest(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2'
    ADMIN_API = True

    def _add_hosts_to_aggregate(self):
        """List all compute services and add them all to an aggregate."""

        compute_services = [s for s in self.api.get_services()
                            if s['binary'] == 'nova-compute']
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        for service in compute_services:
            self.api.add_host_to_aggregate(agg['id'], service['host'])
        return len(compute_services)

    def test_add_hosts(self):
        # Default case with one compute, mapped for us
        self.assertEqual(1, self._add_hosts_to_aggregate())

    def test_add_unmapped_host(self):
        """Ensure that hosts without mappings are still found and added"""

        # Add another compute, but nuke its HostMapping
        self.start_service('compute', host='compute2')
        self.host_mappings['compute2'].destroy()
        self.assertEqual(2, self._add_hosts_to_aggregate())
