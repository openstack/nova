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

from nova.api.openstack.compute import availability_zone
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class AvailabilityZonePolicyTest(base.BasePolicyTest):
    """Test Availability Zone APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AvailabilityZonePolicyTest, self).setUp()
        self.controller = availability_zone.AvailabilityZoneController()
        self.req = fakes.HTTPRequest.blank('')

        # With legacy rule and scope check disabled by default, system admin,
        # legacy admin, and project admin will be able to get AZ with host
        # information.
        self.system_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch('nova.objects.Instance.save')
    def test_availability_zone_list_policy(self, mock_save):
        rule_name = "os_compute_api:os-availability-zone:list"
        self.common_policy_auth(self.all_contexts,
                                rule_name, self.controller.index,
                                self.req)

    def test_availability_zone_detail_policy(self):
        rule_name = "os_compute_api:os-availability-zone:detail"
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.detail,
                                self.req)


class AvailabilityZoneNoLegacyNoScopePolicyTest(AvailabilityZonePolicyTest):
    """Test Availability Zones APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only. In this case
    system admin, legacy admin, and project admin will be able to get
    AZ with host information. Legacy admin will be allowed as policy
    is just admin if no scope checks.

    """

    without_deprecated_rules = True


class AvailabilityZoneScopeTypePolicyTest(AvailabilityZonePolicyTest):
    """Test Availability Zone APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AvailabilityZoneScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope checks enable, only system admin is able to get
        # AZ with host information.
        self.system_admin_authorized_contexts = [self.system_admin_context]


class AZScopeTypeNoLegacyPolicyTest(AvailabilityZoneScopeTypePolicyTest):
    """Test Availability Zones APIs policies with no legacy deprecated rules
    and scope checks enabled which means scope + new defaults so
    only system admin is able to get AZ with host information.
    """

    without_deprecated_rules = True
