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

import fixtures
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import volumes as volumes_v21
from nova.compute import vm_states
from nova import exception
from nova import objects
from nova.objects import block_device as block_device_obj
from nova.policies import base as base_policy
from nova.policies import volumes as v_policies
from nova.policies import volumes_attachments as va_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base

# This is the server ID.
FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
# This is the old volume ID (to swap from).
FAKE_UUID_A = '00000000-aaaa-aaaa-aaaa-000000000000'
# This is the new volume ID (to swap to).
FAKE_UUID_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'


def fake_bdm_get_by_volume_and_instance(cls, ctxt, volume_id, instance_uuid):
    if volume_id != FAKE_UUID_A:
        raise exception.VolumeBDMNotFound(volume_id=volume_id)
    db_bdm = fake_block_device.FakeDbBlockDeviceDict(
        {'id': 1,
         'instance_uuid': instance_uuid,
         'device_name': '/dev/fake0',
         'delete_on_termination': 'False',
         'source_type': 'volume',
         'destination_type': 'volume',
         'snapshot_id': None,
         'volume_id': volume_id,
         'volume_size': 1})
    return objects.BlockDeviceMapping._from_db_object(
        ctxt, objects.BlockDeviceMapping(), db_bdm)


def fake_get_volume(self, context, id):
    if id == FAKE_UUID_A:
        status = 'in-use'
        attach_status = 'attached'
    elif id == FAKE_UUID_B:
        status = 'available'
        attach_status = 'detached'
    else:
        raise exception.VolumeNotFound(volume_id=id)
    return {'id': id, 'status': status, 'attach_status': attach_status}


class VolumeAttachPolicyTest(base.BasePolicyTest):
    """Test os-volumes-attachments APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(VolumeAttachPolicyTest, self).setUp()
        self.controller = volumes_v21.VolumeAttachmentController()
        self.req = fakes.HTTPRequest.blank('')
        self.policy_root = va_policies.POLICY_ROOT
        self.stub_out('nova.objects.BlockDeviceMapping'
                      '.get_by_volume_and_instance',
                      fake_bdm_get_by_volume_and_instance)
        self.stub_out('nova.volume.cinder.API.get', fake_get_volume)

        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
            self.project_member_context,
            id=1, uuid=uuid, project_id=self.project_id,
            vm_state=vm_states.ACTIVE,
            task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance

        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow
        # resource owner- having same project id and no role check) is
        # able create/delete/update the volume attachment.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]

        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow
        # resource owner- having same project id and no role check) is
        # able get the volume attachment.
        self.project_reader_authorized_contexts = (
            self.project_member_authorized_contexts)

        # By default, legacy rule are enable and scope check is disabled.
        # system admin, legacy admin, and project admin is able to update
        # volume attachment with a different volumeId.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    def test_index_volume_attach_policy(self, mock_get_instance):
        rule_name = self.policy_root % "index"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req, FAKE_UUID)

    def test_show_volume_attach_policy(self):
        rule_name = self.policy_root % "show"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.controller.show,
                                self.req, FAKE_UUID, FAKE_UUID_A)

    @mock.patch('nova.compute.api.API.attach_volume')
    def test_create_volume_attach_policy(self, mock_attach_volume):
        rule_name = self.policy_root % "create"
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_B,
                                     'device': '/dev/fake'}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.create,
                                self.req, FAKE_UUID, body=body)

    @mock.patch.object(block_device_obj.BlockDeviceMapping, 'save')
    def test_update_volume_attach_policy(self, mock_bdm_save):
        rule_name = self.policy_root % "update"
        req = fakes.HTTPRequest.blank('', version='2.85')
        body = {'volumeAttachment': {
            'volumeId': FAKE_UUID_A,
            'delete_on_termination': True}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.update,
                                req, FAKE_UUID,
                                FAKE_UUID_A, body=body)

    @mock.patch('nova.compute.api.API.detach_volume')
    def test_delete_volume_attach_policy(self, mock_detach_volume):
        rule_name = self.policy_root % "delete"
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.delete,
                                self.req, FAKE_UUID, FAKE_UUID_A)

    @mock.patch('nova.compute.api.API.swap_volume')
    def test_swap_volume_attach_policy(self, mock_swap_volume):
        rule_name = self.policy_root % "swap"
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_B}}
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.update,
                                self.req, FAKE_UUID, FAKE_UUID_A, body=body)

    @mock.patch.object(block_device_obj.BlockDeviceMapping, 'save')
    @mock.patch('nova.compute.api.API.swap_volume')
    def test_swap_volume_attach_policy_failed(self,
                                              mock_swap_volume,
                                              mock_bdm_save):
        """Policy check fails for swap + update due to swap policy failure.
        """
        rule_name = self.policy_root % "swap"
        req = fakes.HTTPRequest.blank('', version='2.85')
        req.environ['nova.context'].user_id = 'other-user'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_B,
            'delete_on_termination': True}}
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller.update,
            req, FAKE_UUID, FAKE_UUID_A, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())
        mock_swap_volume.assert_not_called()
        mock_bdm_save.assert_not_called()

    @mock.patch.object(block_device_obj.BlockDeviceMapping, 'save')
    @mock.patch('nova.compute.api.API.swap_volume')
    def test_pass_swap_and_update_volume_attach_policy(self,
                                                       mock_swap_volume,
                                                       mock_bdm_save):
        rule_name = self.policy_root % "swap"
        req = fakes.HTTPRequest.blank('', version='2.85')
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_B,
            'delete_on_termination': True}}
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.update,
                                req, FAKE_UUID, FAKE_UUID_A, body=body)
        mock_swap_volume.assert_called()
        mock_bdm_save.assert_called()


class VolumeAttachNoLegacyNoScopePolicyTest(VolumeAttachPolicyTest):
    """Test volume attachment APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only.

    """

    without_deprecated_rules = True

    def setUp(self):
        super(VolumeAttachNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, only admin, member, or reader will be
        # able to perform volume attachment operation on its own project.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_no_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_no_scope_no_legacy)


class VolumeAttachScopeTypePolicyTest(VolumeAttachPolicyTest):
    """Test os-volume-attachments APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(VolumeAttachScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Scope enable will not allow system admin to perform the
        # volume attachments.
        self.project_member_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)
        self.project_reader_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)

        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]


