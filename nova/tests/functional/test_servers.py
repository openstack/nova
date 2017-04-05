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

import datetime
import time
import zlib

import mock
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_utils import timeutils

from nova.compute import api as compute_api
from nova.compute import rpcapi
from nova import context
from nova import exception
from nova import objects
from nova.objects import block_device as block_device_obj
from nova import test
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_network
from nova import volume


LOG = logging.getLogger(__name__)


class ServersTestBase(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2'
    _force_delete_parameter = 'forceDelete'
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'
    _access_ipv4_parameter = 'accessIPv4'
    _access_ipv6_parameter = 'accessIPv6'
    _return_resv_id_parameter = 'return_reservation_id'
    _min_count_parameter = 'min_count'

    def setUp(self):
        super(ServersTestBase, self).setUp()
        # The network service is called as part of server creates but no
        # networks have been populated in the db, so stub the methods.
        # The networks aren't relevant to what is being tested.
        fake_network.set_stub_network_methods(self)
        self.conductor = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')

    def _wait_for_state_change(self, server, from_status):
        for i in range(0, 50):
            server = self.api.get_server(server['id'])
            if server['status'] != from_status:
                break
            time.sleep(.1)

        return server

    def _wait_for_deletion(self, server_id):
        # Wait (briefly) for deletion
        for _retries in range(50):
            try:
                found_server = self.api.get_server(server_id)
            except client.OpenStackApiNotFoundException:
                found_server = None
                LOG.debug("Got 404, proceeding")
                break

            LOG.debug("Found_server=%s", found_server)

            # TODO(justinsb): Mock doesn't yet do accurate state changes
            # if found_server['status'] != 'deleting':
            #    break
            time.sleep(.1)

        # Should be gone
        self.assertFalse(found_server)

    def _delete_server(self, server_id):
        # Delete the server
        self.api.delete_server(server_id)
        self._wait_for_deletion(server_id)

    def _get_access_ips_params(self):
        return {self._access_ipv4_parameter: "172.19.0.2",
                self._access_ipv6_parameter: "fe80::2"}

    def _verify_access_ips(self, server):
        self.assertEqual('172.19.0.2',
                         server[self._access_ipv4_parameter])
        self.assertEqual('fe80::2', server[self._access_ipv6_parameter])


class ServersTest(ServersTestBase):

    def test_get_servers(self):
        # Simple check that listing servers works.
        servers = self.api.get_servers()
        for server in servers:
            LOG.debug("server: %s", server)

    def test_create_server_with_error(self):
        # Create a server which will enter error state.

        def throw_error(*args, **kwargs):
            raise exception.BuildAbortException(reason='',
                    instance_uuid='fake')

        self.stub_out('nova.virt.fake.FakeDriver.spawn', throw_error)

        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'BUILD')

        self.assertEqual('ERROR', found_server['status'])
        self._delete_server(created_server_id)

    def test_create_and_delete_server(self):
        # Creates and deletes a server.

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
        server[self._image_ref_parameter] = self.get_invalid_image()
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # Add a valid imageRef
        server[self._image_ref_parameter] = good_server.get(
            self._image_ref_parameter)

        # Without flavorRef, this throws 500
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        server[self._flavor_ref_parameter] = good_server.get(
            self._flavor_ref_parameter)

        # Without a name, this throws 500
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # Set a valid server name
        server['name'] = good_server['name']

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Check it's there
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        # It should also be in the all-servers list
        servers = self.api.get_servers()
        server_ids = [s['id'] for s in servers]
        self.assertIn(created_server_id, server_ids)

        found_server = self._wait_for_state_change(found_server, 'BUILD')
        # It should be available...
        # TODO(justinsb): Mock doesn't yet do this...
        self.assertEqual('ACTIVE', found_server['status'])
        servers = self.api.get_servers(detail=True)
        for server in servers:
            self.assertIn("image", server)
            self.assertIn("flavor", server)

        self._delete_server(created_server_id)

    def _force_reclaim(self):
        # Make sure that compute manager thinks the instance is
        # old enough to be expired
        the_past = timeutils.utcnow() + datetime.timedelta(hours=1)
        timeutils.set_time_override(override_time=the_past)
        self.addCleanup(timeutils.clear_time_override)
        ctxt = context.get_admin_context()
        self.compute._reclaim_queued_deletes(ctxt)

    def test_deferred_delete(self):
        # Creates, deletes and waits for server to be reclaimed.
        self.flags(reclaim_instance_interval=1)

        # Create server
        server = self._build_minimal_create_server_request()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server)
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

        # Delete the server
        self.api.delete_server(created_server_id)

        # Wait for queued deletion
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')
        self.assertEqual('SOFT_DELETED', found_server['status'])

        self._force_reclaim()

        # Wait for real deletion
        self._wait_for_deletion(created_server_id)

    def test_deferred_delete_restore(self):
        # Creates, deletes and restores a server.
        self.flags(reclaim_instance_interval=3600)

        # Create server
        server = self._build_minimal_create_server_request()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server)
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
        self.assertEqual('SOFT_DELETED', found_server['status'])

        # Restore server
        self.api.post_server_action(created_server_id, {'restore': {}})

        # Wait for server to become active again
        found_server = self._wait_for_state_change(found_server, 'DELETED')
        self.assertEqual('ACTIVE', found_server['status'])

    def test_deferred_delete_force(self):
        # Creates, deletes and force deletes a server.
        self.flags(reclaim_instance_interval=3600)

        # Create server
        server = self._build_minimal_create_server_request()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server)
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
        self.assertEqual('SOFT_DELETED', found_server['status'])

        # Force delete server
        self.api.post_server_action(created_server_id,
                                    {self._force_delete_parameter: {}})

        # Wait for real deletion
        self._wait_for_deletion(created_server_id)

    def test_create_server_with_metadata(self):
        # Creates a server with metadata.

        # Build the server data gradually, checking errors along the way
        server = self._build_minimal_create_server_request()

        metadata = {}
        for i in range(30):
            metadata['key_%s' % i] = 'value_%s' % i

        server['metadata'] = metadata

        post = {'server': server}
        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual(metadata, found_server.get('metadata'))

        # The server should also be in the all-servers details list
        servers = self.api.get_servers(detail=True)
        server_map = {server['id']: server for server in servers}
        found_server = server_map.get(created_server_id)
        self.assertTrue(found_server)
        # Details do include metadata
        self.assertEqual(metadata, found_server.get('metadata'))

        # The server should also be in the all-servers summary list
        servers = self.api.get_servers(detail=False)
        server_map = {server['id']: server for server in servers}
        found_server = server_map.get(created_server_id)
        self.assertTrue(found_server)
        # Summary should not include metadata
        self.assertFalse(found_server.get('metadata'))

        # Cleanup
        self._delete_server(created_server_id)

    def test_server_metadata_actions_negative_invalid_state(self):
        # Create server with metadata
        server = self._build_minimal_create_server_request()

        metadata = {'key_1': 'value_1'}

        server['metadata'] = metadata

        post = {'server': server}
        created_server = self.api.post_server(post)

        found_server = self._wait_for_state_change(created_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])
        self.assertEqual(metadata, found_server.get('metadata'))
        server_id = found_server['id']

        # Change status from ACTIVE to SHELVED for negative test
        self.flags(shelved_offload_time = -1)
        self.api.post_server_action(server_id, {'shelve': {}})
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')
        self.assertEqual('SHELVED', found_server['status'])

        metadata = {'key_2': 'value_2'}

        # Update Metadata item in SHELVED (not ACTIVE, etc.)
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_metadata,
                               server_id, metadata)
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('SHELVED', found_server['status'])

        # Delete Metadata item in SHELVED (not ACTIVE, etc.)
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.delete_server_metadata,
                               server_id, 'key_1')
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('SHELVED', found_server['status'])

        # Cleanup
        self._delete_server(server_id)

    def test_create_and_rebuild_server(self):
        # Rebuild a server with metadata.

        # create a server with initially has no metadata
        server = self._build_minimal_create_server_request()
        server_post = {'server': server}

        metadata = {}
        for i in range(30):
            metadata['key_%s' % i] = 'value_%s' % i

        server_post['server']['metadata'] = metadata

        created_server = self.api.post_server(server_post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        created_server = self._wait_for_state_change(created_server, 'BUILD')

        # rebuild the server with metadata and other server attributes
        post = {}
        post['rebuild'] = {
            self._image_ref_parameter: "76fa36fc-c930-4bf3-8c8a-ea2a2420deb6",
            "name": "blah",
            self._access_ipv4_parameter: "172.19.0.2",
            self._access_ipv6_parameter: "fe80::2",
            "metadata": {'some': 'thing'},
        }
        post['rebuild'].update(self._get_access_ips_params())

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s", created_server)
        self.assertTrue(created_server['id'])

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual({'some': 'thing'}, found_server.get('metadata'))
        self.assertEqual('blah', found_server.get('name'))
        self.assertEqual(post['rebuild'][self._image_ref_parameter],
                         found_server.get('image')['id'])
        self._verify_access_ips(found_server)

        # rebuild the server with empty metadata and nothing else
        post = {}
        post['rebuild'] = {
            self._image_ref_parameter: "76fa36fc-c930-4bf3-8c8a-ea2a2420deb6",
            "metadata": {},
        }

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s", created_server)
        self.assertTrue(created_server['id'])

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])
        self.assertEqual({}, found_server.get('metadata'))
        self.assertEqual('blah', found_server.get('name'))
        self.assertEqual(post['rebuild'][self._image_ref_parameter],
                         found_server.get('image')['id'])
        self._verify_access_ips(found_server)

        # Cleanup
        self._delete_server(created_server_id)

    def test_rename_server(self):
        # Test building and renaming a server.

        # Create a server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server)
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
        # Creates multiple servers and checks for reservation_id.

        # Create 2 servers, setting 'return_reservation_id, which should
        # return a reservation_id
        server = self._build_minimal_create_server_request()
        server[self._min_count_parameter] = 2
        server[self._return_resv_id_parameter] = True
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
        server_map = {server['id']: server for server in servers}
        found_server = server_map.get(created_server_id)
        # The server from the 2nd request should not be there.
        self.assertIsNone(found_server)
        # Should have found 2 servers.
        self.assertEqual(len(server_map), 2)

        # Cleanup
        self._delete_server(created_server_id)
        for server_id in server_map:
            self._delete_server(server_id)

    def test_create_server_with_injected_files(self):
        # Creates a server with injected_files.
        personality = []

        # Inject a text file
        data = 'Hello, World!'
        personality.append({
            'path': '/helloworld.txt',
            'contents': base64.encode_as_bytes(data),
        })

        # Inject a binary file
        data = zlib.compress(b'Hello, World!')
        personality.append({
            'path': '/helloworld.zip',
            'contents': base64.encode_as_bytes(data),
        })

        # Create server
        server = self._build_minimal_create_server_request()
        server['personality'] = personality

        post = {'server': server}

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Check it's there
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # Cleanup
        self._delete_server(created_server_id)

    def test_stop_start_servers_negative_invalid_state(self):
        # Create server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self._wait_for_state_change(created_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # Start server in ACTIVE
        # NOTE(mkoshiya): When os-start API runs, the server status
        # must be SHUTOFF.
        # By returning 409, I want to confirm that the ACTIVE server does not
        # cause unexpected behavior.
        post = {'os-start': {}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id, post)
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('ACTIVE', found_server['status'])

        # Stop server
        post = {'os-stop': {}}
        self.api.post_server_action(created_server_id, post)
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')
        self.assertEqual('SHUTOFF', found_server['status'])

        # Stop server in SHUTOFF
        # NOTE(mkoshiya): When os-stop API runs, the server status
        # must be ACTIVE or ERROR.
        # By returning 409, I want to confirm that the SHUTOFF server does not
        # cause unexpected behavior.
        post = {'os-stop': {}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id, post)
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('SHUTOFF', found_server['status'])

        # Cleanup
        self._delete_server(created_server_id)

    def test_revert_resized_server_negative_invalid_state(self):
        # Create server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # Revert resized server in ACTIVE
        # NOTE(yatsumi): When revert resized server API runs,
        # the server status must be VERIFY_RESIZE.
        # By returning 409, I want to confirm that the ACTIVE server does not
        # cause unexpected behavior.
        post = {'revertResize': {}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id, post)
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('ACTIVE', found_server['status'])

        # Cleanup
        self._delete_server(created_server_id)

    def test_resize_server_negative_invalid_state(self):
        # Avoid migration
        self.flags(allow_resize_to_same_host=True)

        # Create server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # Resize server(flavorRef: 1 -> 2)
        post = {'resize': {"flavorRef": "2", "OS-DCF:diskConfig": "AUTO"}}
        self.api.post_server_action(created_server_id, post)
        found_server = self._wait_for_state_change(found_server, 'RESIZE')
        self.assertEqual('VERIFY_RESIZE', found_server['status'])

        # Resize server in VERIFY_RESIZE(flavorRef: 2 -> 1)
        # NOTE(yatsumi): When resize API runs, the server status
        # must be ACTIVE or SHUTOFF.
        # By returning 409, I want to confirm that the VERIFY_RESIZE server
        # does not cause unexpected behavior.
        post = {'resize': {"flavorRef": "1", "OS-DCF:diskConfig": "AUTO"}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id, post)
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('VERIFY_RESIZE', found_server['status'])

        # Cleanup
        self._delete_server(created_server_id)

    def test_confirm_resized_server_negative_invalid_state(self):
        # Create server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # Confirm resized server in ACTIVE
        # NOTE(yatsumi): When confirm resized server API runs,
        # the server status must be VERIFY_RESIZE.
        # By returning 409, I want to confirm that the ACTIVE server does not
        # cause unexpected behavior.
        post = {'confirmResize': {}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id, post)
        self.assertEqual(409, ex.response.status_code)
        self.assertEqual('ACTIVE', found_server['status'])

        # Cleanup
        self._delete_server(created_server_id)


