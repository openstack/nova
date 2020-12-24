# Copyright 2020, Red Hat, Inc. All Rights Reserved.
#
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

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class TestVolAttachCinderReset(integrated_helpers._IntegratedTestBase):
    """Regression test for bug 1908075.

    This regression test aims to assert if n-api allows a non-multiattached
    volume to be attached to multiple instances after an admin has forcibly
    reset the state of the volume in Cinder.
    """

    microversion = 'latest'

    def test_volume_attach_after_cinder_reset_state(self):

        volume_id = self.cinder.IMAGE_BACKED_VOL

        # Launch a server and attach a volume
        server_a = self._create_server(networks='none')
        self.api.post_server_volume(
            server_a['id'],
            {'volumeAttachment': {'volumeId': volume_id}}
        )

        # reset-state of the volume within the cinder fixture, we don't model
        # the state of the volume within the fixture so this will have to do.
        del self.cinder.volume_to_attachment[volume_id]
        self.assertNotIn(
            volume_id, self.cinder.volume_ids_for_instance(server_a['id']))

        # Launch a second server and attempt to attach the same volume again
        server_b = self._create_server(networks='none')

        # Assert that attempting to attach this non multiattach volume to
        # another instance is rejected by n-api
        ex = self.assertRaises(
            client.OpenStackApiException,
            self.api.post_server_volume,
            server_b['id'],
            {'volumeAttachment': {'volumeId': volume_id}}
        )

        self.assertEqual(400, ex.response.status_code)

    def test_volume_attach_after_cinder_reset_state_multiattach_volume(self):

        volume_id = self.cinder.MULTIATTACH_VOL

        # Launch a server and attach a volume
        server_a = self._create_server(networks='none')
        self.api.post_server_volume(
            server_a['id'],
            {'volumeAttachment': {'volumeId': volume_id}}
        )

        # reset-state of the volume within the cinder fixture, we don't model
        # the state of the volume within the fixture so this will have to do.
        del self.cinder.volume_to_attachment[volume_id]
        self.assertNotIn(
            volume_id, self.cinder.volume_ids_for_instance(server_a['id']))

        # Launch a second server and attempt to attach the same volume again
        server_b = self._create_server(networks='none')
        # NOTE(lyarwood): Unlike non-multiattach volumes this should always be
        # allowed as we can have multiple active bdms for multiattached volumes
        self.api.post_server_volume(
            server_b['id'],
            {'volumeAttachment': {'volumeId': volume_id}}
        )

        # Assert that we have bdms within Nova still for this attachment
        self.assertEqual(
            volume_id,
            self.api.get_server_volumes(server_a['id'])[0].get('volumeId'))
        self.assertEqual(
            volume_id,
            self.api.get_server_volumes(server_b['id'])[0].get('volumeId'))

        # Assert that the new attachment is the only one in the fixture
        self.assertIn(
            volume_id, self.cinder.volume_ids_for_instance(server_b['id']))
