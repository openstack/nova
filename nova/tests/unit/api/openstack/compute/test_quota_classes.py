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

from nova.api.openstack.compute import quota_classes \
       as quota_classes_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


class QuotaClassSetsTestV21(test.TestCase):
    validation_error = exception.ValidationError
    api_version = '2.1'
    quota_resources = {'metadata_items': 128,
                       'ram': 51200, 'floating_ips': -1,
                       'fixed_ips': -1, 'instances': 10,
                       'injected_files': 5, 'cores': 20,
                       'injected_file_content_bytes': 10240,
                       'security_groups': -1,
                       'security_group_rules': -1, 'key_pairs': 100,
                       'injected_file_path_bytes': 255}
    filtered_quotas = None

    def quota_set(self, class_name):
        quotas = copy.deepcopy(self.quota_resources)
        quotas['id'] = class_name
        return {'quota_class_set': quotas}

    def setUp(self):
        super(QuotaClassSetsTestV21, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version=self.api_version)
        self._setup()

    def _setup(self):
        self.controller = quota_classes_v21.QuotaClassSetsController()

    def _check_filtered_extended_quota(self, quota_set):
        self.assertNotIn('server_groups', quota_set)
        self.assertNotIn('server_group_members', quota_set)
        self.assertEqual(-1, quota_set['floating_ips'])
        self.assertEqual(-1, quota_set['fixed_ips'])
        self.assertEqual(-1, quota_set['security_groups'])
        self.assertEqual(-1, quota_set['security_group_rules'])

    def test_format_quota_set(self):
        quota_set = self.controller._format_quota_set('test_class',
                                                      self.quota_resources,
                                                      self.filtered_quotas)
        qs = quota_set['quota_class_set']

        self.assertEqual(qs['id'], 'test_class')
        for resource, value in self.quota_resources.items():
            self.assertEqual(value, qs[resource])
        if self.filtered_quotas:
            for resource in self.filtered_quotas:
                self.assertNotIn(resource, qs)
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
    filtered_quotas = quota_classes_v21.FILTERED_QUOTAS_2_50

    def _check_filtered_extended_quota(self, quota_set):
        self.assertEqual(10, quota_set['server_groups'])
        self.assertEqual(10, quota_set['server_group_members'])
        for resource in self.filtered_quotas:
            self.assertNotIn(resource, quota_set)

    def test_quotas_update_with_filtered_quota(self):
        for resource in self.filtered_quotas:
            body = {'quota_class_set': {resource: 10}}
            self.assertRaises(self.validation_error, self.controller.update,
                              self.req, 'test_class', body=body)


class QuotaClassSetsTestV257(QuotaClassSetsTestV250):
    api_version = '2.57'

    def setUp(self):
        super(QuotaClassSetsTestV257, self).setUp()
        for resource in quota_classes_v21.FILTERED_QUOTAS_2_57:
            self.quota_resources.pop(resource, None)
        self.filtered_quotas.extend(quota_classes_v21.FILTERED_QUOTAS_2_57)
