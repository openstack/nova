# Copyright 2010 OpenStack LLC.
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

from nova import test
from nova import utils
from nova.api.openstack import users
from nova.auth.manager import User, Project
from nova.tests.api.openstack import fakes


def fake_init(self):
    self.manager = fakes.FakeAuthManager()


def fake_admin_check(self, req):
    return True


class UsersTest(test.TestCase):
    def setUp(self):
        super(UsersTest, self).setUp()
        self.flags(verbose=True, allow_admin_api=True)
        self.stubs.Set(users.Controller, '__init__',
                       fake_init)
        self.stubs.Set(users.Controller, '_check_admin',
                       fake_admin_check)
        fakes.FakeAuthManager.clear_fakes()
        fakes.FakeAuthManager.projects = dict(testacct=Project('testacct',
                                                               'testacct',
                                                               'id1',
                                                               'test',
                                                               []))
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)

        fakemgr = fakes.FakeAuthManager()
        fakemgr.add_user(User('id1', 'guy1', 'acc1', 'secret1', False))
        fakemgr.add_user(User('id2', 'guy2', 'acc2', 'secret2', True))

    def test_get_user_list(self):
        req = webob.Request.blank('/v1.0/users')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res_dict['users']), 2)

    def test_get_user_by_id(self):
        req = webob.Request.blank('/v1.0/users/id2')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res_dict['user']['id'], 'id2')
        self.assertEqual(res_dict['user']['name'], 'guy2')
        self.assertEqual(res_dict['user']['secret'], 'secret2')
        self.assertEqual(res_dict['user']['admin'], True)
        self.assertEqual(res.status_int, 200)

    def test_user_delete(self):
        # Check the user exists
        req = webob.Request.blank('/v1.0/users/id1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res_dict['user']['id'], 'id1')
        self.assertEqual(res.status_int, 200)

        # Delete the user
        req = webob.Request.blank('/v1.0/users/id1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertTrue('id1' not in [u.id for u in
                        fakes.FakeAuthManager.auth_data])
        self.assertEqual(res.status_int, 200)

        # Check the user is not returned (and returns 404)
        req = webob.Request.blank('/v1.0/users/id1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 404)

    def test_user_create(self):
        secret = utils.generate_password()
        body = dict(user=dict(name='test_guy',
                              access='acc3',
                              secret=secret,
                              admin=True))
        req = webob.Request.blank('/v1.0/users')
        req.headers["Content-Type"] = "application/json"
        req.method = 'POST'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)

        # NOTE(justinsb): This is a questionable assertion in general
        # fake sets id=name, but others might not...
        self.assertEqual(res_dict['user']['id'], 'test_guy')

        self.assertEqual(res_dict['user']['name'], 'test_guy')
        self.assertEqual(res_dict['user']['access'], 'acc3')
        self.assertEqual(res_dict['user']['secret'], secret)
        self.assertEqual(res_dict['user']['admin'], True)
        self.assertTrue('test_guy' in [u.id for u in
                        fakes.FakeAuthManager.auth_data])
        self.assertEqual(len(fakes.FakeAuthManager.auth_data), 3)

    def test_user_update(self):
        new_secret = utils.generate_password()
        body = dict(user=dict(name='guy2',
                              access='acc2',
                              secret=new_secret))
        req = webob.Request.blank('/v1.0/users/id2')
        req.headers["Content-Type"] = "application/json"
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['user']['id'], 'id2')
        self.assertEqual(res_dict['user']['name'], 'guy2')
        self.assertEqual(res_dict['user']['access'], 'acc2')
        self.assertEqual(res_dict['user']['secret'], new_secret)
        self.assertEqual(res_dict['user']['admin'], True)
