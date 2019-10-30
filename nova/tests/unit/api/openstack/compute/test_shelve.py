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
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel
import six
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import shelve as shelve_v21
from nova.compute import task_states
from nova.compute import vm_states
from nova import exception
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


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
    @mock.patch('nova.objects.instance.Instance.save')
    def test_shelve_task_state_race(self, mock_save, get_instance_mock):
        instance = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            vm_state=vm_states.ACTIVE, task_state=None)
        instance.launched_at = instance.created_at
        get_instance_mock.return_value = instance
        mock_save.side_effect = exception.UnexpectedTaskStateError(
            instance_uuid=instance.uuid, expected=None,
            actual=task_states.SHELVING)
        ex = self.assertRaises(webob.exc.HTTPConflict, self.controller._shelve,
                          self.req, uuidsentinel.fake, body={'shelve': {}})
        self.assertIn('Conflict updating instance', six.text_type(ex))
        mock_save.assert_called_once_with(expected_task_state=[None])

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_locked_server(self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        self.stub_out('nova.compute.api.API.unshelve',
                      fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._unshelve,
                          self.req, uuidsentinel.fake, body={'unshelve': {}})

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
                self.req, uuidsentinel.fake, body={'unshelve': {}})

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


class UnshelveServerControllerTestV277(test.NoDBTestCase):
    """Server controller test for microversion 2.77

    Add availability_zone parameter to unshelve a shelved-offloaded server of
    2.77 microversion.
    """
    wsgi_api_version = '2.77'

    def setUp(self):
        super(UnshelveServerControllerTestV277, self).setUp()
        self.controller = shelve_v21.ShelveController()
        self.req = fakes.HTTPRequest.blank('/fake/servers/a/action',
                                           use_admin_context=True,
                                           version=self.wsgi_api_version)
        # These tests don't care about ports with QoS bandwidth resources.
        self.stub_out('nova.api.openstack.common.'
                      'instance_has_port_with_resource_request',
                      lambda *a, **kw: False)

    def fake_get_instance(self):
        ctxt = self.req.environ['nova.context']
        return fake_instance.fake_instance_obj(
            ctxt, uuid=fakes.FAKE_UUID, vm_state=vm_states.SHELVED_OFFLOADED)

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_az_pre_2_77_failed(self, mock_get_instance):
        """Make sure specifying an AZ before microversion 2.77 is ignored."""
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {
            'unshelve': {
                'availability_zone': 'us-east'
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (api_version_request.
                APIVersionRequest('2.76'))
        with mock.patch.object(self.controller.compute_api,
                               'unshelve') as mock_unshelve:
            self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'], instance, new_az=None)

    @mock.patch('nova.compute.api.API.unshelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_none_pre_2_77_success(
            self, mock_get_instance, mock_unshelve):
        """Make sure we can unshelve server with None
        before microversion 2.77.
        """
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {'unshelve': None}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.req.api_version_request = (api_version_request.
                APIVersionRequest('2.76'))
        self.controller._unshelve(self.req, fakes.FAKE_UUID, body=body)
        mock_unshelve.assert_called_once_with(
            self.req.environ['nova.context'], instance, new_az=None)

    @mock.patch('nova.compute.api.API.unshelve')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_unshelve_with_empty_dict_with_v2_77_failed(
            self, mock_get_instance, mock_unshelve):
        """Make sure we cannot unshelve server with empty dict."""
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        body = {'unshelve': {}}
        self.req.body = jsonutils.dump_as_bytes(body)
        exc = self.assertRaises(exception.ValidationError,
                                self.controller._unshelve,
                                self.req, fakes.FAKE_UUID,
                                body=body)
        self.assertIn("\'availability_zone\' is a required property",
                      six.text_type(exc))

    def test_invalid_az_name_with_int(self):
        body = {
            'unshelve': {
                'availability_zone': 1234
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError,
                          self.controller._unshelve,
                          self.req, fakes.FAKE_UUID,
                          body=body)

    def test_no_az_value(self):
        body = {
            'unshelve': {
                'availability_zone': None
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError,
                          self.controller._unshelve,
                          self.req, fakes.FAKE_UUID,
                          body=body)

    def test_unshelve_with_additional_param(self):
        body = {
            'unshelve': {
                'availability_zone': 'us-east',
                'additional_param': 1
            }}
        self.req.body = jsonutils.dump_as_bytes(body)
        exc = self.assertRaises(
            exception.ValidationError,
            self.controller._unshelve, self.req,
            fakes.FAKE_UUID, body=body)
        self.assertIn("Additional properties are not allowed",
                      six.text_type(exc))
