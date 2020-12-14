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
import collections
import copy
import datetime
import time
import zlib

from keystoneauth1 import adapter
import mock
from neutronclient.common import exceptions as neutron_exception
import os_resource_classes as orc
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_utils import fixture as osloutils_fixture
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
import six

from nova.compute import api as compute_api
from nova.compute import instance_actions
from nova.compute import manager as compute_manager
from nova import context
from nova import exception
from nova.network import constants
from nova.network import neutron as neutronapi
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.policies import base as base_policies
from nova.policies import servers as servers_policies
from nova.scheduler import utils
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_notifier
from nova.tests.unit import fake_requests
from nova.tests.unit.objects import test_instance_info_cache
from nova import utils as nova_utils
from nova.virt import fake
from nova import volume

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class ServersTest(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2'

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

    def test_create_server_with_error(self):
        # Create a server which will enter error state.

        def throw_error(*args, **kwargs):
            raise exception.BuildAbortException(reason='',
                    instance_uuid='fake')

        self.stub_out('nova.virt.fake.FakeDriver.spawn', throw_error)

        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'ERROR')

        # Delete the server
        self._delete_server(created_server)

        # We should have no (persisted) build failures until we update
        # resources, after which we should have one
        self.assertEqual([0], list(self._get_node_build_failures().values()))

        # BuildAbortException will not trigger a reschedule and the build
        # failure update is the last step in the compute manager after
        # instance state setting, fault recording and notification sending. So
        # we have no other way than simply wait to ensure the node build
        # failure counter updated before we assert it.
        def failed_counter_updated():
            self._run_periodics()
            self.assertEqual(
                [1], list(self._get_node_build_failures().values()))

        self._wait_for_assert(failed_counter_updated)

    def test_create_server_with_image_type_filter(self):
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')

        raw_image = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        vhd_image = 'a440c04b-79fa-479c-bed1-0b816eaec379'

        server = self._build_server(image_uuid=vhd_image)
        server = self.api.post_server({'server': server})
        server = self.api.get_server(server['id'])
        errored_server = self._wait_for_state_change(server, 'ERROR')
        self.assertIn('No valid host', errored_server['fault']['message'])

        server = self._build_server(image_uuid=raw_image)
        server = self.api.post_server({'server': server})
        server = self.api.get_server(server['id'])
        created_server = self._wait_for_state_change(server, 'ACTIVE')

        # Delete the server
        self._delete_server(created_server)

    def _test_create_server_with_error_with_retries(self):
        # Create a server which will enter error state.

        self._start_compute('host2')

        fails = []

        def throw_error(*args, **kwargs):
            fails.append('one')
            raise test.TestingException('Please retry me')

        self.stub_out('nova.virt.fake.FakeDriver.spawn', throw_error)

        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'ERROR')

        # Delete the server
        self._delete_server(created_server)

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

        # The build failure update is the last step in build_and_run_instance
        # in the compute manager after instance state setting, fault
        # recording and notification sending. So we have no other way than
        # simply wait to ensure the node build failure counter updated
        # before we assert it.
        def failed_counter_updated():
            self._run_periodics()
            self.assertEqual(
                [0, 1], list(sorted(self._get_node_build_failures().values())))

        self._wait_for_assert(failed_counter_updated)

    def test_create_and_delete_server(self):
        # Creates and deletes a server.

        # Create server
        # Build the server data gradually, checking errors along the way
        server = {}
        good_server = self._build_server()

        post = {'server': server}

        # Without an imageRef, this throws 500.
        # TODO(justinsb): Check whatever the spec says should be thrown here
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server, post)

        # With an invalid imageRef, this throws 500.
        server['imageRef'] = uuids.fake
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

        found_server = self._wait_for_state_change(found_server, 'ACTIVE')

        servers = self.api.get_servers(detail=True)
        for server in servers:
            self.assertIn("image", server)
            self.assertIn("flavor", server)

        # Delete the server
        self._delete_server(found_server)

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
        server = self._build_server()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

        # Cannot restore unless instance is deleted
        self.assertRaises(client.OpenStackApiException,
                          self.api.post_server_action, created_server_id,
                          {'restore': {}})

        # Delete the server
        self.api.delete_server(created_server_id)

        # Wait for queued deletion
        found_server = self._wait_for_state_change(found_server,
                                                   'SOFT_DELETED')

        self._force_reclaim()

        # Wait for real deletion
        self._wait_until_deleted(found_server)

    def test_deferred_delete_restore(self):
        # Creates, deletes and restores a server.
        self.flags(reclaim_instance_interval=3600)

        # Create server
        server = self._build_server()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

        # Delete the server
        self.api.delete_server(created_server_id)

        # Wait for queued deletion
        found_server = self._wait_for_state_change(found_server,
                                                   'SOFT_DELETED')

        # Restore server
        self.api.post_server_action(created_server_id, {'restore': {}})

        # Wait for server to become active again
        found_server = self._wait_for_state_change(found_server, 'ACTIVE')

    def test_deferred_delete_restore_overquota(self):
        # Test that a restore that would put the user over quota fails
        self.flags(instances=1, group='quota')
        # Creates, deletes and restores a server.
        self.flags(reclaim_instance_interval=3600)

        # Create server
        server = self._build_server()

        created_server1 = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server1)
        self.assertTrue(created_server1['id'])
        created_server_id1 = created_server1['id']

        # Wait for it to finish being created
        found_server1 = self._wait_for_state_change(created_server1, 'ACTIVE')

        # Delete the server
        self.api.delete_server(created_server_id1)

        # Wait for queued deletion
        found_server1 = self._wait_for_state_change(found_server1,
                                                    'SOFT_DELETED')

        # Create a second server
        self._create_server()

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
        server = self._build_server()

        created_server = self.api.post_server({'server': server})
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

        # Delete the server
        self.api.delete_server(created_server_id)

        # Wait for queued deletion
        found_server = self._wait_for_state_change(found_server,
                                                   'SOFT_DELETED')

        # Force delete server
        self.api.post_server_action(created_server_id, {'forceDelete': {}})

        # Wait for real deletion
        self._wait_until_deleted(found_server)

    def test_create_server_with_metadata(self):
        # Creates a server with metadata.

        # Build the server data gradually, checking errors along the way
        server = self._build_server()

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
        self._delete_server(found_server)

    def test_server_metadata_actions_negative_invalid_state(self):
        # Create server with metadata
        server = self._build_server()

        metadata = {'key_1': 'value_1'}

        server['metadata'] = metadata

        post = {'server': server}
        created_server = self.api.post_server(post)

        found_server = self._wait_for_state_change(created_server, 'ACTIVE')
        self.assertEqual(metadata, found_server.get('metadata'))
        server_id = found_server['id']

        # Change status from ACTIVE to SHELVED for negative test
        self.flags(shelved_offload_time = -1)
        self.api.post_server_action(server_id, {'shelve': {}})
        found_server = self._wait_for_state_change(found_server, 'SHELVED')

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
        self._delete_server(found_server)

    def test_create_and_rebuild_server(self):
        # Rebuild a server with metadata.

        # create a server with initially has no metadata
        server = self._build_server()
        server_post = {'server': server}

        metadata = {}
        for i in range(30):
            metadata['key_%s' % i] = 'value_%s' % i

        server_post['server']['metadata'] = metadata

        created_server = self.api.post_server(server_post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        created_server = self._wait_for_state_change(created_server, 'ACTIVE')

        # rebuild the server with metadata and other server attributes
        post = {}
        post['rebuild'] = {
            'imageRef': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
            'name': 'blah',
            'accessIPv4': '172.19.0.2',
            'accessIPv6': 'fe80::2',
            'metadata': {'some': 'thing'},
        }
        post['rebuild'].update({
            'accessIPv4': '172.19.0.2',
            'accessIPv6': 'fe80::2',
        })

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s", created_server)
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
            'imageRef': "76fa36fc-c930-4bf3-8c8a-ea2a2420deb6",
            "metadata": {},
        }

        self.api.post_server_action(created_server_id, post)
        LOG.debug("rebuilt server: %s", created_server)
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
        self._delete_server(found_server)

    def test_rename_server(self):
        # Test building and renaming a server.

        # Create a server
        server = self._build_server()
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
        self._delete_server(created_server)

    def test_create_multiple_servers(self):
        # Creates multiple servers and checks for reservation_id.

        # Create 2 servers, setting 'return_reservation_id, which should
        # return a reservation_id
        server = self._build_server()
        server['min_count'] = 2
        server['return_reservation_id'] = True
        post = {'server': server}
        response = self.api.post_server(post)
        self.assertIn('reservation_id', response)
        reservation_id = response['reservation_id']
        self.assertNotIn(reservation_id, ['', None])
        # Assert that the reservation_id itself has the expected format
        self.assertRegex(reservation_id, 'r-[0-9a-zA-Z]{8}')

        # Create 1 more server, which should not return a reservation_id
        server = self._build_server()
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
        self._delete_server(created_server)
        for server in server_map.values():
            self._delete_server(server)

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
        server = self._build_server()
        server['personality'] = personality

        post = {'server': server}

        created_server = self.api.post_server(post)
        LOG.debug("created_server: %s", created_server)
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Check it's there
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'ACTIVE')

        # Cleanup
        self._delete_server(found_server)

    def test_stop_start_servers_negative_invalid_state(self):
        # Create server
        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

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
        found_server = self._wait_for_state_change(found_server, 'SHUTOFF')

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
        self._delete_server(found_server)

    def test_revert_resized_server_negative_invalid_state(self):
        # Create server
        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

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
        self._delete_server(found_server)

    def test_resize_server_negative_invalid_state(self):
        # Avoid migration
        self.flags(allow_resize_to_same_host=True)

        # Create server
        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

        # Resize server(flavorRef: 1 -> 2)
        post = {'resize': {"flavorRef": "2", "OS-DCF:diskConfig": "AUTO"}}
        self.api.post_server_action(created_server_id, post)
        found_server = self._wait_for_state_change(found_server,
                                                   'VERIFY_RESIZE')

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
        self._delete_server(found_server)

    def test_confirm_resized_server_negative_invalid_state(self):
        # Create server
        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']
        found_server = self._wait_for_state_change(created_server, 'ACTIVE')

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
        self._delete_server(found_server)

    def test_resize_server_overquota(self):
        self.flags(cores=1, group='quota')
        self.flags(ram=512, group='quota')
        # Create server with default flavor, 1 core, 512 ram
        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        created_server_id = created_server['id']

        self._wait_for_state_change(created_server, 'ACTIVE')

        # Try to resize to flavorid 2, 1 core, 2048 ram
        post = {'resize': {'flavorRef': '2'}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               created_server_id, post)
        self.assertEqual(403, ex.response.status_code)

    def test_attach_vol_maximum_disk_devices_exceeded(self):
        server = self._build_server()
        created_server = self.api.post_server({"server": server})
        server_id = created_server['id']
        self._wait_for_state_change(created_server, 'ACTIVE')

        volume_id = '9a695496-44aa-4404-b2cc-ccab2501f87e'
        LOG.info('Attaching volume %s to server %s', volume_id, server_id)

        # The fake driver doesn't implement get_device_name_for_instance, so
        # we'll just raise the exception directly here, instead of simuluating
        # an instance with 26 disk devices already attached.
        with mock.patch.object(self.compute.driver,
                               'get_device_name_for_instance') as mock_get:
            mock_get.side_effect = exception.TooManyDiskDevices(maximum=26)
            ex = self.assertRaises(
                client.OpenStackApiException, self.api.post_server_volume,
                server_id, dict(volumeAttachment=dict(volumeId=volume_id)))
            expected = ('The maximum allowed number of disk devices (26) to '
                        'attach to a single instance has been exceeded.')
            self.assertEqual(403, ex.response.status_code)
            self.assertIn(expected, six.text_type(ex))


class ServersTestV21(ServersTest):
    api_major_version = 'v2.1'


class ServersTestV219(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'

    def _create_server(self, set_desc = True, desc = None):
        server = self._build_server()
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
            'name': new_name,
            'imageRef': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
            'accessIPv4': '172.19.0.2',
            'accessIPv6': 'fe80::2',
            'metadata': {'some': 'thing'},
        }
        post['rebuild'].update({
            'accessIPv4': '172.19.0.2',
            'accessIPv6': 'fe80::2',
        })
        if set_desc:
            post['rebuild']['description'] = desc
        self.api.api_post('/servers/%s/action' % server_id, post)

    def _create_server_and_verify(self, set_desc = True, expected_desc = None):
        # Creates a server with a description and verifies it is
        # in the GET responses.
        created_server = self._create_server(set_desc, expected_desc)[1]
        self._verify_server_description(created_server['id'], expected_desc)
        self._delete_server(created_server)

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
        server = self._create_server(True, 'test desc 1')[1]
        server_id = server['id']

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
        self._delete_server(server)

    def test_rebuild_server_with_description(self):
        self.api.microversion = '2.19'

        # Create a server with an initial description
        server = self._create_server(True, 'test desc 1')[1]
        server_id = server['id']
        self._wait_for_state_change(server, 'ACTIVE')

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
        self._delete_server(server)

    def test_version_compatibility(self):
        # Create a server with microversion v2.19 and a description.
        self.api.microversion = '2.19'
        server = self._create_server(True, 'test desc 1')[1]
        server_id = server['id']
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
        self._delete_server(server)

        # Create a server on V2.18 and verify that the description
        # defaults to the name on a V2.19 GET
        server_req, server = self._create_server(False)
        server_id = server['id']
        self.api.microversion = '2.19'
        self._verify_server_description(server_id, server_req['name'])

        # Cleanup
        self._delete_server(server)

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


class ServerTestV220(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'

    def setUp(self):
        super(ServerTestV220, self).setUp()
        self.api.microversion = '2.20'
        self.ctxt = context.get_admin_context()

    def _create_server(self):
        server = self._build_server()
        post = {'server': server}
        response = self.api.api_post('/servers', post).body
        return (server, response['server'])

    def _shelve_server(self):
        server = self._create_server()[1]
        server_id = server['id']
        self._wait_for_state_change(server, 'ACTIVE')
        self.api.post_server_action(server_id, {'shelve': None})
        return self._wait_for_state_change(server, 'SHELVED_OFFLOADED')

    def _get_fake_bdms(self, ctxt):
        return block_device_obj.block_device_make_list(self.ctxt,
                    [fake_block_device.FakeDbBlockDeviceDict(
                    {'device_name': '/dev/vda',
                     'source_type': 'volume',
                     'destination_type': 'volume',
                     'volume_id': '5d721593-f033-4f6d-ab6f-b5b067e61bc4'})])

    def test_attach_detach_vol_to_shelved_offloaded_server_new_flow(self):
        self.flags(shelved_offload_time=0)
        found_server = self._shelve_server()
        server_id = found_server['id']
        fake_bdms = self._get_fake_bdms(self.ctxt)

        # Test attach volume
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        with test.nested(mock.patch.object(compute_api.API,
                            '_check_volume_already_attached_to_instance'),
                         mock.patch.object(volume.cinder.API,
                                        'check_availability_zone'),
                         mock.patch.object(volume.cinder.API,
                                        'attachment_create'),
                         mock.patch.object(volume.cinder.API,
                                        'attachment_complete')
                         ) as (mock_check_vol_attached,
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

        self._delete_server(found_server)


class ServerTestV269(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'
    NUMBER_OF_CELLS = 3

    def setUp(self):
        super(ServerTestV269, self).setUp()
        self.api.microversion = '2.69'

        self.ctxt = context.get_admin_context()
        self.project_id = self.api.project_id
        self.cells = objects.CellMappingList.get_all(self.ctxt)
        self.down_cell_insts = []
        self.up_cell_insts = []
        self.down_cell_mappings = objects.CellMappingList()
        flavor = objects.Flavor(id=1, name='flavor1',
                                memory_mb=256, vcpus=1,
                                root_gb=1, ephemeral_gb=1,
                                flavorid='1',
                                swap=0, rxtx_factor=1.0,
                                vcpu_weight=1,
                                disabled=False,
                                is_public=True,
                                extra_specs={},
                                projects=[])
        _info_cache = objects.InstanceInfoCache(context)
        objects.InstanceInfoCache._from_db_object(context, _info_cache,
            test_instance_info_cache.fake_info_cache)
        # cell1 and cell2 will be the down cells while
        # cell0 and cell3 will be the up cells.
        down_cell_names = ['cell1', 'cell2']
        for cell in self.cells:
            # create 2 instances and their mappings in all the 4 cells
            for i in range(2):
                with context.target_cell(self.ctxt, cell) as cctxt:
                    inst = objects.Instance(
                        context=cctxt,
                        project_id=self.project_id,
                        user_id=self.project_id,
                        instance_type_id=flavor.id,
                        hostname='%s-inst%i' % (cell.name, i),
                        flavor=flavor,
                        info_cache=_info_cache,
                        display_name='server-test')
                    inst.create()
                im = objects.InstanceMapping(context=self.ctxt,
                                             instance_uuid=inst.uuid,
                                             cell_mapping=cell,
                                             project_id=self.project_id,
                                             queued_for_delete=False)
                im.create()
                if cell.name in down_cell_names:
                    self.down_cell_insts.append(inst.uuid)
                else:
                    self.up_cell_insts.append(inst.uuid)
            # In cell1 and cell3 add a third instance in a different project
            # to show the --all-tenants case.
            if cell.name == 'cell1' or cell.name == 'cell3':
                with context.target_cell(self.ctxt, cell) as cctxt:
                    inst = objects.Instance(
                        context=cctxt,
                        project_id='faker',
                        user_id='faker',
                        instance_type_id=flavor.id,
                        hostname='%s-inst%i' % (cell.name, 3),
                        flavor=flavor,
                        info_cache=_info_cache,
                        display_name='server-test')
                    inst.create()
                im = objects.InstanceMapping(context=self.ctxt,
                                             instance_uuid=inst.uuid,
                                             cell_mapping=cell,
                                             project_id='faker',
                                             queued_for_delete=False)
                im.create()
            if cell.name in down_cell_names:
                self.down_cell_mappings.objects.append(cell)
        self.useFixture(nova_fixtures.DownCellFixture(self.down_cell_mappings))

    def test_get_servers_with_down_cells(self):
        servers = self.api.get_servers(detail=False)
        # 4 servers from the up cells and 4 servers from the down cells
        self.assertEqual(8, len(servers))
        for server in servers:
            if 'name' not in server:
                # server is in the down cell.
                self.assertEqual('UNKNOWN', server['status'])
                self.assertIn(server['id'], self.down_cell_insts)
                self.assertIn('links', server)
                # the partial construct will have only the above 3 keys
                self.assertEqual(3, len(server))
            else:
                # server in up cell
                self.assertIn(server['id'], self.up_cell_insts)
                # has all the keys
                self.assertEqual(server['name'], 'server-test')
                self.assertIn('links', server)

    def test_get_servers_detail_with_down_cells(self):
        servers = self.api.get_servers()
        # 4 servers from the up cells and 4 servers from the down cells
        self.assertEqual(8, len(servers))
        for server in servers:
            if 'user_id' not in server:
                # server is in the down cell.
                self.assertEqual('UNKNOWN', server['status'])
                self.assertIn(server['id'], self.down_cell_insts)
                # the partial construct will only have 5 keys: created,
                # tenant_id, status, id and links. security_groups should be
                # present too but isn't since we haven't created a network
                # interface
                self.assertEqual(5, len(server))
            else:
                # server in up cell
                self.assertIn(server['id'], self.up_cell_insts)
                # has all the keys
                self.assertEqual(server['user_id'], self.project_id)
                self.assertIn('image', server)

    def test_get_servers_detail_limits_with_down_cells(self):
        servers = self.api.get_servers(search_opts={'limit': 5})
        # 4 servers from the up cells since we skip down cell
        # results by default for paging.
        self.assertEqual(4, len(servers), servers)
        for server in servers:
            # server in up cell
            self.assertIn(server['id'], self.up_cell_insts)
            # has all the keys
            self.assertEqual(server['user_id'], self.project_id)
            self.assertIn('image', server)

    def test_get_servers_detail_limits_with_down_cells_the_500_gift(self):
        self.flags(list_records_by_skipping_down_cells=False, group='api')
        # We get an API error with a 500 response code since the
        # list_records_by_skipping_down_cells config option is False.
        exp = self.assertRaises(client.OpenStackApiException,
                                self.api.get_servers,
                                search_opts={'limit': 5})
        self.assertEqual(500, exp.response.status_code)
        self.assertIn('NovaException', six.text_type(exp))

    def test_get_servers_detail_marker_in_down_cells(self):
        marker = self.down_cell_insts[2]
        # It will fail with a 500 if the marker is in the down cell.
        exp = self.assertRaises(client.OpenStackApiException,
                                self.api.get_servers,
                                search_opts={'marker': marker})
        self.assertEqual(500, exp.response.status_code)
        self.assertIn('oslo_db.exception.DBError', six.text_type(exp))

    def test_get_servers_detail_marker_sorting(self):
        marker = self.up_cell_insts[1]
        # It will give the results from the up cell if
        # list_records_by_skipping_down_cells config option is True.
        servers = self.api.get_servers(search_opts={'marker': marker,
                                                    'sort_key': "created_at",
                                                    'sort_dir': "asc"})
        # since there are 4 servers from the up cells, when giving the
        # second instance as marker, sorted by creation time in ascending
        # third and fourth instances will be returned.
        self.assertEqual(2, len(servers))
        for server in servers:
            self.assertIn(
                server['id'], [self.up_cell_insts[2], self.up_cell_insts[3]])

    def test_get_servers_detail_non_admin_with_deleted_flag(self):
        # if list_records_by_skipping_down_cells config option is True
        # this deleted option should be ignored and the rest of the instances
        # from the up cells and the partial results from the down cells should
        # be returned.
        # Set the policy so we don't have permission to allow
        # all filters but are able to get server details.
        servers_rule = 'os_compute_api:servers:detail'
        extraspec_rule = 'os_compute_api:servers:allow_all_filters'
        self.policy.set_rules({
            extraspec_rule: 'rule:admin_api',
            servers_rule: '@'})
        servers = self.api.get_servers(search_opts={'deleted': True})
        # gets 4 results from up cells and 4 from down cells.
        self.assertEqual(8, len(servers))
        for server in servers:
            if "image" not in server:
                self.assertIn(server['id'], self.down_cell_insts)
            else:
                self.assertIn(server['id'], self.up_cell_insts)

    def test_get_servers_detail_filters(self):
        # We get the results only from the up cells, this ignoring the down
        # cells if list_records_by_skipping_down_cells config option is True.
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.admin_api = api_fixture.admin_api
        self.admin_api.microversion = '2.69'
        servers = self.admin_api.get_servers(
            search_opts={'hostname': "cell3-inst0"})
        self.assertEqual(1, len(servers))
        self.assertEqual(self.up_cell_insts[2], servers[0]['id'])

    def test_get_servers_detail_all_tenants_with_down_cells(self):
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.admin_api = api_fixture.admin_api
        self.admin_api.microversion = '2.69'
        servers = self.admin_api.get_servers(search_opts={'all_tenants': True})
        # 4 servers from the up cells and 4 servers from the down cells
        # plus the 2 instances from cell1 and cell3 which are in a different
        # project.
        self.assertEqual(10, len(servers))
        for server in servers:
            if 'user_id' not in server:
                # server is in the down cell.
                self.assertEqual('UNKNOWN', server['status'])
                if server['tenant_id'] != 'faker':
                    self.assertIn(server['id'], self.down_cell_insts)
                # the partial construct will only have 5 keys: created,
                # tenant_id, status, id and links. security_groups should be
                # present too but isn't since we haven't created a network
                # interface
                self.assertEqual(5, len(server))
            else:
                # server in up cell
                if server['tenant_id'] != 'faker':
                    self.assertIn(server['id'], self.up_cell_insts)
                    self.assertEqual(server['user_id'], self.project_id)
                self.assertIn('image', server)


class ServerRebuildTestCase(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'
    # We have to cap the microversion at 2.38 because that's the max we
    # can use to update image metadata via our compute images proxy API.
    microversion = '2.38'

    def _disable_compute_for(self, server):
        # Refresh to get its host
        server = self.admin_api.get_server(server['id'])
        host = server['OS-EXT-SRV-ATTR:host']

        # Disable the service it is on
        self.admin_api.put_service(
            'disable', {'host': host, 'binary': 'nova-compute'})

    def test_rebuild_with_image_novalidhost(self):
        """Creates a server with an image that is valid for the single compute
        that we have. Then rebuilds the server, passing in an image with
        metadata that does not fit the single compute which should result in
        a NoValidHost error. The ImagePropertiesFilter filter is enabled by
        default so that should filter out the host based on the image meta.
        """

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
        self._wait_for_state_change(server, 'ACTIVE')

        # Disable the host we're on so ComputeFilter would have ruled it out
        # normally
        self._disable_compute_for(server)

        # Now update the image metadata to be something that won't work with
        # the fake compute driver we're using since the fake driver has an
        # "x86_64" architecture.
        rebuild_image_ref = self.glance.auto_disk_config_enabled_image['id']
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
            server, instance_actions.REBUILD, 'rebuild_server')
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
            return self.placement.get(
                '/resource_providers/%s/usages' % provider_uuid).body['usages']

        def _get_allocations_by_server_uuid(server_uuid):
            return self.placement.get(
                '/allocations/%s' % server_uuid).body['allocations']

        def _set_provider_inventory(rp_uuid, resource_class, inventory):
            # Get the resource provider generation for the inventory update.
            rp = self.placement.get(
                '/resource_providers/%s' % rp_uuid).body
            inventory['resource_provider_generation'] = rp['generation']
            return self.placement.put(
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
        self._wait_for_state_change(server, 'ACTIVE')

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

        rebuild_image_ref = self.glance.auto_disk_config_enabled_image['id']
        # Now rebuild the server with a different image.
        rebuild_req_body = {
            'rebuild': {
                'imageRef': rebuild_image_ref
            }
        }
        self.api.api_post('/servers/%s/action' % server['id'],
                          rebuild_req_body)
        self._wait_for_server_parameter(
            server, {'OS-EXT-STS:task_state': None})

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
                    nova_fixtures.CinderFixture.IMAGE_BACKED_VOL,
                    'source_type': 'volume',
                    'destination_type': 'volume'
                }]
            }
        }
        server = self.api.post_server(server_req_body)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # For a volume-backed server, the image ref will be an empty string
        # in the server response.
        self.assertEqual('', server['image'])

        # Now rebuild the server with a different image than was used to create
        # our fake volume.
        rebuild_image_ref = self.glance.auto_disk_config_enabled_image['id']
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


