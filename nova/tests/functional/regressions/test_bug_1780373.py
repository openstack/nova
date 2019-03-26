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
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture
from nova.virt import fake as fake_virt


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
        self.useFixture(nova_fixtures.PlacementFixture())

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
        # TODO(mriedem): We don't need a compute service when the bug is fixed
        # because we won't be able to get past nova-api validation.
        self.start_service('conductor')
        self.start_service('scheduler')
        fake_virt.set_nodes(['host1'])
        self.addCleanup(fake_virt.restore_nodes)
        self.start_service('compute', host='host1')

        server_req = self._build_minimal_create_server_request(
            self.api, 'test_multi_create_server_group_members_over_quota',
            image_uuid=fake_image.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID,
            networks='none')
        server_req['min_count'] = 3
        server_req['return_reservation_id'] = True
        hints = {'group': self.created_group['id']}
        # FIXME(mriedem): When bug 1780373 is fixed this should result in a
        # 403 error response and 0 members in the group.
        reservation_id = self.api.post_server(
            {'server': server_req,
             'os:scheduler_hints': hints})['reservation_id']
        # Assert that three servers were created regardless of the
        # [quota]/server_group_members=2 quota limit.
        servers = self.api.get_servers(
            detail=False, search_opts={'reservation_id': reservation_id})
        self.assertEqual(3, len(servers))
        group = self.api.api_get(
            '/os-server-groups/%s' %
            self.created_group['id']).body['server_group']
        self.assertEqual(3, len(group['members']))

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
            # FIXME(mriedem): When bug 1780373 is fixed this should result in a
            # 403 error response on the 3rd create server request.
            self.api.post_server(
                {'server': server_req, 'os:scheduler_hints': hints})
        # Assert that three servers were created regardless of the
        # [quota]/server_group_members=2 quota limit.
        servers = self.api.get_servers(detail=False)
        # FIXME(mriedem): When the bug is fixed, there should only be 2 servers
        # created and 2 members in the group.
        self.assertEqual(3, len(servers))
        group = self.api.api_get(
            '/os-server-groups/%s' %
            self.created_group['id']).body['server_group']
        self.assertEqual(3, len(group['members']))
