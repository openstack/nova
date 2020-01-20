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
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as image_fake
from nova.tests.unit import policy_fixture


class ServerTagsFilteringTest(test.TestCase,
                              integrated_helpers.InstanceHelperMixin):
    """Simple tests to create servers with tags and then list servers using
    the various tag filters.

    This is a regression test for bug 1682693 introduced in Newton when we
    started pulling instances from cell0 and the main cell.
    """

    def setUp(self):
        super(ServerTagsFilteringTest, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        # The NeutronFixture is needed to stub out validate_networks in API.
        self.useFixture(nova_fixtures.NeutronFixture(self))
        # Use the PlacementFixture to avoid annoying warnings in the logs.
        self.useFixture(func_fixtures.PlacementFixture())
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
        self.start_service('compute')

        # create two test servers
        self.servers = []
        for x in range(2):
            server = self._build_server(networks='none')
            server = self.api.post_server({'server': server})
            self.addCleanup(self.api.delete_server, server['id'])
            server = self._wait_for_state_change(server, 'ACTIVE')
            self.servers.append(server)

        # now apply two tags to the first server
        self.two_tag_server = self.servers[0]
        self.api.put_server_tags(self.two_tag_server['id'], ['foo', 'bar'])
        # apply one tag to the second server which intersects with one tag
        # from the first server
        self.one_tag_server = self.servers[1]
        self.api.put_server_tags(self.one_tag_server['id'], ['foo'])

    def test_list_servers_filter_by_tags(self):
        """Tests listing servers and filtering by the 'tags' query
        parameter which uses AND logic.
        """
        servers = self.api.get_servers(search_opts=dict(tags='foo,bar'))
        # we should get back our server that has both tags
        self.assertEqual(1, len(servers))
        server = servers[0]
        self.assertEqual(self.two_tag_server['id'], server['id'])
        self.assertEqual(2, len(server['tags']))
        self.assertEqual(['bar', 'foo'], sorted(server['tags']))

        # query for the shared tag and we should get two servers back
        servers = self.api.get_servers(search_opts=dict(tags='foo'))
        self.assertEqual(2, len(servers))
