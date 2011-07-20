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
import json
import unittest
from xml.dom import minidom

import stubout
import webob

from nova import exception
from nova import flags
from nova import test
from nova import utils
import nova.api.openstack
from nova.api.openstack import servers
from nova.api.openstack.contrib import createserverext
import nova.compute.api

import nova.scheduler.api
import nova.image.fake
import nova.rpc
from nova.tests.api.openstack import fakes

FLAGS = flags.FLAGS
FLAGS.verbose = True

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def fake_gen_uuid():
    return FAKE_UUID


def return_server_by_id(context, id):
    return stub_instance(id)


def return_server_by_uuid(context, uuid):
    id = 1
    return stub_instance(id, uuid=uuid)


def return_virtual_interface_by_instance(interfaces):
    def _return_virtual_interface_by_instance(context, instance_id):
        return interfaces
    return _return_virtual_interface_by_instance


def return_virtual_interface_instance_nonexistant(interfaces):
    def _return_virtual_interface_by_instance(context, instance_id):
        raise exception.InstanceNotFound(instance_id=instance_id)
    return _return_virtual_interface_by_instance


def return_server_with_addresses(private, public):
    def _return_server(context, id):
        return stub_instance(id, private_address=private,
                             public_addresses=public)
    return _return_server


def return_server_with_interfaces(interfaces):
    def _return_server(context, id):
        return stub_instance(id, interfaces=interfaces)
    return _return_server


def return_server_with_power_state(power_state):
    def _return_server(context, id):
        return stub_instance(id, power_state=power_state)
    return _return_server


def return_servers(context, user_id=1):
    return [stub_instance(i, user_id) for i in xrange(5)]


def return_servers_by_reservation(context, reservation_id=""):
    return [stub_instance(i, reservation_id) for i in xrange(5)]


def return_servers_by_reservation_empty(context, reservation_id=""):
    return []


def return_servers_from_child_zones_empty(*args, **kwargs):
    return []


def return_servers_from_child_zones(*args, **kwargs):
    class Server(object):
        pass

    zones = []
    for zone in xrange(3):
        servers = []
        for server_id in xrange(5):
            server = Server()
            server._info = stub_instance(server_id, reservation_id="child")
            servers.append(server)

        zones.append(("Zone%d" % zone, servers))
    return zones


def return_security_group(context, instance_id, security_group_id):
    pass


def instance_update(context, instance_id, kwargs):
    return stub_instance(instance_id)


def instance_addresses(context, instance_id):
    return None


def stub_instance(id, user_id=1, private_address=None, public_addresses=None,
                  host=None, power_state=0, reservation_id="",
                  uuid=FAKE_UUID, interfaces=None):
    metadata = []
    metadata.append(InstanceMetadata(key='seq', value=id))

    if interfaces is None:
        interfaces = []

    inst_type = instance_types.get_instance_type_by_flavor_id(1)

    if public_addresses is None:
        public_addresses = list()

    if host is not None:
        host = str(host)

    # ReservationID isn't sent back, hack it in there.
    server_name = "server%s" % id
    if reservation_id != "":
        server_name = "reservation_%s" % (reservation_id, )

    instance = {
        "id": int(id),
        "admin_pass": "",
        "user_id": user_id,
        "project_id": "",
        "image_ref": "10",
        "kernel_id": "",
        "ramdisk_id": "",
        "launch_index": 0,
        "key_name": "",
        "key_data": "",
        "state": power_state,
        "state_description": "",
        "memory_mb": 0,
        "vcpus": 0,
        "local_gb": 0,
        "hostname": "",
        "host": host,
        "instance_type": dict(inst_type),
        "user_data": "",
        "reservation_id": reservation_id,
        "mac_address": "",
        "scheduled_at": utils.utcnow(),
        "launched_at": utils.utcnow(),
        "terminated_at": utils.utcnow(),
        "availability_zone": "",
        "display_name": server_name,
        "display_description": "",
        "locked": False,
        "metadata": metadata,
        "uuid": uuid,
        "virtual_interfaces": interfaces}

    instance["fixed_ips"] = {
        "address": private_address,
        "floating_ips": [{"address":ip} for ip in public_addresses]}

    return instance


