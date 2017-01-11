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

from nova.tests.functional.api import client
from nova.tests.functional import test_servers


class ImagesTest(test_servers.ServersTestBase):

    def test_create_images_negative_invalid_state(self):
        # Create server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # Create image
        name = 'Snapshot 1'
        self.api.post_server_action(
            server_id, {'createImage': {'name': name}})
        self.assertEqual('ACTIVE', found_server['status'])
        # Confirm that the image was created
        images = self.api.get_images(detail=False)
        image_map = {image['name']: image for image in images}
        found_image = image_map.get(name)
        self.assertTrue(found_image)

        # Change server status from ACTIVE to SHELVED for negative test
        self.flags(shelved_offload_time = -1)
        self.api.post_server_action(server_id, {'shelve': {}})
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')
        self.assertEqual('SHELVED', found_server['status'])

        # Create image in SHELVED (not ACTIVE, etc.)
        name = 'Snapshot 2'
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               server_id,
                               {'createImage': {'name': name}})
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('SHELVED', found_server['status'])

        # Confirm that the image was not created
        images = self.api.get_images(detail=False)
        image_map = {image['name']: image for image in images}
        found_image = image_map.get(name)
        self.assertFalse(found_image)

        # Cleanup
        self._delete_server(server_id)
