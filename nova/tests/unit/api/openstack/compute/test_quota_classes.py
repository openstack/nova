# Copyright 2012 OpenStack Foundation
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
import webob

from nova.api.openstack.compute import extension_info
from nova.api.openstack.compute import quota_classes \
       as quota_classes_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


class QuotaClassSetsTestV21(test.TestCase):
    validation_error = exception.ValidationError
    api_version = '2.1'
    quota_resources = {'metadata_items': 128,
                       'ram': 51200, 'floating_ips': 10,
                       'fixed_ips': -1, 'instances': 10,
                       'injected_files': 5, 'cores': 20,
                       'injected_file_content_bytes': 10240,
                       'security_groups': 10,
                       'security_group_rules': 20, 'key_pairs': 100,
                       'injected_file_path_bytes': 255}

    def quota_set(self, class_name):
        quotas = copy.deepcopy(self.quota_resources)
        quotas['id'] = class_name
        return {'quota_class_set': quotas}

    def setUp(self):
        super(QuotaClassSetsTestV21, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version=self.api_version)
        self._setup()

    def _setup(self):
        ext_info = extension_info.LoadedExtensionInfo()
        self.controller = quota_classes_v21.QuotaClassSetsController(
            extension_info=ext_info)

    def _check_filtered_extended_quota(self, quota_set):
        self.assertNotIn('server_groups', quota_set)
        self.assertNotIn('server_group_members', quota_set)
        self.assertEqual(10, quota_set['floating_ips'])
        self.assertEqual(-1, quota_set['fixed_ips'])
        self.assertEqual(10, quota_set['security_groups'])
        self.assertEqual(20, quota_set['security_group_rules'])

    def test_format_quota_set(self):
        quota_set = self.controller._format_quota_set('test_class',
                                                      self.quota_resources,
                                                      self.req)
        qs = quota_set['quota_class_set']

        self.assertEqual(qs['id'], 'test_class')
        self.assertEqual(qs['instances'], 10)
        self.assertEqual(qs['cores'], 20)
        self.assertEqual(qs['ram'], 51200)
        self.assertEqual(qs['metadata_items'], 128)
        self.assertEqual(qs['injected_files'], 5)
        self.assertEqual(qs['injected_file_path_bytes'], 255)
        self.assertEqual(qs['injected_file_content_bytes'], 10240)
        self.assertEqual(qs['key_pairs'], 100)
        self._check_filtered_extended_quota(qs)

    def test_quotas_show(self):
        res_dict = self.controller.show(self.req, 'test_class')

        self.assertEqual(res_dict, self.quota_set('test_class'))

    def test_quotas_update(self):
        expected_body = {'quota_class_set': self.quota_resources}
        request_quota_resources = copy.deepcopy(self.quota_resources)
        request_quota_resources['server_groups'] = 10
        request_quota_resources['server_group_members'] = 10
        request_body = {'quota_class_set': request_quota_resources}
        res_dict = self.controller.update(self.req, 'test_class',
                                          body=request_body)

        self.assertEqual(res_dict, expected_body)

    def test_quotas_update_with_empty_body(self):
        body = {}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req, 'test_class', body=body)

    def test_quotas_update_with_invalid_integer(self):
        body = {'quota_class_set': {'instances': 2 ** 31 + 1}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req, 'test_class', body=body)

    def test_quotas_update_with_long_quota_class_name(self):
        name = 'a' * 256
        body = {'quota_class_set': {'instances': 10}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, name, body=body)

    def test_quotas_update_with_non_integer(self):
        body = {'quota_class_set': {'instances': "abc"}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req, 'test_class', body=body)

        body = {'quota_class_set': {'instances': 50.5}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req, 'test_class', body=body)

        body = {'quota_class_set': {
                'instances': u'\u30aa\u30fc\u30d7\u30f3'}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req, 'test_class', body=body)

    def test_quotas_update_with_unsupported_quota_class(self):
        body = {'quota_class_set': {'instances': 50, 'cores': 50,
                                    'ram': 51200, 'unsupported': 12}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req, 'test_class', body=body)


class QuotaClassSetsTestV250(QuotaClassSetsTestV21):
    api_version = '2.50'
    quota_resources = {'metadata_items': 128,
                       'ram': 51200, 'instances': 10,
                       'injected_files': 5, 'cores': 20,
                       'injected_file_content_bytes': 10240,
                       'key_pairs': 100,
                       'injected_file_path_bytes': 255,
                       'server_groups': 10,
                       'server_group_members': 10}

    def _check_filtered_extended_quota(self, quota_set):
        self.assertEqual(10, quota_set['server_groups'])
        self.assertEqual(10, quota_set['server_group_members'])
        self.assertNotIn('floating_ips', quota_set)
        self.assertNotIn('fixed_ips', quota_set)
        self.assertNotIn('security_groups', quota_set)
        self.assertNotIn('security_group_rules', quota_set)
        self.assertNotIn('networks', quota_set)

    def test_quotas_update_with_filtered_quota(self):
        filtered_quotas = ["fixed_ips", "floating_ips", "networks",
                           "security_group_rules", "security_groups"]
        for resource in filtered_quotas:
            body = {'quota_class_set': {resource: 10}}
            self.assertRaises(self.validation_error, self.controller.update,
                              self.req, 'test_class', body=body)


class QuotaClassesPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(QuotaClassesPolicyEnforcementV21, self).setUp()
        ext_info = extension_info.LoadedExtensionInfo()
        self.controller = quota_classes_v21.QuotaClassSetsController(
            extension_info=ext_info)
        self.req = fakes.HTTPRequest.blank('')

    def test_show_policy_failed(self):
        rule_name = "os_compute_api:os-quota-class-sets:show"
        self.policy.set_rules({rule_name: "quota_class:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_update_policy_failed(self):
        rule_name = "os_compute_api:os-quota-class-sets:update"
        self.policy.set_rules({rule_name: "quota_class:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.update, self.req, fakes.FAKE_UUID,
            body={'quota_class_set': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())
