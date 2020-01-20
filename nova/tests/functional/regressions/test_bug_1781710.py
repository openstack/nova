# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.scheduler import filter_scheduler
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as image_fake
from nova.tests.unit import policy_fixture


class AntiAffinityMultiCreateRequest(test.TestCase,
                                     integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1781710 introduced in Rocky.

    The ServerGroupAntiAffinityFilter changed in Rocky to support the
    "max_server_per_host" rule in the group's anti-affinity policy which
    allows having more than one server from the same anti-affinity group
    on the same host. As a result, the scheduler filter logic changed and
    a regression was introduced because of how the FilterScheduler is tracking
    which hosts are selected for each instance in a multi-create request.

    This test uses a custom weigher to ensure that when creating two servers
    in a single request that are in the same anti-affinity group with
    the default "max_server_per_host" setting (1), the servers are split
    across the two hosts even though normally one host would be weighed higher
    than the other.
    """

    def setUp(self):
        super(AntiAffinityMultiCreateRequest, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        # The admin API is used to get the server details to verify the
        # host on which the server was built.
        self.admin_api = api_fixture.admin_api
        self.api = api_fixture.api

        image_fake.stub_out_image_service(self)
        self.addCleanup(image_fake.FakeImageService_reset)

        self.start_service('conductor')

        # Use the latest microversion available to make sure something does
        # not regress in new microversions; cap as necessary.
        self.admin_api.microversion = 'latest'
        self.api.microversion = 'latest'

        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        # disable late check on compute node to mimic devstack.
        self.flags(disable_group_policy_check_upcall=True,
                   group='workarounds')
        self.start_service('scheduler')

        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')

    def test_anti_affinity_multi_create(self):
        # Create the anti-affinity server group in which we'll create our
        # two servers.
        group = self.api.post_server_groups(
            {'name': 'test group', 'policy': 'anti-affinity'})

        # Stub out FilterScheduler._get_alternate_hosts so we can assert what
        # is coming back for alternate hosts is what we'd expect after the
        # initial hosts are selected for each instance.
        original_get_alternate_hosts = (
            filter_scheduler.FilterScheduler._get_alternate_hosts)

        def stub_get_alternate_hosts(*a, **kw):
            # Intercept the result so we can assert there are no alternates.
            selections_to_return = original_get_alternate_hosts(*a, **kw)
            # Since we only have two hosts and each host is selected for each
            # server, and alternates should not include selected hosts, we
            # should get back a list with two entries (one per server) and each
            # entry should be a list of length 1 for the selected host per
            # server with no alternates.
            self.assertEqual(2, len(selections_to_return),
                             'There should be one host per server in the '
                             'anti-affinity group.')
            hosts = set([])
            for selection_list in selections_to_return:
                self.assertEqual(1, len(selection_list), selection_list)
                hosts.add(selection_list[0].service_host)
            self.assertEqual(2, len(hosts), hosts)
            return selections_to_return
        self.stub_out('nova.scheduler.filter_scheduler.FilterScheduler.'
                      '_get_alternate_hosts', stub_get_alternate_hosts)

        # Now create two servers in that group.
        server_req = self._build_server(
            image_uuid=image_fake.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID,
            networks='none')
        server_req['min_count'] = 2
        self.api.api_post(
            '/servers', {'server': server_req,
                         'os:scheduler_hints': {'group': group['id']}})

        selected_hosts = set([])
        # Now wait for both servers to be ACTIVE and get the host on which
        # each server was built.
        for server in self.api.get_servers(detail=False):
            server = self._wait_for_state_change(server, 'ACTIVE')
            selected_hosts.add(server['OS-EXT-SRV-ATTR:host'])

        # Assert that each server is on a separate host.
        self.assertEqual(2, len(selected_hosts))
