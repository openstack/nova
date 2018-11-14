# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture


class TestMultiCreateServerGroupMemberOverQuota(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """This tests a regression introduced in the Pike release.

    Starting in the Pike release, quotas are no longer tracked using usages
    and reservations tables but instead perform a resource counting operation
    at the point of resource creation.

    When creating multiple servers in the same request that belong in the same
    server group, the [quota]/server_group_members config option is checked
    to determine if those servers can belong in the same group based on quota.
    However, the quota check for server_group_members only counts existing
    group members based on live instances in the cell database(s). But the
    actual instance record isn't created in the cell database until *after* the
    server_group_members quota check happens. Because of this, it is possible
    to bypass the server_group_members quota check when creating multiple
    servers in the same request.
    """
    def setUp(self):
        super(TestMultiCreateServerGroupMemberOverQuota, self).setUp()
        self.flags(server_group_members=2, group='quota')
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.api.microversion = '2.37'  # so we can specify networks='none'

        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)

        group = {'name': 'test group', 'policies': ['soft-anti-affinity']}
        self.created_group = self.api.post_server_groups(group)

    def test_multi_create_server_group_members_over_quota(self):
        """Recreate scenario for the bug where we create an anti-affinity
        server group and then create 3 servers in the group using a
        multi-create POST /servers request.
        """
        server_req = self._build_minimal_create_server_request(
            self.api, 'test_multi_create_server_group_members_over_quota',
            image_uuid=fake_image.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID,
            networks='none')
        server_req['min_count'] = 3
        server_req['return_reservation_id'] = True
        hints = {'group': self.created_group['id']}
        # We should get a 403 response due to going over quota on server
        # group members in a single request.
        self.api.api_post(
            '/servers', {'server': server_req, 'os:scheduler_hints': hints},
            check_response_status=[403])
        group = self.api.api_get(
            '/os-server-groups/%s' %
            self.created_group['id']).body['server_group']
        self.assertEqual(0, len(group['members']))

    def test_concurrent_request_server_group_members_over_quota(self):
        """Recreate scenario for the bug where we create 3 servers in the
        same group but in separate requests. The NoopConductorFixture is used
        to ensure the instances are not created in the nova cell database which
        means the quota check will have to rely on counting group members using
        build requests from the API DB.
        """
        # These aren't really concurrent requests, but we can simulate that
        # by using NoopConductorFixture.
        self.useFixture(nova_fixtures.NoopConductorFixture())
        for x in range(3):
            server_req = self._build_minimal_create_server_request(
                self.api, 'test_concurrent_request_%s' % x,
                image_uuid=fake_image.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID,
                networks='none')
            hints = {'group': self.created_group['id']}
            # This should result in a 403 response on the 3rd server.
            if x == 2:
                self.api.api_post(
                    '/servers',
                    {'server': server_req, 'os:scheduler_hints': hints},
                    check_response_status=[403])
            else:
                self.api.post_server(
                    {'server': server_req, 'os:scheduler_hints': hints})
        # There should only be two servers created which are both members of
        # the same group.
        servers = self.api.get_servers(detail=False)
        self.assertEqual(2, len(servers))
        group = self.api.api_get(
            '/os-server-groups/%s' %
            self.created_group['id']).body['server_group']
        self.assertEqual(2, len(group['members']))