class ServersTestV280(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'

    def setUp(self):
        super(ServersTestV280, self).setUp()
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

        self.api.microversion = '2.80'
        self.admin_api.microversion = '2.80'

    def test_get_migrations_after_cold_migrate_server_in_same_project(
            self):
        # Create a server by non-admin
        server = self.api.post_server({
            'server': {
                'flavorRef': 1,
                'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'name': 'migrate-server-test',
                'networks': 'none'
            }})
        server_id = server['id']

        # Check it's there
        found_server = self.api.get_server(server_id)
        self.assertEqual(server_id, found_server['id'])

        self.start_service('compute', host='host2')

        post = {'migrate': {}}
        self.admin_api.post_server_action(server_id, post)

        # Get the migration records by admin
        migrations = self.admin_api.get_migrations(
            user_id=self.admin_api.auth_user)
        self.assertEqual(1, len(migrations))
        self.assertEqual(server_id, migrations[0]['instance_uuid'])

        # Get the migration records by non-admin
        migrations = self.admin_api.get_migrations(
            user_id=self.api.auth_user)
        self.assertEqual([], migrations)

    def test_get_migrations_after_live_migrate_server_in_different_project(
            self):
        # Create a server by non-admin
        server = self.api.post_server({
            'server': {
                'flavorRef': 1,
                'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'name': 'migrate-server-test',
                'networks': 'none'
            }})
        server_id = server['id']

        # Check it's there
        found_server = self.api.get_server(server_id)
        self.assertEqual(server_id, found_server['id'])

        server = self._wait_for_state_change(found_server, 'BUILD')

        self.start_service('compute', host='host2')

        project_id_1 = '4906260553374bf0a5d566543b320516'
        project_id_2 = 'c850298c1b6b4796a8f197ac310b2469'
        new_api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version=self.api_major_version, project_id=project_id_1))
        new_admin_api = new_api_fixture.admin_api
        new_admin_api.microversion = '2.80'

        post = {
            'os-migrateLive': {
                'host': 'host2',
                'block_migration': True
            }
        }
        new_admin_api.post_server_action(server_id, post)
        # Get the migration records
        migrations = new_admin_api.get_migrations(project_id=project_id_1)
        self.assertEqual(1, len(migrations))
        self.assertEqual(server_id, migrations[0]['instance_uuid'])

        # Get the migration records by not exist project_id
        migrations = new_admin_api.get_migrations(project_id=project_id_2)
        self.assertEqual([], migrations)


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

    def test_resize_revert(self):
        self._test_resize_revert(dest_hostname='host1')

    def test_resize_revert_reverse(self):
        self._test_resize_revert(dest_hostname='host2')

    def test_resize_confirm(self):
        self._test_resize_confirm(dest_hostname='host1')

    def test_resize_confirm_reverse(self):
        self._test_resize_confirm(dest_hostname='host2')

    def test_migration_confirm_resize_error(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(self.flavor1,
                                                  source_hostname)

        self._move_and_check_allocations(
            server, request={'migrate': None}, old_flavor=self.flavor1,
            new_flavor=self.flavor1, source_rp_uuid=source_rp_uuid,
            dest_rp_uuid=dest_rp_uuid)

        # Mock failure
        def fake_confirm_migration(context, migration, instance, network_info):
            raise exception.MigrationPreCheckError(
                reason='test_migration_confirm_resize_error')

        with mock.patch('nova.virt.fake.FakeDriver.'
                        'confirm_migration',
                        side_effect=fake_confirm_migration):

            # Confirm the migration/resize and check the usages
            post = {'confirmResize': None}
            self.api.post_server_action(
                server['id'], post, check_response_status=[204])
            server = self._wait_for_state_change(server, 'ERROR')

        # After confirming and error, we should have an allocation only on the
        # destination host

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)
        self.assertRequestMatchesUsage({'VCPU': 0,
                                        'MEMORY_MB': 0,
                                        'DISK_GB': 0}, source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

        self._run_periodics()

        # Check we're still accurate after running the periodics

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)
        self.assertRequestMatchesUsage({'VCPU': 0,
                                        'MEMORY_MB': 0,
                                        'DISK_GB': 0}, source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

        self._delete_and_check_allocations(server)

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
        self._wait_for_state_change(server, 'ACTIVE')

        # Make sure the RequestSpec.flavor matches the original flavor.
        ctxt = context.get_admin_context()
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        self.assertEqual(self.flavor1['id'], reqspec.flavor.flavorid)

        self._run_periodics()

        # the original host expected to have the old resource allocation
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertRequestMatchesUsage({'VCPU': 0,
                                        'MEMORY_MB': 0,
                                        'DISK_GB': 0}, dest_rp_uuid)

        # Check that the server only allocates resource from the original host
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

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
        self._confirm_resize(server)

        # After confirming, we should have an allocation only on the
        # destination host

        # The target host usage should be according to the new flavor
        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor2)
        self.assertRequestMatchesUsage({'VCPU': 0,
                                        'MEMORY_MB': 0,
                                        'DISK_GB': 0}, source_rp_uuid)

        # and the target host allocation should be according to the new flavor
        self.assertFlavorMatchesAllocation(self.flavor2, server['id'],
                                           dest_rp_uuid)

        self._run_periodics()

        # Check we're still accurate after running the periodics

        # and the target host usage should be according to the new flavor
        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor2)
        self.assertRequestMatchesUsage({'VCPU': 0,
                                        'MEMORY_MB': 0,
                                        'DISK_GB': 0}, source_rp_uuid)

        # and the server allocates only from the target host
        self.assertFlavorMatchesAllocation(self.flavor2, server['id'],
                                           dest_rp_uuid)

        self._delete_and_check_allocations(server)

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
        self._wait_for_state_change(server, 'ACTIVE')

        self._run_periodics()

        # after revert only allocations due to the old flavor should remain
        self.assertFlavorMatchesUsage(rp_uuid, self.flavor2)

        self.assertFlavorMatchesAllocation(self.flavor2, server['id'],
                                           rp_uuid)

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
        self._confirm_resize(server)

        self._run_periodics()

        # after confirm only allocations due to the new flavor should remain
        self.assertFlavorMatchesUsage(rp_uuid, self.flavor3)

        self.assertFlavorMatchesAllocation(self.flavor3, server['id'],
                                           rp_uuid)

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

        self.api.post_server_action(
            server['id'], resize_req, check_response_status=[202])
        event = self._assert_resize_migrate_action_fail(
            server, instance_actions.RESIZE, 'NoValidHost')
        self.assertIn('details', event)
        # This test case works in microversion 2.84.
        self.assertIn('No valid host was found', event['details'])
        server = self.admin_api.get_server(server['id'])
        self.assertEqual(source_hostname, server['OS-EXT-SRV-ATTR:host'])
        # The server is still ACTIVE and thus there is no fault message.
        self.assertEqual('ACTIVE', server['status'])
        self.assertNotIn('fault', server)

        # only the source host shall have usages after the failed resize
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        # Check that the other provider has no usage
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        # Check that the server only allocates resource from the host it is
        # booted on
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_resize_delete_while_verify(self):
        """Test scenario where the server is deleted while in the
        VERIFY_RESIZE state and ensures the allocations are properly
        cleaned up from the source and target compute node resource providers.
        The _confirm_resize_on_deleting() method in the API is actually
        responsible for making sure the migration-based allocations get
        cleaned up by confirming the resize on the source host before deleting
        the server from the target host.
        """
        dest_hostname = 'host2'
        source_hostname = self._other_hostname(dest_hostname)
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(self.flavor1,
                                                  source_hostname)

        self._resize_and_check_allocations(server, self.flavor1, self.flavor2,
                                           source_rp_uuid, dest_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_resize_confirm_assert_hypervisor_usage_no_periodics(self):
        """Resize confirm test for bug 1818914 to make sure the tracked
        resource usage in the os-hypervisors API (not placement) is as
        expected during a confirmed resize. This intentionally does not
        use _test_resize_confirm in order to avoid running periodics.
        """
        # There should be no usage from a server on either hypervisor.
        source_rp_uuid = self._get_provider_uuid_by_host('host1')
        dest_rp_uuid = self._get_provider_uuid_by_host('host2')
        no_usage = {'vcpus': 0, 'disk': 0, 'ram': 0}
        for rp_uuid in (source_rp_uuid, dest_rp_uuid):
            self.assert_hypervisor_usage(
                rp_uuid, no_usage, volume_backed=False)

        # Create the server and wait for it to be ACTIVE.
        server = self._boot_and_check_allocations(self.flavor1, 'host1')

        # There should be resource usage for flavor1 on the source host.
        self.assert_hypervisor_usage(
            source_rp_uuid, self.flavor1, volume_backed=False)
        # And still no usage on the dest host.
        self.assert_hypervisor_usage(
            dest_rp_uuid, no_usage, volume_backed=False)

        # Resize the server to flavor2 and wait for VERIFY_RESIZE.
        self.flags(allow_resize_to_same_host=False)
        resize_req = {
            'resize': {
                'flavorRef': self.flavor2['id']
            }
        }
        self.api.post_server_action(server['id'], resize_req)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # There should be resource usage for flavor1 on the source host.
        self.assert_hypervisor_usage(
            source_rp_uuid, self.flavor1, volume_backed=False)
        # And resource usage for flavor2 on the target host.
        self.assert_hypervisor_usage(
            dest_rp_uuid, self.flavor2, volume_backed=False)

        # Now confirm the resize and check hypervisor usage again.
        self._confirm_resize(server)

        # There should no resource usage for flavor1 on the source host.
        self.assert_hypervisor_usage(
            source_rp_uuid, no_usage, volume_backed=False)
        # And resource usage for flavor2 should still be on the target host.
        self.assert_hypervisor_usage(
            dest_rp_uuid, self.flavor2, volume_backed=False)

        # Run periodics and make sure usage is still as expected.
        self._run_periodics()
        self.assert_hypervisor_usage(
            source_rp_uuid, no_usage, volume_backed=False)
        self.assert_hypervisor_usage(
            dest_rp_uuid, self.flavor2, volume_backed=False)

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
        # patch https://review.opendev.org/#/c/482629/ gets merged:
        # fake_notifier.wait_for_versioned_notifications(
        #     'compute_task.rebuild_server')
        self._wait_for_notification_event_type('compute_task.rebuild_server')

        self._run_periodics()

        # There is no other host to evacuate to so the rebuild should put the
        # VM to ERROR state, but it should remain on source compute
        expected_params = {'OS-EXT-SRV-ATTR:host': source_hostname,
                           'status': 'ERROR'}
        server = self._wait_for_server_parameter(server,
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
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)
        zero_usage = {'VCPU': 0, 'DISK_GB': 0, 'MEMORY_MB': 0}
        self.assertRequestMatchesUsage(zero_usage, dest_rp_uuid)

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
        self.api.post_server_action(server['id'], post)
        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'NoValidHost')
        expected_params = {'OS-EXT-SRV-ATTR:host': source_hostname,
                           'status': 'ACTIVE'}
        self._wait_for_server_parameter(server, expected_params)

        self._run_periodics()

        # Expect to have allocation only on source_host
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)
        zero_usage = {'VCPU': 0, 'DISK_GB': 0, 'MEMORY_MB': 0}
        self.assertRequestMatchesUsage(zero_usage, dest_rp_uuid)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def _test_evacuate(self, keep_hypervisor_state):
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
        server = self._wait_for_server_parameter(server,
                                                 expected_params)

        # Expect to have allocation and usages on both computes as the
        # source compute is still down
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        self._check_allocation_during_evacuate(
            self.flavor1, server['id'], source_rp_uuid, dest_rp_uuid)

        # restart the source compute
        self.compute1 = self.restart_compute_service(
            self.compute1, keep_hypervisor_state=keep_hypervisor_state)

        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertEqual({'VCPU': 0,
                          'MEMORY_MB': 0,
                          'DISK_GB': 0},
                         source_usages)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_evacuate_instance_kept_on_the_hypervisor(self):
        self._test_evacuate(keep_hypervisor_state=True)

    def test_evacuate_clean_hypervisor(self):
        self._test_evacuate(keep_hypervisor_state=False)

    def _test_evacuate_forced_host(self, keep_hypervisor_state):
        """Evacuating a server with a forced host bypasses the scheduler
        which means conductor has to create the allocations against the
        destination node. This test recreates the scenarios and asserts
        the allocations on the source and destination nodes are as expected.
        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        # the ability to force evacuate a server is removed entirely in 2.68
        self.api.microversion = '2.67'

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
        server = self._wait_for_server_parameter(server,
                                                 expected_params)

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        # Expect to have allocation and usages on both computes as the
        # source compute is still down
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        self._check_allocation_during_evacuate(
            self.flavor1, server['id'], source_rp_uuid, dest_rp_uuid)

        # restart the source compute
        self.compute1 = self.restart_compute_service(
            self.compute1, keep_hypervisor_state=keep_hypervisor_state)
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
        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_evacuate_forced_host_instance_kept_on_the_hypervisor(self):
        self._test_evacuate_forced_host(keep_hypervisor_state=True)

    def test_evacuate_forced_host_clean_hypervisor(self):
        self._test_evacuate_forced_host(keep_hypervisor_state=False)

    def test_evacuate_forced_host_v268(self):
        """Evacuating a server with a forced host was removed in API
        microversion 2.68. This test ensures that the request is rejected.
        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        # evacuate the server and force the destination host which bypasses
        # the scheduler
        post = {
            'evacuate': {
                'host': dest_hostname,
                'force': True
            }
        }
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               server['id'], post)
        self.assertIn("'force' was unexpected", six.text_type(ex))

    # NOTE(gibi): there is a similar test in SchedulerOnlyChecksTargetTest but
    # we want this test here as well because ServerMovingTest is a parent class
    # of multiple test classes that run this test case with different compute
    # node setups.
    def test_evacuate_host_specified_but_not_forced(self):
        """Evacuating a server with a host but using the scheduler to create
        the allocations against the destination node. This test recreates the
        scenarios and asserts the allocations on the source and destination
        nodes are as expected.
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

        # evacuate the server specify the target but do not force the
        # destination host to use the scheduler to validate the target host
        post = {
            'evacuate': {
                'host': dest_hostname,
            }
        }
        self.api.post_server_action(server['id'], post)
        expected_params = {'OS-EXT-SRV-ATTR:host': dest_hostname,
                           'status': 'ACTIVE'}
        server = self._wait_for_server_parameter(server,
                                                 expected_params)

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        # Expect to have allocation and usages on both computes as the
        # source compute is still down
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        self._check_allocation_during_evacuate(
            self.flavor1, server['id'], source_rp_uuid, dest_rp_uuid)

        # restart the source compute
        self.compute1 = self.restart_compute_service(self.compute1)
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
        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

        self._delete_and_check_allocations(server)

    def _test_evacuate_claim_on_dest_fails(self, keep_hypervisor_state):
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
        # performs a claim test.
        def fake_move_claim(*args, **kwargs):
            # Assert the destination node allocation exists.
            self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)
            raise exception.ComputeResourcesUnavailable(
                    reason='test_evacuate_claim_on_dest_fails')

        with mock.patch('nova.compute.claims.MoveClaim', fake_move_claim):
            # evacuate the server
            self.api.post_server_action(server['id'], {'evacuate': {}})
            # the migration will fail on the dest node and the instance will
            # stay ACTIVE and task_state will be set to None.
            server = self._wait_for_server_parameter(
                server, {'status': 'ACTIVE', 'OS-EXT-STS:task_state': None})

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        # The allocation should still exist on the source node since it's
        # still down, and the allocation on the destination node should be
        # cleaned up.
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        # restart the source compute
        self.compute1 = self.restart_compute_service(
            self.compute1, keep_hypervisor_state=keep_hypervisor_state)
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        # Run the periodics again to show they don't change anything.
        self._run_periodics()

        # The source compute shouldn't have cleaned up the allocation for
        # itself since the instance didn't move.
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

    def test_evacuate_claim_on_dest_fails_instance_kept_on_the_hypervisor(
            self):
        self._test_evacuate_claim_on_dest_fails(keep_hypervisor_state=True)

    def test_evacuate_claim_on_dest_fails_clean_hypervisor(self):
        self._test_evacuate_claim_on_dest_fails(keep_hypervisor_state=False)

    def _test_evacuate_rebuild_on_dest_fails(self, keep_hypervisor_state):
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
            self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)
            raise test.TestingException('test_evacuate_rebuild_on_dest_fails')

        with mock.patch.object(
                self.compute2.driver, 'rebuild', fake_rebuild):
            # evacuate the server
            self.api.post_server_action(server['id'], {'evacuate': {}})
            # the migration will fail on the dest node and the instance will
            # go into error state
            server = self._wait_for_state_change(server, 'ERROR')

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        # The allocation should still exist on the source node since it's
        # still down, and the allocation on the destination node should be
        # cleaned up.
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        # restart the source compute
        self.compute1 = self.restart_compute_service(
            self.compute1, keep_hypervisor_state=keep_hypervisor_state)
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        # Run the periodics again to show they don't change anything.
        self._run_periodics()

        # The source compute shouldn't have cleaned up the allocation for
        # itself since the instance didn't move.
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

    def test_evacuate_rebuild_on_dest_fails_instance_kept_on_the_hypervisor(
            self):
        self._test_evacuate_rebuild_on_dest_fails(keep_hypervisor_state=True)

    def test_evacuate_rebuild_on_dest_fails_clean_hypervisor(self):
        self._test_evacuate_rebuild_on_dest_fails(keep_hypervisor_state=False)

    def _boot_then_shelve_and_check_allocations(self, hostname, rp_uuid):
        # avoid automatic shelve offloading
        self.flags(shelved_offload_time=-1)
        server = self._boot_and_check_allocations(
            self.flavor1, hostname)
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_state_change(server, 'SHELVED')
        # the host should maintain the existing allocation for this instance
        # while the instance is shelved
        self.assertFlavorMatchesUsage(rp_uuid, self.flavor1)
        # Check that the server only allocates resource from the host it is
        # booted on
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           rp_uuid)
        return server

    def test_shelve_unshelve(self):
        source_hostname = self.compute1.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        server = self._boot_then_shelve_and_check_allocations(
            source_hostname, source_rp_uuid)

        req = {
            'unshelve': None
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_state_change(server, 'ACTIVE')

        # the host should have resource usage as the instance is ACTIVE
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        # Check that the server only allocates resource from the host it is
        # booted on
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def _shelve_offload_and_check_allocations(self, server, source_rp_uuid):
        req = {
            'shelveOffload': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(server, {'status': 'SHELVED_OFFLOADED',
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
            'unshelve': None
        }
        self.api.post_server_action(server['id'], req)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # unshelving an offloaded instance will call the scheduler so the
        # instance might end up on a different host
        current_hostname = server['OS-EXT-SRV-ATTR:host']
        self.assertEqual(current_hostname, self._other_hostname(
            source_hostname))

        # the host running the instance should have resource usage
        current_rp_uuid = self._get_provider_uuid_by_host(current_hostname)
        self.assertFlavorMatchesUsage(current_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           current_rp_uuid)

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
            'unshelve': None
        }
        self.api.post_server_action(server['id'], req)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # unshelving an offloaded instance will call the scheduler so the
        # instance might end up on a different host
        current_hostname = server['OS-EXT-SRV-ATTR:host']
        self.assertEqual(current_hostname, source_hostname)

        # the host running the instance should have resource usage
        current_rp_uuid = self._get_provider_uuid_by_host(current_hostname)
        self.assertFlavorMatchesUsage(current_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           current_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_live_migrate_force(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        # the ability to force live migrate a server is removed entirely in
        # 2.68
        self.api.microversion = '2.67'

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        # live migrate the server and force the destination host which bypasses
        # the scheduler
        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
                'force': True,
            }
        }

        self.api.post_server_action(server['id'], post)
        self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': dest_hostname,
             'status': 'ACTIVE'})

        self._run_periodics()

        # NOTE(danms): There should be no usage for the source
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, source_rp_uuid)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        # the server has an allocation on only the dest node
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_live_migrate_forced_v268(self):
        """Live migrating a server with a forced host was removed in API
        microversion 2.68. This test ensures that the request is rejected.
        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        # live migrate the server and force the destination host which bypasses
        # the scheduler
        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
                'force': True,
            }
        }

        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               server['id'], post)
        self.assertIn("'force' was unexpected", six.text_type(ex))

    def test_live_migrate(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname,
            networks=[{'port': self.neutron.port_1['id']}])
        post = {
            'os-migrateLive': {
                'host': dest_hostname,
                'block_migration': True,
            }
        }

        self.api.post_server_action(server['id'], post)
        self._wait_for_server_parameter(server,
                                        {'OS-EXT-SRV-ATTR:host': dest_hostname,
                                         'status': 'ACTIVE'})

        self._run_periodics()

        # NOTE(danms): There should be no usage for the source
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, source_rp_uuid)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

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

        # Since the instance didn't move, assert the allocations are still
        # on the source node.
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        # Assert the allocations, created by the scheduler, are cleaned up
        # after the migration pre-check error happens.
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        # There should only be 1 allocation for the instance on the source node
        self.assertFlavorMatchesAllocation(
            self.flavor1, server['id'], source_rp_uuid)

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

        # the ability to force live migrate a server is removed entirely in
        # 2.68
        self.api.microversion = '2.67'

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        def stub_pre_live_migration(context, instance, block_device_info,
                                    network_info, disk_info, migrate_data):
            # Make sure the source node allocations are against the migration
            # record and the dest node allocations are against the instance.
            self.assertFlavorMatchesAllocation(
                self.flavor1, migrate_data.migration.uuid, source_rp_uuid)

            self.assertFlavorMatchesAllocation(
                self.flavor1, server['id'], dest_rp_uuid)
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
        # when start _cleanup_pre_live_migration, then set it to failed status
        # at the end of _rollback_live_migration
        migration = self._wait_for_migration_status(
            server, ['error', 'failed'])
        # The _rollback_live_migration method in the compute manager will reset
        # the task_state on the instance, so wait for that to happen.
        server = self._wait_for_server_parameter(
            server, {'OS-EXT-STS:task_state': None})

        self.assertEqual(source_hostname, migration['source_compute'])
        self.assertEqual(dest_hostname, migration['dest_compute'])

        # Since the instance didn't move, assert the allocations are still
        # on the source node.
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        # Assert the allocations, created by the scheduler, are cleaned up
        # after the rollback happens.
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        # There should only be 1 allocation for the instance on the source node
        self.assertFlavorMatchesAllocation(
            self.flavor1, server['id'], source_rp_uuid)

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
            self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)
            allocations = self._get_allocations_by_server_uuid(server['id'])
            self.assertIn(dest_rp_uuid, allocations)

            source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
            self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)
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

        # Expects no allocation records on the failed host.
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        # Ensure the allocation records still exist on the source host.
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)
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
            self.assertFlavorMatchesUsage(rp_uuid, self.flavor1, self.flavor2)
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
        if failing_method == '_finish_resize':
            # finish_resize will drop the old flavor allocations.
            self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor2)
        else:
            # The new_flavor should have been subtracted from the doubled
            # allocation which just leaves us with the original flavor.
            self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

    def test_resize_to_same_host_prep_resize_fails(self):
        self._test_resize_to_same_host_instance_fails(
            '_prep_resize', 'compute_prep_resize')

    def test_resize_instance_fails_allocation_cleanup(self):
        self._test_resize_to_same_host_instance_fails(
            '_resize_instance', 'compute_resize_instance')

    def test_finish_resize_fails_allocation_cleanup(self):
        self._test_resize_to_same_host_instance_fails(
            '_finish_resize', 'compute_finish_resize')

    def _server_created_with_host(self):
        hostname = self.compute1.host
        server_req = self._build_server(
            image_uuid="155d900f-4e14-4e4c-a73d-069cbf4541e6",
            flavor_id=self.flavor1["id"],
            networks='none')
        server_req['host'] = hostname

        created_server = self.api.post_server({"server": server_req})
        server = self._wait_for_state_change(created_server, "ACTIVE")
        return server

    def test_live_migration_after_server_created_with_host(self):
        """Test after creating server with requested host, and then
        do live-migration for the server. The requested host will not
        effect the new moving operation.
        """
        dest_hostname = self.compute2.host
        created_server = self._server_created_with_host()

        post = {
            'os-migrateLive': {
                'host': None,
                'block_migration': 'auto'
            }
        }
        self.api.post_server_action(created_server['id'], post)
        new_server = self._wait_for_server_parameter(
            created_server, {'status': 'ACTIVE'})
        inst_dest_host = new_server["OS-EXT-SRV-ATTR:host"]

        self.assertEqual(dest_hostname, inst_dest_host)

    def test_evacuate_after_server_created_with_host(self):
        """Test after creating server with requested host, and then
        do evacuation for the server. The requested host will not
        effect the new moving operation.
        """
        dest_hostname = self.compute2.host
        created_server = self._server_created_with_host()

        source_compute_id = self.admin_api.get_services(
            host=created_server["OS-EXT-SRV-ATTR:host"],
            binary='nova-compute')[0]['id']

        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        post = {
            'evacuate': {}
        }
        self.api.post_server_action(created_server['id'], post)
        expected_params = {'OS-EXT-SRV-ATTR:host': dest_hostname,
                           'status': 'ACTIVE'}
        new_server = self._wait_for_server_parameter(created_server,
                                                     expected_params)
        inst_dest_host = new_server["OS-EXT-SRV-ATTR:host"]

        self.assertEqual(dest_hostname, inst_dest_host)

    def test_resize_and_confirm_after_server_created_with_host(self):
        """Test after creating server with requested host, and then
        do resize for the server. The requested host will not
        effect the new moving operation.
        """
        dest_hostname = self.compute2.host
        created_server = self._server_created_with_host()

        # resize server
        self.flags(allow_resize_to_same_host=False)
        resize_req = {
            'resize': {
                'flavorRef': self.flavor2['id']
            }
        }
        self.api.post_server_action(created_server['id'], resize_req)
        self._wait_for_state_change(created_server, 'VERIFY_RESIZE')

        # Confirm the resize
        new_server = self._confirm_resize(created_server)
        inst_dest_host = new_server["OS-EXT-SRV-ATTR:host"]

        self.assertEqual(dest_hostname, inst_dest_host)

    def test_shelve_unshelve_after_server_created_with_host(self):
        """Test after creating server with requested host, and then
        do shelve and unshelve for the server. The requested host
        will not effect the new moving operation.
        """
        dest_hostname = self.compute2.host
        created_server = self._server_created_with_host()

        self.flags(shelved_offload_time=-1)
        req = {'shelve': {}}
        self.api.post_server_action(created_server['id'], req)
        self._wait_for_state_change(created_server, 'SHELVED')

        req = {'shelveOffload': {}}
        self.api.post_server_action(created_server['id'], req)
        self._wait_for_server_parameter(created_server, {
            'status': 'SHELVED_OFFLOADED',
            'OS-EXT-SRV-ATTR:host': None,
            'OS-EXT-AZ:availability_zone': ''})

        # unshelve after shelve offload will do scheduling. this test case
        # wants to test the scenario when the scheduler select a different host
        # to ushelve the instance. So we disable the original host.
        source_service_id = self.admin_api.get_services(
            host=created_server["OS-EXT-SRV-ATTR:host"],
            binary='nova-compute')[0]['id']
        self.admin_api.put_service(source_service_id, {'status': 'disabled'})

        req = {'unshelve': None}
        self.api.post_server_action(created_server['id'], req)
        new_server = self._wait_for_state_change(created_server, 'ACTIVE')
        inst_dest_host = new_server["OS-EXT-SRV-ATTR:host"]

        self.assertEqual(dest_hostname, inst_dest_host)

    @mock.patch.object(utils, 'fill_provider_mapping',
                       wraps=utils.fill_provider_mapping)
    def _test_resize_reschedule_uses_host_lists(self, mock_fill_provider_map,
                                                fails, num_alts=None):
        """Test that when a resize attempt fails, the retry comes from the
        supplied host_list, and does not call the scheduler.
        """
        server_req = self._build_server(
            image_uuid="155d900f-4e14-4e4c-a73d-069cbf4541e6",
            flavor_id=self.flavor1["id"],
            networks='none')

        created_server = self.api.post_server({"server": server_req})
        server = self._wait_for_state_change(created_server,
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

        self.useFixture(nova_fixtures.HostNameWeigherFixture(
            weights={
                "selection": 999, "alt_host1": 888, "alt_host2": 777,
                "alt_host3": 666, "host1": 0, "host2": 0}))
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
            server = self._wait_for_state_change(created_server,
                    "ERROR")
            # The usage should be unchanged from the original flavor
            self.assertFlavorMatchesUsage(uuid_orig, self.flavor1)
            # There should be no usages on any of the hosts
            target_uuids = (uuid_sel, uuid_alt1, uuid_alt2, uuid_alt3)
            empty_usage = {"VCPU": 0, "MEMORY_MB": 0, "DISK_GB": 0}
            for target_uuid in target_uuids:
                usage = self._get_provider_usages(target_uuid)
                self.assertEqual(empty_usage, usage)
        else:
            server = self._wait_for_state_change(created_server,
                    "VERIFY_RESIZE")
            # Verify that the selected host failed, and was rescheduled to
            # an alternate host.
            new_server_host = server.get("OS-EXT-SRV-ATTR:host")
            expected_host = hosts[fails]["name"]
            self.assertEqual(expected_host, new_server_host)
            uuid_dest = hosts[fails]["uuid"]
            # The usage should match the resized flavor
            self.assertFlavorMatchesUsage(uuid_dest, self.flavor2)
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

        # fill_provider_mapping should have been called once for the initial
        # build, once for the resize scheduling to the primary host and then
        # once per reschedule.
        expected_fill_count = 2
        if num_alts > 1:
            expected_fill_count += self.num_fails - 1
        self.assertGreaterEqual(mock_fill_provider_map.call_count,
                                expected_fill_count)

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
        self._confirm_resize(server)

        def _check_allocation():
            # the target host usage should be according to the flavor
            self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)
            # the source host has no usage
            self.assertRequestMatchesUsage({'VCPU': 0,
                                            'MEMORY_MB': 0,
                                            'DISK_GB': 0}, source_rp_uuid)

            # and the target host allocation should be according to the flavor
            self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                               dest_rp_uuid)

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
        self._wait_for_state_change(server, 'ACTIVE')

        def _check_allocation():
            self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)
            self.assertRequestMatchesUsage({'VCPU': 0,
                                            'MEMORY_MB': 0,
                                            'DISK_GB': 0}, dest_rp_uuid)

            # Check that the server only allocates resource from the original
            # host
            self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                               source_rp_uuid)

        # the original host expected to have the old resource allocation
        _check_allocation()
        self._run_periodics()
        _check_allocation()

        self._delete_and_check_allocations(server)


