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
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import aggregates
from nova import objects
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class AggregatesPolicyTest(base.BasePolicyTest):
    """Test Aggregates APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AggregatesPolicyTest, self).setUp()
        self.controller = aggregates.AggregateController()
        self.req = fakes.HTTPRequest.blank('')
        # With legacy rule and scope check disabled by default, system admin,
        # legacy admin, and project admin will be able to perform Aggregate
        # Operations.
        self.system_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate_list')
    def test_list_aggregate_policy(self, mock_list):
        rule_name = "os_compute_api:os-aggregates:index"
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req)

    @mock.patch('nova.compute.api.AggregateAPI.create_aggregate')
    def test_create_aggregate_policy(self, mock_create):
        rule_name = "os_compute_api:os-aggregates:create"
        mock_create.return_value = objects.Aggregate(**{"name": "aggregate1",
                                   "id": "1",
                                   "metadata": {'availability_zone': 'nova1'},
                                   "hosts": ["host1", "host2"]})
        body = {"aggregate": {"name": "test",
                              "availability_zone": "nova1"}}
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name,
                                self.controller.create,
                                self.req, body=body)

    @mock.patch('nova.compute.api.AggregateAPI.update_aggregate')
    def test_update_aggregate_policy(self, mock_update):
        rule_name = "os_compute_api:os-aggregates:update"
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.update,
                                self.req, 1,
                                body={"aggregate": {"name": "new_name"}})

    @mock.patch('nova.compute.api.AggregateAPI.delete_aggregate')
    def test_delete_aggregate_policy(self, mock_delete):
        rule_name = "os_compute_api:os-aggregates:delete"
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name,
                                self.controller.delete,
                                self.req, 1)

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate')
    def test_show_aggregate_policy(self, mock_show):
        rule_name = "os_compute_api:os-aggregates:show"
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.show,
                                self.req, 1)

    @mock.patch('nova.compute.api.AggregateAPI.update_aggregate_metadata')
    def test_set_metadata_aggregate_policy(self, mock_metadata):
        rule_name = "os_compute_api:os-aggregates:set_metadata"
        body = {"set_metadata": {"metadata": {"foo": "bar"}}}
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name,
                                self.controller._set_metadata,
                                self.req, 1, body=body)

    @mock.patch('nova.compute.api.AggregateAPI.add_host_to_aggregate')
    def test_add_host_aggregate_policy(self, mock_add):
        rule_name = "os_compute_api:os-aggregates:add_host"
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller._add_host,
                                self.req, 1,
                                body={"add_host": {"host": "host1"}})

    @mock.patch('nova.compute.api.AggregateAPI.remove_host_from_aggregate')
    def test_remove_host_aggregate_policy(self, mock_remove):
        rule_name = "os_compute_api:os-aggregates:remove_host"
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name,
                                self.controller._remove_host,
                                self.req, 1,
                                body={"remove_host": {"host": "host1"}})

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate')
    def test_images_aggregate_policy(self, mock_get):
        rule_name = "compute:aggregates:images"
        mock_get.return_value = {"name": "aggregate1",
                                 "id": "1",
                                 "hosts": ["host1", "host2"]}
        body = {'cache': [{'id': uuids.fake_id}]}
        req = fakes.HTTPRequest.blank('', version='2.81')
        with mock.patch('nova.conductor.api.ComputeTaskAPI.cache_images'):
            self.common_policy_auth(self.system_admin_authorized_contexts,
                                    rule_name, self.controller.images,
                                    req, 1, body=body)


class AggregatesNoLegacyNoScopePolicyTest(AggregatesPolicyTest):
    """Test Aggregates APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only. In this case
    system admin, legacy admin, and project admin will be able to
    perform Aggregate Operations. Legacy admin will be allowed as policy
    is just admin if no scope checks.

    """

    without_deprecated_rules = True


class AggregatesScopeTypePolicyTest(AggregatesPolicyTest):
    """Test Aggregates APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AggregatesScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope checks enable, only system admin is able to perform
        # Aggregate Operations.
        self.system_admin_authorized_contexts = [self.system_admin_context]


class AggregatesScopeTypeNoLegacyPolicyTest(AggregatesScopeTypePolicyTest):
    """Test Aggregates APIs policies with no legacy deprecated rules
    and scope checks enabled which means scope + new defaults so
    only system admin is able to perform aggregates Operations.
    """

    without_deprecated_rules = True
