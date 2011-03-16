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

import stubout
import webob

import nova.api
import nova.api.openstack.auth
from nova import context
from nova import flags
from nova import test
from nova.auth.manager import User, Project
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS
FLAGS.verbose = True


def fake_init(self):
    self.manager = fakes.FakeAuthManager()


def fake_admin_check(self, req):
    return True


class UsersTest(test.TestCase):
    def setUp(self):
        super(UsersTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.stubs.Set(nova.api.openstack.users.Controller, '__init__',
                       fake_init)
        self.stubs.Set(nova.api.openstack.users.Controller, '_check_admin',
                       fake_admin_check)
        fakes.FakeAuthManager.clear_fakes()
        fakes.FakeAuthManager.projects = dict(testacct=Project('testacct',
                                                               'testacct',
                                                               'guy1',
                                                               'test',
                                                               []))
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)

        self.allow_admin = FLAGS.allow_admin_api
        FLAGS.allow_admin_api = True
        fakemgr = fakes.FakeAuthManager()
        fakemgr.add_user(User(1, 'guy1', 'acc1', 'fortytwo!', False))
        fakemgr.add_user(User(2, 'guy2', 'acc2', 'swordfish', True))

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.allow_admin_api = self.allow_admin
        super(UsersTest, self).tearDown()

    def test_get_user_list(self):
        req = webob.Request.blank('/v1.0/users')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res_dict['users']), 2)

    def test_get_user_by_id(self):
        req = webob.Request.blank('/v1.0/users/guy2')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res_dict['user']['id'], 'guy2')
        self.assertEqual(res_dict['user']['name'], 'guy2')
        self.assertEqual(res_dict['user']['secret'], 'swordfish')
        self.assertEqual(res_dict['user']['admin'], True)
        self.assertEqual(res.status_int, 200)

    def test_user_delete(self):
        req = webob.Request.blank('/v1.0/users/guy1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertTrue('guy1' not in [u.id for u in
                        fakes.FakeAuthManager.auth_data])
        self.assertEqual(res.status_int, 200)

    def test_user_create(self):
        body = dict(user=dict(name='test_guy',
                              access='acc3',
                              secret='invasionIsInNormandy',
                              admin=True))
        req = webob.Request.blank('/v1.0/users')
        req.headers["Content-Type"] = "application/json"
        req.method = 'POST'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['user']['id'], 'test_guy')
        self.assertEqual(res_dict['user']['name'], 'test_guy')
        self.assertEqual(res_dict['user']['access'], 'acc3')
        self.assertEqual(res_dict['user']['secret'], 'invasionIsInNormandy')
        self.assertEqual(res_dict['user']['admin'], True)
        self.assertTrue('test_guy' in [u.id for u in
                        fakes.FakeAuthManager.auth_data])
        self.assertEqual(len(fakes.FakeAuthManager.auth_data), 3)

    def test_user_update(self):
        body = dict(user=dict(name='guy2',
                              access='acc2',
                              secret='invasionIsInNormandy'))
        req = webob.Request.blank('/v1.0/users/guy2')
        req.headers["Content-Type"] = "application/json"
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['user']['id'], 'guy2')
        self.assertEqual(res_dict['user']['name'], 'guy2')
        self.assertEqual(res_dict['user']['access'], 'acc2')
        self.assertEqual(res_dict['user']['secret'], 'invasionIsInNormandy')
        self.assertEqual(res_dict['user']['admin'], True)
