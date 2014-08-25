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

import copy

from lxml import etree
import webob

from nova.api.openstack.compute.contrib import quotas as quotas_v2
from nova.api.openstack.compute.plugins.v3 import quota_sets as quotas_v21
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import context as context_maker
from nova import exception
from nova import quota
from nova import test
from nova.tests.api.openstack import fakes


def quota_set(id):
    return {'quota_set': {'id': id, 'metadata_items': 128,
            'ram': 51200, 'floating_ips': 10, 'fixed_ips': -1,
            'instances': 10, 'injected_files': 5, 'cores': 20,
            'injected_file_content_bytes': 10240,
            'security_groups': 10, 'security_group_rules': 20,
            'key_pairs': 100, 'injected_file_path_bytes': 255}}


class BaseQuotaSetsTest(test.TestCase):

    def is_v20_api_test(self):
        # NOTE(oomichi): If a test is for v2.0 API, this method returns
        # True. Otherwise(v2.1 API test), returns False.
        return (self.plugin == quotas_v2)

    def get_update_expected_response(self, base_body):
        # NOTE(oomichi): "id" parameter is added to a response of
        # "update quota" API since v2.1 API, because it makes the
        # API consistent and it is not backwards incompatible change.
        # This method adds "id" for an expected body of a response.
        if self.is_v20_api_test():
            expected_body = base_body
        else:
            expected_body = copy.deepcopy(base_body)
            expected_body['quota_set'].update({'id': 'update_me'})
        return expected_body

    def setup_mock_for_show(self):
        if self.is_v20_api_test():
            self.ext_mgr.is_loaded('os-user-quotas').AndReturn(True)
            self.mox.ReplayAll()

    def setup_mock_for_update(self):
        if self.is_v20_api_test():
            self.ext_mgr.is_loaded('os-extended-quotas').AndReturn(True)
            self.ext_mgr.is_loaded('os-user-quotas').AndReturn(True)
            self.mox.ReplayAll()

    def get_delete_status_int(self, res):
        if self.is_v20_api_test():
            return res.status_int
        else:
            # NOTE: on v2.1, http status code is set as wsgi_code of API
            # method instead of status_int in a response object.
            return self.controller.delete.wsgi_code


class QuotaSetsTestV21(BaseQuotaSetsTest):
    plugin = quotas_v21
    validation_error = exception.ValidationError

    def setUp(self):
        super(QuotaSetsTestV21, self).setUp()
        self.ext_mgr = self.mox.CreateMock(extensions.ExtensionManager)
        self.controller = self.plugin.QuotaSetsController(self.ext_mgr)
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
            'key_pairs': 100
        }

    def test_format_quota_set(self):
        quota_set = self.controller._format_quota_set('1234',
                                                      self.default_quotas)
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

    def test_quotas_defaults(self):
        uri = '/v2/fake_tenant/os-quota-sets/fake_tenant/defaults'

        req = fakes.HTTPRequest.blank(uri)
        res_dict = self.controller.defaults(req, 'fake_tenant')
        self.default_quotas.update({'id': 'fake_tenant'})
        expected = {'quota_set': self.default_quotas}

        self.assertEqual(res_dict, expected)

    def test_quotas_show_as_admin(self):
        self.setup_mock_for_show()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234',
                                      use_admin_context=True)
        res_dict = self.controller.show(req, 1234)

        self.assertEqual(res_dict, quota_set('1234'))

    def test_quotas_show_as_unauthorized_user(self):
        self.setup_mock_for_show()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          req, 1234)

    def test_quotas_update_as_admin(self):
        self.setup_mock_for_update()
        self.default_quotas.update({
            'instances': 50,
            'cores': 50
        })
        body = {'quota_set': self.default_quotas}
        expected_body = self.get_update_expected_response(body)

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        res_dict = self.controller.update(req, 'update_me', body=body)
        self.assertEqual(expected_body, res_dict)

    def test_quotas_update_zero_value_as_admin(self):
        self.setup_mock_for_update()
        body = {'quota_set': {'instances': 0, 'cores': 0,
                              'ram': 0, 'floating_ips': 0,
                              'metadata_items': 0,
                              'injected_files': 0,
                              'injected_file_content_bytes': 0,
                              'injected_file_path_bytes': 0,
                              'security_groups': 0,
                              'security_group_rules': 0,
                              'key_pairs': 100, 'fixed_ips': -1}}
        expected_body = self.get_update_expected_response(body)

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        res_dict = self.controller.update(req, 'update_me', body=body)
        self.assertEqual(expected_body, res_dict)

    def test_quotas_update_as_user(self):
        self.setup_mock_for_update()
        self.default_quotas.update({
            'instances': 50,
            'cores': 50
        })
        body = {'quota_set': self.default_quotas}

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          req, 'update_me', body=body)

    def _quotas_update_bad_request_case(self, body):
        self.setup_mock_for_update()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
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

    def test_quotas_delete_as_unauthorized_user(self):
        if self.is_v20_api_test():
            self.ext_mgr.is_loaded('os-extended-quotas').AndReturn(True)
            self.mox.ReplayAll()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          req, 1234)

    def test_quotas_delete_as_admin(self):
        if self.is_v20_api_test():
            self.ext_mgr.is_loaded('os-extended-quotas').AndReturn(True)
        context = context_maker.get_admin_context()
        self.req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234')
        self.req.environ['nova.context'] = context
        self.mox.StubOutWithMock(quota.QUOTAS,
                                 "destroy_all_by_project")
        quota.QUOTAS.destroy_all_by_project(context, 1234)
        self.mox.ReplayAll()
        res = self.controller.delete(self.req, 1234)
        self.mox.VerifyAll()
        self.assertEqual(202, self.get_delete_status_int(res))


