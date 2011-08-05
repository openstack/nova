# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
#
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

import time
import unittest

from nova.log import logging
from nova.tests.integrated import integrated_helpers
from nova.tests.integrated.api import client


LOG = logging.getLogger('nova.tests.integrated')


class ServersTest(integrated_helpers._IntegratedTestBase):
    def test_get_servers(self):
        """Simple check that listing servers works."""
        servers = self.api.get_servers()
        for server in servers:
            LOG.debug("server: %s" % server)

    def test_create_and_delete_server(self):
        """Creates and deletes a server."""

        # Create server

        # Build the server data gradually, checking errors along the way
        server = {}
        good_server = self._build_minimal_create_server_request()

        post = {'server': server}

        # Without an imageRef, this throws 500.
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # With an invalid imageRef, this throws 500.
        server['imageRef'] = self.user.get_invalid_image()
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # Add a valid imageId/imageRef
        server['imageId'] = good_server.get('imageId')
        server['imageRef'] = good_server.get('imageRef')

        # Without flavorId, this throws 500
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # Set a valid flavorId/flavorRef
        server['flavorRef'] = good_server.get('flavorRef')
        server['flavorId'] = good_server.get('flavorId')

        # Without a name, this throws 500
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # Set a valid server name
        server['name'] = good_server['name']

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Check it's there
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        # It should also be in the all-servers list
        servers = self.api.get_servers()
        server_ids = [server['id'] for server in servers]
        self.assertTrue(created_server_id in server_ids)

        # Wait (briefly) for creation
        retries = 0
        while found_server['status'] == 'build':
            LOG.debug("found server: %s" % found_server)
            time.sleep(1)
            found_server = self.api.get_server(created_server_id)
            retries = retries + 1
            if retries > 5:
                break

        # It should be available...
        # TODO(justinsb): Mock doesn't yet do this...
        #self.assertEqual('available', found_server['status'])

        self._delete_server(created_server_id)

    def _delete_server(self, server_id):
        # Delete the server
        self.api.delete_server(server_id)

        # Wait (briefly) for deletion
        for _retries in range(5):
            try:
                found_server = self.api.get_server(server_id)
            except client.OpenStackApiNotFoundException:
                found_server = None
                LOG.debug("Got 404, proceeding")
                break

            LOG.debug("Found_server=%s" % found_server)

            # TODO(justinsb): Mock doesn't yet do accurate state changes
            #if found_server['status'] != 'deleting':
            #    break
            time.sleep(1)

        # Should be gone
        self.assertFalse(found_server)

    def test_create_server_with_metadata(self):
        """Creates a server with metadata."""

        # Build the server data gradually, checking errors along the way
        server = self._build_minimal_create_server_request()

        metadata = {}
        for i in range(30):
            metadata['key_%s' % i] = 'value_%s' % i

        server['metadata'] = metadata

        post = {'server': server}
        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Reenable when bug fixed
        self.assertEqual(metadata, created_server.get('metadata'))
        # Check it's there

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual(metadata, found_server.get('metadata'))

        # The server should also be in the all-servers details list
        servers = self.api.get_servers(detail=True)
        server_map = dict((server['id'], server) for server in servers)
        found_server = server_map.get(created_server_id)
        self.assertTrue(found_server)
        # Details do include metadata
        self.assertEqual(metadata, found_server.get('metadata'))

        # The server should also be in the all-servers summary list
        servers = self.api.get_servers(detail=False)
        server_map = dict((server['id'], server) for server in servers)
        found_server = server_map.get(created_server_id)
        self.assertTrue(found_server)
        # Summary should not include metadata
        self.assertFalse(found_server.get('metadata'))

        # Cleanup
        self._delete_server(created_server_id)

    def test_create_and_rebuild_server(self):
        """Rebuild a server."""

        # create a server with initially has no metadata
        server = self._build_minimal_create_server_request()
        server_post = {'server': server}
        created_server = self.api.post_server(server_post)
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # rebuild the server with metadata
        post = {}
        post['rebuild'] = {
            "imageRef": "https://localhost/v1.1/32278/images/2",
            "name": "blah",
        }

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s" % created_server)
        self.assertTrue(created_server['id'])

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual({}, found_server.get('metadata'))
        self.assertEqual('blah', found_server.get('name'))

        # Cleanup
        self._delete_server(created_server_id)

    def test_create_and_rebuild_server_with_metadata(self):
        """Rebuild a server with metadata."""

        # create a server with initially has no metadata
        server = self._build_minimal_create_server_request()
        server_post = {'server': server}
        created_server = self.api.post_server(server_post)
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # rebuild the server with metadata
        post = {}
        post['rebuild'] = {
            "imageRef": "https://localhost/v1.1/32278/images/2",
            "name": "blah",
        }

        metadata = {}
        for i in range(30):
            metadata['key_%s' % i] = 'value_%s' % i

        post['rebuild']['metadata'] = metadata

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s" % created_server)
        self.assertTrue(created_server['id'])

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual(metadata, found_server.get('metadata'))
        self.assertEqual('blah', found_server.get('name'))

        # Cleanup
        self._delete_server(created_server_id)

    def test_create_and_rebuild_server_with_metadata_removal(self):
        """Rebuild a server with metadata."""

        # create a server with initially has no metadata
        server = self._build_minimal_create_server_request()
        server_post = {'server': server}

        metadata = {}
        for i in range(30):
            metadata['key_%s' % i] = 'value_%s' % i

        server_post['server']['metadata'] = metadata

        created_server = self.api.post_server(server_post)
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # rebuild the server with metadata
        post = {}
        post['rebuild'] = {
            "imageRef": "https://localhost/v1.1/32278/images/2",
            "name": "blah",
        }

        metadata = {}
        post['rebuild']['metadata'] = metadata

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s" % created_server)
        self.assertTrue(created_server['id'])

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual(metadata, found_server.get('metadata'))
        self.assertEqual('blah', found_server.get('name'))

        # Cleanup
        self._delete_server(created_server_id)

    def test_rename_server(self):
        """Test building and renaming a server."""

        # Create a server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s" % created_server)
        server_id = created_server['id']
        self.assertTrue(server_id)

        # Rename the server to 'new-name'
        self.api.put_server(server_id, {'server': {'name': 'new-name'}})

        # Check the name of the server
        created_server = self.api.get_server(server_id)
        self.assertEqual(created_server['name'], 'new-name')

        # Cleanup
        self._delete_server(server_id)


if __name__ == "__main__":
    unittest.main()
