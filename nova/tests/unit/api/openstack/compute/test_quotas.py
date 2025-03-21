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

from unittest import mock

from oslo_limit import fixture as limit_fixture
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import quota_sets as quotas_v21
from nova.db import constants as db_const
from nova import exception
from nova.limit import local as local_limit
from nova.limit import placement as placement_limit
from nova import objects
from nova import quota
from nova import test
from nova.tests.unit.api.openstack import fakes


def quota_set(id, include_server_group_quotas=True):
    res = {'quota_set': {'id': id, 'metadata_items': 128,
           'ram': 51200, 'floating_ips': -1, 'fixed_ips': -1,
           'instances': 10, 'injected_files': 5, 'cores': 20,
           'injected_file_content_bytes': 10240,
           'security_groups': -1, 'security_group_rules': -1,
           'key_pairs': 100, 'injected_file_path_bytes': 255}}
    if include_server_group_quotas:
        res['quota_set']['server_groups'] = 10
        res['quota_set']['server_group_members'] = 10
    return res


class BaseQuotaSetsTest(test.TestCase):

    def setUp(self):
        super(BaseQuotaSetsTest, self).setUp()
        # We need to stub out verify_project_id so that it doesn't
        # generate an EndpointNotFound exception and result in a
        # server error.
        self.stub_out('nova.api.openstack.identity.verify_project_id',
                      lambda ctx, project_id: True)


