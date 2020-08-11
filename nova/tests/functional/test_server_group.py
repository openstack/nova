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
from oslo_config import cfg
import six

from nova.compute import instance_actions
from nova import context
from nova.db import api as db
from nova.db.sqlalchemy import api as db_api
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture
from nova import utils
from nova.virt import fake

# An alternate project id
PROJECT_ID_ALT = "616c6c796f7572626173656172656f73"

CONF = cfg.CONF


class ServerGroupTestBase(test.TestCase,
                          integrated_helpers.InstanceHelperMixin):
    REQUIRES_LOCKING = True
    api_major_version = 'v2.1'
    microversion = None

    _enabled_filters = (CONF.filter_scheduler.enabled_filters +
                        ['ServerGroupAntiAffinityFilter',
                           'ServerGroupAffinityFilter'])

    anti_affinity = {'name': 'fake-name-1', 'policies': ['anti-affinity']}
    affinity = {'name': 'fake-name-2', 'policies': ['affinity']}

    def _get_weight_classes(self):
        return []

    def setUp(self):
        super(ServerGroupTestBase, self).setUp()
        self.flags(enabled_filters=self._enabled_filters,
                   group='filter_scheduler')
        # NOTE(sbauza): Don't verify VCPUS and disks given the current nodes.
        self.flags(cpu_allocation_ratio=9999.0)
        self.flags(disk_allocation_ratio=9999.0)
        self.flags(weight_classes=self._get_weight_classes(),
                   group='filter_scheduler')

        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.NeutronFixture(self))

        self.useFixture(func_fixtures.PlacementFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.api
        self.api.microversion = self.microversion
        self.admin_api = api_fixture.admin_api
        self.admin_api.microversion = self.microversion

        self.start_service('conductor')
        self.start_service('scheduler')

    def _boot_a_server_to_group(self, group,
                                expected_status='ACTIVE', flavor=None,
                                az=None):
        server = self._build_server(
            image_uuid='a2459075-d96c-40d5-893e-577ff92e721c',
            flavor_id=flavor['id'] if flavor else None,
            networks=[],
            az=az)
        post = {'server': server,
                'os:scheduler_hints': {'group': group['id']}}
        created_server = self.api.post_server(post)
        self.assertTrue(created_server['id'])

        # Wait for it to finish being created
        found_server = self._wait_for_state_change(
            created_server, expected_status)

        return found_server


class ServerGroupFakeDriver(fake.SmallFakeDriver):
    """A specific fake driver for our tests.

    Here, we only want to be RAM-bound.
    """

    vcpus = 1000
    memory_mb = 8192
    local_gb = 100000


# A fake way to change the FakeDriver given we don't have a possibility yet to
# modify the resources for the FakeDriver
def _fake_load_compute_driver(virtapi, compute_driver=None):
    return ServerGroupFakeDriver(virtapi)


class ServerGroupTestV21(ServerGroupTestBase):

    def setUp(self):
        super(ServerGroupTestV21, self).setUp()

        # TODO(sbauza): Remove that once there is a way to have a custom
        # FakeDriver supporting different resources. Note that we can't also
        # simply change the config option for choosing our custom fake driver
        # as the mocked method only accepts to load drivers in the nova.virt
        # tree.
        self.stub_out('nova.virt.driver.load_compute_driver',
                      _fake_load_compute_driver)
        self.compute = self.start_service('compute', host='compute')

        # NOTE(gibi): start a second compute host to be able to test affinity
        self.compute2 = self.start_service('compute', host='host2')

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
        #
        # NOTE(sdague): this is actually very much *not* how this
        # fixture should be used. This actually spawns a whole
        # additional API server. Should be addressed in the future.
        api_openstack1 = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version=self.api_major_version,
            project_id=PROJECT_ID_ALT)).api
        api_openstack1.microversion = self.microversion

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

    def test_create_duplicated_policy(self):
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_groups,
                               {"name": "fake-name-1",
                                "policies": ["affinity", "affinity"]})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Invalid input', ex.response.text)

    def test_create_multiple_policies(self):
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_groups,
                               {"name": "fake-name-1",
                                "policies": ["anti-affinity", "affinity"]})
        self.assertEqual(400, ex.response.status_code)

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

    def test_boot_servers_with_affinity_overquota(self):
        # Tests that we check server group member quotas and cleanup created
        # resources when we fail with OverQuota.
        self.flags(server_group_members=1, group='quota')
        # make sure we start with 0 servers
        servers = self.api.get_servers(detail=False)
        self.assertEqual(0, len(servers))
        created_group = self.api.post_server_groups(self.affinity)
        ex = self.assertRaises(client.OpenStackApiException,
                               self._boot_servers_to_group,
                               created_group)
        self.assertEqual(403, ex.response.status_code)
        # _boot_servers_to_group creates 2 instances in the group in order, not
        # multiple servers in a single request. Since our quota is 1, the first
        # server create would pass, the second should fail, and we should be
        # left with 1 server and it's 1 block device mapping.
        servers = self.api.get_servers(detail=False)
        self.assertEqual(1, len(servers))
        ctxt = context.get_admin_context()
        servers = db.instance_get_all(ctxt)
        self.assertEqual(1, len(servers))
        ctxt_mgr = db_api.get_context_manager(ctxt)
        with ctxt_mgr.reader.using(ctxt):
            bdms = db_api._block_device_mapping_get_query(ctxt).all()
        self.assertEqual(1, len(bdms))
        self.assertEqual(servers[0]['uuid'], bdms[0]['instance_uuid'])

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

        post = {'rebuild': {'imageRef':
                            '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'}}
        self.api.post_server_action(servers[1]['id'], post)

        rebuilt_server = self._wait_for_state_change(servers[1], 'ACTIVE')

        self.assertEqual(post['rebuild']['imageRef'],
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
        # NoValidHost errors are handled in conductor after the API has cast
        # off and returned a 202 response to the user.
        self.admin_api.post_server_action(servers[1]['id'], post,
                                          check_response_status=[202])
        # The instance action should have failed with details.
        self._assert_resize_migrate_action_fail(
            servers[1], instance_actions.MIGRATE, 'NoValidHost')

    def test_migrate_with_group_no_valid_host(self):
        for group in [self.affinity, self.anti_affinity]:
            self._migrate_with_group_no_valid_host(group)

    def test_migrate_with_anti_affinity(self):
        # Start additional host to test migration with anti-affinity
        self.start_service('compute', host='host3')

        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        post = {'migrate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        migrated_server = self._wait_for_state_change(
            servers[1], 'VERIFY_RESIZE')

        self.assertNotEqual(servers[0]['OS-EXT-SRV-ATTR:host'],
                            migrated_server['OS-EXT-SRV-ATTR:host'])

    def test_migrate_with_anti_affinity_confirm_updates_scheduler(self):
        # Start additional host to test migration with anti-affinity
        compute3 = self.start_service('compute', host='host3')

        # make sure that compute syncing instance info to scheduler
        # this tells the scheduler that it can expect such updates periodically
        # and don't have to look into the db for it at the start of each
        # scheduling
        for compute in [self.compute, self.compute2, compute3]:
            compute.manager._sync_scheduler_instance_info(
                context.get_admin_context())

        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        post = {'migrate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        migrated_server = self._wait_for_state_change(
            servers[1], 'VERIFY_RESIZE')

        self.assertNotEqual(servers[0]['OS-EXT-SRV-ATTR:host'],
                            migrated_server['OS-EXT-SRV-ATTR:host'])

        # We have 3 hosts, so after the move is confirmed one of the hosts
        # should be considered empty so we could boot a 3rd server on that host
        post = {'confirmResize': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_state_change(servers[1], 'ACTIVE')

        server3 = self._boot_a_server_to_group(created_group)

        # we have 3 servers that should occupy 3 different hosts
        hosts = {server['OS-EXT-SRV-ATTR:host']
                 for server in [servers[0], migrated_server, server3]}
        self.assertEqual(3, len(hosts))

    def test_resize_to_same_host_with_anti_affinity(self):
        self.flags(allow_resize_to_same_host=True)
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group,
                                              flavor=self.api.get_flavors()[0])

        post = {'resize': {'flavorRef': '2'}}
        server1_old_host = servers[1]['OS-EXT-SRV-ATTR:host']
        self.admin_api.post_server_action(servers[1]['id'], post)
        migrated_server = self._wait_for_state_change(
            servers[1], 'VERIFY_RESIZE')

        self.assertEqual(server1_old_host,
                         migrated_server['OS-EXT-SRV-ATTR:host'])

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

    def _set_forced_down(self, service, forced_down):
        # Use microversion 2.53 for PUT /os-services/{service_id} force down.
        with utils.temporary_mutation(self.admin_api, microversion='2.53'):
            self.admin_api.put_service_force_down(service.service_ref.uuid,
                                                  forced_down)

    def test_evacuate_with_anti_affinity(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        # Set forced_down on the host to ensure nova considers the host down.
        self._set_forced_down(host, True)

        # Start additional host to test evacuation
        self.start_service('compute', host='host3')

        post = {'evacuate': {'onSharedStorage': False}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_migration_status(servers[1], ['done'])
        evacuated_server = self._wait_for_state_change(servers[1], 'ACTIVE')

        # check that the server is evacuated to another host
        self.assertNotEqual(evacuated_server['OS-EXT-SRV-ATTR:host'],
                            servers[1]['OS-EXT-SRV-ATTR:host'])
        # check that anti-affinity policy is kept during evacuation
        self.assertNotEqual(evacuated_server['OS-EXT-SRV-ATTR:host'],
                            servers[0]['OS-EXT-SRV-ATTR:host'])

    def test_evacuate_with_anti_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        # Set forced_down on the host to ensure nova considers the host down.
        self._set_forced_down(host, True)

        post = {'evacuate': {'onSharedStorage': False}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_migration_status(servers[1], ['error'])
        server_after_failed_evac = self._wait_for_state_change(
            servers[1], 'ERROR')

        # assert that after a failed evac the server active on the same host
        # as before
        self.assertEqual(server_after_failed_evac['OS-EXT-SRV-ATTR:host'],
                         servers[1]['OS-EXT-SRV-ATTR:host'])

    def test_evacuate_with_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        # Set forced_down on the host to ensure nova considers the host down.
        self._set_forced_down(host, True)

        post = {'evacuate': {'onSharedStorage': False}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_migration_status(servers[1], ['error'])
        server_after_failed_evac = self._wait_for_state_change(
            servers[1], 'ERROR')

        # assert that after a failed evac the server active on the same host
        # as before
        self.assertEqual(server_after_failed_evac['OS-EXT-SRV-ATTR:host'],
                         servers[1]['OS-EXT-SRV-ATTR:host'])

    def test_soft_affinity_not_supported(self):
        ex = self.assertRaises(client.OpenStackApiException,
                               self.api.post_server_groups,
                               {'name': 'fake-name-1',
                                'policies': ['soft-affinity']})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Invalid input', ex.response.text)
        self.assertIn('soft-affinity', ex.response.text)


class ServerGroupAffinityConfTest(ServerGroupTestBase):
    api_major_version = 'v2.1'
    # Load only anti-affinity filter so affinity will be missing
    _enabled_filters = ['ServerGroupAntiAffinityFilter']

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
    api_major_version = 'v2.1'
    # Load only affinity filter so anti-affinity will be missing
    _enabled_filters = ['ServerGroupAffinityFilter']

    @mock.patch('nova.scheduler.utils._SUPPORTS_ANTI_AFFINITY', None)
    def test_anti_affinity_no_filter(self):
        created_group = self.api.post_server_groups(self.anti_affinity)

        failed_server = self._boot_a_server_to_group(created_group,
                                                     expected_status='ERROR')
        self.assertEqual('ServerGroup policy is not supported: '
                         'ServerGroupAntiAffinityFilter not configured',
                         failed_server['fault']['message'])
        self.assertEqual(400, failed_server['fault']['code'])


class ServerGroupSoftAffinityConfTest(ServerGroupTestBase):
    api_major_version = 'v2.1'
    microversion = '2.15'
    soft_affinity = {'name': 'fake-name-4',
                     'policies': ['soft-affinity']}

    def _get_weight_classes(self):
        # Load only soft-anti-affinity weigher so affinity will be missing
        return ['nova.scheduler.weights.affinity.'
                'ServerGroupSoftAntiAffinityWeigher']

    @mock.patch('nova.scheduler.utils._SUPPORTS_SOFT_AFFINITY', None)
    def test_soft_affinity_no_filter(self):
        created_group = self.api.post_server_groups(self.soft_affinity)

        failed_server = self._boot_a_server_to_group(created_group,
                                                     expected_status='ERROR')
        self.assertEqual('ServerGroup policy is not supported: '
                         'ServerGroupSoftAffinityWeigher not configured',
                         failed_server['fault']['message'])
        self.assertEqual(400, failed_server['fault']['code'])


class ServerGroupSoftAntiAffinityConfTest(ServerGroupTestBase):
    api_major_version = 'v2.1'
    microversion = '2.15'
    soft_anti_affinity = {'name': 'fake-name-3',
                          'policies': ['soft-anti-affinity']}

    def _get_weight_classes(self):
        # Load only soft affinity filter so anti-affinity will be missing
        return ['nova.scheduler.weights.affinity.'
                'ServerGroupSoftAffinityWeigher']

    @mock.patch('nova.scheduler.utils._SUPPORTS_SOFT_ANTI_AFFINITY', None)
    def test_soft_anti_affinity_no_filter(self):
        created_group = self.api.post_server_groups(self.soft_anti_affinity)

        failed_server = self._boot_a_server_to_group(created_group,
                                                     expected_status='ERROR')
        self.assertEqual('ServerGroup policy is not supported: '
                         'ServerGroupSoftAntiAffinityWeigher not configured',
                         failed_server['fault']['message'])
        self.assertEqual(400, failed_server['fault']['code'])


class ServerGroupTestV215(ServerGroupTestV21):
    api_major_version = 'v2.1'
    microversion = '2.15'

    soft_anti_affinity = {'name': 'fake-name-3',
                          'policies': ['soft-anti-affinity']}
    soft_affinity = {'name': 'fake-name-4',
                     'policies': ['soft-affinity']}

    def setUp(self):
        super(ServerGroupTestV215, self).setUp()

        soft_affinity_patcher = mock.patch(
            'nova.scheduler.utils._SUPPORTS_SOFT_AFFINITY')
        soft_anti_affinity_patcher = mock.patch(
            'nova.scheduler.utils._SUPPORTS_SOFT_ANTI_AFFINITY')
        self.addCleanup(soft_affinity_patcher.stop)
        self.addCleanup(soft_anti_affinity_patcher.stop)
        self.mock_soft_affinity = soft_affinity_patcher.start()
        self.mock_soft_anti_affinity = soft_anti_affinity_patcher.start()
        self.mock_soft_affinity.return_value = None
        self.mock_soft_anti_affinity.return_value = None

    def _get_weight_classes(self):
        return ['nova.scheduler.weights.affinity.'
                'ServerGroupSoftAffinityWeigher',
                'nova.scheduler.weights.affinity.'
                'ServerGroupSoftAntiAffinityWeigher']

    def test_evacuate_with_anti_affinity(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        # Set forced_down on the host to ensure nova considers the host down.
        self._set_forced_down(host, True)

        # Start additional host to test evacuation
        compute3 = self.start_service('compute', host='host3')

        post = {'evacuate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_migration_status(servers[1], ['done'])
        evacuated_server = self._wait_for_state_change(servers[1], 'ACTIVE')

        # check that the server is evacuated
        self.assertNotEqual(evacuated_server['OS-EXT-SRV-ATTR:host'],
                            servers[1]['OS-EXT-SRV-ATTR:host'])
        # check that policy is kept
        self.assertNotEqual(evacuated_server['OS-EXT-SRV-ATTR:host'],
                            servers[0]['OS-EXT-SRV-ATTR:host'])

        compute3.kill()

    def test_evacuate_with_anti_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        # Set forced_down on the host to ensure nova considers the host down.
        self._set_forced_down(host, True)

        post = {'evacuate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_migration_status(servers[1], ['error'])
        server_after_failed_evac = self._wait_for_state_change(
            servers[1], 'ERROR')

        # assert that after a failed evac the server active on the same host
        # as before
        self.assertEqual(server_after_failed_evac['OS-EXT-SRV-ATTR:host'],
                         servers[1]['OS-EXT-SRV-ATTR:host'])

    def test_evacuate_with_affinity_no_valid_host(self):
        created_group = self.api.post_server_groups(self.affinity)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        # Set forced_down on the host to ensure nova considers the host down.
        self._set_forced_down(host, True)

        post = {'evacuate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_migration_status(servers[1], ['error'])
        server_after_failed_evac = self._wait_for_state_change(
            servers[1], 'ERROR')

        # assert that after a failed evac the server active on the same host
        # as before
        self.assertEqual(server_after_failed_evac['OS-EXT-SRV-ATTR:host'],
                         servers[1]['OS-EXT-SRV-ATTR:host'])

    def _check_group_format(self, group, created_group):
        self.assertEqual(group['policies'], created_group['policies'])
        self.assertEqual({}, created_group['metadata'])
        self.assertNotIn('rules', created_group)

    def test_create_and_delete_groups(self):
        groups = [self.anti_affinity,
                  self.affinity,
                  self.soft_affinity,
                  self.soft_anti_affinity]

        created_groups = []

        for group in groups:
            created_group = self.api.post_server_groups(group)
            created_groups.append(created_group)
            self.assertEqual(group['name'], created_group['name'])
            self._check_group_format(group, created_group)
            self.assertEqual([], created_group['members'])
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

    def test_boot_servers_with_soft_affinity(self):
        created_group = self.api.post_server_groups(self.soft_affinity)
        servers = self._boot_servers_to_group(created_group)
        members = self.api.get_server_group(created_group['id'])['members']

        self.assertEqual(2, len(servers))
        self.assertIn(servers[0]['id'], members)
        self.assertIn(servers[1]['id'], members)
        self.assertEqual(servers[0]['OS-EXT-SRV-ATTR:host'],
                         servers[1]['OS-EXT-SRV-ATTR:host'])

    def test_boot_servers_with_soft_affinity_no_resource_on_first_host(self):
        created_group = self.api.post_server_groups(self.soft_affinity)

        # Using big enough flavor to use up the resources on the first host
        flavor = self.api.get_flavors()[2]
        servers = self._boot_servers_to_group(created_group, flavor)

        # The third server cannot be booted on the first host as there
        # is not enough resource there, but as opposed to the affinity policy
        # it will be booted on the other host, which has enough resources.
        third_server = self._boot_a_server_to_group(created_group,
                                                    flavor=flavor)
        members = self.api.get_server_group(created_group['id'])['members']
        hosts = []
        for server in servers:
            hosts.append(server['OS-EXT-SRV-ATTR:host'])

        self.assertIn(third_server['id'], members)
        self.assertNotIn(third_server['OS-EXT-SRV-ATTR:host'], hosts)

    def test_boot_servers_with_soft_anti_affinity(self):
        created_group = self.api.post_server_groups(self.soft_anti_affinity)
        servers = self._boot_servers_to_group(created_group)
        members = self.api.get_server_group(created_group['id'])['members']

        self.assertEqual(2, len(servers))
        self.assertIn(servers[0]['id'], members)
        self.assertIn(servers[1]['id'], members)
        self.assertNotEqual(servers[0]['OS-EXT-SRV-ATTR:host'],
                            servers[1]['OS-EXT-SRV-ATTR:host'])

    def test_boot_servers_with_soft_anti_affinity_one_available_host(self):
        self.compute2.kill()
        created_group = self.api.post_server_groups(self.soft_anti_affinity)
        servers = self._boot_servers_to_group(created_group)

        members = self.api.get_server_group(created_group['id'])['members']
        host = servers[0]['OS-EXT-SRV-ATTR:host']
        for server in servers:
            self.assertIn(server['id'], members)
            self.assertEqual(host, server['OS-EXT-SRV-ATTR:host'])

    def test_rebuild_with_soft_affinity(self):
        untouched_server, rebuilt_server = self._rebuild_with_group(
            self.soft_affinity)
        self.assertEqual(untouched_server['OS-EXT-SRV-ATTR:host'],
                         rebuilt_server['OS-EXT-SRV-ATTR:host'])

    def test_rebuild_with_soft_anti_affinity(self):
        untouched_server, rebuilt_server = self._rebuild_with_group(
            self.soft_anti_affinity)
        self.assertNotEqual(untouched_server['OS-EXT-SRV-ATTR:host'],
                            rebuilt_server['OS-EXT-SRV-ATTR:host'])

    def _migrate_with_soft_affinity_policies(self, group):
        created_group = self.api.post_server_groups(group)
        servers = self._boot_servers_to_group(created_group)

        post = {'migrate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        migrated_server = self._wait_for_state_change(
            servers[1], 'VERIFY_RESIZE')

        return [migrated_server['OS-EXT-SRV-ATTR:host'],
                servers[0]['OS-EXT-SRV-ATTR:host']]

    def test_migrate_with_soft_affinity(self):
        migrated_server, other_server = (
            self._migrate_with_soft_affinity_policies(self.soft_affinity))
        self.assertNotEqual(migrated_server, other_server)

    def test_migrate_with_soft_anti_affinity(self):
        migrated_server, other_server = (
            self._migrate_with_soft_affinity_policies(self.soft_anti_affinity))
        self.assertEqual(migrated_server, other_server)

    def _evacuate_with_soft_anti_affinity_policies(self, group):
        created_group = self.api.post_server_groups(group)
        servers = self._boot_servers_to_group(created_group)

        host = self._get_compute_service_by_host_name(
            servers[1]['OS-EXT-SRV-ATTR:host'])
        # Set forced_down on the host to ensure nova considers the host down.
        self._set_forced_down(host, True)

        post = {'evacuate': {}}
        self.admin_api.post_server_action(servers[1]['id'], post)
        self._wait_for_migration_status(servers[1], ['done'])
        evacuated_server = self._wait_for_state_change(servers[1], 'ACTIVE')

        # Note(gibi): need to get the server again as the state of the instance
        # goes to ACTIVE first then the host of the instance changes to the
        # new host later
        evacuated_server = self.admin_api.get_server(evacuated_server['id'])

        return [evacuated_server['OS-EXT-SRV-ATTR:host'],
                servers[0]['OS-EXT-SRV-ATTR:host']]

    def test_evacuate_with_soft_affinity(self):
        evacuated_server, other_server = (
            self._evacuate_with_soft_anti_affinity_policies(
                self.soft_affinity))
        self.assertNotEqual(evacuated_server, other_server)

    def test_evacuate_with_soft_anti_affinity(self):
        evacuated_server, other_server = (
            self._evacuate_with_soft_anti_affinity_policies(
                self.soft_anti_affinity))
        self.assertEqual(evacuated_server, other_server)

    def test_soft_affinity_not_supported(self):
        pass


class ServerGroupTestV264(ServerGroupTestV215):
    api_major_version = 'v2.1'
    microversion = '2.64'
    anti_affinity = {'name': 'fake-name-1', 'policy': 'anti-affinity'}
    affinity = {'name': 'fake-name-2', 'policy': 'affinity'}
    soft_anti_affinity = {'name': 'fake-name-3',
                          'policy': 'soft-anti-affinity'}
    soft_affinity = {'name': 'fake-name-4', 'policy': 'soft-affinity'}

    def _check_group_format(self, group, created_group):
        self.assertEqual(group['policy'], created_group['policy'])
        self.assertEqual(group.get('rules', {}), created_group['rules'])
        self.assertNotIn('metadata', created_group)
        self.assertNotIn('policies', created_group)

    def test_boot_server_with_anti_affinity_rules(self):
        anti_affinity_max_2 = {
            'name': 'fake-name-1',
            'policy': 'anti-affinity',
            'rules': {'max_server_per_host': 2}
        }
        created_group = self.api.post_server_groups(anti_affinity_max_2)
        servers1st = self._boot_servers_to_group(created_group)
        servers2nd = self._boot_servers_to_group(created_group)

        # We have 2 computes so the fifth server won't fit into the same group
        failed_server = self._boot_a_server_to_group(created_group,
                                                     expected_status='ERROR')
        self.assertEqual('No valid host was found. '
                         'There are not enough hosts available.',
                         failed_server['fault']['message'])

        hosts = map(lambda x: x['OS-EXT-SRV-ATTR:host'],
                    servers1st + servers2nd)
        hosts = [h for h in hosts]
        # 4 servers
        self.assertEqual(4, len(hosts))
        # schedule to 2 host
        self.assertEqual(2, len(set(hosts)))
        # each host has 2 servers
        for host in set(hosts):
            self.assertEqual(2, hosts.count(host))


class ServerGroupTestMultiCell(ServerGroupTestBase):

    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(ServerGroupTestMultiCell, self).setUp()
        # Start two compute services, one per cell
        self.compute1 = self.start_service('compute', host='host1',
                                           cell_name='cell1')
        self.compute2 = self.start_service('compute', host='host2',
                                           cell_name='cell2')
        # This is needed to find a server that is still booting with multiple
        # cells, while waiting for the state change to ACTIVE. See the
        # _get_instance method in the compute/api for details.
        self.useFixture(nova_fixtures.AllServicesCurrent())

        self.aggregates = {}

    def _create_aggregate(self, name):
        agg = self.admin_api.post_aggregate({'aggregate': {'name': name}})
        self.aggregates[name] = agg

    def _add_host_to_aggregate(self, agg, host):
        """Add a compute host to nova aggregates.

        :param agg: Name of the nova aggregate
        :param host: Name of the compute host
        """
        agg = self.aggregates[agg]
        self.admin_api.add_host_to_aggregate(agg['id'], host)

    def _set_az_aggregate(self, agg, az):
        """Set the availability_zone of an aggregate

        :param agg: Name of the nova aggregate
        :param az: Availability zone name
        """
        agg = self.aggregates[agg]
        action = {
            'set_metadata': {
                'metadata': {
                    'availability_zone': az,
                }
            },
        }
        self.admin_api.post_aggregate_action(agg['id'], action)

    def test_boot_servers_with_affinity(self):
        # Create a server group for affinity
        # As of microversion 2.64, a single policy must be specified when
        # creating a server group.
        created_group = self.api.post_server_groups(self.affinity)
        # Create aggregates for cell1 and cell2
        self._create_aggregate('agg1_cell1')
        self._create_aggregate('agg2_cell2')
        # Add each cell to a separate aggregate
        self._add_host_to_aggregate('agg1_cell1', 'host1')
        self._add_host_to_aggregate('agg2_cell2', 'host2')
        # Set each cell to a separate availability zone
        self._set_az_aggregate('agg1_cell1', 'cell1')
        self._set_az_aggregate('agg2_cell2', 'cell2')
        # Boot a server to cell2 with the affinity policy. Order matters here
        # because the CellDatabases fixture defaults the local cell database to
        # cell1. So boot the server to cell2 where the group member cannot be
        # found as a result of the default setting.
        self._boot_a_server_to_group(created_group, az='cell2')
        # Boot a server to cell1 with the affinity policy. This should fail
        # because group members found in cell2 should violate the policy.
        self._boot_a_server_to_group(created_group, az='cell1',
                                     expected_status='ERROR')


class TestAntiAffinityLiveMigration(test.TestCase,
                                    integrated_helpers.InstanceHelperMixin):

    def setUp(self):
        super(TestAntiAffinityLiveMigration, self).setUp()
        # Setup common fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        # Setup API.
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

        # Start conductor, scheduler and two computes.
        self.start_service('conductor')
        self.start_service('scheduler')
        for host in ('host1', 'host2'):
            self.start_service('compute', host=host)

    def test_serial_no_valid_host_then_pass_with_third_host(self):
        """Creates 2 servers in order (not a multi-create request) in an
        anti-affinity group so there will be 1 server on each host. Then
        attempts to live migrate the first server which will fail because the
        only other available host will be full. Then starts up a 3rd compute
        service and retries the live migration which should then pass.
        """
        # Create the anti-affinity group used for the servers.
        group = self.api.post_server_groups(
            {'name': 'test_serial_no_valid_host_then_pass_with_third_host',
             'policies': ['anti-affinity']})
        servers = []
        for _ in range(2):
            server = self._build_server(networks='none')
            # Add the group hint so the server is created in our group.
            server_req = {
                'server': server,
                'os:scheduler_hints': {'group': group['id']}
            }
            # Use microversion 2.37 for passing networks='none'.
            with utils.temporary_mutation(self.api, microversion='2.37'):
                server = self.api.post_server(server_req)
                servers.append(
                    self._wait_for_state_change(server, 'ACTIVE'))

        # Make sure each server is on a unique host.
        hosts = set([svr['OS-EXT-SRV-ATTR:host'] for svr in servers])
        self.assertEqual(2, len(hosts))

        # And make sure the group has 2 members.
        members = self.api.get_server_group(group['id'])['members']
        self.assertEqual(2, len(members))

        # Now attempt to live migrate one of the servers which should fail
        # because we don't have a free host. Since we're using microversion 2.1
        # the scheduling will be synchronous and we should get back a 400
        # response for the NoValidHost error.
        body = {
            'os-migrateLive': {
                'host': None,
                'block_migration': False,
                'disk_over_commit': False
            }
        }
        # Specifically use the first server since that was the first member
        # added to the group.
        server = servers[0]
        ex = self.assertRaises(client.OpenStackApiException,
                               self.admin_api.post_server_action,
                               server['id'], body)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('No valid host', six.text_type(ex))

        # Now start up a 3rd compute service and retry the live migration which
        # should work this time.
        self.start_service('compute', host='host3')
        self.admin_api.post_server_action(server['id'], body)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # Now the server should be on host3 since that was the only available
        # host for the live migration.
        self.assertEqual('host3', server['OS-EXT-SRV-ATTR:host'])
