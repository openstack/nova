# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import json
import webob

from nova import context
from nova import test
from nova.tests.api.openstack import fakes

from nova.api.openstack.contrib.quotas import QuotaSetsController


def quota_set(id):
    return {'quota_set': {'id': id, 'metadata_items': 128, 'volumes': 10,
            'gigabytes': 1000, 'ram': 51200, 'floating_ips': 10,
            'instances': 10, 'injected_files': 5, 'cores': 20,
            'injected_file_content_bytes': 10240}}


def quota_set_list():
    return {'quota_set_list': [quota_set('1234'), quota_set('5678'),
                               quota_set('update_me')]}


class QuotaSetsTest(test.TestCase):

    def setUp(self):
        super(QuotaSetsTest, self).setUp()
        self.controller = QuotaSetsController()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.user_context = context.RequestContext(self.user_id,
                                                   self.project_id)
        self.admin_context = context.RequestContext(self.user_id,
                                                    self.project_id,
                                                    is_admin=True)

    def test_format_quota_set(self):
        raw_quota_set = {
            'instances': 10,
            'cores': 20,
            'ram': 51200,
            'volumes': 10,
            'floating_ips': 10,
            'metadata_items': 128,
            'gigabytes': 1000,
            'injected_files': 5,
            'injected_file_content_bytes': 10240}

        quota_set = QuotaSetsController()._format_quota_set('1234',
                                                            raw_quota_set)
        qs = quota_set['quota_set']

        self.assertEqual(qs['id'], '1234')
        self.assertEqual(qs['instances'], 10)
        self.assertEqual(qs['cores'], 20)
        self.assertEqual(qs['ram'], 51200)
        self.assertEqual(qs['volumes'], 10)
        self.assertEqual(qs['gigabytes'], 1000)
        self.assertEqual(qs['floating_ips'], 10)
        self.assertEqual(qs['metadata_items'], 128)
        self.assertEqual(qs['injected_files'], 5)
        self.assertEqual(qs['injected_file_content_bytes'], 10240)

    def test_quotas_defaults(self):
        uri = '/v1.1/fake_tenant/os-quota-sets/fake_tenant/defaults'
        req = webob.Request.blank(uri)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        expected = {'quota_set': {
                    'id': 'fake_tenant',
                    'instances': 10,
                    'cores': 20,
                    'ram': 51200,
                    'volumes': 10,
                    'gigabytes': 1000,
                    'floating_ips': 10,
                    'metadata_items': 128,
                    'injected_files': 5,
                    'injected_file_content_bytes': 10240}}

        self.assertEqual(json.loads(res.body), expected)

    def test_quotas_show_as_admin(self):
        req = webob.Request.blank('/v1.1/1234/os-quota-sets/1234')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))

        self.assertEqual(res.status_int, 200)
        self.assertEqual(json.loads(res.body), quota_set('1234'))

    def test_quotas_show_as_unauthorized_user(self):
        req = webob.Request.blank('/v1.1/fake/os-quota-sets/1234')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context))

        self.assertEqual(res.status_int, 403)

    def test_quotas_update_as_admin(self):
        updated_quota_set = {'quota_set': {'instances': 50,
                             'cores': 50, 'ram': 51200, 'volumes': 10,
                             'gigabytes': 1000, 'floating_ips': 10,
                             'metadata_items': 128, 'injected_files': 5,
                             'injected_file_content_bytes': 10240}}

        req = webob.Request.blank('/v1.1/1234/os-quota-sets/update_me')
        req.method = 'PUT'
        req.body = json.dumps(updated_quota_set)
        req.headers['Content-Type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.admin_context))

        self.assertEqual(json.loads(res.body), updated_quota_set)

    def test_quotas_update_as_user(self):
        updated_quota_set = {'quota_set': {'instances': 50,
                             'cores': 50, 'ram': 51200, 'volumes': 10,
                             'gigabytes': 1000, 'floating_ips': 10,
                             'metadata_items': 128, 'injected_files': 5,
                             'injected_file_content_bytes': 10240}}

        req = webob.Request.blank('/v1.1/1234/os-quota-sets/update_me')
        req.method = 'PUT'
        req.body = json.dumps(updated_quota_set)
        req.headers['Content-Type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(
                               fake_auth_context=self.user_context))

        self.assertEqual(res.status_int, 403)
