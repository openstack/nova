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
from nova.compute import api as compute_api
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


def fake_get(self, context, id, expected_attrs=None, want_objects=False):
    return {'uuid': id}


def fake_set_admin_password(self, context, instance, password=None):
    pass


class AdminPasswordTestV21(test.NoDBTestCase):

    def setUp(self):
        super(AdminPasswordTestV21, self).setUp()
        self.stubs.Set(compute_api.API, 'set_admin_password',
                       fake_set_admin_password)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        self.controller = admin_password_v21.AdminPasswordController()
        self.fake_req = fakes.HTTPRequest.blank('')

    def test_change_password(self):
        body = {'changePassword': {'adminPass': 'test'}}
        self.controller.change_password(self.fake_req, '1', body=body)
        self.assertEqual(self.controller.change_password.wsgi_code, 202)

    def test_change_password_empty_string(self):
        body = {'changePassword': {'adminPass': ''}}
        self.controller.change_password(self.fake_req, '1', body=body)
        self.assertEqual(self.controller.change_password.wsgi_code, 202)

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=NotImplementedError())
    def test_change_password_with_non_implement(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.controller.change_password,
                          self.fake_req, '1', body=body)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(instance_id='1'))
    def test_change_password_with_non_existed_instance(self, mock_get):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.change_password,
                          self.fake_req, '1', body=body)

    def test_change_password_with_non_string_password(self):
        body = {'changePassword': {'adminPass': 1234}}
        self.assertRaises(exception.ValidationError,
                          self.controller.change_password,
                          self.fake_req, '1', body=body)

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=exception.InstancePasswordSetFailed(instance="1",
                                                                reason=''))
    def test_change_password_failed(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.change_password,
                          self.fake_req, '1', body=body)

    def test_change_password_without_admin_password(self):
        body = {'changPassword': {}}
        self.assertRaises(exception.ValidationError,
                          self.controller.change_password,
                          self.fake_req, '1', body=body)

    def test_change_password_none(self):
        body = {'changePassword': None}
        self.assertRaises(exception.ValidationError,
                          self.controller.change_password,
                          self.fake_req, '1', body=body)
