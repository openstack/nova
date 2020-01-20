# Copyright 2017 Huawei Technologies Co.,LTD.
#
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

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import cast_as_call
from nova.tests.unit.image import fake as image_fake
from nova.tests.unit import policy_fixture


class ServerListLimitMarkerCell0Test(test.TestCase,
                                     integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1689692 introduced in Ocata.

    The user specifies a limit which is greater than the number of instances
    left in the page and the marker starts in the cell0 database. What happens
    is we don't null out the marker but we still have more limit so we continue
    to page in the cell database(s) but the marker isn't found in any of those,
    since it's already found in cell0, so it eventually raises a MarkerNotFound
    error.
    """

    def setUp(self):
        super(ServerListLimitMarkerCell0Test, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        # The NeutronFixture is needed to stub out validate_networks in API.
        self.useFixture(nova_fixtures.NeutronFixture(self))
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        image_fake.stub_out_image_service(self)
        self.addCleanup(image_fake.FakeImageService_reset)

        # Use the latest microversion available to make sure something does
        # not regress in new microversions; cap as necessary.
        self.api.microversion = 'latest'

        self.start_service('conductor')
        self.start_service('scheduler')
        # We don't start the compute service because we want NoValidHost so
        # all of the instances go into ERROR state and get put into cell0.
        self.useFixture(cast_as_call.CastAsCall(self))

    def test_list_servers_marker_in_cell0_more_limit(self):
        """Creates three servers, then lists them with a marker on the first
        and a limit of 3 which is more than what's left to page on (2) but
        it shouldn't fail, it should just give the other two back.
        """
        # create three test servers
        for x in range(3):
            server_req = self._build_server(networks='none')
            server = self.api.post_server({'server': server_req})
            self.addCleanup(self.api.delete_server, server['id'])
            self._wait_for_state_change(server, 'ERROR')

        servers = self.api.get_servers()
        self.assertEqual(3, len(servers))

        # Take the first server and user that as our marker.
        marker = servers[0]['id']
        # Since we're paging after the first server as our marker, there are
        # only two left so specifying three should just return two.
        servers = self.api.get_servers(search_opts=dict(marker=marker,
                                                        limit=3))
        self.assertEqual(2, len(servers))
