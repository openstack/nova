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

from oslo.serialization import jsonutils
import webob

from nova.api.openstack.compute.contrib import keypairs as keypairs_v2
from nova.api.openstack.compute.plugins.v3 import keypairs as keypairs_v21
from nova import db
from nova import exception
from nova.openstack.common import policy as common_policy
from nova import policy
from nova import quota
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_keypair


QUOTAS = quota.QUOTAS


keypair_data = {
    'public_key': 'FAKE_KEY',
    'fingerprint': 'FAKE_FINGERPRINT',
}


def fake_keypair(name):
    return dict(test_keypair.fake_keypair,
                name=name, **keypair_data)


def db_key_pair_get_all_by_user(self, user_id):
    return [fake_keypair('FAKE')]


def db_key_pair_create(self, keypair):
    return fake_keypair(name=keypair['name'])


def db_key_pair_destroy(context, user_id, name):
    if not (user_id and name):
        raise Exception()


def db_key_pair_create_duplicate(context, keypair):
    raise exception.KeyPairExists(key_name=keypair.get('name', ''))


class KeypairsTestV21(test.TestCase):
    base_url = '/v2/fake'
    validation_error = exception.ValidationError

    def _setup_app_and_controller(self):
        self.app_server = fakes.wsgi_app_v21(init_only=('os-keypairs',
                                                        'servers'))
        self.controller = keypairs_v21.KeypairController()

    def setUp(self):
        super(KeypairsTestV21, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)

        self.stubs.Set(db, "key_pair_get_all_by_user",
                       db_key_pair_get_all_by_user)
        self.stubs.Set(db, "key_pair_create",
                       db_key_pair_create)
        self.stubs.Set(db, "key_pair_destroy",
                       db_key_pair_destroy)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Keypairs'])
        self._setup_app_and_controller()

    def test_keypair_list(self):
        req = fakes.HTTPRequest.blank('')
        res_dict = self.controller.index(req)
        response = {'keypairs': [{'keypair': dict(keypair_data, name='FAKE')}]}
        self.assertEqual(res_dict, response)

    def test_keypair_create(self):
        body = {'keypair': {'name': 'create_test'}}
        req = fakes.HTTPRequest.blank('')
        res_dict = self.controller.create(req, body=body)
        self.assertTrue(len(res_dict['keypair']['fingerprint']) > 0)
        self.assertTrue(len(res_dict['keypair']['private_key']) > 0)

    def _test_keypair_create_bad_request_case(self,
                                              body,
                                              exception):
        req = fakes.HTTPRequest.blank('')
        self.assertRaises(exception,
                          self.controller.create, req, body=body)

    def test_keypair_create_with_empty_name(self):
        body = {'keypair': {'name': ''}}
        self._test_keypair_create_bad_request_case(body,
                                                   self.validation_error)

    def test_keypair_create_with_name_too_long(self):
        body = {
            'keypair': {
                'name': 'a' * 256
            }
        }
        self._test_keypair_create_bad_request_case(body,
                                                   self.validation_error)

    def test_keypair_create_with_non_alphanumeric_name(self):
        body = {
            'keypair': {
                'name': 'test/keypair'
            }
        }
        self._test_keypair_create_bad_request_case(body,
                                                   webob.exc.HTTPBadRequest)

    def test_keypair_import_bad_key(self):
        body = {
            'keypair': {
                'name': 'create_test',
                'public_key': 'ssh-what negative',
            },
        }
        self._test_keypair_create_bad_request_case(body,
                                                   webob.exc.HTTPBadRequest)

    def test_keypair_create_with_invalid_keypair_body(self):
        body = {'alpha': {'name': 'create_test'}}
        self._test_keypair_create_bad_request_case(body,
                                                   self.validation_error)

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
        req = fakes.HTTPRequest.blank('')
        res_dict = self.controller.create(req, body=body)
        # FIXME(ja): sholud we check that public_key was sent to create?
        self.assertTrue(len(res_dict['keypair']['fingerprint']) > 0)
        self.assertNotIn('private_key', res_dict['keypair'])

    def test_keypair_import_quota_limit(self):

        def fake_quotas_count(self, context, resource, *args, **kwargs):
            return 100

        self.stubs.Set(QUOTAS, "count", fake_quotas_count)

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

        req = fakes.HTTPRequest.blank('')
        ex = self.assertRaises(webob.exc.HTTPForbidden,
                               self.controller.create, req, body=body)
        self.assertIn('Quota exceeded, too many key pairs.', ex.explanation)

    def test_keypair_create_quota_limit(self):

        def fake_quotas_count(self, context, resource, *args, **kwargs):
            return 100

        self.stubs.Set(QUOTAS, "count", fake_quotas_count)

        body = {
            'keypair': {
                'name': 'create_test',
            },
        }

        req = fakes.HTTPRequest.blank('')
        ex = self.assertRaises(webob.exc.HTTPForbidden,
                               self.controller.create, req, body=body)
        self.assertIn('Quota exceeded, too many key pairs.', ex.explanation)

    def test_keypair_create_duplicate(self):
        self.stubs.Set(db, "key_pair_create", db_key_pair_create_duplicate)
        body = {'keypair': {'name': 'create_duplicate'}}
        req = fakes.HTTPRequest.blank('')
        ex = self.assertRaises(webob.exc.HTTPConflict,
                               self.controller.create, req, body=body)
        self.assertIn("Key pair 'create_duplicate' already exists.",
                      ex.explanation)

    def test_keypair_delete(self):
        req = fakes.HTTPRequest.blank('')
        self.controller.delete(req, 'FAKE')

    def test_keypair_get_keypair_not_found(self):
        req = fakes.HTTPRequest.blank('')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'DOESNOTEXIST')

    def test_keypair_delete_not_found(self):

        def db_key_pair_get_not_found(context, user_id, name):
            raise exception.KeypairNotFound(user_id=user_id, name=name)

        self.stubs.Set(db, "key_pair_destroy",
                       db_key_pair_get_not_found)
        req = fakes.HTTPRequest.blank('')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, 'FAKE')

    def test_keypair_show(self):

        def _db_key_pair_get(context, user_id, name):
            return dict(test_keypair.fake_keypair,
                        name='foo', public_key='XXX', fingerprint='YYY')

        self.stubs.Set(db, "key_pair_get", _db_key_pair_get)

        req = fakes.HTTPRequest.blank('')
        res_dict = self.controller.show(req, 'FAKE')
        self.assertEqual('foo', res_dict['keypair']['name'])
        self.assertEqual('XXX', res_dict['keypair']['public_key'])
        self.assertEqual('YYY', res_dict['keypair']['fingerprint'])

    def test_keypair_show_not_found(self):

        def _db_key_pair_get(context, user_id, name):
            raise exception.KeypairNotFound(user_id=user_id, name=name)

        self.stubs.Set(db, "key_pair_get", _db_key_pair_get)

        req = fakes.HTTPRequest.blank('')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'FAKE')

    def test_show_server(self):
        self.stubs.Set(db, 'instance_get',
                        fakes.fake_instance_get())
        self.stubs.Set(db, 'instance_get_by_uuid',
                        fakes.fake_instance_get())
        req = webob.Request.blank(self.base_url + '/servers/1')
        req.headers['Content-Type'] = 'application/json'
        response = req.get_response(self.app_server)
        self.assertEqual(response.status_int, 200)
        res_dict = jsonutils.loads(response.body)
        self.assertIn('key_name', res_dict['server'])
        self.assertEqual(res_dict['server']['key_name'], '')

    def test_detail_servers(self):
        # Sort is disabled in v2 without an extension so stub out
        # the non-sorted DB get
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fakes.fake_instance_get_all_by_filters())
        # But it is enabled in v3 so stub out the sorted function
        self.stubs.Set(db, 'instance_get_all_by_filters_sort',
                       fakes.fake_instance_get_all_by_filters())
        req = fakes.HTTPRequest.blank(self.base_url + '/servers/detail')
        res = req.get_response(self.app_server)
        server_dicts = jsonutils.loads(res.body)['servers']
        self.assertEqual(len(server_dicts), 5)

        for server_dict in server_dicts:
            self.assertIn('key_name', server_dict)
            self.assertEqual(server_dict['key_name'], '')


