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


class TestDetachVolumeWhileComputeDown(integrated_helpers._IntegratedTestBase):
    """Regression test for bug 1909120

    This regression test aims to assert the behaviour of the
    os-volume_attachments API when removing a volume attachment from an
    instance hosted on a down compute.
    """
    microversion = 'latest'

    def test_volume_detach_while_compute_down(self):

        # _IntegratedTestBase uses CastAsCall so set the response timeout to 1
        self.flags(rpc_response_timeout=1)

        # Launch a test instance
        server = self._create_server(networks='none')

        # Attach the volume
        volume_id = self.cinder.IMAGE_BACKED_VOL
        self.api.post_server_volume(
            server['id'],
            {'volumeAttachment': {'volumeId': volume_id}}
        )

        # Assert that the volume is attached in Nova
        attachment = self.api.get_server_volumes(server['id'])[0]
        self.assertEqual(volume_id, attachment.get('volumeId'))
        # Assert that the volume is attached in the Cinder fixture
        self.assertIn(
            volume_id, self.cinder.volume_ids_for_instance(server['id']))

        # Stop and force down the compute
        self.compute.stop()
        compute_id = self.admin_api.get_services(
            binary='nova-compute')[0]['id']
        self.admin_api.put_service_force_down(compute_id, True)

        # Assert that the request fails in this functional test as the cast to
        # detach_volume on the compute is actually treated as a call by the
        # CastAsCall fixture used by _IntegratedTestBase.
        ex = self.assertRaises(
            client.OpenStackApiException,
            self.api.delete_server_volume, server['id'], volume_id)

        # FIXME(lyarwood): n-cpu should reject the initial request with 409
        # self.assertEqual(409, ex.response.status_code)
        self.assertEqual(500, ex.response.status_code)