class ServersTestV21(ServersTest):
    api_major_version = 'v2.1'


class ServersTestV219(ServersTestBase):
    api_major_version = 'v2.1'

    def _create_server(self, set_desc = True, desc = None):
        server = self._build_minimal_create_server_request()
        if set_desc:
            server['description'] = desc
        post = {'server': server}
        response = self.api.api_post('/servers', post).body
        return (server, response['server'])

    def _update_server(self, server_id, set_desc = True, desc = None):
        new_name = integrated_helpers.generate_random_alphanumeric(8)
        server = {'server': {'name': new_name}}
        if set_desc:
            server['server']['description'] = desc
        self.api.api_put('/servers/%s' % server_id, server)

    def _rebuild_server(self, server_id, set_desc = True, desc = None):
        new_name = integrated_helpers.generate_random_alphanumeric(8)
        post = {}
        post['rebuild'] = {
            "name": new_name,
            self._image_ref_parameter: "76fa36fc-c930-4bf3-8c8a-ea2a2420deb6",
            self._access_ipv4_parameter: "172.19.0.2",
            self._access_ipv6_parameter: "fe80::2",
            "metadata": {'some': 'thing'},
        }
        post['rebuild'].update(self._get_access_ips_params())
        if set_desc:
            post['rebuild']['description'] = desc
        self.api.api_post('/servers/%s/action' % server_id, post)

    def _create_server_and_verify(self, set_desc = True, expected_desc = None):
        # Creates a server with a description and verifies it is
        # in the GET responses.
        created_server_id = self._create_server(set_desc,
                                                expected_desc)[1]['id']
        self._verify_server_description(created_server_id, expected_desc)
        self._delete_server(created_server_id)

    def _update_server_and_verify(self, server_id, set_desc = True,
                                  expected_desc = None):
        # Updates a server with a description and verifies it is
        # in the GET responses.
        self._update_server(server_id, set_desc, expected_desc)
        self._verify_server_description(server_id, expected_desc)

    def _rebuild_server_and_verify(self, server_id, set_desc = True,
                                  expected_desc = None):
        # Rebuilds a server with a description and verifies it is
        # in the GET responses.
        self._rebuild_server(server_id, set_desc, expected_desc)
        self._verify_server_description(server_id, expected_desc)

    def _verify_server_description(self, server_id, expected_desc = None,
                                   desc_in_resp = True):
        # Calls GET on the servers and verifies that the description
        # is set as expected in the response, or not set at all.
        response = self.api.api_get('/servers/%s' % server_id)
        found_server = response.body['server']
        self.assertEqual(server_id, found_server['id'])
        if desc_in_resp:
            # Verify the description is set as expected (can be None)
            self.assertEqual(expected_desc, found_server.get('description'))
        else:
            # Verify the description is not included in the response.
            self.assertNotIn('description', found_server)

        servers = self.api.api_get('/servers/detail').body['servers']
        server_map = {server['id']: server for server in servers}
        found_server = server_map.get(server_id)
        self.assertTrue(found_server)
        if desc_in_resp:
            # Verify the description is set as expected (can be None)
            self.assertEqual(expected_desc, found_server.get('description'))
        else:
            # Verify the description is not included in the response.
            self.assertNotIn('description', found_server)

    def _create_assertRaisesRegex(self, desc):
        # Verifies that a 400 error is thrown on create server
        with self.assertRaisesRegex(client.OpenStackApiException,
                                    ".*Unexpected status code.*") as cm:
            self._create_server(True, desc)
            self.assertEqual(400, cm.exception.response.status_code)

    def _update_assertRaisesRegex(self, server_id, desc):
        # Verifies that a 400 error is thrown on update server
        with self.assertRaisesRegex(client.OpenStackApiException,
                                    ".*Unexpected status code.*") as cm:
            self._update_server(server_id, True, desc)
            self.assertEqual(400, cm.exception.response.status_code)

    def _rebuild_assertRaisesRegex(self, server_id, desc):
        # Verifies that a 400 error is thrown on rebuild server
        with self.assertRaisesRegex(client.OpenStackApiException,
                                    ".*Unexpected status code.*") as cm:
            self._rebuild_server(server_id, True, desc)
            self.assertEqual(400, cm.exception.response.status_code)

    def test_create_server_with_description(self):
        self.api.microversion = '2.19'
        # Create and get a server with a description
        self._create_server_and_verify(True, 'test description')
        # Create and get a server with an empty description
        self._create_server_and_verify(True, '')
        # Create and get a server with description set to None
        self._create_server_and_verify()
        # Create and get a server without setting the description
        self._create_server_and_verify(False)

    def test_update_server_with_description(self):
        self.api.microversion = '2.19'
        # Create a server with an initial description
        server_id = self._create_server(True, 'test desc 1')[1]['id']

        # Update and get the server with a description
        self._update_server_and_verify(server_id, True, 'updated desc')
        # Update and get the server name without changing the description
        self._update_server_and_verify(server_id, False, 'updated desc')
        # Update and get the server with an empty description
        self._update_server_and_verify(server_id, True, '')
        # Update and get the server by removing the description (set to None)
        self._update_server_and_verify(server_id)
        # Update and get the server with a 2nd new description
        self._update_server_and_verify(server_id, True, 'updated desc2')

        # Cleanup
        self._delete_server(server_id)

    def test_rebuild_server_with_description(self):
        self.api.microversion = '2.19'

        # Create a server with an initial description
        server = self._create_server(True, 'test desc 1')[1]
        server_id = server['id']
        self._wait_for_state_change(server, 'BUILD')

        # Rebuild and get the server with a description
        self._rebuild_server_and_verify(server_id, True, 'updated desc')
        # Rebuild and get the server name without changing the description
        self._rebuild_server_and_verify(server_id, False, 'updated desc')
        # Rebuild and get the server with an empty description
        self._rebuild_server_and_verify(server_id, True, '')
        # Rebuild and get the server by removing the description (set to None)
        self._rebuild_server_and_verify(server_id)
        # Rebuild and get the server with a 2nd new description
        self._rebuild_server_and_verify(server_id, True, 'updated desc2')

        # Cleanup
        self._delete_server(server_id)

    def test_version_compatibility(self):
        # Create a server with microversion v2.19 and a description.
        self.api.microversion = '2.19'
        server_id = self._create_server(True, 'test desc 1')[1]['id']
        # Verify that the description is not included on V2.18 GETs
        self.api.microversion = '2.18'
        self._verify_server_description(server_id, desc_in_resp = False)
        # Verify that updating the server with description on V2.18
        # results in a 400 error
        self._update_assertRaisesRegex(server_id, 'test update 2.18')
        # Verify that rebuilding the server with description on V2.18
        # results in a 400 error
        self._rebuild_assertRaisesRegex(server_id, 'test rebuild 2.18')

        # Cleanup
        self._delete_server(server_id)

        # Create a server on V2.18 and verify that the description
        # defaults to the name on a V2.19 GET
        server_req, response = self._create_server(False)
        server_id = response['id']
        self.api.microversion = '2.19'
        self._verify_server_description(server_id, server_req['name'])

        # Cleanup
        self._delete_server(server_id)

        # Verify that creating a server with description on V2.18
        # results in a 400 error
        self.api.microversion = '2.18'
        self._create_assertRaisesRegex('test create 2.18')

    def test_description_errors(self):
        self.api.microversion = '2.19'
        # Create servers with invalid descriptions.  These throw 400.
        # Invalid unicode with non-printable control char
        self._create_assertRaisesRegex(u'invalid\0dstring')
        # Description is longer than 255 chars
        self._create_assertRaisesRegex('x' * 256)

        # Update and rebuild servers with invalid descriptions.
        # These throw 400.
        server_id = self._create_server(True, "desc")[1]['id']
        # Invalid unicode with non-printable control char
        self._update_assertRaisesRegex(server_id, u'invalid\u0604string')
        self._rebuild_assertRaisesRegex(server_id, u'invalid\u0604string')
        # Description is longer than 255 chars
        self._update_assertRaisesRegex(server_id, 'x' * 256)
        self._rebuild_assertRaisesRegex(server_id, 'x' * 256)


