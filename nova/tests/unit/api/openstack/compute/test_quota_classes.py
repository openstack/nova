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
from unittest import mock

from oslo_limit import fixture as limit_fixture
import webob

from nova.api.openstack.compute import quota_classes \
       as quota_classes_v21
from nova import exception
from nova.limit import local as local_limit
from nova.limit import placement as placement_limit
from nova import objects
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


class NoopQuotaClassesTest(test.NoDBTestCase):
    quota_driver = "nova.quota.NoopQuotaDriver"

    def setUp(self):
        super(NoopQuotaClassesTest, self).setUp()
        self.flags(driver=self.quota_driver, group="quota")
        self.controller = quota_classes_v21.QuotaClassSetsController()

    def test_show_v21(self):
        req = fakes.HTTPRequest.blank("")
        response = self.controller.show(req, "test_class")
        expected_response = {
            'quota_class_set': {
                'id': 'test_class',
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
                'security_groups': -1
            }
        }
        self.assertEqual(expected_response, response)

    def test_show_v257(self):
        req = fakes.HTTPRequest.blank("", version='2.57')
        response = self.controller.show(req, "default")
        expected_response = {
            'quota_class_set': {
                'id': 'default',
                'cores': -1,
                'instances': -1,
                'key_pairs': -1,
                'metadata_items': -1,
                'ram': -1,
                'server_group_members': -1,
                'server_groups': -1,
            }
        }
        self.assertEqual(expected_response, response)

    def test_update_v21_still_rejects_badrequests(self):
        req = fakes.HTTPRequest.blank("")
        body = {'quota_class_set': {'instances': 50, 'cores': 50,
                                    'ram': 51200, 'unsupported': 12}}
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, 'test_class', body=body)

    @mock.patch.object(objects.Quotas, "update_class")
    def test_update_v21(self, mock_update):
        req = fakes.HTTPRequest.blank("")
        body = {'quota_class_set': {'ram': 51200}}
        response = self.controller.update(req, 'default', body=body)
        expected_response = {
            'quota_class_set': {
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
                'security_groups': -1
            }
        }
        self.assertEqual(expected_response, response)
        mock_update.assert_called_once_with(req.environ['nova.context'],
                                            "default", "ram", 51200)

    @mock.patch.object(objects.Quotas, "update_class")
    def test_update_v257(self, mock_update):
        req = fakes.HTTPRequest.blank("", version='2.57')
        body = {'quota_class_set': {'ram': 51200}}
        response = self.controller.update(req, 'default', body=body)
        expected_response = {
            'quota_class_set': {
                'cores': -1,
                'instances': -1,
                'key_pairs': -1,
                'metadata_items': -1,
                'ram': -1,
                'server_group_members': -1,
                'server_groups': -1,
            }
        }
        self.assertEqual(expected_response, response)
        mock_update.assert_called_once_with(req.environ['nova.context'],
                                            "default", "ram", 51200)


class UnifiedLimitsQuotaClassesTest(NoopQuotaClassesTest):
    quota_driver = "nova.quota.UnifiedLimitsDriver"

    def setUp(self):
        super(UnifiedLimitsQuotaClassesTest, self).setUp()
        # Set server_groups so all config options get a different value
        # but we also test as much as possible with the default config
        self.flags(driver="nova.quota.UnifiedLimitsDriver", group='quota')
        reglimits = {local_limit.SERVER_METADATA_ITEMS: 128,
                     local_limit.INJECTED_FILES: 5,
                     local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
                     local_limit.INJECTED_FILES_PATH: 255,
                     local_limit.KEY_PAIRS: 100,
                     local_limit.SERVER_GROUPS: 12,
                     local_limit.SERVER_GROUP_MEMBERS: 10}
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))

    @mock.patch.object(placement_limit, "get_legacy_default_limits")
    def test_show_v21(self, mock_default):
        mock_default.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("")
        response = self.controller.show(req, "test_class")
        expected_response = {
            'quota_class_set': {
                'id': 'test_class',
                'cores': 2,
                'fixed_ips': -1,
                'floating_ips': -1,
                'ram': 3,
                'injected_file_content_bytes': 10240,
                'injected_file_path_bytes': 255,
                'injected_files': 5,
                'instances': 1,
                'key_pairs': 100,
                'metadata_items': 128,
                'security_group_rules': -1,
                'security_groups': -1,
            }
        }
        self.assertEqual(expected_response, response)

    @mock.patch.object(placement_limit, "get_legacy_default_limits")
    def test_show_v257(self, mock_default):
        mock_default.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("", version='2.57')
        response = self.controller.show(req, "default")
        expected_response = {
            'quota_class_set': {
                'id': 'default',
                'cores': 2,
                'instances': 1,
                'ram': 3,
                'key_pairs': 100,
                'metadata_items': 128,
                'server_group_members': 10,
                'server_groups': 12,
            }
        }
        self.assertEqual(expected_response, response)

    def test_update_still_rejects_badrequests(self):
        req = fakes.HTTPRequest.blank("")
        body = {'quota_class_set': {'instances': 50, 'cores': 50,
                                    'ram': 51200, 'unsupported': 12}}
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, 'test_class', body=body)

    @mock.patch.object(placement_limit, "get_legacy_default_limits")
    @mock.patch.object(objects.Quotas, "update_class")
    def test_update_v21(self, mock_update, mock_default):
        mock_default.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("")
        body = {'quota_class_set': {'ram': 51200}}
        response = self.controller.update(req, 'default', body=body)
        expected_response = {
            'quota_class_set': {
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
                'security_groups': -1
            }
        }
        self.assertEqual(expected_response, response)
        # TODO(johngarbutt) we should be proxying to keystone
        self.assertEqual(0, mock_update.call_count)

    @mock.patch.object(placement_limit, "get_legacy_default_limits")
    @mock.patch.object(objects.Quotas, "update_class")
    def test_update_v257(self, mock_update, mock_default):
        mock_default.return_value = {"instances": 1, "cores": 2, "ram": 3}
        req = fakes.HTTPRequest.blank("", version='2.57')
        body = {'quota_class_set': {'ram': 51200}}
        response = self.controller.update(req, 'default', body=body)
        expected_response = {
            'quota_class_set': {
                'cores': 2,
                'instances': 1,
                'ram': 3,
                'key_pairs': 100,
                'metadata_items': 128,
                'server_group_members': 10,
                'server_groups': 12,
            }
        }
        self.assertEqual(expected_response, response)
        # TODO(johngarbutt) we should be proxying to keystone
        self.assertEqual(0, mock_update.call_count)
