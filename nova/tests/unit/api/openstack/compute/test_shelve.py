# All Rights Reserved.
#
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
from oslo_policy import policy as oslo_policy
import webob

from nova.api.openstack.compute import shelve as shelve_v21
from nova import exception
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel


class ShelvePolicyTestV21(test.NoDBTestCase):
    plugin = shelve_v21

    def setUp(self):
        super(ShelvePolicyTestV21, self).setUp()
        self.controller = self.plugin.ShelveController()
        self.req = fakes.HTTPRequest.blank('')

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.shelve',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._shelve,
                          self.req, uuidsentinel.fake, {})

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.unshelve',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._unshelve,
                          self.req, uuidsentinel.fake, {})

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_offload_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.shelve_offload',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._shelve_offload,
                          self.req, uuidsentinel.fake, {})


class ShelvePolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(ShelvePolicyEnforcementV21, self).setUp()
        self.controller = shelve_v21.ShelveController()
        self.req = fakes.HTTPRequest.blank('')

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_restricted_by_role(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        rules = {'os_compute_api:os-shelve:shelve': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        self.assertRaises(exception.Forbidden, self.controller._shelve,
                self.req, uuidsentinel.fake, {})

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_policy_failed_with_other_project(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        rule_name = "os_compute_api:os-shelve:shelve"
        self.policy.set_rules({rule_name: "project_id:%(project_id)s"})
        # Change the project_id in request context.
        self.req.environ['nova.context'].project_id = 'other-project'
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._shelve, self.req, fakes.FAKE_UUID,
            body={'shelve': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.shelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_overridden_policy_pass_with_same_project(self,
                                                             get_instance_mock,
                                                             shelve_mock):
        instance = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            project_id=self.req.environ['nova.context'].project_id)
        get_instance_mock.return_value = instance
        rule_name = "os_compute_api:os-shelve:shelve"
        self.policy.set_rules({rule_name: "project_id:%(project_id)s"})
        self.controller._shelve(self.req, fakes.FAKE_UUID, body={'shelve': {}})
        shelve_mock.assert_called_once_with(self.req.environ['nova.context'],
                                          instance)

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_overridden_policy_failed_with_other_user_in_same_project(
        self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        rule_name = "os_compute_api:os-shelve:shelve"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        # Change the user_id in request context.
        self.req.environ['nova.context'].user_id = 'other-user'
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._shelve, self.req,
                                fakes.FAKE_UUID, body={'shelve': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    @mock.patch('nova.compute.api.API.shelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_shelve_overridden_policy_pass_with_same_user(self,
                                                        get_instance_mock,
                                                        shelve_mock):
        instance = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            user_id=self.req.environ['nova.context'].user_id)
        get_instance_mock.return_value = instance
        rule_name = "os_compute_api:os-shelve:shelve"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._shelve(self.req, fakes.FAKE_UUID, body={'shelve': {}})
        shelve_mock.assert_called_once_with(self.req.environ['nova.context'],
                                          instance)

    def test_shelve_offload_restricted_by_role(self):
        rules = {'os_compute_api:os-shelve:shelve_offload': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        self.assertRaises(exception.Forbidden,
                self.controller._shelve_offload, self.req,
                uuidsentinel.fake, {})

    def test_shelve_offload_policy_failed(self):
        rule_name = "os_compute_api:os-shelve:shelve_offload"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._shelve_offload, self.req, fakes.FAKE_UUID,
            body={'shelve_offload': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_unshelve_restricted_by_role(self):
        rules = {'os_compute_api:os-shelve:unshelve': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        self.assertRaises(exception.Forbidden, self.controller._unshelve,
                self.req, uuidsentinel.fake, {})

    def test_unshelve_policy_failed(self):
        rule_name = "os_compute_api:os-shelve:unshelve"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._unshelve, self.req, fakes.FAKE_UUID,
            body={'unshelve': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())
