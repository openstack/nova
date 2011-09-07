# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

import base64
import datetime
import json
import unittest
from xml.dom import minidom

import stubout
import webob

from nova import db
from nova import exception
from nova import flags
from nova import test
import nova.api.openstack
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS
FLAGS.verbose = True

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

FAKE_NETWORKS = [('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '10.0.1.12'),
                 ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '10.0.2.12')]

DUPLICATE_NETWORKS = [('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '10.0.1.12'),
                      ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '10.0.1.12')]

INVALID_NETWORKS = [('invalid', 'invalid-ip-address')]

INSTANCE = {
             "id": 1,
             "display_name": "test_server",
             "uuid": FAKE_UUID,
             "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
             "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
             "security_groups": [{"id": 1, "name": "test"}]
        }


def return_server_by_id(context, id, session=None):
    INSTANCE['id'] = id
    return INSTANCE


def return_security_group_non_existing(context, project_id, group_name):
    raise exception.SecurityGroupNotFoundForProject(project_id=project_id,
                                                 security_group_id=group_name)


def return_security_group_get_by_name(context, project_id, group_name):
    return {'id': 1, 'name': group_name}


def return_security_group_get(context, security_group_id, session):
    return {'id': security_group_id}


def return_instance_add_security_group(context, instance_id,
                                       security_group_id):
    pass


