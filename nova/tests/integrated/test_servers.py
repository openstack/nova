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

import nova.virt.fake
from nova.log import logging
from nova.tests.integrated import integrated_helpers
from nova.tests.integrated.api import client


LOG = logging.getLogger(__name__)


class ServersTest(integrated_helpers._IntegratedTestBase):

    def _wait_for_state_change(self, server, from_status):
        for i in xrange(0, 50):
            server = self.api.get_server(server['id'])
            if server['status'] != from_status:
                break
            time.sleep(.1)

        return server

    def _restart_compute_service(self, periodic_interval=None):
        """restart compute service. NOTE: fake driver forgets all instances."""
        self.compute.kill()
        if periodic_interval:
            self.compute = self.start_service(
                'compute', periodic_interval=periodic_interval)
        else:
            self.compute = self.start_service('compute')

    def test_get_servers(self):
        """Simple check that listing servers works."""
        servers = self.api.get_servers()
        for server in servers:
            LOG.debug("server: %s" % server)

    def test_create_server_with_error(self):
        """Create a server which will enter error state."""
        self.flags(stub_network=True)

        def throw_error(*_):
            raise Exception()

        self.stubs.Set(nova.virt.fake.FakeConnection, 'spawn', throw_error)

        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'BUILD')

        self.assertEqual('ERROR', found_server['status'])
        self._delete_server(created_server_id)

    def test_create_and_delete_server(self):
        """Creates and deletes a server."""
        self.flags(stub_network=True)

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
        server['imageRef'] = self.get_invalid_image()
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # Add a valid imageRef
        server['imageRef'] = good_server.get('imageRef')

        # Without flavorRef, this throws 500
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        server['flavorRef'] = good_server.get('flavorRef')

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

        found_server = self._wait_for_state_change(found_server, 'BUILD')
        # It should be available...
        # TODO(justinsb): Mock doesn't yet do this...
        self.assertEqual('ACTIVE', found_server['status'])
        servers = self.api.get_servers(detail=True)
        for server in servers:
            self.assertTrue("image" in server)
            self.assertTrue("flavor" in server)

        self._delete_server(created_server_id)

    def test_deferred_delete(self):
        """Creates, deletes and waits for server to be reclaimed."""
        self.flags(stub_network=True, reclaim_instance_interval=1)

        # enforce periodic tasks run in short time to avoid wait for 60s.
        self._restart_compute_service(periodic_interval=0.3)

        # Create server
        server = self._build_minimal_create_server_request()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(created_server, 'BUILD')

        # It should be available...
        self.assertEqual('ACTIVE', found_server['status'])

        # Cannot restore unless instance is deleted
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server_action, created_server_id,
                          {'restore': {}})

        # Cannot forceDelete unless instance is deleted
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server_action, created_server_id,
                          {'forceDelete': {}})

        # Delete the server
        self.api.delete_server(created_server_id)

        # Wait for queued deletion
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')
        self.assertEqual('DELETED', found_server['status'])

        # Wait for real deletion
        self._wait_for_deletion(created_server_id)

    def test_deferred_delete_restore(self):
        """Creates, deletes and restores a server."""
        self.flags(stub_network=True, reclaim_instance_interval=1)

        # Create server
        server = self._build_minimal_create_server_request()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(created_server, 'BUILD')

        # It should be available...
        self.assertEqual('ACTIVE', found_server['status'])

        # Delete the server
        self.api.delete_server(created_server_id)

        # Wait for queued deletion
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')
        self.assertEqual('DELETED', found_server['status'])

        # Restore server
        self.api.post_server_action(created_server_id, {'restore': {}})

        # Wait for server to become active again
        found_server = self._wait_for_state_change(found_server, 'DELETED')
        self.assertEqual('ACTIVE', found_server['status'])

    def test_deferred_delete_force(self):
        """Creates, deletes and force deletes a server."""
        self.flags(stub_network=True, reclaim_instance_interval=1)

        # Create server
        server = self._build_minimal_create_server_request()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s" % created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(created_server, 'BUILD')

        # It should be available...
        self.assertEqual('ACTIVE', found_server['status'])

        # Delete the server
        self.api.delete_server(created_server_id)

        # Wait for queued deletion
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')
        self.assertEqual('DELETED', found_server['status'])

        # Force delete server
        self.api.post_server_action(created_server_id, {'forceDelete': {}})

        # Wait for real deletion
        self._wait_for_deletion(created_server_id)

    def _wait_for_deletion(self, server_id):
        # Wait (briefly) for deletion
        for _retries in range(50):
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
            time.sleep(.1)

        # Should be gone
        self.assertFalse(found_server)

    def _delete_server(self, server_id):
        # Delete the server
        self.api.delete_server(server_id)
        self._wait_for_deletion(server_id)

    def test_create_server_with_metadata(self):
        """Creates a server with metadata."""
        self.flags(stub_network=True)

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
        """Rebuild a server with metadata."""
        self.flags(stub_network=True)

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

        created_server = self._wait_for_state_change(created_server, 'BUILD')

        # rebuild the server with metadata and other server attributes
        post = {}
        post['rebuild'] = {
            "imageRef": "76fa36fc-c930-4bf3-8c8a-ea2a2420deb6",
            "name": "blah",
            "accessIPv4": "172.19.0.2",
            "accessIPv6": "fe80::2",
            "metadata": {'some': 'thing'},
        }

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s" % created_server)
        self.assertTrue(created_server['id'])

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual({'some': 'thing'}, found_server.get('metadata'))
        self.assertEqual('blah', found_server.get('name'))
        self.assertEqual(post['rebuild']['imageRef'],
                         found_server.get('image')['id'])
        self.assertEqual('172.19.0.2', found_server['accessIPv4'])
        self.assertEqual('fe80::2', found_server['accessIPv6'])

        # rebuild the server with empty metadata and nothing else
        post = {}
        post['rebuild'] = {
            "imageRef": "76fa36fc-c930-4bf3-8c8a-ea2a2420deb6",
            "metadata": {},
        }

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s" % created_server)
        self.assertTrue(created_server['id'])

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual({}, found_server.get('metadata'))
        self.assertEqual('blah', found_server.get('name'))
        self.assertEqual(post['rebuild']['imageRef'],
                         found_server.get('image')['id'])
        self.assertEqual('172.19.0.2', found_server['accessIPv4'])
        self.assertEqual('fe80::2', found_server['accessIPv6'])

        # Cleanup
        self._delete_server(created_server_id)

    def test_rename_server(self):
        """Test building and renaming a server."""
        self.flags(stub_network=True)

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

    def test_create_multiple_servers(self):
        """Creates multiple servers and checks for reservation_id"""

        # Create 2 servers, setting 'return_reservation_id, which should
        # return a reservation_id
        server = self._build_minimal_create_server_request()
        server['min_count'] = 2
        server['return_reservation_id'] = True
        post = {'server': server}
        response = self.api.post_server(post)
        self.assertIn('reservation_id', response)
        reservation_id = response['reservation_id']
        self.assertNotIn(reservation_id, ['', None])

        # Create 1 more server, which should not return a reservation_id
        server = self._build_minimal_create_server_request()
        post = {'server': server}
        created_server = self.api.post_server(post)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # lookup servers created by the first request.
        servers = self.api.get_servers(detail=True,
                search_opts={'reservation_id': reservation_id})
        server_map = dict((server['id'], server) for server in servers)
        found_server = server_map.get(created_server_id)
        # The server from the 2nd request should not be there.
        self.assertEqual(found_server, None)
        # Should have found 2 servers.
        self.assertEqual(len(server_map), 2)

        # Cleanup
        self._delete_server(created_server_id)
        for server_id in server_map.iterkeys():
            self._delete_server(server_id)


if __name__ == "__main__":
    unittest.main()
