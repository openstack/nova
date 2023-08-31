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

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


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
        self.useFixture(nova_fixtures.CastAsCallFixture(self))
        self.useFixture(nova_fixtures.RealPolicyFixture())
        self.useFixture(nova_fixtures.CinderFixture(self, az=self.az))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        self.notifier = self.useFixture(
            nova_fixtures.NotificationFixture(self))
        # Start nova controller services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.start_service('conductor')
        self.start_service('scheduler')
        # Start two compute service and add it to the AZ.
        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')
        agg_id = self.api.post_aggregate({'aggregate': {
            'name': self.az, 'availability_zone': self.az}})['id']
        self.api.api_post('/os-aggregates/%s/action' % agg_id,
                          {'add_host': {'host': 'host1'}})
        self.api.api_post('/os-aggregates/%s/action' % agg_id,
                          {'add_host': {'host': 'host2'}})

    def test_cross_az_attach_false_boot_from_volume_no_az_specified(self):
        """Tests the scenario where [cinder]/cross_az_attach=False and the
        server is created with a pre-existing volume but the server create
        request does not specify an AZ nor is [DEFAULT]/default_schedule_zone
        set. In this case the server is created in the zone specified by the
        volume.
        """
        self.flags(cross_az_attach=False, group='cinder')
        # Do not need imageRef for boot from volume.
        server = self._build_server(image_uuid='')
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        }]
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(self.az, server['OS-EXT-AZ:availability_zone'])

    def test_cross_az_attach_false_data_volume_no_az_specified(self):
        """Tests the scenario where [cinder]/cross_az_attach=False and the
        server is created with a pre-existing volume as a non-boot data volume
        but the server create request does not specify an AZ nor is
        [DEFAULT]/default_schedule_zone set. In this case the server is created
        in the zone specified by the non-root data volume.
        """
        self.flags(cross_az_attach=False, group='cinder')
        server = self._build_server()
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
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(self.az, server['OS-EXT-AZ:availability_zone'])

    def test_cross_az_attach_false_boot_from_volume_default_zone_match(self):
        """Tests the scenario where [cinder]/cross_az_attach=False and the
        server is created with a pre-existing volume and the
        [DEFAULT]/default_schedule_zone matches the volume's AZ.
        """
        self.flags(cross_az_attach=False, group='cinder')
        self.flags(default_schedule_zone=self.az)
        # Do not need imageRef for boot from volume.
        server = self._build_server(image_uuid='')
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        }]
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(self.az, server['OS-EXT-AZ:availability_zone'])

    def test_cross_az_attach_false_bfv_az_specified_mismatch(self):
        """Negative test where the server is being created in a specific AZ
        that does not match the volume being attached which results in a 400
        error response.
        """
        self.flags(cross_az_attach=False, group='cinder')
        # Do not need imageRef for boot from volume.
        server = self._build_server(image_uuid='', az='london')
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        }]
        # Use the AZ fixture to fake out the london AZ.
        with nova_fixtures.AvailabilityZoneFixture(zones=['london', self.az]):
            ex = self.assertRaises(api_client.OpenStackApiException,
                                   self.api.post_server, {'server': server})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Server and volumes are not in the same availability '
                      'zone. Server is in: london. Volumes are in: %s' %
                      self.az, str(ex))

    def test_cross_az_attach_false_no_volumes(self):
        """A simple test to make sure cross_az_attach=False API validation is
        a noop if there are no volumes in the server create request.
        """
        self.flags(cross_az_attach=False, group='cinder')
        server = self._create_server(az=self.az)
        self.assertEqual(self.az, server['OS-EXT-AZ:availability_zone'])

    def test_cross_az_attach_false_migrate_continues_to_pin_an_az(self):
        self.flags(cross_az_attach=False, group='cinder')
        server = self._build_server()
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        }]
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        # The instance is now pinned to a specific AZ.
        self.assertEqual(self.az, server['OS-EXT-AZ:availability_zone'])
        # Start a third compute service and add it to a different 'london' AZ.
        self.start_service('compute', host='host3')
        agg_id = self.api.post_aggregate({'aggregate': {
            'name': 'london', 'availability_zone': 'london'}})['id']
        self.api.api_post('/os-aggregates/%s/action' % agg_id,
                          {'add_host': {'host': 'host3'}})

        # we want 2.56 because of the host param in migrate action.
        self.api.microversion = '2.56'

        # We can migrate the instance to another host in the same AZ
        server = self._migrate_server(server, host='host2')
        # let's move it back to host1
        server = self._revert_resize(server)

        # Now let's try to migrate to host3 which is a different AZ.
        # It fails miserably.
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.post_server_action,
                               server['id'], {'migrate': {'host': 'host3'}})
        self.assertEqual(500, ex.response.status_code)
        # And yeah, that's due to the fact that the only tested host in not in
        # the pinned AZ.
        self.assertIn('NoValidHost', str(ex))