class KeypairPolicyTestV21(test.TestCase):
    KeyPairController = keypairs_v21.KeypairController()
    policy_path = 'compute_extension:v3:os-keypairs'

    def setUp(self):
        super(KeypairPolicyTestV21, self).setUp()

        def _db_key_pair_get(context, user_id, name):
            return dict(test_keypair.fake_keypair,
                        name='foo', public_key='XXX', fingerprint='YYY')

        self.stubs.Set(db, "key_pair_get",
                       _db_key_pair_get)
        self.stubs.Set(db, "key_pair_get_all_by_user",
                       db_key_pair_get_all_by_user)
        self.stubs.Set(db, "key_pair_create",
                       db_key_pair_create)
        self.stubs.Set(db, "key_pair_destroy",
                       db_key_pair_destroy)

    def test_keypair_list_fail_policy(self):
        rules = {self.policy_path + ':index':
                     common_policy.parse_rule('role:admin')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.index,
                          req)

    def test_keypair_list_pass_policy(self):
        rules = {self.policy_path + ':index':
                     common_policy.parse_rule('')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        res = self.KeyPairController.index(req)
        self.assertIn('keypairs', res)

    def test_keypair_show_fail_policy(self):
        rules = {self.policy_path + ':show':
                     common_policy.parse_rule('role:admin')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.show,
                          req, 'FAKE')

    def test_keypair_show_pass_policy(self):
        rules = {self.policy_path + ':show':
                     common_policy.parse_rule('')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        res = self.KeyPairController.show(req, 'FAKE')
        self.assertIn('keypair', res)

    def test_keypair_create_fail_policy(self):
        body = {'keypair': {'name': 'create_test'}}
        rules = {self.policy_path + ':create':
                     common_policy.parse_rule('role:admin')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        req.method = 'POST'
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.create,
                          req, body=body)

    def test_keypair_create_pass_policy(self):
        body = {'keypair': {'name': 'create_test'}}
        rules = {self.policy_path + ':create':
                     common_policy.parse_rule('')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        req.method = 'POST'
        res = self.KeyPairController.create(req, body=body)
        self.assertIn('keypair', res)

    def test_keypair_delete_fail_policy(self):
        rules = {self.policy_path + ':delete':
                     common_policy.parse_rule('role:admin')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        req.method = 'DELETE'
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.delete,
                          req, 'FAKE')

    def test_keypair_delete_pass_policy(self):
        rules = {self.policy_path + ':delete':
                     common_policy.parse_rule('')}
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank('')
        req.method = 'DELETE'
        res = self.KeyPairController.delete(req, 'FAKE')

        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.KeyPairController, keypairs_v21.KeypairController):
            status_int = self.KeyPairController.delete.wsgi_code
        else:
            status_int = res.status_int
        self.assertEqual(202, status_int)


class KeypairsTestV2(KeypairsTestV21):
    validation_error = webob.exc.HTTPBadRequest

    def _setup_app_and_controller(self):
        self.app_server = fakes.wsgi_app(init_only=('servers',))
        self.controller = keypairs_v2.KeypairController()


class KeypairPolicyTestV2(KeypairPolicyTestV21):
    KeyPairController = keypairs_v2.KeypairController()
    policy_path = 'compute_extension:keypairs'