class CreateserverextTest(test.TestCase):

    def setUp(self):
        super(CreateserverextTest, self).setUp()

    def tearDown(self):
        super(CreateserverextTest, self).tearDown()

    def _setup_mock_compute_api(self):

        class MockComputeAPI(nova.compute.API):

            def __init__(self):
                self.injected_files = None
                self.networks = None
                self.user_data = None
                self.db = db

            def create(self, *args, **kwargs):
                if 'injected_files' in kwargs:
                    self.injected_files = kwargs['injected_files']
                else:
                    self.injected_files = None

                if 'requested_networks' in kwargs:
                    self.networks = kwargs['requested_networks']
                else:
                    self.networks = None

                if 'user_data' in kwargs:
                    self.user_data = kwargs['user_data']

                return [{'id': '1234', 'display_name': 'fakeinstance',
                         'uuid': FAKE_UUID,
                         'user_id': 'fake',
                         'project_id': 'fake',
                         'created_at': "",
                         'updated_at': ""}]

            def set_admin_password(self, *args, **kwargs):
                pass

        def make_stub_method(canned_return):
            def stub_method(*args, **kwargs):
                return canned_return
            return stub_method

        compute_api = MockComputeAPI()
        self.stubs.Set(nova.compute, 'API', make_stub_method(compute_api))
        self.stubs.Set(
            nova.api.openstack.create_instance_helper.CreateInstanceHelper,
            '_get_kernel_ramdisk_from_image', make_stub_method((1, 1)))
        return compute_api

    def _create_security_group_request_dict(self, security_groups):
        server = {}
        server['name'] = 'new-server-test'
        server['imageRef'] = 1
        server['flavorRef'] = 1
        if security_groups is not None:
            sg_list = []
            for name in security_groups:
                sg_list.append({'name': name})
            server['security_groups'] = sg_list
        return {'server': server}

    def _create_networks_request_dict(self, networks):
        server = {}
        server['name'] = 'new-server-test'
        server['imageRef'] = 1
        server['flavorRef'] = 1
        if networks is not None:
            network_list = []
            for uuid, fixed_ip in networks:
                network_list.append({'uuid': uuid, 'fixed_ip': fixed_ip})
            server['networks'] = network_list
        return {'server': server}

    def _create_user_data_request_dict(self, user_data):
        server = {}
        server['name'] = 'new-server-test'
        server['imageRef'] = 1
        server['flavorRef'] = 1
        server['user_data'] = user_data
        return {'server': server}

    def _get_create_request_json(self, body_dict):
        req = webob.Request.blank('/v1.1/123/os-create-server-ext')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body_dict)
        return req

    def _run_create_instance_with_mock_compute_api(self, request):
        compute_api = self._setup_mock_compute_api()
        response = request.get_response(fakes.wsgi_app())
        return compute_api, response

    def _format_xml_request_body(self, body_dict):
        server = body_dict['server']
        body_parts = []
        body_parts.extend([
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.1"',
            ' name="%s" imageRef="%s" flavorRef="%s">' % (
                    server['name'], server['imageRef'], server['flavorRef'])])
        if 'metadata' in server:
            metadata = server['metadata']
            body_parts.append('<metadata>')
            for item in metadata.iteritems():
                body_parts.append('<meta key="%s">%s</meta>' % item)
            body_parts.append('</metadata>')
        if 'personality' in server:
            personalities = server['personality']
            body_parts.append('<personality>')
            for file in personalities:
                item = (file['path'], file['contents'])
                body_parts.append('<file path="%s">%s</file>' % item)
            body_parts.append('</personality>')
        if 'networks' in server:
            networks = server['networks']
            body_parts.append('<networks>')
            for network in networks:
                item = (network['uuid'], network['fixed_ip'])
                body_parts.append('<network uuid="%s" fixed_ip="%s"></network>'
                                  % item)
            body_parts.append('</networks>')
        body_parts.append('</server>')
        return ''.join(body_parts)

    def _get_create_request_xml(self, body_dict):
        req = webob.Request.blank('/v1.1/123/os-create-server-ext')
        req.content_type = 'application/xml'
        req.accept = 'application/xml'
        req.method = 'POST'
        req.body = self._format_xml_request_body(body_dict)
        return req

    def _create_instance_with_networks_json(self, networks):
        body_dict = self._create_networks_request_dict(networks)
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        return request, response, compute_api.networks

    def _create_instance_with_user_data_json(self, networks):
        body_dict = self._create_user_data_request_dict(networks)
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        return request, response, compute_api.user_data

    def _create_instance_with_networks_xml(self, networks):
        body_dict = self._create_networks_request_dict(networks)
        request = self._get_create_request_xml(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        return request, response, compute_api.networks

    def test_create_instance_with_no_networks(self):
        request, response, networks = \
                self._create_instance_with_networks_json(networks=None)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(networks, None)

    def test_create_instance_with_no_networks_xml(self):
        request, response, networks = \
                self._create_instance_with_networks_xml(networks=None)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(networks, None)

    def test_create_instance_with_one_network(self):
        request, response, networks = \
            self._create_instance_with_networks_json([FAKE_NETWORKS[0]])
        self.assertEquals(response.status_int, 202)
        self.assertEquals(networks, [FAKE_NETWORKS[0]])

    def test_create_instance_with_one_network_xml(self):
        request, response, networks = \
            self._create_instance_with_networks_xml([FAKE_NETWORKS[0]])
        self.assertEquals(response.status_int, 202)
        self.assertEquals(networks, [FAKE_NETWORKS[0]])

    def test_create_instance_with_two_networks(self):
        request, response, networks = \
            self._create_instance_with_networks_json(FAKE_NETWORKS)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(networks, FAKE_NETWORKS)

    def test_create_instance_with_two_networks_xml(self):
        request, response, networks = \
            self._create_instance_with_networks_xml(FAKE_NETWORKS)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(networks, FAKE_NETWORKS)

    def test_create_instance_with_duplicate_networks(self):
        request, response, networks = \
            self._create_instance_with_networks_json(DUPLICATE_NETWORKS)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_duplicate_networks_xml(self):
        request, response, networks = \
            self._create_instance_with_networks_xml(DUPLICATE_NETWORKS)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_no_id(self):
        body_dict = self._create_networks_request_dict([FAKE_NETWORKS[0]])
        del body_dict['server']['networks'][0]['uuid']
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.networks, None)

    def test_create_instance_with_network_no_id_xml(self):
        body_dict = self._create_networks_request_dict([FAKE_NETWORKS[0]])
        request = self._get_create_request_xml(body_dict)
        uuid = ' uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"'
        request.body = request.body.replace(uuid, '')
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.networks, None)

    def test_create_instance_with_network_invalid_id(self):
        request, response, networks = \
            self._create_instance_with_networks_json(INVALID_NETWORKS)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_invalid_id_xml(self):
        request, response, networks = \
            self._create_instance_with_networks_xml(INVALID_NETWORKS)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_empty_fixed_ip(self):
        networks = [('1', '')]
        request, response, networks = \
            self._create_instance_with_networks_json(networks)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_non_string_fixed_ip(self):
        networks = [('1', 12345)]
        request, response, networks = \
            self._create_instance_with_networks_json(networks)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_empty_fixed_ip_xml(self):
        networks = [('1', '')]
        request, response, networks = \
            self._create_instance_with_networks_xml(networks)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_no_fixed_ip(self):
        body_dict = self._create_networks_request_dict([FAKE_NETWORKS[0]])
        del body_dict['server']['networks'][0]['fixed_ip']
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(compute_api.networks,
                          [('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', None)])

    def test_create_instance_with_network_no_fixed_ip_xml(self):
        body_dict = self._create_networks_request_dict([FAKE_NETWORKS[0]])
        request = self._get_create_request_xml(body_dict)
        request.body = request.body.replace(' fixed_ip="10.0.1.12"', '')
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(compute_api.networks,
                          [('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', None)])

    def test_create_instance_with_userdata(self):
        user_data_contents = '#!/bin/bash\necho "Oh no!"\n'
        user_data_contents = base64.b64encode(user_data_contents)
        request, response, user_data = \
                self._create_instance_with_user_data_json(user_data_contents)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(user_data, user_data_contents)

    def test_create_instance_with_userdata_none(self):
        user_data_contents = None
        request, response, user_data = \
                self._create_instance_with_user_data_json(user_data_contents)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(user_data, user_data_contents)

    def test_create_instance_with_userdata_with_non_b64_content(self):
        user_data_contents = '#!/bin/bash\necho "Oh no!"\n'
        request, response, user_data = \
                self._create_instance_with_user_data_json(user_data_contents)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(user_data, None)

    def test_create_instance_with_security_group_json(self):
        security_groups = ['test', 'test1']
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group_get_by_name)
        self.stubs.Set(nova.db.api, 'instance_add_security_group',
                       return_instance_add_security_group)
        body_dict = self._create_security_group_request_dict(security_groups)
        request = self._get_create_request_json(body_dict)
        response = request.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 202)

    def test_get_server_by_id_verify_security_groups_json(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_by_id)
        req = webob.Request.blank('/v1.1/123/os-create-server-ext/1')
        req.headers['Content-Type'] = 'application/json'
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 200)
        res_dict = json.loads(response.body)
        expected_security_group = [{"name": "test"}]
        self.assertEquals(res_dict['server']['security_groups'],
                          expected_security_group)

    def test_get_server_by_id_verify_security_groups_xml(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_by_id)
        req = webob.Request.blank('/v1.1/123/os-create-server-ext/1')
        req.headers['Accept'] = 'application/xml'
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 200)
        dom = minidom.parseString(response.body)
        server = dom.childNodes[0]
        sec_groups = server.getElementsByTagName('security_groups')[0]
        sec_group = sec_groups.getElementsByTagName('security_group')[0]
        self.assertEqual(INSTANCE['security_groups'][0]['name'],
                         sec_group.getAttribute("name"))
