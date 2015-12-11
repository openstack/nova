# Copyright 2015 Ericsson AB
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

import mock
import time

from oslo_config import cfg

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.unit import fake_network
from nova.tests.unit import policy_fixture

import nova.scheduler.utils
import nova.servicegroup
import nova.tests.unit.image.fake

CONF = cfg.CONF


class ServerGroupTestBase(test.TestCase):
    REQUIRES_LOCKING = True
    api_major_version = 'v2'
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'

    # Note(gibi): RamFilter is needed to ensure that
    # test_boot_servers_with_affinity_no_valid_host behaves as expected
    _scheduler_default_filters = ('ServerGroupAntiAffinityFilter',
                                  'ServerGroupAffinityFilter',
                                  'RamFilter')

    # Override servicegroup parameters to make the tests run faster
    _service_down_time = 2
    _report_interval = 1

    anti_affinity = {'name': 'fake-name-1', 'policies': ['anti-affinity']}
    affinity = {'name': 'fake-name-2', 'policies': ['affinity']}

    def setUp(self):
        super(ServerGroupTestBase, self).setUp()
        self.flags(scheduler_default_filters=self._scheduler_default_filters)
        self.flags(service_down_time=self._service_down_time)
        self.flags(report_interval=self._report_interval)

        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture())

        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self.stubs)

        self.start_service('conductor', manager=CONF.conductor.manager)
        self.start_service('scheduler')

        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

    def _wait_for_state_change(self, server, expected_status, max_retries=10):
        retry_count = 0
        while True:
            server = self.admin_api.get_server(server['id'])
            if server['status'] == expected_status:
                break
            retry_count += 1
            if retry_count == max_retries:
                self.fail('Wait for state change failed, '
                          'expected_status=%s, actual_status=%s'
                          % (expected_status, server['status']))
            time.sleep(0.5)

        return server

    def _boot_a_server_to_group(self, group,
                                expected_status='ACTIVE', flavor=None):
        server = self._build_minimal_create_server_request('some-server')
        if flavor:
            server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                                  % flavor['id'])
        post = {'server': server,
                'os:scheduler_hints': {'group': group['id']}}
        created_server = self.api.post_server(post)
        self.assertTrue(created_server['id'])

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(created_server,
                                                   expected_status)

        return found_server

    def _build_minimal_create_server_request(self, name):
        server = {}

        image = self.api.get_images()[0]

        if self._image_ref_parameter in image:
            image_href = image[self._image_ref_parameter]
        else:
            image_href = image['id']
            image_href = 'http://fake.server/%s' % image_href

        # We now have a valid imageId
        server[self._image_ref_parameter] = image_href

        # Set a valid flavorId
        flavor = self.api.get_flavors()[1]
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])
        server['name'] = name
        return server


