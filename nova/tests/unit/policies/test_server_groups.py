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
import functools

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import server_groups
import nova.conf
from nova import objects
from nova.policies import server_groups as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base

CONF = nova.conf.CONF


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

        # With legacy rule and no scope checks, all admin, project members
        # project reader or project any role(because legacy rule allow SG
        # owner- having same project id and no role check) is able to
        # delete and get SG.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
        ]
        # By default, legacy rule are enabled and scope check is disabled.
        # system admin, legacy admin, and project admin is able to get
        # all projects SG.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

        # List SG can not check for project id so everyone is allowed.
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]

        # With legacy rule, anyone can create SG.
        self.project_create_authorized_contexts = (
            self.everyone_authorized_contexts)

    @mock.patch('nova.objects.InstanceGroupList.get_by_project_id')
    def test_index_server_groups_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'index'
        self.common_policy_auth(self.everyone_authorized_contexts,
                                rule_name,
                                self.controller.index,
                                self.req)

    @mock.patch('nova.objects.InstanceGroupList.get_all')
    @mock.patch('nova.objects.InstanceGroupList.get_by_project_id')
    def test_index_all_project_server_groups_policy(self, mock_get,
            mock_get_all):
        mock_get_all.return_value = objects.InstanceGroupList(objects=self.sg)
        mock_get.return_value = objects.InstanceGroupList(
            objects=[self.sg[0]])
        # 'index' policy is checked before 'index:all_projects' so
        # we have to allow it for everyone otherwise it will fail for
        # unauthorized contexts here.
        rule = policies.POLICY_ROOT % 'index'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        rule_name = policies.POLICY_ROOT % 'index:all_projects'
        req = fakes.HTTPRequest.blank('?all_projects', version='2.13')
        if not CONF.oslo_policy.enforce_scope:
            check_rule = rule_name
        else:
            check_rule = functools.partial(base.rule_if_system,
                rule, rule_name)
        authorize_res, unauthorize_res = self.common_policy_auth(
            self.project_admin_authorized_contexts,
            check_rule, self.controller.index,
            req, fatal=False)
        for resp in authorize_res:
            projs = [sg['project_id'] for sg in resp['server_groups']]
            self.assertEqual(2, len(projs))
            self.assertIn('proj2', projs)
        for resp in unauthorize_res:
            projs = [sg['project_id'] for sg in resp['server_groups']]
            self.assertNotIn('proj2', projs)

    def test_show_server_groups_policy(self):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_auth(
            self.project_reader_authorized_contexts,
            rule_name,
            self.controller.show,
            self.req, uuids.fake_id)

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_create_server_groups_policy(self, mock_quota):
        rule_name = policies.POLICY_ROOT % 'create'
        body = {'server_group': {'name': 'fake',
                                 'policies': ['affinity']}}
        self.common_policy_auth(self.project_create_authorized_contexts,
                                rule_name,
                                self.controller.create,
                                self.req, body=body)

    @mock.patch('nova.objects.InstanceGroup.destroy')
    def test_delete_server_groups_policy(self, mock_destroy):
        rule_name = policies.POLICY_ROOT % 'delete'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.delete,
                                self.req, uuids.fake_id)


class ServerGroupNoLegacyNoScopePolicyTest(ServerGroupPolicyTest):
    """Test Server Groups APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only.

    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerGroupNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy, only project admin, member will be able to delete
        # the SG and also reader will be able to get the SG.
        self.project_member_authorized_contexts = [
            self.project_admin_context, self.project_member_context]

        self.project_reader_authorized_contexts = [
            self.project_admin_context, self.project_member_context,
            self.project_reader_context]

        # Even with no legacy rule, legacy admin is allowed to create SG
        # use requesting context's project_id. Same for list SG.
        self.project_create_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.system_member_context, self.other_project_member_context]

        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.other_project_member_context
        ]


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

        # With scope enable, it disallow system users.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context,
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context,
        ]

        self.project_create_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context, self.other_project_reader_context,
            self.other_project_member_context]

        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]

        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.other_project_member_context
        ]


class ServerGroupScopeTypeNoLegacyPolicyTest(ServerGroupScopeTypePolicyTest):
    """Test Server Group APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerGroupScopeTypeNoLegacyPolicyTest, self).setUp()

        self.project_member_authorized_contexts = [
            self.project_admin_context, self.project_member_context]

        self.project_create_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context,
            self.other_project_member_context]

        self.project_reader_authorized_contexts = [
            self.project_admin_context, self.project_member_context,
            self.project_reader_context]

        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]

        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_reader_context,
            self.other_project_member_context
        ]