class PollUnconfirmedResizesTest(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests for the _poll_unconfirmed_resizes periodic task."""
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(PollUnconfirmedResizesTest, self).setUp()
        # Start two computes for the resize.
        self._start_compute('host1')
        self._start_compute('host2')

    def test_source_host_down_during_confirm(self):
        """Tests the scenario that between the time that the server goes to
        VERIFY_RESIZE status and the _poll_unconfirmed_resizes periodic task
        runs the source compute service goes down so the confirm task fails.
        """
        server = self._build_server(networks='none', host='host1')
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        # Cold migrate the server to the other host.
        self.api.post_server_action(server['id'], {'migrate': None})
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])
        # Make sure the migration is finished.
        self._wait_for_migration_status(server, ['finished'])
        # Stop and force down the source compute service.
        self.computes['host1'].stop()
        source_service = self.api.get_services(
            binary='nova-compute', host='host1')[0]
        self.api.put_service(
            source_service['id'], {'status': 'disabled', 'forced_down': True})
        # Now configure auto-confirm and call the method on the target compute
        # so we do not have to wait for the periodic to run.
        self.flags(resize_confirm_window=1)
        # Stub timeutils so the DB API query finds the unconfirmed migration.
        future = timeutils.utcnow() + datetime.timedelta(hours=1)
        ctxt = context.get_admin_context()
        with osloutils_fixture.TimeFixture(future):
            self.computes['host2'].manager._poll_unconfirmed_resizes(ctxt)
        self.assertIn('Error auto-confirming resize',
                      self.stdlog.logger.output)
        self.assertIn('Service is unavailable at this time',
                      self.stdlog.logger.output)
        # The source compute service check should have been done before the
        # migration status was updated so it should still be "finished".
        self._wait_for_migration_status(server, ['finished'])
        # Try to confirm in the API while the source compute service is still
        # down to assert the 409 (rather than a 500) error.
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_action,
                               server['id'], {'confirmResize': None})
        self.assertEqual(409, ex.response.status_code)
        self.assertIn('Service is unavailable at this time', six.text_type(ex))
        # Bring the source compute back up and try to confirm the resize which
        # should work since the migration status is still "finished".
        self.restart_compute_service(self.computes['host1'])
        self.api.put_service(
            source_service['id'], {'status': 'enabled', 'forced_down': False})
        # Use the API to confirm the resize because _poll_unconfirmed_resizes
        # requires mucking with the current time which causes problems with
        # the service_is_up check in the API.
        self.api.post_server_action(server['id'], {'confirmResize': None})
        self._wait_for_state_change(server, 'ACTIVE')


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

        self._wait_for_server_parameter(server,
                                        {'OS-EXT-SRV-ATTR:host': dest_hostname,
                                         'status': 'ACTIVE'})

        self._run_periodics()

        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, source_rp_uuid)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           dest_rp_uuid)

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
        self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': source_hostname,
             'status': 'ACTIVE'})

        self._run_periodics()

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertNotIn(dest_rp_uuid, allocations)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self.assertRequestMatchesUsage({'VCPU': 0,
                                        'MEMORY_MB': 0,
                                        'DISK_GB': 0}, dest_rp_uuid)

        self._delete_and_check_allocations(server)


class ServerLiveMigrateForceAndAbortWithNestedResourcesRequest(
        ServerLiveMigrateForceAndAbort):
    compute_driver = 'fake.FakeLiveMigrateDriverWithNestedCustomResources'

    def setUp(self):
        super(ServerLiveMigrateForceAndAbortWithNestedResourcesRequest,
              self).setUp()
        # modify the flavor used in the test base class to require one piece of
        # CUSTOM_MAGIC resource as well.

        self.api.post_extra_spec(
            self.flavor1['id'], {'extra_specs': {'resources:CUSTOM_MAGIC': 1}})
        # save the extra_specs in the flavor stored in the test case as
        # well
        self.flavor1['extra_specs'] = {'resources:CUSTOM_MAGIC': 1}


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
        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor1['id'],
            networks='none')

        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(created_server, 'ACTIVE')
        dest_hostname = server['OS-EXT-SRV-ATTR:host']
        failed_hostname = self._other_hostname(dest_hostname)

        LOG.info('failed on %s', failed_hostname)
        LOG.info('booting on %s', dest_hostname)

        failed_rp_uuid = self._get_provider_uuid_by_host(failed_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        # Expects no allocation records on the failed host.
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, failed_rp_uuid)

        # Ensure the allocation records on the destination host.
        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

    def test_allocation_fails_during_reschedule(self):
        """Verify that if nova fails to allocate resources during re-schedule
        then the server is put into ERROR state properly.
        """

        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor1['id'],
            networks='none')

        orig_claim = utils.claim_resources
        # First call is during boot, we want that to succeed normally. Then the
        # fake virt driver triggers a re-schedule. During that re-schedule we
        # simulate that the placement call fails.
        with mock.patch('nova.scheduler.utils.claim_resources',
                        side_effect=[
                            orig_claim,
                            exception.AllocationUpdateFailed(
                                consumer_uuid=uuids.inst1, error='testing')]):

            server = self.api.post_server({'server': server_req})
            server = self._wait_for_state_change(server, 'ERROR')

        self._delete_and_check_allocations(server)


class ServerRescheduleTestsWithNestedResourcesRequest(ServerRescheduleTests):
    compute_driver = 'fake.FakeRescheduleDriverWithNestedCustomResources'

    def setUp(self):
        super(ServerRescheduleTestsWithNestedResourcesRequest, self).setUp()
        # modify the flavor used in the test base class to require one piece of
        # CUSTOM_MAGIC resource as well.

        self.api.post_extra_spec(
            self.flavor1['id'], {'extra_specs': {'resources:CUSTOM_MAGIC': 1}})
        # save the extra_specs in the flavor stored in the test case as
        # well
        self.flavor1['extra_specs'] = {'resources:CUSTOM_MAGIC': 1}


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
        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor1['id'],
            networks='none')

        created_server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(created_server, 'ERROR')

        failed_hostname = self.compute1.manager.host

        # BuildAbortException coming from the FakeBuildAbortDriver will not
        # trigger a reschedule and the placement cleanup is the last step in
        # the compute manager after instance state setting, fault recording
        # and notification sending. So we have no other way than simply wait
        # to ensure the placement cleanup happens before we assert it.
        def placement_cleanup():
            failed_rp_uuid = self._get_provider_uuid_by_host(failed_hostname)
            # Expects no allocation records on the failed host.
            self.assertRequestMatchesUsage({'VCPU': 0,
                                            'MEMORY_MB': 0,
                                            'DISK_GB': 0}, failed_rp_uuid)
        self._wait_for_assert(placement_cleanup)


class ServerDeleteBuildTests(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests server delete during instance in build and validates that
        allocations in Placement are properly cleaned up.
    """
    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(ServerDeleteBuildTests, self).setUp()
        self.compute1 = self._start_compute(host='host1')
        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def test_delete_stuck_build_instance_after_claim(self):
        """Test for bug 1859496 where an instance allocation can leaks after
        deletion if build process have been interrupted after resource claim
        """

        # To reproduce the issue we need to interrupt instance spawn
        # when build request has already reached the scheduler service,
        # so that instance resource get claims.
        # Real case can typically be a conductor restart during
        # instance claim.
        # To emulate conductor restart we raise an Exception in
        # filter_scheduler after instance is claimed and mock
        # _bury_in_cell0 in that case conductor thread return.
        # Then we delete server after ensuring allocation is made and check
        # There is no leak.
        # Note that because deletion occurs early, conductor did not populate
        # instance DB entries in cells, preventing the compute
        # update_available_resource periodic task to heal leaked allocations.

        server_req = self._build_server(
            'interrupted-server', flavor_id=self.flavor1['id'],
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')

        with test.nested(
            mock.patch('nova.scheduler.filter_scheduler.FilterScheduler.'
                       '_ensure_sufficient_hosts'),
            mock.patch('nova.conductor.manager.ComputeTaskManager.'
                       '_bury_in_cell0')
        ) as (mock_suff_hosts, mock_bury):
            mock_suff_hosts.side_effect = test.TestingException('oops')
            server = self.api.post_server({'server': server_req})
            self._wait_for_server_allocations(server['id'])
            self.api.api_delete('/servers/%s' % server['id'])
            allocations = self._get_allocations_by_server_uuid(server['id'])
            self.assertEqual({}, allocations)


class ServerBuildAbortTestsWithNestedResourceRequest(ServerBuildAbortTests):
    compute_driver = 'fake.FakeBuildAbortDriverWithNestedCustomResources'

    def setUp(self):
        super(ServerBuildAbortTestsWithNestedResourceRequest, self).setUp()
        # modify the flavor used in the test base class to require one piece of
        # CUSTOM_MAGIC resource as well.

        self.api.post_extra_spec(
            self.flavor1['id'], {'extra_specs': {'resources:CUSTOM_MAGIC': 1}})
        # save the extra_specs in the flavor stored in the test case as
        # well
        self.flavor1['extra_specs'] = {'resources:CUSTOM_MAGIC': 1}


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
        # We start with no usages on the host.
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, rp_uuid)

        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor1['id'],
            networks='none')

        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(server, 'ACTIVE')

        # assert allocations exist for the host
        self.assertFlavorMatchesUsage(rp_uuid, self.flavor1)

        # shelve offload the server
        self.flags(shelved_offload_time=0)
        self.api.post_server_action(server['id'], {'shelve': None})
        self._wait_for_server_parameter(server, {'status': 'SHELVED_OFFLOADED',
                               'OS-EXT-SRV-ATTR:host': None})

        # assert allocations were removed from the host
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, rp_uuid)

        # unshelve the server, which should fail
        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_action_fail_completion(
            server, instance_actions.UNSHELVE, 'compute_unshelve_instance')

        # assert allocations were removed from the host
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, rp_uuid)


class ServerUnshelveSpawnFailTestsWithNestedResourceRequest(
    ServerUnshelveSpawnFailTests):
    compute_driver = ('fake.'
                      'FakeUnshelveSpawnFailDriverWithNestedCustomResources')

    def setUp(self):
        super(ServerUnshelveSpawnFailTestsWithNestedResourceRequest,
              self).setUp()
        # modify the flavor used in the test base class to require one piece of
        # CUSTOM_MAGIC resource as well.

        self.api.post_extra_spec(
            self.flavor1['id'], {'extra_specs': {'resources:CUSTOM_MAGIC': 1}})
        # save the extra_specs in the flavor stored in the test case as
        # well
        self.flavor1['extra_specs'] = {'resources:CUSTOM_MAGIC': 1}


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
        server = self._wait_for_state_change(server, 'SOFT_DELETED')

        self._run_periodics()

        # in soft delete state nova should keep the resource allocation as
        # the instance can be restored
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        self.assertFlavorMatchesUsage(rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           rp_uuid)

        # run the periodic reclaim but as time isn't advanced it should not
        # reclaim the instance
        ctxt = context.get_admin_context()
        self.compute1._reclaim_queued_deletes(ctxt)

        self._run_periodics()

        self.assertFlavorMatchesUsage(rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           rp_uuid)

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
        server = self._wait_for_state_change(server, 'ACTIVE')

        # after restore the allocations should be kept
        self.assertFlavorMatchesUsage(rp_uuid, self.flavor1)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           rp_uuid)

        # Now we want a real delete
        self.flags(reclaim_instance_interval=0)
        self._delete_and_check_allocations(server)


class ServerSoftDeleteTestsWithNestedResourceRequest(ServerSoftDeleteTests):
    compute_driver = 'fake.MediumFakeDriverWithNestedCustomResources'

    def setUp(self):
        super(ServerSoftDeleteTestsWithNestedResourceRequest, self).setUp()
        # modify the flavor used in the test base class to require one piece of
        # CUSTOM_MAGIC resource as well.

        self.api.post_extra_spec(
            self.flavor1['id'], {'extra_specs': {'resources:CUSTOM_MAGIC': 1}})
        # save the extra_specs in the flavor stored in the test case as
        # well
        self.flavor1['extra_specs'] = {'resources:CUSTOM_MAGIC': 1}


