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

from nova.api.openstack.compute import server_metadata
from nova.policies import server_metadata as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ServerMetadataPolicyTest(base.BasePolicyTest):
    """Test Server Metadata APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerMetadataPolicyTest, self).setUp()
        self.controller = server_metadata.ServerMetadataController()
        self.req = fakes.HTTPRequest.blank('')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id)
        self.mock_get.return_value = self.instance

        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow server
        # owner- having same project id and no role check) is able to create,
        # update, and delete the server metadata.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # and they can get their own server metadata.
        self.project_reader_authorized_contexts = (
            self.project_member_authorized_contexts)

    @mock.patch('nova.compute.api.API.get_instance_metadata')
    def test_index_server_Metadata_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'index'
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.index,
                                self.req, self.instance.uuid)

    @mock.patch('nova.compute.api.API.get_instance_metadata')
    def test_show_server_Metadata_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'show'
        mock_get.return_value = {'key9': 'value'}
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, self.instance.uuid, 'key9')

    @mock.patch('nova.compute.api.API.update_instance_metadata')
    def test_create_server_Metadata_policy(self, mock_quota):
        rule_name = policies.POLICY_ROOT % 'create'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.create,
                                self.req, self.instance.uuid,
                                body={"metadata": {"key9": "value9"}})

    @mock.patch('nova.compute.api.API.update_instance_metadata')
    def test_update_server_Metadata_policy(self, mock_quota):
        rule_name = policies.POLICY_ROOT % 'update'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.update,
                                self.req, self.instance.uuid, 'key9',
                                body={"meta": {"key9": "value9"}})

    @mock.patch('nova.compute.api.API.update_instance_metadata')
    def test_update_all_server_Metadata_policy(self, mock_quota):
        rule_name = policies.POLICY_ROOT % 'update_all'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.update_all,
                                self.req, self.instance.uuid,
                                body={"metadata": {"key9": "value9"}})

    @mock.patch('nova.compute.api.API.get_instance_metadata')
    @mock.patch('nova.compute.api.API.delete_instance_metadata')
    def test_delete_server_Metadata_policy(self, mock_delete, mock_get):
        rule_name = policies.POLICY_ROOT % 'delete'
        mock_get.return_value = {'key9': 'value'}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.delete,
                                self.req, self.instance.uuid, 'key9')


class ServerMetadataNoLegacyNoScopePolicyTest(ServerMetadataPolicyTest):
    """Test Server Metadata APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only.

    """

    without_deprecated_rules = True

    def setUp(self):
        super(ServerMetadataNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, legacy admin loose power.
        self.project_member_authorized_contexts = [
            self.project_admin_context, self.project_member_context]
        self.project_reader_authorized_contexts = [
            self.project_admin_context, self.project_member_context,
            self.project_reader_context]


class ServerMetadataScopeTypePolicyTest(ServerMetadataPolicyTest):
    """Test Server Metadata APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerMetadataScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With Scope enable, system users no longer allowed.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        self.project_reader_authorized_contexts = (
            self.project_member_authorized_contexts)


class ServerMetadataScopeTypeNoLegacyPolicyTest(
        ServerMetadataScopeTypePolicyTest):
    """Test Server Metadata APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerMetadataScopeTypeNoLegacyPolicyTest, self).setUp()
        # With no legacy and scope enable, only project admin, member,
        # and reader will be able to allowed operation on server metadata.
        self.project_member_authorized_contexts = [
            self.project_admin_context, self.project_member_context]
        self.project_reader_authorized_contexts = [
            self.project_admin_context, self.project_member_context,
            self.project_reader_context]
