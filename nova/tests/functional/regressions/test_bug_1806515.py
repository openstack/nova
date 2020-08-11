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
from nova.tests.unit import fake_notifier


class ShowErrorServerWithTags(test.TestCase,
                              integrated_helpers.InstanceHelperMixin):
    """Test list of an instance in error state that has tags.

    This test boots a server with tag which will fail to be scheduled,
    ending up in ERROR state with no host assigned and then show the server.
    """

    def setUp(self):
        super(ShowErrorServerWithTags, self).setUp()

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api

        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))

        self.start_service('conductor')
        self.start_service('scheduler')

        self.image_id = self.api.get_images()[0]['id']

        self.api.microversion = 'latest'

        self.addCleanup(fake_notifier.reset)

    def _create_error_server(self):
        server = self.api.post_server({
            'server': {
                'flavorRef': '1',
                'name': 'show-server-with-tag-in-error-status',
                'networks': 'none',
                'tags': ['tag1'],
                'imageRef': self.image_id
            }
        })
        return self._wait_for_state_change(server, 'ERROR')

    def test_show_server_tag_in_error(self):
        # Create a server which should go to ERROR state because we don't
        # have any active computes.
        server = self._create_error_server()
        server_id = server['id']

        tags = self.api.get_server_tags(server_id)
        self.assertIn('tag1', tags)