class QuotaSetsTestV21(BaseQuotaSetsTest):
    plugin = quotas_v21
    validation_error = exception.ValidationError
    include_server_group_quotas = True

    def setUp(self):
        super(QuotaSetsTestV21, self).setUp()
        self._setup_controller()
        self.default_quotas = {
            'instances': 10,
            'cores': 20,
            'ram': 51200,
            'floating_ips': -1,
            'fixed_ips': -1,
            'metadata_items': 128,
            'injected_files': 5,
            'injected_file_path_bytes': 255,
            'injected_file_content_bytes': 10240,
            'security_groups': -1,
            'security_group_rules': -1,
            'key_pairs': 100,
        }
        if self.include_server_group_quotas:
            self.default_quotas['server_groups'] = 10
            self.default_quotas['server_group_members'] = 10

    def _setup_controller(self):
        self.controller = self.plugin.QuotaSetsController()

    def _get_http_request(self, url=''):
        return fakes.HTTPRequest.blank(url)

    def test_format_quota_set(self):
        quota_set = self.controller._format_quota_set('1234',
                                                      self.default_quotas,
                                                      [])
        qs = quota_set['quota_set']

        self.assertEqual(qs['id'], '1234')
        self.assertEqual(qs['instances'], 10)
        self.assertEqual(qs['cores'], 20)
        self.assertEqual(qs['ram'], 51200)
        self.assertEqual(qs['floating_ips'], -1)
        self.assertEqual(qs['fixed_ips'], -1)
        self.assertEqual(qs['metadata_items'], 128)
        self.assertEqual(qs['injected_files'], 5)
        self.assertEqual(qs['injected_file_path_bytes'], 255)
        self.assertEqual(qs['injected_file_content_bytes'], 10240)
        self.assertEqual(qs['security_groups'], -1)
        self.assertEqual(qs['security_group_rules'], -1)
        self.assertEqual(qs['key_pairs'], 100)
        if self.include_server_group_quotas:
            self.assertEqual(qs['server_groups'], 10)
            self.assertEqual(qs['server_group_members'], 10)

    def test_validate_quota_limit(self):
        resource = 'fake'

        # Valid - finite values
        self.assertIsNone(self.controller._validate_quota_limit(resource,
                                                                50, 10, 100))

        # Valid - finite limit and infinite maximum
        self.assertIsNone(self.controller._validate_quota_limit(resource,
                                                                50, 10, -1))

        # Valid - infinite limit and infinite maximum
        self.assertIsNone(self.controller._validate_quota_limit(resource,
                                                                -1, 10, -1))

        # Valid - all infinite
        self.assertIsNone(self.controller._validate_quota_limit(resource,
                                                                -1, -1, -1))

        # Invalid - limit is less than -1
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._validate_quota_limit,
                          resource, -2, 10, 100)

        # Invalid - limit is less than minimum
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._validate_quota_limit,
                          resource, 5, 10, 100)

        # Invalid - limit is greater than maximum
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._validate_quota_limit,
                          resource, 200, 10, 100)

        # Invalid - infinite limit is greater than maximum
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._validate_quota_limit,
                          resource, -1, 10, 100)

        # Invalid - limit is less than infinite minimum
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._validate_quota_limit,
                          resource, 50, -1, -1)

        # Invalid - limit is larger than 0x7FFFFFFF
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._validate_quota_limit,
                          resource, db_const.MAX_INT + 1, -1, -1)

    def test_quotas_defaults(self):
        uri = '/v2/%s/os-quota-sets/%s/defaults' % (
                fakes.FAKE_PROJECT_ID, fakes.FAKE_PROJECT_ID)

        req = fakes.HTTPRequest.blank(uri)
        res_dict = self.controller.defaults(req, fakes.FAKE_PROJECT_ID)
        self.default_quotas.update({'id': fakes.FAKE_PROJECT_ID})
        expected = {'quota_set': self.default_quotas}

        self.assertEqual(res_dict, expected)

    def test_quotas_show(self):
        req = self._get_http_request()
        res_dict = self.controller.show(req, 1234)

        ref_quota_set = quota_set('1234', self.include_server_group_quotas)
        self.assertEqual(res_dict, ref_quota_set)

    def test_quotas_update(self):
        self.default_quotas.update({
            'instances': 50,
            'cores': 50
        })
        body = {'quota_set': self.default_quotas}
        req = self._get_http_request()
        res_dict = self.controller.update(req, 'update_me', body=body)
        self.assertEqual(body, res_dict)

    @mock.patch('nova.objects.Quotas.create_limit')
    def test_quotas_update_with_good_data(self, mock_createlimit):
        self.default_quotas.update({})
        body = {'quota_set': self.default_quotas}
        req = self._get_http_request()
        self.controller.update(req, 'update_me', body=body)
        self.assertEqual(len(self.default_quotas),
                         len(mock_createlimit.mock_calls))

    @mock.patch('nova.api.validation.validators._SchemaValidator.validate')
    @mock.patch('nova.objects.Quotas.create_limit')
    def test_quotas_update_with_bad_data(self, mock_createlimit,
                                                  mock_validate):
        self.default_quotas.update({
            'instances': 50,
            'cores': -50
        })
        body = {'quota_set': self.default_quotas}
        req = self._get_http_request()
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)
        self.assertEqual(0,
                         len(mock_createlimit.mock_calls))

    def test_quotas_update_zero_value(self):
        body = {'quota_set': {'instances': 0, 'cores': 0,
                              'ram': 0, 'floating_ips': -1,
                              'metadata_items': 0,
                              'injected_files': 0,
                              'injected_file_content_bytes': 0,
                              'injected_file_path_bytes': 0,
                              'security_groups': -1,
                              'security_group_rules': -1,
                              'key_pairs': 100, 'fixed_ips': -1}}
        if self.include_server_group_quotas:
            body['quota_set']['server_groups'] = 10
            body['quota_set']['server_group_members'] = 10

        req = self._get_http_request()
        res_dict = self.controller.update(req, 'update_me', body=body)
        self.assertEqual(body, res_dict)

    def _quotas_update_bad_request_case(self, body):
        req = self._get_http_request()
        self.assertRaises(self.validation_error, self.controller.update,
                          req, 'update_me', body=body)

    def test_quotas_update_invalid_key(self):
        body = {'quota_set': {'instances2': -2, 'cores': -2,
                              'ram': -2, 'floating_ips': -2,
                              'metadata_items': -2, 'injected_files': -2,
                              'injected_file_content_bytes': -2}}
        self._quotas_update_bad_request_case(body)

    def test_quotas_update_invalid_limit(self):
        body = {'quota_set': {'instances': -2, 'cores': -2,
                              'ram': -2, 'floating_ips': -2, 'fixed_ips': -2,
                              'metadata_items': -2, 'injected_files': -2,
                              'injected_file_content_bytes': -2}}
        self._quotas_update_bad_request_case(body)

    def test_quotas_update_empty_body(self):
        body = {}
        self._quotas_update_bad_request_case(body)

    def test_quotas_update_invalid_value_non_int(self):
        # when PUT non integer value
        self.default_quotas.update({
            'instances': 'test'
        })
        body = {'quota_set': self.default_quotas}
        self._quotas_update_bad_request_case(body)

    def test_quotas_update_invalid_value_with_float(self):
        # when PUT non integer value
        self.default_quotas.update({
            'instances': 50.5
        })
        body = {'quota_set': self.default_quotas}
        self._quotas_update_bad_request_case(body)

    def test_quotas_update_invalid_value_with_unicode(self):
        # when PUT non integer value
        self.default_quotas.update({
            'instances': u'\u30aa\u30fc\u30d7\u30f3'
        })
        body = {'quota_set': self.default_quotas}
        self._quotas_update_bad_request_case(body)

    @mock.patch('nova.objects.Quotas.destroy_all_by_project')
    def test_quotas_delete(self, mock_destroy_all_by_project):
        req = self._get_http_request()
        self.controller.delete(req, 1234)
        self.assertEqual(202, self.controller.delete.wsgi_codes(req))
        mock_destroy_all_by_project.assert_called_once_with(
            req.environ['nova.context'], 1234)

    def test_duplicate_quota_filter(self):
        query_string = 'user_id=1&user_id=2'
        req = fakes.HTTPRequest.blank('', query_string=query_string)
        self.controller.show(req, 1234)
        self.controller.update(req, 1234, body={'quota_set': {}})
        self.controller.detail(req, 1234)
        self.controller.delete(req, 1234)

    def test_quota_filter_negative_int_as_string(self):
        req = fakes.HTTPRequest.blank('', query_string='user_id=-1')
        self.controller.show(req, 1234)
        self.controller.update(req, 1234, body={'quota_set': {}})
        self.controller.detail(req, 1234)
        self.controller.delete(req, 1234)

    def test_quota_filter_int_as_string(self):
        req = fakes.HTTPRequest.blank('', query_string='user_id=123')
        self.controller.show(req, 1234)
        self.controller.update(req, 1234, body={'quota_set': {}})
        self.controller.detail(req, 1234)
        self.controller.delete(req, 1234)

    def test_unknown_quota_filter(self):
        query_string = 'unknown_filter=abc'
        req = fakes.HTTPRequest.blank('', query_string=query_string)
        self.controller.show(req, 1234)
        self.controller.update(req, 1234, body={'quota_set': {}})
        self.controller.detail(req, 1234)
        self.controller.delete(req, 1234)

    def test_quota_additional_filter(self):
        query_string = 'user_id=1&additional_filter=2'
        req = fakes.HTTPRequest.blank('', query_string=query_string)
        self.controller.show(req, 1234)
        self.controller.update(req, 1234, body={'quota_set': {}})
        self.controller.detail(req, 1234)
        self.controller.delete(req, 1234)


