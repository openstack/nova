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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import test_servers


class ImagesTest(test_servers.ServersTestBase):

    def test_create_images_negative_invalid_state(self):
        # Create server
        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

        # Create image
        name = 'Snapshot 1'
        self.api.post_server_action(
            server_id, {'createImage': {'name': name}})

        # Confirm that the image was created
        images = self.api.get_images(detail=False)
        image_map = {image['name']: image for image in images}
        found_image = image_map.get(name)
        self.assertTrue(found_image)

        # Change server status from ACTIVE to SHELVED for negative test
        self.flags(shelved_offload_time = -1)
        self.api.post_server_action(server_id, {'shelve': {}})
        found_server = self._wait_for_state_change(found_server, 'SHELVED')

        # Create image in SHELVED (not ACTIVE, etc.)
        name = 'Snapshot 2'
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               server_id,
                               {'createImage': {'name': name}})
        self.assertEqual(409, ex.response.status_code)

        # Confirm that the image was not created
        images = self.api.get_images(detail=False)
        image_map = {image['name']: image for image in images}
        found_image = image_map.get(name)
        self.assertFalse(found_image)

        # Cleanup
        self._delete_server(found_server)

    def test_admin_snapshot_user_image_access_member(self):
        """Tests a scenario where a user in project A creates a server and
        an admin in project B creates a snapshot of the server. The user in
        project A should have member access to the image even though the admin
        project B is the owner of the image.
        """
        # Create a server using the tenant user project.
        server = self._build_server()
        server = self.api.post_server({"server": server})
        server = self._wait_for_state_change(server, 'ACTIVE')

        # Create an admin API fixture with a unique project ID.
        admin_api = self.useFixture(
            nova_fixtures.OSAPIFixture(
                project_id=uuids.admin_project)).admin_api

        # Create a snapshot of the server using the admin project.
        name = 'admin-created-snapshot'
        admin_api.post_server_action(
            server['id'], {'createImage': {'name': name}})
        # Confirm that the image was created.
        images = admin_api.get_images()
        for image in images:
            if image['name'] == name:
                break
        else:
            self.fail('Expected snapshot image %s not found in images list %s'
                      % (name, images))
        # Assert the owner is the admin project since the admin created the
        # snapshot. Note that the images API proxy puts stuff it does not know
        # about in the 'metadata' dict so that is where we will find owner.
        metadata = image['metadata']
        self.assertIn('owner', metadata)
        self.assertEqual(uuids.admin_project, metadata['owner'])
        # Assert the non-admin tenant user project is a member.
        self.assertIn('instance_owner', metadata)
        self.assertEqual(
            self.api_fixture.project_id, metadata['instance_owner'])
        # Be sure we did not get a false positive by making sure the admin and
        # tenant user API fixtures are not using the same project_id.
        self.assertNotEqual(uuids.admin_project, self.api_fixture.project_id)
