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

from lxml import etree
import webob

from nova.api.openstack.compute.plugins.v3 import quota_classes
from nova.api.openstack import wsgi
from nova import test
from nova.tests.api.openstack import fakes


def quota_set(class_name):
    return {'quota_class_set': {'id': class_name, 'metadata_items': 128,
                                'ram': 51200, 'floating_ips': 10,
                                'fixed_ips': -1, 'instances': 10,
                                'injected_files': 5, 'cores': 20,
                                'injected_file_content_bytes': 10240,
                                'security_groups': 10,
                                'security_group_rules': 20, 'key_pairs': 100,
                                'injected_file_path_bytes': 255}}


class QuotaClassSetsTest(test.TestCase):

    def setUp(self):
        super(QuotaClassSetsTest, self).setUp()
        self.controller = quota_classes.QuotaClassSetsController()

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
        req = fakes.HTTPRequestV3.blank('/os-quota-class-sets/test_class',
                                        use_admin_context=True)
        res_dict = self.controller.show(req, 'test_class')

        self.assertEqual(res_dict, quota_set('test_class'))

    def test_quotas_show_as_unauthorized_user(self):
        req = fakes.HTTPRequestV3.blank('/os-quota-class-sets/test_class')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          req, 'test_class')

    def test_quotas_update_as_admin(self):
        body = {'quota_class_set': {'instances': 50, 'cores': 50,
                                    'ram': 51200, 'floating_ips': 10,
                                    'fixed_ips': -1, 'metadata_items': 128,
                                    'injected_files': 5, 'id': 'test_class',
                                    'injected_file_content_bytes': 10240,
                                    'injected_file_path_bytes': 255,
                                    'security_groups': 10,
                                    'security_group_rules': 20,
                                    'key_pairs': 100}}

        req = fakes.HTTPRequestV3.blank('/os-quota-class-sets/test_class',
                                        use_admin_context=True)
        res_dict = self.controller.update(req, 'test_class', body)

        self.assertEqual(res_dict, body)

    def test_quotas_update_with_non_integer(self):
        body = {'quota_class_set': {'instances': "abc"}}
        req = fakes.HTTPRequestV3.blank('/os-quota-class-sets/test_class',
                                        use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'test_class', body)

    def test_quotas_update_with_invalid_body(self):
        body = {'quota_class_set': None}
        req = fakes.HTTPRequestV3.blank('/os-quota-class-sets/test_class',
                                        use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'test_class', body)
        body = {}
        req = fakes.HTTPRequestV3.blank('/os-quota-class-sets/test_class',
                                        use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'test_class', body)

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

        req = fakes.HTTPRequestV3.blank('/os-quota-class-sets/test_class')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          req, 'test_class', body)


class QuotaTemplateXMLSerializerTest(test.TestCase):
    def setUp(self):
        super(QuotaTemplateXMLSerializerTest, self).setUp()
        self.serializer = quota_classes.QuotaClassTemplate()
        self.deserializer = wsgi.XMLDeserializer()

    def test_serializer(self):
        exemplar = dict(quota_class_set=dict(
                id='test_class',
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

        self.assertEqual('quota_class_set', tree.tag)
        self.assertEqual('test_class', tree.get('id'))
        self.assertEqual(len(exemplar['quota_class_set']) - 1, len(tree))
        for child in tree:
            self.assertTrue(child.tag in exemplar['quota_class_set'])
            self.assertEqual(int(child.text),
                             exemplar['quota_class_set'][child.tag])

    def test_deserializer(self):
        exemplar = dict(quota_class_set=dict(
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
                  '<quota_class_set>'
                  '<metadata_items>10</metadata_items>'
                  '<injected_file_content_bytes>20'
                  '</injected_file_content_bytes>'
                  '<ram>50</ram>'
                  '<floating_ips>60</floating_ips>'
                  '<fixed_ips>-1</fixed_ips>'
                  '<instances>70</instances>'
                  '<injected_files>80</injected_files>'
                  '<cores>90</cores>'
                  '<security_groups>10</security_groups>'
                  '<security_group_rules>20</security_group_rules>'
                  '<key_pairs>100</key_pairs>'
                  '</quota_class_set>')

        result = self.deserializer.deserialize(intext)['body']
        self.assertEqual(result, exemplar)