class VolumeAttachScopeTypeNoLegacyPolicyTest(VolumeAttachScopeTypePolicyTest):
    """Test os-volume-attachments APIs policies with system scope enabled,
    and no legacy deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(VolumeAttachScopeTypeNoLegacyPolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With scope enable and no legacy rule, it will not allow
        # system users and project admin/member/reader will be able to
        # perform volume attachment operation on its own project.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_scope_no_legacy)


class VolumesPolicyTest(base.BasePolicyTest):
    """Test Volumes APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(VolumesPolicyTest, self).setUp()
        self.controller = volumes_v21.VolumeController()
        self.snapshot_ctlr = volumes_v21.SnapshotController()
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
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
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
        rule_name = "os_compute_api:os-volumes:show"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.controller.show,
                                self.req, uuids.fake_id)

    @mock.patch('nova.api.openstack.compute.volumes.'
        '_translate_volume_detail_view')
    @mock.patch('nova.volume.cinder.API.create')
    def test_create_volumes_policy(self, mock_create, mock_view):
        rule_name = "os_compute_api:os-volumes:create"
        body = {"volume": {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.create,
                                self.req, body=body)

    @mock.patch('nova.volume.cinder.API.delete')
    def test_delete_volume_policy(self, mock_delete):
        rule_name = "os_compute_api:os-volumes:delete"
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.delete,
                                self.req, uuids.fake_id)

    @mock.patch('nova.volume.cinder.API.get_all_snapshots')
    def test_list_snapshots_policy(self, mock_get):
        rule_name = "os_compute_api:os-volumes:snapshots:list"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.snapshot_ctlr.index,
                                self.req)

    @mock.patch('nova.volume.cinder.API.get_all_snapshots')
    def test_list_detail_snapshots_policy(self, mock_get):
        rule_name = "os_compute_api:os-volumes:snapshots:detail"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.snapshot_ctlr.detail,
                                self.req)

    @mock.patch('nova.volume.cinder.API.get_snapshot')
    def test_show_snapshot_policy(self, mock_get):
        rule_name = "os_compute_api:os-volumes:snapshots:show"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.snapshot_ctlr.show,
                                self.req, uuids.fake_id)

    @mock.patch('nova.volume.cinder.API.create_snapshot')
    def test_create_snapshot_policy(self, mock_create):
        rule_name = "os_compute_api:os-volumes:snapshots:create"
        body = {"snapshot": {"volume_id": uuids.fake_id}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.snapshot_ctlr.create,
                                self.req, body=body)

    @mock.patch('nova.volume.cinder.API.delete_snapshot')
    def test_delete_snapshot_policy(self, mock_delete):
        rule_name = "os_compute_api:os-volumes:snapshots:delete"
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.snapshot_ctlr.delete,
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
        super(VolumesNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy, project other roles like foo will not be able
        # to operate on volume and snapshot.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.system_member_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
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
        super(VolumesScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With scope enabled, system users will not be able to
        # operate on volume and snapshot.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context, self.other_project_reader_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context, self.other_project_reader_context,
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
        super(VolumesScopeTypeNoLegacyPolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With no legacy and scope enabled, system users and project
        # other roles like foo will not be able to operate on volume
        # and snapshot.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_reader_context,
            self.other_project_member_context
        ]
