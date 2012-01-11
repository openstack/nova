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

import webob
from lxml import etree

from nova.api.openstack import wsgi
from nova.api.openstack.v2.contrib import quotas
from nova import context
from nova import test
from nova.tests.api.openstack import fakes


def quota_set(id):
    return {'quota_set': {'id': id, 'metadata_items': 128, 'volumes': 10,
            'gigabytes': 1000, 'ram': 51200, 'floating_ips': 10,
            'instances': 10, 'injected_files': 5, 'cores': 20,
            'injected_file_content_bytes': 10240}}


def quota_set_list():
    return {'quota_set_list': [quota_set('1234'), quota_set('5678'),
                               quota_set('update_me')]}


class QuotaSetsTest(test.TestCase):

    def setUp(self):
        super(QuotaSetsTest, self).setUp()
        self.controller = quotas.QuotaSetsController()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.user_context = context.RequestContext(self.user_id,
                                                   self.project_id)
        self.admin_context = context.RequestContext(self.user_id,
                                                    self.project_id,
                                                    is_admin=True)

    def test_format_quota_set(self):
        raw_quota_set = {
            'instances': 10,
            'cores': 20,
            'ram': 51200,
            'volumes': 10,
            'floating_ips': 10,
            'metadata_items': 128,
            'gigabytes': 1000,
            'injected_files': 5,
            'injected_file_content_bytes': 10240}

        quota_set = quotas.QuotaSetsController()._format_quota_set('1234',
                                                            raw_quota_set)
        qs = quota_set['quota_set']

        self.assertEqual(qs['id'], '1234')
        self.assertEqual(qs['instances'], 10)
        self.assertEqual(qs['cores'], 20)
        self.assertEqual(qs['ram'], 51200)
        self.assertEqual(qs['volumes'], 10)
        self.assertEqual(qs['gigabytes'], 1000)
        self.assertEqual(qs['floating_ips'], 10)
        self.assertEqual(qs['metadata_items'], 128)
        self.assertEqual(qs['injected_files'], 5)
        self.assertEqual(qs['injected_file_content_bytes'], 10240)

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
                    'metadata_items': 128,
                    'injected_files': 5,
                    'injected_file_content_bytes': 10240}}

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
                              'injected_file_content_bytes': 10240}}

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me',
                                      use_admin_context=True)
        res_dict = self.controller.update(req, 'update_me', body)

        self.assertEqual(res_dict, body)

    def test_quotas_update_as_user(self):
        body = {'quota_set': {'instances': 50, 'cores': 50,
                              'ram': 51200, 'volumes': 10,
                              'gigabytes': 1000, 'floating_ips': 10,
                              'metadata_items': 128, 'injected_files': 5,
                              'injected_file_content_bytes': 10240}}

        req = fakes.HTTPRequest.blank('/v2/fake4/os-quota-sets/update_me')
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
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
                injected_file_content_bytes=20,
                volumes=30,
                gigabytes=40,
                ram=50,
                floating_ips=60,
                instances=70,
                injected_files=80,
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
                instances='70',
                injected_files='80',
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
                  '<instances>70</instances>'
                  '<injected_files>80</injected_files>'
                  '<cores>90</cores>'
                  '</quota_set>')

        result = self.deserializer.deserialize(intext)['body']
        self.assertEqual(result, exemplar)
