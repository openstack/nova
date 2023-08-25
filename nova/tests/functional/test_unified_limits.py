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

from oslo_limit import fixture as limit_fixture
from oslo_serialization import base64
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context as nova_context
from nova.limit import local as local_limit
from nova.objects import flavor as flavor_obj
from nova.objects import instance_group as group_obj
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
