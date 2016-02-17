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

import mock
from oslo_serialization import jsonutils
import webob

from oslo_policy import policy as oslo_policy

from nova.api.openstack.compute import keypairs as keypairs_v21
from nova.api.openstack.compute.legacy_v2.contrib import keypairs \
        as keypairs_v2
from nova.api.openstack import wsgi as os_wsgi
from nova.compute import api as compute_api
from nova import exception
from nova import objects
from nova import policy
from nova import quota
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_keypair
from nova.tests import uuidsentinel as uuids


QUOTAS = quota.QUOTAS


keypair_data = {
    'public_key': 'FAKE_KEY',
    'fingerprint': 'FAKE_FINGERPRINT',
}

FAKE_UUID = 'b48316c5-71e8-45e4-9884-6c78055b9b13'


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
    wsgi_api_version = os_wsgi.DEFAULT_API_VERSION

    def _setup_app_and_controller(self):
        self.app_server = fakes.wsgi_app_v21(init_only=('os-keypairs',
                                                        'servers'))
        self.controller = keypairs_v21.KeypairController()

    def setUp(self):
        super(KeypairsTestV21, self).setUp()
        fakes.stub_out_networking(self)
        fakes.stub_out_rate_limiting(self.stubs)

        self.stub_out("nova.db.key_pair_get_all_by_user",
                      db_key_pair_get_all_by_user)
        self.stub_out("nova.db.key_pair_create",
                      db_key_pair_create)
        self.stub_out("nova.db.key_pair_destroy",
                      db_key_pair_destroy)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Keypairs'])
        self._setup_app_and_controller()

        self.req = fakes.HTTPRequest.blank('', version=self.wsgi_api_version)

    def test_keypair_list(self):
        res_dict = self.controller.index(self.req)
        response = {'keypairs': [{'keypair': dict(keypair_data, name='FAKE')}]}
        self.assertEqual(res_dict, response)

    def test_keypair_create(self):
        body = {'keypair': {'name': 'create_test'}}
        res_dict = self.controller.create(self.req, body=body)
        self.assertTrue(len(res_dict['keypair']['fingerprint']) > 0)
        self.assertTrue(len(res_dict['keypair']['private_key']) > 0)
        self._assert_keypair_type(res_dict)

    def _test_keypair_create_bad_request_case(self,
                                              body,
                                              exception):
        self.assertRaises(exception,
                          self.controller.create, self.req, body=body)

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

    def test_keypair_create_with_name_leading_trailing_spaces(self):
        body = {
            'keypair': {
                'name': '  test  '
            }
        }
        self._test_keypair_create_bad_request_case(body,
                                                   self.validation_error)

    def test_keypair_create_with_name_leading_trailing_spaces_compat_mode(
            self):
        body = {'keypair': {'name': '  test  '}}
        self.req.set_legacy_v2()
        res_dict = self.controller.create(self.req, body=body)
        self.assertEqual('test', res_dict['keypair']['name'])

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
        res_dict = self.controller.create(self.req, body=body)
        # FIXME(ja): sholud we check that public_key was sent to create?
        self.assertTrue(len(res_dict['keypair']['fingerprint']) > 0)
        self.assertNotIn('private_key', res_dict['keypair'])
        self._assert_keypair_type(res_dict)

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

        ex = self.assertRaises(webob.exc.HTTPForbidden,
                               self.controller.create, self.req, body=body)
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

        ex = self.assertRaises(webob.exc.HTTPForbidden,
                               self.controller.create, self.req, body=body)
        self.assertIn('Quota exceeded, too many key pairs.', ex.explanation)

    def test_keypair_create_duplicate(self):
        self.stub_out("nova.db.key_pair_create", db_key_pair_create_duplicate)
        body = {'keypair': {'name': 'create_duplicate'}}
        ex = self.assertRaises(webob.exc.HTTPConflict,
                               self.controller.create, self.req, body=body)
        self.assertIn("Key pair 'create_duplicate' already exists.",
                      ex.explanation)

    def test_keypair_delete(self):
        self.controller.delete(self.req, 'FAKE')

    def test_keypair_get_keypair_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, 'DOESNOTEXIST')

    def test_keypair_delete_not_found(self):

        def db_key_pair_get_not_found(context, user_id, name):
            raise exception.KeypairNotFound(user_id=user_id, name=name)

        self.stub_out("nova.db.key_pair_destroy",
                      db_key_pair_get_not_found)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, self.req, 'FAKE')

    def test_keypair_show(self):

        def _db_key_pair_get(context, user_id, name):
            return dict(test_keypair.fake_keypair,
                        name='foo', public_key='XXX', fingerprint='YYY',
                        type='ssh')

        self.stub_out("nova.db.key_pair_get", _db_key_pair_get)

        res_dict = self.controller.show(self.req, 'FAKE')
        self.assertEqual('foo', res_dict['keypair']['name'])
        self.assertEqual('XXX', res_dict['keypair']['public_key'])
        self.assertEqual('YYY', res_dict['keypair']['fingerprint'])
        self._assert_keypair_type(res_dict)

    def test_keypair_show_not_found(self):

        def _db_key_pair_get(context, user_id, name):
            raise exception.KeypairNotFound(user_id=user_id, name=name)

        self.stub_out("nova.db.key_pair_get", _db_key_pair_get)

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, 'FAKE')

    def test_show_server(self):
        self.stub_out('nova.db.instance_get',
                      fakes.fake_instance_get())
        self.stub_out('nova.db.instance_get_by_uuid',
                      fakes.fake_instance_get())
        req = webob.Request.blank(self.base_url + '/servers/' + uuids.server)
        req.headers['Content-Type'] = 'application/json'
        response = req.get_response(self.app_server)
        self.assertEqual(response.status_int, 200)
        res_dict = jsonutils.loads(response.body)
        self.assertIn('key_name', res_dict['server'])
        self.assertEqual(res_dict['server']['key_name'], '')

    @mock.patch('nova.compute.api.API.get_all')
    def test_detail_servers(self, mock_get_all):
        # NOTE(danms): Orphan these fakes (no context) so that we
        # are sure that the API is requesting what it needs without
        # having to lazy-load.
        mock_get_all.return_value = objects.InstanceList(
            objects=[fakes.stub_instance_obj(ctxt=None, id=1),
                     fakes.stub_instance_obj(ctxt=None, id=2)])
        req = fakes.HTTPRequest.blank(self.base_url + '/servers/detail')
        res = req.get_response(self.app_server)
        server_dicts = jsonutils.loads(res.body)['servers']
        self.assertEqual(len(server_dicts), 2)

        for server_dict in server_dicts:
            self.assertIn('key_name', server_dict)
            self.assertEqual(server_dict['key_name'], '')

    def _assert_keypair_type(self, res_dict):
        self.assertNotIn('type', res_dict['keypair'])

    def test_create_server_keypair_name_with_leading_trailing(self):
        req = fakes.HTTPRequest.blank(self.base_url + '/servers')
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dump_as_bytes({'server': {'name': 'test',
                                               'flavorRef': 1,
                                               'keypair_name': '  abc  ',
                                               'imageRef': FAKE_UUID}})
        res = req.get_response(self.app_server)
        self.assertEqual(400, res.status_code)
        self.assertIn('keypair_name', res.body)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_server_keypair_name_with_leading_trailing_compat_mode(
            self, mock_create):
        mock_create.return_value = (
            objects.InstanceList(objects=[
                fakes.stub_instance_obj(ctxt=None, id=1)]),
            None)
        req = fakes.HTTPRequest.blank(self.base_url + '/servers')
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dump_as_bytes({'server': {'name': 'test',
                                               'flavorRef': 1,
                                               'keypair_name': '  abc  ',
                                               'imageRef': FAKE_UUID}})
        req.set_legacy_v2()
        res = req.get_response(self.app_server)
        self.assertEqual(202, res.status_code)