class VolumeBackedServerTest(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests for volume-backed servers."""

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(VolumeBackedServerTest, self).setUp()
        self.compute1 = self._start_compute('host1')
        self.flavor_id = self._create_flavor(
            disk=10, ephemeral=20, swap=5 * 1024)

    def _create_server(self):
        server_req = self._build_server(
            flavor_id=self.flavor_id,
            networks='none')
        server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(server, 'ACTIVE')
        return server

    def _create_volume_backed_server(self):
        self.useFixture(nova_fixtures.CinderFixture(self))
        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
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
        server = self._wait_for_state_change(server, 'ACTIVE')
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

    def test_volume_backed_image_type_filter(self):
        # Enable the image type support filter and ensure that a
        # non-image-having volume-backed server can still boot
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')
        server = self._create_volume_backed_server()
        created_server = self.api.get_server(server['id'])
        self.assertEqual('ACTIVE', created_server['status'])

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
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])
        # Confirm the cold migration and check usage and the request spec.
        self._confirm_resize(server)
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
        self._wait_for_state_change(server, 'SHELVED_OFFLOADED')
        fake_notifier.wait_for_versioned_notifications(
                'instance.shelve_offload.end')
        # The server should not have any allocations since it's not currently
        # hosted on any compute service.
        allocs = self._get_allocations_by_server_uuid(server['id'])
        self.assertDictEqual({}, allocs)
        # Now unshelve the server and make sure there are still no DISK_GB
        # allocations for the root disk.
        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_state_change(server, 'ACTIVE')
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
        with nova_utils.temporary_mutation(self.api, microversion='2.35'):
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

        server_req = self._build_server(
            image_uuid=image_id,
            flavor_id=flavor_id,
            networks='none')
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
        """Tests that a server create request using a required trait in the
        flavor ends up on the single compute node resource provider that also
        has that trait in Placement. That test will however pass half of the
        times even if the trait is not taken into consideration, so we are
        also disabling the compute node that has the required trait and try
        again, which should result in a no valid host error.
        """

        # Decorate compute1 resource provider with the required trait.
        rp_uuid = self._get_provider_uuid_by_host(self.compute1.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_VMX'])

        # Create server using flavor with required trait
        server = self._create_server_with_traits(self.flavor_with_trait['id'],
                                                 self.image_id_without_trait)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # Assert the server ended up on the expected compute host that has
        # the required trait.
        self.assertEqual(self.compute1.host, server['OS-EXT-SRV-ATTR:host'])

        # Disable the compute node that has the required trait
        compute1_service_id = self.admin_api.get_services(
            host=self.compute1.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute1_service_id, {'status': 'disabled'})

        # Create server using flavor with required trait
        server = self._create_server_with_traits(self.flavor_with_trait['id'],
                                                 self.image_id_without_trait)

        # The server should go to ERROR state because there is no valid host.
        server = self._wait_for_state_change(server, 'ERROR')
        self.assertIsNone(server['OS-EXT-SRV-ATTR:host'])
        # Make sure the failure was due to NoValidHost by checking the fault.
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

    def test_flavor_forbidden_traits_based_scheduling(self):
        """Tests that a server create request using a forbidden trait in the
        flavor ends up on the single compute host that doesn't have that
        trait in Placement. That test will however pass half of the times even
        if the trait is not taken into consideration, so we are also disabling
        the compute node that doesn't have the forbidden trait and try again,
        which should result in a no valid host error.
        """

        # Decorate compute1 resource provider with forbidden trait
        rp_uuid = self._get_provider_uuid_by_host(self.compute1.host)
        self._set_provider_traits(rp_uuid, ['HW_CPU_X86_SGX'])

        # Create server using flavor with forbidden trait
        server = self._create_server_with_traits(
            self.flavor_with_forbidden_trait['id'],
            self.image_id_without_trait
        )

        server = self._wait_for_state_change(server, 'ACTIVE')

        # Assert the server ended up on the expected compute host that doesn't
        # have the forbidden trait.
        self.assertEqual(self.compute2.host, server['OS-EXT-SRV-ATTR:host'])

        # Disable the compute node that doesn't have the forbidden trait
        compute2_service_id = self.admin_api.get_services(
            host=self.compute2.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute2_service_id, {'status': 'disabled'})

        # Create server using flavor with forbidden trait
        server = self._create_server_with_traits(
            self.flavor_with_forbidden_trait['id'],
            self.image_id_without_trait
        )

        # The server should go to ERROR state because there is no valid host.
        server = self._wait_for_state_change(server, 'ERROR')
        self.assertIsNone(server['OS-EXT-SRV-ATTR:host'])
        # Make sure the failure was due to NoValidHost by checking the fault.
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

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
        server = self._wait_for_state_change(server, 'ACTIVE')
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
        server = self._wait_for_state_change(server, 'ACTIVE')
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

        self.useFixture(nova_fixtures.CinderFixture(self))
        # Create our server with a volume containing the image meta data with a
        # required trait
        server = self._create_volume_backed_server_with_traits(
            self.flavor_without_trait['id'],
            nova_fixtures.CinderFixture.
            IMAGE_WITH_TRAITS_BACKED_VOL)

        server = self._wait_for_state_change(server, 'ACTIVE')
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

        self.useFixture(nova_fixtures.CinderFixture(self))
        # Create our server with a flavor trait and a volume containing the
        # image meta data with a required trait
        server = self._create_volume_backed_server_with_traits(
            self.flavor_with_trait['id'],
            nova_fixtures.CinderFixture.
            IMAGE_WITH_TRAITS_BACKED_VOL)

        server = self._wait_for_state_change(server, 'ACTIVE')
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
        server = self._wait_for_state_change(server, 'ERROR')
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
        server = self._wait_for_state_change(server, 'ERROR')
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
        server = self._wait_for_state_change(server, 'ERROR')
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
        self.useFixture(nova_fixtures.CinderFixture(self))
        # Create our server with a volume
        server = self._create_volume_backed_server_with_traits(
            self.flavor_without_trait['id'],
            nova_fixtures.CinderFixture.
            IMAGE_WITH_TRAITS_BACKED_VOL)

        # The server should go to ERROR state because there is no valid host.
        server = self._wait_for_state_change(server, 'ERROR')
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
        server = self._wait_for_state_change(server, 'ACTIVE')

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
            server, {'OS-EXT-STS:task_state': None})

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
        server = self._wait_for_state_change(server, 'ACTIVE')

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
            server, instance_actions.REBUILD, 'rebuild_server')
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
        server = self._wait_for_state_change(server,
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
            server, {'OS-EXT-STS:task_state': None})

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
        server = self._wait_for_state_change(server, 'ACTIVE')

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
            server, instance_actions.REBUILD, 'rebuild_server')
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


class ServerTestV256Common(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'
    microversion = '2.56'
    ADMIN_API = True

    def _setup_compute_service(self):
        # Set up 3 compute services in the same cell
        for host in ('host1', 'host2', 'host3'):
            self.start_service('compute', host=host)

    def _create_server(self, target_host=None):
        server = self._build_server(
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
            self.start_service('compute', host=host,
                               cell_name=host_to_cell_mappings[host])

    def test_migrate_server_to_host_in_different_cell(self):
        # We target host1 specifically so that we have a predictable target for
        # the cold migration in cell2.
        server = self._create_server(target_host='host1')
        server = self._wait_for_state_change(server, 'ACTIVE')

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
        server = self._wait_for_state_change(server, 'ACTIVE')
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
        found_server = self._wait_for_state_change(server, 'ACTIVE')

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


class ConsumerGenerationConflictTest(
        integrated_helpers.ProviderUsageBaseTestCase):

    # we need the medium driver to be able to allocate resource not just for
    # a single instance
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(ConsumerGenerationConflictTest, self).setUp()
        flavors = self.api.get_flavors()
        self.flavor = flavors[0]
        self.other_flavor = flavors[1]
        self.compute1 = self._start_compute('compute1')
        self.compute2 = self._start_compute('compute2')

    def test_create_server_fails_as_placement_reports_consumer_conflict(self):
        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor['id'],
            networks='none')

        # We cannot pre-create a consumer with the uuid of the instance created
        # below as that uuid is generated. Instead we have to simulate that
        # Placement returns 409, consumer generation conflict for the PUT
        # /allocation request the scheduler does for the instance.
        with mock.patch('keystoneauth1.adapter.Adapter.put') as mock_put:
            rsp = fake_requests.FakeResponse(
                409,
                jsonutils.dumps(
                    {'errors': [
                        {'code': 'placement.concurrent_update',
                         'detail': 'consumer generation conflict'}]}))
            mock_put.return_value = rsp

            created_server = self.api.post_server({'server': server_req})
            server = self._wait_for_state_change(created_server, 'ERROR')

        # This is not a conflict that the API user can ever resolve. It is a
        # serious inconsistency in our database or a bug in the scheduler code
        # doing the claim.
        self.assertEqual(500, server['fault']['code'])
        self.assertIn('Failed to update allocations for consumer',
                      server['fault']['message'])

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(0, len(allocations))

        self._delete_and_check_allocations(server)

    def test_migrate_claim_on_dest_fails(self):
        source_hostname = self.compute1.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)

        server = self._boot_and_check_allocations(self.flavor, source_hostname)

        # We have to simulate that Placement returns 409, consumer generation
        # conflict for the PUT /allocation request the scheduler does on the
        # destination host for the instance.
        with mock.patch('keystoneauth1.adapter.Adapter.put') as mock_put:
            rsp = fake_requests.FakeResponse(
                409,
                jsonutils.dumps(
                    {'errors': [
                        {'code': 'placement.concurrent_update',
                         'detail': 'consumer generation conflict'}]}))
            mock_put.return_value = rsp

            request = {'migrate': None}
            self.api.post_server_action(server['id'], request,
                                        check_response_status=[202])
            self._wait_for_server_parameter(server,
                                            {'OS-EXT-STS:task_state': None})

        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'claim_resources')

        # The migration is aborted so the instance is ACTIVE on the source
        # host instead of being in VERIFY_RESIZE state.
        server = self.api.get_server(server['id'])
        self.assertEqual('ACTIVE', server['status'])
        self.assertEqual(source_hostname, server['OS-EXT-SRV-ATTR:host'])

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor)

        self.assertFlavorMatchesAllocation(self.flavor, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_migrate_move_allocation_fails_due_to_conflict(self):
        source_hostname = self.compute1.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)

        server = self._boot_and_check_allocations(self.flavor, source_hostname)

        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))

        with mock.patch('keystoneauth1.adapter.Adapter.post',
                        autospec=True) as mock_post:
            mock_post.return_value = rsp

            request = {'migrate': None}
            self.api.post_server_action(server['id'], request,
                                        check_response_status=[202])
            self._wait_for_server_parameter(server,
                                            {'OS-EXT-STS:task_state': None})

        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'move_allocations')

        self.assertEqual(1, mock_post.call_count)

        migrations = self.api.get_migrations()
        self.assertEqual(1, len(migrations))
        self.assertEqual('migration', migrations[0]['migration_type'])
        self.assertEqual(server['id'], migrations[0]['instance_uuid'])
        self.assertEqual(source_hostname, migrations[0]['source_compute'])
        self.assertEqual('error', migrations[0]['status'])

        # The migration is aborted so the instance is ACTIVE on the source
        # host instead of being in VERIFY_RESIZE state.
        server = self.api.get_server(server['id'])
        self.assertEqual('ACTIVE', server['status'])
        self.assertEqual(source_hostname, server['OS-EXT-SRV-ATTR:host'])

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor)

        self.assertFlavorMatchesAllocation(self.flavor, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_confirm_migrate_delete_alloc_on_source_fails(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(self.flavor, source_hostname)
        self._migrate_and_check_allocations(
            server, self.flavor, source_rp_uuid, dest_rp_uuid)

        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))

        with mock.patch('keystoneauth1.adapter.Adapter.put',
                        autospec=True) as mock_put:
            mock_put.return_value = rsp

            post = {'confirmResize': None}
            self.api.post_server_action(
                server['id'], post, check_response_status=[204])
            server = self._wait_for_state_change(server, 'ERROR')
            self.assertIn('Failed to delete allocations',
                          server['fault']['message'])

        self.assertEqual(1, mock_put.call_count)

        migrations = self.api.get_migrations()
        self.assertEqual(1, len(migrations))
        self.assertEqual('migration', migrations[0]['migration_type'])
        self.assertEqual(server['id'], migrations[0]['instance_uuid'])
        self.assertEqual(source_hostname, migrations[0]['source_compute'])
        self.assertEqual('error', migrations[0]['status'])

        # NOTE(gibi): Nova leaks the allocation held by the migration_uuid even
        # after the instance is deleted. At least nova logs a fat ERROR.
        self.assertIn('Deleting allocation in placement for migration %s '
                      'failed. The instance %s will be put to ERROR state but '
                      'the allocation held by the migration is leaked.' %
                      (migrations[0]['uuid'], server['id']),
                      self.stdlog.logger.output)
        self._delete_server(server)
        fake_notifier.wait_for_versioned_notifications('instance.delete.end')

        allocations = self._get_allocations_by_server_uuid(
            migrations[0]['uuid'])
        self.assertEqual(1, len(allocations))

    def test_revert_migrate_delete_dest_allocation_fails_due_to_conflict(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        server = self._boot_and_check_allocations(self.flavor, source_hostname)
        self._migrate_and_check_allocations(
            server, self.flavor, source_rp_uuid, dest_rp_uuid)

        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))

        with mock.patch('keystoneauth1.adapter.Adapter.post',
                        autospec=True) as mock_post:
            mock_post.return_value = rsp

            post = {'revertResize': None}
            self.api.post_server_action(server['id'], post)
            server = self._wait_for_state_change(server, 'ERROR')

        self.assertEqual(1, mock_post.call_count)

        migrations = self.api.get_migrations()
        self.assertEqual(1, len(migrations))
        self.assertEqual('migration', migrations[0]['migration_type'])
        self.assertEqual(server['id'], migrations[0]['instance_uuid'])
        self.assertEqual(source_hostname, migrations[0]['source_compute'])
        self.assertEqual('error', migrations[0]['status'])

        # NOTE(gibi): Nova leaks the allocation held by the migration_uuid even
        # after the instance is deleted. At least nova logs a fat ERROR.
        self.assertIn('Reverting allocation in placement for migration %s '
                      'failed. The instance %s will be put into ERROR state '
                      'but the allocation held by the migration is leaked.' %
                      (migrations[0]['uuid'], server['id']),
                      self.stdlog.logger.output)
        self._delete_server(server)
        fake_notifier.wait_for_versioned_notifications('instance.delete.end')

        allocations = self._get_allocations_by_server_uuid(
            migrations[0]['uuid'])
        self.assertEqual(1, len(allocations))

    def test_revert_resize_same_host_delete_dest_fails_due_to_conflict(self):
        # make sure that the test only uses a single host
        compute2_service_id = self.admin_api.get_services(
            host=self.compute2.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute2_service_id, {'status': 'disabled'})

        hostname = self.compute1.manager.host
        rp_uuid = self._get_provider_uuid_by_host(hostname)

        server = self._boot_and_check_allocations(self.flavor, hostname)

        self._resize_to_same_host_and_check_allocations(
            server, self.flavor, self.other_flavor, rp_uuid)

        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))
        with mock.patch('keystoneauth1.adapter.Adapter.post',
                        autospec=True) as mock_post:
            mock_post.return_value = rsp

            post = {'revertResize': None}
            self.api.post_server_action(server['id'], post)
            server = self._wait_for_state_change(server, 'ERROR',)

        self.assertEqual(1, mock_post.call_count)

        migrations = self.api.get_migrations()
        self.assertEqual(1, len(migrations))
        self.assertEqual('resize', migrations[0]['migration_type'])
        self.assertEqual(server['id'], migrations[0]['instance_uuid'])
        self.assertEqual(hostname, migrations[0]['source_compute'])
        self.assertEqual('error', migrations[0]['status'])

        # NOTE(gibi): Nova leaks the allocation held by the migration_uuid even
        # after the instance is deleted. At least nova logs a fat ERROR.
        self.assertIn('Reverting allocation in placement for migration %s '
                      'failed. The instance %s will be put into ERROR state '
                      'but the allocation held by the migration is leaked.' %
                      (migrations[0]['uuid'], server['id']),
                      self.stdlog.logger.output)
        self._delete_server(server)
        fake_notifier.wait_for_versioned_notifications('instance.delete.end')

        allocations = self._get_allocations_by_server_uuid(
            migrations[0]['uuid'])
        self.assertEqual(1, len(allocations))

    def test_force_live_migrate_claim_on_dest_fails(self):
        # Normal live migrate moves source allocation from instance to
        # migration like a normal migrate tested above.
        # Normal live migrate claims on dest like a normal boot tested above.
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        # the ability to force live migrate a server is removed entirely in
        # 2.68
        self.api.microversion = '2.67'

        server = self._boot_and_check_allocations(
            self.flavor, source_hostname)

        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))
        with mock.patch('keystoneauth1.adapter.Adapter.put',
                        autospec=True) as mock_put:
            mock_put.return_value = rsp

            post = {
                'os-migrateLive': {
                    'host': dest_hostname,
                    'block_migration': True,
                    'force': True,
                }
            }

            self.api.post_server_action(server['id'], post)
            server = self._wait_for_state_change(server, 'ERROR')

        self.assertEqual(1, mock_put.call_count)

        # This is not a conflict that the API user can ever resolve. It is a
        # serious inconsistency in our database or a bug in the scheduler code
        # doing the claim.
        self.assertEqual(500, server['fault']['code'])
        # The instance is in ERROR state so the allocations are in limbo but
        # at least we expect that when the instance is deleted the allocations
        # are cleaned up properly.
        self._delete_and_check_allocations(server)

    def test_live_migrate_drop_allocation_on_source_fails(self):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        # the ability to force live migrate a server is removed entirely in
        # 2.68
        self.api.microversion = '2.67'

        server = self._boot_and_check_allocations(
            self.flavor, source_hostname)

        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        orig_put = adapter.Adapter.put

        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))

        self.adapter_put_call_count = 0

        def fake_put(_self, url, **kwargs):
            self.adapter_put_call_count += 1
            migration_uuid = self.get_migration_uuid_for_instance(server['id'])
            if url == '/allocations/%s' % migration_uuid:
                return rsp
            else:
                return orig_put(_self, url, **kwargs)

        with mock.patch('keystoneauth1.adapter.Adapter.put', new=fake_put):
            post = {
                'os-migrateLive': {
                    'host': dest_hostname,
                    'block_migration': True,
                    'force': True,
                }
            }

            self.api.post_server_action(server['id'], post)

            # nova does the source host cleanup _after_ setting the migration
            # to completed and sending end notifications so we have to wait
            # here a bit.
            time.sleep(1)

            # Nova failed to clean up on the source host. This right now puts
            # the instance to ERROR state and fails the migration.
            server = self._wait_for_server_parameter(server,
                {'OS-EXT-SRV-ATTR:host': dest_hostname,
                 'status': 'ERROR'})
            self._wait_for_migration_status(server, ['error'])
            fake_notifier.wait_for_versioned_notifications(
                'instance.live_migration_post.end')

        # 1 claim on destination, 1 normal delete on dest that fails,
        self.assertEqual(2, self.adapter_put_call_count)

        # As the cleanup on the source host failed Nova leaks the allocation
        # held by the migration.
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor)
        migration_uuid = self.get_migration_uuid_for_instance(server['id'])
        self.assertFlavorMatchesAllocation(self.flavor, migration_uuid,
                                           source_rp_uuid)

        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor)

        self.assertFlavorMatchesAllocation(self.flavor, server['id'],
                                           dest_rp_uuid)

        # NOTE(gibi): Nova leaks the allocation held by the migration_uuid even
        # after the instance is deleted. At least nova logs a fat ERROR.
        self.assertIn('Deleting allocation in placement for migration %s '
                      'failed. The instance %s will be put to ERROR state but '
                      'the allocation held by the migration is leaked.' %
                      (migration_uuid, server['id']),
                      self.stdlog.logger.output)

        self._delete_server(server)
        fake_notifier.wait_for_versioned_notifications('instance.delete.end')

        self.assertFlavorMatchesAllocation(self.flavor, migration_uuid,
                                           source_rp_uuid)

    def _test_evacuate_fails_allocating_on_dest_host(self, force):
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        # the ability to force evacuate a server is removed entirely in 2.68
        self.api.microversion = '2.67'

        server = self._boot_and_check_allocations(
            self.flavor, source_hostname)

        source_compute_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']

        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        rsp = fake_requests.FakeResponse(
            409,
            jsonutils.dumps(
                {'errors': [
                    {'code': 'placement.concurrent_update',
                     'detail': 'consumer generation conflict'}]}))

        with mock.patch('keystoneauth1.adapter.Adapter.put',
                        autospec=True) as mock_put:
            mock_put.return_value = rsp
            post = {
                'evacuate': {
                    'force': force
                }
            }
            if force:
                post['evacuate']['host'] = dest_hostname

            self.api.post_server_action(server['id'], post)
            server = self._wait_for_state_change(server, 'ERROR')

        self.assertEqual(1, mock_put.call_count)

        # As nova failed to allocate on the dest host we only expect allocation
        # on the source
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor)

        self.assertRequestMatchesUsage({'VCPU': 0,
                                        'MEMORY_MB': 0,
                                        'DISK_GB': 0}, dest_rp_uuid)

        self.assertFlavorMatchesAllocation(self.flavor, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_force_evacuate_fails_allocating_on_dest_host(self):
        self._test_evacuate_fails_allocating_on_dest_host(force=True)

    def test_evacuate_fails_allocating_on_dest_host(self):
        self._test_evacuate_fails_allocating_on_dest_host(force=False)

    def test_server_delete_fails_due_to_conflict(self):
        source_hostname = self.compute1.host

        server = self._boot_and_check_allocations(self.flavor, source_hostname)

        rsp = fake_requests.FakeResponse(
            409, jsonutils.dumps({'text': 'consumer generation conflict'}))

        with mock.patch('keystoneauth1.adapter.Adapter.put',
                        autospec=True) as mock_put:
            mock_put.return_value = rsp

            self.api.delete_server(server['id'])
            server = self._wait_for_state_change(server,
                                                 'ERROR')
            self.assertEqual(1, mock_put.call_count)

        # We still have the allocations as deletion failed
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor)

        self.assertFlavorMatchesAllocation(self.flavor, server['id'],
                                           source_rp_uuid)

        # retry the delete to make sure that allocations are removed this time
        self._delete_and_check_allocations(server)

    def test_server_local_delete_fails_due_to_conflict(self):
        source_hostname = self.compute1.host

        server = self._boot_and_check_allocations(self.flavor, source_hostname)
        source_compute_id = self.admin_api.get_services(
            host=self.compute1.host, binary='nova-compute')[0]['id']
        self.compute1.stop()
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        rsp = fake_requests.FakeResponse(
            409, jsonutils.dumps({'text': 'consumer generation conflict'}))

        with mock.patch('keystoneauth1.adapter.Adapter.put',
                        autospec=True) as mock_put:
            mock_put.return_value = rsp

            ex = self.assertRaises(client.OpenStackApiException,
                                   self.api.delete_server, server['id'])
            self.assertEqual(409, ex.response.status_code)
            self.assertIn('Failed to delete allocations for consumer',
                          jsonutils.loads(ex.response.content)[
                              'conflictingRequest']['message'])
            self.assertEqual(1, mock_put.call_count)

        # We still have the allocations as deletion failed
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor)

        self.assertFlavorMatchesAllocation(self.flavor, server['id'],
                                           source_rp_uuid)

        # retry the delete to make sure that allocations are removed this time
        self._delete_and_check_allocations(server)


class ServerMovingTestsWithNestedComputes(ServerMovingTests):
    """Runs all the server moving tests while the computes have nested trees.
    The servers still do not request resources from any child provider though.
    """
    compute_driver = 'fake.MediumFakeDriverWithNestedCustomResources'


class ServerMovingTestsWithNestedResourceRequests(
    ServerMovingTestsWithNestedComputes):
    """Runs all the server moving tests while the computes have nested trees.
    The servers also request resources from child providers.
    """

    def setUp(self):
        super(ServerMovingTestsWithNestedResourceRequests, self).setUp()
        # modify the flavors used in the ServerMoving test base class to
        # require one piece of CUSTOM_MAGIC resource as well.

        for flavor in [self.flavor1, self.flavor2, self.flavor3]:
            self.api.post_extra_spec(
                flavor['id'], {'extra_specs': {'resources:CUSTOM_MAGIC': 1}})
            # save the extra_specs in the flavor stored in the test case as
            # well
            flavor['extra_specs'] = {'resources:CUSTOM_MAGIC': 1}

    def _check_allocation_during_evacuate(
            self, flavor, server_uuid, source_root_rp_uuid, dest_root_rp_uuid):
        # NOTE(gibi): evacuate is the only case when the same consumer has
        # allocation from two different RP trees so we need a special check
        # here.
        allocations = self._get_allocations_by_server_uuid(server_uuid)
        source_rps = self._get_all_rp_uuids_in_a_tree(source_root_rp_uuid)
        dest_rps = self._get_all_rp_uuids_in_a_tree(dest_root_rp_uuid)

        self.assertEqual(set(source_rps + dest_rps), set(allocations))

        total_source_allocation = collections.defaultdict(int)
        total_dest_allocation = collections.defaultdict(int)
        for rp, alloc in allocations.items():
            for rc, value in alloc['resources'].items():
                if rp in source_rps:
                    total_source_allocation[rc] += value
                else:
                    total_dest_allocation[rc] += value

        self.assertEqual(
            self._resources_from_flavor(flavor), total_source_allocation)
        self.assertEqual(
            self._resources_from_flavor(flavor), total_dest_allocation)

    def test_live_migrate_force(self):
        # Nova intentionally does not support force live-migrating server
        # with nested allocations.

        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        # the ability to force live migrate a server is removed entirely in
        # 2.68
        self.api.microversion = '2.67'

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
        self._wait_for_migration_status(server, ['error'])
        self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': source_hostname,
             'status': 'ACTIVE'})
        self.assertIn('Unable to move instance %s to host host2. The instance '
                      'has complex allocations on the source host so move '
                      'cannot be forced.' %
                      server['id'],
                      self.stdlog.logger.output)

        self._run_periodics()

        # NOTE(danms): There should be no usage for the dest
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        # the server has an allocation on only the source node
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def _test_evacuate_forced_host(self, keep_hypervisor_state):
        # Nova intentionally does not support force evacuating server
        # with nested allocations.

        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        # the ability to force evacuate a server is removed entirely in 2.68
        self.api.microversion = '2.67'

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
        self._wait_for_migration_status(server, ['error'])
        expected_params = {'OS-EXT-SRV-ATTR:host': source_hostname,
                           'status': 'ACTIVE'}
        server = self._wait_for_server_parameter(server,
                                                 expected_params)
        self.assertIn('Unable to move instance %s to host host2. The instance '
                      'has complex allocations on the source host so move '
                      'cannot be forced.' %
                      server['id'],
                      self.stdlog.logger.output)

        # Run the periodics to show those don't modify allocations.
        self._run_periodics()

        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        # restart the source compute
        self.compute1 = self.restart_compute_service(
            self.compute1, keep_hypervisor_state=keep_hypervisor_state)
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'false'})

        # Run the periodics again to show they don't change anything.
        self._run_periodics()

        # When the source node starts up nothing should change as the
        # evacuation failed
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)

        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)


# NOTE(gibi): There is another case NestedToFlat but that leads to the same
# code path that NestedToNested as in both cases the instance will have
# complex allocation on the source host which is already covered in
# ServerMovingTestsWithNestedResourceRequests
class ServerMovingTestsFromFlatToNested(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Tests trying to move servers from a compute with a flat RP tree to a
    compute with a nested RP tree and assert that the blind allocation copy
    fails cleanly.
    """

    REQUIRES_LOCKING = True
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(ServerMovingTestsFromFlatToNested, self).setUp()
        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]
        self.api.post_extra_spec(
            self.flavor1['id'], {'extra_specs': {'resources:CUSTOM_MAGIC': 1}})
        self.flavor1['extra_specs'] = {'resources:CUSTOM_MAGIC': 1}

    def test_force_live_migrate_from_flat_to_nested(self):
        # first compute will start with the flat RP tree but we add
        # CUSTOM_MAGIC inventory to the root compute RP
        orig_update_provider_tree = fake.MediumFakeDriver.update_provider_tree

        # the ability to force live migrate a server is removed entirely in
        # 2.68
        self.api.microversion = '2.67'

        def stub_update_provider_tree(self, provider_tree, nodename,
                                      allocations=None):
            # do the regular inventory update
            orig_update_provider_tree(
                self, provider_tree, nodename, allocations)
            if nodename == 'host1':
                # add the extra resource
                inv = provider_tree.data(nodename).inventory
                inv['CUSTOM_MAGIC'] = {
                    'total': 10,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 10,
                    'step_size': 1,
                    'allocation_ratio': 1,
                }
                provider_tree.update_inventory(nodename, inv)

        self.stub_out('nova.virt.fake.FakeDriver.update_provider_tree',
                      stub_update_provider_tree)
        self.compute1 = self._start_compute(host='host1')
        source_rp_uuid = self._get_provider_uuid_by_host('host1')

        server = self._boot_and_check_allocations(self.flavor1, 'host1')
        # start the second compute with nested RP tree
        self.flags(
            compute_driver='fake.MediumFakeDriverWithNestedCustomResources')
        self.compute2 = self._start_compute(host='host2')

        # try to force live migrate from flat to nested.
        post = {
            'os-migrateLive': {
                'host': 'host2',
                'block_migration': True,
                'force': True,
            }
        }

        self.api.post_server_action(server['id'], post)
        # We expect that the migration will fail as force migrate tries to
        # blindly copy the source allocation to the destination but on the
        # destination there is no inventory of CUSTOM_MAGIC on the compute node
        # provider as that resource is reported on a child provider.
        self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})

        migration = self._wait_for_migration_status(server, ['error'])
        self.assertEqual('host1', migration['source_compute'])
        self.assertEqual('host2', migration['dest_compute'])

        # Nova fails the migration because it ties to allocation CUSTOM_MAGIC
        # from the dest node root RP and placement rejects the that allocation.
        self.assertIn("Unable to allocate inventory: Inventory for "
                      "'CUSTOM_MAGIC'", self.stdlog.logger.output)
        self.assertIn('No valid host was found. Unable to move instance %s to '
                      'host host2. There is not enough capacity on the host '
                      'for the instance.' % server['id'],
                      self.stdlog.logger.output)

        dest_rp_uuid = self._get_provider_uuid_by_host('host2')

        # There should be no usage for the dest
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        # and everything stays at the source
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)

    def test_force_evacuate_from_flat_to_nested(self):
        # first compute will start with the flat RP tree but we add
        # CUSTOM_MAGIC inventory to the root compute RP
        orig_update_provider_tree = fake.MediumFakeDriver.update_provider_tree

        # the ability to force evacuate a server is removed entirely in 2.68
        self.api.microversion = '2.67'

        def stub_update_provider_tree(self, provider_tree, nodename,
                                      allocations=None):
            # do the regular inventory update
            orig_update_provider_tree(
                self, provider_tree, nodename, allocations)
            if nodename == 'host1':
                # add the extra resource
                inv = provider_tree.data(nodename).inventory
                inv['CUSTOM_MAGIC'] = {
                    'total': 10,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 10,
                    'step_size': 1,
                    'allocation_ratio': 1,
                }
                provider_tree.update_inventory(nodename, inv)

        self.stub_out('nova.virt.fake.FakeDriver.update_provider_tree',
                      stub_update_provider_tree)
        self.compute1 = self._start_compute(host='host1')
        source_rp_uuid = self._get_provider_uuid_by_host('host1')

        server = self._boot_and_check_allocations(self.flavor1, 'host1')
        # start the second compute with nested RP tree
        self.flags(
            compute_driver='fake.MediumFakeDriverWithNestedCustomResources')
        self.compute2 = self._start_compute(host='host2')

        source_compute_id = self.admin_api.get_services(
            host='host1', binary='nova-compute')[0]['id']
        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # try to force evacuate from flat to nested.
        post = {
            'evacuate': {
                'host': 'host2',
                'force': True,
            }
        }

        self.api.post_server_action(server['id'], post)
        # We expect that the evacuation will fail as force evacuate tries to
        # blindly copy the source allocation to the destination but on the
        # destination there is no inventory of CUSTOM_MAGIC on the compute node
        # provider as that resource is reported on a child provider.
        self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})

        migration = self._wait_for_migration_status(server, ['error'])
        self.assertEqual('host1', migration['source_compute'])
        self.assertEqual('host2', migration['dest_compute'])

        # Nova fails the migration because it ties to allocation CUSTOM_MAGIC
        # from the dest node root RP and placement rejects the that allocation.
        self.assertIn("Unable to allocate inventory: Inventory for "
                      "'CUSTOM_MAGIC'", self.stdlog.logger.output)
        self.assertIn('No valid host was found. Unable to move instance %s to '
                      'host host2. There is not enough capacity on the host '
                      'for the instance.' % server['id'],
                      self.stdlog.logger.output)

        dest_rp_uuid = self._get_provider_uuid_by_host('host2')

        # There should be no usage for the dest
        self.assertRequestMatchesUsage(
            {'VCPU': 0,
             'MEMORY_MB': 0,
             'DISK_GB': 0}, dest_rp_uuid)

        # and everything stays at the source
        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)
        self.assertFlavorMatchesAllocation(self.flavor1, server['id'],
                                           source_rp_uuid)

        self._delete_and_check_allocations(server)


