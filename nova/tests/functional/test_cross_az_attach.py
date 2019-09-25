#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import six

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture


class CrossAZAttachTestCase(test.TestCase,
                            integrated_helpers.InstanceHelperMixin):
    """Contains various scenarios for the [cinder]/cross_az_attach option
    and how it affects interactions between nova and cinder in the API and
    compute service.
    """
    az = 'us-central-1'

    def setUp(self):
        super(CrossAZAttachTestCase, self).setUp()
        # Use the standard fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.CinderFixture(self, az=self.az))
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        # Start nova controller services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.start_service('conductor')
        self.start_service('scheduler')
        # Start one compute service.
        self.start_service('compute', host='host1')

    def test_cross_az_attach_false_boot_from_volume_no_az_specified(self):
        """Tests the scenario where [cinder]/cross_az_attach=False and the
        server is created with a pre-existing volume but the server create
        request does not specify an AZ nor is [DEFAULT]/default_schedule_zone
        set.
        """
        self.flags(cross_az_attach=False, group='cinder')
        server = self._build_minimal_create_server_request(
            self.api,
            'test_cross_az_attach_false_boot_from_volume_no_az_specified')
        del server['imageRef']  # Do not need imageRef for boot from volume.
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        }]
        # FIXME(mriedem): This is bug 1694844 where the user creates the server
        # without specifying an AZ and there is no default_schedule_zone set
        # and the cross_az_attach check fails because the volume's availability
        # zone shows up as "us-central-1" and None != "us-central-1" so the API
        # thinks the cross_az_attach=False setting was violated.
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.post_server, {'server': server})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('are not in the same availability_zone',
                      six.text_type(ex))

    def test_cross_az_attach_false_data_volume_no_az_specified(self):
        """Tests the scenario where [cinder]/cross_az_attach=False and the
        server is created with a pre-existing volume as a non-boot data volume
        but the server create request does not specify an AZ nor is
        [DEFAULT]/default_schedule_zone set.
        """
        self.flags(cross_az_attach=False, group='cinder')
        server = self._build_minimal_create_server_request(
            self.api,
            'test_cross_az_attach_false_data_volume_no_az_specified')
        # Note that we use the legacy block_device_mapping parameter rather
        # than block_device_mapping_v2 because that will create an implicit
        # source_type=image, destination_type=local, boot_index=0,
        # uuid=$imageRef which is used as the root BDM and allows our
        # non-boot data volume to be attached during server create. Otherwise
        # we get InvalidBDMBootSequence.
        server['block_device_mapping'] = [{
            # This is a non-bootable volume in the CinderFixture.
            'volume_id': nova_fixtures.CinderFixture.SWAP_OLD_VOL
        }]
        # FIXME(mriedem): This is bug 1694844 where the user creates the server
        # without specifying an AZ and there is no default_schedule_zone set
        # and the cross_az_attach check fails because the volume's availability
        # zone shows up as "us-central-1" and None != "us-central-1" so the API
        # thinks the cross_az_attach=False setting was violated.
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.post_server, {'server': server})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('are not in the same availability_zone',
                      six.text_type(ex))

    def test_cross_az_attach_false_boot_from_volume_default_zone_match(self):
        """Tests the scenario where [cinder]/cross_az_attach=False and the
        server is created with a pre-existing volume and the
        [DEFAULT]/default_schedule_zone matches the volume's AZ.
        """
        self.flags(cross_az_attach=False, group='cinder')
        self.flags(default_schedule_zone=self.az)
        # For this test we have to put the compute host in an aggregate with
        # the AZ we want to match.
        agg_id = self.api.post_aggregate({
            'aggregate': {
                'name': self.az,
                'availability_zone': self.az
            }
        })['id']
        self.api.add_host_to_aggregate(agg_id, 'host1')

        server = self._build_minimal_create_server_request(
            self.api,
            'test_cross_az_attach_false_boot_from_volume_default_zone_match')
        del server['imageRef']  # Do not need imageRef for boot from volume.
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        }]
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        self.assertEqual(self.az, server['OS-EXT-AZ:availability_zone'])
