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
from nova.tests.unit import fake_network
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestRescheduleWithVolumesAttached(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1784353 introduced in Queens.

    This regression test asserts that volume backed instances fail to start
    when rescheduled due to their volume attachments being deleted by cleanup
    code within the compute layer after an initial failure to spawn.
    """

    def setUp(self):
        super(TestRescheduleWithVolumesAttached, self).setUp()

        # Use the new attach flow fixture for cinder
        cinder_fixture = nova_fixtures.CinderFixture(self)
        self.cinder = self.useFixture(cinder_fixture)
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))

        fake_network.set_stub_network_methods(self)

        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api

        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.flags(compute_driver='fake.FakeRescheduleDriver')

        self.start_service('conductor')
        self.start_service('scheduler')

        # Start two computes to allow the instance to be rescheduled
        self.host1 = self.start_service('compute', host='host1')

        self.host2 = self.start_service('compute', host='host2')

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def test_reschedule_with_volume_attached(self):
        # Boot a volume backed instance
        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server_request = {
            'name': 'server',
            'flavorRef': self.flavor_id,
            'block_device_mapping_v2': [{
                'boot_index': 0,
                'uuid': volume_id,
                'source_type': 'volume',
                'destination_type': 'volume'}],
        }
        server_response = self.api.post_server({'server': server_request})
        server_id = server_response['id']

        self._wait_for_state_change(self.api, server_response, 'ACTIVE')
        attached_volume_ids = self.cinder.volume_ids_for_instance(server_id)
        self.assertIn(volume_id, attached_volume_ids)
        self.assertEqual(1, len(self.cinder.volume_to_attachment))
        # There should only be one attachment record for the volume and
        # instance because the original would have been deleted before
        # rescheduling off the first host.
        self.assertEqual(1, len(self.cinder.volume_to_attachment[volume_id]))
