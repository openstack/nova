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
from nova.tests.functional.api import client as api_client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class TestServersPerUserQuota(test.TestCase,
                              integrated_helpers.InstanceHelperMixin):
    """This tests a regression introduced in the Pike release.

    In Pike we started counting resources for quota limit checking instead of
    tracking usages in a separate database table. As part of that change,
    per-user quota functionality was broken for server creates.

    When mulitple users in the same project have per-user quota, they are meant
    to be allowed to create resources such that may not exceed their
    per-user quota nor their project quota.

    If a project has an 'instances' quota of 10 and user A has a quota of 1
    and user B has a quota of 1, both users should each be able to create 1
    server.

    Because of the bug, in this scenario user A will succeed in creating a
    server but user B will fail to create a server with a 403 "quota exceeded"
    error because the 'instances' resource count isn't being correctly scoped
    per-user.
    """
    def setUp(self):
        super(TestServersPerUserQuota, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.glance = self.useFixture(nova_fixtures.GlanceFixture(self))

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api
        self.api.microversion = '2.37'  # so we can specify networks='none'
        self.admin_api.microversion = '2.37'

        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute')

    def test_create_server_with_per_user_quota(self):
        # Set per-user quota for the non-admin user to allow 1 instance.
        # The default quota for the project is 10 instances.
        quotas = {'instances': 1}
        self.admin_api.update_quota(
            quotas, project_id=self.api.project_id, user_id=self.api.auth_user)
        # Verify that the non-admin user has a quota limit of 1 instance.
        quotas = self.api.get_quota_detail(user_id=self.api.auth_user)
        self.assertEqual(1, quotas['instances']['limit'])
        # Verify that the admin user has a quota limit of 10 instances.
        quotas = self.api.get_quota_detail(user_id=self.admin_api.auth_user)
        self.assertEqual(10, quotas['instances']['limit'])
        # Boot one instance into the default project as the admin user.
        # This results in usage of 1 instance for the project and 1 instance
        # for the admin user.
        self._create_server(networks='none', api=self.admin_api)
        # Now try to boot an instance as the non-admin user.
        # This should succeed because the non-admin user has 0 instances and
        # the project limit allows 10 instances.
        server_req = self._build_server(networks='none')
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(server, 'ACTIVE')
        # A request to boot a second instance should fail because the
        # non-admin has already booted 1 allowed instance.
        ex = self.assertRaises(
            api_client.OpenStackApiException, self.api.post_server,
            {'server': server_req})
        self.assertEqual(403, ex.response.status_code)