class ServerTestV220(ServersTestBase):
    api_major_version = 'v2.1'

    def setUp(self):
        super(ServerTestV220, self).setUp()
        self.api.microversion = '2.20'
        fake_network.set_stub_network_methods(self)
        self.ctxt = context.get_admin_context()

    def _create_server(self):
        server = self._build_minimal_create_server_request()
        post = {'server': server}
        response = self.api.api_post('/servers', post).body
        return (server, response['server'])

    def _shelve_server(self):
        server = self._create_server()[1]
        server_id = server['id']
        self._wait_for_state_change(server, 'BUILD')
        self.api.post_server_action(server_id, {'shelve': None})
        return self._wait_for_state_change(server, 'ACTIVE')

    def _get_fake_bdms(self, ctxt):
        return block_device_obj.block_device_make_list(self.ctxt,
                    [fake_block_device.FakeDbBlockDeviceDict(
                    {'device_name': '/dev/vda',
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'volume_id': '5d721593-f033-4f6d-ab6f-b5b067e61bc4'})])

    def test_attach_detach_vol_to_shelved_server(self):
        self.flags(shelved_offload_time=-1)
        found_server = self._shelve_server()
        self.assertEqual('SHELVED', found_server['status'])
        server_id = found_server['id']

        # Test attach volume
        with test.nested(mock.patch.object(compute_api.API,
                                       '_check_attach_and_reserve_volume'),
                         mock.patch.object(rpcapi.ComputeAPI,
                                       'attach_volume')) as (mock_reserve,
                                                             mock_attach):
            volume_attachment = {"volumeAttachment": {"volumeId":
                                       "5d721593-f033-4f6d-ab6f-b5b067e61bc4"}}
            self.api.api_post(
                            '/servers/%s/os-volume_attachments' % (server_id),
                            volume_attachment)
            self.assertTrue(mock_reserve.called)
            self.assertTrue(mock_attach.called)

        # Test detach volume
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        with test.nested(mock.patch.object(compute_api.API,
                                           '_check_and_begin_detach'),
                         mock.patch.object(objects.BlockDeviceMappingList,
                                           'get_by_instance_uuid'),
                         mock.patch.object(rpcapi.ComputeAPI,
                                           'detach_volume')
                         ) as (mock_check, mock_get_bdms, mock_rpc):

            mock_get_bdms.return_value = self._get_fake_bdms(self.ctxt)
            attachment_id = mock_get_bdms.return_value[0]['volume_id']

            self.api.api_delete('/servers/%s/os-volume_attachments/%s' %
                            (server_id, attachment_id))
            self.assertTrue(mock_check.called)
            self.assertTrue(mock_rpc.called)

        self._delete_server(server_id)

    def test_attach_detach_vol_to_shelved_offloaded_server(self):
        self.flags(shelved_offload_time=0)
        found_server = self._shelve_server()
        self.assertEqual('SHELVED_OFFLOADED', found_server['status'])
        server_id = found_server['id']

        # Test attach volume
        with test.nested(mock.patch.object(compute_api.API,
                                       '_check_attach_and_reserve_volume'),
                         mock.patch.object(volume.cinder.API,
                                       'attach')) as (mock_reserve, mock_vol):
            volume_attachment = {"volumeAttachment": {"volumeId":
                                       "5d721593-f033-4f6d-ab6f-b5b067e61bc4"}}
            attach_response = self.api.api_post(
                             '/servers/%s/os-volume_attachments' % (server_id),
                             volume_attachment).body['volumeAttachment']
            self.assertTrue(mock_reserve.called)
            self.assertTrue(mock_vol.called)
            self.assertIsNone(attach_response['device'])

        # Test detach volume
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        with test.nested(mock.patch.object(compute_api.API,
                                           '_check_and_begin_detach'),
                         mock.patch.object(objects.BlockDeviceMappingList,
                                           'get_by_instance_uuid'),
                         mock.patch.object(compute_api.API,
                                           '_local_cleanup_bdm_volumes')
                         ) as (mock_check, mock_get_bdms, mock_clean_vols):

            mock_get_bdms.return_value = self._get_fake_bdms(self.ctxt)
            attachment_id = mock_get_bdms.return_value[0]['volume_id']
            self.api.api_delete('/servers/%s/os-volume_attachments/%s' %
                            (server_id, attachment_id))
            self.assertTrue(mock_check.called)
            self.assertTrue(mock_clean_vols.called)

        self._delete_server(server_id)
