# Copyright 2011 OpenStack Foundation
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
import webob

from nova.api.openstack.compute import deferred_delete as dd_v21
from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'nova.context': context}


class DeferredDeleteExtensionTestV21(test.NoDBTestCase):
    ext_ver = dd_v21.DeferredDeleteController

    def setUp(self):
        super(DeferredDeleteExtensionTestV21, self).setUp()
        self.fake_input_dict = {}
        self.fake_uuid = 'fake_uuid'
        self.fake_context = context.RequestContext('fake', 'fake')
        self.fake_req = FakeRequest(self.fake_context)
        self.extension = self.ext_ver()

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'force_delete')
    def test_force_delete(self, mock_force_delete, mock_get):
        instance = fake_instance.fake_instance_obj(
            self.fake_req.environ['nova.context'])
        mock_get.return_value = instance

        res = self.extension._force_delete(self.fake_req, self.fake_uuid,
                                           self.fake_input_dict)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.extension, dd_v21.DeferredDeleteController):
            status_int = self.extension._force_delete.wsgi_code
        else:
            status_int = res.status_int
        self.assertEqual(202, status_int)

        mock_get.assert_called_once_with(self.fake_context,
                                         self.fake_uuid,
                                         expected_attrs=None,
                                         cell_down_support=False)
        mock_force_delete.assert_called_once_with(self.fake_context,
                                                  instance)

    @mock.patch.object(compute_api.API, 'get')
    def test_force_delete_instance_not_found(self, mock_get):
        mock_get.side_effect = exception.InstanceNotFound(
            instance_id='instance-0000')

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.extension._force_delete,
                          self.fake_req,
                          self.fake_uuid,
                          self.fake_input_dict)

        mock_get.assert_called_once_with(self.fake_context,
                                         self.fake_uuid,
                                         expected_attrs=None,
                                         cell_down_support=False)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'force_delete',
                side_effect=exception.InstanceIsLocked(
                    instance_uuid='fake_uuid'))
    def test_force_delete_instance_locked(self, mock_force_delete, mock_get):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/fake_uuid/action')
        ex = self.assertRaises(webob.exc.HTTPConflict,
                            self.extension._force_delete,
                            req, 'fake_uuid', '')
        self.assertIn('Instance fake_uuid is locked', ex.explanation)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'force_delete',
                side_effect=exception.InstanceNotFound(
                    instance_id='fake_uuid'))
    def test_force_delete_instance_notfound(self, mock_force_delete, mock_get):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/fake_uuid/action')
        ex = self.assertRaises(webob.exc.HTTPNotFound,
                            self.extension._force_delete,
                            req, 'fake_uuid', '')
        self.assertIn('Instance fake_uuid could not be found',
                      ex.explanation)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'restore')
    def test_restore(self, mock_restore, mock_get):
        instance = fake_instance.fake_instance_obj(
            self.fake_req.environ['nova.context'])
        mock_get.return_value = instance

        res = self.extension._restore(self.fake_req, self.fake_uuid,
                                      self.fake_input_dict)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.extension, dd_v21.DeferredDeleteController):
            status_int = self.extension._restore.wsgi_code
        else:
            status_int = res.status_int
        self.assertEqual(202, status_int)

        mock_get.assert_called_once_with(self.fake_context,
                                         self.fake_uuid,
                                         expected_attrs=None,
                                         cell_down_support=False)
        mock_restore.assert_called_once_with(self.fake_context,
                                             instance)

    @mock.patch.object(compute_api.API, 'get')
    def test_restore_instance_not_found(self, mock_get):
        mock_get.side_effect = exception.InstanceNotFound(
            instance_id='instance-0000')

        self.assertRaises(webob.exc.HTTPNotFound, self.extension._restore,
                          self.fake_req, self.fake_uuid,
                          self.fake_input_dict)

        mock_get.assert_called_once_with(self.fake_context,
                                         self.fake_uuid,
                                         expected_attrs=None,
                                         cell_down_support=False)

    @mock.patch.object(compute_api.API, 'get')
    @mock.patch.object(compute_api.API, 'restore')
    def test_restore_raises_conflict_on_invalid_state(self,
            mock_restore, mock_get):
        instance = fake_instance.fake_instance_obj(
            self.fake_req.environ['nova.context'])
        mock_get.return_value = instance
        mock_restore.side_effect = exception.InstanceInvalidState(
            attr='fake_attr', state='fake_state', method='fake_method',
            instance_uuid='fake')

        self.assertRaises(webob.exc.HTTPConflict, self.extension._restore,
                self.fake_req, self.fake_uuid, self.fake_input_dict)

        mock_get.assert_called_once_with(self.fake_context,
                                         self.fake_uuid,
                                         expected_attrs=None,
                                         cell_down_support=False)

        mock_restore.assert_called_once_with(self.fake_context,
                                             instance)


class DeferredDeletePolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(DeferredDeletePolicyEnforcementV21, self).setUp()
        self.controller = dd_v21.DeferredDeleteController()
        self.req = fakes.HTTPRequest.blank('')

    def test_restore_policy_failed(self):
        rule_name = "os_compute_api:os-deferred-delete"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._restore, self.req, fakes.FAKE_UUID,
            body={'restore': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_force_delete_policy_failed_with_other_project(
        self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        rule_name = "os_compute_api:os-deferred-delete"
        self.policy.set_rules({rule_name: "project_id:%(project_id)s"})
        # Change the project_id in request context.
        self.req.environ['nova.context'].project_id = 'other-project'
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._force_delete, self.req, fakes.FAKE_UUID,
            body={'forceDelete': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.force_delete')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_force_delete_overridden_policy_pass_with_same_project(
        self, get_instance_mock, force_delete_mock):
        instance = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            project_id=self.req.environ['nova.context'].project_id)
        get_instance_mock.return_value = instance
        rule_name = "os_compute_api:os-deferred-delete"
        self.policy.set_rules({rule_name: "project_id:%(project_id)s"})
        self.controller._force_delete(self.req, fakes.FAKE_UUID,
                                      body={'forceDelete': {}})
        force_delete_mock.assert_called_once_with(
            self.req.environ['nova.context'], instance)

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_force_delete_overridden_policy_failed_with_other_user(
        self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        rule_name = "os_compute_api:os-deferred-delete"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        # Change the user_id in request context.
        self.req.environ['nova.context'].user_id = 'other-user'
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._force_delete, self.req,
                                fakes.FAKE_UUID, body={'forceDelete': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    @mock.patch('nova.compute.api.API.force_delete')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_force_delete_overridden_policy_pass_with_same_user(self,
                                                        get_instance_mock,
                                                        force_delete_mock):
        instance = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            user_id=self.req.environ['nova.context'].user_id)
        get_instance_mock.return_value = instance
        rule_name = "os_compute_api:os-deferred-delete"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._force_delete(self.req, fakes.FAKE_UUID,
                                      body={'forceDelete': {}})
        force_delete_mock.assert_called_once_with(
            self.req.environ['nova.context'], instance)