class ExtendedQuotasTestV21(BaseQuotaSetsTest):
    plugin = quotas_v21

    def setUp(self):
        super(ExtendedQuotasTestV21, self).setUp()
        self._setup_controller()

    fake_quotas = {'ram': {'limit': 51200,
                           'in_use': 12800,
                           'reserved': 12800},
                   'cores': {'limit': 20,
                             'in_use': 10,
                             'reserved': 5},
                   'instances': {'limit': 100,
                                 'in_use': 0,
                                 'reserved': 0}}

    def _setup_controller(self):
        self.controller = self.plugin.QuotaSetsController()

    def fake_get_quotas(self, context, id, user_id=None, usages=False):
        if usages:
            return self.fake_quotas
        else:
            return {k: v['limit'] for k, v in self.fake_quotas.items()}

    def fake_get_settable_quotas(self, context, project_id, user_id=None):
        return {
            'ram': {'minimum': self.fake_quotas['ram']['in_use'] +
                               self.fake_quotas['ram']['reserved'],
                    'maximum': -1},
            'cores': {'minimum': self.fake_quotas['cores']['in_use'] +
                                 self.fake_quotas['cores']['reserved'],
                      'maximum': -1},
            'instances': {'minimum': self.fake_quotas['instances']['in_use'] +
                                     self.fake_quotas['instances']['reserved'],
                          'maximum': -1},
        }

    def _get_http_request(self, url=''):
        return fakes.HTTPRequest.blank(url)

    @mock.patch.object(quota.QUOTAS, 'get_settable_quotas')
    def test_quotas_update_exceed_in_used(self, get_settable_quotas):
        body = {'quota_set': {'cores': 10}}

        get_settable_quotas.side_effect = self.fake_get_settable_quotas
        req = self._get_http_request()
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)

    @mock.patch.object(quota.QUOTAS, 'get_settable_quotas')
    def test_quotas_force_update_exceed_in_used(self, get_settable_quotas):
        with mock.patch.object(self.plugin.QuotaSetsController,
                               '_get_quotas') as _get_quotas:

            body = {'quota_set': {'cores': 10, 'force': 'True'}}

            get_settable_quotas.side_effect = self.fake_get_settable_quotas
            _get_quotas.side_effect = self.fake_get_quotas
            req = self._get_http_request()
            self.controller.update(req, 'update_me', body=body)

    @mock.patch('nova.objects.Quotas.create_limit')
    def test_quotas_update_good_data(self, mock_createlimit):
        body = {'quota_set': {'cores': 1,
                              'instances': 1}}
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-quota-sets/update_me' % fakes.FAKE_PROJECT_ID,
                use_admin_context=True)
        self.controller.update(req, 'update_me', body=body)
        self.assertEqual(2,
                         len(mock_createlimit.mock_calls))

    @mock.patch('nova.objects.Quotas.create_limit')
    @mock.patch.object(quota.QUOTAS, 'get_settable_quotas')
    def test_quotas_update_bad_data(self, mock_gsq, mock_createlimit):
        body = {'quota_set': {'cores': 10,
                              'instances': 1}}

        mock_gsq.side_effect = self.fake_get_settable_quotas
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-quota-sets/update_me' % fakes.FAKE_PROJECT_ID,
                use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)
        self.assertEqual(0,
                         len(mock_createlimit.mock_calls))