def fake_compute_api(cls, req, id):
    return True


def find_host(self, context, instance_id):
    return "nova"


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance_id, password):
        self.instance_id = instance_id
        self.password = password


class CreateserverextTest(test.TestCase):

    def setUp(self):
        super(CreateserverextTest, self).setUp()
        self.controller = createserverext.CreateServerExtController()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_auth(self.stubs)
        fakes.stub_out_image_service(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        self.allow_admin = FLAGS.allow_admin_api

    def tearDown(self):
        self.stubs.UnsetAll()
        FLAGS.allow_admin_api = self.allow_admin
        super(CreateserverextTest, self).tearDown()

    def _setup_mock_compute_api(self):

        class MockComputeAPI(nova.compute.API):

            def __init__(self):
                self.injected_files = None
                self.networks = None

            def create(self, *args, **kwargs):
                if 'injected_files' in kwargs:
                    self.injected_files = kwargs['injected_files']
                else:
                    self.injected_files = None

                if 'requested_networks' in kwargs:
                    self.networks = kwargs['requested_networks']
                else:
                    self.networks = None
                return [{'id': '1234', 'display_name': 'fakeinstance',
                         'uuid': FAKE_UUID}]

            def set_admin_password(self, *args, **kwargs):
                pass

        def make_stub_method(canned_return):
            def stub_method(*args, **kwargs):
                return canned_return
            return stub_method

        compute_api = MockComputeAPI()
        self.stubs.Set(nova.compute, 'API', make_stub_method(compute_api))
        self.stubs.Set(
            createserverext.CreateInstanceHelperEx,
            '_get_kernel_ramdisk_from_image', make_stub_method((1, 1)))
        return compute_api

    def _create_personality_request_dict(self, personality_files):
        server = {}
        server['name'] = 'new-server-test'
        server['imageRef'] = 1
        server['flavorRef'] = 1
        if personality_files is not None:
            personalities = []
            for path, contents in personality_files:
                personalities.append({'path': path, 'contents': contents})
            server['personality'] = personalities
        return {'server': server}

    def _create_networks_request_dict(self, networks):
        server = {}
        server['name'] = 'new-server-test'
        server['imageRef'] = 1
        server['flavorRef'] = 1
        if networks is not None:
            network_list = []
            for id, fixed_ip in networks:
                network_list.append({'id': id, 'fixed_ip': fixed_ip})
            server['networks'] = network_list
        return {'server': server}

    def _get_create_request_json(self, body_dict):
        req = webob.Request.blank('/v1.1/os-create-server-ext')
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
            '<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"',
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
                item = (network['id'], network['fixed_ip'])
                body_parts.append('<network id="%s" fixed_ip="%s"></network>'
                                  % item)
            body_parts.append('</networks>')
        body_parts.append('</server>')
        return ''.join(body_parts)

    def _get_create_request_xml(self, body_dict):
        req = webob.Request.blank('/v1.1/os-create-server-ext')
        req.content_type = 'application/xml'
        req.accept = 'application/xml'
        req.method = 'POST'
        req.body = self._format_xml_request_body(body_dict)
        return req

    def _create_instance_with_personality_json(self, personality):
        body_dict = self._create_personality_request_dict(personality)
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        return request, response, compute_api.injected_files

    def _create_instance_with_personality_xml(self, personality):
        body_dict = self._create_personality_request_dict(personality)
        request = self._get_create_request_xml(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        return request, response, compute_api.injected_files

    def _create_instance_with_networks_json(self, networks):
        body_dict = self._create_networks_request_dict(networks)
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        return request, response, compute_api.networks

    def _create_instance_with_networks_xml(self, networks):
        body_dict = self._create_networks_request_dict(networks)
        request = self._get_create_request_xml(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        return request, response, compute_api.networks

    def test_create_instance_with_no_personality(self):
        request, response, injected_files = \
                self._create_instance_with_personality_json(personality=None)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(injected_files, [])

    def test_create_instance_with_no_personality_xml(self):
        request, response, injected_files = \
                self._create_instance_with_personality_xml(personality=None)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(injected_files, [])

    def test_create_instance_with_personality(self):
        path = '/my/file/path'
        contents = '#!/bin/bash\necho "Hello, World!"\n'
        b64contents = base64.b64encode(contents)
        personality = [(path, b64contents)]
        request, response, injected_files = \
            self._create_instance_with_personality_json(personality)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(injected_files, [(path, contents)])

    def test_create_instance_with_personality_xml(self):
        path = '/my/file/path'
        contents = '#!/bin/bash\necho "Hello, World!"\n'
        b64contents = base64.b64encode(contents)
        personality = [(path, b64contents)]
        request, response, injected_files = \
            self._create_instance_with_personality_xml(personality)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(injected_files, [(path, contents)])

    def test_create_instance_with_personality_no_path(self):
        personality = [('/remove/this/path',
            base64.b64encode('my\n\file\ncontents'))]
        body_dict = self._create_personality_request_dict(personality)
        del body_dict['server']['personality'][0]['path']
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.injected_files, None)

    def _test_create_instance_with_personality_no_path_xml(self):
        personality = [('/remove/this/path',
            base64.b64encode('my\n\file\ncontents'))]
        body_dict = self._create_personality_request_dict(personality)
        request = self._get_create_request_xml(body_dict)
        request.body = request.body.replace(' path="/remove/this/path"', '')
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.injected_files, None)

    def test_create_instance_with_personality_no_contents(self):
        personality = [('/test/path',
            base64.b64encode('remove\nthese\ncontents'))]
        body_dict = self._create_personality_request_dict(personality)
        del body_dict['server']['personality'][0]['contents']
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.injected_files, None)

    def test_create_instance_with_personality_not_a_list(self):
        personality = [('/test/path', base64.b64encode('test\ncontents\n'))]
        body_dict = self._create_personality_request_dict(personality)
        body_dict['server']['personality'] = \
            body_dict['server']['personality'][0]
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.injected_files, None)

    def test_create_instance_with_personality_with_non_b64_content(self):
        path = '/my/file/path'
        contents = '#!/bin/bash\necho "Oh no!"\n'
        personality = [(path, contents)]
        request, response, injected_files = \
            self._create_instance_with_personality_json(personality)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(injected_files, None)

    def test_create_instance_with_null_personality(self):
        personality = None
        body_dict = self._create_personality_request_dict(personality)
        body_dict['server']['personality'] = None
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 200)

    def test_create_instance_with_three_personalities(self):
        files = [
            ('/etc/sudoers', 'ALL ALL=NOPASSWD: ALL\n'),
            ('/etc/motd', 'Enjoy your root access!\n'),
            ('/etc/dovecot.conf', 'dovecot\nconfig\nstuff\n'),
            ]
        personality = []
        for path, content in files:
            personality.append((path, base64.b64encode(content)))
        request, response, injected_files = \
            self._create_instance_with_personality_json(personality)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(injected_files, files)

    def test_create_instance_personality_empty_content(self):
        path = '/my/file/path'
        contents = ''
        personality = [(path, contents)]
        request, response, injected_files = \
            self._create_instance_with_personality_json(personality)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(injected_files, [(path, contents)])

    def test_create_instance_admin_pass_json(self):
        request, response, dummy = \
            self._create_instance_with_personality_json(None)
        self.assertEquals(response.status_int, 200)
        response = json.loads(response.body)
        self.assertTrue('adminPass' in response['server'])
        self.assertEqual(16, len(response['server']['adminPass']))

    def test_create_instance_admin_pass_xml(self):
        request, response, dummy = \
            self._create_instance_with_personality_xml(None)
        self.assertEquals(response.status_int, 200)
        dom = minidom.parseString(response.body)
        server = dom.childNodes[0]
        self.assertEquals(server.nodeName, 'server')
        self.assertEqual(16, len(server.getAttribute('adminPass')))

    def test_create_instance_with_no_networks(self):
        request, response, networks = \
                self._create_instance_with_networks_json(networks=None)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(networks, None)

    def test_create_instance_with_no_networks_xml(self):
        request, response, networks = \
                self._create_instance_with_networks_xml(networks=None)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(networks, None)

    def test_create_instance_with_one_network(self):
        id = 1
        fixed_ip = '10.0.1.12'
        networks = [(id, fixed_ip)]
        request, response, networks = \
            self._create_instance_with_networks_json(networks)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(networks, [(id, fixed_ip)])

    def test_create_instance_with_one_network_xml(self):
        id = 1
        fixed_ip = '10.0.1.12'
        networks = [(id, fixed_ip)]
        request, response, networks = \
            self._create_instance_with_networks_xml(networks)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(networks, [(id, fixed_ip)])

    def test_create_instance_with_two_networks(self):
        networks = [(1, '10.0.1.12'), (2, '10.0.2.12')]
        request, response, networks = \
            self._create_instance_with_networks_json(networks)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(networks, [(1, '10.0.1.12'), (2, '10.0.2.12')])

    def test_create_instance_with_two_networks_xml(self):
        networks = [(1, '10.0.1.12'), (2, '10.0.2.12')]
        request, response, networks = \
            self._create_instance_with_networks_xml(networks)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(networks, [(1, '10.0.1.12'), (2, '10.0.2.12')])

    def test_create_instance_with_duplicate_networks(self):
        networks = [(1, '10.0.1.12'), (1, '10.0.2.12')]
        request, response, networks = \
            self._create_instance_with_networks_json(networks)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_duplicate_networks_xml(self):
        networks = [(1, '10.0.1.12'), (1, '10.0.2.12')]
        request, response, networks = \
            self._create_instance_with_networks_xml(networks)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_no_id(self):
        networks = [(1, '10.0.1.12')]
        body_dict = self._create_networks_request_dict(networks)
        del body_dict['server']['networks'][0]['id']
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.networks, None)

    def test_create_instance_with_network_no_id_xml(self):
        networks = [(1, '10.0.1.12')]
        body_dict = self._create_networks_request_dict(networks)
        request = self._get_create_request_xml(body_dict)
        request.body = request.body.replace(' id="1"', '')
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(compute_api.networks, None)

    def test_create_instance_with_network_invalid_id(self):
        networks = [('asd123', '10.0.1.12')]
        request, response, networks = \
            self._create_instance_with_networks_json(networks)
        self.assertEquals(response.status_int, 400)
        self.assertEquals(networks, None)

    def test_create_instance_with_network_invalid_id_xml(self):
        networks = [('asd123', '10.0.1.12')]
        request, response, networks = \
            self._create_instance_with_networks_xml(networks)
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
        networks = [(1, '10.0.1.12')]
        body_dict = self._create_networks_request_dict(networks)
        del body_dict['server']['networks'][0]['fixed_ip']
        request = self._get_create_request_json(body_dict)
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(compute_api.networks, [(1, None)])

    def test_create_instance_with_network_no_fixed_ip_xml(self):
        networks = [(1, '10.0.1.12')]
        body_dict = self._create_networks_request_dict(networks)
        request = self._get_create_request_xml(body_dict)
        request.body = request.body.replace(' fixed_ip="10.0.1.12"', '')
        compute_api, response = \
            self._run_create_instance_with_mock_compute_api(request)
        self.assertEquals(response.status_int, 200)
        self.assertEquals(compute_api.networks, [(1, None)])
