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

from lxml import etree

from nova.api.openstack.compute.contrib import users
from nova.auth.manager import User, Project
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


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

        self.controller = users.Controller()

    def test_get_user_list(self):
        req = fakes.HTTPRequest.blank('/v2/fake/users')
        res_dict = self.controller.index(req)

        self.assertEqual(len(res_dict['users']), 2)

    def test_get_user_by_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/users/id2')
        res_dict = self.controller.show(req, 'id2')

        self.assertEqual(res_dict['user']['id'], 'id2')
        self.assertEqual(res_dict['user']['name'], 'guy2')
        self.assertEqual(res_dict['user']['secret'], 'secret2')
        self.assertEqual(res_dict['user']['admin'], True)

    def test_user_delete(self):
        req = fakes.HTTPRequest.blank('/v2/fake/users/id1')
        self.controller.delete(req, 'id1')

        self.assertTrue('id1' not in [u.id for u in
                        fakes.FakeAuthManager.auth_data])

    def test_user_create(self):
        secret = utils.generate_password()
        body = dict(user=dict(name='test_guy',
                              access='acc3',
                              secret=secret,
                              admin=True))
        req = fakes.HTTPRequest.blank('/v2/fake/users')
        res_dict = self.controller.create(req, body)

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

        req = fakes.HTTPRequest.blank('/v2/fake/users/id2')
        res_dict = self.controller.update(req, 'id2', body)

        self.assertEqual(res_dict['user']['id'], 'id2')
        self.assertEqual(res_dict['user']['name'], 'guy2')
        self.assertEqual(res_dict['user']['access'], 'acc2')
        self.assertEqual(res_dict['user']['secret'], new_secret)
        self.assertEqual(res_dict['user']['admin'], True)


class TestUsersXMLSerializer(test.TestCase):

    def test_index(self):
        serializer = users.UsersTemplate()
        fixture = {'users': [{'id': 'id1',
                              'name': 'guy1',
                              'secret': 'secret1',
                              'admin': False},
                             {'id': 'id2',
                              'name': 'guy2',
                              'secret': 'secret2',
                              'admin': True}]}

        output = serializer.serialize(fixture)
        res_tree = etree.XML(output)

        self.assertEqual(res_tree.tag, 'users')
        self.assertEqual(len(res_tree), 2)
        self.assertEqual(res_tree[0].tag, 'user')
        self.assertEqual(res_tree[0].get('id'), 'id1')
        self.assertEqual(res_tree[1].tag, 'user')
        self.assertEqual(res_tree[1].get('id'), 'id2')

    def test_show(self):
        serializer = users.UserTemplate()
        fixture = {'user': {'id': 'id2',
                            'name': 'guy2',
                            'secret': 'secret2',
                            'admin': True}}

        output = serializer.serialize(fixture)
        res_tree = etree.XML(output)

        self.assertEqual(res_tree.tag, 'user')
        self.assertEqual(res_tree.get('id'), 'id2')
        self.assertEqual(res_tree.get('name'), 'guy2')
        self.assertEqual(res_tree.get('secret'), 'secret2')
        self.assertEqual(res_tree.get('admin'), 'True')
