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

from unittest import mock

from oslo_limit import fixture as limit_fixture
from oslo_serialization import base64
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context as nova_context
from nova.limit import local as local_limit
from nova.objects import flavor as flavor_obj
from nova.objects import instance_group as group_obj
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class UnifiedLimitsTest(integrated_helpers._IntegratedTestBase):

    def setUp(self):
        super(UnifiedLimitsTest, self).setUp()
        # Use different project_ids for non-admin and admin.
        self.api.project_id = 'fake'
        self.admin_api.project_id = 'admin'

        self.flags(driver="nova.quota.UnifiedLimitsDriver", group="quota")
        reglimits = {local_limit.SERVER_METADATA_ITEMS: 128,
                     local_limit.INJECTED_FILES: 5,
                     local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
                     local_limit.INJECTED_FILES_PATH: 255,
                     local_limit.KEY_PAIRS: 100,
                     local_limit.SERVER_GROUPS: 10,
                     local_limit.SERVER_GROUP_MEMBERS: 1,
                     'servers': 4,
                     'class:VCPU': 8,
                     'class:MEMORY_MB': 32768,
                     'class:DISK_GB': 250}
        projlimits = {self.api.project_id: {'servers': 2,
                                            'class:VCPU': 4,
                                            'class:MEMORY_MB': 16384,
                                            'class:DISK_GB': 100}}
        self.useFixture(limit_fixture.LimitFixture(reglimits, projlimits))
        self.ctx = nova_context.get_admin_context()

    def _setup_services(self):
        # Use driver with lots of resources so we don't get NoValidHost while
        # testing quotas. Need to do this before services are started.
        self.flags(compute_driver='fake.FakeDriver')
        super(UnifiedLimitsTest, self)._setup_services()

    def test_servers(self):
        # First test the project limit using the non-admin project.
        for i in range(2):
            self._create_server(api=self.api)

        # Attempt to create a third server should fail.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('servers', e.response.text)

        # Then test the default limit using the admin project.
        for i in range(4):
            self._create_server(api=self.admin_api)

        # Attempt to create a fifth server should fail.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server,
            api=self.admin_api)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('servers', e.response.text)

    def test_vcpu(self):
        # First test the project limit using the non-admin project.
        # m1.large has vcpus=4 and our project limit is 4, should succeed.
        flavor = flavor_obj.Flavor.get_by_name(self.ctx, 'm1.large')
        self._create_server(api=self.api, flavor_id=flavor.flavorid)

        # m1.small has vcpus=1, should fail because we are at quota.
        flavor = flavor_obj.Flavor.get_by_name(self.ctx, 'm1.small')
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api,
            flavor_id=flavor.flavorid)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('class:VCPU', e.response.text)

        # Then test the default limit of 8 using the admin project.
        flavor = flavor_obj.Flavor.get_by_name(self.ctx, 'm1.large')
        for i in range(2):
            self._create_server(api=self.admin_api, flavor_id=flavor.flavorid)

        # Attempt to create another server with vcpus=1 should fail because we
        # are at quota.
        flavor = flavor_obj.Flavor.get_by_name(self.ctx, 'm1.small')
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server,
            api=self.admin_api, flavor_id=flavor.flavorid)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('class:VCPU', e.response.text)

    def test_memory_mb(self):
        # First test the project limit using the non-admin project.
        flavor = flavor_obj.Flavor(
            context=self.ctx, memory_mb=16384, vcpus=1, root_gb=1,
            flavorid='9', name='m1.custom')
        flavor.create()
        self._create_server(api=self.api, flavor_id=flavor.flavorid)

        # Attempt to create another should fail as we are at quota.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api,
            flavor_id=flavor.flavorid)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('class:MEMORY_MB', e.response.text)

        # Then test the default limit of 32768 using the admin project.
        for i in range(2):
            self._create_server(api=self.admin_api, flavor_id=flavor.flavorid)

        # Attempt to create another server should fail because we are at quota.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server,
            api=self.admin_api, flavor_id=flavor.flavorid)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('class:MEMORY_MB', e.response.text)

    def test_disk_gb(self):
        # First test the project limit using the non-admin project.
        flavor = flavor_obj.Flavor(
            context=self.ctx, memory_mb=1, vcpus=1, root_gb=100,
            flavorid='9', name='m1.custom')
        flavor.create()
        self._create_server(api=self.api, flavor_id=flavor.flavorid)

        # Attempt to create another should fail as we are at quota.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api,
            flavor_id=flavor.flavorid)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('class:DISK_GB', e.response.text)

        # Then test the default limit of 250 using the admin project.
        for i in range(2):
            self._create_server(api=self.admin_api, flavor_id=flavor.flavorid)

        # Attempt to create another server should fail because we are at quota.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server,
            api=self.admin_api, flavor_id=flavor.flavorid)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('class:DISK_GB', e.response.text)

    def test_no_injected_files(self):
        self._create_server()

    def test_max_injected_files(self):
        # Quota is 5.
        files = []
        contents = base64.encode_as_text('some content')
        for i in range(5):
            files.append(('/my/path%d' % i, contents))
        server = self._build_server()
        personality = [
            {'path': item[0], 'contents': item[1]} for item in files]
        server['personality'] = personality
        server = self.api.post_server({'server': server})
        self.api.delete_server(server['id'])

    def test_max_injected_file_content_bytes(self):
        # Quota is 10 * 1024
        # Hm, apparently quota is checked against the base64 encoded string
        # even though the api-ref claims the limit is for the decoded data.
        # Subtract 3072 characters to account for that.
        content = base64.encode_as_bytes(
            ''.join(['a' for i in range(10 * 1024 - 3072)]))
        server = self._build_server()
        personality = [{'path': '/test/path', 'contents': content}]
        server['personality'] = personality
        server = self.api.post_server({'server': server})
        self.api.delete_server(server['id'])

    def test_max_injected_file_path_bytes(self):
        # Quota is 255.
        path = ''.join(['a' for i in range(255)])
        contents = base64.encode_as_text('some content')
        server = self._build_server()
        personality = [{'path': path, 'contents': contents}]
        server['personality'] = personality
        server = self.api.post_server({'server': server})
        self.api.delete_server(server['id'])

    def test_server_group_members(self):
        # Create a server group.
        instance_group = group_obj.InstanceGroup(
            self.ctx, policy="anti-affinity")
        instance_group.name = "foo"
        instance_group.project_id = self.ctx.project_id
        instance_group.user_id = self.ctx.user_id
        instance_group.uuid = uuids.instance_group
        instance_group.create()

        # Quota for server group members is 1.
        server = self._build_server()
        hints = {'group': uuids.instance_group}
        req = {'server': server, 'os:scheduler_hints': hints}
        server = self.admin_api.post_server(req)

        # Attempt to create another server in the group should fail because we
        # are at quota.
        e = self.assertRaises(
            client.OpenStackApiException, self.admin_api.post_server, req)
        self.assertEqual(403, e.response.status_code)
        self.assertIn('server_group_members', e.response.text)

        self.admin_api.delete_server(server['id'])