class ServerGroupTest(ServerGroupTestBase):

    def setUp(self):
        super(ServerGroupTest, self).setUp()

        self.start_service('network')
        self.compute = self.start_service('compute')

        # NOTE(gibi): start a second compute host to be able to test affinity
        self.compute2 = self.start_service('compute', host='host2')
        fake_network.set_stub_network_methods(self.stubs)

    def test_get_no_groups(self):
        groups = self.api.get_server_groups()
        self.assertEqual([], groups)

    def test_create_and_delete_groups(self):
        groups = [self.anti_affinity,
                  self.affinity]
        created_groups = []
        for group in groups:
            created_group = self.api.post_server_groups(group)
            created_groups.append(created_group)
            self.assertEqual(group['name'], created_group['name'])
            self.assertEqual(group['policies'], created_group['policies'])
            self.assertEqual([], created_group['members'])
            self.assertEqual({}, created_group['metadata'])
            self.assertIn('id', created_group)

            group_details = self.api.get_server_group(created_group['id'])
            self.assertEqual(created_group, group_details)

            existing_groups = self.api.get_server_groups()
            self.assertIn(created_group, existing_groups)

        existing_groups = self.api.get_server_groups()
        self.assertEqual(len(groups), len(existing_groups))

        for group in created_groups:
            self.api.delete_server_group(group['id'])
            existing_groups = self.api.get_server_groups()
            self.assertNotIn(group, existing_groups)

    def test_create_wrong_policy(self):
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_groups,
                               {'name': 'fake-name-1',
                                'policies': ['wrong-policy']})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Invalid input', ex.response.text)
        self.assertIn('wrong-policy', ex.response.text)

    def test_get_groups_all_projects(self):
        # This test requires APIs using two projects.

        # Create an API using project 'openstack1'.
        # This is a non-admin API.
        api_openstack1 = self.useFixture(nova_fixtures.OSAPIFixture(
                                        project_id='openstack1')).api

        # Create a server group in project 'openstack'
        # Project 'openstack' is used by self.api
        group1 = self.anti_affinity
        openstack_group = self.api.post_server_groups(group1)

        # Create a server group in project 'openstack1'
        group2 = self.affinity
        openstack1_group = api_openstack1.post_server_groups(group2)

        # The admin should be able to get server groups in all projects.
        all_projects_admin = self.admin_api.get_server_groups(
            all_projects=True)
        self.assertIn(openstack_group, all_projects_admin)
        self.assertIn(openstack1_group, all_projects_admin)

        # The non-admin should only be able to get server groups
        # in his project.
        # The all_projects parameter is ignored for non-admin clients.
        all_projects_non_admin = api_openstack1.get_server_groups(
            all_projects=True)
        self.assertNotIn(openstack_group, all_projects_non_admin)
        self.assertIn(openstack1_group, all_projects_non_admin)

    def _boot_servers_to_group(self, group, flavor=None):
        servers = []
        for _ in range(0, 2):
            server = self._boot_a_server_to_group(group,
                                                  flavor=flavor)
            servers.append(server)
        return servers

    def test_boot_servers_with_affinity(self):
        created_group = self.api.post_server_groups(self.affinity)
        servers = self._boot_servers_to_group(created_group)

        members = self.api.get_server_group(created_group['id'])['members']
        host = servers[0]['OS-EXT-SRV-ATTR:host']
        for server in servers:
            self.assertIn(server['id'], members)
            self.assertEqual(host, server['OS-EXT-SRV-ATTR:host'])

    def test_boot_servers_with_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.affinity)
        # Using big enough flavor to use up the resources on the host
        flavor = self.api.get_flavors()[2]
        self._boot_servers_to_group(created_group, flavor=flavor)

        # The third server cannot be booted as there is not enough resource
        # on the host where the first two server was booted
        failed_server = self._boot_a_server_to_group(created_group,
                                                     flavor=flavor,
                                                     expected_status='ERROR')
        self.assertEqual('No valid host was found. '
                         'There are not enough hosts available.',
                         failed_server['fault']['message'])

    def test_boot_servers_with_anti_affinity(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        members = self.api.get_server_group(created_group['id'])['members']
        self.assertNotEqual(servers[0]['OS-EXT-SRV-ATTR:host'],
                            servers[1]['OS-EXT-SRV-ATTR:host'])
        for server in servers:
            self.assertIn(server['id'], members)

    def test_boot_server_with_anti_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        self._boot_servers_to_group(created_group)

        # We have 2 computes so the third server won't fit into the same group
        failed_server = self._boot_a_server_to_group(created_group,
                                                     expected_status='ERROR')
        self.assertEqual('No valid host was found. '
                         'There are not enough hosts available.',
                         failed_server['fault']['message'])

    def _rebuild_with_group(self, group):
        created_group = self.api.post_server_groups(group)
        servers = self._boot_servers_to_group(created_group)

        post = {'rebuild': {self._image_ref_parameter:
                            '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'}}
        self.api.post_server_action(servers[1]['id'], post)

        rebuilt_server = self._wait_for_state_change(servers[1], 'ACTIVE')

        self.assertEqual(post['rebuild'][self._image_ref_parameter],
                         rebuilt_server.get('image')['id'])
        return [servers[0], rebuilt_server]

    def test_rebuild_with_affinity(self):
        untouched_server, rebuilt_server = self._rebuild_with_group(
            self.affinity)
        self.assertEqual(untouched_server['OS-EXT-SRV-ATTR:host'],
                         rebuilt_server['OS-EXT-SRV-ATTR:host'])

    def test_rebuild_with_anti_affinity(self):
        untouched_server, rebuilt_server = self._rebuild_with_group(
            self.anti_affinity)
        self.assertNotEqual(untouched_server['OS-EXT-SRV-ATTR:host'],
                            rebuilt_server['OS-EXT-SRV-ATTR:host'])

    def _migrate_with_group_no_valid_host(self, group):
        created_group = self.api.post_server_groups(group)
        servers = self._boot_servers_to_group(created_group)

        post = {'migrate': {}}
        ex = self.assertRaises(client.OpenStackApiException,
                               self.admin_api.post_server_action,
                               servers[1]['id'], post)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('No valid host found for cold migrate', ex.response.text)

    def test_migrate_with_group_no_valid_host(self):
        for group in [self.affinity, self.anti_affinity]:
            self._migrate_with_group_no_valid_host(group)

    def test_migrate_with_anti_affinity(self):
        # Start additional host to test migration with anti-affinity
        compute3 = self.start_service('compute', host='host3')

        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        post = {'migrate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        migrated_server = self._wait_for_state_change(servers[1],
                                                      'VERIFY_RESIZE')

        self.assertNotEqual(servers[0]['OS-EXT-SRV-ATTR:host'],
                            migrated_server['OS-EXT-SRV-ATTR:host'])

        compute3.kill()

    def _get_compute_service_by_host_name(self, host_name):
        host = None
        if self.compute.host == host_name:
            host = self.compute
        elif self.compute2.host == host_name:
            host = self.compute2
        else:
            raise AssertionError('host = %s does not found in '
                                 'existing hosts %s' %
                                 (host_name, str([self.compute.host,
                                                  self.compute2.host])))

        return host

    def test_evacuate_with_anti_affinity(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        host.stop()
        # Need to wait service_down_time amount of seconds to ensure
        # nova considers the host down
        time.sleep(self._service_down_time)

        # Start additional host to test evacuation
        compute3 = self.start_service('compute', host='host3')

        post = {'evacuate': {'onSharedStorage': False}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        evacuated_server = self._wait_for_state_change(servers[1], 'ACTIVE')

        self.assertNotEqual(evacuated_server['OS-EXT-SRV-ATTR:host'],
                            servers[0]['OS-EXT-SRV-ATTR:host'])

        compute3.kill()
        host.start()

    def test_evacuate_with_anti_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        host.stop()
        # Need to wait service_down_time amount of seconds to ensure
        # nova considers the host down
        time.sleep(self._service_down_time)

        post = {'evacuate': {'onSharedStorage': False}}
        self.admin_api.post_server_action(servers[1]['id'], post)

        server_after_failed_evac = self._wait_for_state_change(servers[1],
                                                               'ACTIVE')

        # assert that after a failed evac the server active on the same host
        # as before
        self.assertEqual(server_after_failed_evac['OS-EXT-SRV-ATTR:host'],
                         servers[1]['OS-EXT-SRV-ATTR:host'])

        host.start()

    def test_evacuate_with_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        host.stop()
        # Need to wait service_down_time amount of seconds to ensure
        # nova considers the host down
        time.sleep(self._service_down_time)

        post = {'evacuate': {'onSharedStorage': False}}
        self.admin_api.post_server_action(servers[1]['id'], post)

        server_after_failed_evac = self._wait_for_state_change(servers[1],
                                                               'ACTIVE')

        # assert that after a failed evac the server active on the same host
        # as before
        self.assertEqual(server_after_failed_evac['OS-EXT-SRV-ATTR:host'],
                         servers[1]['OS-EXT-SRV-ATTR:host'])

        host.start()


class ServerGroupAffinityConfTest(ServerGroupTestBase):
    # Load only anti-affinity filter so affinity will be missing
    _scheduler_default_filters = 'ServerGroupAntiAffinityFilter'

    @mock.patch('nova.scheduler.utils._SUPPORTS_AFFINITY', None)
    def test_affinity_no_filter(self):
        created_group = self.api.post_server_groups(self.affinity)

        failed_server = self._boot_a_server_to_group(created_group,
                                                     expected_status='ERROR')
        self.assertEqual('ServerGroup policy is not supported: '
                         'ServerGroupAffinityFilter not configured',
                         failed_server['fault']['message'])
        self.assertEqual(400, failed_server['fault']['code'])


class ServerGroupAntiAffinityConfTest(ServerGroupTestBase):
    # Load only affinity filter so anti-affinity will be missing
    _scheduler_default_filters = 'ServerGroupAffinityFilter'

    @mock.patch('nova.scheduler.utils._SUPPORTS_ANTI_AFFINITY', None)
    def test_anti_affinity_no_filter(self):
        created_group = self.api.post_server_groups(self.anti_affinity)

        failed_server = self._boot_a_server_to_group(created_group,
                                                     expected_status='ERROR')
        self.assertEqual('ServerGroup policy is not supported: '
                         'ServerGroupAntiAffinityFilter not configured',
                         failed_server['fault']['message'])
        self.assertEqual(400, failed_server['fault']['code'])


class ServerGroupTestV21(ServerGroupTest):
    api_major_version = 'v2.1'
