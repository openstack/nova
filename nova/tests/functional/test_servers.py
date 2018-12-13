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
import six

from nova.compute import api as compute_api
from nova.compute import instance_actions
from nova.compute import manager as compute_manager
from nova.compute import rpcapi
from nova import context
from nova import exception
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.scheduler import weights
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_notifier
import nova.tests.unit.image.fake
from nova.tests import uuidsentinel as uuids
from nova.virt import fake
from nova import volume


LOG = logging.getLogger(__name__)


class AltHostWeigher(weights.BaseHostWeigher):
    """Used in the alternate host tests to return a pre-determined list of
    hosts.
    """
    def _weigh_object(self, host_state, weight_properties):
        """Return a defined order of hosts."""
        weights = {"selection": 999, "alt_host1": 888, "alt_host2": 777,
                   "alt_host3": 666, "host1": 0, "host2": 0}
        return weights.get(host_state.host, 0)


class ServersTestBase(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2'
    _force_delete_parameter = 'forceDelete'
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'
    _access_ipv4_parameter = 'accessIPv4'
    _access_ipv6_parameter = 'accessIPv6'
    _return_resv_id_parameter = 'return_reservation_id'
    _min_count_parameter = 'min_count'

    USE_NEUTRON = True

    def setUp(self):
        self.computes = {}
        super(ServersTestBase, self).setUp()
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

    def _get_node_build_failures(self):
        ctxt = context.get_admin_context()
        computes = objects.ComputeNodeList.get_all(ctxt)
        return {
            node.hypervisor_hostname: int(node.stats.get('failed_builds', 0))
            for node in computes}

    def _run_periodics(self):
        """Run the update_available_resource task on every compute manager

        This runs periodics on the computes in an undefined order; some child
        class redefined this function to force a specific order.
        """

        if self.compute.host not in self.computes:
            self.computes[self.compute.host] = self.compute

        ctx = context.get_admin_context()
        for compute in self.computes.values():
            LOG.info('Running periodic for compute (%s)',
                compute.manager.host)
            compute.manager.update_available_resource(ctx)
        LOG.info('Finished with periodics')

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

        # We should have no (persisted) build failures until we update
        # resources, after which we should have one
        self.assertEqual([0], list(self._get_node_build_failures().values()))
        self._run_periodics()
        self.assertEqual([1], list(self._get_node_build_failures().values()))

    def _test_create_server_with_error_with_retries(self):
        # Create a server which will enter error state.

        fake.set_nodes(['host2'])
        self.addCleanup(fake.restore_nodes)
        self.flags(host='host2')
        self.compute2 = self.start_service('compute', host='host2')
        self.computes['compute2'] = self.compute2

        fails = []

        def throw_error(*args, **kwargs):
            fails.append('one')
            raise test.TestingException('Please retry me')

        self.stub_out('nova.virt.fake.FakeDriver.spawn', throw_error)

        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'BUILD')

        self.assertEqual('ERROR', found_server['status'])
        self._delete_server(created_server_id)

        return len(fails)

    def test_create_server_with_error_with_retries(self):
        self.flags(max_attempts=2, group='scheduler')
        fails = self._test_create_server_with_error_with_retries()
        self.assertEqual(2, fails)
        self._run_periodics()
        self.assertEqual(
            [1, 1], list(self._get_node_build_failures().values()))

    def test_create_server_with_error_with_no_retries(self):
        self.flags(max_attempts=1, group='scheduler')
        fails = self._test_create_server_with_error_with_retries()
        self.assertEqual(1, fails)
        self._run_periodics()
        self.assertEqual(
            [0, 1], list(sorted(self._get_node_build_failures().values())))

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

    def test_deferred_delete_restore_overquota(self):
        # Test that a restore that would put the user over quota fails
        self.flags(instances=1, group='quota')
        # Creates, deletes and restores a server.
        self.flags(reclaim_instance_interval=3600)

        # Create server
        server = self._build_minimal_create_server_request()

        created_server1 = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server1)
        self.assertTrue(created_server1['id'])
        created_server_id1 = created_server1['id']

        # Wait for it to finish being created
        found_server1 = self._wait_for_state_change(created_server1, 'BUILD')

        # It should be available...
        self.assertEqual('ACTIVE', found_server1['status'])

        # Delete the server
        self.api.delete_server(created_server_id1)

        # Wait for queued deletion
        found_server1 = self._wait_for_state_change(found_server1, 'ACTIVE')
        self.assertEqual('SOFT_DELETED', found_server1['status'])

        # Create a second server
        server = self._build_minimal_create_server_request()

        created_server2 = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server2)
        self.assertTrue(created_server2['id'])

        # Wait for it to finish being created
        found_server2 = self._wait_for_state_change(created_server2, 'BUILD')

        # It should be available...
        self.assertEqual('ACTIVE', found_server2['status'])

        # Try to restore the first server, it should fail
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id1, {'restore': {}})
        self.assertEqual(403, ex.response.status_code)
        self.assertEqual('SOFT_DELETED', found_server1['status'])

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

    def test_resize_server_overquota(self):
        self.flags(cores=1, group='quota')
        self.flags(ram=512, group='quota')
        # Create server with default flavor, 1 core, 512 ram
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self._wait_for_state_change(created_server, 'BUILD')
        self.assertEqual('ACTIVE', found_server['status'])

        # Try to resize to flavorid 2, 1 core, 2048 ram
        post = {'resize': {'flavorRef': '2'}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id, post)
        self.assertEqual(403, ex.response.status_code)


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
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        with test.nested(mock.patch.object(volume.cinder,
                                       'is_microversion_supported'),
                         mock.patch.object(compute_api.API,
                                       '_check_attach_and_reserve_volume'),
                         mock.patch.object(rpcapi.ComputeAPI,
                                       'attach_volume')) as (mock_cinder_mv,
                                                             mock_reserve,
                                                             mock_attach):
            mock_cinder_mv.side_effect = \
                exception.CinderAPIVersionNotAvailable(version='3.44')
            volume_attachment = {"volumeAttachment": {"volumeId":
                                       "5d721593-f033-4f6d-ab6f-b5b067e61bc4"}}
            self.api.api_post(
                            '/servers/%s/os-volume_attachments' % (server_id),
                            volume_attachment)
            self.assertTrue(mock_reserve.called)
            self.assertTrue(mock_attach.called)

        # Test detach volume
        with test.nested(mock.patch.object(volume.cinder.API,
                                           'begin_detaching'),
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
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        with test.nested(mock.patch.object(volume.cinder,
                                       'is_microversion_supported'),
                         mock.patch.object(compute_api.API,
                                       '_check_attach_and_reserve_volume'),
                         mock.patch.object(volume.cinder.API,
                                       'attach')) as (mock_cinder_mv,
                                                      mock_reserve, mock_vol):
            mock_cinder_mv.side_effect = \
                exception.CinderAPIVersionNotAvailable(version='3.44')
            volume_attachment = {"volumeAttachment": {"volumeId":
                                       "5d721593-f033-4f6d-ab6f-b5b067e61bc4"}}
            attach_response = self.api.api_post(
                             '/servers/%s/os-volume_attachments' % (server_id),
                             volume_attachment).body['volumeAttachment']
            self.assertTrue(mock_reserve.called)
            self.assertTrue(mock_vol.called)
            self.assertIsNone(attach_response['device'])

        # Test detach volume
        with test.nested(mock.patch.object(volume.cinder.API,
                                           'begin_detaching'),
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

    def test_attach_detach_vol_to_shelved_offloaded_server_new_flow(self):
        self.flags(shelved_offload_time=0)
        found_server = self._shelve_server()
        self.assertEqual('SHELVED_OFFLOADED', found_server['status'])
        server_id = found_server['id']
        fake_bdms = self._get_fake_bdms(self.ctxt)

        # Test attach volume
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        with test.nested(mock.patch.object(volume.cinder,
                                       'is_microversion_supported'),
                         mock.patch.object(compute_api.API,
                            '_check_volume_already_attached_to_instance'),
                         mock.patch.object(volume.cinder.API,
                                        'check_availability_zone'),
                         mock.patch.object(volume.cinder.API,
                                        'attachment_create'),
                         mock.patch.object(volume.cinder.API,
                                        'attachment_complete')
                         ) as (mock_cinder_mv, mock_check_vol_attached,
                               mock_check_av_zone, mock_attach_create,
                               mock_attachment_complete):
            mock_attach_create.return_value = {'id': uuids.volume}
            volume_attachment = {"volumeAttachment": {"volumeId":
                                       "5d721593-f033-4f6d-ab6f-b5b067e61bc4"}}
            attach_response = self.api.api_post(
                             '/servers/%s/os-volume_attachments' % (server_id),
                             volume_attachment).body['volumeAttachment']
            self.assertTrue(mock_attach_create.called)
            mock_attachment_complete.assert_called_once_with(
                mock.ANY, uuids.volume)
            self.assertIsNone(attach_response['device'])

        # Test detach volume
        with test.nested(mock.patch.object(objects.BlockDeviceMappingList,
                                           'get_by_instance_uuid'),
                         mock.patch.object(compute_api.API,
                                           '_local_cleanup_bdm_volumes')
                         ) as (mock_get_bdms, mock_clean_vols):

            mock_get_bdms.return_value = fake_bdms
            attachment_id = mock_get_bdms.return_value[0]['volume_id']
            self.api.api_delete('/servers/%s/os-volume_attachments/%s' %
                            (server_id, attachment_id))
            self.assertTrue(mock_clean_vols.called)

        self._delete_server(server_id)


class ServerRebuildTestCase(integrated_helpers._IntegratedTestBase,
                            integrated_helpers.InstanceHelperMixin):
    api_major_version = 'v2.1'
    # We have to cap the microversion at 2.38 because that's the max we
    # can use to update image metadata via our compute images proxy API.
    microversion = '2.38'

    def _disable_compute_for(self, server):
        # Refresh to get its host
        server = self.api.get_server(server['id'])
        host = server['OS-EXT-SRV-ATTR:host']

        # Disable the service it is on
        self.api_fixture.admin_api.put_service('disable',
                                               {'host': host,
                                                'binary': 'nova-compute'})

    def test_rebuild_with_image_novalidhost(self):
        """Creates a server with an image that is valid for the single compute
        that we have. Then rebuilds the server, passing in an image with
        metadata that does not fit the single compute which should result in
        a NoValidHost error. The ImagePropertiesFilter filter is enabled by
        default so that should filter out the host based on the image meta.
        """

        fake.set_nodes(['host2'])
        self.addCleanup(fake.restore_nodes)
        self.flags(host='host2')
        self.compute2 = self.start_service('compute', host='host2')

        # We hard-code from a fake image since we can't get images
        # via the compute /images proxy API with microversion > 2.35.
        original_image_ref = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        server_req_body = {
            'server': {
                'imageRef': original_image_ref,
                'flavorRef': '1',   # m1.tiny from DefaultFlavorsFixture,
                'name': 'test_rebuild_with_image_novalidhost',
                # We don't care about networking for this test. This requires
                # microversion >= 2.37.
                'networks': 'none'
            }
        }
        server = self.api.post_server(server_req_body)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Disable the host we're on so ComputeFilter would have ruled it out
        # normally
        self._disable_compute_for(server)

        # Now update the image metadata to be something that won't work with
        # the fake compute driver we're using since the fake driver has an
        # "x86_64" architecture.
        rebuild_image_ref = (
            nova.tests.unit.image.fake.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID)
        self.api.put_image_meta_key(
            rebuild_image_ref, 'hw_architecture', 'unicore32')
        # Now rebuild the server with that updated image and it should result
        # in a NoValidHost failure from the scheduler.
        rebuild_req_body = {
            'rebuild': {
                'imageRef': rebuild_image_ref
            }
        }
        # Since we're using the CastAsCall fixture, the NoValidHost error
        # should actually come back to the API and result in a 500 error.
        # Normally the user would get a 202 response because nova-api RPC casts
        # to nova-conductor which RPC calls the scheduler which raises the
        # NoValidHost. We can mimic the end user way to figure out the failure
        # by looking for the failed 'rebuild' instance action event.
        self.api.api_post('/servers/%s/action' % server['id'],
                          rebuild_req_body, check_response_status=[500])
        # Look for the failed rebuild action.
        self._wait_for_action_fail_completion(
            server, instance_actions.REBUILD, 'rebuild_server',
            # Before microversion 2.51 events are only returned for instance
            # actions if you're an admin.
            self.api_fixture.admin_api)
        # Assert the server image_ref was rolled back on failure.
        server = self.api.get_server(server['id'])
        self.assertEqual(original_image_ref, server['image']['id'])

        # The server should be in ERROR state
        self.assertEqual('ERROR', server['status'])
        self.assertIn('No valid host', server['fault']['message'])

        # Rebuild it again with the same bad image to make sure it's rejected
        # again. Since we're using CastAsCall here, there is no 202 from the
        # API, and the exception from conductor gets passed back through the
        # API.
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.api_post,
            '/servers/%s/action' % server['id'], rebuild_req_body)
        self.assertIn('NoValidHost', six.text_type(ex))

    # A rebuild to the same host should never attempt a rebuild claim.
    @mock.patch('nova.compute.resource_tracker.ResourceTracker.rebuild_claim',
                new_callable=mock.NonCallableMock)
    def test_rebuild_with_new_image(self, mock_rebuild_claim):
        """Rebuilds a server with a different image which will run it through
        the scheduler to validate the image is still OK with the compute host
        that the instance is running on.

        Validates that additional resources are not allocated against the
        instance.host in Placement due to the rebuild on same host.
        """
        admin_api = self.api_fixture.admin_api
        admin_api.microversion = '2.53'

        def _get_provider_uuid_by_host(host):
            resp = admin_api.api_get(
                'os-hypervisors?hypervisor_hostname_pattern=%s' % host).body
            return resp['hypervisors'][0]['id']

        def _get_provider_usages(provider_uuid):
            return self.placement_api.get(
                '/resource_providers/%s/usages' % provider_uuid).body['usages']

        def _get_allocations_by_server_uuid(server_uuid):
            return self.placement_api.get(
                '/allocations/%s' % server_uuid).body['allocations']

        def _set_provider_inventory(rp_uuid, resource_class, inventory):
            # Get the resource provider generation for the inventory update.
            rp = self.placement_api.get(
                '/resource_providers/%s' % rp_uuid).body
            inventory['resource_provider_generation'] = rp['generation']
            return self.placement_api.put(
                '/resource_providers/%s/inventories/%s' %
                (rp_uuid, resource_class), inventory).body

        def assertFlavorMatchesAllocation(flavor, allocation):
            self.assertEqual(flavor['vcpus'], allocation['VCPU'])
            self.assertEqual(flavor['ram'], allocation['MEMORY_MB'])
            self.assertEqual(flavor['disk'], allocation['DISK_GB'])

        nodename = self.compute.manager._get_nodename(None)
        rp_uuid = _get_provider_uuid_by_host(nodename)
        # make sure we start with no usage on the compute node
        rp_usages = _get_provider_usages(rp_uuid)
        self.assertEqual({'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0}, rp_usages)

        server_req_body = {
            'server': {
                # We hard-code from a fake image since we can't get images
                # via the compute /images proxy API with microversion > 2.35.
                'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'flavorRef': '1',   # m1.tiny from DefaultFlavorsFixture,
                'name': 'test_rebuild_with_new_image',
                # We don't care about networking for this test. This requires
                # microversion >= 2.37.
                'networks': 'none'
            }
        }
        server = self.api.post_server(server_req_body)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        flavor = self.api.api_get('/flavors/1').body['flavor']

        # make the compute node full and ensure rebuild still succeed
        _set_provider_inventory(rp_uuid, "VCPU", {"total": 1})

        # There should be usage for the server on the compute node now.
        rp_usages = _get_provider_usages(rp_uuid)
        assertFlavorMatchesAllocation(flavor, rp_usages)
        allocs = _get_allocations_by_server_uuid(server['id'])
        self.assertIn(rp_uuid, allocs)
        allocs = allocs[rp_uuid]['resources']
        assertFlavorMatchesAllocation(flavor, allocs)

        rebuild_image_ref = (
            nova.tests.unit.image.fake.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID)
        # Now rebuild the server with a different image.
        rebuild_req_body = {
            'rebuild': {
                'imageRef': rebuild_image_ref
            }
        }
        self.api.api_post('/servers/%s/action' % server['id'],
                          rebuild_req_body)
        self._wait_for_server_parameter(
            self.api, server, {'OS-EXT-STS:task_state': None})

        # The usage and allocations should not have changed.
        rp_usages = _get_provider_usages(rp_uuid)
        assertFlavorMatchesAllocation(flavor, rp_usages)

        allocs = _get_allocations_by_server_uuid(server['id'])
        self.assertIn(rp_uuid, allocs)
        allocs = allocs[rp_uuid]['resources']
        assertFlavorMatchesAllocation(flavor, allocs)

    def test_volume_backed_rebuild_different_image(self):
        """Tests that trying to rebuild a volume-backed instance with a
        different image than what is in the root disk of the root volume
        will result in a 400 BadRequest error.
        """
        self.useFixture(nova_fixtures.CinderFixtureNewAttachFlow(self))
        # First create our server as normal.
        server_req_body = {
            # There is no imageRef because this is boot from volume.
            'server': {
                'flavorRef': '1',  # m1.tiny from DefaultFlavorsFixture,
                'name': 'test_volume_backed_rebuild_different_image',
                # We don't care about networking for this test. This requires
                # microversion >= 2.37.
                'networks': 'none',
                'block_device_mapping_v2': [{
                    'boot_index': 0,
                    'uuid':
                    nova_fixtures.CinderFixtureNewAttachFlow.IMAGE_BACKED_VOL,
                    'source_type': 'volume',
                    'destination_type': 'volume'
                }]
            }
        }
        server = self.api.post_server(server_req_body)
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        # For a volume-backed server, the image ref will be an empty string
        # in the server response.
        self.assertEqual('', server['image'])

        # Now rebuild the server with a different image than was used to create
        # our fake volume.
        rebuild_image_ref = (
            nova.tests.unit.image.fake.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID)
        rebuild_req_body = {
            'rebuild': {
                'imageRef': rebuild_image_ref
            }
        }
        resp = self.api.api_post('/servers/%s/action' % server['id'],
                                 rebuild_req_body, check_response_status=[400])
        # Assert that we failed because of the image change and not something
        # else.
        self.assertIn('Unable to rebuild with a different image for a '
                      'volume-backed server', six.text_type(resp))


class ProviderTreeTests(integrated_helpers.ProviderUsageBaseTestCase):
    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(ProviderTreeTests, self).setUp()
        _p = mock.patch.object(fake.SmallFakeDriver, 'update_provider_tree')
        self.addCleanup(_p.stop)
        self.mock_upt = _p.start()

        # Before starting compute, placement has no providers registered
        self.assertEqual([], self._get_all_providers())

        self.compute = self._start_compute(host='host1')

        # The compute host should have been created in placement with empty
        # inventory and no traits
        rps = self._get_all_providers()
        self.assertEqual(1, len(rps))
        self.assertEqual(self.compute.host, rps[0]['name'])
        self.host_uuid = self._get_provider_uuid_by_host(self.compute.host)
        self.assertEqual({}, self._get_provider_inventory(self.host_uuid))
        self.assertEqual([], self._get_provider_traits(self.host_uuid))

    def _run_update_available_resource_and_assert_sync_error(self):
        """Invoke ResourceTracker.update_available_resource and assert that it
        results in ResourceProviderSyncFailed.

        _run_periodicals is a little too high up in the call stack to be useful
        for this, because ResourceTracker.update_available_resource_for_node
        swallows all exceptions.
        """
        ctx = context.get_admin_context()
        rt = self.compute._get_resource_tracker()
        self.assertRaises(
            exception.ResourceProviderSyncFailed,
            rt.update_available_resource, ctx, self.compute.host)

    def test_update_provider_tree_associated_info(self):
        """Inventory in some standard and custom resource classes.  Standard
        and custom traits.  Aggregates.  Custom resource class and trait get
        created; inventory, traits, and aggregates get set properly.
        """
        inv = {
            'VCPU': {
                'total': 10,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 2,
                'step_size': 1, 'allocation_ratio': 10.0,
            },
            'MEMORY_MB': {
                'total': 1048576,
                'reserved': 2048,
                'min_unit': 1024,
                'max_unit': 131072,
                'step_size': 1024,
                'allocation_ratio': 1.0,
            },
            'CUSTOM_BANDWIDTH': {
                'total': 1250000,
                'reserved': 10000,
                'min_unit': 5000,
                'max_unit': 250000,
                'step_size': 5000,
                'allocation_ratio': 8.0,
            },
        }
        traits = set(['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'CUSTOM_GOLD'])
        aggs = set([uuids.agg1, uuids.agg2])

        def update_provider_tree(prov_tree, nodename):
            prov_tree.update_inventory(self.compute.host, inv)
            prov_tree.update_traits(self.compute.host, traits)
            prov_tree.update_aggregates(self.compute.host, aggs)
        self.mock_upt.side_effect = update_provider_tree

        self.assertNotIn('CUSTOM_BANDWIDTH', self._get_all_resource_classes())
        self.assertNotIn('CUSTOM_GOLD', self._get_all_traits())

        self._run_periodics()

        self.assertIn('CUSTOM_BANDWIDTH', self._get_all_resource_classes())
        self.assertIn('CUSTOM_GOLD', self._get_all_traits())
        self.assertEqual(inv, self._get_provider_inventory(self.host_uuid))
        self.assertEqual(traits,
                         set(self._get_provider_traits(self.host_uuid)))
        self.assertEqual(aggs,
                         set(self._get_provider_aggregates(self.host_uuid)))

    def test_update_provider_tree_multiple_providers(self):
        """Make update_provider_tree create multiple providers, including an
        additional root as a sharing provider; and some descendants in the
        compute node's tree.
        """
        def update_provider_tree(prov_tree, nodename):
            # Create a shared storage provider as a root
            prov_tree.new_root('ssp', uuids.ssp)
            prov_tree.update_traits(
                'ssp', ['MISC_SHARES_VIA_AGGREGATE', 'STORAGE_DISK_SSD'])
            prov_tree.update_aggregates('ssp', [uuids.agg])
            # Compute node is in the same aggregate
            prov_tree.update_aggregates(self.compute.host, [uuids.agg])
            # Create two NUMA nodes as children
            prov_tree.new_child('numa1', self.host_uuid, uuid=uuids.numa1)
            prov_tree.new_child('numa2', self.host_uuid, uuid=uuids.numa2)
            # Give the NUMA nodes the proc/mem inventory.  NUMA 2 has twice as
            # much as NUMA 1 (so we can validate later that everything is where
            # it should be).
            for n in (1, 2):
                inv = {
                    'VCPU': {
                        'total': 10 * n,
                        'reserved': 0,
                        'min_unit': 1,
                        'max_unit': 2,
                        'step_size': 1,
                        'allocation_ratio': 10.0,
                    },
                    'MEMORY_MB': {
                         'total': 1048576 * n,
                         'reserved': 2048,
                         'min_unit': 1024,
                         'max_unit': 131072,
                         'step_size': 1024,
                         'allocation_ratio': 1.0,
                     },
                }
                prov_tree.update_inventory('numa%d' % n, inv)
            # Each NUMA node has two PFs providing VF inventory on one of two
            # networks
            for n in (1, 2):
                for p in (1, 2):
                    name = 'pf%d_%d' % (n, p)
                    prov_tree.new_child(
                        name, getattr(uuids, 'numa%d' % n),
                        uuid=getattr(uuids, name))
                    trait = 'CUSTOM_PHYSNET_%d' % ((n + p) % 2)
                    prov_tree.update_traits(name, [trait])
                    inv = {
                        'SRIOV_NET_VF': {
                            'total': n + p,
                            'reserved': 0,
                            'min_unit': 1,
                            'max_unit': 1,
                            'step_size': 1,
                            'allocation_ratio': 1.0,
                        },
                    }
                    prov_tree.update_inventory(name, inv)
        self.mock_upt.side_effect = update_provider_tree

        self._run_periodics()

        # Create a dict, keyed by provider UUID, of all the providers
        rps_by_uuid = {}
        for rp_dict in self._get_all_providers():
            rps_by_uuid[rp_dict['uuid']] = rp_dict

        # All and only the expected providers got created.
        all_uuids = set([self.host_uuid, uuids.ssp, uuids.numa1, uuids.numa2,
                         uuids.pf1_1, uuids.pf1_2, uuids.pf2_1, uuids.pf2_2])
        self.assertEqual(all_uuids, set(rps_by_uuid))

        # Validate tree roots
        tree_uuids = [self.host_uuid, uuids.numa1, uuids.numa2,
                      uuids.pf1_1, uuids.pf1_2, uuids.pf2_1, uuids.pf2_2]
        for tree_uuid in tree_uuids:
            self.assertEqual(self.host_uuid,
                             rps_by_uuid[tree_uuid]['root_provider_uuid'])
        self.assertEqual(uuids.ssp,
                         rps_by_uuid[uuids.ssp]['root_provider_uuid'])

        # SSP has the right traits
        self.assertEqual(
            set(['MISC_SHARES_VIA_AGGREGATE', 'STORAGE_DISK_SSD']),
            set(self._get_provider_traits(uuids.ssp)))

        # SSP and compute are in the same aggregate
        agg_uuids = set([self.host_uuid, uuids.ssp])
        for uuid in agg_uuids:
            self.assertEqual(set([uuids.agg]),
                             set(self._get_provider_aggregates(uuid)))

        # The rest aren't in aggregates
        for uuid in (all_uuids - agg_uuids):
            self.assertEqual(set(), set(self._get_provider_aggregates(uuid)))

        # NUMAs have the right inventory and parentage
        for n in (1, 2):
            numa_uuid = getattr(uuids, 'numa%d' % n)
            self.assertEqual(self.host_uuid,
                             rps_by_uuid[numa_uuid]['parent_provider_uuid'])
            inv = self._get_provider_inventory(numa_uuid)
            self.assertEqual(10 * n, inv['VCPU']['total'])
            self.assertEqual(1048576 * n, inv['MEMORY_MB']['total'])

        # PFs have the right inventory, physnet, and parentage
        self.assertEqual(uuids.numa1,
                         rps_by_uuid[uuids.pf1_1]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_0'],
                         self._get_provider_traits(uuids.pf1_1))
        self.assertEqual(
            2,
            self._get_provider_inventory(uuids.pf1_1)['SRIOV_NET_VF']['total'])

        self.assertEqual(uuids.numa1,
                         rps_by_uuid[uuids.pf1_2]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_1'],
                         self._get_provider_traits(uuids.pf1_2))
        self.assertEqual(
            3,
            self._get_provider_inventory(uuids.pf1_2)['SRIOV_NET_VF']['total'])

        self.assertEqual(uuids.numa2,
                         rps_by_uuid[uuids.pf2_1]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_1'],
                         self._get_provider_traits(uuids.pf2_1))
        self.assertEqual(
            3,
            self._get_provider_inventory(uuids.pf2_1)['SRIOV_NET_VF']['total'])

        self.assertEqual(uuids.numa2,
                         rps_by_uuid[uuids.pf2_2]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_0'],
                         self._get_provider_traits(uuids.pf2_2))
        self.assertEqual(
            4,
            self._get_provider_inventory(uuids.pf2_2)['SRIOV_NET_VF']['total'])

        # Compute and NUMAs don't have any traits
        for uuid in (self.host_uuid, uuids.numa1, uuids.numa2):
            self.assertEqual([], self._get_provider_traits(uuid))

    def test_update_provider_tree_bogus_resource_class(self):
        def update_provider_tree(prov_tree, nodename):
            prov_tree.update_inventory(self.compute.host, {'FOO': {}})
        self.mock_upt.side_effect = update_provider_tree

        rcs = self._get_all_resource_classes()
        self.assertIn('VCPU', rcs)
        self.assertNotIn('FOO', rcs)

        self._run_update_available_resource_and_assert_sync_error()

        rcs = self._get_all_resource_classes()
        self.assertIn('VCPU', rcs)
        self.assertNotIn('FOO', rcs)

    def test_update_provider_tree_bogus_trait(self):
        def update_provider_tree(prov_tree, nodename):
            prov_tree.update_traits(self.compute.host, ['FOO'])
        self.mock_upt.side_effect = update_provider_tree

        traits = self._get_all_traits()
        self.assertIn('HW_CPU_X86_AVX', traits)
        self.assertNotIn('FOO', traits)

        self._run_update_available_resource_and_assert_sync_error()

        traits = self._get_all_traits()
        self.assertIn('HW_CPU_X86_AVX', traits)
        self.assertNotIn('FOO', traits)


class ServerMovingTests(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests moving servers while checking the resource allocations and usages

    These tests use two compute hosts. Boot a server on one of them then try to
    move the server to the other. At every step resource allocation of the
    server and the resource usages of the computes are queried from placement
    API and asserted.
    """

    REQUIRES_LOCKING = True
    # NOTE(danms): The test defaults to using SmallFakeDriver,
    # which only has one vcpu, which can't take the doubled allocation
    # we're now giving it. So, use the bigger MediumFakeDriver here.
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(ServerMovingTests, self).setUp()
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        self.compute1 = self._start_compute(host='host1')
        self.compute2 = self._start_compute(host='host2')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]
        self.flavor2 = flavors[1]
        # create flavor3 which has less MEMORY_MB but more DISK_GB than flavor2
        flavor_body = {'flavor':
                           {'name': 'test_flavor3',
                            'ram': int(self.flavor2['ram'] / 2),
                            'vcpus': 1,
                            'disk': self.flavor2['disk'] * 2,
                            'id': 'a22d5517-147c-4147-a0d1-e698df5cd4e3'
                            }}

        self.flavor3 = self.api.post_flavor(flavor_body)

    def _other_hostname(self, host):
        other_host = {'host1': 'host2',
                      'host2': 'host1'}
        return other_host[host]

    def _run_periodics(self):
        # NOTE(jaypipes): We always run periodics in the same order: first on
        # compute1, then on compute2. However, we want to test scenarios when
        # the periodics run at different times during mover operations. This is
        # why we have the "reverse" tests which simply switch the source and
        # dest host while keeping the order in which we run the
        # periodics. This effectively allows us to test the matrix of timing
        # scenarios during move operations.
        ctx = context.get_admin_context()
        LOG.info('Running periodic for compute1 (%s)',
            self.compute1.manager.host)
        self.compute1.manager.update_available_resource(ctx)
        LOG.info('Running periodic for compute2 (%s)',
            self.compute2.manager.host)
        self.compute2.manager.update_available_resource(ctx)
        LOG.info('Finished with periodics')

    def _migrate_and_check_allocations(self, server, flavor, source_rp_uuid,
                                       dest_rp_uuid):
        request = {
            'migrate': None
        }
        self._move_and_check_allocations(
            server, request=request, old_flavor=flavor, new_flavor=flavor,
            source_rp_uuid=source_rp_uuid, dest_rp_uuid=dest_rp_uuid)

    def _move_and_check_allocations(self, server, request, old_flavor,
                                    new_flavor, source_rp_uuid, dest_rp_uuid):
        self.api.post_server_action(server['id'], request)
        self._wait_for_state_change(self.api, server, 'VERIFY_RESIZE')

        def _check_allocation():
            source_usages = self._get_provider_usages(source_rp_uuid)
            self.assertFlavorMatchesAllocation(old_flavor, source_usages)
            dest_usages = self._get_provider_usages(dest_rp_uuid)
            self.assertFlavorMatchesAllocation(new_flavor, dest_usages)

            # The instance should own the new_flavor allocation against the
            # destination host created by the scheduler
            allocations = self._get_allocations_by_server_uuid(server['id'])
            self.assertEqual(1, len(allocations))
            dest_alloc = allocations[dest_rp_uuid]['resources']
            self.assertFlavorMatchesAllocation(new_flavor, dest_alloc)

            # The migration should own the old_flavor allocation against the
            # source host created by conductor
            migration_uuid = self.get_migration_uuid_for_instance(server['id'])
            allocations = self._get_allocations_by_server_uuid(migration_uuid)
            source_alloc = allocations[source_rp_uuid]['resources']
            self.assertFlavorMatchesAllocation(old_flavor, source_alloc)

        # OK, so the move operation has run, but we have not yet confirmed or
        # reverted the move operation. Before we run periodics, make sure
        # that we have allocations/usages on BOTH the source and the
        # destination hosts.
        _check_allocation()
        self._run_periodics()
        _check_allocation()

        # Make sure the RequestSpec.flavor matches the new_flavor.
        ctxt = context.get_admin_context()
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        self.assertEqual(new_flavor['id'], reqspec.flavor.flavorid)

    def test_resize_revert(self):
        self._test_resize_revert(dest_hostname='host1')

    def test_resize_revert_reverse(self):
        self._test_resize_revert(dest_hostname='host2')

    def test_resize_confirm(self):
        self._test_resize_confirm(dest_hostname='host1')

    def test_resize_confirm_reverse(self):
        self._test_resize_confirm(dest_hostname='host2')

    def _resize_and_check_allocations(self, server, old_flavor, new_flavor,
            source_rp_uuid, dest_rp_uuid):
        self.flags(allow_resize_to_same_host=False)
        resize_req = {
            'resize': {
                'flavorRef': new_flavor['id']
            }
        }
        self._move_and_check_allocations(
            server, request=resize_req, old_flavor=old_flavor,
            new_flavor=new_flavor, source_rp_uuid=source_rp_uuid,
            dest_rp_uuid=dest_rp_uuid)

    def _test_resize_revert(self, dest_hostname):
        source_hostname = self._other_hostname(dest_hostname)
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(self.flavor1,
            source_hostname)

        self._resize_and_check_allocations(server, self.flavor1, self.flavor2,
            source_rp_uuid, dest_rp_uuid)

        # Revert the resize and check the usages
        post = {'revertResize': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Make sure the RequestSpec.flavor matches the original flavor.
        ctxt = context.get_admin_context()
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        self.assertEqual(self.flavor1['id'], reqspec.flavor.flavorid)

        self._run_periodics()

        # the original host expected to have the old resource allocation
        source_usages = self._get_provider_usages(source_rp_uuid)
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0}, dest_usages,
                          'Target host %s still has usage after the resize '
                          'has been reverted' % dest_hostname)

        # Check that the server only allocates resource from the original host
        self.assertEqual(1, len(allocations))

        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)

        self._delete_and_check_allocations(server)

    def _test_resize_confirm(self, dest_hostname):
        source_hostname = self._other_hostname(dest_hostname)
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(self.flavor1,
            source_hostname)

        self._resize_and_check_allocations(server, self.flavor1, self.flavor2,
            source_rp_uuid, dest_rp_uuid)

        # Confirm the resize and check the usages
        post = {'confirmResize': None}
        self.api.post_server_action(
            server['id'], post, check_response_status=[204])
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # After confirming, we should have an allocation only on the
        # destination host
        allocations = self._get_allocations_by_server_uuid(server['id'])

        # and the server allocates only from the target host
        self.assertEqual(1, len(allocations))

        source_usages = self._get_provider_usages(source_rp_uuid)
        dest_usages = self._get_provider_usages(dest_rp_uuid)

        # and the target host allocation should be according to the new flavor
        self.assertFlavorMatchesAllocation(self.flavor2, dest_usages)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0}, source_usages,
                         'The source host %s still has usages after the '
                         'resize has been confirmed' % source_hostname)

        # and the target host allocation should be according to the new flavor
        self.assertFlavorMatchesAllocation(self.flavor2, dest_usages)

        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor2, dest_allocation)

        self._run_periodics()

        # Check we're still accurate after running the periodics

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        source_usages = self._get_provider_usages(source_rp_uuid)

        # and the target host allocation should be according to the new flavor
        self.assertFlavorMatchesAllocation(self.flavor2, dest_usages)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0}, source_usages,
                          'The source host %s still has usages after the '
                          'resize has been confirmed' % source_hostname)

        allocations = self._get_allocations_by_server_uuid(server['id'])

        # and the server allocates only from the target host
        self.assertEqual(1, len(allocations))

        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor2, dest_allocation)

        self._delete_and_check_allocations(server)

    def _resize_to_same_host_and_check_allocations(self, server, old_flavor,
                                                   new_flavor, rp_uuid):
        # Resize the server to the same host and check usages in VERIFY_RESIZE
        # state
        self.flags(allow_resize_to_same_host=True)
        resize_req = {
            'resize': {
                'flavorRef': new_flavor['id']
            }
        }
        self.api.post_server_action(server['id'], resize_req)
        self._wait_for_state_change(self.api, server, 'VERIFY_RESIZE')

        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorsMatchAllocation(old_flavor, new_flavor, usages)

        # The instance should hold a new_flavor allocation
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(new_flavor, allocation)

        # The migration should hold an old_flavor allocation
        migration_uuid = self.get_migration_uuid_for_instance(server['id'])
        allocations = self._get_allocations_by_server_uuid(migration_uuid)
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(old_flavor, allocation)

        # We've resized to the same host and have doubled allocations for both
        # the old and new flavor on the same host. Run the periodic on the
        # compute to see if it tramples on what the scheduler did.
        self._run_periodics()

        usages = self._get_provider_usages(rp_uuid)

        # In terms of usage, it's still double on the host because the instance
        # and the migration each hold an allocation for the new and old
        # flavors respectively.
        self.assertFlavorsMatchAllocation(old_flavor, new_flavor, usages)

        # The instance should hold a new_flavor allocation
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(new_flavor, allocation)

        # The migration should hold an old_flavor allocation
        allocations = self._get_allocations_by_server_uuid(migration_uuid)
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(old_flavor, allocation)

    def test_resize_revert_same_host(self):
        # make sure that the test only uses a single host
        compute2_service_id = self.admin_api.get_services(
            host=self.compute2.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute2_service_id, {'status': 'disabled'})

        hostname = self.compute1.manager.host
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        server = self._boot_and_check_allocations(self.flavor2, hostname)

        self._resize_to_same_host_and_check_allocations(
            server, self.flavor2, self.flavor3, rp_uuid)

        # Revert the resize and check the usages
        post = {'revertResize': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        self._run_periodics()

        # after revert only allocations due to the old flavor should remain
        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor2, usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor2, allocation)

        self._delete_and_check_allocations(server)

    def test_resize_confirm_same_host(self):
        # make sure that the test only uses a single host
        compute2_service_id = self.admin_api.get_services(
            host=self.compute2.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute2_service_id, {'status': 'disabled'})

        hostname = self.compute1.manager.host
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        server = self._boot_and_check_allocations(self.flavor2, hostname)

        self._resize_to_same_host_and_check_allocations(
            server, self.flavor2, self.flavor3, rp_uuid)

        # Confirm the resize and check the usages
        post = {'confirmResize': None}
        self.api.post_server_action(
            server['id'], post, check_response_status=[204])
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        self._run_periodics()

        # after confirm only allocations due to the new flavor should remain
        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor3, usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor3, allocation)

        self._delete_and_check_allocations(server)

    def test_resize_not_enough_resource(self):
        # Try to resize to a flavor that requests more VCPU than what the
        # compute hosts has available and expect the resize to fail

        flavor_body = {'flavor':
                           {'name': 'test_too_big_flavor',
                            'ram': 1024,
                            'vcpus': fake.MediumFakeDriver.vcpus + 1,
                            'disk': 20,
                            }}

        big_flavor = self.api.post_flavor(flavor_body)

        dest_hostname = self.compute2.host
        source_hostname = self._other_hostname(dest_hostname)
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        self.flags(allow_resize_to_same_host=False)
        resize_req = {
            'resize': {
                'flavorRef': big_flavor['id']
            }
        }

        resp = self.api.post_server_action(
            server['id'], resize_req, check_response_status=[400])
        self.assertEqual(
            resp['badRequest']['message'],
            "No valid host was found. No valid host found for resize")
        server = self.admin_api.get_server(server['id'])
        self.assertEqual(source_hostname, server['OS-EXT-SRV-ATTR:host'])

        # only the source host shall have usages after the failed resize
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        # Check that the other provider has no usage
        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0}, dest_usages)

        # Check that the server only allocates resource from the host it is
        # booted on
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        self._delete_and_check_allocations(server)

    def _wait_for_notification_event_type(self, event_type, max_retries=50):
        retry_counter = 0
        while True:
            if len(fake_notifier.NOTIFICATIONS) > 0:
                for notification in fake_notifier.NOTIFICATIONS:
                    if notification.event_type == event_type:
                        return
            if retry_counter == max_retries:
                self.fail('Wait for notification event type (%s) failed'
                          % event_type)
            retry_counter += 1
            time.sleep(0.1)

    def test_evacuate_with_no_compute(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        # Disable compute service on destination host
        compute2_service_id = self.admin_api.get_services(
            host=dest_hostname, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute2_service_id, {'status': 'disabled'})

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        # Force source compute down
        source_compute_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']
        self.compute1.stop()
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # Initialize fake_notifier
        fake_notifier.stub_notifier(self)
        fake_notifier.reset()

        # Initiate evacuation
        post = {'evacuate': {}}
        self.api.post_server_action(server['id'], post)

        # NOTE(elod.illes): Should be changed to non-polling solution when
        # patch https://review.openstack.org/#/c/482629/ gets merged:
        # fake_notifier.wait_for_versioned_notifications(
        #     'compute_task.rebuild_server')
        self._wait_for_notification_event_type('compute_task.rebuild_server')

        self._run_periodics()

        # There is no other host to evacuate to so the rebuild should put the
        # VM to ERROR state, but it should remain on source compute
        expected_params = {'OS-EXT-SRV-ATTR:host': source_hostname,
                           'status': 'ERROR'}
        server = self._wait_for_server_parameter(self.api, server,
                                                 expected_params)

        # Check migrations
        migrations = self.api.get_migrations()
        self.assertEqual(1, len(migrations))
        self.assertEqual('evacuation', migrations[0]['migration_type'])
        self.assertEqual(server['id'], migrations[0]['instance_uuid'])
        self.assertEqual(source_hostname, migrations[0]['source_compute'])
        self.assertEqual('error', migrations[0]['status'])

        # Restart source host
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})
        self.compute1.start()

        self._run_periodics()

        # Check allocation and usages: should only use resources on source host
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)
        zero_usage = {'VCPU': 0, 'DISK_GB': 0, 'MEMORY_MB': 0}
        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertEqual(zero_usage, dest_usages)

        self._delete_and_check_allocations(server)

    def test_migrate_no_valid_host(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        dest_compute_id = self.admin_api.get_services(
            host=dest_hostname, binary='nova-compute')[0]['id']
        self.compute2.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            dest_compute_id, {'forced_down': 'true'})

        # migrate the server
        post = {'migrate': None}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               server['id'], post)
        self.assertIn('No valid host', six.text_type(ex))
        expected_params = {'OS-EXT-SRV-ATTR:host': source_hostname,
                           'status': 'ACTIVE'}
        self._wait_for_server_parameter(self.api, server, expected_params)

        self._run_periodics()

        # Expect to have allocation only on source_host
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)
        zero_usage = {'VCPU': 0, 'DISK_GB': 0, 'MEMORY_MB': 0}
        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertEqual(zero_usage, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        self._delete_and_check_allocations(server)

    def test_evacuate(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        source_compute_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']

        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # evacuate the server
        post = {'evacuate': {}}
        self.api.post_server_action(
            server['id'], post)
        expected_params = {'OS-EXT-SRV-ATTR:host': dest_hostname,
                           'status': 'ACTIVE'}
        server = self._wait_for_server_parameter(self.api, server,
                                                 expected_params)

        # Expect to have allocation and usages on both computes as the
        # source compute is still down
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(2, len(allocations))
        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)
        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        # restart the source compute
        self.restart_compute_service(self.compute1)

        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0},
                         source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        self._delete_and_check_allocations(server)

    def test_evacuate_forced_host(self):
        """Evacuating a server with a forced host bypasses the scheduler
        which means conductor has to create the allocations against the
        destination node. This test recreates the scenarios and asserts
        the allocations on the source and destination nodes are as expected.
        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        source_compute_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']

        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # evacuate the server and force the destination host which bypasses
        # the scheduler
        post = {
            'evacuate': {
                'host': dest_hostname,
                'force': True
            }
        }
        self.api.post_server_action(server['id'], post)
        expected_params = {'OS-EXT-SRV-ATTR:host': dest_hostname,
                           'status': 'ACTIVE'}
        server = self._wait_for_server_parameter(self.api, server,
                                                 expected_params)

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        # Expect to have allocation and usages on both computes as the
        # source compute is still down
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(2, len(allocations))
        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)
        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        # restart the source compute
        self.restart_compute_service(self.compute1)
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        # Run the periodics again to show they don't change anything.
        self._run_periodics()

        # When the source node starts up, the instance has moved so the
        # ResourceTracker should cleanup allocations for the source node.
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertEqual(
            {'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0}, source_usages)

        # The usages/allocations should still exist on the destination node
        # after the source node starts back up.
        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        self._delete_and_check_allocations(server)

    def test_evacuate_claim_on_dest_fails(self):
        """Tests that the allocations on the destination node are cleaned up
        when the rebuild move claim fails due to insufficient resources.
        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        source_compute_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']

        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # NOTE(mriedem): This isn't great, and I'd like to fake out the driver
        # to make the claim fail, by doing something like returning a too high
        # memory_mb overhead, but the limits dict passed to the claim is empty
        # so the claim test is considering it as unlimited and never actually
        # performs a claim test. Configuring the scheduler to use the RamFilter
        # to get the memory_mb limit at least seems like it should work but
        # it doesn't appear to for some reason...
        def fake_move_claim(*args, **kwargs):
            # Assert the destination node allocation exists.
            dest_usages = self._get_provider_usages(dest_rp_uuid)
            self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)
            raise exception.ComputeResourcesUnavailable(
                    reason='test_evacuate_claim_on_dest_fails')

        with mock.patch('nova.compute.claims.MoveClaim', fake_move_claim):
            # evacuate the server
            self.api.post_server_action(server['id'], {'evacuate': {}})
            # the migration will fail on the dest node and the instance will
            # go into error state
            server = self._wait_for_state_change(self.api, server, 'ERROR')

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        # The allocation should still exist on the source node since it's
        # still down, and the allocation on the destination node should be
        # cleaned up.
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(
            {'vcpus': 0, 'ram': 0, 'disk': 0}, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)

        # restart the source compute
        self.restart_compute_service(self.compute1)
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        # Run the periodics again to show they don't change anything.
        self._run_periodics()

        # The source compute shouldn't have cleaned up the allocation for
        # itself since the instance didn't move.
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)

    def test_evacuate_rebuild_on_dest_fails(self):
        """Tests that the allocations on the destination node are cleaned up
        automatically when the claim is made but the actual rebuild
        via the driver fails.

        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        source_compute_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']

        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        def fake_rebuild(*args, **kwargs):
            # Assert the destination node allocation exists.
            dest_usages = self._get_provider_usages(dest_rp_uuid)
            self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)
            raise test.TestingException('test_evacuate_rebuild_on_dest_fails')

        with mock.patch.object(
                self.compute2.driver, 'rebuild', fake_rebuild):
            # evacuate the server
            self.api.post_server_action(server['id'], {'evacuate': {}})
            # the migration will fail on the dest node and the instance will
            # go into error state
            server = self._wait_for_state_change(self.api, server, 'ERROR')

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        # The allocation should still exist on the source node since it's
        # still down, and the allocation on the destination node should be
        # cleaned up.
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(
            {'vcpus': 0, 'ram': 0, 'disk': 0}, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)

        # restart the source compute
        self.restart_compute_service(self.compute1)
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        # Run the periodics again to show they don't change anything.
        self._run_periodics()

        # The source compute shouldn't have cleaned up the allocation for
        # itself since the instance didn't move.
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)

    def _boot_then_shelve_and_check_allocations(self, hostname, rp_uuid):
        # avoid automatic shelve offloading
        self.flags(shelved_offload_time=-1)
        server = self._boot_and_check_allocations(
            self.flavor1, hostname)
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_state_change(self.api, server, 'SHELVED')
        # the host should maintain the existing allocation for this instance
        # while the instance is shelved
        source_usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)
        # Check that the server only allocates resource from the host it is
        # booted on
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)
        return server

    def test_shelve_unshelve(self):
        source_hostname = self.compute1.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        server = self._boot_then_shelve_and_check_allocations(
            source_hostname, source_rp_uuid)

        req = {
            'unshelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # the host should have resource usage as the instance is ACTIVE
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        # Check that the server only allocates resource from the host it is
        # booted on
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        self._delete_and_check_allocations(server)

    def _shelve_offload_and_check_allocations(self, server, source_rp_uuid):
        req = {
            'shelveOffload': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            self.api, server, {'status': 'SHELVED_OFFLOADED',
                               'OS-EXT-SRV-ATTR:host': None,
                               'OS-EXT-AZ:availability_zone': ''})
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0},
                         source_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(0, len(allocations))

    def test_shelve_offload_unshelve_diff_host(self):
        source_hostname = self.compute1.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        server = self._boot_then_shelve_and_check_allocations(
            source_hostname, source_rp_uuid)

        self._shelve_offload_and_check_allocations(server, source_rp_uuid)

        # unshelve after shelve offload will do scheduling. this test case
        # wants to test the scenario when the scheduler select a different host
        # to ushelve the instance. So we disable the original host.
        source_service_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']
        self.admin_api.put_service(source_service_id, {'status': 'disabled'})

        req = {
            'unshelve': {}
        }
        self.api.post_server_action(server['id'], req)
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        # unshelving an offloaded instance will call the scheduler so the
        # instance might end up on a different host
        current_hostname = server['OS-EXT-SRV-ATTR:host']
        self.assertEqual(current_hostname, self._other_hostname(
            source_hostname))

        # the host running the instance should have resource usage
        current_rp_uuid = self._get_provider_uuid_by_host(current_hostname)
        current_usages = self._get_provider_usages(current_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, current_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[current_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        self._delete_and_check_allocations(server)

    def test_shelve_offload_unshelve_same_host(self):
        source_hostname = self.compute1.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        server = self._boot_then_shelve_and_check_allocations(
            source_hostname, source_rp_uuid)

        self._shelve_offload_and_check_allocations(server, source_rp_uuid)

        # unshelve after shelve offload will do scheduling. this test case
        # wants to test the scenario when the scheduler select the same host
        # to ushelve the instance. So we disable the other host.
        source_service_id = self.admin_api.get_services(
            host=self._other_hostname(source_hostname),
            binary='nova-compute')[0]['id']
        self.admin_api.put_service(source_service_id, {'status': 'disabled'})

        req = {
            'unshelve': {}
        }
        self.api.post_server_action(server['id'], req)
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        # unshelving an offloaded instance will call the scheduler so the
        # instance might end up on a different host
        current_hostname = server['OS-EXT-SRV-ATTR:host']
        self.assertEqual(current_hostname, source_hostname)

        # the host running the instance should have resource usage
        current_rp_uuid = self._get_provider_uuid_by_host(current_hostname)
        current_usages = self._get_provider_usages(current_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, current_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[current_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        self._delete_and_check_allocations(server)

    def test_live_migrate_force(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)
        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
                'force': True,
            }
        }

        self.api.post_server_action(server['id'], post)
        self._wait_for_server_parameter(self.api, server,
            {'OS-EXT-SRV-ATTR:host': dest_hostname,
             'status': 'ACTIVE'})

        self._run_periodics()

        source_usages = self._get_provider_usages(source_rp_uuid)
        # NOTE(danms): There should be no usage for the source
        self.assertFlavorMatchesAllocation(
            {'ram': 0, 'disk': 0, 'vcpus': 0}, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        # the server has an allocation on only the dest node
        self.assertEqual(1, len(allocations))
        self.assertNotIn(source_rp_uuid, allocations)
        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        self._delete_and_check_allocations(server)

    def test_live_migrate(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)
        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
            }
        }

        self.api.post_server_action(server['id'], post)
        self._wait_for_server_parameter(self.api, server,
                                        {'OS-EXT-SRV-ATTR:host': dest_hostname,
                                         'status': 'ACTIVE'})

        self._run_periodics()

        source_usages = self._get_provider_usages(source_rp_uuid)
        # NOTE(danms): There should be no usage for the source
        self.assertFlavorMatchesAllocation(
            {'ram': 0, 'disk': 0, 'vcpus': 0}, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        self.assertNotIn(source_rp_uuid, allocations)
        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        self._delete_and_check_allocations(server)

    def test_live_migrate_pre_check_fails(self):
        """Tests the case that the LiveMigrationTask in conductor has
        called the scheduler which picked a host and created allocations
        against it in Placement, but then when the conductor task calls
        check_can_live_migrate_destination on the destination compute it
        fails. The allocations on the destination compute node should be
        cleaned up before the conductor task asks the scheduler for another
        host to try the live migration.
        """
        self.failed_hostname = None
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        def fake_check_can_live_migrate_destination(
                context, instance, src_compute_info, dst_compute_info,
                block_migration=False, disk_over_commit=False):
            self.failed_hostname = dst_compute_info['host']
            raise exception.MigrationPreCheckError(
                reason='test_live_migrate_pre_check_fails')

        with mock.patch('nova.virt.fake.FakeDriver.'
                        'check_can_live_migrate_destination',
                        side_effect=fake_check_can_live_migrate_destination):
            post = {
                'os-migrateLive': {
                    'host': dest_hostname,
                    'block_migration': True,
                }
            }
            self.api.post_server_action(server['id'], post)
            # As there are only two computes and we failed to live migrate to
            # the only other destination host, the LiveMigrationTask raises
            # MaxRetriesExceeded back to the conductor manager which handles it
            # generically and sets the instance back to ACTIVE status and
            # clears the task_state. The migration record status is set to
            # 'error', so that's what we need to look for to know when this
            # is done.
            migration = self._wait_for_migration_status(server, ['error'])

        # The source_compute should be set on the migration record, but the
        # destination shouldn't be as we never made it to one.
        self.assertEqual(source_hostname, migration['source_compute'])
        self.assertIsNone(migration['dest_compute'])
        # Make sure the destination host (the only other host) is the failed
        # host.
        self.assertEqual(dest_hostname, self.failed_hostname)

        source_usages = self._get_provider_usages(source_rp_uuid)
        # Since the instance didn't move, assert the allocations are still
        # on the source node.
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        # Assert the allocations, created by the scheduler, are cleaned up
        # after the migration pre-check error happens.
        self.assertFlavorMatchesAllocation(
            {'vcpus': 0, 'ram': 0, 'disk': 0}, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        # There should only be 1 allocation for the instance on the source node
        self.assertEqual(1, len(allocations))
        self.assertIn(source_rp_uuid, allocations)
        self.assertFlavorMatchesAllocation(
            self.flavor1, allocations[source_rp_uuid]['resources'])

        self._delete_and_check_allocations(server)

    @mock.patch('nova.virt.fake.FakeDriver.pre_live_migration')
    def test_live_migrate_rollback_cleans_dest_node_allocations(
            self, mock_pre_live_migration, force=False):
        """Tests the case that when live migration fails, either during the
        call to pre_live_migration on the destination, or during the actual
        live migration in the virt driver, the allocations on the destination
        node are rolled back since the instance is still on the source node.
        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        def stub_pre_live_migration(context, instance, block_device_info,
                                    network_info, disk_info, migrate_data):
            # Make sure the source node allocations are against the migration
            # record and the dest node allocations are against the instance.
            _allocations = self._get_allocations_by_server_uuid(
                migrate_data.migration.uuid)
            self.assertEqual(1, len(_allocations))
            self.assertIn(source_rp_uuid, _allocations)
            self.assertFlavorMatchesAllocation(
                self.flavor1, _allocations[source_rp_uuid]['resources'])

            _allocations = self._get_allocations_by_server_uuid(server['id'])
            self.assertEqual(1, len(_allocations))
            self.assertIn(dest_rp_uuid, _allocations)
            self.assertFlavorMatchesAllocation(
                self.flavor1, _allocations[dest_rp_uuid]['resources'])
            # The actual type of exception here doesn't matter. The point
            # is that the virt driver raised an exception from the
            # pre_live_migration method on the destination host.
            raise test.TestingException(
                'test_live_migrate_rollback_cleans_dest_node_allocations')

        mock_pre_live_migration.side_effect = stub_pre_live_migration

        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
                'force': force
            }
        }
        self.api.post_server_action(server['id'], post)
        # The compute manager will put the migration record into error status
        # when pre_live_migration fails, so wait for that to happen.
        migration = self._wait_for_migration_status(server, ['error'])
        # The _rollback_live_migration method in the compute manager will reset
        # the task_state on the instance, so wait for that to happen.
        server = self._wait_for_server_parameter(
            self.api, server, {'OS-EXT-STS:task_state': None})

        self.assertEqual(source_hostname, migration['source_compute'])
        self.assertEqual(dest_hostname, migration['dest_compute'])

        source_usages = self._get_provider_usages(source_rp_uuid)
        # Since the instance didn't move, assert the allocations are still
        # on the source node.
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        # Assert the allocations, created by the scheduler, are cleaned up
        # after the rollback happens.
        self.assertFlavorMatchesAllocation(
            {'vcpus': 0, 'ram': 0, 'disk': 0}, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        # There should only be 1 allocation for the instance on the source node
        self.assertEqual(1, len(allocations))
        self.assertIn(source_rp_uuid, allocations)
        self.assertFlavorMatchesAllocation(
            self.flavor1, allocations[source_rp_uuid]['resources'])

        self._delete_and_check_allocations(server)

    def test_live_migrate_rollback_cleans_dest_node_allocations_forced(self):
        """Tests the case that when a forced host live migration fails, either
        during the call to pre_live_migration on the destination, or during
        the actual live migration in the virt driver, the allocations on the
        destination node are rolled back since the instance is still on the
        source node.
        """
        self.test_live_migrate_rollback_cleans_dest_node_allocations(
            force=True)

    def test_rescheduling_when_migrating_instance(self):
        """Tests that allocations are removed from the destination node by
        the compute service when a cold migrate / resize fails and a reschedule
        request is sent back to conductor.
        """
        source_hostname = self.compute1.manager.host
        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        def fake_prep_resize(*args, **kwargs):
            dest_hostname = self._other_hostname(source_hostname)
            dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)
            dest_usages = self._get_provider_usages(dest_rp_uuid)
            self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)
            allocations = self._get_allocations_by_server_uuid(server['id'])
            self.assertIn(dest_rp_uuid, allocations)

            source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
            source_usages = self._get_provider_usages(source_rp_uuid)
            self.assertFlavorMatchesAllocation(self.flavor1, source_usages)
            migration_uuid = self.get_migration_uuid_for_instance(server['id'])
            allocations = self._get_allocations_by_server_uuid(migration_uuid)
            self.assertIn(source_rp_uuid, allocations)

            raise test.TestingException('Simulated _prep_resize failure.')

        # Yes this isn't great in a functional test, but it's simple.
        self.stub_out('nova.compute.manager.ComputeManager._prep_resize',
                      fake_prep_resize)

        # Now migrate the server which is going to fail on the destination.
        self.api.post_server_action(server['id'], {'migrate': None})

        self._wait_for_action_fail_completion(
            server, instance_actions.MIGRATE, 'compute_prep_resize')

        dest_hostname = self._other_hostname(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        failed_usages = self._get_provider_usages(dest_rp_uuid)
        # Expects no allocation records on the failed host.
        self.assertFlavorMatchesAllocation(
           {'vcpus': 0, 'ram': 0, 'disk': 0}, failed_usages)

        # Ensure the allocation records still exist on the source host.
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertIn(source_rp_uuid, allocations)

    def _test_resize_to_same_host_instance_fails(self, failing_method,
                                                 event_name):
        """Tests that when we resize to the same host and resize fails in
        the given method, we cleanup the allocations before rescheduling.
        """
        # make sure that the test only uses a single host
        compute2_service_id = self.admin_api.get_services(
            host=self.compute2.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute2_service_id, {'status': 'disabled'})

        hostname = self.compute1.manager.host
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        server = self._boot_and_check_allocations(self.flavor1, hostname)

        def fake_resize_method(*args, **kwargs):
            # Ensure the allocations are doubled now before we fail.
            usages = self._get_provider_usages(rp_uuid)
            self.assertFlavorsMatchAllocation(
                self.flavor1, self.flavor2, usages)
            raise test.TestingException('Simulated resize failure.')

        # Yes this isn't great in a functional test, but it's simple.
        self.stub_out(
            'nova.compute.manager.ComputeManager.%s' % failing_method,
            fake_resize_method)

        self.flags(allow_resize_to_same_host=True)
        resize_req = {
            'resize': {
                'flavorRef': self.flavor2['id']
            }
        }
        self.api.post_server_action(server['id'], resize_req)

        self._wait_for_action_fail_completion(
            server, instance_actions.RESIZE, event_name)

        # Ensure the allocation records still exist on the host.
        source_rp_uuid = self._get_provider_uuid_by_host(hostname)
        source_usages = self._get_provider_usages(source_rp_uuid)
        # The new_flavor should have been subtracted from the doubled
        # allocation which just leaves us with the original flavor.
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

    def test_resize_to_same_host_prep_resize_fails(self):
        self._test_resize_to_same_host_instance_fails(
            '_prep_resize', 'compute_prep_resize')

    def test_resize_instance_fails_allocation_cleanup(self):
        self._test_resize_to_same_host_instance_fails(
            '_resize_instance', 'compute_resize_instance')

    def test_finish_resize_fails_allocation_cleanup(self):
        self._test_resize_to_same_host_instance_fails(
            '_finish_resize', 'compute_finish_resize')

    def _test_resize_reschedule_uses_host_lists(self, fails, num_alts=None):
        """Test that when a resize attempt fails, the retry comes from the
        supplied host_list, and does not call the scheduler.
        """
        server_req = self._build_minimal_create_server_request(
                self.api, "some-server", flavor_id=self.flavor1["id"],
                image_uuid="155d900f-4e14-4e4c-a73d-069cbf4541e6",
                networks='none')

        created_server = self.api.post_server({"server": server_req})
        server = self._wait_for_state_change(self.api, created_server,
                "ACTIVE")
        inst_host = server["OS-EXT-SRV-ATTR:host"]
        uuid_orig = self._get_provider_uuid_by_host(inst_host)

        # We will need four new compute nodes to test the resize, representing
        # the host selected by select_destinations(), along with 3 alternates.
        self._start_compute(host="selection")
        self._start_compute(host="alt_host1")
        self._start_compute(host="alt_host2")
        self._start_compute(host="alt_host3")
        uuid_sel = self._get_provider_uuid_by_host("selection")
        uuid_alt1 = self._get_provider_uuid_by_host("alt_host1")
        uuid_alt2 = self._get_provider_uuid_by_host("alt_host2")
        uuid_alt3 = self._get_provider_uuid_by_host("alt_host3")
        hosts = [{"name": "selection", "uuid": uuid_sel},
                 {"name": "alt_host1", "uuid": uuid_alt1},
                 {"name": "alt_host2", "uuid": uuid_alt2},
                 {"name": "alt_host3", "uuid": uuid_alt3},
                ]

        self.flags(weight_classes=[__name__ + '.AltHostWeigher'],
                   group='filter_scheduler')
        self.scheduler_service.stop()
        self.scheduler_service = self.start_service('scheduler')

        def fake_prep_resize(*args, **kwargs):
            if self.num_fails < fails:
                self.num_fails += 1
                raise Exception("fake_prep_resize")
            actual_prep_resize(*args, **kwargs)

        # Yes this isn't great in a functional test, but it's simple.
        actual_prep_resize = compute_manager.ComputeManager._prep_resize
        self.stub_out("nova.compute.manager.ComputeManager._prep_resize",
                      fake_prep_resize)
        self.num_fails = 0
        num_alts = 4 if num_alts is None else num_alts
        # Make sure we have enough retries available for the number of
        # requested fails.
        attempts = min(fails + 2, num_alts)
        self.flags(max_attempts=attempts, group='scheduler')
        server_uuid = server["id"]
        data = {"resize": {"flavorRef": self.flavor2["id"]}}
        self.api.post_server_action(server_uuid, data)

        if num_alts < fails:
            # We will run out of alternates before populate_retry will
            # raise a MaxRetriesExceeded exception, so the migration will
            # fail and the server should be in status "ERROR"
            server = self._wait_for_state_change(self.api, created_server,
                    "ERROR")
            source_usages = self._get_provider_usages(uuid_orig)
            # The usage should be unchanged from the original flavor
            self.assertFlavorMatchesAllocation(self.flavor1, source_usages)
            # There should be no usages on any of the hosts
            target_uuids = (uuid_sel, uuid_alt1, uuid_alt2, uuid_alt3)
            empty_usage = {"VCPU": 0, "MEMORY_MB": 0, "DISK_GB": 0}
            for target_uuid in target_uuids:
                usage = self._get_provider_usages(target_uuid)
                self.assertEqual(empty_usage, usage)
        else:
            server = self._wait_for_state_change(self.api, created_server,
                    "VERIFY_RESIZE")
            # Verify that the selected host failed, and was rescheduled to
            # an alternate host.
            new_server_host = server.get("OS-EXT-SRV-ATTR:host")
            expected_host = hosts[fails]["name"]
            self.assertEqual(expected_host, new_server_host)
            uuid_dest = hosts[fails]["uuid"]
            source_usages = self._get_provider_usages(uuid_orig)
            dest_usages = self._get_provider_usages(uuid_dest)
            # The usage should match the resized flavor
            self.assertFlavorMatchesAllocation(self.flavor2, dest_usages)
            # Verify that the other host have no allocations
            target_uuids = (uuid_sel, uuid_alt1, uuid_alt2, uuid_alt3)
            empty_usage = {"VCPU": 0, "MEMORY_MB": 0, "DISK_GB": 0}
            for target_uuid in target_uuids:
                if target_uuid == uuid_dest:
                    continue
                usage = self._get_provider_usages(target_uuid)
                self.assertEqual(empty_usage, usage)

            # Verify that there is only one migration record for the instance.
            ctxt = context.get_admin_context()
            filters = {"instance_uuid": server["id"]}
            migrations = objects.MigrationList.get_by_filters(ctxt, filters)
            self.assertEqual(1, len(migrations.objects))

    def test_resize_reschedule_uses_host_lists_1_fail(self):
        self._test_resize_reschedule_uses_host_lists(fails=1)

    def test_resize_reschedule_uses_host_lists_3_fails(self):
        self._test_resize_reschedule_uses_host_lists(fails=3)

    def test_resize_reschedule_uses_host_lists_not_enough_alts(self):
        self._test_resize_reschedule_uses_host_lists(fails=3, num_alts=1)

    def test_migrate_confirm(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        self._migrate_and_check_allocations(
            server, self.flavor1, source_rp_uuid, dest_rp_uuid)

        # Confirm the move and check the usages
        post = {'confirmResize': None}
        self.api.post_server_action(
            server['id'], post, check_response_status=[204])
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        def _check_allocation():
            allocations = self._get_allocations_by_server_uuid(server['id'])

            # and the server allocates only from the target host
            self.assertEqual(1, len(allocations))

            source_usages = self._get_provider_usages(source_rp_uuid)
            dest_usages = self._get_provider_usages(dest_rp_uuid)

            # and the target host allocation should be according to the flavor
            self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)
            self.assertEqual({'VCPU': 0,
                              'MEMORY_MB': 0,
                              'DISK_GB': 0}, source_usages,
                             'The source host %s still has usages after the '
                             'resize has been confirmed' % source_hostname)

            # and the target host allocation should be according to the flavor
            self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

            dest_allocation = allocations[dest_rp_uuid]['resources']
            self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        # After confirming, we should have an allocation only on the
        # destination host
        _check_allocation()
        self._run_periodics()

        # Check we're still accurate after running the periodics
        _check_allocation()

        self._delete_and_check_allocations(server)

    def test_migrate_revert(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        self._migrate_and_check_allocations(
            server, self.flavor1, source_rp_uuid, dest_rp_uuid)

        # Revert the move and check the usages
        post = {'revertResize': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        def _check_allocation():
            source_usages = self._get_provider_usages(source_rp_uuid)
            allocations = self._get_allocations_by_server_uuid(server['id'])
            self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

            dest_usages = self._get_provider_usages(dest_rp_uuid)
            self.assertEqual({'VCPU': 0,
                              'MEMORY_MB': 0,
                              'DISK_GB': 0}, dest_usages,
                              'Target host %s still has usage after the '
                              'resize has been reverted' % dest_hostname)

            # Check that the server only allocates resource from the original
            # host
            self.assertEqual(1, len(allocations))

            source_allocation = allocations[source_rp_uuid]['resources']
            self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)

        # the original host expected to have the old resource allocation
        _check_allocation()
        self._run_periodics()
        _check_allocation()

        self._delete_and_check_allocations(server)


class ServerLiveMigrateForceAndAbort(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Test Server live migrations, which delete the migration or
    force_complete it, and check the allocations after the operations.

    The test are using fakedriver to handle the force_completion and deletion
    of live migration.
    """

    compute_driver = 'fake.FakeLiveMigrateDriver'

    def setUp(self):
        super(ServerLiveMigrateForceAndAbort, self).setUp()

        self.compute1 = self._start_compute(host='host1')
        self.compute2 = self._start_compute(host='host2')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def test_live_migrate_force_complete(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
            }
        }
        self.api.post_server_action(server['id'], post)

        migration = self._wait_for_migration_status(server, ['running'])
        self.api.force_complete_migration(server['id'],
                                          migration['id'])

        self._wait_for_server_parameter(self.api, server,
                                        {'OS-EXT-SRV-ATTR:host': dest_hostname,
                                         'status': 'ACTIVE'})

        self._run_periodics()

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(
            {'ram': 0, 'disk': 0, 'vcpus': 0}, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        self.assertNotIn(source_rp_uuid, allocations)

        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        self._delete_and_check_allocations(server)

    def test_live_migrate_delete(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
            }
        }
        self.api.post_server_action(server['id'], post)

        migration = self._wait_for_migration_status(server, ['running'])

        self.api.delete_migration(server['id'], migration['id'])
        self._wait_for_server_parameter(self.api, server,
            {'OS-EXT-SRV-ATTR:host': source_hostname,
             'status': 'ACTIVE'})

        self._run_periodics()

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        self.assertNotIn(dest_rp_uuid, allocations)

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(
           {'ram': 0, 'disk': 0, 'vcpus': 0}, dest_usages)

        self._delete_and_check_allocations(server)


class ServerRescheduleTests(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests server create scenarios which trigger a reschedule during
    a server build and validates that allocations in Placement
    are properly cleaned up.

    Uses a fake virt driver that fails the build on the first attempt.
    """

    compute_driver = 'fake.FakeRescheduleDriver'

    def setUp(self):
        super(ServerRescheduleTests, self).setUp()
        self.compute1 = self._start_compute(host='host1')
        self.compute2 = self._start_compute(host='host2')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def _other_hostname(self, host):
        other_host = {'host1': 'host2',
                      'host2': 'host1'}
        return other_host[host]

    def test_rescheduling_when_booting_instance(self):
        """Tests that allocations, created by the scheduler, are cleaned
        from the source node when the build fails on that node and is
        rescheduled to another node.
        """
        server_req = self._build_minimal_create_server_request(
                self.api, 'some-server', flavor_id=self.flavor1['id'],
                image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                networks='none')

        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(
                self.api, created_server, 'ACTIVE')
        dest_hostname = server['OS-EXT-SRV-ATTR:host']
        failed_hostname = self._other_hostname(dest_hostname)

        LOG.info('failed on %s', failed_hostname)
        LOG.info('booting on %s', dest_hostname)

        failed_rp_uuid = self._get_provider_uuid_by_host(failed_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        failed_usages = self._get_provider_usages(failed_rp_uuid)
        # Expects no allocation records on the failed host.
        self.assertFlavorMatchesAllocation(
           {'vcpus': 0, 'ram': 0, 'disk': 0}, failed_usages)

        # Ensure the allocation records on the destination host.
        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)


class ServerBuildAbortTests(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests server create scenarios which trigger a build abort during
    a server build and validates that allocations in Placement
    are properly cleaned up.

    Uses a fake virt driver that aborts the build on the first attempt.
    """

    compute_driver = 'fake.FakeBuildAbortDriver'

    def setUp(self):
        super(ServerBuildAbortTests, self).setUp()
        # We only need one compute service/host/node for these tests.
        self.compute1 = self._start_compute(host='host1')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def test_abort_when_booting_instance(self):
        """Tests that allocations, created by the scheduler, are cleaned
        from the source node when the build is aborted on that node.
        """
        server_req = self._build_minimal_create_server_request(
                self.api, 'some-server', flavor_id=self.flavor1['id'],
                image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                networks='none')

        created_server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(self.api, created_server, 'ERROR')

        failed_hostname = self.compute1.manager.host

        failed_rp_uuid = self._get_provider_uuid_by_host(failed_hostname)
        failed_usages = self._get_provider_usages(failed_rp_uuid)
        # Expects no allocation records on the failed host.
        self.assertFlavorMatchesAllocation(
           {'vcpus': 0, 'ram': 0, 'disk': 0}, failed_usages)


class ServerUnshelveSpawnFailTests(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Tests server unshelve scenarios which trigger a
    VirtualInterfaceCreateException during driver.spawn() and validates that
    allocations in Placement are properly cleaned up.
    """

    compute_driver = 'fake.FakeUnshelveSpawnFailDriver'

    def setUp(self):
        super(ServerUnshelveSpawnFailTests, self).setUp()
        # We only need one compute service/host/node for these tests.
        self.compute1 = self._start_compute('host1')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def test_driver_spawn_fail_when_unshelving_instance(self):
        """Tests that allocations, created by the scheduler, are cleaned
        from the target node when the unshelve driver.spawn fails on that node.
        """
        hostname = self.compute1.manager.host
        rp_uuid = self._get_provider_uuid_by_host(hostname)
        usages = self._get_provider_usages(rp_uuid)
        # We start with no usages on the host.
        self.assertFlavorMatchesAllocation(
           {'vcpus': 0, 'ram': 0, 'disk': 0}, usages)

        server_req = self._build_minimal_create_server_request(
            self.api, 'unshelve-spawn-fail', flavor_id=self.flavor1['id'],
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')

        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # assert allocations exist for the host
        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, usages)

        # shelve offload the server
        self.flags(shelved_offload_time=0)
        self.api.post_server_action(server['id'], {'shelve': None})
        self._wait_for_server_parameter(
            self.api, server, {'status': 'SHELVED_OFFLOADED',
                               'OS-EXT-SRV-ATTR:host': None})

        # assert allocations were removed from the host
        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(
           {'vcpus': 0, 'ram': 0, 'disk': 0}, usages)

        # unshelve the server, which should fail
        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_action_fail_completion(
            server, instance_actions.UNSHELVE, 'compute_unshelve_instance')

        # assert allocations were removed from the host
        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(
           {'vcpus': 0, 'ram': 0, 'disk': 0}, usages)


class ServerSoftDeleteTests(integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(ServerSoftDeleteTests, self).setUp()
        # We only need one compute service/host/node for these tests.
        self.compute1 = self._start_compute('host1')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def _soft_delete_and_check_allocation(self, server, hostname):
        self.api.delete_server(server['id'])
        server = self._wait_for_state_change(self.api, server, 'SOFT_DELETED')

        self._run_periodics()

        # in soft delete state nova should keep the resource allocation as
        # the instance can be restored
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        # run the periodic reclaim but as time isn't advanced it should not
        # reclaim the instance
        ctxt = context.get_admin_context()
        self.compute1._reclaim_queued_deletes(ctxt)

        self._run_periodics()

        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

    def test_soft_delete_then_reclaim(self):
        """Asserts that the automatic reclaim of soft deleted instance cleans
        up the allocations in placement.
        """

        # make sure that instance will go to SOFT_DELETED state instead of
        # deleted immediately
        self.flags(reclaim_instance_interval=30)

        hostname = self.compute1.host
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        server = self._boot_and_check_allocations(self.flavor1, hostname)

        self._soft_delete_and_check_allocation(server, hostname)

        # advance the time and run periodic reclaim, instance should be deleted
        # and resources should be freed
        the_past = timeutils.utcnow() + datetime.timedelta(hours=1)
        timeutils.set_time_override(override_time=the_past)
        self.addCleanup(timeutils.clear_time_override)
        ctxt = context.get_admin_context()
        self.compute1._reclaim_queued_deletes(ctxt)

        # Wait for real deletion
        self._wait_until_deleted(server)

        usages = self._get_provider_usages(rp_uuid)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0}, usages)
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(0, len(allocations))

    def test_soft_delete_then_restore(self):
        """Asserts that restoring a soft deleted instance keeps the proper
        allocation in placement.
        """

        # make sure that instance will go to SOFT_DELETED state instead of
        # deleted immediately
        self.flags(reclaim_instance_interval=30)

        hostname = self.compute1.host
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, hostname)

        self._soft_delete_and_check_allocation(server, hostname)

        post = {'restore': {}}
        self.api.post_server_action(server['id'], post)
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')

        # after restore the allocations should be kept
        usages = self._get_provider_usages(rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations))
        allocation = allocations[rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, allocation)

        # Now we want a real delete
        self.flags(reclaim_instance_interval=0)
        self._delete_and_check_allocations(server)


class VolumeBackedServerTest(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests for volume-backed servers."""

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(VolumeBackedServerTest, self).setUp()
        self.compute1 = self._start_compute('host1')
        self.flavor_id = self._create_flavor()

    def _create_flavor(self):
        body = {
            'flavor': {
                'id': 'vbst',
                'name': 'special',
                'ram': 512,
                'vcpus': 1,
                'disk': 10,
                'OS-FLV-EXT-DATA:ephemeral': 20,
                'swap': 5 * 1024,
                'rxtx_factor': 1.0,
                'os-flavor-access:is_public': True,
            },
        }
        self.admin_api.post_flavor(body)
        return body['flavor']['id']

    def _create_server(self):
        with nova.utils.temporary_mutation(self.api, microversion='2.35'):
            image_id = self.api.get_images()[0]['id']
        server_req = self._build_minimal_create_server_request(
            self.api, 'trait-based-server',
            image_uuid=image_id,
            flavor_id=self.flavor_id, networks='none')
        server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        return server

    def _create_volume_backed_server(self):
        self.useFixture(nova_fixtures.CinderFixtureNewAttachFlow(self))
        volume_id = nova_fixtures.CinderFixtureNewAttachFlow.IMAGE_BACKED_VOL
        server_req_body = {
            # There is no imageRef because this is boot from volume.
            'server': {
                'flavorRef': self.flavor_id,
                'name': 'test_volume_backed',
                # We don't care about networking for this test. This
                # requires microversion >= 2.37.
                'networks': 'none',
                'block_device_mapping_v2': [{
                    'boot_index': 0,
                    'uuid': volume_id,
                    'source_type': 'volume',
                    'destination_type': 'volume'
                }]
            }
        }
        server = self.api.post_server(server_req_body)
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        return server

    def test_ephemeral_has_disk_allocation(self):
        server = self._create_server()
        allocs = self._get_allocations_by_server_uuid(server['id'])
        resources = list(allocs.values())[0]['resources']
        self.assertIn('MEMORY_MB', resources)
        # 10gb root, 20gb ephemeral, 5gb swap
        expected_usage = 35
        self.assertEqual(expected_usage, resources['DISK_GB'])
        # Ensure the compute node is reporting the correct disk usage
        self.assertEqual(
            expected_usage,
            self.admin_api.get_hypervisor_stats()['local_gb_used'])

    def test_volume_backed_no_disk_allocation(self):
        server = self._create_volume_backed_server()
        allocs = self._get_allocations_by_server_uuid(server['id'])
        resources = list(allocs.values())[0]['resources']
        self.assertIn('MEMORY_MB', resources)
        # 0gb root, 20gb ephemeral, 5gb swap
        expected_usage = 25
        self.assertEqual(expected_usage, resources['DISK_GB'])
        # Ensure the compute node is reporting the correct disk usage
        self.assertEqual(
            expected_usage,
            self.admin_api.get_hypervisor_stats()['local_gb_used'])

        # Now let's hack the RequestSpec.is_bfv field to mimic migrating an
        # old instance created before RequestSpec.is_bfv was set in the API,
        # move the instance and verify that the RequestSpec.is_bfv is set
        # and the instance still reports the same DISK_GB allocations as during
        # the initial create.
        ctxt = context.get_admin_context()
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        # Make sure it's set.
        self.assertTrue(reqspec.is_bfv)
        del reqspec.is_bfv
        reqspec.save()
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        # Make sure it's not set.
        self.assertNotIn('is_bfv', reqspec)
        # Now migrate the instance to another host and check the request spec
        # and allocations after the migration.
        self._start_compute('host2')
        self.admin_api.post_server_action(server['id'], {'migrate': None})
        # Wait for the server to complete the cold migration.
        server = self._wait_for_state_change(
            self.admin_api, server, 'VERIFY_RESIZE')
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])
        # Confirm the cold migration and check usage and the request spec.
        self.api.post_server_action(server['id'], {'confirmResize': None})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        # Make sure it's set.
        self.assertTrue(reqspec.is_bfv)
        allocs = self._get_allocations_by_server_uuid(server['id'])
        resources = list(allocs.values())[0]['resources']
        self.assertEqual(expected_usage, resources['DISK_GB'])

        # Now shelve and unshelve the server to make sure root_gb DISK_GB
        # isn't reported for allocations after we unshelve the server.
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)
        self.api.post_server_action(server['id'], {'shelve': None})
        self._wait_for_state_change(self.api, server, 'SHELVED_OFFLOADED')
        fake_notifier.wait_for_versioned_notifications('shelve_offload.end')
        # The server should not have any allocations since it's not currently
        # hosted on any compute service.
        allocs = self._get_allocations_by_server_uuid(server['id'])
        self.assertDictEqual({}, allocs)
        # Now unshelve the server and make sure there are still no DISK_GB
        # allocations for the root disk.
        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        allocs = self._get_allocations_by_server_uuid(server['id'])
        resources = list(allocs.values())[0]['resources']
        self.assertEqual(expected_usage, resources['DISK_GB'])


class TraitsBasedSchedulingTest(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests for requesting a server with required traits in Placement"""

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(TraitsBasedSchedulingTest, self).setUp()
        self.compute1 = self._start_compute('host1')
        self.compute2 = self._start_compute('host2')
        # Using a standard trait from the os-traits library, set a required
        # trait extra spec on the flavor.
        flavors = self.api.get_flavors()
        self.flavor_with_trait = flavors[0]
        self.admin_api.post_extra_spec(
            self.flavor_with_trait['id'],
            {'extra_specs': {'trait:HW_CPU_X86_VMX': 'required'}})
        self.flavor_without_trait = flavors[1]
        self.flavor_with_forbidden_trait = flavors[2]
        self.admin_api.post_extra_spec(
            self.flavor_with_forbidden_trait['id'],
            {'extra_specs': {'trait:HW_CPU_X86_SGX': 'forbidden'}})

        # Note that we're using v2.35 explicitly as the api returns 404
        # starting with 2.36
        with nova.utils.temporary_mutation(self.api, microversion='2.35'):
            images = self.api.get_images()
            self.image_id_with_trait = images[0]['id']
            self.api.api_put('/images/%s/metadata' % self.image_id_with_trait,
                             {'metadata': {
                                 'trait:HW_CPU_X86_SGX': 'required'}})
            self.image_id_without_trait = images[1]['id']

    def _create_server_with_traits(self, flavor_id, image_id):
        """Create a server with given flavor and image id's
        :param flavor_id: the flavor id
        :param image_id: the image id
        :return: create server response
        """

        server_req = self._build_minimal_create_server_request(
            self.api, 'trait-based-server',
            image_uuid=image_id,
            flavor_id=flavor_id, networks='none')
        return self.api.post_server({'server': server_req})

    def _create_volume_backed_server_with_traits(self, flavor_id, volume_id):
        """Create a server with block device mapping(volume) with the given
        flavor and volume id's. Either the flavor or the image backing the
        volume is expected to have the traits
        :param flavor_id: the flavor id
        :param volume_id: the volume id
        :return: create server response
        """

        server_req_body = {
            # There is no imageRef because this is boot from volume.
            'server': {
                'flavorRef': flavor_id,
                'name': 'test_image_trait_on_volume_backed',
                # We don't care about networking for this test. This
                # requires microversion >= 2.37.
                'networks': 'none',
                'block_device_mapping_v2': [{
                    'boot_index': 0,
                    'uuid': volume_id,
                    'source_type': 'volume',
                    'destination_type': 'volume'
                }]
            }
        }
        server = self.api.post_server(server_req_body)
        return server

    def test_flavor_traits_based_scheduling(self):
        """Tests that a server create request using a required trait on flavor
        ends up on the single compute node resource provider that also has that
        trait in Placement.
        """

        # Decorate compute1 resource provider with that same trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute1.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX'])

        # Create server using only flavor trait
        server = self._create_server_with_traits(self.flavor_with_trait['id'],
                                                 self.image_id_without_trait)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute1.host, server['OS-EXT-SRV-ATTR:host'])

    def test_image_traits_based_scheduling(self):
        """Tests that a server create request using a required trait on image
        ends up on the single compute node resource provider that also has that
        trait in Placement.
        """

        # Decorate compute2 resource provider with image trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_SGX'])

        # Create server using only image trait
        server = self._create_server_with_traits(
            self.flavor_without_trait['id'], self.image_id_with_trait)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute2.host, server['OS-EXT-SRV-ATTR:host'])

    def test_flavor_image_traits_based_scheduling(self):
        """Tests that a server create request using a required trait on flavor
        AND a required trait on the image ends up on the single compute node
        resource provider that also has that trait in Placement.
        """

        # Decorate compute2 resource provider with both flavor and image trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX',
                                            'HW_CPU_X86_SGX'])

        # Create server using flavor and image trait
        server = self._create_server_with_traits(
            self.flavor_with_trait['id'], self.image_id_with_trait)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute2.host, server['OS-EXT-SRV-ATTR:host'])

    def test_image_trait_on_volume_backed_instance(self):
        """Tests that when trying to launch a volume-backed instance with a
        required trait on the image metadata contained within the volume,
        the instance ends up on the single compute node resource provider
        that also has that trait in Placement.
        """
        # Decorate compute2 resource provider with volume image metadata trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_SGX'])

        self.useFixture(nova_fixtures.CinderFixtureNewAttachFlow(self))
        # Create our server with a volume containing the image meta data with a
        # required trait
        server = self._create_volume_backed_server_with_traits(
            self.flavor_without_trait['id'],
            nova_fixtures.CinderFixtureNewAttachFlow.
            IMAGE_WITH_TRAITS_BACKED_VOL)

        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute2.host, server['OS-EXT-SRV-ATTR:host'])

    def test_flavor_image_trait_on_volume_backed_instance(self):
        """Tests that when trying to launch a volume-backed instance with a
        required trait on flavor AND a required trait on the image metadata
        contained within the volume, the instance ends up on the single
        compute node resource provider that also has those traits in Placement.
        """
        # Decorate compute2 resource provider with volume image metadata trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX',
                                            'HW_CPU_X86_SGX'])

        self.useFixture(nova_fixtures.CinderFixtureNewAttachFlow(self))
        # Create our server with a flavor trait and a volume containing the
        # image meta data with a required trait
        server = self._create_volume_backed_server_with_traits(
            self.flavor_with_trait['id'],
            nova_fixtures.CinderFixtureNewAttachFlow.
            IMAGE_WITH_TRAITS_BACKED_VOL)

        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute2.host, server['OS-EXT-SRV-ATTR:host'])

    def test_flavor_traits_based_scheduling_no_valid_host(self):
        """Tests that a server create request using a required trait expressed
         in flavor fails to find a valid host since no compute node resource
         providers have the trait.
        """

        # Decorate compute1 resource provider with the image trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute1.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_SGX'])

        server = self._create_server_with_traits(self.flavor_with_trait['id'],
                                                 self.image_id_without_trait)
        # The server should go to ERROR state because there is no valid host.
        server = self._wait_for_state_change(self.admin_api, server, 'ERROR')
        self.assertIsNone(server['OS-EXT-SRV-ATTR:host'])
        # Make sure the failure was due to NoValidHost by checking the fault.
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

    def test_image_traits_based_scheduling_no_valid_host(self):
        """Tests that a server create request using a required trait expressed
         in image fails to find a valid host since no compute node resource
         providers have the trait.
        """

        # Decorate compute1 resource provider with that flavor trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute1.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX'])

        server = self._create_server_with_traits(
            self.flavor_without_trait['id'], self.image_id_with_trait)
        # The server should go to ERROR state because there is no valid host.
        server = self._wait_for_state_change(self.admin_api, server, 'ERROR')
        self.assertIsNone(server['OS-EXT-SRV-ATTR:host'])
        # Make sure the failure was due to NoValidHost by checking the fault.
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

    def test_flavor_image_traits_based_scheduling_no_valid_host(self):
        """Tests that a server create request using a required trait expressed
         in flavor AND a required trait expressed in the image fails to find a
         valid host since no compute node resource providers have the trait.
        """

        server = self._create_server_with_traits(
            self.flavor_with_trait['id'], self.image_id_with_trait)
        # The server should go to ERROR state because there is no valid host.
        server = self._wait_for_state_change(self.admin_api, server, 'ERROR')
        self.assertIsNone(server['OS-EXT-SRV-ATTR:host'])
        # Make sure the failure was due to NoValidHost by checking the fault.
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

    def test_image_trait_on_volume_backed_instance_no_valid_host(self):
        """Tests that when trying to launch a volume-backed instance with a
        required trait on the image metadata contained within the volume
        fails to find a valid host since no compute node resource providers
        have the trait.
        """
        self.useFixture(nova_fixtures.CinderFixtureNewAttachFlow(self))
        # Create our server with a volume
        server = self._create_volume_backed_server_with_traits(
            self.flavor_without_trait['id'],
            nova_fixtures.CinderFixtureNewAttachFlow.
            IMAGE_WITH_TRAITS_BACKED_VOL)

        # The server should go to ERROR state because there is no valid host.
        server = self._wait_for_state_change(self.admin_api, server, 'ERROR')
        self.assertIsNone(server['OS-EXT-SRV-ATTR:host'])
        # Make sure the failure was due to NoValidHost by checking the fault.
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

    def test_rebuild_instance_with_image_traits(self):
        """Rebuilds a server with a different image which has traits
        associated with it and which will run it through the scheduler to
        validate the image is still OK with the compute host that the
        instance is running on.
         """
        # Decorate compute2 resource provider with both flavor and image trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX',
                                            'HW_CPU_X86_SGX'])
        # make sure we start with no usage on the compute node
        rp_usages = self._get_provider_usages(rp_uuid)
        self.assertEqual({'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0}, rp_usages)

        # create a server without traits on image and with traits on flavour
        server = self._create_server_with_traits(
            self.flavor_with_trait['id'], self.image_id_without_trait)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

        # make the compute node full and ensure rebuild still succeed
        inv = {"resource_class": "VCPU",
               "total": 1}
        self._set_inventory(rp_uuid, inv)

        # Now rebuild the server with a different image with traits
        rebuild_req_body = {
            'rebuild': {
                'imageRef': self.image_id_with_trait
            }
        }
        self.api.api_post('/servers/%s/action' % server['id'],
                          rebuild_req_body)
        self._wait_for_server_parameter(
            self.api, server, {'OS-EXT-STS:task_state': None})

        allocs = self._get_allocations_by_server_uuid(server['id'])
        self.assertIn(rp_uuid, allocs)

        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute2.host, server['OS-EXT-SRV-ATTR:host'])

    def test_rebuild_instance_with_image_traits_no_host(self):
        """Rebuilding a server with a different image which has required
        traits on the image fails to valid the host that this server is
        currently running, cause the compute host resource provider is not
        associated with similar trait.
        """
        # Decorate compute2 resource provider with traits on flavor
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX'])

        # make sure we start with no usage on the compute node
        rp_usages = self._get_provider_usages(rp_uuid)
        self.assertEqual({'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0}, rp_usages)

        # create a server without traits on image and with traits on flavour
        server = self._create_server_with_traits(
            self.flavor_with_trait['id'], self.image_id_without_trait)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

        # Now rebuild the server with a different image with traits
        rebuild_req_body = {
            'rebuild': {
                'imageRef': self.image_id_with_trait
            }
        }

        self.api.api_post('/servers/%s/action' % server['id'],
                          rebuild_req_body)
        # Look for the failed rebuild action.
        self._wait_for_action_fail_completion(
            server, instance_actions.REBUILD, 'rebuild_server', self.admin_api)
        # Assert the server image_ref was rolled back on failure.
        server = self.api.get_server(server['id'])
        self.assertEqual(self.image_id_without_trait, server['image']['id'])

        # The server should be in ERROR state
        self.assertEqual('ERROR', server['status'])
        self.assertEqual("No valid host was found. Image traits cannot be "
                         "satisfied by the current resource providers. "
                         "Either specify a different image during rebuild "
                         "or create a new server with the specified image.",
                         server['fault']['message'])

    def test_rebuild_instance_with_image_traits_no_image_change(self):
        """Rebuilds a server with a same image which has traits
        associated with it and which will run it through the scheduler to
        validate the image is still OK with the compute host that the
        instance is running on.
         """
        # Decorate compute2 resource provider with both flavor and image trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX',
                                            'HW_CPU_X86_SGX'])
        # make sure we start with no usage on the compute node
        rp_usages = self._get_provider_usages(rp_uuid)
        self.assertEqual({'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0},
                         rp_usages)

        # create a server with traits in both image and flavour
        server = self._create_server_with_traits(
            self.flavor_with_trait['id'], self.image_id_with_trait)
        server = self._wait_for_state_change(self.admin_api, server,
                                             'ACTIVE')

        # Now rebuild the server with a different image with traits
        rebuild_req_body = {
            'rebuild': {
                'imageRef': self.image_id_with_trait
            }
        }
        self.api.api_post('/servers/%s/action' % server['id'],
                          rebuild_req_body)
        self._wait_for_server_parameter(
            self.api, server, {'OS-EXT-STS:task_state': None})

        allocs = self._get_allocations_by_server_uuid(server['id'])
        self.assertIn(rp_uuid, allocs)

        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute2.host,
                         server['OS-EXT-SRV-ATTR:host'])

    def test_rebuild_instance_with_image_traits_and_forbidden_flavor_traits(
                                                                        self):
        """Rebuilding a server with a different image which has required
        traits on the image fails to validate image traits because flavor
        associated with the current instance has the similar trait that is
        forbidden
        """
        # Decorate compute2 resource provider with traits on flavor
        rp_uuid = self._get_provider_uuid_by_host(self.compute2.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX'])

        # make sure we start with no usage on the compute node
        rp_usages = self._get_provider_usages(rp_uuid)
        self.assertEqual({'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0}, rp_usages)

        # create a server with forbidden traits on flavor and no triats on
        # image
        server = self._create_server_with_traits(
            self.flavor_with_forbidden_trait['id'],
            self.image_id_without_trait)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

        # Now rebuild the server with a different image with traits
        rebuild_req_body = {
            'rebuild': {
                'imageRef': self.image_id_with_trait
            }
        }

        self.api.api_post('/servers/%s/action' % server['id'],
                          rebuild_req_body)
        # Look for the failed rebuild action.
        self._wait_for_action_fail_completion(
            server, instance_actions.REBUILD, 'rebuild_server', self.admin_api)
        # Assert the server image_ref was rolled back on failure.
        server = self.api.get_server(server['id'])
        self.assertEqual(self.image_id_without_trait, server['image']['id'])

        # The server should be in ERROR state
        self.assertEqual('ERROR', server['status'])
        self.assertEqual("No valid host was found. Image traits are part of "
                         "forbidden traits in flavor associated with the "
                         "server. Either specify a different image during "
                         "rebuild or create a new server with the specified "
                         "image and a compatible flavor.",
                         server['fault']['message'])


class ServerTestV256Common(ServersTestBase):
    api_major_version = 'v2.1'
    microversion = '2.56'
    ADMIN_API = True

    def _setup_compute_service(self):
        # Set up 3 compute services in the same cell
        for host in ('host1', 'host2', 'host3'):
            fake.set_nodes([host])
            self.addCleanup(fake.restore_nodes)
            self.start_service('compute', host=host)

    def _create_server(self, target_host=None):
        server = self._build_minimal_create_server_request(
            image_uuid='a2459075-d96c-40d5-893e-577ff92e721c')
        server.update({'networks': 'auto'})
        if target_host is not None:
            server['availability_zone'] = 'nova:%s' % target_host
        post = {'server': server}
        response = self.api.api_post('/servers', post).body
        return response['server']

    @staticmethod
    def _get_target_and_other_hosts(host):
        target_other_hosts = {'host1': ['host2', 'host3'],
                              'host2': ['host3', 'host1'],
                              'host3': ['host1', 'host2']}
        return target_other_hosts[host]


class ServerTestV256MultiCellTestCase(ServerTestV256Common):
    """Negative test to ensure we fail with ComputeHostNotFound if we try to
    target a host in another cell from where the instance lives.
    """
    NUMBER_OF_CELLS = 2

    def _setup_compute_service(self):
        # Set up 2 compute services in different cells
        host_to_cell_mappings = {
            'host1': 'cell1',
            'host2': 'cell2'}
        for host in sorted(host_to_cell_mappings):
            fake.set_nodes([host])
            self.addCleanup(fake.restore_nodes)
            self.start_service('compute', host=host,
                               cell=host_to_cell_mappings[host])

    def test_migrate_server_to_host_in_different_cell(self):
        # We target host1 specifically so that we have a predictable target for
        # the cold migration in cell2.
        server = self._create_server(target_host='host1')
        server = self._wait_for_state_change(server, 'BUILD')

        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               server['id'],
                               {'migrate': {'host': 'host2'}})
        # When the API pulls the instance out of cell1, the context is targeted
        # to cell1, so when the compute API resize() method attempts to lookup
        # the target host in cell1, it will result in a ComputeHostNotFound
        # error.
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Compute host host2 could not be found',
                      six.text_type(ex))


class ServerTestV256SingleCellMultiHostTestCase(ServerTestV256Common):
    """Happy path test where we create a server on one host, migrate it to
    another host of our choosing and ensure it lands there.
    """
    def test_migrate_server_to_host_in_same_cell(self):
        server = self._create_server()
        server = self._wait_for_state_change(server, 'BUILD')
        source_host = server['OS-EXT-SRV-ATTR:host']
        target_host = self._get_target_and_other_hosts(source_host)[0]
        self.api.post_server_action(server['id'],
                                    {'migrate': {'host': target_host}})
        # Assert the server is now on the target host.
        server = self.api.get_server(server['id'])
        self.assertEqual(target_host, server['OS-EXT-SRV-ATTR:host'])


class ServerTestV256RescheduleTestCase(ServerTestV256Common):

    @mock.patch.object(compute_manager.ComputeManager, '_prep_resize',
                       side_effect=exception.MigrationError(
                           reason='Test Exception'))
    def test_migrate_server_not_reschedule(self, mock_prep_resize):
        server = self._create_server()
        found_server = self._wait_for_state_change(server, 'BUILD')

        target_host, other_host = self._get_target_and_other_hosts(
            found_server['OS-EXT-SRV-ATTR:host'])

        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server_action,
                          server['id'],
                          {'migrate': {'host': target_host}})
        self.assertEqual(1, mock_prep_resize.call_count)
        found_server = self.api.get_server(server['id'])
        # Check that rescheduling is not occurred.
        self.assertNotEqual(other_host, found_server['OS-EXT-SRV-ATTR:host'])
