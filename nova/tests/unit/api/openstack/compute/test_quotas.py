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

import mock
import webob

from nova.api.openstack.compute import quota_sets as quotas_v21
from nova import db
from nova import exception
from nova import quota
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.api.openstack import fakes


def quota_set(id, include_server_group_quotas=True):
    res = {'quota_set': {'id': id, 'metadata_items': 128,
           'ram': 51200, 'floating_ips': 10, 'fixed_ips': -1,
           'instances': 10, 'injected_files': 5, 'cores': 20,
           'injected_file_content_bytes': 10240,
           'security_groups': 10, 'security_group_rules': 20,
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

    def get_delete_status_int(self, res):
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        return self.controller.delete.wsgi_code


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
            'floating_ips': 10,
            'fixed_ips': -1,
            'metadata_items': 128,
            'injected_files': 5,
            'injected_file_path_bytes': 255,
            'injected_file_content_bytes': 10240,
            'security_groups': 10,
            'security_group_rules': 20,
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
        self.assertEqual(qs['floating_ips'], 10)
        self.assertEqual(qs['fixed_ips'], -1)
        self.assertEqual(qs['metadata_items'], 128)
        self.assertEqual(qs['injected_files'], 5)
        self.assertEqual(qs['injected_file_path_bytes'], 255)
        self.assertEqual(qs['injected_file_content_bytes'], 10240)
        self.assertEqual(qs['security_groups'], 10)
        self.assertEqual(qs['security_group_rules'], 20)
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
                          resource, db.MAX_INT + 1, -1, -1)

    def test_quotas_defaults(self):
        uri = '/v2/fake_tenant/os-quota-sets/fake_tenant/defaults'

        req = fakes.HTTPRequest.blank(uri)
        res_dict = self.controller.defaults(req, 'fake_tenant')
        self.default_quotas.update({'id': 'fake_tenant'})
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
                              'ram': 0, 'floating_ips': 0,
                              'metadata_items': 0,
                              'injected_files': 0,
                              'injected_file_content_bytes': 0,
                              'injected_file_path_bytes': 0,
                              'security_groups': 0,
                              'security_group_rules': 0,
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

    @mock.patch.object(quota.QUOTAS, 'destroy_all_by_project')
    def test_quotas_delete(self, mock_destroy_all_by_project):
        req = self._get_http_request()
        res = self.controller.delete(req, 1234)
        self.assertEqual(202, self.get_delete_status_int(res))
        mock_destroy_all_by_project.assert_called_once_with(
            req.environ['nova.context'], 1234)

    def test_update_network_quota_disabled(self):
        self.flags(enable_network_quota=False)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self._get_http_request(),
                          1234, body={'quota_set': {'networks': 1}})

    def test_update_network_quota_enabled(self):
        self.flags(enable_network_quota=True)
        self.useFixture(nova_fixtures.RegisterNetworkQuota())
        self.controller.update(self._get_http_request(),
                               1234, body={'quota_set': {'networks': 1}})

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
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
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
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
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
        req = self._get_http_request('/v2/fake4/os-quota-sets/1234?user_id=1')
        res_dict = self.controller.show(req, 1234)
        ref_quota_set = quota_set('1234', self.include_server_group_quotas)
        self.assertEqual(res_dict, ref_quota_set)

    def test_user_quotas_update(self):
        body = {'quota_set': {'instances': 10, 'cores': 20,
                              'ram': 51200, 'floating_ips': 10,
                              'fixed_ips': -1, 'metadata_items': 128,
                              'injected_files': 5,
                              'injected_file_content_bytes': 10240,
                              'injected_file_path_bytes': 255,
                              'security_groups': 10,
                              'security_group_rules': 20,
                              'key_pairs': 100}}
        if self.include_server_group_quotas:
            body['quota_set']['server_groups'] = 10
            body['quota_set']['server_group_members'] = 10

        url = '/v2/fake4/os-quota-sets/update_me?user_id=1'
        req = self._get_http_request(url)
        res_dict = self.controller.update(req, 'update_me', body=body)

        self.assertEqual(body, res_dict)

    def test_user_quotas_update_exceed_project(self):
        body = {'quota_set': {'instances': 20}}

        url = '/v2/fake4/os-quota-sets/update_me?user_id=1'
        req = self._get_http_request(url)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)

    @mock.patch.object(quota.QUOTAS, "destroy_all_by_project_and_user")
    def test_user_quotas_delete(self, mock_destroy_all_by_project_and_user):
        url = '/v2/fake4/os-quota-sets/1234?user_id=1'
        req = self._get_http_request(url)
        res = self.controller.delete(req, 1234)
        self.assertEqual(202, self.get_delete_status_int(res))
        mock_destroy_all_by_project_and_user.assert_called_once_with(
            req.environ['nova.context'], 1234, '1'
        )

    @mock.patch('nova.objects.Quotas.create_limit')
    def test_user_quotas_update_good_data(self, mock_createlimit):
        body = {'quota_set': {'instances': 1,
                              'cores': 1}}

        url = '/v2/fake4/os-quota-sets/update_me?user_id=1'
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        self.controller.update(req, 'update_me', body=body)
        self.assertEqual(2,
                         len(mock_createlimit.mock_calls))

    @mock.patch('nova.objects.Quotas.create_limit')
    def test_user_quotas_update_bad_data(self, mock_createlimit):
        body = {'quota_set': {'instances': 20,
                              'cores': 1}}

        url = '/v2/fake4/os-quota-sets/update_me?user_id=1'
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)
        self.assertEqual(0,
                         len(mock_createlimit.mock_calls))


class QuotaSetsPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(QuotaSetsPolicyEnforcementV21, self).setUp()
        self.controller = quotas_v21.QuotaSetsController()
        self.req = fakes.HTTPRequest.blank('')

    def test_delete_policy_failed(self):
        rule_name = "os_compute_api:os-quota-sets:delete"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_defaults_policy_failed(self):
        rule_name = "os_compute_api:os-quota-sets:defaults"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.defaults, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_show_policy_failed(self):
        rule_name = "os_compute_api:os-quota-sets:show"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_detail_policy_failed(self):
        rule_name = "os_compute_api:os-quota-sets:detail"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.detail, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_update_policy_failed(self):
        rule_name = "os_compute_api:os-quota-sets:update"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.update, self.req, fakes.FAKE_UUID,
            body={'quota_set': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class QuotaSetsTestV236(test.NoDBTestCase):
    microversion = '2.36'

    def setUp(self):
        super(QuotaSetsTestV236, self).setUp()
        # We need to stub out verify_project_id so that it doesn't
        # generate an EndpointNotFound exception and result in a
        # server error.
        self.stub_out('nova.api.openstack.identity.verify_project_id',
                      lambda ctx, project_id: True)

        self.flags(enable_network_quota=True)
        self.useFixture(nova_fixtures.RegisterNetworkQuota())
        self.old_req = fakes.HTTPRequest.blank('', version='2.1')
        self.filtered_quotas = ['fixed_ips', 'floating_ips', 'networks',
            'security_group_rules', 'security_groups']
        self.quotas = {
            'cores': {'limit': 20},
            'fixed_ips': {'limit': -1},
            'floating_ips': {'limit': 10},
            'injected_file_content_bytes': {'limit': 10240},
            'injected_file_path_bytes': {'limit': 255},
            'injected_files': {'limit': 5},
            'instances': {'limit': 10},
            'key_pairs': {'limit': 100},
            'metadata_items': {'limit': 128},
            'networks': {'limit': 3},
            'ram': {'limit': 51200},
            'security_group_rules': {'limit': 20},
            'security_groups': {'limit': 10},
            'server_group_members': {'limit': 10},
            'server_groups': {'limit': 10}
        }
        self.defaults = {
            'cores': 20,
            'fixed_ips': -1,
            'floating_ips': 10,
            'injected_file_content_bytes': 10240,
            'injected_file_path_bytes': 255,
            'injected_files': 5,
            'instances': 10,
            'key_pairs': 100,
            'metadata_items': 128,
            'networks': 3,
            'ram': 51200,
            'security_group_rules': 20,
            'security_groups': 10,
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
