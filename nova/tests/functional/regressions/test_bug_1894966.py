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
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class TestCreateServerGroupWithEmptyPolicies(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):
    """Demonstrate bug #1894966.

    Attempt to create a server group with an invalid 'policies' field. It
    should fail cleanly.
    """
    def setUp(self):
        super(TestCreateServerGroupWithEmptyPolicies, self).setUp()

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.api.microversion = '2.63'  # the last version with the bug

    def test_create_with_empty_policies(self):
        exc = self.assertRaises(
            client.OpenStackApiException,
            self.api.post_server_groups,
            {'name': 'test group', 'policies': []})
        self.assertEqual(400, exc.response.status_code)
