# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

from nova.api.openstack.compute.plugins.v3 import admin_password \
                                           as admin_password_v21
from nova.api.openstack.compute import servers
from nova.compute import api as compute_api
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


def fake_get(self, context, id, expected_attrs=None, want_objects=False):
    return {'uuid': id}


def fake_set_admin_password(self, context, instance, password=None):
    pass


class AdminPasswordTestV21(test.NoDBTestCase):
    validiation_error = exception.ValidationError

    def setUp(self):
        super(AdminPasswordTestV21, self).setUp()
        self.stubs.Set(compute_api.API, 'set_admin_password',
                       fake_set_admin_password)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        self.fake_req = fakes.HTTPRequest.blank('')

    def _get_action(self):
        return admin_password_v21.AdminPasswordController().change_password

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, controller_method.wsgi_code)

    def test_change_password(self):
        body = {'changePassword': {'adminPass': 'test'}}
        res = self._get_action()(self.fake_req, '1', body=body)
        self._check_status(202, res, self._get_action())

    def test_change_password_empty_string(self):
        body = {'changePassword': {'adminPass': ''}}
        res = self._get_action()(self.fake_req, '1', body=body)
        self._check_status(202, res, self._get_action())

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=NotImplementedError())
    def test_change_password_with_non_implement(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(instance_id='1'))
    def test_change_password_with_non_existed_instance(self, mock_get):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    def test_change_password_with_non_string_password(self):
        body = {'changePassword': {'adminPass': 1234}}
        self.assertRaises(self.validiation_error,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=exception.InstancePasswordSetFailed(instance="1",
                                                                reason=''))
    def test_change_password_failed(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    def test_change_password_without_admin_password(self):
        body = {'changPassword': {}}
        self.assertRaises(self.validiation_error,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    def test_change_password_none(self):
        body = {'changePassword': {'adminPass': None}}
        self.assertRaises(self.validiation_error,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    def test_change_password_adminpass_none(self):
        body = {'changePassword': None}
        self.assertRaises(self.validiation_error,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    def test_change_password_bad_request(self):
        body = {'changePassword': {'pass': '12345'}}
        self.assertRaises(self.validiation_error,
                          self._get_action(),
                          self.fake_req, '1', body=body)

    def test_server_change_password_pass_disabled(self):
        # run with enable_instance_password disabled to verify adminPass
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False)
        body = {'changePassword': {'adminPass': '1234pass'}}
        res = self._get_action()(self.fake_req, '1', body=body)
        self._check_status(202, res, self._get_action())

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=exception.InstanceInvalidState(instance="1",
                                                           reason=''))
    def test_change_password_invalid_state(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._get_action(),
                          self.fake_req, '1', body=body)


class AdminPasswordTestV2(AdminPasswordTestV21):
    validiation_error = webob.exc.HTTPBadRequest

    def _get_action(self):
        class FakeExtManager(object):
            def is_loaded(self, ext):
                return False
        return servers.Controller(ext_mgr=FakeExtManager()).\
                                    _action_change_password

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, res.status_int)