class QuotaXMLSerializerTest(test.TestCase):
    def setUp(self):
        super(QuotaXMLSerializerTest, self).setUp()
        self.serializer = quotas_v2.QuotaTemplate()
        self.deserializer = wsgi.XMLDeserializer()

    def test_serializer(self):
        exemplar = dict(quota_set=dict(
                id='project_id',
                metadata_items=10,
                injected_file_path_bytes=255,
                injected_file_content_bytes=20,
                ram=50,
                floating_ips=60,
                fixed_ips=-1,
                instances=70,
                injected_files=80,
                security_groups=10,
                security_group_rules=20,
                key_pairs=100,
                cores=90))
        text = self.serializer.serialize(exemplar)

        tree = etree.fromstring(text)

        self.assertEqual('quota_set', tree.tag)
        self.assertEqual('project_id', tree.get('id'))
        self.assertEqual(len(exemplar['quota_set']) - 1, len(tree))
        for child in tree:
            self.assertIn(child.tag, exemplar['quota_set'])
            self.assertEqual(int(child.text), exemplar['quota_set'][child.tag])

    def test_deserializer(self):
        exemplar = dict(quota_set=dict(
                metadata_items='10',
                injected_file_content_bytes='20',
                ram='50',
                floating_ips='60',
                fixed_ips='-1',
                instances='70',
                injected_files='80',
                security_groups='10',
                security_group_rules='20',
                key_pairs='100',
                cores='90'))
        intext = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                  '<quota_set>'
                  '<metadata_items>10</metadata_items>'
                  '<injected_file_content_bytes>20'
                  '</injected_file_content_bytes>'
                  '<ram>50</ram>'
                  '<floating_ips>60</floating_ips>'
                  '<fixed_ips>-1</fixed_ips>'
                  '<instances>70</instances>'
                  '<injected_files>80</injected_files>'
                  '<security_groups>10</security_groups>'
                  '<security_group_rules>20</security_group_rules>'
                  '<key_pairs>100</key_pairs>'
                  '<cores>90</cores>'
                  '</quota_set>')

        result = self.deserializer.deserialize(intext)['body']
        self.assertEqual(result, exemplar)


class ExtendedQuotasTestV21(BaseQuotaSetsTest):
    plugin = quotas_v21

    def setUp(self):
        super(ExtendedQuotasTestV21, self).setUp()
        self.ext_mgr = self.mox.CreateMock(extensions.ExtensionManager)
        self.controller = self.plugin.QuotaSetsController(self.ext_mgr)
        self.setup_mock_for_update()

    fake_quotas = {'ram': {'limit': 51200,
                           'in_use': 12800,
                           'reserved': 12800},
                   'cores': {'limit': 20,
                             'in_use': 10,
                             'reserved': 5},
                   'instances': {'limit': 100,
                                 'in_use': 0,
                                 'reserved': 0}}

    def fake_get_quotas(self, context, id, user_id=None, usages=False):
        if usages:
            return self.fake_quotas
        else:
            return dict((k, v['limit']) for k, v in self.fake_quotas.items())

    def test_quotas_update_exceed_in_used(self):

        body = {'quota_set': {'cores': 10}}

        self.stubs.Set(self.plugin.QuotaSetsController, '_get_quotas',
                       self.fake_get_quotas)
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)

    def test_quotas_force_update_exceed_in_used(self):
        self.stubs.Set(self.plugin.QuotaSetsController, '_get_quotas',
                       self.fake_get_quotas)
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)

        expected = {'quota_set': {'ram': 25600, 'instances': 200, 'cores': 10}}
        expected = self.get_update_expected_response(expected)

        body = {'quota_set': {'ram': 25600,
                              'instances': 200,
                              'cores': 10,
                              'force': 'True'}}
        self.fake_quotas.get('ram')['limit'] = 25600
        self.fake_quotas.get('cores')['limit'] = 10
        self.fake_quotas.get('instances')['limit'] = 200

        res_dict = self.controller.update(req, 'update_me', body=body)
        self.assertEqual(expected, res_dict)


