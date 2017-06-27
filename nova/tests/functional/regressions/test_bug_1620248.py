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
from nova.tests.unit import cast_as_call
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestServerUpdate(test.TestCase):
    REQUIRES_LOCKING = True

    def setUp(self):
        super(TestServerUpdate, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        # Simulate requests coming in before the instance is scheduled by
        # using a no-op for conductor build_instances
        self.useFixture(nova_fixtures.NoopConductorFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

        self.useFixture(cast_as_call.CastAsCall(self))
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def test_update_name_before_scheduled(self):
        server = dict(name='server0',
                      imageRef=self.image_id,
                      flavorRef=self.flavor_id)
        server_id = self.api.post_server({'server': server})['id']
        server = {'server': {'name': 'server-renamed'}}
        self.api.api_put('/servers/%s' % server_id, server)
        server_name = self.api.get_server(server_id)['name']
        self.assertEqual('server-renamed', server_name)
