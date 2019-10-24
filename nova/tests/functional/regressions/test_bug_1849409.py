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
from nova.tests.unit.image import fake as fake_image


class ListDeletedServersWithMarker(test.TestCase,
                                   integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1849409 introduced in Queens where listing
    deleted servers with a marker returns the wrong results because the marker
    is nulled out if BuildRequestList.get_by_filters does not raise
    MarkerNotFound, but that does not mean the marker was found in the build
    request list.
    """
    def setUp(self):
        super(ListDeletedServersWithMarker, self).setUp()
        # Start standard fixtures.
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        # Start nova services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute')

    def test_list_deleted_servers_with_marker(self):
        # Create a server.
        server = self._build_minimal_create_server_request(
            self.api, 'test_list_deleted_servers_with_marker',
            image_uuid=fake_image.get_valid_image_id())
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        # Now delete the server and wait for it to be gone.
        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)
        # List deleted servers, we should get the one back.
        servers = self.api.get_servers(detail=False,
                                       search_opts={'deleted': True})
        self.assertEqual(1, len(servers), servers)
        self.assertEqual(server['id'], servers[0]['id'])
        # Now list deleted servers with a marker which should not return the
        # marker instance.
        servers = self.api.get_servers(detail=False,
                                       search_opts={'deleted': True,
                                                    'marker': server['id']})
        self.assertEqual(0, len(servers), servers)