class UserQuotasTestV21(BaseQuotaSetsTest):
    plugin = quotas_v21
    include_server_group_quotas = True

    def setUp(self):
        super(UserQuotasTestV21, self).setUp()
        self._setup_controller()

    def _get_http_request(self, url=''):
        return fakes.HTTPRequest.blank(url)

    def _setup_controller(self):
        self.controller = self.plugin.QuotaSetsController()

    def test_user_quotas_show(self):
        req = self._get_http_request(
                '/v2/%s/os-quota-sets/%s?user_id=1' % (fakes.FAKE_PROJECT_ID,
                                                       fakes.FAKE_PROJECT_ID))
        res_dict = self.controller.show(req, fakes.FAKE_PROJECT_ID)
        ref_quota_set = quota_set(fakes.FAKE_PROJECT_ID,
                                  self.include_server_group_quotas)
        self.assertEqual(res_dict, ref_quota_set)

    def test_user_quotas_update(self):
        body = {'quota_set': {'instances': 10, 'cores': 20,
                              'ram': 51200, 'floating_ips': -1,
                              'fixed_ips': -1, 'metadata_items': 128,
                              'injected_files': 5,
                              'injected_file_content_bytes': 10240,
                              'injected_file_path_bytes': 255,
                              'security_groups': -1,
                              'security_group_rules': -1,
                              'key_pairs': 100}}
        if self.include_server_group_quotas:
            body['quota_set']['server_groups'] = 10
            body['quota_set']['server_group_members'] = 10

        url = ('/v2/%s/os-quota-sets/update_me?user_id=1' %
               fakes.FAKE_PROJECT_ID)
        req = self._get_http_request(url)
        res_dict = self.controller.update(req, 'update_me', body=body)

        self.assertEqual(body, res_dict)

    def test_user_quotas_update_exceed_project(self):
        body = {'quota_set': {'instances': 20}}

        url = ('/v2/%s/os-quota-sets/update_me?user_id=1' %
               fakes.FAKE_PROJECT_ID)
        req = self._get_http_request(url)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)

    @mock.patch('nova.objects.Quotas.destroy_all_by_project_and_user')
    def test_user_quotas_delete(self, mock_destroy_all_by_project_and_user):
        url = '/v2/%s/os-quota-sets/%s?user_id=1' % (fakes.FAKE_PROJECT_ID,
                                                     fakes.FAKE_PROJECT_ID)
        req = self._get_http_request(url)
        self.controller.delete(req, fakes.FAKE_PROJECT_ID)
        self.assertEqual(202, self.controller.delete.wsgi_codes(req))
        mock_destroy_all_by_project_and_user.assert_called_once_with(
            req.environ['nova.context'], fakes.FAKE_PROJECT_ID, '1'
        )

    @mock.patch('nova.objects.Quotas.create_limit')
    def test_user_quotas_update_good_data(self, mock_createlimit):
        body = {'quota_set': {'instances': 1,
                              'cores': 1}}

        url = ('/v2/%s/os-quota-sets/update_me?user_id=1' %
               fakes.FAKE_PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        self.controller.update(req, 'update_me', body=body)
        self.assertEqual(2,
                         len(mock_createlimit.mock_calls))

    @mock.patch('nova.objects.Quotas.create_limit')
    def test_user_quotas_update_bad_data(self, mock_createlimit):
        body = {'quota_set': {'instances': 20,
                              'cores': 1}}

        url = ('/v2/%s/os-quota-sets/update_me?user_id=1' %
               fakes.FAKE_PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)
        self.assertEqual(0,
                         len(mock_createlimit.mock_calls))


class QuotaSetsTestV236(test.NoDBTestCase):
    microversion = '2.36'

    def setUp(self):
        super(QuotaSetsTestV236, self).setUp()
        # We need to stub out verify_project_id so that it doesn't
        # generate an EndpointNotFound exception and result in a
        # server error.
        self.stub_out('nova.api.openstack.identity.verify_project_id',
                      lambda ctx, project_id: True)

        self.old_req = fakes.HTTPRequest.blank('', version='2.1')
        self.filtered_quotas = ['fixed_ips', 'floating_ips',
            'security_group_rules', 'security_groups']
        self.quotas = {
            'cores': {'limit': 20},
            'fixed_ips': {'limit': -1},
            'floating_ips': {'limit': -1},
            'injected_file_content_bytes': {'limit': 10240},
            'injected_file_path_bytes': {'limit': 255},
            'injected_files': {'limit': 5},
            'instances': {'limit': 10},
            'key_pairs': {'limit': 100},
            'metadata_items': {'limit': 128},
            'ram': {'limit': 51200},
            'security_group_rules': {'limit': -1},
            'security_groups': {'limit': -1},
            'server_group_members': {'limit': 10},
            'server_groups': {'limit': 10}
        }
        self.defaults = {
            'cores': 20,
            'fixed_ips': -1,
            'floating_ips': -1,
            'injected_file_content_bytes': 10240,
            'injected_file_path_bytes': 255,
            'injected_files': 5,
            'instances': 10,
            'key_pairs': 100,
            'metadata_items': 128,
            'ram': 51200,
            'security_group_rules': -1,
            'security_groups': -1,
            'server_group_members': 10,
            'server_groups': 10
        }
        self.controller = quotas_v21.QuotaSetsController()
        self.req = fakes.HTTPRequest.blank('', version=self.microversion)

    def _ensure_filtered_quotas_existed_in_old_api(self):
        res_dict = self.controller.show(self.old_req, 1234)
        for filtered in self.filtered_quotas:
            self.assertIn(filtered, res_dict['quota_set'])

    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_quotas_show_filtered(self, mock_quotas):
        mock_quotas.return_value = self.quotas
        self._ensure_filtered_quotas_existed_in_old_api()
        res_dict = self.controller.show(self.req, 1234)
        for filtered in self.filtered_quotas:
            self.assertNotIn(filtered, res_dict['quota_set'])

    @mock.patch('nova.quota.QUOTAS.get_defaults')
    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_quotas_default_filtered(self, mock_quotas, mock_defaults):
        mock_quotas.return_value = self.quotas
        self._ensure_filtered_quotas_existed_in_old_api()
        res_dict = self.controller.defaults(self.req, 1234)
        for filtered in self.filtered_quotas:
            self.assertNotIn(filtered, res_dict['quota_set'])

    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_quotas_detail_filtered(self, mock_quotas):
        mock_quotas.return_value = self.quotas
        self._ensure_filtered_quotas_existed_in_old_api()
        res_dict = self.controller.detail(self.req, 1234)
        for filtered in self.filtered_quotas:
            self.assertNotIn(filtered, res_dict['quota_set'])

    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_quotas_update_input_filtered(self, mock_quotas):
        mock_quotas.return_value = self.quotas
        self._ensure_filtered_quotas_existed_in_old_api()
        for filtered in self.filtered_quotas:
            self.assertRaises(exception.ValidationError,
                self.controller.update, self.req, 1234,
                body={'quota_set': {filtered: 100}})

    @mock.patch('nova.objects.Quotas.create_limit')
    @mock.patch('nova.quota.QUOTAS.get_settable_quotas')
    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_quotas_update_output_filtered(self, mock_quotas, mock_settable,
                                           mock_create_limit):
        mock_quotas.return_value = self.quotas
        mock_settable.return_value = {'cores': {'maximum': -1, 'minimum': 0}}
        self._ensure_filtered_quotas_existed_in_old_api()
        res_dict = self.controller.update(self.req, 1234,
             body={'quota_set': {'cores': 100}})
        for filtered in self.filtered_quotas:
            self.assertNotIn(filtered, res_dict['quota_set'])


class QuotaSetsTestV257(QuotaSetsTestV236):
    microversion = '2.57'

    def setUp(self):
        super(QuotaSetsTestV257, self).setUp()
        self.filtered_quotas.extend(quotas_v21.FILTERED_QUOTAS_2_57)


class QuotaSetsTestV275(QuotaSetsTestV257):
    microversion = '2.75'

    @mock.patch('nova.objects.Quotas.destroy_all_by_project')
    @mock.patch('nova.objects.Quotas.create_limit')
    @mock.patch('nova.quota.QUOTAS.get_settable_quotas')
    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_quota_additional_filter_older_version(self, mock_quotas,
                                                   mock_settable,
                                                   mock_create_limit,
                                                   mock_destroy):
        mock_quotas.return_value = self.quotas
        mock_settable.return_value = {'cores': {'maximum': -1, 'minimum': 0}}
        query_string = 'additional_filter=2'
        req = fakes.HTTPRequest.blank('', version='2.74',
                                      query_string=query_string)
        self.controller.show(req, 1234)
        self.controller.update(req, 1234, body={'quota_set': {}})
        self.controller.detail(req, 1234)
        self.controller.delete(req, 1234)

    def test_quota_update_additional_filter(self):
        query_string = 'user_id=1&additional_filter=2'
        req = fakes.HTTPRequest.blank('', version=self.microversion,
                                      query_string=query_string)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, 'update_me', body={'quota_set': {}})

    def test_quota_show_additional_filter(self):
        query_string = 'user_id=1&additional_filter=2'
        req = fakes.HTTPRequest.blank('', version=self.microversion,
                                      query_string=query_string)
        self.assertRaises(exception.ValidationError, self.controller.show,
                          req, 1234)

    def test_quota_detail_additional_filter(self):
        query_string = 'user_id=1&additional_filter=2'
        req = fakes.HTTPRequest.blank('', version=self.microversion,
                                      query_string=query_string)
        self.assertRaises(exception.ValidationError, self.controller.detail,
                          req, 1234)

    def test_quota_delete_additional_filter(self):
        query_string = 'user_id=1&additional_filter=2'
        req = fakes.HTTPRequest.blank('', version=self.microversion,
                                      query_string=query_string)
        self.assertRaises(exception.ValidationError, self.controller.delete,
                          req, 1234)