class PortResourceRequestBasedSchedulingTestBase(
        integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.FakeDriverWithPciResources'

    CUSTOM_VNIC_TYPE_NORMAL = 'CUSTOM_VNIC_TYPE_NORMAL'
    CUSTOM_VNIC_TYPE_DIRECT = 'CUSTOM_VNIC_TYPE_DIRECT'
    CUSTOM_VNIC_TYPE_MACVTAP = 'CUSTOM_VNIC_TYPE_MACVTAP'
    CUSTOM_PHYSNET1 = 'CUSTOM_PHYSNET1'
    CUSTOM_PHYSNET2 = 'CUSTOM_PHYSNET2'
    CUSTOM_PHYSNET3 = 'CUSTOM_PHYSNET3'
    PF1 = 'pf1'
    PF2 = 'pf2'
    PF3 = 'pf3'

    def setUp(self):
        # enable PciPassthroughFilter to support SRIOV before the base class
        # starts the scheduler
        if 'PciPassthroughFilter' not in CONF.filter_scheduler.enabled_filters:
            self.flags(
                enabled_filters=CONF.filter_scheduler.enabled_filters +
                                ['PciPassthroughFilter'],
                group='filter_scheduler')

        self.useFixture(
            fake.FakeDriverWithPciResources.
                FakeDriverWithPciResourcesConfigFixture())

        super(PortResourceRequestBasedSchedulingTestBase, self).setUp()
        # Make ComputeManager._allocate_network_async synchronous to detect
        # errors in tests that involve rescheduling.
        self.useFixture(nova_fixtures.SpawnIsSynchronousFixture())
        self.compute1 = self._start_compute('host1')
        self.compute1_rp_uuid = self._get_provider_uuid_by_host('host1')
        self.compute1_service_id = self.admin_api.get_services(
            host='host1', binary='nova-compute')[0]['id']
        self.ovs_bridge_rp_per_host = {}
        self.sriov_dev_rp_per_host = {}
        self.flavor = self.api.get_flavors()[0]
        self.flavor_with_group_policy = self.api.get_flavors()[1]

        # Setting group policy for placement. This is mandatory when more than
        # one request group is included in the allocation candidate request and
        # we have tests with two ports both having resource request modelled as
        # two separate request groups.
        self.admin_api.post_extra_spec(
            self.flavor_with_group_policy['id'],
            {'extra_specs': {'group_policy': 'isolate'}})

        self._create_networking_rp_tree('host1', self.compute1_rp_uuid)

        # add extra ports and the related network to the neutron fixture
        # specifically for these tests. It cannot be added globally in the
        # fixture init as it adds a second network that makes auto allocation
        # based test to fail due to ambiguous networks.
        self.neutron._ports[
            self.neutron.port_with_sriov_resource_request['id']] = \
            copy.deepcopy(self.neutron.port_with_sriov_resource_request)
        self.neutron._ports[self.neutron.sriov_port['id']] = \
            copy.deepcopy(self.neutron.sriov_port)
        self.neutron._networks[
            self.neutron.network_2['id']] = self.neutron.network_2
        self.neutron._subnets[
            self.neutron.subnet_2['id']] = self.neutron.subnet_2
        macvtap = self.neutron.port_macvtap_with_resource_request
        self.neutron._ports[macvtap['id']] = copy.deepcopy(macvtap)

    def assertComputeAllocationMatchesFlavor(
            self, allocations, compute_rp_uuid, flavor):
        compute_allocations = allocations[compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

    def _create_server(self, flavor, networks, host=None):
        server_req = self._build_server(
            image_uuid='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
            flavor_id=flavor['id'],
            networks=networks,
            host=host)
        return self.api.post_server({'server': server_req})

    def _set_provider_inventories(self, rp_uuid, inventories):
        rp = self.placement.get(
            '/resource_providers/%s' % rp_uuid).body
        inventories['resource_provider_generation'] = rp['generation']
        return self._update_inventory(rp_uuid, inventories)

    def _create_ovs_networking_rp_tree(self, compute_rp_uuid):
        # we need uuid sentinel for the test to make pep8 happy but we need a
        # unique one per compute so here is some ugliness
        ovs_agent_rp_uuid = getattr(uuids, compute_rp_uuid + 'ovs agent')
        agent_rp_req = {
            "name": ovs_agent_rp_uuid,
            "uuid": ovs_agent_rp_uuid,
            "parent_provider_uuid": compute_rp_uuid
        }
        self.placement.post('/resource_providers',
                                body=agent_rp_req,
                                version='1.20')
        ovs_bridge_rp_uuid = getattr(uuids, ovs_agent_rp_uuid + 'ovs br')
        ovs_bridge_req = {
            "name": ovs_bridge_rp_uuid,
            "uuid": ovs_bridge_rp_uuid,
            "parent_provider_uuid": ovs_agent_rp_uuid
        }
        self.placement.post('/resource_providers',
                                body=ovs_bridge_req,
                                version='1.20')
        self.ovs_bridge_rp_per_host[compute_rp_uuid] = ovs_bridge_rp_uuid

        self._set_provider_inventories(
            ovs_bridge_rp_uuid,
            {"inventories": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: {"total": 10000},
                orc.NET_BW_EGR_KILOBIT_PER_SEC: {"total": 10000},
            }})

        self._create_trait(self.CUSTOM_VNIC_TYPE_NORMAL)
        self._create_trait(self.CUSTOM_PHYSNET2)

        self._set_provider_traits(
            ovs_bridge_rp_uuid,
            [self.CUSTOM_VNIC_TYPE_NORMAL, self.CUSTOM_PHYSNET2])

    def _create_pf_device_rp(
            self, device_rp_uuid, parent_rp_uuid, inventories, traits,
            device_rp_name=None):
        """Create a RP in placement for a physical function network device with
        traits and inventories.
        """

        if not device_rp_name:
            device_rp_name = device_rp_uuid

        sriov_pf_req = {
            "name": device_rp_name,
            "uuid": device_rp_uuid,
            "parent_provider_uuid": parent_rp_uuid
        }
        self.placement.post('/resource_providers',
                                body=sriov_pf_req,
                                version='1.20')

        self._set_provider_inventories(
            device_rp_uuid,
            {"inventories": inventories})

        for trait in traits:
            self._create_trait(trait)

        self._set_provider_traits(
            device_rp_uuid,
            traits)

    def _create_sriov_networking_rp_tree(self, hostname, compute_rp_uuid):
        # Create a matching RP tree in placement for the PCI devices added to
        # the passthrough_whitelist config during setUp() and PCI devices
        # present in the FakeDriverWithPciResources virt driver.
        #
        # * PF1 represents the PCI device 0000:01:00, it will be mapped to
        # physnet1 and it will have bandwidth inventory.
        # * PF2 represents the PCI device 0000:02:00, it will be mapped to
        # physnet2 it will have bandwidth inventory.
        # * PF3 represents the PCI device 0000:03:00 and, it will be mapped to
        # physnet2 but it will not have bandwidth inventory.
        self.sriov_dev_rp_per_host[compute_rp_uuid] = {}

        sriov_agent_rp_uuid = getattr(uuids, compute_rp_uuid + 'sriov agent')
        agent_rp_req = {
            "name": "%s:NIC Switch agent" % hostname,
            "uuid": sriov_agent_rp_uuid,
            "parent_provider_uuid": compute_rp_uuid
        }
        self.placement.post('/resource_providers',
                                body=agent_rp_req,
                                version='1.20')
        dev_rp_name_prefix = ("%s:NIC Switch agent:" % hostname)

        sriov_pf1_rp_uuid = getattr(uuids, sriov_agent_rp_uuid + 'PF1')
        self.sriov_dev_rp_per_host[
            compute_rp_uuid][self.PF1] = sriov_pf1_rp_uuid

        inventories = {
            orc.NET_BW_IGR_KILOBIT_PER_SEC: {"total": 100000},
            orc.NET_BW_EGR_KILOBIT_PER_SEC: {"total": 100000},
        }
        traits = [self.CUSTOM_VNIC_TYPE_DIRECT, self.CUSTOM_PHYSNET1]
        self._create_pf_device_rp(
            sriov_pf1_rp_uuid, sriov_agent_rp_uuid, inventories, traits,
            device_rp_name=dev_rp_name_prefix + "%s-ens1" % hostname)

        sriov_pf2_rp_uuid = getattr(uuids, sriov_agent_rp_uuid + 'PF2')
        self.sriov_dev_rp_per_host[
            compute_rp_uuid][self.PF2] = sriov_pf2_rp_uuid
        inventories = {
            orc.NET_BW_IGR_KILOBIT_PER_SEC: {"total": 100000},
            orc.NET_BW_EGR_KILOBIT_PER_SEC: {"total": 100000},
        }
        traits = [self.CUSTOM_VNIC_TYPE_DIRECT, self.CUSTOM_VNIC_TYPE_MACVTAP,
                  self.CUSTOM_PHYSNET2]
        self._create_pf_device_rp(
            sriov_pf2_rp_uuid, sriov_agent_rp_uuid, inventories, traits,
            device_rp_name=dev_rp_name_prefix + "%s-ens2" % hostname)

        sriov_pf3_rp_uuid = getattr(uuids, sriov_agent_rp_uuid + 'PF3')
        self.sriov_dev_rp_per_host[
            compute_rp_uuid][self.PF3] = sriov_pf3_rp_uuid
        inventories = {}
        traits = [self.CUSTOM_VNIC_TYPE_DIRECT, self.CUSTOM_PHYSNET2]
        self._create_pf_device_rp(
            sriov_pf3_rp_uuid, sriov_agent_rp_uuid, inventories, traits,
            device_rp_name=dev_rp_name_prefix + "%s-ens3" % hostname)

    def _create_networking_rp_tree(self, hostname, compute_rp_uuid):
        # let's simulate what the neutron would do
        self._create_ovs_networking_rp_tree(compute_rp_uuid)
        self._create_sriov_networking_rp_tree(hostname, compute_rp_uuid)

    def assertPortMatchesAllocation(self, port, allocations):
        port_request = port[constants.RESOURCE_REQUEST]['resources']
        for rc, amount in allocations.items():
            self.assertEqual(port_request[rc], amount,
                             'port %s requested %d %s '
                             'resources but got allocation %d' %
                             (port['id'], port_request[rc], rc,
                              amount))

    def _create_server_with_ports(self, *ports):
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[{'port': port['id']} for port in ports],
            host='host1')
        return self._wait_for_state_change(server, 'ACTIVE')

    def _check_allocation(
            self, server, compute_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, flavor, migration_uuid=None,
            source_compute_rp_uuid=None, new_flavor=None):

        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # if there is new_flavor then we either have an in progress resize or
        # a confirmed resize. In both cases the instance allocation should be
        # according to the new_flavor
        current_flavor = (new_flavor if new_flavor else flavor)

        # We expect one set of allocations for the compute resources on the
        # compute rp and two sets for the networking resources one on the ovs
        # bridge rp due to the qos_port resource request and one one the
        # sriov pf2 due to qos_sriov_port resource request
        self.assertEqual(3, len(allocations))
        self.assertComputeAllocationMatchesFlavor(
            allocations, compute_rp_uuid, current_flavor)
        ovs_allocations = allocations[
            self.ovs_bridge_rp_per_host[compute_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(qos_port, ovs_allocations)
        sriov_allocations = allocations[
            self.sriov_dev_rp_per_host[compute_rp_uuid][self.PF2]]['resources']
        self.assertPortMatchesAllocation(qos_sriov_port, sriov_allocations)

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding for the port having resource
        # request
        qos_binding_profile = updated_qos_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[compute_rp_uuid],
                         qos_binding_profile['allocation'])
        qos_sriov_binding_profile = updated_qos_sriov_port['binding:profile']
        self.assertEqual(self.sriov_dev_rp_per_host[compute_rp_uuid][self.PF2],
                         qos_sriov_binding_profile['allocation'])

        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

        if migration_uuid:
            migration_allocations = self.placement.get(
                '/allocations/%s' % migration_uuid).body['allocations']

            # We expect one set of allocations for the compute resources on the
            # compute rp and two sets for the networking resources one on the
            # ovs bridge rp due to the qos_port resource request and one one
            # the sriov pf2 due to qos_sriov_port resource request
            self.assertEqual(3, len(migration_allocations))
            self.assertComputeAllocationMatchesFlavor(
                migration_allocations, source_compute_rp_uuid, flavor)
            ovs_allocations = migration_allocations[
                self.ovs_bridge_rp_per_host[
                    source_compute_rp_uuid]]['resources']
            self.assertPortMatchesAllocation(qos_port, ovs_allocations)
            sriov_allocations = migration_allocations[
                self.sriov_dev_rp_per_host[
                    source_compute_rp_uuid][self.PF2]]['resources']
            self.assertPortMatchesAllocation(qos_sriov_port, sriov_allocations)

    def _delete_server_and_check_allocations(
            self, server, qos_port, qos_sriov_port):
        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding of the
        # ports that got allocation during the bind
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        binding_profile = updated_qos_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']
        binding_profile = updated_qos_sriov_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def _create_server_with_ports_and_check_allocation(
            self, non_qos_normal_port, qos_normal_port, qos_sriov_port):
        server = self._create_server_with_ports(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)
        # check that the server allocates from the current host properly
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)
        return server

    def _assert_pci_request_pf_device_name(self, server, device_name):
        ctxt = context.get_admin_context()
        pci_requests = objects.InstancePCIRequests.get_by_instance_uuid(
            ctxt, server['id'])
        self.assertEqual(1, len(pci_requests.requests))
        self.assertEqual(1, len(pci_requests.requests[0].spec))
        self.assertEqual(
            device_name,
            pci_requests.requests[0].spec[0]['parent_ifname'])


