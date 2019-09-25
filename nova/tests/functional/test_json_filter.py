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

from oslo_serialization import jsonutils

from nova import conf
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers

CONF = conf.CONF


class JsonFilterTestCase(integrated_helpers.ProviderUsageBaseTestCase):
    """Functional tests for the JsonFilter scheduler filter."""

    microversion = '2.1'
    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        # Need to enable the JsonFilter before starting the scheduler service
        # in the parent class.
        enabled_filters = CONF.filter_scheduler.enabled_filters
        if 'JsonFilter' not in enabled_filters:
            enabled_filters.append('JsonFilter')
            self.flags(enabled_filters=enabled_filters,
                       group='filter_scheduler')

        # Use our custom weigher defined above to make sure that we have
        # a predictable scheduling sort order during server create.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())

        super(JsonFilterTestCase, self).setUp()

        # Now create two compute services which will have unique host and
        # node names.
        self._start_compute('host1')
        self._start_compute('host2')

    def test_filter_on_hypervisor_hostname(self):
        """Tests a commonly used scenario for people trying to build a
        baremetal server on a specific ironic node. Note that although
        an ironic deployment would normally have a 1:M host:node topology
        the test is setup with a 1:1 host:node but we can still test using
        that by filtering on hypervisor_hostname. Also note that an admin
        could force a server to build on a specific host by passing
        availability_zone=<zone>::<nodename> but that means no filters get run
        which might be undesirable.
        """
        # Create a server passing the hypervisor_hostname query scheduler hint
        # for host2 to make sure the filter works. If not, because of the
        # custom HostNameWeigher, host1 would be chosen.
        query = jsonutils.dumps(['=', '$hypervisor_hostname', 'host2'])
        server = self._build_minimal_create_server_request(
            self.api, 'test_filter_on_hypervisor_hostname')
        request = {'server': server, 'os:scheduler_hints': {'query': query}}
        server = self.api.post_server(request)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # Since we request host2 the server should be there despite host1 being
        # weighed higher.
        self.assertEqual(
            'host2', server['OS-EXT-SRV-ATTR:hypervisor_hostname'])