class NoopQuotaSetsTest(test.NoDBTestCase):
    quota_driver = "nova.quota.NoopQuotaDriver"
    expected_detail = {'in_use': -1, 'limit': -1, 'reserved': -1}

    def setUp(self):
        super(NoopQuotaSetsTest, self).setUp()
        self.flags(driver=self.quota_driver, group="quota")
        self.controller = quotas_v21.QuotaSetsController()
        self.stub_out('nova.api.openstack.identity.verify_project_id',
                      lambda ctx, project_id: True)

    def test_show_v21(self):
        req = fakes.HTTPRequest.blank("")
        response = self.controller.show(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': -1,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': -1,
                'injected_file_path_bytes': -1,
                'injected_files': -1,
                'instances': -1,
                'key_pairs': -1,
                'metadata_items': -1,
                'ram': -1,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': -1,
                'server_groups': -1,
            }
        }
        self.assertEqual(expected_response, response)

    def test_show_v257(self):
        req = fakes.HTTPRequest.blank("", version='2.57')
        response = self.controller.show(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': -1,
                'instances': -1,
                'key_pairs': -1,
                'metadata_items': -1,
                'ram': -1,
                'server_group_members': -1,
                'server_groups': -1}}
        self.assertEqual(expected_response, response)

    def test_detail_v21(self):
        req = fakes.HTTPRequest.blank("")
        response = self.controller.detail(req, uuids.project_id)

        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': self.expected_detail,
                'fixed_ips': self.expected_detail,
                'floating_ips': self.expected_detail,
                'injected_file_content_bytes': self.expected_detail,
                'injected_file_path_bytes': self.expected_detail,
                'injected_files': self.expected_detail,
                'instances': self.expected_detail,
                'key_pairs': self.expected_detail,
                'metadata_items': self.expected_detail,
                'ram': self.expected_detail,
                'security_group_rules': self.expected_detail,
                'security_groups': self.expected_detail,
                'server_group_members': self.expected_detail,
                'server_groups': self.expected_detail,
            }
        }
        self.assertEqual(expected_response, response)

    def test_detail_v21_user(self):
        req = fakes.HTTPRequest.blank("?user_id=42")
        response = self.controller.detail(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': self.expected_detail,
                'fixed_ips': self.expected_detail,
                'floating_ips': self.expected_detail,
                'injected_file_content_bytes': self.expected_detail,
                'injected_file_path_bytes': self.expected_detail,
                'injected_files': self.expected_detail,
                'instances': self.expected_detail,
                'key_pairs': self.expected_detail,
                'metadata_items': self.expected_detail,
                'ram': self.expected_detail,
                'security_group_rules': self.expected_detail,
                'security_groups': self.expected_detail,
                'server_group_members': self.expected_detail,
                'server_groups': self.expected_detail,
            }
        }
        self.assertEqual(expected_response, response)

    def test_update_still_rejects_badrequests(self):
        req = fakes.HTTPRequest.blank("")
        body = {'quota_set': {'instances': 50, 'cores': 50,
                              'ram': 51200, 'unsupported': 12}}
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, uuids.project_id, body=body)

    @mock.patch.object(objects.Quotas, "create_limit")
    def test_update_v21(self, mock_create):
        req = fakes.HTTPRequest.blank("")
        body = {'quota_set': {'server_groups': 2}}
        response = self.controller.update(req, uuids.project_id, body=body)
        expected_response = {
            'quota_set': {
                'cores': -1,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': -1,
                'injected_file_path_bytes': -1,
                'injected_files': -1,
                'instances': -1,
                'key_pairs': -1,
                'metadata_items': -1,
                'ram': -1,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': -1,
                'server_groups': -1,
            }
        }
        self.assertEqual(expected_response, response)
        mock_create.assert_called_once_with(req.environ['nova.context'],
                                            uuids.project_id, "server_groups",
                                            2, user_id=None)

    @mock.patch.object(objects.Quotas, "create_limit")
    def test_update_v21_user(self, mock_create):
        req = fakes.HTTPRequest.blank("?user_id=42")
        body = {'quota_set': {'key_pairs': 52}}
        response = self.controller.update(req, uuids.project_id, body=body)
        expected_response = {
            'quota_set': {
                'cores': -1,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': -1,
                'injected_file_path_bytes': -1,
                'injected_files': -1,
                'instances': -1,
                'key_pairs': -1,
                'metadata_items': -1,
                'ram': -1,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': -1,
                'server_groups': -1,
            }
        }
        self.assertEqual(expected_response, response)
        mock_create.assert_called_once_with(req.environ['nova.context'],
                                            uuids.project_id, "key_pairs", 52,
                                            user_id="42")

    def test_defaults_v21(self):
        req = fakes.HTTPRequest.blank("")
        response = self.controller.defaults(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': -1,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': -1,
                'injected_file_path_bytes': -1,
                'injected_files': -1,
                'instances': -1,
                'key_pairs': -1,
                'metadata_items': -1,
                'ram': -1,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': -1,
                'server_groups': -1,
            }
        }
        self.assertEqual(expected_response, response)

    @mock.patch('nova.objects.Quotas.destroy_all_by_project')
    def test_quotas_delete(self, mock_destroy_all_by_project):
        req = fakes.HTTPRequest.blank("")
        self.controller.delete(req, "1234")
        mock_destroy_all_by_project.assert_called_once_with(
            req.environ['nova.context'], "1234")

    @mock.patch('nova.objects.Quotas.destroy_all_by_project_and_user')
    def test_user_quotas_delete(self, mock_destroy_all_by_user):
        req = fakes.HTTPRequest.blank("?user_id=42")
        self.controller.delete(req, "1234")
        mock_destroy_all_by_user.assert_called_once_with(
            req.environ['nova.context'], "1234", "42")