class UnsupportedPortResourceRequestBasedSchedulingTest(
        PortResourceRequestBasedSchedulingTestBase):
    """Tests for handling servers with ports having resource requests """

    def _add_resource_request_to_a_bound_port(self, port_id):
        # NOTE(gibi): self.neutron._ports contains a copy of each neutron port
        # defined on class level in the fixture. So modifying what is in the
        # _ports list is safe as it is re-created for each Neutron fixture
        # instance therefore for each individual test using that fixture.
        bound_port = self.neutron._ports[port_id]
        bound_port[constants.RESOURCE_REQUEST] = (
            self.neutron.port_with_resource_request[
                constants.RESOURCE_REQUEST])

    def test_interface_attach_with_port_resource_request(self):
        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # try to add a port with resource request
        post = {
            'interfaceAttachment': {
                'port_id': self.neutron.port_with_resource_request['id']
        }}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.attach_interface,
                               server['id'], post)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Attaching interfaces with QoS policy is '
                      'not supported for instance',
                      six.text_type(ex))

    @mock.patch('nova.tests.fixtures.NeutronFixture.create_port')
    def test_interface_attach_with_network_create_port_has_resource_request(
            self, mock_neutron_create_port):
        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # the interfaceAttach operation below will result in a new port being
        # created in the network that is attached. Make sure that neutron
        # returns a port that has resource request.
        mock_neutron_create_port.return_value = (
            {'port': copy.deepcopy(self.neutron.port_with_resource_request)})

        # try to attach a network
        post = {
            'interfaceAttachment': {
                'net_id': self.neutron.network_1['id']
        }}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.attach_interface,
                               server['id'], post)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Using networks with QoS policy is not supported for '
                      'instance',
                      six.text_type(ex))

    @mock.patch('nova.tests.fixtures.NeutronFixture.create_port')
    def test_create_server_with_network_create_port_has_resource_request(
            self, mock_neutron_create_port):
        # the server create operation below will result in a new port being
        # created in the network. Make sure that neutron returns a port that
        # has resource request.
        mock_neutron_create_port.return_value = (
            {'port': copy.deepcopy(self.neutron.port_with_resource_request)})

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'uuid': self.neutron.network_1['id']}])
        server = self._wait_for_state_change(server, 'ERROR')

        self.assertEqual(500, server['fault']['code'])
        self.assertIn('Failed to allocate the network',
                      server['fault']['message'])

    def test_create_server_with_port_resource_request_old_microversion(self):

        # NOTE(gibi): 2.71 is the last microversion where nova does not support
        # this kind of create server
        self.api.microversion = '2.71'
        ex = self.assertRaises(
            client.OpenStackApiException, self._create_server,
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_with_resource_request['id']}])

        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            "Creating servers with ports having resource requests, like a "
            "port with a QoS minimum bandwidth policy, is not supported "
            "until microversion 2.72.",
            six.text_type(ex))

    def test_live_migrate_server_with_port_resource_request_old_version(
            self):
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # We need to simulate that the above server has a port that has
        # resource request; we cannot boot with such a port but legacy servers
        # can exist with such a port.
        self._add_resource_request_to_a_bound_port(self.neutron.port_1['id'])

        post = {
            'os-migrateLive': {
                'host': None,
                'block_migration': False,
            }
        }
        with mock.patch(
            "nova.objects.service.get_minimum_version_all_cells",
            return_value=48,
        ):
            ex = self.assertRaises(
                client.OpenStackApiException,
                self.api.post_server_action, server['id'], post)

        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            "The os-migrateLive action on a server with ports having resource "
            "requests, like a port with a QoS minimum bandwidth policy, is "
            "not supported by this cluster right now",
            six.text_type(ex))
        self.assertIn(
            "The os-migrateLive action on a server with ports having resource "
            "requests, like a port with a QoS minimum bandwidth policy, is "
            "not supported until every nova-compute is upgraded to Ussuri",
            self.stdlog.logger.output)

    def test_evacuate_server_with_port_resource_request_old_version(
            self):
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # We need to simulate that the above server has a port that has
        # resource request; we cannot boot with such a port but legacy servers
        # can exist with such a port.
        self._add_resource_request_to_a_bound_port(self.neutron.port_1['id'])

        with mock.patch(
            "nova.objects.service.get_minimum_version_all_cells",
            return_value=48,
        ):
            ex = self.assertRaises(
                client.OpenStackApiException,
                self.api.post_server_action, server['id'], {'evacuate': {}})

        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            "The evacuate action on a server with ports having resource "
            "requests, like a port with a QoS minimum bandwidth policy, is "
            "not supported by this cluster right now",
            six.text_type(ex))
        self.assertIn(
            "The evacuate action on a server with ports having resource "
            "requests, like a port with a QoS minimum bandwidth policy, is "
            "not supported until every nova-compute is upgraded to Ussuri",
            self.stdlog.logger.output)

    def test_unshelve_offloaded_server_with_port_resource_request_old_version(
            self):
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})

        # We need to simulate that the above server has a port that has
        # resource request; we cannot boot with such a port but legacy servers
        # can exist with such a port.
        self._add_resource_request_to_a_bound_port(self.neutron.port_1['id'])

        with mock.patch(
            "nova.objects.service.get_minimum_version_all_cells",
            return_value=48,
        ):
            ex = self.assertRaises(
                client.OpenStackApiException,
                self.api.post_server_action, server['id'], {'unshelve': None})

        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            "The unshelve action on a server with ports having resource "
            "requests, like a port with a QoS minimum bandwidth policy, is "
            "not supported by this cluster right now",
            six.text_type(ex))
        self.assertIn(
            "The unshelve action on a server with ports having resource "
            "requests, like a port with a QoS minimum bandwidth policy, is "
            "not supported until every nova-compute is upgraded to Ussuri",
            self.stdlog.logger.output)

    def test_unshelve_not_offloaded_server_with_port_resource_request(
            self):
        """If the server is not offloaded then unshelving does not cause a new
        resource allocation therefore having port resource request is
        irrelevant. This test asserts that such unshelve request is not
        rejected.
        """
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': self.neutron.port_1['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        # avoid automatic shelve offloading
        self.flags(shelved_offload_time=-1)
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(server, {'status': 'SHELVED'})

        # We need to simulate that the above server has a port that has
        # resource request; we cannot boot with such a port but legacy servers
        # can exist with such a port.
        self._add_resource_request_to_a_bound_port(self.neutron.port_1['id'])

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_state_change(server, 'ACTIVE')


class NonAdminUnsupportedPortResourceRequestBasedSchedulingTest(
        UnsupportedPortResourceRequestBasedSchedulingTest):

    def setUp(self):
        super(
            NonAdminUnsupportedPortResourceRequestBasedSchedulingTest,
            self).setUp()
        # switch to non admin api
        self.api = self.api_fixture.api
        self.api.microversion = self.microversion

        # allow non-admin to call the operations
        self.policy.set_rules({
            'os_compute_api:servers:create': '@',
            'os_compute_api:servers:create:attach_network': '@',
            'os_compute_api:servers:show': '@',
            'os_compute_api:os-attach-interfaces': '@',
            'os_compute_api:os-attach-interfaces:create': '@',
            'os_compute_api:os-shelve:shelve': '@',
            'os_compute_api:os-shelve:unshelve': '@',
            'os_compute_api:os-migrate-server:migrate_live': '@',
            'os_compute_api:os-evacuate': '@',
        })