class UserQuotasTestV21(BaseQuotaSetsTest):
    plugin = quotas_v21

    def setUp(self):
        super(UserQuotasTestV21, self).setUp()
        self.ext_mgr = self.mox.CreateMock(extensions.ExtensionManager)
        self.controller = self.plugin.QuotaSetsController(self.ext_mgr)

    def test_user_quotas_show_as_admin(self):
        self.setup_mock_for_show()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234?user_id=1',
                                      use_admin_context=True)
        res_dict = self.controller.show(req, 1234)

        self.assertEqual(res_dict, quota_set('1234'))

    def test_user_quotas_show_as_unauthorized_user(self):
        self.setup_mock_for_show()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234?user_id=1')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          req, 1234)

    def test_user_quotas_update_as_admin(self):
        self.setup_mock_for_update()
        body = {'quota_set': {'instances': 10, 'cores': 20,
                              'ram': 51200, 'floating_ips': 10,
                              'fixed_ips': -1, 'metadata_items': 128,
                              'injected_files': 5,
                              'injected_file_content_bytes': 10240,
                              'injected_file_path_bytes': 255,
                              'security_groups': 10,
                              'security_group_rules': 20,
                              'key_pairs': 100}}
        expected_body = self.get_update_expected_response(body)

        url = '/v2/fake4/os-quota-sets/update_me?user_id=1'
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res_dict = self.controller.update(req, 'update_me', body=body)

        self.assertEqual(expected_body, res_dict)

    def test_user_quotas_update_as_user(self):
        self.setup_mock_for_update()
        body = {'quota_set': {'instances': 10, 'cores': 20,
                              'ram': 51200, 'floating_ips': 10,
                              'fixed_ips': -1, 'metadata_items': 128,
                              'injected_files': 5,
                              'injected_file_content_bytes': 10240,
                              'security_groups': 10,
                              'security_group_rules': 20,
                              'key_pairs': 100}}

        url = '/v2/fake4/os-quota-sets/update_me?user_id=1'
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          req, 'update_me', body=body)

    def test_user_quotas_update_exceed_project(self):
        self.setup_mock_for_update()
        body = {'quota_set': {'instances': 20}}

        url = '/v2/fake4/os-quota-sets/update_me?user_id=1'
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body=body)

    def test_user_quotas_delete_as_unauthorized_user(self):
        self.setup_mock_for_update()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234?user_id=1')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          req, 1234)

    def test_user_quotas_delete_as_admin(self):
        if self.is_v20_api_test():
            self.ext_mgr.is_loaded('os-extended-quotas').AndReturn(True)
            self.ext_mgr.is_loaded('os-user-quotas').AndReturn(True)
        context = context_maker.get_admin_context()
        url = '/v2/fake4/os-quota-sets/1234?user_id=1'
        self.req = fakes.HTTPRequest.blank(url)
        self.req.environ['nova.context'] = context
        self.mox.StubOutWithMock(quota.QUOTAS,
                                 "destroy_all_by_project_and_user")
        quota.QUOTAS.destroy_all_by_project_and_user(context, 1234, '1')
        self.mox.ReplayAll()
        res = self.controller.delete(self.req, 1234)
        self.mox.VerifyAll()
        self.assertEqual(202, self.get_delete_status_int(res))


class QuotaSetsTestV2(QuotaSetsTestV21):
    plugin = quotas_v2
    validation_error = webob.exc.HTTPBadRequest

    # NOTE: The following tests are tricky and v2.1 API does not allow
    # this kind of input by strong input validation. Just for test coverage,
    # we keep them now.
    def test_quotas_update_invalid_value_json_fromat_empty_string(self):
        self.setup_mock_for_update()
        self.default_quotas.update({
            'instances': 50,
            'cores': 50
        })
        expected_resp = {'quota_set': self.default_quotas}

        # when PUT JSON format with empty string for quota
        body = copy.deepcopy(expected_resp)
        body['quota_set']['ram'] = ''
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        res_dict = self.controller.update(req, 'update_me', body)
        self.assertEqual(res_dict, expected_resp)

    def test_quotas_update_invalid_value_xml_fromat_empty_string(self):
        self.default_quotas.update({
            'instances': 50,
            'cores': 50
        })
        expected_resp = {'quota_set': self.default_quotas}

        # when PUT XML format with empty string for quota
        body = copy.deepcopy(expected_resp)
        body['quota_set']['ram'] = {}
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        self.setup_mock_for_update()
        res_dict = self.controller.update(req, 'update_me', body)
        self.assertEqual(res_dict, expected_resp)

    # NOTE: os-extended-quotas and os-user-quotas are only for v2.0.
    # On v2.1, these features are always enable. So we need the following
    # tests only for v2.0.
    def test_delete_quotas_when_extension_not_loaded(self):
        self.ext_mgr.is_loaded('os-extended-quotas').AndReturn(False)
        self.mox.ReplayAll()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1234)

    def test_delete_user_quotas_when_extension_not_loaded(self):
        self.ext_mgr.is_loaded('os-extended-quotas').AndReturn(True)
        self.ext_mgr.is_loaded('os-user-quotas').AndReturn(False)
        self.mox.ReplayAll()
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234?user_id=1')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1234)


class ExtendedQuotasTestV2(ExtendedQuotasTestV21):
    plugin = quotas_v2


class UserQuotasTestV2(UserQuotasTestV21):
    plugin = quotas_v2
