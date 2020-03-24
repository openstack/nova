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

from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
import urllib

from nova.api.openstack.compute import assisted_volume_snapshots as snapshots
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class AssistedVolumeSnapshotPolicyTest(base.BasePolicyTest):
    """Test Assisted Volume Snapshots APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AssistedVolumeSnapshotPolicyTest, self).setUp()
        self.controller = snapshots.AssistedVolumeSnapshotsController()
        self.req = fakes.HTTPRequest.blank('')
        # By default, legacy rule are enable and scope check is disabled.
        # system admin, legacy admin, and project admin is able to
        # take volume snapshot.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch('nova.compute.api.API.volume_snapshot_create')
    def test_assisted_create_policy(self, mock_create):
        rule_name = "os_compute_api:os-assisted-volume-snapshots:create"
        body = {'snapshot': {'volume_id': uuids.fake_id,
                             'create_info': {'type': 'qcow2',
                                             'new_file': 'new_file',
                                             'snapshot_id': 'snapshot_id'}}}
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.create,
                                self.req, body=body)

    @mock.patch('nova.compute.api.API.volume_snapshot_delete')
    def test_assisted_delete_policy(self, mock_delete):
        rule_name = "os_compute_api:os-assisted-volume-snapshots:delete"
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
        }
        req = fakes.HTTPRequest.blank('?%s' % urllib.parse.urlencode(params))
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name,
                                self.controller.delete,
                                req, 1)


class AssistedSnapshotNoLegacyNoScopePolicyTest(
        AssistedVolumeSnapshotPolicyTest):
    """Test Assisted Snapshot APIs policies with no legacy deprecated rules
    and no scope checks.

    """

    without_deprecated_rules = True


class AssistedSnapshotScopeTypePolicyTest(AssistedVolumeSnapshotPolicyTest):
    """Test Assisted Volume Snapshots APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scopped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AssistedSnapshotScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope check enabled, system admin is not able to
        # take volume snapshot.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]


class AssistedSnapshotScopeTypeNoLegacyPolicyTest(
        AssistedSnapshotScopeTypePolicyTest):
    """Test os-volume-attachments APIs policies with system scope enabled,
    and no legacy deprecated rules.
    """
    without_deprecated_rules = True