class PortResourceRequestBasedSchedulingTest(
        PortResourceRequestBasedSchedulingTestBase):
    """Tests creating a server with a pre-existing port that has a resource
    request for a QoS minimum bandwidth policy.
    """

    def test_boot_server_with_two_ports_one_having_resource_request(self):
        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': non_qos_port['id']},
                      {'port': qos_port['id']}])
        server = self._wait_for_state_change(server, 'ACTIVE')
        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the ovs bridge
        # rp due to the qos_port resource request
        self.assertEqual(2, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)
        network_allocations = allocations[
            self.ovs_bridge_rp_per_host[self.compute1_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(qos_port, network_allocations)

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding for the port having resource
        # request
        qos_binding_profile = updated_qos_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[self.compute1_rp_uuid],
                         qos_binding_profile['allocation'])

        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding of the
        # port that got allocation during the bind
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        binding_profile = updated_qos_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def test_one_ovs_one_sriov_port(self):
        ovs_port = self.neutron.port_with_resource_request
        sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server(flavor=self.flavor_with_group_policy,
                                     networks=[{'port': ovs_port['id']},
                                               {'port': sriov_port['id']}])

        server = self._wait_for_state_change(server, 'ACTIVE')

        ovs_port = self.neutron.show_port(ovs_port['id'])['port']
        sriov_port = self.neutron.show_port(sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the ovs bridge
        # rp and on the sriov PF rp.
        self.assertEqual(3, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor_with_group_policy)

        ovs_allocations = allocations[
            self.ovs_bridge_rp_per_host[self.compute1_rp_uuid]]['resources']
        sriov_allocations = allocations[
            self.sriov_dev_rp_per_host[
                self.compute1_rp_uuid][self.PF2]]['resources']

        self.assertPortMatchesAllocation(ovs_port, ovs_allocations)
        self.assertPortMatchesAllocation(sriov_port, sriov_allocations)

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding for the port having resource
        # request
        ovs_binding = ovs_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[self.compute1_rp_uuid],
                         ovs_binding['allocation'])
        sriov_binding = sriov_port['binding:profile']
        self.assertEqual(
            self.sriov_dev_rp_per_host[self.compute1_rp_uuid][self.PF2],
            sriov_binding['allocation'])

    def test_interface_detach_with_port_with_bandwidth_request(self):
        port = self.neutron.port_with_resource_request

        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])
        self._wait_for_state_change(server, 'ACTIVE')

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the ovs bridge
        # rp due to the port resource request
        self.assertEqual(2, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)

        network_allocations = allocations[
            self.ovs_bridge_rp_per_host[self.compute1_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(port, network_allocations)

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding for the port having resource
        # request
        updated_port = self.neutron.show_port(port['id'])['port']
        binding_profile = updated_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[self.compute1_rp_uuid],
                         binding_profile['allocation'])

        self.api.detach_interface(
            server['id'], self.neutron.port_with_resource_request['id'])

        fake_notifier.wait_for_versioned_notifications(
            'instance.interface_detach.end')

        updated_port = self.neutron.show_port(
            self.neutron.port_with_resource_request['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect that the port related resource allocations are removed
        self.assertEqual(1, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)

        # We expect that the allocation is removed from the port too
        binding_profile = updated_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def test_delete_bound_port_in_neutron_with_resource_request(self):
        """Neutron sends a network-vif-deleted os-server-external-events
        notification to nova when a bound port is deleted. Nova detaches the
        vif from the server. If the port had a resource allocation then that
        allocation is leaked. This test makes sure that 1) an ERROR is logged
        when the leak happens. 2) the leaked resource is reclaimed when the
        server is deleted.
        """
        port = self.neutron.port_with_resource_request

        # create a server
        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])
        server = self._wait_for_state_change(server, 'ACTIVE')

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the ovs bridge
        # rp due to the port resource request
        self.assertEqual(2, len(allocations))
        compute_allocations = allocations[self.compute1_rp_uuid]['resources']
        network_allocations = allocations[
            self.ovs_bridge_rp_per_host[self.compute1_rp_uuid]]['resources']

        self.assertEqual(self._resources_from_flavor(self.flavor),
                         compute_allocations)
        self.assertPortMatchesAllocation(port, network_allocations)

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding for the port having resource
        # request
        updated_port = self.neutron.show_port(port['id'])['port']
        binding_profile = updated_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[self.compute1_rp_uuid],
                         binding_profile['allocation'])

        # neutron is faked in the functional test so this test just sends in
        # a os-server-external-events notification to trigger the
        # detach + ERROR log.
        events = {
            "events": [
                {
                    "name": "network-vif-deleted",
                    "server_uuid": server['id'],
                    "tag": port['id'],
                }
            ]
        }
        response = self.api.api_post('/os-server-external-events', events).body
        self.assertEqual(200, response['events'][0]['code'])

        port_rp_uuid = self.ovs_bridge_rp_per_host[self.compute1_rp_uuid]

        # 1) Nova logs an ERROR about the leak
        self._wait_for_log(
            'ERROR [nova.compute.manager] The bound port %(port_id)s is '
            'deleted in Neutron but the resource allocation on the resource '
            'provider %(rp_uuid)s is leaked until the server %(server_uuid)s '
            'is deleted.'
            % {'port_id': port['id'],
               'rp_uuid': port_rp_uuid,
               'server_uuid': server['id']})

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # Nova leaks the port allocation so the server still has the same
        # allocation before the port delete.
        self.assertEqual(2, len(allocations))
        compute_allocations = allocations[self.compute1_rp_uuid]['resources']
        network_allocations = allocations[port_rp_uuid]['resources']

        self.assertEqual(self._resources_from_flavor(self.flavor),
                         compute_allocations)
        self.assertPortMatchesAllocation(port, network_allocations)

        # 2) Also nova will reclaim the leaked resource during the server
        # delete
        self._delete_and_check_allocations(server)

    def test_two_sriov_ports_one_with_request_two_available_pfs(self):
        """Verify that the port's bandwidth allocated from the same PF as
        the allocated VF.

        One compute host:
        * PF1 (0000:01:00) is configured for physnet1
        * PF2 (0000:02:00) is configured for physnet2, with 1 VF and bandwidth
          inventory
        * PF3 (0000:03:00) is configured for physnet2, with 1 VF but without
          bandwidth inventory

        One instance will be booted with two neutron ports, both ports
        requested to be connected to physnet2. One port has resource request
        the other does not have resource request. The port having the resource
        request cannot be allocated to PF3 and PF1 while the other port that
        does not have resource request can be allocated to PF2 or PF3.

        For the detailed compute host config see the FakeDriverWithPciResources
        class. For the necessary passthrough_whitelist config see the setUp of
        the PortResourceRequestBasedSchedulingTestBase class.
        """

        sriov_port = self.neutron.sriov_port
        sriov_port_with_res_req = self.neutron.port_with_sriov_resource_request
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[
                {'port': sriov_port_with_res_req['id']},
                {'port': sriov_port['id']}])

        server = self._wait_for_state_change(server, 'ACTIVE')

        sriov_port = self.neutron.show_port(sriov_port['id'])['port']
        sriov_port_with_res_req = self.neutron.show_port(
            sriov_port_with_res_req['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the sriov PF2
        # rp.
        self.assertEqual(2, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor_with_group_policy)

        sriov_allocations = allocations[
            self.sriov_dev_rp_per_host[
                self.compute1_rp_uuid][self.PF2]]['resources']
        self.assertPortMatchesAllocation(
            sriov_port_with_res_req, sriov_allocations)

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding for the port having resource
        # request
        sriov_with_req_binding = sriov_port_with_res_req['binding:profile']
        self.assertEqual(
            self.sriov_dev_rp_per_host[self.compute1_rp_uuid][self.PF2],
            sriov_with_req_binding['allocation'])
        # and the port without resource request does not have allocation
        sriov_binding = sriov_port['binding:profile']
        self.assertNotIn('allocation', sriov_binding)

        # We expect that the selected PCI device matches with the RP from
        # where the bandwidth is allocated from. The bandwidth is allocated
        # from 0000:02:00 (PF2) so the PCI device should be a VF of that PF
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF2_VF1,
            sriov_with_req_binding['pci_slot'])
        # But also the port that has no resource request still gets a pci slot
        # allocated. The 0000:02:00 has no more VF available but 0000:03:00 has
        # one VF available and that PF is also on physnet2
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF3_VF1,
            sriov_binding['pci_slot'])

    def test_one_sriov_port_no_vf_and_bandwidth_available_on_the_same_pf(self):
        """Verify that if there is no PF that both provides bandwidth and VFs
        then the boot will fail.
        """

        # boot a server with a single sriov port that has no resource request
        sriov_port = self.neutron.sriov_port
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[{'port': sriov_port['id']}])

        self._wait_for_state_change(server, 'ACTIVE')
        sriov_port = self.neutron.show_port(sriov_port['id'])['port']
        sriov_binding = sriov_port['binding:profile']

        # We expect that this consume the last available VF from the PF2
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF2_VF1,
            sriov_binding['pci_slot'])

        # Now boot a second server with a port that has resource request
        # At this point PF2 has available bandwidth but no available VF
        # and PF3 has available VF but no available bandwidth so we expect
        # the boot to fail.

        sriov_port_with_res_req = self.neutron.port_with_sriov_resource_request
        server = self._create_server(
            flavor=self.flavor_with_group_policy,
            networks=[{'port': sriov_port_with_res_req['id']}])

        # NOTE(gibi): It should be NoValidHost in an ideal world but that would
        # require the scheduler to detect the situation instead of the pci
        # claim. However that is pretty hard as the scheduler does not know
        # anything about allocation candidates (e.g. that the only candidate
        # for the port in this case is PF2) it see the whole host as a
        # candidate and in our host there is available VF for the request even
        # if that is on the wrong PF.
        server = self._wait_for_state_change(server, 'ERROR')
        self.assertIn(
            'Exceeded maximum number of retries. Exhausted all hosts '
            'available for retrying build failures for instance',
            server['fault']['message'])

    def test_sriov_macvtap_port_with_resource_request(self):
        """Verify that vnic type macvtap is also supported"""

        port = self.neutron.port_macvtap_with_resource_request

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])

        server = self._wait_for_state_change(server, 'ACTIVE')

        port = self.neutron.show_port(port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the sriov PF2
        # rp.
        self.assertEqual(2, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor)

        sriov_allocations = allocations[self.sriov_dev_rp_per_host[
                self.compute1_rp_uuid][self.PF2]]['resources']
        self.assertPortMatchesAllocation(
            port, sriov_allocations)

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding for the port having resource
        # request
        port_binding = port['binding:profile']
        self.assertEqual(
            self.sriov_dev_rp_per_host[self.compute1_rp_uuid][self.PF2],
            port_binding['allocation'])

        # We expect that the selected PCI device matches with the RP from
        # where the bandwidth is allocated from. The bandwidth is allocated
        # from 0000:02:00 (PF2) so the PCI device should be a VF of that PF
        self.assertEqual(
            fake.FakeDriverWithPciResources.PCI_ADDR_PF2_VF1,
            port_binding['pci_slot'])


class ServerMoveWithPortResourceRequestTest(
        PortResourceRequestBasedSchedulingTestBase):

    def setUp(self):
        # Use our custom weigher defined above to make sure that we have
        # a predictable host order in the alternate list returned by the
        # scheduler for migration.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super(ServerMoveWithPortResourceRequestTest, self).setUp()
        self.compute2 = self._start_compute('host2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

        # create a bigger flavor to use in resize test
        self.flavor_with_group_policy_bigger = self.admin_api.post_flavor(
            {'flavor': {
                'ram': self.flavor_with_group_policy['ram'],
                'vcpus': self.flavor_with_group_policy['vcpus'],
                'name': self.flavor_with_group_policy['name'] + '+',
                'disk': self.flavor_with_group_policy['disk'] + 1,
            }})
        self.admin_api.post_extra_spec(
            self.flavor_with_group_policy_bigger['id'],
            {'extra_specs': {'group_policy': 'isolate'}})

    def test_migrate_server_with_qos_port_old_dest_compute_no_alternate(self):
        """Create a situation where the only migration target host returned
        by the scheduler is too old and therefore the migration fails.
        """
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        orig_get_service = objects.Service.get_by_host_and_binary

        def fake_get_service(context, host, binary):
            # host2 is the only migration target, let's make it too old so the
            # migration will fail
            if host == 'host2':
                service = orig_get_service(context, host, binary)
                service.version = 38
                return service
            else:
                return orig_get_service(context, host, binary)

        with mock.patch(
                'nova.objects.Service.get_by_host_and_binary',
                side_effect=fake_get_service):

            self.api.post_server_action(server['id'], {'migrate': None},
                                        check_response_status=[202])
            self._wait_for_server_parameter(server,
                                            {'OS-EXT-STS:task_state': None})

        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'NoValidHost')

        # check that the server still allocates from the original host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # but the migration allocation is gone
        migration_uuid = self.get_migration_uuid_for_instance(server['id'])
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_migrate_server_with_qos_port_old_dest_compute_alternate(self):
        """Create a situation where the first migration target host returned
        by the scheduler is too old and therefore the second host is selected
        by the MigrationTask.
        """
        self._start_compute('host3')
        compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', compute3_rp_uuid)

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        orig_get_service = objects.Service.get_by_host_and_binary

        def fake_get_service(context, host, binary):
            # host2 is the first migration target, let's make it too old so the
            # migration will skip this host
            if host == 'host2':
                service = orig_get_service(context, host, binary)
                service.version = 38
                return service
            # host3 is the second migration target, let's make it new enough so
            # the migration task will choose this host
            elif host == 'host3':
                service = orig_get_service(context, host, binary)
                service.version = 39
                return service
            else:
                return orig_get_service(context, host, binary)

        with mock.patch(
                'nova.objects.Service.get_by_host_and_binary',
                side_effect=fake_get_service):

            self.api.post_server_action(server['id'], {'migrate': None})
            self._wait_for_state_change(server, 'VERIFY_RESIZE')

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # check that server allocates from host3 and the migration allocates
        # from host1
        self._check_allocation(
            server, compute3_rp_uuid, non_qos_normal_port, qos_normal_port,
            qos_sriov_port, self.flavor_with_group_policy, migration_uuid,
            source_compute_rp_uuid=self.compute1_rp_uuid)

        self._confirm_resize(server)
        # check that allocation is still OK
        self._check_allocation(
            server, compute3_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)
        # but the migration allocation is gone
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def _test_resize_or_migrate_server_with_qos_ports(self, new_flavor=None):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        if new_flavor:
            self.api_fixture.api.post_server_action(
                server['id'], {'resize': {"flavorRef": new_flavor['id']}})
        else:
            self.api.post_server_action(server['id'], {'migrate': None})

        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # check that server allocates from the new host properly
        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy,
            migration_uuid, source_compute_rp_uuid=self.compute1_rp_uuid,
            new_flavor=new_flavor)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        self._confirm_resize(server)

        # check that allocation is still OK
        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy,
            new_flavor=new_flavor)
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_migrate_server_with_qos_ports(self):
        self._test_resize_or_migrate_server_with_qos_ports()

    def test_resize_server_with_qos_ports(self):
        self._test_resize_or_migrate_server_with_qos_ports(
            new_flavor=self.flavor_with_group_policy_bigger)

    def _test_resize_or_migrate_revert_with_qos_ports(self, new_flavor=None):
        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        if new_flavor:
            self.api_fixture.api.post_server_action(
                server['id'], {'resize': {"flavorRef": new_flavor['id']}})
        else:
            self.api.post_server_action(server['id'], {'migrate': None})

        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # check that server allocates from the new host properly
        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy, migration_uuid,
            source_compute_rp_uuid=self.compute1_rp_uuid,
            new_flavor=new_flavor)

        self.api.post_server_action(server['id'], {'revertResize': None})
        self._wait_for_state_change(server, 'ACTIVE')

        # check that allocation is moved back to the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

        # check that the target host allocation is cleaned up.
        self.assertRequestMatchesUsage(
            {'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0,
             'NET_BW_IGR_KILOBIT_PER_SEC': 0, 'NET_BW_EGR_KILOBIT_PER_SEC': 0},
            self.compute2_rp_uuid)
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_port, qos_sriov_port)

    def test_migrate_revert_with_qos_ports(self):
        self._test_resize_or_migrate_revert_with_qos_ports()

    def test_resize_revert_with_qos_ports(self):
        self._test_resize_or_migrate_revert_with_qos_ports(
            new_flavor=self.flavor_with_group_policy_bigger)

    def _test_resize_or_migrate_server_with_qos_port_reschedule_success(
            self, new_flavor=None):
        self._start_compute('host3')
        compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', compute3_rp_uuid)

        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # Yes this isn't great in a functional test, but it's simple.
        original_prep_resize = compute_manager.ComputeManager._prep_resize

        prep_resize_calls = []

        def fake_prep_resize(_self, *args, **kwargs):
            # Make the first prep_resize fail and the rest passing through
            # the original _prep_resize call
            if not prep_resize_calls:
                prep_resize_calls.append(_self.host)
                raise test.TestingException('Simulated prep_resize failure.')
            prep_resize_calls.append(_self.host)
            original_prep_resize(_self, *args, **kwargs)

        # The patched compute manager will raise from _prep_resize on the
        # first host of the migration. Then the migration
        # is reschedule on the other host where it will succeed
        with mock.patch.object(
                compute_manager.ComputeManager, '_prep_resize',
                new=fake_prep_resize):
            if new_flavor:
                self.api_fixture.api.post_server_action(
                    server['id'], {'resize': {"flavorRef": new_flavor['id']}})
            else:
                self.api.post_server_action(server['id'], {'migrate': None})
            self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # ensure that resize is tried on two hosts, so we had a re-schedule
        self.assertEqual(['host2', 'host3'], prep_resize_calls)

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # check that server allocates from the final host properly while
        # the migration holds the allocation on the source host
        self._check_allocation(
            server, compute3_rp_uuid, non_qos_port, qos_port, qos_sriov_port,
            self.flavor_with_group_policy, migration_uuid,
            source_compute_rp_uuid=self.compute1_rp_uuid,
            new_flavor=new_flavor)

        self._assert_pci_request_pf_device_name(server, 'host3-ens2')

        self._confirm_resize(server)

        # check that allocation is still OK
        self._check_allocation(
            server, compute3_rp_uuid, non_qos_port, qos_port, qos_sriov_port,
            self.flavor_with_group_policy, new_flavor=new_flavor)
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        self._delete_server_and_check_allocations(
            server, qos_port, qos_sriov_port)

    def test_migrate_server_with_qos_port_reschedule_success(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_success()

    def test_resize_server_with_qos_port_reschedule_success(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_success(
            new_flavor=self.flavor_with_group_policy_bigger)

    def _test_resize_or_migrate_server_with_qos_port_reschedule_failure(
            self, new_flavor=None):
        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # The patched compute manager on host2 will raise from _prep_resize.
        # Then the migration is reschedule but there is no other host to
        # choose from.
        with mock.patch.object(
                compute_manager.ComputeManager, '_prep_resize',
                side_effect=test.TestingException(
                    'Simulated prep_resize failure.')):
            if new_flavor:
                self.api_fixture.api.post_server_action(
                    server['id'], {'resize': {"flavorRef": new_flavor['id']}})
            else:
                self.api.post_server_action(server['id'], {'migrate': None})
            self._wait_for_server_parameter(server,
                {'OS-EXT-SRV-ATTR:host': 'host1',
                 'status': 'ERROR'})
            self._wait_for_migration_status(server, ['error'])

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # as the migration is failed we expect that the migration allocation
        # is deleted
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        # and the instance allocates from the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

    def test_migrate_server_with_qos_port_reschedule_failure(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_failure()

    def test_resize_server_with_qos_port_reschedule_failure(self):
        self._test_resize_or_migrate_server_with_qos_port_reschedule_failure(
            new_flavor=self.flavor_with_group_policy_bigger)

    def test_migrate_server_with_qos_port_pci_update_fail_not_reschedule(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is migrated to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        self._start_compute('host3')
        compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', compute3_rp_uuid)

        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # The compute manager on host2 will raise from
        # update_pci_request_spec_with_allocated_interface_name which will
        # intentionally not trigger a re-schedule even if there is host3 as an
        # alternate.
        self.api.post_server_action(server['id'], {'migrate': None})
        server = self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             # Note that we have to wait for the task_state to be reverted
             # to None since that happens after the fault is recorded.
             'OS-EXT-STS:task_state': None,
             'status': 'ERROR'})
        self._wait_for_migration_status(server, ['error'])

        self.assertIn(
            'Build of instance %s aborted' % server['id'],
            server['fault']['message'])

        self._wait_for_action_fail_completion(
            server, instance_actions.MIGRATE, 'compute_prep_resize')

        fake_notifier.wait_for_versioned_notifications(
            'instance.resize_prep.end')
        fake_notifier.wait_for_versioned_notifications(
            'compute.exception')

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # as the migration is failed we expect that the migration allocation
        # is deleted
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        # and the instance allocates from the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

    def test_migrate_server_with_qos_port_pinned_compute_rpc(self):
        # Pin the compute rpc version to 5.1 to test what happens if
        # resize RPC is called without RequestSpec.
        # It is OK to set this after the nova services has started in setUp()
        # as no compute rpc call is made so far.
        self.flags(compute='5.1', group='upgrade_levels')

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request

        server = self._create_server_with_ports(
            non_qos_normal_port, qos_normal_port)

        # This migration expected to fail as the old RPC does not provide
        # enough information to do a proper port binding on the target host.
        # The MigrationTask in the conductor checks that the RPC is new enough
        # for this request for each possible destination provided by the
        # scheduler and skips the old hosts. The actual response will be a 202
        # so we have to wait for the failed instance action event.
        self.api.post_server_action(server['id'], {'migrate': None})
        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'NoValidHost')

        # The migration is put into error
        self._wait_for_migration_status(server, ['error'])

        # The migration is rejected so the instance remains on the source host
        server = self.api.get_server(server['id'])
        self.assertEqual('ACTIVE', server['status'])
        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])

        migration_uuid = self.get_migration_uuid_for_instance(server['id'])

        # The migration allocation is deleted
        migration_allocations = self.placement.get(
            '/allocations/%s' % migration_uuid).body['allocations']
        self.assertEqual({}, migration_allocations)

        # The instance is still allocated from the source host
        updated_non_qos_port = self.neutron.show_port(
            non_qos_normal_port['id'])['port']
        updated_qos_port = self.neutron.show_port(
            qos_normal_port['id'])['port']
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the ovs
        # bridge rp due to the qos_port resource request
        self.assertEqual(2, len(allocations))
        self.assertComputeAllocationMatchesFlavor(
            allocations, self.compute1_rp_uuid, self.flavor_with_group_policy)
        ovs_allocations = allocations[
            self.ovs_bridge_rp_per_host[self.compute1_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(qos_normal_port, ovs_allocations)

        # binding:profile still points to the networking RP on the source host
        qos_binding_profile = updated_qos_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[self.compute1_rp_uuid],
                         qos_binding_profile['allocation'])
        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

    def _check_allocation_during_evacuate(
            self, server, flavor, source_compute_rp_uuid, dest_compute_rp_uuid,
            non_qos_port, qos_port, qos_sriov_port):
        # evacuate is the only case when the same consumer has allocation from
        # two different RP trees so we need special checks

        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect two sets of allocations. One set for the source compute
        # and one set for the dest compute. Each set we expect 3 allocations
        # one for the compute RP according to the flavor, one for the ovs port
        # and one for the SRIOV port.
        self.assertEqual(6, len(allocations), allocations)

        # 1. source compute allocation
        compute_allocations = allocations[source_compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

        # 2. source ovs allocation
        ovs_allocations = allocations[
            self.ovs_bridge_rp_per_host[source_compute_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(qos_port, ovs_allocations)

        # 3. source sriov allocation
        sriov_allocations = allocations[
            self.sriov_dev_rp_per_host[
                source_compute_rp_uuid][self.PF2]]['resources']
        self.assertPortMatchesAllocation(qos_sriov_port, sriov_allocations)

        # 4. dest compute allocation
        compute_allocations = allocations[dest_compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

        # 5. dest ovs allocation
        ovs_allocations = allocations[
            self.ovs_bridge_rp_per_host[dest_compute_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(qos_port, ovs_allocations)

        # 6. dest SRIOV allocation
        sriov_allocations = allocations[
            self.sriov_dev_rp_per_host[
                dest_compute_rp_uuid][self.PF2]]['resources']
        self.assertPortMatchesAllocation(qos_sriov_port, sriov_allocations)

        # the qos ports should have their binding pointing to the RPs in the
        # dest compute RP tree
        qos_binding_profile = updated_qos_port['binding:profile']
        self.assertEqual(
            self.ovs_bridge_rp_per_host[dest_compute_rp_uuid],
            qos_binding_profile['allocation'])

        qos_sriov_binding_profile = updated_qos_sriov_port['binding:profile']
        self.assertEqual(
            self.sriov_dev_rp_per_host[dest_compute_rp_uuid][self.PF2],
            qos_sriov_binding_profile['allocation'])

        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

    def _check_allocation_after_evacuation_source_recovered(
            self, server, flavor, dest_compute_rp_uuid, non_qos_port,
            qos_port, qos_sriov_port):
        # check that source allocation is cleaned up and the dest allocation
        # and the port bindings are not touched.

        updated_non_qos_port = self.neutron.show_port(
            non_qos_port['id'])['port']
        updated_qos_port = self.neutron.show_port(qos_port['id'])['port']
        updated_qos_sriov_port = self.neutron.show_port(
            qos_sriov_port['id'])['port']

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        self.assertEqual(3, len(allocations), allocations)

        # 1. dest compute allocation
        compute_allocations = allocations[dest_compute_rp_uuid]['resources']
        self.assertEqual(
            self._resources_from_flavor(flavor),
            compute_allocations)

        # 2. dest ovs allocation
        ovs_allocations = allocations[
            self.ovs_bridge_rp_per_host[dest_compute_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(qos_port, ovs_allocations)

        # 3. dest SRIOV allocation
        sriov_allocations = allocations[
            self.sriov_dev_rp_per_host[
                dest_compute_rp_uuid][self.PF2]]['resources']
        self.assertPortMatchesAllocation(qos_sriov_port, sriov_allocations)

        # the qos ports should have their binding pointing to the RPs in the
        # dest compute RP tree
        qos_binding_profile = updated_qos_port['binding:profile']
        self.assertEqual(
            self.ovs_bridge_rp_per_host[dest_compute_rp_uuid],
            qos_binding_profile['allocation'])

        qos_sriov_binding_profile = updated_qos_sriov_port['binding:profile']
        self.assertEqual(
            self.sriov_dev_rp_per_host[dest_compute_rp_uuid][self.PF2],
            qos_sriov_binding_profile['allocation'])

        # And we expect not to have any allocation set in the port binding for
        # the port that doesn't have resource request
        self.assertEqual({}, updated_non_qos_port['binding:profile'])

    def test_evacuate_with_qos_port(self, host=None):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # force source compute down
        self.compute1.stop()
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'true'})

        req = {'evacuate': {}}
        if host:
            req['evacuate']['host'] = host

        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': 'host2',
             'status': 'ACTIVE'})

        self._check_allocation_during_evacuate(
            server, self.flavor_with_group_policy, self.compute1_rp_uuid,
            self.compute2_rp_uuid, non_qos_normal_port, qos_normal_port,
            qos_sriov_port)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        # recover source compute
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'false'})
        self.compute1 = self.restart_compute_service(self.compute1)

        # check that source allocation is cleaned up and the dest allocation
        # and the port bindings are not touched.
        self._check_allocation_after_evacuation_source_recovered(
            server, self.flavor_with_group_policy, self.compute2_rp_uuid,
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_evacuate_with_target_host_with_qos_port(self):
        self.test_evacuate_with_qos_port(host='host2')

    def test_evacuate_with_qos_port_fails_recover_source_compute(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # force source compute down
        self.compute1.stop()
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'true'})

        with mock.patch(
                'nova.compute.resource_tracker.ResourceTracker.rebuild_claim',
                side_effect=exception.ComputeResourcesUnavailable(
                    reason='test evacuate failure')):
            req = {'evacuate': {}}
            self.api.post_server_action(server['id'], req)
            # Evacuate does not have reschedule loop so evacuate expected to
            # simply fail and the server remains on the source host
            server = self._wait_for_server_parameter(server,
                {'OS-EXT-SRV-ATTR:host': 'host1',
                 'status': 'ACTIVE',
                 'OS-EXT-STS:task_state': None})

        self._wait_for_migration_status(server, ['failed'])

        # As evacuation failed the resource allocation should be untouched
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # recover source compute
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'false'})
        self.compute1 = self.restart_compute_service(self.compute1)

        # check again that even after source host recovery the source
        # allocation is intact
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_evacuate_with_qos_port_pci_update_fail(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is evacuated to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        non_qos_port = self.neutron.port_1
        qos_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_port, qos_port, qos_sriov_port)

        # force source compute down
        self.compute1.stop()
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'true'})

        # The compute manager on host2 will raise from
        # update_pci_request_spec_with_allocated_interface_name
        self.api.post_server_action(server['id'], {'evacuate': {}})
        server = self._wait_for_server_parameter(server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'OS-EXT-STS:task_state': None,
             'status': 'ERROR'})
        self._wait_for_migration_status(server, ['failed'])

        self.assertIn(
            'does not have a properly formatted name',
            server['fault']['message'])

        self._wait_for_action_fail_completion(
            server, instance_actions.EVACUATE, 'compute_rebuild_instance')

        fake_notifier.wait_for_versioned_notifications(
            'instance.rebuild.error')
        fake_notifier.wait_for_versioned_notifications(
            'compute.exception')

        # and the instance allocates from the source host
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_port, qos_port,
            qos_sriov_port, self.flavor_with_group_policy)

    def test_live_migrate_with_qos_port(self, host=None):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        self.api.post_server_action(
            server['id'],
            {
                'os-migrateLive': {
                    'host': host,
                    'block_migration': 'auto'
                }
            }
        )

        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host2',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_live_migrate_with_qos_port_with_target_host(self):
        self.test_live_migrate_with_qos_port(host='host2')

    def test_live_migrate_with_qos_port_reschedule_success(self):
        self._start_compute('host3')
        compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', compute3_rp_uuid)

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        orig_check = fake.FakeDriver.check_can_live_migrate_destination

        def fake_check_can_live_migrate_destination(
                context, instance, src_compute_info, dst_compute_info,
                block_migration=False, disk_over_commit=False):
            if dst_compute_info['host'] == 'host2':
                raise exception.MigrationPreCheckError(
                    reason='test_live_migrate_pre_check_fails')
            else:
                return orig_check(
                    context, instance, src_compute_info, dst_compute_info,
                    block_migration, disk_over_commit)

        with mock.patch('nova.virt.fake.FakeDriver.'
                        'check_can_live_migrate_destination',
                        side_effect=fake_check_can_live_migrate_destination):
            self.api.post_server_action(
                server['id'],
                {
                    'os-migrateLive': {
                        'host': None,
                        'block_migration': 'auto'
                    }
                }
            )
            # The first migration attempt was to host2. So we expect that the
            # instance lands on host3.
            self._wait_for_server_parameter(
                server,
                {'OS-EXT-SRV-ATTR:host': 'host3',
                 'status': 'ACTIVE'})

        self._check_allocation(
            server, compute3_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host3-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_live_migrate_with_qos_port_reschedule_fails(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        with mock.patch(
                'nova.virt.fake.FakeDriver.check_can_live_migrate_destination',
                side_effect=exception.MigrationPreCheckError(
                    reason='test_live_migrate_pre_check_fails')):
            self.api.post_server_action(
                server['id'],
                {
                    'os-migrateLive': {
                        'host': None,
                        'block_migration': 'auto'
                    }
                }
            )
            # The every migration target host will fail the pre check so
            # the conductor will run out of target host and the migration will
            # fail
            self._wait_for_migration_status(server, ['error'])

        # the server will remain on host1
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # Assert that the InstancePCIRequests also rolled back to point to
        # host1
        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_live_migrate_with_qos_port_pci_update_fails(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is live migrated to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        self.api.post_server_action(
            server['id'],
            {
                'os-migrateLive': {
                    'host': None,
                    'block_migration': 'auto'
                }
            }
        )

        # pci update will fail after scheduling to host2
        self._wait_for_migration_status(server, ['error'])
        server = self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ERROR'})
        self.assertIn(
            'does not have a properly formatted name',
            server['fault']['message'])

        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # Assert that the InstancePCIRequests still point to host1
        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_unshelve_offloaded_server_with_qos_port(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})
        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        # shelve offload again and then make host1 unusable so the subsequent
        # unshelve needs to select host2
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self.admin_api.put_service(
            self.compute1_service_id, {"status": "disabled"})

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host2',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute2_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        self._assert_pci_request_pf_device_name(server, 'host2-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_unshelve_offloaded_server_with_qos_port_pci_update_fails(self):
        # Update the name of the network device RP of PF2 on host2 to something
        # unexpected. This will cause
        # update_pci_request_spec_with_allocated_interface_name() to raise
        # when the instance is unshelved to the host2.
        rsp = self.placement.put(
            '/resource_providers/%s'
            % self.sriov_dev_rp_per_host[self.compute2_rp_uuid][self.PF2],
            {"name": "invalid-device-rp-name"})
        self.assertEqual(200, rsp.status)

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        # make host1 unusable so the subsequent unshelve needs to select host2
        self.admin_api.put_service(
            self.compute1_service_id, {"status": "disabled"})

        self.api.post_server_action(server['id'], {'unshelve': None})

        # Unshelve fails on host2 due to
        # update_pci_request_spec_with_allocated_interface_name fails so the
        # instance goes back to shelve offloaded state
        fake_notifier.wait_for_versioned_notifications(
            'instance.unshelve.start')
        error_notification = fake_notifier.wait_for_versioned_notifications(
            'compute.exception')[0]
        self.assertEqual(
            'UnexpectedResourceProviderNameForPCIRequest',
            error_notification['payload']['nova_object.data']['exception'])
        server = self._wait_for_server_parameter(
            server,
            {'OS-EXT-STS:task_state': None,
             'status': 'SHELVED_OFFLOADED'})

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)

    def test_unshelve_offloaded_server_with_qos_port_fails_due_to_neutron(
            self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED'})
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        # Simulate that port update fails during unshelve due to neutron is
        # unavailable
        with mock.patch(
                'nova.tests.fixtures.NeutronFixture.'
                'update_port') as mock_update_port:
            mock_update_port.side_effect = neutron_exception.ConnectionFailed(
                reason='test')
            req = {'unshelve': None}
            self.api.post_server_action(server['id'], req)
            fake_notifier.wait_for_versioned_notifications(
                'instance.unshelve.start')
            self._wait_for_server_parameter(
                server,
                {'status': 'SHELVED_OFFLOADED',
                 'OS-EXT-STS:task_state': None})

        # As the instance went back to offloaded state we expect no allocation
        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']
        self.assertEqual(0, len(allocations))

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)


class LiveMigrateAbortWithPortResourceRequestTest(
        PortResourceRequestBasedSchedulingTestBase):

    compute_driver = "fake.FakeLiveMigrateDriverWithPciResources"

    def setUp(self):
        # Use a custom weigher to make sure that we have a predictable host
        # order in the alternate list returned by the scheduler for migration.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super(LiveMigrateAbortWithPortResourceRequestTest, self).setUp()
        self.compute2 = self._start_compute('host2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

    def test_live_migrate_with_qos_port_abort_migration(self):
        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        # The special virt driver will keep the live migration running until it
        # is aborted.
        self.api.post_server_action(
            server['id'],
            {
                'os-migrateLive': {
                    'host': None,
                    'block_migration': 'auto'
                }
            }
        )

        # wait for the migration to start
        migration = self._wait_for_migration_status(server, ['running'])

        # delete the migration to abort it
        self.api.delete_migration(server['id'], migration['id'])

        self._wait_for_migration_status(server, ['cancelled'])
        self._wait_for_server_parameter(
            server,
            {'OS-EXT-SRV-ATTR:host': 'host1',
             'status': 'ACTIVE'})

        self._check_allocation(
            server, self.compute1_rp_uuid, non_qos_normal_port,
            qos_normal_port, qos_sriov_port, self.flavor_with_group_policy)

        # Assert that the InstancePCIRequests rolled back to point to host1
        self._assert_pci_request_pf_device_name(server, 'host1-ens2')

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)


class PortResourceRequestReSchedulingTest(
        PortResourceRequestBasedSchedulingTestBase):
    """Similar to PortResourceRequestBasedSchedulingTest
    except this test uses FakeRescheduleDriver which will test reschedules
    during server create work as expected, i.e. that the resource request
    allocations are moved from the initially selected compute to the
    alternative compute.
    """

    compute_driver = 'fake.FakeRescheduleDriver'

    def setUp(self):
        super(PortResourceRequestReSchedulingTest, self).setUp()
        self.compute2 = self._start_compute('host2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)

    def _create_networking_rp_tree(self, hostname, compute_rp_uuid):
        # let's simulate what the neutron would do
        self._create_ovs_networking_rp_tree(compute_rp_uuid)

    def test_boot_reschedule_success(self):
        port = self.neutron.port_with_resource_request

        server = self._create_server(
            flavor=self.flavor,
            networks=[{'port': port['id']}])
        server = self._wait_for_state_change(server, 'ACTIVE')
        updated_port = self.neutron.show_port(port['id'])['port']

        dest_hostname = server['OS-EXT-SRV-ATTR:host']
        dest_compute_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        failed_compute_rp = (self.compute1_rp_uuid
                             if dest_compute_rp_uuid == self.compute2_rp_uuid
                             else self.compute2_rp_uuid)

        allocations = self.placement.get(
            '/allocations/%s' % server['id']).body['allocations']

        # We expect one set of allocations for the compute resources on the
        # compute rp and one set for the networking resources on the ovs bridge
        # rp
        self.assertEqual(2, len(allocations))

        self.assertComputeAllocationMatchesFlavor(
            allocations, dest_compute_rp_uuid, self.flavor)

        network_allocations = allocations[
            self.ovs_bridge_rp_per_host[dest_compute_rp_uuid]]['resources']
        self.assertPortMatchesAllocation(port, network_allocations)

        # assert that the allocations against the host where the spawn
        # failed are cleaned up properly
        self.assertEqual(
            {'VCPU': 0, 'MEMORY_MB': 0, 'DISK_GB': 0},
            self._get_provider_usages(failed_compute_rp))
        self.assertEqual(
            {'NET_BW_EGR_KILOBIT_PER_SEC': 0, 'NET_BW_IGR_KILOBIT_PER_SEC': 0},
            self._get_provider_usages(
                self.ovs_bridge_rp_per_host[failed_compute_rp]))

        # We expect that only the RP uuid of the networking RP having the port
        # allocation is sent in the port binding
        binding_profile = updated_port['binding:profile']
        self.assertEqual(self.ovs_bridge_rp_per_host[dest_compute_rp_uuid],
                         binding_profile['allocation'])

        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding
        updated_port = self.neutron.show_port(port['id'])['port']
        binding_profile = updated_port['binding:profile']
        self.assertNotIn('allocation', binding_profile)

    def test_boot_reschedule_fill_provider_mapping_raises(self):
        """Verify that if the  _fill_provider_mapping raises during re-schedule
        then the instance is properly put into ERROR state.
        """

        port = self.neutron.port_with_resource_request

        # First call is during boot, we want that to succeed normally. Then the
        # fake virt driver triggers a re-schedule. During that re-schedule the
        # fill is called again, and we simulate that call raises.
        original_fill = utils.fill_provider_mapping

        def stub_fill_provider_mapping(*args, **kwargs):
            if not mock_fill.called:
                return original_fill(*args, **kwargs)
            raise exception.ResourceProviderTraitRetrievalFailed(
                uuid=uuids.rp1)

        with mock.patch(
                'nova.scheduler.utils.fill_provider_mapping',
                side_effect=stub_fill_provider_mapping) as mock_fill:
            server = self._create_server(
                flavor=self.flavor,
                networks=[{'port': port['id']}])
            server = self._wait_for_state_change(server, 'ERROR')

        self.assertIn(
            'Failed to get traits for resource provider',
            server['fault']['message'])

        self._delete_and_check_allocations(server)

        # assert that unbind removes the allocation from the binding
        updated_port = self.neutron.show_port(port['id'])['port']
        binding_profile = neutronapi.get_binding_profile(updated_port)
        self.assertNotIn('allocation', binding_profile)


class AcceleratorServerBase(integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(AcceleratorServerBase, self).setUp()
        self.cyborg = self.useFixture(nova_fixtures.CyborgFixture())
        # dict of form {$compute_rp_uuid: $device_rp_uuid}
        self.device_rp_map = {}
        # self.NUM_HOSTS should be set up by derived classes
        if not hasattr(self, 'NUM_HOSTS'):
            self.NUM_HOSTS = 1
        self._setup_compute_nodes_and_device_rps()

    def _setup_compute_nodes_and_device_rps(self):
        self.compute_services = []
        for i in range(self.NUM_HOSTS):
            svc = self._start_compute(host='accel_host' + str(i))
            self.compute_services.append(svc)
        self.compute_rp_uuids = [
           rp['uuid'] for rp in self._get_all_providers()
           if rp['uuid'] == rp['root_provider_uuid']]
        for index, uuid in enumerate(self.compute_rp_uuids):
            device_rp_uuid = self._create_device_rp(index, uuid)
            self.device_rp_map[uuid] = device_rp_uuid
        self.device_rp_uuids = list(self.device_rp_map.values())

    def _create_device_rp(self, index, compute_rp_uuid,
                          resource='FPGA', res_amt=2):
        """Created nested RP for a device. There is one per host.

        :param index: Number of the device rp uuid for this setup
        :param compute_rp_uuid: Resource provider UUID of the host.
        :param resource: Placement resource name.
            Assumed to be a standard resource class.
        :param res_amt: Amount of the resource.
        :returns: Device RP UUID
        """
        resp = self._post_nested_resource_provider(
            'FakeDevice' + str(index), parent_rp_uuid=compute_rp_uuid)
        device_rp_uuid = resp['uuid']
        inventory = {
            'resource_provider_generation': 0,
            'inventories': {
                resource: {
                    'total': res_amt,
                    'allocation_ratio': 1.0,
                    'max_unit': res_amt,
                    'min_unit': 1,
                    'reserved': 0,
                    'step_size': 1,
                 }
             },
        }
        self._update_inventory(device_rp_uuid, inventory)
        self._create_trait(self.cyborg.trait)
        self._set_provider_traits(device_rp_uuid, [self.cyborg.trait])
        return device_rp_uuid

    def _post_nested_resource_provider(self, rp_name, parent_rp_uuid):
        body = {'name': rp_name, 'parent_provider_uuid': parent_rp_uuid}
        return self.placement.post(
            url='/resource_providers', version='1.20', body=body).body

    def _create_acc_flavor(self):
        extra_specs = {'accel:device_profile': self.cyborg.dp_name}
        flavor_id = self._create_flavor(name='acc.tiny',
                                        extra_spec=extra_specs)
        return flavor_id

    def _check_allocations_usage(self, server, check_other_host_alloc=True):
        # Check allocations on host where instance is running
        server_uuid = server['id']

        hostname = server['OS-EXT-SRV-ATTR:host']
        server_host_rp_uuid = self._get_provider_uuid_by_host(hostname)
        expected_host_alloc = {
            'resources': {'VCPU': 2, 'MEMORY_MB': 2048, 'DISK_GB': 20},
        }
        expected_device_alloc = {'resources': {'FPGA': 1}}

        for i in range(self.NUM_HOSTS):
            compute_uuid = self.compute_rp_uuids[i]
            device_uuid = self.device_rp_map[compute_uuid]
            host_alloc = self._get_allocations_by_provider_uuid(compute_uuid)
            device_alloc = self._get_allocations_by_provider_uuid(device_uuid)
            if compute_uuid == server_host_rp_uuid:
                self.assertEqual(expected_host_alloc, host_alloc[server_uuid])
                self.assertEqual(expected_device_alloc,
                                 device_alloc[server_uuid])
            else:
                if check_other_host_alloc:
                    self.assertEqual({}, host_alloc)
                self.assertEqual({}, device_alloc)

        # NOTE(Sundar): ARQs for an instance could come from different
        # devices in the same host, in general. But, in this test case,
        # there is only one device in the host. So, we check for that.
        device_rp_uuid = self.device_rp_map[server_host_rp_uuid]
        expected_arq_bind_info = set([('Bound', hostname,
                                       device_rp_uuid, server_uuid)])
        arqs = nova_fixtures.CyborgFixture.fake_get_arqs_for_instance(
            server_uuid)
        # The state is hardcoded but other fields come from the test case.
        arq_bind_info = {(arq['state'], arq['hostname'],
                          arq['device_rp_uuid'], arq['instance_uuid'])
                         for arq in arqs}
        self.assertSetEqual(expected_arq_bind_info, arq_bind_info)

    def _check_no_allocs_usage(self, server_uuid):
        allocs = self._get_allocations_by_server_uuid(server_uuid)
        self.assertEqual({}, allocs)

        for i in range(self.NUM_HOSTS):
            host_alloc = self._get_allocations_by_provider_uuid(
                    self.compute_rp_uuids[i])
            self.assertEqual({}, host_alloc)
            device_alloc = self._get_allocations_by_provider_uuid(
                    self.device_rp_uuids[i])
            self.assertEqual({}, device_alloc)
            usage = self._get_provider_usages(
                self.device_rp_uuids[i]).get('FPGA')
            self.assertEqual(0, usage)


class AcceleratorServerTest(AcceleratorServerBase):
    def setUp(self):
        self.NUM_HOSTS = 1
        super(AcceleratorServerTest, self).setUp()

    def _get_server(self, expected_state='ACTIVE'):
        flavor_id = self._create_acc_flavor()
        server_name = 'accel_server1'
        server = self._create_server(
            server_name, flavor_id=flavor_id,
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none', expected_state=expected_state)
        return server

    def test_create_delete_server_ok(self):
        server = self._get_server()

        # Verify that the host name and the device rp UUID are set properly.
        # Other fields in the ARQ are hardcoded data from the fixture.
        arqs = self.cyborg.fake_get_arqs_for_instance(server['id'])
        self.assertEqual(self.device_rp_uuids[0], arqs[0]['device_rp_uuid'])
        self.assertEqual(server['OS-EXT-SRV-ATTR:host'], arqs[0]['hostname'])

        # Check allocations and usage
        self._check_allocations_usage(server)

        # Delete server and check that ARQs got deleted
        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)
        self.cyborg.mock_del_arqs.assert_called_once_with(server['id'])

        # Check that resources are freed
        self._check_no_allocs_usage(server['id'])

    def test_create_server_with_error(self):

        def throw_error(*args, **kwargs):
            raise exception.BuildAbortException(reason='',
                    instance_uuid='fake')

        self.stub_out('nova.virt.fake.FakeDriver.spawn', throw_error)

        server = self._get_server(expected_state='ERROR')
        server_uuid = server['id']
        # Check that Cyborg was called to delete ARQs
        self.cyborg.mock_del_arqs.assert_called_once_with(server_uuid)

        # BuildAbortException will not trigger a reschedule and the placement
        # cleanup is the last step in the compute manager after instance state
        # setting, fault recording and notification sending. So we have no
        # other way than simply wait to ensure the placement cleanup happens
        # before we assert it.
        def placement_cleanup():
            # An instance in error state should consume no resources
            self._check_no_allocs_usage(server_uuid)

        self._wait_for_assert(placement_cleanup)

        self.api.delete_server(server_uuid)
        self._wait_until_deleted(server)
        # Verify that there is one more call to delete ARQs
        self.cyborg.mock_del_arqs.assert_has_calls(
            [mock.call(server_uuid), mock.call(server_uuid)])

        # Verify that no allocations/usages remain after deletion
        self._check_no_allocs_usage(server_uuid)

    def test_create_server_with_local_delete(self):
        """Delete the server when compute service is down."""
        server = self._get_server()
        server_uuid = server['id']

        # Stop the server.
        self.api.post_server_action(server_uuid, {'os-stop': {}})
        self._wait_for_state_change(server, 'SHUTOFF')
        self._check_allocations_usage(server)
        # Stop and force down the compute service.
        compute_id = self.admin_api.get_services(
            host='accel_host0', binary='nova-compute')[0]['id']
        self.compute_services[0].stop()
        self.admin_api.put_service(compute_id, {'forced_down': 'true'})

        # Delete the server with compute service down.
        self.api.delete_server(server_uuid)
        self.cyborg.mock_del_arqs.assert_called_once_with(server_uuid)
        self._check_no_allocs_usage(server_uuid)

        # Restart the compute service to see if anything fails.
        self.admin_api.put_service(compute_id, {'forced_down': 'false'})
        self.compute_services[0].start()


class AcceleratorServerReschedTest(AcceleratorServerBase):

    def setUp(self):
        self.NUM_HOSTS = 2
        super(AcceleratorServerReschedTest, self).setUp()

    def test_resched(self):
        orig_spawn = fake.FakeDriver.spawn

        def fake_spawn(*args, **kwargs):
            fake_spawn.count += 1
            if fake_spawn.count == 1:
                raise exception.ComputeResourcesUnavailable(
                    reason='First host fake fail.', instance_uuid='fake')
            else:
                orig_spawn(*args, **kwargs)
        fake_spawn.count = 0

        with mock.patch('nova.virt.fake.FakeDriver.spawn', new=fake_spawn):
            flavor_id = self._create_acc_flavor()
            server_name = 'accel_server1'
            server = self._create_server(
                server_name, flavor_id=flavor_id,
                image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                networks='none', expected_state='ACTIVE')

        self.assertEqual(2, fake_spawn.count)
        self._check_allocations_usage(server)
        self.cyborg.mock_del_arqs.assert_called_once_with(server['id'])

    def test_resched_fails(self):

        def throw_error(*args, **kwargs):
            raise exception.ComputeResourcesUnavailable(reason='',
                    instance_uuid='fake')

        self.stub_out('nova.virt.fake.FakeDriver.spawn', throw_error)

        flavor_id = self._create_acc_flavor()
        server_name = 'accel_server1'
        server = self._create_server(
            server_name, flavor_id=flavor_id,
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none', expected_state='ERROR')

        server_uuid = server['id']
        self._check_no_allocs_usage(server_uuid)
        self.cyborg.mock_del_arqs.assert_has_calls(
            [mock.call(server_uuid),
             mock.call(server_uuid),
             mock.call(server_uuid)])


class AcceleratorServerOpsTest(AcceleratorServerBase):

    def setUp(self):
        self.NUM_HOSTS = 2  # 2nd host needed for evacuate
        super(AcceleratorServerOpsTest, self).setUp()
        flavor_id = self._create_acc_flavor()
        server_name = 'accel_server1'
        self.server = self._create_server(
            server_name, flavor_id=flavor_id,
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none', expected_state='ACTIVE')

    def _test_evacuate(self, server, num_hosts):
        server_hostname = server['OS-EXT-SRV-ATTR:host']
        for i in range(num_hosts):
            if self.compute_services[i].host == server_hostname:
                compute_to_stop = self.compute_services[i]
            else:
                compute_to_evacuate = self.compute_services[i]
        # Stop and force down the compute service.
        compute_id = self.admin_api.get_services(
            host=server_hostname, binary='nova-compute')[0]['id']
        compute_to_stop.stop()
        self.admin_api.put_service(compute_id, {'forced_down': 'true'})
        return compute_to_stop, compute_to_evacuate

    def test_soft_reboot_ok(self):
        self._reboot_server(self.server)
        self._check_allocations_usage(self.server)

    def test_hard_reboot_ok(self):
        self._reboot_server(self.server, hard=True)
        self._check_allocations_usage(self.server)

    def test_pause_unpause_ok(self):
        # Pause and unpause should work with accelerators.
        # This is not a general test of un/pause functionality.
        self.api.post_server_action(self.server['id'], {'pause': {}})
        self._wait_for_state_change(self.server, 'PAUSED')
        self._check_allocations_usage(self.server)
        # ARQs didn't get deleted (and so didn't have to be re-created).
        self.cyborg.mock_del_arqs.assert_not_called()

        self.api.post_server_action(self.server['id'], {'unpause': {}})
        self._wait_for_state_change(self.server, 'ACTIVE')
        self._check_allocations_usage(self.server)

    def test_stop_start_ok(self):
        # Stop and start should work with accelerators.
        # This is not a general test of start/stop functionality.
        self.api.post_server_action(self.server['id'], {'os-stop': {}})
        self._wait_for_state_change(self.server, 'SHUTOFF')
        self._check_allocations_usage(self.server)
        # ARQs didn't get deleted (and so didn't have to be re-created).
        self.cyborg.mock_del_arqs.assert_not_called()

        self.api.post_server_action(self.server['id'], {'os-start': {}})
        self._wait_for_state_change(self.server, 'ACTIVE')
        self._check_allocations_usage(self.server)

    def test_lock_unlock_ok(self):
        # Lock/unlock are no-ops for accelerators.
        self.api.post_server_action(self.server['id'], {'lock': {}})
        server = self.api.get_server(self.server['id'])
        self.assertTrue(server['locked'])
        self._check_allocations_usage(self.server)

        self.api.post_server_action(self.server['id'], {'unlock': {}})
        server = self.api.get_server(self.server['id'])
        self.assertTrue(not server['locked'])
        self._check_allocations_usage(self.server)

    def test_backup_ok(self):
        self.api.post_server_action(self.server['id'],
            {'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1}})
        self._check_allocations_usage(self.server)

    def test_create_image_ok(self):  # snapshot
        self.api.post_server_action(self.server['id'],
            {'createImage': {
                'name': 'foo-image',
                'metadata': {'meta_var': 'meta_val'}}})
        self._check_allocations_usage(self.server)

    def test_rescue_unrescue_ok(self):
        self.api.post_server_action(self.server['id'],
            {'rescue': {
                'adminPass': 'MySecretPass',
                'rescue_image_ref': '70a599e0-31e7-49b7-b260-868f441e862b'}})
        self._check_allocations_usage(self.server)
        # ARQs didn't get deleted (and so didn't have to be re-created).
        self.cyborg.mock_del_arqs.assert_not_called()
        self._wait_for_state_change(self.server, 'RESCUE')

        self.api.post_server_action(self.server['id'], {'unrescue': {}})
        self._check_allocations_usage(self.server)

    def test_evacuate_ok(self):
        server_hostname = self.server['OS-EXT-SRV-ATTR:host']
        arqs = self.cyborg.fake_get_arqs_for_instance(self.server['id'])
        compute_to_stop, compute_to_evacuate = self._test_evacuate(
            self.server, self.NUM_HOSTS)
        self._evacuate_server(self.server, compute_to_evacuate.host)
        compute_to_stop.start()
        self.server = self.api.get_server(self.server['id'])
        arqs_new = self.cyborg.fake_get_arqs_for_instance(self.server['id'])
        evac_hostname = self.server['OS-EXT-SRV-ATTR:host']
        self.assertNotEqual(server_hostname, evac_hostname)
        self.assertEqual(server_hostname, arqs[0]['hostname'])
        self.assertEqual(evac_hostname, arqs_new[0]['hostname'])

    def test_rebuild_ok(self):
        rebuild_image_ref = self.glance.auto_disk_config_enabled_image['id']
        self.api.post_server_action(self.server['id'],
            {'rebuild': {
                'imageRef': rebuild_image_ref,
                'OS-DCF:diskConfig': 'AUTO'}})
        fake_notifier.wait_for_versioned_notifications('instance.rebuild.end')
        self._wait_for_state_change(self.server, 'ACTIVE')
        self._check_allocations_usage(self.server)

    def test_resize_fails(self):
        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server_action, self.server['id'],
            {'resize': {'flavorRef': '2', 'OS-DCF:diskConfig': 'AUTO'}})
        self.assertEqual(403, ex.response.status_code)
        self._check_allocations_usage(self.server)

    def test_suspend_fails(self):
        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server_action, self.server['id'], {'suspend': {}})
        self.assertEqual(403, ex.response.status_code)
        self._check_allocations_usage(self.server)

    def test_migrate_fails(self):
        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server_action, self.server['id'], {'migrate': {}})
        self.assertEqual(403, ex.response.status_code)
        self._check_allocations_usage(self.server)

    def test_live_migrate_fails(self):
        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server_action, self.server['id'],
            {'migrate': {'host': 'accel_host1'}})
        self.assertEqual(403, ex.response.status_code)
        self._check_allocations_usage(self.server)

    @mock.patch.object(objects.service, 'get_minimum_version_all_cells')
    def test_evacuate_old_compute(self, old_compute_version):
        """Tests when the source compute service is too old to call
        evacuate so OpenStackApiException is raised.
        """
        old_compute_version.return_value = 52
        _, compute_to_evacuate = self._test_evacuate(
            self.server, self.NUM_HOSTS)

        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server_action, self.server['id'],
            {'evacuate': {
                 'host': compute_to_evacuate.host,
                 'adminPass': 'MySecretPass'}})
        self.assertEqual(403, ex.response.status_code)
        self._check_allocations_usage(self.server)

    @mock.patch.object(objects.service, 'get_minimum_version_all_cells')
    def test_rebuild_old_compute(self, old_compute_version):
        """Tests when the source compute service is too old to call
        rebuild so OpenStackApiException is raised.
        """
        old_compute_version.return_value = 52
        rebuild_image_ref = self.glance.auto_disk_config_enabled_image['id']

        ex = self.assertRaises(client.OpenStackApiException,
            self.api.post_server_action, self.server['id'],
            {'rebuild': {
                'imageRef': rebuild_image_ref,
                'OS-DCF:diskConfig': 'AUTO'}})
        self.assertEqual(403, ex.response.status_code)
        self._check_allocations_usage(self.server)


class CrossCellResizeWithQoSPort(PortResourceRequestBasedSchedulingTestBase):
    NUMBER_OF_CELLS = 2

    def setUp(self):
        # Use our custom weigher defined above to make sure that we have
        # a predictable host order in the alternate list returned by the
        # scheduler for migration.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super(CrossCellResizeWithQoSPort, self).setUp()
        # start compute2 in cell2, compute1 is started in cell1 by default
        self.compute2 = self._start_compute('host2', cell_name='cell2')
        self.compute2_rp_uuid = self._get_provider_uuid_by_host('host2')
        self._create_networking_rp_tree('host2', self.compute2_rp_uuid)
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

        # Enable cross-cell resize policy since it defaults to not allow
        # anyone to perform that type of operation. For these tests we'll
        # just allow admins to perform cross-cell resize.
        self.policy.set_rules({
            servers_policies.CROSS_CELL_RESIZE:
                base_policies.RULE_ADMIN_API},
            overwrite=False)

    def test_cross_cell_migrate_server_with_qos_ports(self):
        """Test that cross cell migration is not supported with qos ports and
        nova therefore falls back to do a same cell migration instead.
        To test this properly we first make sure that there is no valid host
        in the same cell but there is valid host in another cell and observe
        that the migration fails with NoValidHost. Then we start a new compute
        in the same cell the instance is in and retry the migration that is now
        expected to pass.
        """

        non_qos_normal_port = self.neutron.port_1
        qos_normal_port = self.neutron.port_with_resource_request
        qos_sriov_port = self.neutron.port_with_sriov_resource_request

        server = self._create_server_with_ports_and_check_allocation(
            non_qos_normal_port, qos_normal_port, qos_sriov_port)

        orig_create_binding = neutronapi.API._create_port_binding

        hosts = {
            'host1': self.compute1_rp_uuid, 'host2': self.compute2_rp_uuid}

        # Add an extra check to our neutron fixture. This check makes sure that
        # the RP sent in the binding corresponds to host of the binding. In a
        # real deployment this is checked by the Neutron server. As bug
        # 1907522 showed we fail this check for cross cell migration with qos
        # ports in a real deployment. So to reproduce that bug we need to have
        # the same check in our test env too.
        def spy_on_create_binding(context, client, port_id, data):
            host_rp_uuid = hosts[data['binding']['host']]
            device_rp_uuid = data['binding']['profile'].get('allocation')
            if port_id == qos_normal_port['id']:
                if device_rp_uuid != self.ovs_bridge_rp_per_host[host_rp_uuid]:
                    raise exception.PortBindingFailed(port_id=port_id)
            elif port_id == qos_sriov_port['id']:
                if (device_rp_uuid not in
                        self.sriov_dev_rp_per_host[host_rp_uuid].values()):
                    raise exception.PortBindingFailed(port_id=port_id)

            return orig_create_binding(context, client, port_id, data)

        with mock.patch(
            'nova.network.neutron.API._create_port_binding',
            side_effect=spy_on_create_binding, autospec=True
        ):
            # We expect the migration to fail as the only available target
            # host is in a different cell and while cross cell migration is
            # enabled it is not supported for neutron ports with resource
            # request.
            self.api.post_server_action(server['id'], {'migrate': None})
            self._wait_for_migration_status(server, ['error'])
            self._wait_for_server_parameter(
                server,
                {'status': 'ACTIVE', 'OS-EXT-SRV-ATTR:host': 'host1'})
            event = self._wait_for_action_fail_completion(
                server, 'migrate', 'conductor_migrate_server')
            self.assertIn(
                'exception.NoValidHost', event['traceback'])
            log = self.stdlog.logger.output
            self.assertIn(
                'Request is allowed by policy to perform cross-cell resize '
                'but the instance has ports with resource request and '
                'cross-cell resize is not supported with such ports.',
                log)
            self.assertNotIn(
                'nova.exception.PortBindingFailed: Binding failed for port',
                log)
            self.assertNotIn(
                "AttributeError: 'NoneType' object has no attribute 'version'",
                log)

        # Now start a new compute in the same cell as the instance and retry
        # the migration.
        self._start_compute('host3', cell_name='cell1')
        self.compute3_rp_uuid = self._get_provider_uuid_by_host('host3')
        self._create_networking_rp_tree('host3', self.compute3_rp_uuid)

        with mock.patch(
                'nova.network.neutron.API._create_port_binding',
                side_effect=spy_on_create_binding, autospec=True
        ):
            server = self._migrate_server(server)
            self.assertEqual('host3', server['OS-EXT-SRV-ATTR:host'])

        self._delete_server_and_check_allocations(
            server, qos_normal_port, qos_sriov_port)
