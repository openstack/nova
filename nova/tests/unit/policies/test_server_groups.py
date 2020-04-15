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

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import server_groups
from nova import objects
from nova.policies import server_groups as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class ServerGroupPolicyTest(base.BasePolicyTest):
    """Test Server Groups APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerGroupPolicyTest, self).setUp()
        self.controller = server_groups.ServerGroupController()
        self.req = fakes.HTTPRequest.blank('')

        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.objects.InstanceGroup.get_by_uuid')).mock
        self.sg = [objects.InstanceGroup(
                    uuid=uuids.fake_id, name='fake',
                    project_id=self.project_id, user_id='u1',
                    policies=[], members=[]),
                   objects.InstanceGroup(
                    uuid=uuids.fake_id, name='fake2', project_id='proj2',
                    user_id='u2', policies=[], members=[])]
        self.mock_get.return_value = self.sg[0]

        # Check that admin or and owner is able to delete
        # the server group.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin/owner is not able to delete
        # the server group.
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]
        # Check that system reader or owner is able to get
        # the server group. Due to old default everyone
        # is allowed to perform this operation.
        self.system_reader_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.system_member_context,
            self.system_reader_context, self.project_foo_context
        ]
        self.system_reader_or_owner_unauthorized_contexts = [
            self.system_foo_context,
            self.other_project_member_context
        ]
        # Check that everyone is able to list
        # theie own server group. Due to old defaults everyone
        # is able to list their server groups.
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context]
        self.everyone_unauthorized_contexts = [
        ]
        # Check that project member is able to create server group.
        # Due to old defaults everyone is able to list their server groups.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.system_member_context, self.project_reader_context,
            self.project_foo_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context]
        self.project_member_unauthorized_contexts = []

    @mock.patch('nova.objects.InstanceGroupList.get_by_project_id')
    def test_index_server_groups_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'index'
        self.common_policy_check(self.everyone_authorized_contexts,
                                 self.everyone_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 self.req)

    @mock.patch('nova.objects.InstanceGroupList.get_all')
    def test_index_all_project_server_groups_policy(self, mock_get_all):
        mock_get_all.return_value = objects.InstanceGroupList(objects=self.sg)
        # 'index' policy is checked before 'index:all_projects' so
        # we have to allow it for everyone otherwise it will fail for
        # unauthorized contexts here.
        rule = policies.POLICY_ROOT % 'index'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        admin_req = fakes.HTTPRequest.blank(
            '/os-server-groups?all_projects=True',
            version='2.13', use_admin_context=True)
        # Check admin user get all projects server groups.
        resp = self.controller.index(admin_req)
        projs = [sg['project_id'] for sg in resp['server_groups']]
        self.assertEqual(2, len(projs))
        self.assertIn('proj2', projs)
        # Check non-admin user does not get all projects server groups.
        req = fakes.HTTPRequest.blank('/os-server-groups?all_projects=True',
                                      version='2.13')
        resp = self.controller.index(req)
        projs = [sg['project_id'] for sg in resp['server_groups']]
        self.assertNotIn('proj2', projs)

    def test_show_server_groups_policy(self):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_check(
            self.system_reader_or_owner_authorized_contexts,
            self.system_reader_or_owner_unauthorized_contexts,
            rule_name,
            self.controller.show,
            self.req, uuids.fake_id)

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_create_server_groups_policy(self, mock_quota):
        rule_name = policies.POLICY_ROOT % 'create'
        body = {'server_group': {'name': 'fake',
                                 'policies': ['affinity']}}
        self.common_policy_check(self.project_member_authorized_contexts,
                                 self.project_member_unauthorized_contexts,
                                 rule_name,
                                 self.controller.create,
                                 self.req, body=body)

    @mock.patch('nova.objects.InstanceGroup.destroy')
    def test_delete_server_groups_policy(self, mock_destroy):
        rule_name = policies.POLICY_ROOT % 'delete'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.delete,
                                 self.req, uuids.fake_id)


class ServerGroupScopeTypePolicyTest(ServerGroupPolicyTest):
    """Test Server Groups APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerGroupScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check if project scoped can create the server group.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context,
            self.other_project_member_context
        ]
        # Check if non-project scoped cannot create the server group.
        self.project_member_unauthorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context
        ]

    # TODO(gmann): Test this with system scope once we remove
    # the hardcoded admin check
    def test_index_all_project_server_groups_policy(self):
        pass


class ServerGroupNoLegacyPolicyTest(ServerGroupScopeTypePolicyTest):
    """Test Server Group APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerGroupNoLegacyPolicyTest, self).setUp()

        # Check that system admin or and owner is able to delete
        # the server group.
        self.admin_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context,
        ]
        # Check that non-system admin/owner is not able to delete
        # the server group.
        self.admin_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context
        ]
        # Check that system reader or owner is able to get
        # the server group.
        self.system_reader_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.system_member_context,
            self.system_reader_context
        ]
        self.system_reader_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.other_project_member_context, self.project_foo_context
        ]
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.other_project_member_context
        ]
        self.everyone_unauthorized_contexts = [
            self.project_foo_context,
            self.system_foo_context
        ]
        # Check if project member can create the server group.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.other_project_member_context
        ]
        # Check if non-project member cannot create the server group.
        self.project_member_unauthorized_contexts = [
            self.system_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_reader_context,
            self.project_foo_context,
        ]
