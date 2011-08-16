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
from nova.auth import manager as auth_manager
from nova.tests.api.openstack import fakes


from nova.api.openstack.contrib.quotas import QuotasController


def quota_set(id):
    return {'quota_set': {'id': id, 'metadata_items': 128, 'volumes': 10,
            'gigabytes': 1000, 'ram': 51200, 'floating_ips': 10,
            'instances': 10, 'injected_files': 5, 'cores': 20,
            'injected_file_content_bytes': 10240}}


def quota_set_list():
    return {'quota_set_list': [quota_set('1234'), quota_set('5678'),
                               quota_set('update_me')]}


def create_project(project_name, manager_user):
    auth_manager.AuthManager().create_project(project_name, manager_user)


def delete_project(project_name):
    auth_manager.AuthManager().delete_project(project_name)


def create_admin_user(name):
    auth_manager.AuthManager().create_user(name, admin=True)


def delete_user(name):
    auth_manager.AuthManager().delete_user(name)


class QuotasTest(test.TestCase):

    def setUp(self):
        super(QuotasTest, self).setUp()
        self.controller = QuotasController()
        self.context = context.get_admin_context()

        create_admin_user('foo')
        create_project('1234', 'foo')
        create_project('5678', 'foo')
        create_project('update_me', 'foo')

    def tearDown(self):
        delete_project('1234')
        delete_project('5678')
        delete_project('update_me')
        delete_user('foo')

    def test_format_quota_set(self):
        raw_quota_set = {
            'instances': 10,
            'cores': 20,
            'ram': 51200,
            'volumes': 10,
            'gigabytes': 1000,
            'floating_ips': 10,
            'metadata_items': 128,
            'injected_files': 5,
            'injected_file_content_bytes': 10240,
        }

        quota_set = QuotasController()._format_quota_set('1234', raw_quota_set)
        quota_set_check = quota_set['quota_set']

        self.assertEqual(quota_set_check['id'], '1234')
        self.assertEqual(quota_set_check['instances'], 10)
        self.assertEqual(quota_set_check['cores'], 20)
        self.assertEqual(quota_set_check['ram'], 51200)
        self.assertEqual(quota_set_check['volumes'], 10)
        self.assertEqual(quota_set_check['gigabytes'], 1000)
        self.assertEqual(quota_set_check['floating_ips'], 10)
        self.assertEqual(quota_set_check['metadata_items'], 128)
        self.assertEqual(quota_set_check['injected_files'], 5)
        self.assertEqual(quota_set_check['injected_file_content_bytes'], 10240)

    def test_quotas_index_with_default_param(self):
        req = webob.Request.blank('/v1.1/os-quotas?defaults=True')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        expected = {'quota_set_list': [{'quota_set': {
            'id': '__defaults__',
            'instances': 10,
            'cores': 20,
            'ram': 51200,
            'volumes': 10,
            'gigabytes': 1000,
            'floating_ips': 10,
            'metadata_items': 128,
            'injected_files': 5,
            'injected_file_content_bytes': 10240}}]}

        self.assertEqual(json.loads(res.body), expected)

    def test_quotas_index(self):
        req = webob.Request.blank('/v1.1/os-quotas')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        self.assertEqual(json.loads(res.body), quota_set_list())

    def test_quotas_show(self):
        req = webob.Request.blank('/v1.1/os-quotas/1234')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        self.assertEqual(json.loads(res.body), quota_set('1234'))

    def test_quotas_update(self):
        updated_quota_set = {'quota_set': {'instances': 50,
                             'cores': 50, 'ram': 51200, 'volumes': 10,
                             'gigabytes': 1000, 'floating_ips': 10,
                             'metadata_items': 128, 'injected_files': 5,
                             'injected_file_content_bytes': 10240}}

        req = webob.Request.blank('/v1.1/os-quotas/update_me')
        req.method = 'PUT'
        req.body = json.dumps(updated_quota_set)
        req.headers['Content-Type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=\
                               context.RequestContext('fake', 'fake',
                                                      is_admin=True)))

        self.assertEqual(json.loads(res.body), updated_quota_set)