class ResourceStrategyTest(integrated_helpers._IntegratedTestBase):

    def setUp(self):
        super().setUp()
        # Use different project_ids for non-admin and admin.
        self.api.project_id = 'fake'
        self.admin_api.project_id = 'admin'

        self.flags(driver="nova.quota.UnifiedLimitsDriver", group='quota')
        self.ctx = nova_context.get_admin_context()
        self.ul_api = self.useFixture(nova_fixtures.UnifiedLimitsFixture())

    def test_invalid_value_in_resource_list(self):
        # First two have casing issues, next doesn't have the "class:" prefix,
        # last is a typo.
        invalid_names = (
            'class:vcpu', 'class:CUSTOM_thing', 'VGPU', 'class:MEMRY_MB')
        for name in invalid_names:
            e = self.assertRaises(
                ValueError, self.flags, unified_limits_resource_list=[name],
                group='quota')
            self.assertIsInstance(e, ValueError)
            self.assertIn('not a valid resource class name', str(e))

    def test_valid_custom_resource_classes(self):
        valid_names = ('class:CUSTOM_GOLD', 'class:CUSTOM_A5_1')
        for name in valid_names:
            self.flags(unified_limits_resource_list=[name], group='quota')

    @mock.patch('nova.limit.utils.LOG.error')
    def test_invalid_strategy_configuration(self, mock_log_error):
        # Quota should be enforced and fail the check if there is somehow an
        # invalid strategy value.
        self.stub_out(
            'nova.limit.utils.CONF.quota.unified_limits_resource_strategy',
            'bogus')
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server)
        self.assertEqual(403, e.response.status_code)
        expected = (
            'Invalid strategy value: bogus is specified in the '
            '[quota]unified_limits_resource_strategy config option, so '
            'enforcing for resources')
        mock_log_error.assert_called()
        self.assertIn(expected, mock_log_error.call_args.args[0])

    @mock.patch('nova.limit.utils.LOG.debug')
    def test_required_limits_set(self, mock_log_debug):
        # Required resources configured are: 'servers', MEMORY_MB, and VCPU
        self.flags(unified_limits_resource_strategy='require', group='quota')
        require = ['servers', 'class:MEMORY_MB', 'class:VCPU']
        self.flags(unified_limits_resource_list=require, group='quota')
        # Purposely not setting any quota for DISK_GB.
        self.ul_api.create_registered_limit(
            resource_name='servers', default_limit=4)
        self.ul_api.create_registered_limit(
            resource_name='class:VCPU', default_limit=8)
        self.ul_api.create_registered_limit(
            resource_name='class:MEMORY_MB', default_limit=32768)
        # Server create should succeed because required resources VCPU,
        # MEMORY_MB, and 'servers' have registered limits.
        self._create_server()
        unset_limits = set(['class:DISK_GB'])
        call = mock.call(
            f'Resources {unset_limits} have no registered limits set in '
            f'Keystone. [quota]unified_limits_resource_strategy is require '
            f'and [quota]unified_limits_resource_list is {require}, so not '
            'enforcing')
        # The message will be logged twice -- once in nova-api and once in
        # nova-conductor because of the quota recheck after resource creation.
        self.assertEqual([call, call], mock_log_debug.mock_calls)

    def test_some_required_limits_not_set(self):
        # Now add DISK_GB as a required resource.
        self.flags(unified_limits_resource_strategy='require', group='quota')
        self.flags(unified_limits_resource_list=[
            'servers', 'class:MEMORY_MB', 'class:VCPU', 'class:DISK_GB'],
            group='quota')
        # Purposely not setting any quota for DISK_GB.
        self.ul_api.create_registered_limit(
            resource_name='servers', default_limit=-1)
        self.ul_api.create_registered_limit(
            resource_name='class:VCPU', default_limit=8)
        self.ul_api.create_registered_limit(
            resource_name='class:MEMORY_MB', default_limit=32768)
        # Server create should fail because required resource DISK_GB does not
        # have a registered limit set.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api)
        self.assertEqual(403, e.response.status_code)

    @mock.patch('nova.limit.utils.LOG.debug')
    def test_no_required_limits(self, mock_log_debug):
        # Configured to not require any resource limits.
        self.flags(unified_limits_resource_strategy='require', group='quota')
        self.flags(unified_limits_resource_list=[], group='quota')
        # Server create should succeed because no resource registered limits
        # are required to be set.
        self._create_server()
        # The message will be logged twice -- once in nova-api and once in
        # nova-conductor because of the quota recheck after resource creation.
        self.assertEqual(2, mock_log_debug.call_count)

    @mock.patch('nova.limit.utils.LOG.debug')
    def test_ignored_limits_set(self, mock_log_debug):
        # Ignored unset limit resources configured is DISK_GB.
        self.flags(unified_limits_resource_strategy='ignore', group='quota')
        ignore = ['class:DISK_GB']
        self.flags(unified_limits_resource_list=ignore, group='quota')
        # Purposely not setting any quota for DISK_GB.
        self.ul_api.create_registered_limit(
            resource_name='servers', default_limit=4)
        self.ul_api.create_registered_limit(
            resource_name='class:VCPU', default_limit=8)
        self.ul_api.create_registered_limit(
            resource_name='class:MEMORY_MB', default_limit=32768)
        # Server create should succeed because class:DISK_GB is specified in
        # the ignore unset limit list.
        self._create_server()
        unset_limits = set(['class:DISK_GB'])
        call = mock.call(
            f'Resources {unset_limits} have no registered limits set in '
            f'Keystone. [quota]unified_limits_resource_strategy is ignore and '
            f'[quota]unified_limits_resource_list is {ignore}, so not '
            'enforcing')
        # The message will be logged twice -- once in nova-api and once in
        # nova-conductor because of the quota recheck after resource creation.
        self.assertEqual([call, call], mock_log_debug.mock_calls)

    def test_some_ignored_limits_not_set(self):
        # Configured to ignore only one unset resource limit.
        self.flags(unified_limits_resource_strategy='ignore', group='quota')
        self.flags(unified_limits_resource_list=[
            'class:DISK_GB'], group='quota')
        # Purposely not setting any quota for servers.
        self.ul_api.create_registered_limit(
            resource_name='class:VCPU', default_limit=8)
        self.ul_api.create_registered_limit(
            resource_name='class:MEMORY_MB', default_limit=32768)
        # Server create should fail because although resource DISK_GB does not
        # have a registered limit set and it is in the ignore list, resource
        # 'servers' does not have a limit set and it is not in the ignore list.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api)
        self.assertEqual(403, e.response.status_code)

    def test_no_ignored_limits(self):
        # Configured to not ignore any unset resource limits.
        self.flags(unified_limits_resource_strategy='ignore', group='quota')
        self.flags(unified_limits_resource_list=[], group='quota')
        # Server create should fail because resource DISK_GB does not have a
        # registered limit set and it is not in the ignore list.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api)
        self.assertEqual(403, e.response.status_code)

    def test_all_unlimited(self):
        # -1 is documented in Keystone as meaning unlimited:
        #
        # https://docs.openstack.org/keystone/latest/admin/unified-limits.html#what-is-a-limit
        #
        # but oslo.limit enforce does not treat -1 as unlimited at this time
        # and instead uses its literal integer value.
        #
        # Test that we consider -1 to be unlimited in Nova and the server
        # create should succeed.
        for resource in (
                'servers', 'class:VCPU', 'class:MEMORY_MB', 'class:DISK_GB'):
            self.ul_api.create_registered_limit(
                resource_name=resource, default_limit=-1)
        self._create_server()

    def test_default_unlimited_but_project_limited(self):
        # If the default limit is set to -1 unlimited but the project has a
        # limit, quota should be enforced at the project level.
        # Note that it is not valid to set a project limit without first
        # setting a registered limit -- Keystone will not allow it.
        self.ul_api.create_registered_limit(
            resource_name='servers', default_limit=-1)
        self.ul_api.create_limit(
            project_id='fake', resource_name='servers', resource_limit=1)
        # First server should succeed because we have a project limit of 1.
        self._create_server()
        # Second server should fail because it would exceed the project limit
        # of 1.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server, api=self.api)
        self.assertEqual(403, e.response.status_code)

    def test_default_limited_but_project_unlimited(self):
        # If the default limit is set to a value but the project has a limit
        # set to -1 unlimited, quota should be enforced at the project level.
        # Note that it is not valid to set a project limit without first
        # setting a registered limit -- Keystone will not allow it.
        self.ul_api.create_registered_limit(
            resource_name='servers', default_limit=0)
        self.ul_api.create_limit(
            project_id='fake', resource_name='servers', resource_limit=-1)
        # First server should succeed because we have a default limit of 0 and
        # a project limit of -1 unlimited.
        self._create_server()
        # Try to create a server in a different project (admin project) -- this
        # should fail because the default limit has been explicitly set to 0.
        e = self.assertRaises(
            client.OpenStackApiException, self._create_server,
            api=self.admin_api)
        self.assertEqual(403, e.response.status_code)
