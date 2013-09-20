# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import webob

from nova.api.openstack.compute.plugins.v3 import admin_password
from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


def fake_get(self, context, id):
    return {'uuid': id}


def fake_get_non_existed(self, context, id):
    raise exception.InstanceNotFound(instance_id=id)


def fake_set_admin_password(self, context, instance, password=None):
    pass


def fake_set_admin_password_failed(self, context, instance, password=None):
    raise exception.InstancePasswordSetFailed(instance=instance, reason='')


def fake_set_admin_password_non_implement(self, context, instance,
                                          password=None):
    raise NotImplementedError()


class AdminPasswordTest(test.NoDBTestCase):

    def setUp(self):
        super(AdminPasswordTest, self).setUp()
        self.stubs.Set(compute_api.API, 'set_admin_password',
                       fake_set_admin_password)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        self.app = fakes.wsgi_app_v3(init_only=('servers',
                                                admin_password.ALIAS))

    def _make_request(self, url, body):
        req = webob.Request.blank(url)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.content_type = 'application/json'
        res = req.get_response(self.app)
        return res

    def test_change_password(self):
        url = '/v3/servers/1/action'
        body = {'change_password': {'admin_password': 'test'}}
        res = self._make_request(url, body)
        self.assertEqual(res.status_int, 204)

    def test_change_password_with_non_implement(self):
        url = '/v3/servers/1/action'
        body = {'change_password': {'admin_password': 'test'}}
        self.stubs.Set(compute_api.API, 'set_admin_password',
                       fake_set_admin_password_non_implement)
        res = self._make_request(url, body)
        self.assertEqual(res.status_int, 501)

    def test_change_password_with_non_existed_instance(self):
        url = '/v3/servers/1/action'
        body = {'change_password': {'admin_password': 'test'}}
        self.stubs.Set(compute_api.API, 'get', fake_get_non_existed)
        res = self._make_request(url, body)
        self.assertEqual(res.status_int, 404)

    def test_change_password_failed(self):
        url = '/v3/servers/1/action'
        body = {'change_password': {'admin_password': 'test'}}
        self.stubs.Set(compute_api.API, 'set_admin_password',
                       fake_set_admin_password_failed)
        res = self._make_request(url, body)
        self.assertEqual(res.status_int, 409)

    def test_change_password_with_bad_request(self):
        url = '/v3/servers/1/action'
        body = {'change_password': {}}
        res = self._make_request(url, body)
        self.assertEqual(res.status_int, 400)


class AdminPasswordXMLTest(test.NoDBTestCase):
    def test_change_password_deserializer(self):
        deserializer = admin_password.ChangePasswordDeserializer()
        request = '<change_password admin_password="1"></change_password>'
        expected = {'body': {'change_password': {'admin_password': '1'}}}
        res = deserializer.default(request)
        self.assertEqual(res, expected)

    def test_change_password_deserializer_without_admin_password(self):
        deserializer = admin_password.ChangePasswordDeserializer()
        request = '<change_password></change_password>'
        expected = {'body': {'change_password': None}}
        res = deserializer.default(request)
        self.assertEqual(res, expected)