class UnifiedLimitsQuotaSetsTest(NoopQuotaSetsTest):
    quota_driver = "nova.quota.UnifiedLimitsDriver"
    # this matches what the db driver returns
    expected_detail = {'in_use': 0, 'limit': -1, 'reserved': 0}

    def setUp(self):
        super(UnifiedLimitsQuotaSetsTest, self).setUp()
        reglimits = {local_limit.SERVER_METADATA_ITEMS: 128,
                     local_limit.INJECTED_FILES: 5,
                     local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
                     local_limit.INJECTED_FILES_PATH: 255,
                     local_limit.KEY_PAIRS: 100,
                     local_limit.SERVER_GROUPS: 12,
                     local_limit.SERVER_GROUP_MEMBERS: 10}
        self.limit_fixture = self.useFixture(
            limit_fixture.LimitFixture(reglimits, {}))

    @mock.patch.object(placement_limit, "get_legacy_project_limits")
    def test_show_v21(self, mock_proj):
        mock_proj.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("")
        response = self.controller.show(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': 2,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': 10240,
                'injected_file_path_bytes': 255,
                'injected_files': 5,
                'instances': 1,
                'key_pairs': 100,
                'metadata_items': 128,
                'ram': 3,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': 10,
                'server_groups': 12,
            }
        }
        self.assertEqual(expected_response, response)

    @mock.patch.object(placement_limit, "get_legacy_project_limits")
    def test_show_v257(self, mock_proj):
        mock_proj.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("", version='2.57')
        response = self.controller.show(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': 2,
                'instances': 1,
                'key_pairs': 100,
                'metadata_items': 128,
                'ram': 3,
                'server_group_members': 10,
                'server_groups': 12}}
        self.assertEqual(expected_response, response)

    @mock.patch.object(placement_limit, "get_legacy_counts")
    @mock.patch.object(placement_limit, "get_legacy_project_limits")
    @mock.patch.object(objects.InstanceGroupList, "get_counts")
    def test_detail_v21(self, mock_count, mock_proj, mock_kcount):
        mock_proj.return_value = {"instances": 1, "cores": 2, "ram": 3}
        mock_kcount.return_value = {"instances": 4, "cores": 5, "ram": 6}
        mock_count.return_value = {'project': {'server_groups': 9}}
        req = fakes.HTTPRequest.blank("")
        response = self.controller.detail(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': {
                    'in_use': 5, 'limit': 2, 'reserved': 0},
                'fixed_ips': self.expected_detail,
                'floating_ips': self.expected_detail,
                'injected_file_content_bytes': {
                    'in_use': 0, 'limit': 10240, 'reserved': 0},
                'injected_file_path_bytes': {
                    'in_use': 0, 'limit': 255, 'reserved': 0},
                'injected_files': {
                    'in_use': 0, 'limit': 5, 'reserved': 0},
                'instances': {
                    'in_use': 4, 'limit': 1, 'reserved': 0},
                'key_pairs': {
                    'in_use': 0, 'limit': 100, 'reserved': 0},
                'metadata_items': {
                    'in_use': 0, 'limit': 128, 'reserved': 0},
                'ram': {
                    'in_use': 6, 'limit': 3, 'reserved': 0},
                'security_group_rules': self.expected_detail,
                'security_groups': self.expected_detail,
                'server_group_members': {
                    'in_use': 0, 'limit': 10, 'reserved': 0},
                'server_groups': {
                    'in_use': 9, 'limit': 12, 'reserved': 0},
            }
        }
        self.assertEqual(expected_response, response)

    @mock.patch.object(placement_limit, "get_legacy_counts")
    @mock.patch.object(placement_limit, "get_legacy_project_limits")
    @mock.patch.object(objects.InstanceGroupList, "get_counts")
    def test_detail_v21_user(self, mock_count, mock_proj, mock_kcount):
        mock_proj.return_value = {"instances": 1, "cores": 2, "ram": 3}
        mock_kcount.return_value = {"instances": 4, "cores": 5, "ram": 6}
        mock_count.return_value = {'project': {'server_groups': 9}}
        req = fakes.HTTPRequest.blank("?user_id=42")
        response = self.controller.detail(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': {
                    'in_use': 5, 'limit': 2, 'reserved': 0},
                'fixed_ips': self.expected_detail,
                'floating_ips': self.expected_detail,
                'injected_file_content_bytes': {
                    'in_use': 0, 'limit': 10240, 'reserved': 0},
                'injected_file_path_bytes': {
                    'in_use': 0, 'limit': 255, 'reserved': 0},
                'injected_files': {
                    'in_use': 0, 'limit': 5, 'reserved': 0},
                'instances': {
                    'in_use': 4, 'limit': 1, 'reserved': 0},
                'key_pairs': {
                    'in_use': 0, 'limit': 100, 'reserved': 0},
                'metadata_items': {
                    'in_use': 0, 'limit': 128, 'reserved': 0},
                'ram': {
                    'in_use': 6, 'limit': 3, 'reserved': 0},
                'security_group_rules': self.expected_detail,
                'security_groups': self.expected_detail,
                'server_group_members': {
                    'in_use': 0, 'limit': 10, 'reserved': 0},
                'server_groups': {
                    'in_use': 9, 'limit': 12, 'reserved': 0},
            }
        }
        self.assertEqual(expected_response, response)

    @mock.patch.object(placement_limit, "get_legacy_project_limits")
    @mock.patch.object(objects.Quotas, "create_limit")
    def test_update_v21(self, mock_create, mock_proj):
        mock_proj.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("")
        # TODO(johngarbutt) still need to implement get_settable_quotas
        body = {'quota_set': {'server_groups': 2}}
        response = self.controller.update(req, uuids.project_id, body=body)
        expected_response = {
            'quota_set': {
                'cores': 2,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': 10240,
                'injected_file_path_bytes': 255,
                'injected_files': 5,
                'instances': 1,
                'key_pairs': 100,
                'metadata_items': 128,
                'ram': 3,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': 10,
                'server_groups': 12,
            }
        }
        self.assertEqual(expected_response, response)
        self.assertEqual(0, mock_create.call_count)

    @mock.patch.object(placement_limit, "get_legacy_project_limits")
    @mock.patch.object(objects.Quotas, "create_limit")
    def test_update_v21_user(self, mock_create, mock_proj):
        mock_proj.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("?user_id=42")
        body = {'quota_set': {'key_pairs': 52}}
        response = self.controller.update(req, uuids.project_id, body=body)
        expected_response = {
            'quota_set': {
                'cores': 2,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': 10240,
                'injected_file_path_bytes': 255,
                'injected_files': 5,
                'instances': 1,
                'key_pairs': 100,
                'metadata_items': 128,
                'ram': 3,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': 10,
                'server_groups': 12,
            }
        }
        self.assertEqual(expected_response, response)
        self.assertEqual(0, mock_create.call_count)

    @mock.patch.object(placement_limit, "get_legacy_default_limits")
    def test_defaults_v21(self, mock_default):
        mock_default.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("")
        response = self.controller.defaults(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': 2,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': 10240,
                'injected_file_path_bytes': 255,
                'injected_files': 5,
                'instances': 1,
                'key_pairs': 100,
                'metadata_items': 128,
                'ram': 3,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': 10,
                'server_groups': 12,
            }
        }
        self.assertEqual(expected_response, response)

    def test_defaults_v21_different_limit_values(self):
        reglimits = {local_limit.SERVER_METADATA_ITEMS: 7,
                     local_limit.INJECTED_FILES: 6,
                     local_limit.INJECTED_FILES_CONTENT: 4,
                     local_limit.INJECTED_FILES_PATH: 5,
                     local_limit.KEY_PAIRS: 1,
                     local_limit.SERVER_GROUPS: 3,
                     local_limit.SERVER_GROUP_MEMBERS: 2}
        self.limit_fixture.reglimits = reglimits

        req = fakes.HTTPRequest.blank("")
        response = self.controller.defaults(req, uuids.project_id)
        expected_response = {
            'quota_set': {
                'id': uuids.project_id,
                'cores': 0,
                'fixed_ips': -1,
                'floating_ips': -1,
                'injected_file_content_bytes': 4,
                'injected_file_path_bytes': 5,
                'injected_files': 6,
                'instances': 0,
                'key_pairs': 1,
                'metadata_items': 7,
                'ram': 0,
                'security_group_rules': -1,
                'security_groups': -1,
                'server_group_members': 2,
                'server_groups': 3,
            }
        }
        self.assertEqual(expected_response, response)

    @mock.patch('nova.objects.Quotas.destroy_all_by_project')
    def test_quotas_delete(self, mock_destroy_all_by_project):
        req = fakes.HTTPRequest.blank("")
        self.controller.delete(req, "1234")
        # Ensure destroy isn't called for unified limits
        self.assertEqual(0, mock_destroy_all_by_project.call_count)

    @mock.patch('nova.objects.Quotas.destroy_all_by_project_and_user')
    def test_user_quotas_delete(self, mock_destroy_all_by_user):
        req = fakes.HTTPRequest.blank("?user_id=42")
        self.controller.delete(req, "1234")
        # Ensure destroy isn't called for unified limits
        self.assertEqual(0, mock_destroy_all_by_user.call_count)
