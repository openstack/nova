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

import webob

from nova.api.openstack.compute.contrib import quota_classes
from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import quota_classes \
       as quota_classes_v21
from nova.api.openstack import extensions
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


def quota_set(class_name):
    return {'quota_class_set': {'id': class_name, 'metadata_items': 128,
                                'ram': 51200, 'floating_ips': 10,
                                'fixed_ips': -1, 'instances': 10,
                                'injected_files': 5, 'cores': 20,
                                'injected_file_content_bytes': 10240,
                                'security_groups': 10,
                                'security_group_rules': 20, 'key_pairs': 100,
                                'injected_file_path_bytes': 255}}


class QuotaClassSetsTestV21(test.TestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(QuotaClassSetsTestV21, self).setUp()
        self.req_admin = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.req = fakes.HTTPRequest.blank('')
        self._setup()

    def _setup(self):
        ext_info = plugins.LoadedExtensionInfo()
        self.controller = quota_classes_v21.QuotaClassSetsController(
            extension_info=ext_info)

    def test_format_quota_set(self):
        raw_quota_set = {
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

        quota_set = self.controller._format_quota_set('test_class',
                                                      raw_quota_set)
        qs = quota_set['quota_class_set']

        self.assertEqual(qs['id'], 'test_class')
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

    def test_quotas_show_as_admin(self):
        res_dict = self.controller.show(self.req_admin, 'test_class')

        self.assertEqual(res_dict, quota_set('test_class'))

    def test_quotas_show_as_unauthorized_user(self):
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          self.req, 'test_class')

    def test_quotas_update_as_admin(self):
        body = {'quota_class_set': {'instances': 50, 'cores': 50,
                                    'ram': 51200, 'floating_ips': 10,
                                    'fixed_ips': -1, 'metadata_items': 128,
                                    'injected_files': 5,
                                    'injected_file_content_bytes': 10240,
                                    'injected_file_path_bytes': 255,
                                    'security_groups': 10,
                                    'security_group_rules': 20,
                                    'key_pairs': 100}}

        res_dict = self.controller.update(self.req_admin, 'test_class',
                                          body=body)

        self.assertEqual(res_dict, body)

    def test_quotas_update_as_user(self):
        body = {'quota_class_set': {'instances': 50, 'cores': 50,
                                    'ram': 51200, 'floating_ips': 10,
                                    'fixed_ips': -1, 'metadata_items': 128,
                                    'injected_files': 5,
                                    'injected_file_content_bytes': 10240,
                                    'security_groups': 10,
                                    'security_group_rules': 20,
                                    'key_pairs': 100,
                                    }}

        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          self.req, 'test_class', body=body)

    def test_quotas_update_with_empty_body(self):
        body = {}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req_admin, 'test_class', body=body)

    def test_quotas_update_with_non_integer(self):
        body = {'quota_class_set': {'instances': "abc"}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req_admin, 'test_class', body=body)

        body = {'quota_class_set': {'instances': 50.5}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req_admin, 'test_class', body=body)

        body = {'quota_class_set': {
                'instances': u'\u30aa\u30fc\u30d7\u30f3'}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req_admin, 'test_class', body=body)

    def test_quotas_update_with_unsupported_quota_class(self):
        body = {'quota_class_set': {'instances': 50, 'cores': 50,
                                    'ram': 51200, 'unsupported': 12}}
        self.assertRaises(self.validation_error, self.controller.update,
                          self.req_admin, 'test_class', body=body)


class QuotaClassSetsTestV2(QuotaClassSetsTestV21):
    validation_error = webob.exc.HTTPBadRequest

    def _setup(self):
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {}
        self.controller = quota_classes.QuotaClassSetsController(ext_mgr)
