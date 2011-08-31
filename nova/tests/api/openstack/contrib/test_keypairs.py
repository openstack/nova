# Copyright 2011 Eldar Nugaev
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
from nova import db
from nova import test
from nova.api.openstack.contrib.keypairs import KeypairController
from nova.tests.api.openstack import fakes


def fake_keypair(name):
    return {'public_key': 'FAKE_KEY',
            'fingerprint': 'FAKE_FINGERPRINT',
            'name': name}


def db_key_pair_get_all_by_user(self, user_id):
    return [fake_keypair('FAKE')]


def db_key_pair_create(self, keypair):
    pass


def db_key_pair_destroy(context, user_id, name):
    if not (user_id and name):
        raise Exception()


class KeypairsTest(test.TestCase):

    def setUp(self):
        super(KeypairsTest, self).setUp()
        self.controller = KeypairController()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(db, "key_pair_get_all_by_user",
                       db_key_pair_get_all_by_user)
        self.stubs.Set(db, "key_pair_create",
                       db_key_pair_create)
        self.stubs.Set(db, "key_pair_destroy",
                       db_key_pair_destroy)
        self.context = context.get_admin_context()

    def test_keypair_list(self):
        req = webob.Request.blank('/v1.1/123/os-keypairs')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        response = {'keypairs': [{'keypair': fake_keypair('FAKE')}]}
        self.assertEqual(res_dict, response)

    def test_keypair_create(self):
        body = {'keypair': {'name': 'create_test'}}
        req = webob.Request.blank('/v1.1/123/os-keypairs')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertTrue(len(res_dict['keypair']['fingerprint']) > 0)
        self.assertTrue(len(res_dict['keypair']['private_key']) > 0)

    def test_keypair_import(self):
        body = {
            'keypair': {
                'name': 'create_test',
                'public_key': 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDBYIznA'
                              'x9D7118Q1VKGpXy2HDiKyUTM8XcUuhQpo0srqb9rboUp4'
                              'a9NmCwpWpeElDLuva707GOUnfaBAvHBwsRXyxHJjRaI6Y'
                              'Qj2oLJwqvaSaWUbyT1vtryRqy6J3TecN0WINY71f4uymi'
                              'MZP0wby4bKBcYnac8KiCIlvkEl0ETjkOGUq8OyWRmn7lj'
                              'j5SESEUdBP0JnuTFKddWTU/wD6wydeJaUhBTqOlHn0kX1'
                              'GyqoNTE1UEhcM5ZRWgfUZfTjVyDF2kGj3vJLCJtJ8LoGc'
                              'j7YaN4uPg1rBle+izwE/tLonRrds+cev8p6krSSrxWOwB'
                              'bHkXa6OciiJDvkRzJXzf',
            },
        }

        req = webob.Request.blank('/v1.1/123/os-keypairs')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        # FIXME(ja): sholud we check that public_key was sent to create?
        res_dict = json.loads(res.body)
        self.assertTrue(len(res_dict['keypair']['fingerprint']) > 0)
        self.assertFalse('private_key' in res_dict['keypair'])

    def test_keypair_delete(self):
        req = webob.Request.blank('/v1.1/123/os-keypairs/FAKE')
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
