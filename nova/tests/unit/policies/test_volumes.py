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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import volumes
from nova.policies import base as base_policy
from nova.policies import volumes as v_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class VolumesPolicyTest(base.BasePolicyTest):
    """Test Volumes APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super().setUp()
        self.controller = volumes.VolumeController()
        self.req = fakes.HTTPRequest.blank('')
        self.controller._translate_volume_summary_view = mock.MagicMock()
        # Everyone will be able to perform crud operations
        # on volume and volume snapshots.
        # NOTE: Nova cannot verify the volume/snapshot owner during nova policy
        # enforcement so will be passing context's project_id as target to
        # policy and always pass. If requester is not admin or owner
        # of volume/snapshot then cinder will be returning the appropriate
        # error.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_manager_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_manager_context,
            self.other_project_member_context
        ]

    @mock.patch('nova.volume.cinder.API.get_all')
    def test_list_volumes_policy(self, mock_get):
        rule_name = "os_compute_api:os-volumes:list"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req)

    @mock.patch('nova.volume.cinder.API.get_all')
    def test_list_detail_volumes_policy(self, mock_get):
        rule_name = "os_compute_api:os-volumes:detail"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.controller.detail,
                                self.req)

    @mock.patch('nova.volume.cinder.API.get')
    def test_show_volume_policy(self, mock_get):
        mock_get.return_value = {
            'attach_status': 'detached',
            'availability_zone': 'nova',
            'created_at': '2024-11-26T18:20:21.000000',
            'display_name': 'foo',
            'display_description': None,
            'id': uuids.volume_id,
            'size': 1,
            'snapshot_id': None,
            'status': 'available',
            'volume_type_id': uuids.volume_type_id,
        }
        rule_name = "os_compute_api:os-volumes:show"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.controller.show,
                                self.req, uuids.fake_id)

    @mock.patch('nova.volume.cinder.API.create')
    def test_create_volumes_policy(self, mock_create):
        mock_create.return_value = {
            'attach_status': 'detached',
            'availability_zone': 'nova',
            'created_at': '2024-11-26T18:20:21.000000',
            'display_name': 'foo',
            'display_description': None,
            'id': uuids.volume_id,
            'size': 1,
            'snapshot_id': None,
            'status': 'available',
            'volume_type_id': uuids.volume_type_id,
        }
        rule_name = "os_compute_api:os-volumes:create"
        body = {"volume": {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "dublin"}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.create,
                                self.req, body=body)

    @mock.patch('nova.volume.cinder.API.delete')
    def test_delete_volume_policy(self, mock_delete):
        rule_name = "os_compute_api:os-volumes:delete"
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.delete,
                                self.req, uuids.fake_id)


class VolumesNoLegacyNoScopePolicyTest(VolumesPolicyTest):
    """Test Volume APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only.

    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        v_policies.POLICY_NAME % 'list':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'detail':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:list':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:detail':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:show':
            base_policy.PROJECT_READER_OR_ADMIN,
    }

    def setUp(self):
        super().setUp()
        # With no legacy, project other roles like foo will not be able
        # to operate on volume and snapshot.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.project_member_context, self.system_member_context,
            self.other_project_manager_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.other_project_manager_context,
            self.other_project_member_context
        ]


class VolumesScopeTypePolicyTest(VolumesPolicyTest):
    """Test Volumes APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super().setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With scope enabled, system users will not be able to
        # operate on volume and snapshot.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_manager_context,
            self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.other_project_manager_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_manager_context,
            self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.other_project_manager_context,
            self.other_project_member_context
        ]


class VolumesScopeTypeNoLegacyPolicyTest(VolumesScopeTypePolicyTest):
    """Test Volume APIs policies with system scope enabled,
    and no legacy deprecated rules.
    """
    without_deprecated_rules = True

    rules_without_deprecation = {
        v_policies.POLICY_NAME % 'list':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'detail':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:list':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:detail':
            base_policy.PROJECT_READER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        v_policies.POLICY_NAME % 'snapshots:show':
            base_policy.PROJECT_READER_OR_ADMIN,
    }

    def setUp(self):
        super().setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With no legacy and scope enabled, system users and project
        # other roles like foo will not be able to operate on volume
        # and snapshot.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_manager_context,
            self.project_member_context,
            self.other_project_manager_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_manager_context,
            self.project_member_context,
            self.project_reader_context,
            self.other_project_manager_context,
            self.other_project_reader_context,
            self.other_project_member_context
        ]
