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
import mock

from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture
from nova.virt import fake


class BootServerInAzRescheduleTest(
        test.TestCase, integrated_helpers.InstanceHelperMixin):

    def setUp(self):
        super(BootServerInAzRescheduleTest, self).setUp()

        # Use the standard fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.PlacementFixture())
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api

        # The image fake backend
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.start_service('conductor')
        self.start_service('scheduler')

        self.image_id = self.api.get_images()[0]['id']

        fake.set_nodes(['compute_in_my_az'])
        self.addCleanup(fake.restore_nodes)
        self.compute_in_my_az = self.start_service(
            'compute', host='compute_in_my_az')

        fake.set_nodes(['compute_not_in_my_az'])
        self.compute_not_in_my_az = self.start_service(
            'compute', host='compute_not_in_my_az')

        self.api.microversion = 'latest'

    def test_boot_server_in_an_az_re_schedule(self):
        """Assert that reschedule keeps the instance in the requested
        availability zone.

        Start two compute hosts. Add one of it to an aggregate mapped to an az.
        Boot a server requesting the az but inject fault in the instance claim
        process so the server cannot be booted on the only host that is in the
        requested az. Expect that the reschedule is triggered but it fail with
        no valid host.
        """
        agg = self.api.post_aggregate(
            {'aggregate':
                 {'name': 'my-agg',
                  'availability_zone': 'my-az'}})
        self.api.add_host_to_aggregate(agg['id'], 'compute_in_my_az')

        with mock.patch.object(
                self.compute_in_my_az.manager._get_resource_tracker(),
                'instance_claim',
                side_effect=exception.ComputeResourcesUnavailable(
                    reason='test')) as mock_instance_claim:
            server = self.api.post_server({
                'server': {
                    'flavorRef': '1',
                    'name': 'server-in-az',
                    'networks': 'none',
                    'imageRef': self.image_id,
                    'availability_zone': 'my-az'
                }
            })

            # The server expected to go the ERROR state as the resource claim
            # failed on the only host that was in the requested aggregate
            # server = self._wait_for_state_change(self.api, server, 'ERROR')
            #
            # bug 1852207: re-schedule allows to boot the server outside of the
            # requested availability zone so the instance ends up on the
            # compute_not_in_my_az host
            server = self._wait_for_state_change(self.api, server, 'ACTIVE')
            self.assertEqual('nova', server['OS-EXT-AZ:availability_zone'])
            self.assertEqual(
                'compute_not_in_my_az', server['OS-EXT-SRV-ATTR:host'])

            self.assertTrue(mock_instance_claim.called)