class KeypairPolicyTestV21(test.NoDBTestCase):
    KeyPairController = keypairs_v21.KeypairController()
    policy_path = 'os_compute_api:os-keypairs'

    def setUp(self):
        super(KeypairPolicyTestV21, self).setUp()

        def _db_key_pair_get(context, user_id, name):
            return dict(test_keypair.fake_keypair,
                        name='foo', public_key='XXX', fingerprint='YYY',
                        type='ssh')

        self.stub_out("nova.db.key_pair_get", _db_key_pair_get)
        self.stub_out("nova.db.key_pair_get_all_by_user",
                      db_key_pair_get_all_by_user)
        self.stub_out("nova.db.key_pair_destroy", db_key_pair_destroy)

        self.req = fakes.HTTPRequest.blank('')

    def test_keypair_list_fail_policy(self):
        rules = {self.policy_path + ':index': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.index,
                          self.req)

    def test_keypair_list_pass_policy(self):
        rules = {self.policy_path + ':index': ''}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        res = self.KeyPairController.index(self.req)
        self.assertIn('keypairs', res)

    def test_keypair_show_fail_policy(self):
        rules = {self.policy_path + ':show': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.show,
                          self.req, 'FAKE')

    def test_keypair_show_pass_policy(self):
        rules = {self.policy_path + ':show': ''}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        res = self.KeyPairController.show(self.req, 'FAKE')
        self.assertIn('keypair', res)

    def test_keypair_create_fail_policy(self):
        body = {'keypair': {'name': 'create_test'}}
        rules = {self.policy_path + ':create': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.create,
                          self.req, body=body)

    def _assert_keypair_create(self, mock_create, req):
        mock_create.assert_called_with(req, 'fake_user', 'create_test', 'ssh')

    @mock.patch.object(compute_api.KeypairAPI, 'create_key_pair')
    def test_keypair_create_pass_policy(self, mock_create):
        keypair_obj = objects.KeyPair(name='', public_key='',
                                      fingerprint='', user_id='')

        mock_create.return_value = (keypair_obj, 'dummy')
        body = {'keypair': {'name': 'create_test'}}
        rules = {self.policy_path + ':create': ''}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        res = self.KeyPairController.create(self.req, body=body)
        self.assertIn('keypair', res)
        req = self.req.environ['nova.context']
        self._assert_keypair_create(mock_create, req)

    def test_keypair_delete_fail_policy(self):
        rules = {self.policy_path + ':delete': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.assertRaises(exception.Forbidden,
                          self.KeyPairController.delete,
                          self.req, 'FAKE')

    def test_keypair_delete_pass_policy(self):
        rules = {self.policy_path + ':delete': ''}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.KeyPairController.delete(self.req, 'FAKE')


class KeypairsTestV2(KeypairsTestV21):
    validation_error = webob.exc.HTTPBadRequest

    def _setup_app_and_controller(self):
        self.app_server = fakes.wsgi_app(init_only=('servers',))
        self.controller = keypairs_v2.KeypairController()

    def test_keypair_create_with_name_leading_trailing_spaces(
            self):
        body = {'keypair': {'name': '  test  '}}
        self.req.set_legacy_v2()
        res_dict = self.controller.create(self.req, body=body)
        self.assertEqual('  test  ', res_dict['keypair']['name'])

    def test_keypair_create_with_name_leading_trailing_spaces_compat_mode(
            self):
        pass

    def test_create_server_keypair_name_with_leading_trailing(self):
        pass

    @mock.patch.object(compute_api.API, 'create')
    def test_create_server_keypair_name_with_leading_trailing_compat_mode(
            self, mock_create):
        mock_create.return_value = (
            objects.InstanceList(objects=[
                fakes.stub_instance_obj(ctxt=None, id=1)]),
            None)
        req = fakes.HTTPRequest.blank(self.base_url + '/servers')
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dump_as_bytes({'server': {'name': 'test',
                                               'flavorRef': 1,
                                               'keypair_name': '  abc  ',
                                               'imageRef': FAKE_UUID}})
        res = req.get_response(self.app_server)
        self.assertEqual(202, res.status_code)


class KeypairsTestV22(KeypairsTestV21):
    wsgi_api_version = '2.2'

    def test_keypair_list(self):
        res_dict = self.controller.index(self.req)
        expected = {'keypairs': [{'keypair': dict(keypair_data, name='FAKE',
                                                  type='ssh')}]}
        self.assertEqual(expected, res_dict)

    def _assert_keypair_type(self, res_dict):
        self.assertEqual('ssh', res_dict['keypair']['type'])

    def test_keypair_create_with_name_leading_trailing_spaces_compat_mode(
            self):
        pass

    def test_create_server_keypair_name_with_leading_trailing_compat_mode(
            self):
        pass


class KeypairsTestV210(KeypairsTestV22):
    wsgi_api_version = '2.10'

    def test_keypair_create_with_name_leading_trailing_spaces_compat_mode(
            self):
        pass

    def test_create_server_keypair_name_with_leading_trailing_compat_mode(
            self):
        pass

    def test_keypair_list_other_user(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs?user_id=foo',
                                      version=self.wsgi_api_version,
                                      use_admin_context=True)
        with mock.patch.object(self.controller.api, 'get_key_pairs') as mock_g:
            self.controller.index(req)
            userid = mock_g.call_args_list[0][0][1]
            self.assertEqual('foo', userid)

    def test_keypair_list_other_user_not_admin(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs?user_id=foo',
                                      version=self.wsgi_api_version)
        with mock.patch.object(self.controller.api, 'get_key_pairs'):
            self.assertRaises(exception.PolicyNotAuthorized,
                              self.controller.index, req)

    def test_keypair_show_other_user(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs/FAKE?user_id=foo',
                                      version=self.wsgi_api_version,
                                      use_admin_context=True)
        with mock.patch.object(self.controller.api, 'get_key_pair') as mock_g:
            self.controller.show(req, 'FAKE')
            userid = mock_g.call_args_list[0][0][1]
            self.assertEqual('foo', userid)

    def test_keypair_show_other_user_not_admin(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs/FAKE?user_id=foo',
                                      version=self.wsgi_api_version)
        with mock.patch.object(self.controller.api, 'get_key_pair'):
            self.assertRaises(exception.PolicyNotAuthorized,
                              self.controller.show, req, 'FAKE')

    def test_keypair_delete_other_user(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs/FAKE?user_id=foo',
                                      version=self.wsgi_api_version,
                                      use_admin_context=True)
        with mock.patch.object(self.controller.api,
                               'delete_key_pair') as mock_g:
            self.controller.delete(req, 'FAKE')
            userid = mock_g.call_args_list[0][0][1]
            self.assertEqual('foo', userid)

    def test_keypair_delete_other_user_not_admin(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs/FAKE?user_id=foo',
                                      version=self.wsgi_api_version)
        with mock.patch.object(self.controller.api, 'delete_key_pair'):
            self.assertRaises(exception.PolicyNotAuthorized,
                              self.controller.delete, req, 'FAKE')

    def test_keypair_create_other_user(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs',
                                      version=self.wsgi_api_version,
                                      use_admin_context=True)
        body = {'keypair': {'name': 'create_test',
                            'user_id': '8861f37f-034e-4ca8-8abe-6d13c074574a'}}
        with mock.patch.object(self.controller.api,
                               'create_key_pair',
                               return_value=(mock.MagicMock(), 1)) as mock_g:
            res = self.controller.create(req, body=body)
            userid = mock_g.call_args_list[0][0][1]
            self.assertEqual('8861f37f-034e-4ca8-8abe-6d13c074574a', userid)
        self.assertIn('keypair', res)

    def test_keypair_import_other_user(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs',
                                      version=self.wsgi_api_version,
                                      use_admin_context=True)
        body = {'keypair': {'name': 'create_test',
                            'user_id': '8861f37f-034e-4ca8-8abe-6d13c074574a',
                            'public_key': 'public_key'}}
        with mock.patch.object(self.controller.api,
                               'import_key_pair') as mock_g:
            res = self.controller.create(req, body=body)
            userid = mock_g.call_args_list[0][0][1]
            self.assertEqual('8861f37f-034e-4ca8-8abe-6d13c074574a', userid)
        self.assertIn('keypair', res)

    def test_keypair_create_other_user_not_admin(self):
        req = fakes.HTTPRequest.blank(self.base_url +
                                      '/os-keypairs',
                                      version=self.wsgi_api_version)
        body = {'keypair': {'name': 'create_test',
                            'user_id': '8861f37f-034e-4ca8-8abe-6d13c074574a'}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.create,
                          req, body=body)


class KeypairPolicyTestV2(KeypairPolicyTestV21):
    KeyPairController = keypairs_v2.KeypairController()
    policy_path = 'compute_extension:keypairs'

    def _assert_keypair_create(self, mock_create, req):
        mock_create.assert_called_with(req, 'fake_user', 'create_test')
