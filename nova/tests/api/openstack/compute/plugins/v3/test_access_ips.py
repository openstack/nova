# Copyright 2013 IBM Corp.
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
from xml.dom import minidom

import webob

from nova.api.openstack.compute.plugins.v3 import access_ips
from nova.api.openstack.compute.plugins.v3 import servers
from nova.api.openstack import wsgi
from nova import test
from nova.tests.api.openstack import fakes


class AccessIPsExtTest(test.NoDBTestCase):
    def setUp(self):
        super(AccessIPsExtTest, self).setUp()
        self.access_ips_ext = access_ips.AccessIPs(None)

    def _test(self, func):
        server_dict = {access_ips.AccessIPs.v4_key: '1.1.1.1',
                       access_ips.AccessIPs.v6_key: 'fe80::'}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {'access_ip_v4': '1.1.1.1',
                                         'access_ip_v6': 'fe80::'})

    def _test_with_ipv4_only(self, func):
        server_dict = {access_ips.AccessIPs.v4_key: '1.1.1.1'}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {'access_ip_v4': '1.1.1.1'})

    def _test_with_ipv6_only(self, func):
        server_dict = {access_ips.AccessIPs.v6_key: 'fe80::'}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {'access_ip_v6': 'fe80::'})

    def _test_without_ipv4_and_ipv6(self, func):
        server_dict = {}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {})

    def _test_with_invalid_ipv4(self, func):
        server_dict = {access_ips.AccessIPs.v4_key: '1.1.1.1.1.1'}
        create_kwargs = {}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          func,
                          server_dict,
                          create_kwargs)

    def _test_with_invalid_ipv6(self, func):
        server_dict = {access_ips.AccessIPs.v6_key: 'fe80:::::::'}
        create_kwargs = {}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          func,
                          server_dict,
                          create_kwargs)

    def _test_with_ipv4_null(self, func):
        server_dict = {access_ips.AccessIPs.v4_key: None}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {'access_ip_v4': None})

    def _test_with_ipv6_null(self, func):
        server_dict = {access_ips.AccessIPs.v6_key: None}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {'access_ip_v6': None})

    def _test_with_ipv4_blank(self, func):
        server_dict = {access_ips.AccessIPs.v4_key: ''}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {'access_ip_v4': None})

    def _test_with_ipv6_blank(self, func):
        server_dict = {access_ips.AccessIPs.v6_key: ''}
        create_kwargs = {}
        func(server_dict, create_kwargs)
        self.assertEqual(create_kwargs, {'access_ip_v6': None})

    def test_server_create(self):
        self._test(self.access_ips_ext.server_create)

    def test_server_create_with_ipv4_only(self):
        self._test_with_ipv4_only(self.access_ips_ext.server_create)

    def test_server_create_with_ipv6_only(self):
        self._test_with_ipv6_only(self.access_ips_ext.server_create)

    def test_server_create_without_ipv4_and_ipv6(self):
        self._test_without_ipv4_and_ipv6(self.access_ips_ext.server_create)

    def test_server_create_with_invalid_ipv4(self):
        self._test_with_invalid_ipv4(self.access_ips_ext.server_create)

    def test_server_create_with_invalid_ipv6(self):
        self._test_with_invalid_ipv6(self.access_ips_ext.server_create)

    def test_server_create_with_ipv4_null(self):
        self._test_with_ipv4_null(self.access_ips_ext.server_create)

    def test_server_create_with_ipv6_null(self):
        self._test_with_ipv6_null(self.access_ips_ext.server_create)

    def test_server_create_with_ipv4_blank(self):
        self._test_with_ipv4_blank(self.access_ips_ext.server_create)

    def test_server_create_with_ipv6_blank(self):
        self._test_with_ipv6_blank(self.access_ips_ext.server_create)

    def test_server_update(self):
        self._test(self.access_ips_ext.server_update)

    def test_server_update_with_ipv4_only(self):
        self._test_with_ipv4_only(self.access_ips_ext.server_update)

    def test_server_update_with_ipv6_only(self):
        self._test_with_ipv6_only(self.access_ips_ext.server_update)

    def test_server_update_without_ipv4_and_ipv6(self):
        self._test_without_ipv4_and_ipv6(self.access_ips_ext.server_update)

    def test_server_update_with_invalid_ipv4(self):
        self._test_with_invalid_ipv4(self.access_ips_ext.server_update)

    def test_server_update_with_invalid_ipv6(self):
        self._test_with_invalid_ipv6(self.access_ips_ext.server_update)

    def test_server_update_with_ipv4_null(self):
        self._test_with_ipv4_null(self.access_ips_ext.server_update)

    def test_server_update_with_ipv6_null(self):
        self._test_with_ipv6_null(self.access_ips_ext.server_update)

    def test_server_update_with_ipv4_blank(self):
        self._test_with_ipv4_blank(self.access_ips_ext.server_update)

    def test_server_update_with_ipv6_blank(self):
        self._test_with_ipv6_blank(self.access_ips_ext.server_update)

    def test_server_rebuild(self):
        self._test(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_ipv4_only(self):
        self._test_with_ipv4_only(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_ipv6_only(self):
        self._test_with_ipv6_only(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_without_ipv4_and_ipv6(self):
        self._test_without_ipv4_and_ipv6(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_invalid_ipv4(self):
        self._test_with_invalid_ipv4(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_invalid_ipv6(self):
        self._test_with_invalid_ipv6(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_ipv4_null(self):
        self._test_with_ipv4_null(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_ipv6_null(self):
        self._test_with_ipv6_null(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_ipv4_blank(self):
        self._test_with_ipv4_blank(self.access_ips_ext.server_rebuild)

    def test_server_rebuild_with_ipv6_blank(self):
        self._test_with_ipv6_blank(self.access_ips_ext.server_rebuild)


class AccessIPsControllerTest(test.NoDBTestCase):
    def setUp(self):
        super(AccessIPsControllerTest, self).setUp()
        self.controller = access_ips.AccessIPsController()

    def _test_with_access_ips(self, func, kwargs={'id': 'fake'}):
        req = wsgi.Request({'nova.context':
                    fakes.FakeRequestContext('fake_user', 'fake',
                                             is_admin=True)})
        instance = {'uuid': 'fake',
                    'access_ip_v4': '1.1.1.1',
                    'access_ip_v6': 'fe80::'}
        req.cache_db_instance(instance)
        resp_obj = wsgi.ResponseObject(
            {"server": {'id': 'fake'}})
        func(req, resp_obj, **kwargs)
        self.assertEqual(resp_obj.obj['server'][access_ips.AccessIPs.v4_key],
                         '1.1.1.1')
        self.assertEqual(resp_obj.obj['server'][access_ips.AccessIPs.v6_key],
                         'fe80::')

    def _test_without_access_ips(self, func, kwargs={'id': 'fake'}):
        req = wsgi.Request({'nova.context':
                    fakes.FakeRequestContext('fake_user', 'fake',
                                             is_admin=True)})
        instance = {'uuid': 'fake',
                    'access_ip_v4': None,
                    'access_ip_v6': None}
        req.cache_db_instance(instance)
        resp_obj = wsgi.ResponseObject(
            {"server": {'id': 'fake'}})
        func(req, resp_obj, **kwargs)
        self.assertEqual(resp_obj.obj['server'][access_ips.AccessIPs.v4_key],
                         '')
        self.assertEqual(resp_obj.obj['server'][access_ips.AccessIPs.v6_key],
                         '')

    def test_create(self):
        self._test_with_access_ips(self.controller.create, {'body': {}})

    def test_create_without_access_ips(self):
        self._test_with_access_ips(self.controller.create, {'body': {}})

    def test_create_with_reservation_id(self):
        req = wsgi.Request({'nova.context':
                    fakes.FakeRequestContext('fake_user', 'fake',
                                             is_admin=True)})
        expected_res = {'servers_reservation': {'reservation_id': 'test'}}
        body = copy.deepcopy(expected_res)
        resp_obj = wsgi.ResponseObject(body)
        self.controller.create(req, resp_obj, body)
        self.assertEqual(expected_res, resp_obj.obj)

    def test_show(self):
        self._test_with_access_ips(self.controller.show)

    def test_show_without_access_ips(self):
        self._test_without_access_ips(self.controller.show)

    def test_detail(self):
        req = wsgi.Request({'nova.context':
                    fakes.FakeRequestContext('fake_user', 'fake',
                                             is_admin=True)})
        instance1 = {'uuid': 'fake1',
                     'access_ip_v4': '1.1.1.1',
                     'access_ip_v6': 'fe80::'}
        instance2 = {'uuid': 'fake2',
                     'access_ip_v4': '1.1.1.2',
                     'access_ip_v6': 'fe81::'}
        req.cache_db_instance(instance1)
        req.cache_db_instance(instance2)
        resp_obj = wsgi.ResponseObject(
            {"servers": [{'id': 'fake1'}, {'id': 'fake2'}]})
        self.controller.detail(req, resp_obj)
        self.assertEqual(
            resp_obj.obj['servers'][0][access_ips.AccessIPs.v4_key],
            '1.1.1.1')
        self.assertEqual(
            resp_obj.obj['servers'][0][access_ips.AccessIPs.v6_key],
            'fe80::')
        self.assertEqual(
            resp_obj.obj['servers'][1][access_ips.AccessIPs.v4_key],
            '1.1.1.2')
        self.assertEqual(
            resp_obj.obj['servers'][1][access_ips.AccessIPs.v6_key],
            'fe81::')

    def test_detail_without_access_ips(self):
        req = wsgi.Request({'nova.context':
                    fakes.FakeRequestContext('fake_user', 'fake',
                                             is_admin=True)})
        instance1 = {'uuid': 'fake1',
                     'access_ip_v4': None,
                     'access_ip_v6': None}
        instance2 = {'uuid': 'fake2',
                     'access_ip_v4': None,
                     'access_ip_v6': None}
        req.cache_db_instance(instance1)
        req.cache_db_instance(instance2)
        resp_obj = wsgi.ResponseObject(
            {"servers": [{'id': 'fake1'}, {'id': 'fake2'}]})
        self.controller.detail(req, resp_obj)
        self.assertEqual(
            resp_obj.obj['servers'][0][access_ips.AccessIPs.v4_key], '')
        self.assertEqual(
            resp_obj.obj['servers'][0][access_ips.AccessIPs.v6_key], '')
        self.assertEqual(
            resp_obj.obj['servers'][1][access_ips.AccessIPs.v4_key], '')
        self.assertEqual(
            resp_obj.obj['servers'][1][access_ips.AccessIPs.v6_key], '')

    def test_update(self):
        self._test_with_access_ips(self.controller.update, {'id': 'fake',
                                                            'body': {}})

    def test_update_without_access_ips(self):
        self._test_without_access_ips(self.controller.update, {'id': 'fake',
                                                               'body': {}})

    def test_rebuild(self):
        self._test_with_access_ips(self.controller.rebuild, {'id': 'fake',
                                                             'body': {}})

    def test_rebuild_without_access_ips(self):
        self._test_without_access_ips(self.controller.rebuild, {'id': 'fake',
                                                                'body': {}})


class AccessIPsXmlSerializeTest(test.TestCase):
    v4_xml_key = '{%s}access_ip_v4' % access_ips.AccessIPs.namespace
    v6_xml_key = '{%s}access_ip_v6' % access_ips.AccessIPs.namespace

    def setUp(self):
        super(AccessIPsXmlSerializeTest, self).setUp()

    def test_access_ip(self):
        server = {"server": {'id': 'fake',
                             access_ips.AccessIPs.v4_key: '1.1.1.1',
                             access_ips.AccessIPs.v6_key: 'fe80::'}}
        serializer = servers.ServerTemplate()
        serializer.attach(access_ips.AccessIPTemplate())
        output = serializer.serialize(server)
        root = etree.XML(output)
        access_ipv4_node = root.get(
            AccessIPsXmlSerializeTest.v4_xml_key)
        access_ipv6_node = root.get(
            AccessIPsXmlSerializeTest.v6_xml_key)
        self.assertEqual(access_ipv4_node, '1.1.1.1')
        self.assertEqual(access_ipv6_node, 'fe80::')

    def test_access_ip_with_empty(self):
        server = {"server": {'id': 'fake',
                             access_ips.AccessIPs.v4_key: '',
                             access_ips.AccessIPs.v6_key: ''}}
        serializer = servers.ServerTemplate()
        serializer.attach(access_ips.AccessIPTemplate())
        output = serializer.serialize(server)
        root = etree.XML(output)
        access_ipv4_node = root.get(
            AccessIPsXmlSerializeTest.v4_xml_key)
        access_ipv6_node = root.get(
            AccessIPsXmlSerializeTest.v6_xml_key)
        self.assertEqual(access_ipv4_node, '')
        self.assertEqual(access_ipv6_node, '')

    def test_access_ips(self):
        server = {"servers": [{'id': 'fake1',
                               access_ips.AccessIPs.v4_key: '1.1.1.1',
                               access_ips.AccessIPs.v6_key: 'fe80::'},
                              {'id': 'fake2',
                               access_ips.AccessIPs.v4_key: '1.1.1.2',
                               access_ips.AccessIPs.v6_key: 'fe81::'}]}
        serializer = servers.ServersTemplate()
        serializer.attach(access_ips.AccessIPsTemplate())
        output = serializer.serialize(server)
        root = etree.XML(output)
        server_nodes = root.getchildren()
        access_ipv4_node = server_nodes[0].get(
            AccessIPsXmlSerializeTest.v4_xml_key)
        access_ipv6_node = server_nodes[0].get(
            AccessIPsXmlSerializeTest.v6_xml_key)
        self.assertEqual(access_ipv4_node, '1.1.1.1')
        self.assertEqual(access_ipv6_node, 'fe80::')
        access_ipv4_node = server_nodes[1].get(
            AccessIPsXmlSerializeTest.v4_xml_key)
        access_ipv6_node = server_nodes[1].get(
            AccessIPsXmlSerializeTest.v6_xml_key)
        self.assertEqual(access_ipv4_node, '1.1.1.2')
        self.assertEqual(access_ipv6_node, 'fe81::')

    def test_access_ips_with_empty(self):
        server = {"servers": [{'id': 'fake1',
                               access_ips.AccessIPs.v4_key: '',
                               access_ips.AccessIPs.v6_key: ''},
                              {'id': 'fake2',
                               access_ips.AccessIPs.v4_key: '',
                               access_ips.AccessIPs.v6_key: ''}]}
        serializer = servers.ServersTemplate()
        serializer.attach(access_ips.AccessIPsTemplate())
        output = serializer.serialize(server)
        root = etree.XML(output)
        server_nodes = root.getchildren()
        access_ipv4_node = server_nodes[0].get(
            AccessIPsXmlSerializeTest.v4_xml_key)
        access_ipv6_node = server_nodes[0].get(
            AccessIPsXmlSerializeTest.v6_xml_key)
        self.assertEqual(access_ipv4_node, '')
        self.assertEqual(access_ipv6_node, '')
        access_ipv4_node = server_nodes[1].get(
            AccessIPsXmlSerializeTest.v4_xml_key)
        access_ipv6_node = server_nodes[1].get(
            AccessIPsXmlSerializeTest.v6_xml_key)
        self.assertEqual(access_ipv4_node, '')
        self.assertEqual(access_ipv6_node, '')


class AccessIPsXmlDeserializeTest(test.TestCase):
    def setUp(self):
        super(AccessIPsXmlDeserializeTest, self).setUp()
        self.access_ip_ext = access_ips.AccessIPs(None)

    def _test(self, func):
        server = (
            '<server xmlns:os-access-ips='
            '"http://docs.openstack.org/compute/ext/os-access-ips/api/v3" '
            'xmlns:atom="http://www.w3.org/2005/Atom" '
            'xmlns="http://docs.openstack.org/compute/api/v1.1" '
            'id="fake1" os-access-ips:access_ip_v4="1.1.1.1" '
            'os-access-ips:access_ip_v6="fe80::">'
            '</server>')
        doc = minidom.parseString(server)
        server_dict = {}
        func(doc.documentElement, server_dict)
        self.assertEqual(server_dict[access_ips.AccessIPs.v4_key], '1.1.1.1')
        self.assertEqual(server_dict[access_ips.AccessIPs.v6_key], 'fe80::')

    def _test_with_empty(self, func):
        server = (
            '<server xmlns:os-access-ips='
            '"http://docs.openstack.org/compute/ext/os-access-ips/api/v3" '
            'xmlns:atom="http://www.w3.org/2005/Atom" '
            'xmlns="http://docs.openstack.org/compute/api/v1.1" '
            'id="fake1" os-access-ips:access_ip_v4="" '
            'os-access-ips:access_ip_v6="">'
            '</server>')
        doc = minidom.parseString(server)
        server_dict = {}
        func(doc.documentElement, server_dict)
        self.assertIsNone(server_dict[access_ips.AccessIPs.v4_key])
        self.assertIsNone(server_dict[access_ips.AccessIPs.v6_key])

    def test_server_create(self):
        self._test(self.access_ip_ext.server_xml_extract_server_deserialize)

    def test_server_create_with_empty(self):
        self._test_with_empty(
            self.access_ip_ext.server_xml_extract_server_deserialize)

    def test_server_rebuild(self):
        self._test(self.access_ip_ext.server_xml_extract_rebuild_deserialize)

    def test_server_rebuild_with_empty(self):
        self._test_with_empty(
            self.access_ip_ext.server_xml_extract_rebuild_deserialize)
