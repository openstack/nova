# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova.api.openstack.compute.contrib import quotas
from nova.api.openstack import wsgi
from nova import test
from nova.tests.api.openstack import fakes


def quota_set(id):
    return {'quota_set': {'id': id, 'metadata_items': 128, 'volumes': 10,
                          'gigabytes': 1000, 'ram': 51200, 'floating_ips': 10,
                          'fixed_ips': -1, 'instances': 10,
                          'injected_files': 5, 'cores': 20,
                          'injected_file_content_bytes': 10240,
                          'security_groups': 10, 'security_group_rules': 20,
                          'key_pairs': 100, 'injected_file_path_bytes': 255}}


class QuotaSetsTest(test.TestCase):

    def setUp(self):
        super(QuotaSetsTest, self).setUp()
        self.controller = quotas.QuotaSetsController()

    def test_format_quota_set(self):
        raw_quota_set = {
            'instances': 10,
            'cores': 20,
            'ram': 51200,
            'volumes': 10,
            'floating_ips': 10,
            'fixed_ips': -1,
            'metadata_items': 128,
            'gigabytes': 1000,
            'injected_files': 5,
            'injected_file_path_bytes': 255,
            'injected_file_content_bytes': 10240,
            'security_groups': 10,
            'security_group_rules': 20,
            'key_pairs': 100,
            }

        quota_set = self.controller._format_quota_set('1234', raw_quota_set)
        qs = quota_set['quota_set']

        self.assertEqual(qs['id'], '1234')
        self.assertEqual(qs['instances'], 10)
        self.assertEqual(qs['cores'], 20)
        self.assertEqual(qs['ram'], 51200)
        self.assertEqual(qs['volumes'], 10)
        self.assertEqual(qs['gigabytes'], 1000)
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

        expected = {'quota_set': {
                    'id': 'fake_tenant',
                    'instances': 10,
                    'cores': 20,
                    'ram': 51200,
                    'volumes': 10,
                    'gigabytes': 1000,
                    'floating_ips': 10,
                    'fixed_ips': -1,
                    'metadata_items': 128,
                    'injected_files': 5,
                    'injected_file_path_bytes': 255,
                    'injected_file_content_bytes': 10240,
                    'security_groups': 10,
                    'security_group_rules': 20,
                    'key_pairs': 100,
                    }}

        self.assertEqual(res_dict, expected)

    def test_quotas_show_as_admin(self):
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234',
                                      use_admin_context=True)
        res_dict = self.controller.show(req, 1234)

        self.assertEqual(res_dict, quota_set('1234'))

    def test_quotas_show_as_unauthorized_user(self):
        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/1234')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          req, 1234)

    def test_quotas_update_as_admin(self):
        body = {'quota_set': {'instances': 50, 'cores': 50,
                              'ram': 51200, 'volumes': 10,
                              'gigabytes': 1000, 'floating_ips': 10,
                              'metadata_items': 128, 'injected_files': 5,
                              'fixed_ips': -1,
                              'injected_file_content_bytes': 10240,
                              'injected_file_path_bytes': 255,
                              'security_groups': 10,
                              'security_group_rules': 20,
                              'key_pairs': 100, 'fixed_ips': -1}}

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        res_dict = self.controller.update(req, 'update_me', body)

        self.assertEqual(res_dict, body)

    def test_quotas_update_as_user(self):
        body = {'quota_set': {'instances': 50, 'cores': 50,
                              'ram': 51200, 'volumes': 10,
                              'gigabytes': 1000, 'floating_ips': 10,
                              'metadata_items': 128, 'injected_files': 5,
                              'fixed_ips': -1,
                              'injected_file_content_bytes': 10240,
                              'security_groups': 10,
                              'security_group_rules': 20,
                              'key_pairs': 100}}

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          req, 'update_me', body)

    def test_quotas_update_invalid_limit(self):
        body = {'quota_set': {'instances': -2, 'cores': -2,
                              'ram': -2, 'volumes': -2,
                              'gigabytes': -2, 'floating_ips': -2,
                              'metadata_items': -2, 'injected_files': -2,
                              'injected_file_content_bytes': -2}}

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 'update_me', body)


class QuotaXMLSerializerTest(test.TestCase):
    def setUp(self):
        super(QuotaXMLSerializerTest, self).setUp()
        self.serializer = quotas.QuotaTemplate()
        self.deserializer = wsgi.XMLDeserializer()

    def test_serializer(self):
        exemplar = dict(quota_set=dict(
                id='project_id',
                metadata_items=10,
                injected_file_path_bytes=255,
                injected_file_content_bytes=20,
                volumes=30,
                gigabytes=40,
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

        print text
        tree = etree.fromstring(text)

        self.assertEqual('quota_set', tree.tag)
        self.assertEqual('project_id', tree.get('id'))
        self.assertEqual(len(exemplar['quota_set']) - 1, len(tree))
        for child in tree:
            self.assertTrue(child.tag in exemplar['quota_set'])
            self.assertEqual(int(child.text), exemplar['quota_set'][child.tag])

    def test_deserializer(self):
        exemplar = dict(quota_set=dict(
                metadata_items='10',
                injected_file_content_bytes='20',
                volumes='30',
                gigabytes='40',
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
                  '<volumes>30</volumes>'
                  '<gigabytes>40</gigabytes>'
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
