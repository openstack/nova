# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
# Copyright 2011 Piston Cloud Computing, Inc.
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
from lxml import etree
from xml.dom import minidom

import webob

from nova import context
from nova import db
from nova import exception
from nova import test
from nova import utils
import nova.api.openstack
from nova.api.openstack import create_instance_helper
from nova.api.openstack import servers
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
import nova.compute.api
from nova.compute import instance_types
from nova.compute import task_states
from nova.compute import vm_states
import nova.db.api
import nova.scheduler.api
from nova.db.sqlalchemy.models import Instance
from nova.db.sqlalchemy.models import InstanceMetadata
import nova.image.fake
import nova.rpc
from nova.tests.api.openstack import common
from nova.tests.api.openstack import fakes


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


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


def return_server_with_attributes(**kwargs):
    def _return_server(context, id):
        return stub_instance(id, **kwargs)
    return _return_server


def return_server_with_addresses(private, public):
    def _return_server(context, id):
        return stub_instance(id, private_address=private,
                             public_addresses=public)
    return _return_server


def return_server_with_state(vm_state, task_state=None):
    def _return_server(context, id):
        return stub_instance(id, vm_state=vm_state, task_state=task_state)
    return _return_server


def return_server_with_uuid_and_state(vm_state, task_state):
    def _return_server(context, id):
        return stub_instance(id,
                             uuid=FAKE_UUID,
                             vm_state=vm_state,
                             task_state=task_state)
    return _return_server


def return_servers(context, *args, **kwargs):
    return [stub_instance(i, 'fake', 'fake') for i in xrange(5)]


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


def instance_update(context, instance_id, values):
    return stub_instance(instance_id, name=values.get('display_name'))


def instance_addresses(context, instance_id):
    return None


def stub_instance(id, user_id='fake', project_id='fake', private_address=None,
                  public_addresses=None, host=None,
                  vm_state=None, task_state=None,
                  reservation_id="", uuid=FAKE_UUID, image_ref="10",
                  flavor_id="1", interfaces=None, name=None, key_name='',
                  access_ipv4=None, access_ipv6=None):
    metadata = []
    metadata.append(InstanceMetadata(key='seq', value=id))

    if interfaces is None:
        interfaces = []

    inst_type = instance_types.get_instance_type_by_flavor_id(int(flavor_id))

    if public_addresses is None:
        public_addresses = list()

    if host is not None:
        host = str(host)

    if key_name:
        key_data = 'FAKE'
    else:
        key_data = ''

    # ReservationID isn't sent back, hack it in there.
    server_name = name or "server%s" % id
    if reservation_id != "":
        server_name = "reservation_%s" % (reservation_id, )

    instance = {
        "id": int(id),
        "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
        "admin_pass": "",
        "user_id": user_id,
        "project_id": project_id,
        "image_ref": image_ref,
        "kernel_id": "",
        "ramdisk_id": "",
        "launch_index": 0,
        "key_name": key_name,
        "key_data": key_data,
        "vm_state": vm_state or vm_states.BUILDING,
        "task_state": task_state,
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
        "access_ip_v4": access_ipv4,
        "access_ip_v6": access_ipv6,
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


class ServersTest(test.TestCase):
    def setUp(self):
        self.maxDiff = None
        super(ServersTest, self).setUp()
        self.flags(verbose=True)
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_image_service(self.stubs)
        self.stubs.Set(utils, 'gen_uuid', fake_gen_uuid)
        self.stubs.Set(nova.db.api, 'instance_get_all_by_filters',
                return_servers)
        self.stubs.Set(nova.db.api, 'instance_get', return_server_by_id)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_by_uuid)
        self.stubs.Set(nova.db.api, 'instance_get_all_by_project',
                       return_servers)
        self.stubs.Set(nova.db.api, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(nova.db.api, 'instance_update', instance_update)
        self.stubs.Set(nova.db.api, 'instance_get_fixed_addresses',
                       instance_addresses)
        self.stubs.Set(nova.db.api, 'instance_get_floating_address',
                       instance_addresses)
        self.stubs.Set(nova.compute.API, 'pause', fake_compute_api)
        self.stubs.Set(nova.compute.API, 'unpause', fake_compute_api)
        self.stubs.Set(nova.compute.API, 'suspend', fake_compute_api)
        self.stubs.Set(nova.compute.API, 'resume', fake_compute_api)
        self.stubs.Set(nova.compute.API, "get_diagnostics", fake_compute_api)
        self.stubs.Set(nova.compute.API, "get_actions", fake_compute_api)

        self.webreq = common.webob_factory('/v1.0/servers')
        self.config_drive = None

    def test_get_server_by_id(self):
        req = webob.Request.blank('/v1.0/servers/1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server1')

    def test_get_server_by_uuid(self):
        """
        The steps involved with resolving a UUID are pretty complicated;
        here's what's happening in this scenario:

        1. Show is calling `routing_get`

        2. `routing_get` is wrapped by `reroute_compute` which does the work
           of resolving requests to child zones.

        3. `reroute_compute` looks up the UUID by hitting the stub
           (returns_server_by_uuid)

        4. Since the stub return that the record exists, `reroute_compute`
           considers the request to be 'zone local', so it replaces the UUID
           in the argument list with an integer ID and then calls the inner
           function ('get').

        5. The call to `get` hits the other stub 'returns_server_by_id` which
           has the UUID set to FAKE_UUID

        So, counterintuitively, we call `get` twice on the `show` command.
        """
        req = webob.Request.blank('/v1.0/servers/%s' % FAKE_UUID)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['uuid'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server1')

    def test_get_server_by_id_v1_1(self):
        image_bookmark = "http://localhost/fake/images/10"
        flavor_ref = "http://localhost/v1.1/fake/flavors/1"
        flavor_id = "1"
        flavor_bookmark = "http://localhost/fake/flavors/1"

        public_ip = '192.168.0.3'
        private_ip = '172.19.0.1'
        interfaces = [
            {
                'network': {'label': 'public'},
                'fixed_ips': [
                    {'address': public_ip},
                ],
            },
            {
                'network': {'label': 'private'},
                'fixed_ips': [
                    {'address': private_ip},
                ],
            },
        ]
        new_return_server = return_server_with_attributes(
            interfaces=interfaces)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        req = webob.Request.blank('/v1.1/fake/servers/1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        expected_server = {
            "server": {
                "id": 1,
                "uuid": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "server1",
                "status": "BUILD",
                "accessIPv4": "",
                "accessIPv6": "",
                "hostId": '',
                "key_name": '',
                "image": {
                    "id": "10",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    "public": [
                        {
                            "version": 4,
                            "addr": public_ip,
                        },
                    ],
                    "private": [
                        {
                            "version": 4,
                            "addr": private_ip,
                        },
                    ],
                },
                "metadata": {
                    "seq": "1",
                },
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        #FIXME(wwolf) Do we want the links to be id or uuid?
                        "href": "http://localhost/v1.1/fake/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/1",
                    },
                ],
            }
        }

        self.assertDictMatch(res_dict, expected_server)

    def test_get_server_by_id_v1_1_xml(self):
        image_bookmark = "http://localhost/fake/images/10"
        flavor_ref = "http://localhost/v1.1/fake/flavors/1"
        flavor_id = "1"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        server_href = "http://localhost/v1.1/fake/servers/1"
        server_bookmark = "http://localhost/fake/servers/1"

        public_ip = '192.168.0.3'
        private_ip = '172.19.0.1'
        interfaces = [
            {
                'network': {'label': 'public'},
                'fixed_ips': [
                    {'address': public_ip},
                ],
            },
            {
                'network': {'label': 'private'},
                'fixed_ips': [
                    {'address': private_ip},
                ],
            },
        ]
        new_return_server = return_server_with_attributes(
            interfaces=interfaces)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        req = webob.Request.blank('/v1.1/fake/servers/1')
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        actual = minidom.parseString(res.body.replace('  ', ''))
        expected_uuid = FAKE_UUID
        expected_updated = "2010-11-11T11:00:00Z"
        expected_created = "2010-10-10T12:00:00Z"
        expected = minidom.parseString("""
        <server id="1"
                uuid="%(expected_uuid)s"
                userId="fake"
                tenantId="fake"
                xmlns="http://docs.openstack.org/compute/api/v1.1"
                xmlns:atom="http://www.w3.org/2005/Atom"
                name="server1"
                updated="%(expected_updated)s"
                created="%(expected_created)s"
                hostId=""
                status="BUILD"
                accessIPv4=""
                accessIPv6=""
                progress="0">
            <atom:link href="%(server_href)s" rel="self"/>
            <atom:link href="%(server_bookmark)s" rel="bookmark"/>
            <image id="10">
                <atom:link rel="bookmark" href="%(image_bookmark)s"/>
            </image>
            <flavor id="1">
                <atom:link rel="bookmark" href="%(flavor_bookmark)s"/>
            </flavor>
            <metadata>
                <meta key="seq">
                    1
                </meta>
            </metadata>
            <addresses>
                <network id="public">
                    <ip version="4" addr="%(public_ip)s"/>
                </network>
                <network id="private">
                    <ip version="4" addr="%(private_ip)s"/>
                </network>
            </addresses>
        </server>
        """.replace("  ", "") % (locals()))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_get_server_with_active_status_by_id_v1_1(self):
        image_bookmark = "http://localhost/fake/images/10"
        flavor_ref = "http://localhost/v1.1/fake/flavors/1"
        flavor_id = "1"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        private_ip = "192.168.0.3"
        public_ip = "1.2.3.4"

        interfaces = [
            {
                'network': {'label': 'public'},
                'fixed_ips': [
                    {'address': public_ip},
                ],
            },
            {
                'network': {'label': 'private'},
                'fixed_ips': [
                    {'address': private_ip},
                ],
            },
        ]
        new_return_server = return_server_with_attributes(
            interfaces=interfaces, vm_state=vm_states.ACTIVE)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        req = webob.Request.blank('/v1.1/fake/servers/1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        expected_server = {
            "server": {
                "id": 1,
                "uuid": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 100,
                "name": "server1",
                "status": "ACTIVE",
                "accessIPv4": "",
                "accessIPv6": "",
                "hostId": '',
                "key_name": '',
                "image": {
                    "id": "10",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                      {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    "public": [
                        {
                            "version": 4,
                            "addr": public_ip,
                        },
                    ],
                    "private": [
                        {
                            "version": 4,
                            "addr": private_ip,
                        },
                    ],
                },
                "metadata": {
                    "seq": "1",
                },
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/fake/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/1",
                    },
                ],
            }
        }

        self.assertDictMatch(res_dict, expected_server)

    def test_get_server_with_id_image_ref_by_id_v1_1(self):
        image_ref = "10"
        image_bookmark = "http://localhost/fake/images/10"
        flavor_ref = "http://localhost/v1.1/fake/flavors/1"
        flavor_id = "1"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        private_ip = "192.168.0.3"
        public_ip = "1.2.3.4"

        interfaces = [
            {
                'network': {'label': 'public'},
                'fixed_ips': [
                    {'address': public_ip},
                ],
            },
            {
                'network': {'label': 'private'},
                'fixed_ips': [
                    {'address': private_ip},
                ],
            },
        ]
        new_return_server = return_server_with_attributes(
            interfaces=interfaces, vm_state=vm_states.ACTIVE,
            image_ref=image_ref, flavor_id=flavor_id)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        req = webob.Request.blank('/v1.1/fake/servers/1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        expected_server = {
            "server": {
                "id": 1,
                "uuid": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 100,
                "name": "server1",
                "status": "ACTIVE",
                "accessIPv4": "",
                "accessIPv6": "",
                "hostId": '',
                "key_name": '',
                "image": {
                    "id": "10",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                      {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    "public": [
                        {
                            "version": 4,
                            "addr": public_ip,
                        },
                    ],
                    "private": [
                        {
                            "version": 4,
                            "addr": private_ip,
                        },
                    ],
                },
                "metadata": {
                    "seq": "1",
                },
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/fake/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/1",
                    },
                ],
            }
        }

        self.assertDictMatch(res_dict, expected_server)

    def test_get_server_by_id_with_addresses_xml(self):
        private = "192.168.0.3"
        public = ["1.2.3.4"]
        new_return_server = return_server_with_addresses(private, public)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1')
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        dom = minidom.parseString(res.body)
        server = dom.childNodes[0]
        self.assertEquals(server.nodeName, 'server')
        self.assertEquals(server.getAttribute('id'), '1')
        self.assertEquals(server.getAttribute('name'), 'server1')
        (public,) = server.getElementsByTagName('public')
        (ip,) = public.getElementsByTagName('ip')
        self.assertEquals(ip.getAttribute('addr'), '1.2.3.4')
        (private,) = server.getElementsByTagName('private')
        (ip,) = private.getElementsByTagName('ip')
        self.assertEquals(ip.getAttribute('addr'), '192.168.0.3')

    def test_get_server_by_id_with_addresses(self):
        private = "192.168.0.3"
        public = ["1.2.3.4"]
        new_return_server = return_server_with_addresses(private, public)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server1')
        addresses = res_dict['server']['addresses']
        self.assertEqual(len(addresses["public"]), len(public))
        self.assertEqual(addresses["public"][0], public[0])
        self.assertEqual(len(addresses["private"]), 1)
        self.assertEqual(addresses["private"][0], private)

    def test_get_server_addresses_v1_0(self):
        private = '192.168.0.3'
        public = ['1.2.3.4']
        new_return_server = return_server_with_addresses(private, public)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1/ips')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict, {
            'addresses': {'public': public, 'private': [private]}})

    def test_get_server_addresses_xml_v1_0(self):
        private_expected = "192.168.0.3"
        public_expected = ["1.2.3.4"]
        new_return_server = return_server_with_addresses(private_expected,
                                                         public_expected)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1/ips')
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        dom = minidom.parseString(res.body)
        (addresses,) = dom.childNodes
        self.assertEquals(addresses.nodeName, 'addresses')
        (public,) = addresses.getElementsByTagName('public')
        (ip,) = public.getElementsByTagName('ip')
        self.assertEquals(ip.getAttribute('addr'), public_expected[0])
        (private,) = addresses.getElementsByTagName('private')
        (ip,) = private.getElementsByTagName('ip')
        self.assertEquals(ip.getAttribute('addr'), private_expected)

    def test_get_server_addresses_public_v1_0(self):
        private = "192.168.0.3"
        public = ["1.2.3.4"]
        new_return_server = return_server_with_addresses(private, public)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1/ips/public')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict, {'public': public})

    def test_get_server_addresses_private_v1_0(self):
        private = "192.168.0.3"
        public = ["1.2.3.4"]
        new_return_server = return_server_with_addresses(private, public)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1/ips/private')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict, {'private': [private]})

    def test_get_server_addresses_public_xml_v1_0(self):
        private = "192.168.0.3"
        public = ["1.2.3.4"]
        new_return_server = return_server_with_addresses(private, public)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1/ips/public')
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        dom = minidom.parseString(res.body)
        (public_node,) = dom.childNodes
        self.assertEquals(public_node.nodeName, 'public')
        (ip,) = public_node.getElementsByTagName('ip')
        self.assertEquals(ip.getAttribute('addr'), public[0])

    def test_get_server_addresses_private_xml_v1_0(self):
        private = "192.168.0.3"
        public = ["1.2.3.4"]
        new_return_server = return_server_with_addresses(private, public)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        req = webob.Request.blank('/v1.0/servers/1/ips/private')
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        dom = minidom.parseString(res.body)
        (private_node,) = dom.childNodes
        self.assertEquals(private_node.nodeName, 'private')
        (ip,) = private_node.getElementsByTagName('ip')
        self.assertEquals(ip.getAttribute('addr'), private)

    # NOTE(bcwaldon): lp830817
    def test_get_server_by_id_malformed_networks_v1_1(self):
        ifaces = [
            {
                'network': None,
                'fixed_ips': [
                    {'address': '192.168.0.3'},
                    {'address': '192.168.0.4'},
                ],
            },
        ]
        new_return_server = return_server_with_attributes(interfaces=ifaces)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        req = webob.Request.blank('/v1.1/fake/servers/1')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server1')

    def test_get_server_by_id_with_addresses_v1_1(self):
        self.flags(use_ipv6=True)
        interfaces = [
            {
                'network': {'label': 'network_1'},
                'fixed_ips': [
                    {'address': '192.168.0.3'},
                    {'address': '192.168.0.4'},
                ],
            },
            {
                'network': {'label': 'network_2'},
                'fixed_ips': [
                    {'address': '172.19.0.1'},
                    {'address': '172.19.0.2'},
                ],
                'fixed_ipv6': '2001:4860::12',
            },
        ]
        new_return_server = return_server_with_attributes(
            interfaces=interfaces)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        req = webob.Request.blank('/v1.1/fake/servers/1')
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server1')
        addresses = res_dict['server']['addresses']
        expected = {
            'network_1': [
                {'addr': '192.168.0.3', 'version': 4},
                {'addr': '192.168.0.4', 'version': 4},
            ],
            'network_2': [
                {'addr': '172.19.0.1', 'version': 4},
                {'addr': '172.19.0.2', 'version': 4},
                {'addr': '2001:4860::12', 'version': 6},
            ],
        }

        self.assertEqual(addresses, expected)

    def test_get_server_by_id_with_addresses_v1_1_ipv6_disabled(self):
        self.flags(use_ipv6=False)
        interfaces = [
            {
                'network': {'label': 'network_1'},
                'fixed_ips': [
                    {'address': '192.168.0.3'},
                    {'address': '192.168.0.4'},
                ],
            },
            {
                'network': {'label': 'network_2'},
                'fixed_ips': [
                    {'address': '172.19.0.1'},
                    {'address': '172.19.0.2'},
                ],
                'fixed_ipv6': '2001:4860::12',
            },
        ]
        new_return_server = return_server_with_attributes(
            interfaces=interfaces)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        req = webob.Request.blank('/v1.1/fake/servers/1')
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server1')
        addresses = res_dict['server']['addresses']
        expected = {
            'network_1': [
                {'addr': '192.168.0.3', 'version': 4},
                {'addr': '192.168.0.4', 'version': 4},
            ],
            'network_2': [
                {'addr': '172.19.0.1', 'version': 4},
                {'addr': '172.19.0.2', 'version': 4},
            ],
        }

        self.assertEqual(addresses, expected)

    def test_get_server_addresses_v1_1(self):
        self.flags(use_ipv6=True)
        interfaces = [
            {
                'network': {'label': 'network_1'},
                'fixed_ips': [
                    {'address': '192.168.0.3'},
                    {'address': '192.168.0.4'},
                ],
            },
            {
                'network': {'label': 'network_2'},
                'fixed_ips': [
                    {
                        'address': '172.19.0.1',
                        'floating_ips': [
                            {'address': '1.2.3.4'},
                        ],
                    },
                    {'address': '172.19.0.2'},
                ],
                'fixed_ipv6': '2001:4860::12',
            },
        ]

        _return_vifs = return_virtual_interface_by_instance(interfaces)
        self.stubs.Set(nova.db.api,
                       'virtual_interface_get_by_instance',
                       _return_vifs)

        req = webob.Request.blank('/v1.1/fake/servers/1/ips')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        expected = {
            'addresses': {
                'network_1': [
                    {'version': 4, 'addr': '192.168.0.3'},
                    {'version': 4, 'addr': '192.168.0.4'},
                ],
                'network_2': [
                    {'version': 4, 'addr': '172.19.0.1'},
                    {'version': 4, 'addr': '1.2.3.4'},
                    {'version': 4, 'addr': '172.19.0.2'},
                    {'version': 6, 'addr': '2001:4860::12'},
                ],
            },
        }

        self.assertEqual(res_dict, expected)

    def test_get_server_addresses_single_network_v1_1(self):
        self.flags(use_ipv6=True)
        interfaces = [
            {
                'network': {'label': 'network_1'},
                'fixed_ips': [
                    {'address': '192.168.0.3'},
                    {'address': '192.168.0.4'},
                ],
            },
            {
                'network': {'label': 'network_2'},
                'fixed_ips': [
                    {
                        'address': '172.19.0.1',
                        'floating_ips': [
                            {'address': '1.2.3.4'},
                        ],
                    },
                    {'address': '172.19.0.2'},
                ],
                'fixed_ipv6': '2001:4860::12',
            },
        ]
        _return_vifs = return_virtual_interface_by_instance(interfaces)
        self.stubs.Set(nova.db.api,
                       'virtual_interface_get_by_instance',
                       _return_vifs)

        req = webob.Request.blank('/v1.1/fake/servers/1/ips/network_2')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        expected = {
            'network_2': [
                {'version': 4, 'addr': '172.19.0.1'},
                {'version': 4, 'addr': '1.2.3.4'},
                {'version': 4, 'addr': '172.19.0.2'},
                {'version': 6, 'addr': '2001:4860::12'},
            ],
        }
        self.assertEqual(res_dict, expected)

    def test_get_server_addresses_nonexistant_network_v1_1(self):
        _return_vifs = return_virtual_interface_by_instance([])
        self.stubs.Set(nova.db.api,
                       'virtual_interface_get_by_instance',
                       _return_vifs)

        req = webob.Request.blank('/v1.1/fake/servers/1/ips/network_0')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_server_addresses_nonexistant_server_v1_1(self):
        _return_vifs = return_virtual_interface_instance_nonexistant([])
        self.stubs.Set(nova.db.api,
                       'virtual_interface_get_by_instance',
                       _return_vifs)

        req = webob.Request.blank('/v1.1/fake/servers/600/ips')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_server_list(self):
        req = webob.Request.blank('/v1.0/servers')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(len(res_dict['servers']), 5)
        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s['id'], i)
            self.assertEqual(s['name'], 'server%d' % i)
            self.assertEqual(s.get('imageId', None), None)
            i += 1

    def test_get_server_list_with_reservation_id(self):
        self.stubs.Set(nova.db.api, 'instance_get_all_by_reservation',
                       return_servers_by_reservation)
        self.stubs.Set(nova.scheduler.api, 'call_zone_method',
                       return_servers_from_child_zones)
        req = webob.Request.blank('/v1.0/servers?reservation_id=foo')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        i = 0
        for s in res_dict['servers']:
            if '_is_precooked' in s:
                self.assertEqual(s.get('reservation_id'), 'child')
            else:
                self.assertEqual(s.get('name'), 'server%d' % i)
                i += 1

    def test_get_server_list_with_reservation_id_empty(self):
        self.stubs.Set(nova.db.api, 'instance_get_all_by_reservation',
                       return_servers_by_reservation_empty)
        self.stubs.Set(nova.scheduler.api, 'call_zone_method',
                       return_servers_from_child_zones_empty)
        req = webob.Request.blank('/v1.0/servers/detail?reservation_id=foo')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        i = 0
        for s in res_dict['servers']:
            if '_is_precooked' in s:
                self.assertEqual(s.get('reservation_id'), 'child')
            else:
                self.assertEqual(s.get('name'), 'server%d' % i)
                i += 1

    def test_get_server_list_with_reservation_id_details(self):
        self.stubs.Set(nova.db.api, 'instance_get_all_by_reservation',
                       return_servers_by_reservation)
        self.stubs.Set(nova.scheduler.api, 'call_zone_method',
                       return_servers_from_child_zones)
        req = webob.Request.blank('/v1.0/servers/detail?reservation_id=foo')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        i = 0
        for s in res_dict['servers']:
            if '_is_precooked' in s:
                self.assertEqual(s.get('reservation_id'), 'child')
            else:
                self.assertEqual(s.get('name'), 'server%d' % i)
                i += 1

    def test_get_server_list_v1_1(self):
        req = webob.Request.blank('/v1.1/fake/servers')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(len(res_dict['servers']), 5)
        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], i)
            self.assertEqual(s['name'], 'server%d' % i)
            self.assertEqual(s.get('image', None), None)

            expected_links = [
                {
                    "rel": "self",
                    "href": "http://localhost/v1.1/fake/servers/%s" % s['id'],
                },
                {
                    "rel": "bookmark",
                    "href": "http://localhost/fake/servers/%s" % s['id'],
                },
            ]

            self.assertEqual(s['links'], expected_links)

    def test_get_servers_with_limit(self):
        req = webob.Request.blank('/v1.0/servers?limit=3')
        res = req.get_response(fakes.wsgi_app())
        servers = json.loads(res.body)['servers']
        self.assertEqual([s['id'] for s in servers], [0, 1, 2])

        req = webob.Request.blank('/v1.0/servers?limit=aaa')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        self.assertTrue('limit' in res.body)

    def test_get_servers_with_offset(self):
        req = webob.Request.blank('/v1.0/servers?offset=2')
        res = req.get_response(fakes.wsgi_app())
        servers = json.loads(res.body)['servers']
        self.assertEqual([s['id'] for s in servers], [2, 3, 4])

        req = webob.Request.blank('/v1.0/servers?offset=aaa')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        self.assertTrue('offset' in res.body)

    def test_get_servers_with_limit_and_offset(self):
        req = webob.Request.blank('/v1.0/servers?limit=2&offset=1')
        res = req.get_response(fakes.wsgi_app())
        servers = json.loads(res.body)['servers']
        self.assertEqual([s['id'] for s in servers], [1, 2])

    def test_get_servers_with_bad_limit(self):
        req = webob.Request.blank('/v1.0/servers?limit=asdf&offset=1')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        self.assertTrue(res.body.find('limit param') > -1)

    def test_get_servers_with_bad_offset(self):
        req = webob.Request.blank('/v1.0/servers?limit=2&offset=asdf')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        self.assertTrue(res.body.find('offset param') > -1)

    def test_get_servers_with_marker(self):
        req = webob.Request.blank('/v1.1/fake/servers?marker=2')
        res = req.get_response(fakes.wsgi_app())
        servers = json.loads(res.body)['servers']
        self.assertEqual([s['name'] for s in servers], ["server3", "server4"])

    def test_get_servers_with_limit_and_marker(self):
        req = webob.Request.blank('/v1.1/fake/servers?limit=2&marker=1')
        res = req.get_response(fakes.wsgi_app())
        servers = json.loads(res.body)['servers']
        self.assertEqual([s['name'] for s in servers], ['server2', 'server3'])

    def test_get_servers_with_bad_marker(self):
        req = webob.Request.blank('/v1.1/fake/servers?limit=2&marker=asdf')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        self.assertTrue(res.body.find('marker param') > -1)

    def test_get_servers_with_bad_option_v1_0(self):
        # 1.0 API ignores unknown options
        def fake_get_all(compute_self, context, search_opts=None):
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = webob.Request.blank('/v1.0/servers?unknownoption=whee')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_with_bad_option_v1_1(self):
        # 1.1 API also ignores unknown options
        def fake_get_all(compute_self, context, search_opts=None):
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = webob.Request.blank('/v1.1/fake/servers?unknownoption=whee')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_allows_image_v1_1(self):
        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('image' in search_opts)
            self.assertEqual(search_opts['image'], '12345')
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)
        self.flags(allow_admin_api=False)

        req = webob.Request.blank('/v1.1/fake/servers?image=12345')
        res = req.get_response(fakes.wsgi_app())
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_tenant_id_filter_converts_to_project_id_for_admin(self):
        def fake_get_all(context, filters=None):
            self.assertNotEqual(filters, None)
            self.assertEqual(filters['project_id'], 'faketenant')
            self.assertFalse(filters.get('tenant_id'))
            return [stub_instance(100)]

        self.stubs.Set(nova.db.api, 'instance_get_all_by_filters',
                       fake_get_all)
        self.flags(allow_admin_api=True)

        req = webob.Request.blank('/v1.1/fake/servers?tenant_id=faketenant')
        # Use admin context
        context = nova.context.RequestContext('testuser', 'testproject',
                is_admin=True)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=context))
        res_dict = json.loads(res.body)
        # Failure in fake_get_all returns non 200 status code
        self.assertEqual(res.status_int, 200)

    def test_get_servers_allows_flavor_v1_1(self):
        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('flavor' in search_opts)
            # flavor is an integer ID
            self.assertEqual(search_opts['flavor'], '12345')
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)
        self.flags(allow_admin_api=False)

        req = webob.Request.blank('/v1.1/fake/servers?flavor=12345')
        res = req.get_response(fakes.wsgi_app())
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_allows_status_v1_1(self):
        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('vm_state' in search_opts)
            self.assertEqual(search_opts['vm_state'], vm_states.ACTIVE)
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)
        self.flags(allow_admin_api=False)

        req = webob.Request.blank('/v1.1/fake/servers?status=active')
        res = req.get_response(fakes.wsgi_app())
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_invalid_status_v1_1(self):
        """Test getting servers by invalid status"""
        self.flags(allow_admin_api=False)
        req = webob.Request.blank('/v1.1/fake/servers?status=running')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        self.assertTrue(res.body.find('Invalid server status') > -1)

    def test_get_servers_allows_name_v1_1(self):
        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('name' in search_opts)
            self.assertEqual(search_opts['name'], 'whee.*')
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)
        self.flags(allow_admin_api=False)

        req = webob.Request.blank('/v1.1/fake/servers?name=whee.*')
        res = req.get_response(fakes.wsgi_app())
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_allows_changes_since_v1_1(self):
        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('changes-since' in search_opts)
            changes_since = datetime.datetime(2011, 1, 24, 17, 8, 1)
            self.assertEqual(search_opts['changes-since'], changes_since)
            self.assertTrue('deleted' not in search_opts)
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        params = 'changes-since=2011-01-24T17:08:01Z'
        req = webob.Request.blank('/v1.1/fake/servers?%s' % params)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_allows_changes_since_bad_value_v1_1(self):
        params = 'changes-since=asdf'
        req = webob.Request.blank('/v1.1/fake/servers?%s' % params)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_get_servers_unknown_or_admin_options1(self):
        """Test getting servers by admin-only or unknown options.
        This tests when admin_api is off.  Make sure the admin and
        unknown options are stripped before they get to
        compute_api.get_all()
        """

        self.flags(allow_admin_api=False)

        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            # Allowed by user
            self.assertTrue('name' in search_opts)
            self.assertTrue('status' in search_opts)
            # Allowed only by admins with admin API on
            self.assertFalse('ip' in search_opts)
            self.assertFalse('unknown_option' in search_opts)
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = webob.Request.blank('/v1.1/fake/servers?%s' % query_str)
        # Request admin context
        context = nova.context.RequestContext('testuser', 'testproject',
                is_admin=True)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=context))
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_unknown_or_admin_options2(self):
        """Test getting servers by admin-only or unknown options.
        This tests when admin_api is on, but context is a user.
        Make sure the admin and unknown options are stripped before
        they get to compute_api.get_all()
        """

        self.flags(allow_admin_api=True)

        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            # Allowed by user
            self.assertTrue('name' in search_opts)
            self.assertTrue('status' in search_opts)
            # Allowed only by admins with admin API on
            self.assertFalse('ip' in search_opts)
            self.assertFalse('unknown_option' in search_opts)
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = webob.Request.blank('/v1.1/fake/servers?%s' % query_str)
        # Request admin context
        context = nova.context.RequestContext('testuser', 'testproject',
                is_admin=False)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=context))
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_unknown_or_admin_options3(self):
        """Test getting servers by admin-only or unknown options.
        This tests when admin_api is on and context is admin.
        All options should be passed through to compute_api.get_all()
        """

        self.flags(allow_admin_api=True)

        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            # Allowed by user
            self.assertTrue('name' in search_opts)
            self.assertTrue('status' in search_opts)
            # Allowed only by admins with admin API on
            self.assertTrue('ip' in search_opts)
            self.assertTrue('unknown_option' in search_opts)
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = webob.Request.blank('/v1.1/fake/servers?%s' % query_str)
        # Request admin context
        context = nova.context.RequestContext('testuser', 'testproject',
                is_admin=True)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=context))
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_admin_allows_ip_v1_1(self):
        """Test getting servers by ip with admin_api enabled and
        admin context
        """
        self.flags(allow_admin_api=True)

        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('ip' in search_opts)
            self.assertEqual(search_opts['ip'], '10\..*')
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = webob.Request.blank('/v1.1/fake/servers?ip=10\..*')
        # Request admin context
        context = nova.context.RequestContext('testuser', 'testproject',
                is_admin=True)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=context))
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def test_get_servers_admin_allows_ip6_v1_1(self):
        """Test getting servers by ip6 with admin_api enabled and
        admin context
        """
        self.flags(allow_admin_api=True)

        def fake_get_all(compute_self, context, search_opts=None):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('ip6' in search_opts)
            self.assertEqual(search_opts['ip6'], 'ffff.*')
            return [stub_instance(100)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = webob.Request.blank('/v1.1/fake/servers?ip6=ffff.*')
        # Request admin context
        context = nova.context.RequestContext('testuser', 'testproject',
                is_admin=True)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=context))
        # The following assert will fail if either of the asserts in
        # fake_get_all() fail
        self.assertEqual(res.status_int, 200)
        servers = json.loads(res.body)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], 100)

    def _setup_for_create_instance(self):
        """Shared implementation for tests below that create instance"""
        def instance_create(context, inst):
            inst_type = instance_types.get_instance_type_by_flavor_id(3)
            image_ref = 'http://localhost/images/2'
            return {'id': 1,
                    'display_name': 'server_test',
                    'uuid': FAKE_UUID,
                    'instance_type': dict(inst_type),
                    'access_ip_v4': '1.2.3.4',
                    'access_ip_v6': 'fead::1234',
                    'image_ref': image_ref,
                    'user_id': 'fake',
                    'project_id': 'fake',
                    "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                    "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                    "config_drive": self.config_drive,
                   }

        def server_update(context, id, params):
            return instance_create(context, id)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        def kernel_ramdisk_mapping(*args, **kwargs):
            return (1, 1)

        def image_id_from_hash(*args, **kwargs):
            return 2

        self.stubs.Set(nova.db.api, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(nova.db.api, 'instance_create', instance_create)
        self.stubs.Set(nova.rpc, 'cast', fake_method)
        self.stubs.Set(nova.rpc, 'call', fake_method)
        self.stubs.Set(nova.db.api, 'instance_update', server_update)
        self.stubs.Set(nova.db.api, 'queue_get_for', queue_get_for)
        self.stubs.Set(nova.network.manager.VlanManager, 'allocate_fixed_ip',
            fake_method)
        self.stubs.Set(
            nova.api.openstack.create_instance_helper.CreateInstanceHelper,
            "_get_kernel_ramdisk_from_image", kernel_ramdisk_mapping)
        self.stubs.Set(nova.compute.api.API, "_find_host", find_host)

    def _test_create_instance_helper(self):
        self._setup_for_create_instance()

        body = dict(server=dict(
            name='server_test', imageId=3, flavorId=2,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(16, len(server['adminPass']))
        self.assertEqual('server_test', server['name'])
        self.assertEqual(1, server['id'])
        self.assertEqual(2, server['flavorId'])
        self.assertEqual(3, server['imageId'])
        self.assertEqual(FAKE_UUID, server['uuid'])

    def test_create_instance(self):
        self._test_create_instance_helper()

    def test_create_instance_has_uuid(self):
        """Tests at the db-layer instead of API layer since that's where the
           UUID is generated
        """
        ctxt = context.RequestContext(1, 1)
        values = {}
        instance = nova.db.api.instance_create(ctxt, values)
        expected = FAKE_UUID
        self.assertEqual(instance['uuid'], expected)

    def test_create_instance_via_zones(self):
        """Server generated ReservationID"""
        self._setup_for_create_instance()
        self.flags(allow_admin_api=True)

        body = dict(server=dict(
            name='server_test', imageId=3, flavorId=2,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = webob.Request.blank('/v1.0/zones/boot')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())

        reservation_id = json.loads(res.body)['reservation_id']
        self.assertEqual(res.status_int, 200)
        self.assertNotEqual(reservation_id, "")
        self.assertNotEqual(reservation_id, None)
        self.assertTrue(len(reservation_id) > 1)

    def test_create_instance_via_zones_with_resid(self):
        """User supplied ReservationID"""
        self._setup_for_create_instance()
        self.flags(allow_admin_api=True)

        body = dict(server=dict(
            name='server_test', imageId=3, flavorId=2,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}, reservation_id='myresid'))
        req = webob.Request.blank('/v1.0/zones/boot')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())

        reservation_id = json.loads(res.body)['reservation_id']
        self.assertEqual(res.status_int, 200)
        self.assertEqual(reservation_id, "myresid")

    def test_create_instance_no_key_pair(self):
        fakes.stub_out_key_pair_funcs(self.stubs, have_key_pair=False)
        self._test_create_instance_helper()

    def test_create_instance_no_name(self):
        self._setup_for_create_instance()

        body = {
            'server': {
                'imageId': 3,
                'flavorId': 1,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
            },
        }

        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_image_conflict_snapshot_v1_1(self):
        """Attempt to create image when image is already being created."""
        def snapshot(*args, **kwargs):
            raise exception.InstanceSnapshotting
        self.stubs.Set(nova.compute.API, 'snapshot', snapshot)

        req = webob.Request.blank('/v1.1/fakes/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps({
            "createImage": {
                "name": "test_snapshot",
            },
        })
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 409)

    def test_create_instance_nonstring_name(self):
        self._setup_for_create_instance()

        body = {
            'server': {
                'name': 12,
                'imageId': 3,
                'flavorId': 1,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
            },
        }

        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_no_server_entity(self):
        self._setup_for_create_instance()

        body = {}

        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 422)

    def test_create_instance_whitespace_name(self):
        self._setup_for_create_instance()

        body = {
            'server': {
                'name': '    ',
                'imageId': 3,
                'flavorId': 1,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
            },
        }

        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_with_access_ip_v1_1(self):
        self._setup_for_create_instance()

        # proper local hrefs must start with 'http://localhost/v1.1/'
        image_href = 'http://localhost/v1.1/123/images/2'
        flavor_ref = 'http://localhost/123/flavors/3'
        access_ipv4 = '1.2.3.4'
        access_ipv6 = 'fead::1234'
        expected_flavor = {
            "id": "3",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/123/flavors/3',
                },
            ],
        }
        expected_image = {
            "id": "2",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/123/images/2',
                },
            ],
        }
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'accessIPv4': access_ipv4,
                'accessIPv6': access_ipv6,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': [
                    {
                        "path": "/etc/banner.txt",
                        "contents": "MQ==",
                    },
                ],
            },
        }

        req = webob.Request.blank('/v1.1/123/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(16, len(server['adminPass']))
        self.assertEqual(1, server['id'])
        self.assertEqual(0, server['progress'])
        self.assertEqual('server_test', server['name'])
        self.assertEqual(expected_flavor, server['flavor'])
        self.assertEqual(expected_image, server['image'])
        self.assertEqual(access_ipv4, server['accessIPv4'])
        self.assertEqual(access_ipv6, server['accessIPv6'])

    def test_create_instance_v1_1(self):
        self._setup_for_create_instance()

        # proper local hrefs must start with 'http://localhost/v1.1/'
        image_href = 'http://localhost/v1.1/images/2'
        flavor_ref = 'http://localhost/123/flavors/3'
        expected_flavor = {
            "id": "3",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/fake/flavors/3',
                },
            ],
        }
        expected_image = {
            "id": "2",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/fake/images/2',
                },
            ],
        }
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': [
                    {
                        "path": "/etc/banner.txt",
                        "contents": "MQ==",
                    },
                ],
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(16, len(server['adminPass']))
        self.assertEqual(1, server['id'])
        self.assertEqual("BUILD", server["status"])
        self.assertEqual(0, server['progress'])
        self.assertEqual('server_test', server['name'])
        self.assertEqual(expected_flavor, server['flavor'])
        self.assertEqual(expected_image, server['image'])
        self.assertEqual('1.2.3.4', server['accessIPv4'])
        self.assertEqual('fead::1234', server['accessIPv6'])

    def test_create_instance_v1_1_invalid_key_name(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/images/2'
        flavor_ref = 'http://localhost/flavors/3'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            key_name='nonexistentkey'))
        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_v1_1_valid_key_name(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/images/2'
        flavor_ref = 'http://localhost/flavors/3'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            key_name='key'))
        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_create_instance_v1_1_invalid_flavor_href(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/images/2'
        flavor_ref = 'http://localhost/v1.1/flavors/asdf'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_v1_1_invalid_flavor_id_int(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/123/images/2'
        flavor_ref = -1
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = webob.Request.blank('/v1.1/123/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_v1_1_bad_flavor_href(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/images/2'
        flavor_ref = 'http://localhost/v1.1/flavors/17'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_with_config_drive_v1_1(self):
        self.config_drive = True
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/123/images/2'
        flavor_ref = 'http://localhost/v1.1/123/flavors/3'
        body = {
            'server': {
                'name': 'config_drive_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
                'config_drive': True,
            },
        }

        req = webob.Request.blank('/v1.1/123/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        print res
        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(1, server['id'])
        self.assertTrue(server['config_drive'])

    def test_create_instance_with_config_drive_as_id_v1_1(self):
        self.config_drive = 2
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/123/images/2'
        flavor_ref = 'http://localhost/v1.1/123/flavors/3'
        body = {
            'server': {
                'name': 'config_drive_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
                'config_drive': 2,
            },
        }

        req = webob.Request.blank('/v1.1/123/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(1, server['id'])
        self.assertTrue(server['config_drive'])
        self.assertEqual(2, server['config_drive'])

    def test_create_instance_with_bad_config_drive_v1_1(self):
        self.config_drive = "asdf"
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/123/images/2'
        flavor_ref = 'http://localhost/v1.1/123/flavors/3'
        body = {
            'server': {
                'name': 'config_drive_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
                'config_drive': 'asdf',
            },
        }

        req = webob.Request.blank('/v1.1/123/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_without_config_drive_v1_1(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/123/images/2'
        flavor_ref = 'http://localhost/v1.1/123/flavors/3'
        body = {
            'server': {
                'name': 'config_drive_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
                'config_drive': True,
            },
        }

        req = webob.Request.blank('/v1.1/123/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(1, server['id'])
        self.assertFalse(server['config_drive'])

    def test_create_instance_v1_1_bad_href(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/images/asdf'
        flavor_ref = 'http://localhost/v1.1/flavors/3'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_v1_1_local_href(self):
        self._setup_for_create_instance()

        image_id = "2"
        flavor_ref = 'http://localhost/v1.1/flavors/3'
        expected_flavor = {
            "id": "3",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/fake/flavors/3',
                },
            ],
        }
        expected_image = {
            "id": "2",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/fake/images/2',
                },
            ],
        }
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_id,
                'flavorRef': flavor_ref,
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(expected_flavor, server['flavor'])
        self.assertEqual(expected_image, server['image'])

    def test_create_instance_with_admin_pass_v1_0(self):
        self._setup_for_create_instance()

        body = {
            'server': {
                'name': 'test-server-create',
                'imageId': 3,
                'flavorId': 1,
                'adminPass': 'testpass',
            },
        }

        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        res = json.loads(res.body)
        self.assertNotEqual(res['server']['adminPass'],
                            body['server']['adminPass'])

    def test_create_instance_v1_1_admin_pass(self):
        self._setup_for_create_instance()

        image_href = 'http://localhost/v1.1/images/2'
        flavor_ref = 'http://localhost/v1.1/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': 3,
                'flavorRef': 3,
                'adminPass': 'testpass',
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        server = json.loads(res.body)['server']
        self.assertEqual(server['adminPass'], body['server']['adminPass'])

    def test_create_instance_v1_1_admin_pass_empty(self):
        self._setup_for_create_instance()

        body = {
            'server': {
                'name': 'server_test',
                'imageRef': 3,
                'flavorRef': 3,
                'adminPass': '',
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_create_instance_whitespace_name(self):
        self._setup_for_create_instance()

        body = {
            'server': {
                'name': '    ',
                'imageId': 3,
                'flavorId': 1,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'personality': {},
            },
        }

        req = webob.Request.blank('/v1.0/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_server_no_body(self):
        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_nonstring_name(self):
        """ Confirm that update is filtering params """
        inst_dict = dict(name=12, adminPass='bacon')
        self.body = json.dumps(dict(server=inst_dict))

        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = self.body
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_whitespace_name(self):
        """ Confirm that update is filtering params """
        inst_dict = dict(name='   ', adminPass='bacon')
        self.body = json.dumps(dict(server=inst_dict))

        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = self.body
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_null_name(self):
        """ Confirm that update is filtering params """
        inst_dict = dict(name='', adminPass='bacon')
        self.body = json.dumps(dict(server=inst_dict))

        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = self.body
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_server_v1_0(self):
        inst_dict = dict(name='server_test', adminPass='bacon')
        self.body = json.dumps(dict(server=inst_dict))

        def server_update(context, id, params):
            filtered_dict = dict(display_name='server_test')
            self.assertEqual(params, filtered_dict)
            return filtered_dict

        self.stubs.Set(nova.db.api, 'instance_update',
            server_update)
        self.stubs.Set(nova.compute.api.API, "_find_host", find_host)
        mock_method = MockSetAdminPassword()
        self.stubs.Set(nova.compute.api.API, 'set_admin_password', mock_method)

        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = self.body
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 204)
        self.assertEqual(mock_method.instance_id, '1')
        self.assertEqual(mock_method.password, 'bacon')

    def test_update_server_no_body_v1_1(self):
        req = webob.Request.blank('/v1.1/fake/servers/1')
        req.method = 'PUT'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_server_all_attributes_v1_1(self):
        self.stubs.Set(nova.db.api, 'instance_get',
                return_server_with_attributes(name='server_test',
                                              access_ipv4='0.0.0.0',
                                              access_ipv6='beef::0123'))
        req = webob.Request.blank('/v1.1/123/servers/1')
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'accessIPv4': '0.0.0.0',
                  'accessIPv6': 'beef::0123',
               }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server_test')
        self.assertEqual(res_dict['server']['accessIPv4'], '0.0.0.0')
        self.assertEqual(res_dict['server']['accessIPv6'], 'beef::0123')

    def test_update_server_name_v1_1(self):
        self.stubs.Set(nova.db.api, 'instance_get',
                return_server_with_attributes(name='server_test'))
        req = webob.Request.blank('/v1.1/fake/servers/1')
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = json.dumps({'server': {'name': 'server_test'}})
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_access_ipv4_v1_1(self):
        self.stubs.Set(nova.db.api, 'instance_get',
                return_server_with_attributes(access_ipv4='0.0.0.0'))
        req = webob.Request.blank('/v1.1/123/servers/1')
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = json.dumps({'server': {'accessIPv4': '0.0.0.0'}})
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['accessIPv4'], '0.0.0.0')

    def test_update_server_access_ipv6_v1_1(self):
        self.stubs.Set(nova.db.api, 'instance_get',
                return_server_with_attributes(access_ipv6='beef::0123'))
        req = webob.Request.blank('/v1.1/123/servers/1')
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = json.dumps({'server': {'accessIPv6': 'beef::0123'}})
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['accessIPv6'], 'beef::0123')

    def test_update_server_adminPass_ignored_v1_1(self):
        inst_dict = dict(name='server_test', adminPass='bacon')
        self.body = json.dumps(dict(server=inst_dict))

        def server_update(context, id, params):
            filtered_dict = dict(display_name='server_test')
            self.assertEqual(params, filtered_dict)
            return filtered_dict

        self.stubs.Set(nova.db.api, 'instance_update', server_update)
        self.stubs.Set(nova.db.api, 'instance_get',
                return_server_with_attributes(name='server_test'))

        req = webob.Request.blank('/v1.1/fake/servers/1')
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = self.body
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['server']['id'], 1)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_create_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedule')
        req.method = 'POST'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_delete_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedule/1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_get_server_backup_schedules(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedule')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_get_server_backup_schedule(self):
        req = webob.Request.blank('/v1.0/servers/1/backup_schedule/1')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_server_backup_schedule_deprecated_v1_1(self):
        req = webob.Request.blank('/v1.1/fake/servers/1/backup_schedule')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_all_server_details_xml_v1_0(self):
        req = webob.Request.blank('/v1.0/servers/detail')
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        dom = minidom.parseString(res.body)
        for i, server in enumerate(dom.getElementsByTagName('server')):
            self.assertEqual(server.getAttribute('id'), str(i))
            self.assertEqual(server.getAttribute('hostId'), '')
            self.assertEqual(server.getAttribute('name'), 'server%d' % i)
            self.assertEqual(server.getAttribute('imageId'), '10')
            self.assertEqual(server.getAttribute('status'), 'BUILD')
            (meta,) = server.getElementsByTagName('meta')
            self.assertEqual(meta.getAttribute('key'), 'seq')
            self.assertEqual(meta.firstChild.data.strip(), str(i))

    def test_get_all_server_details_v1_0(self):
        req = webob.Request.blank('/v1.0/servers/detail')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)

        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], i)
            self.assertEqual(s['hostId'], '')
            self.assertEqual(s['name'], 'server%d' % i)
            self.assertEqual(s['imageId'], 10)
            self.assertEqual(s['flavorId'], 1)
            self.assertEqual(s['status'], 'BUILD')
            self.assertEqual(s['metadata']['seq'], str(i))

    def test_get_all_server_details_v1_1(self):
        expected_flavor = {
            "id": "1",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/fake/flavors/1',
                },
            ],
        }
        expected_image = {
            "id": "10",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost/fake/images/10',
                },
            ],
        }
        req = webob.Request.blank('/v1.1/fake/servers/detail')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], i)
            self.assertEqual(s['hostId'], '')
            self.assertEqual(s['name'], 'server%d' % i)
            self.assertEqual(s['image'], expected_image)
            self.assertEqual(s['flavor'], expected_flavor)
            self.assertEqual(s['status'], 'BUILD')
            self.assertEqual(s['metadata']['seq'], str(i))

    def test_get_all_server_details_with_host(self):
        '''
        We want to make sure that if two instances are on the same host, then
        they return the same hostId. If two instances are on different hosts,
        they should return different hostId's. In this test, there are 5
        instances - 2 on one host and 3 on another.
        '''

        def return_servers_with_host(context, *args, **kwargs):
            return [stub_instance(i, 'fake', 'fake', None, None, i % 2)
                    for i in xrange(5)]

        self.stubs.Set(nova.db.api, 'instance_get_all_by_filters',
            return_servers_with_host)

        req = webob.Request.blank('/v1.0/servers/detail')
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        server_list = res_dict['servers']
        host_ids = [server_list[0]['hostId'], server_list[1]['hostId']]
        self.assertTrue(host_ids[0] and host_ids[1])
        self.assertNotEqual(host_ids[0], host_ids[1])

        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], i)
            self.assertEqual(s['hostId'], host_ids[i % 2])
            self.assertEqual(s['name'], 'server%d' % i)
            self.assertEqual(s['imageId'], 10)
            self.assertEqual(s['flavorId'], 1)

    def test_server_pause(self):
        self.flags(allow_admin_api=True)
        req = webob.Request.blank('/v1.0/servers/1/pause')
        req.method = 'POST'
        req.content_type = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_unpause(self):
        self.flags(allow_admin_api=True)
        req = webob.Request.blank('/v1.0/servers/1/unpause')
        req.method = 'POST'
        req.content_type = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_suspend(self):
        self.flags(allow_admin_api=True)
        req = webob.Request.blank('/v1.0/servers/1/suspend')
        req.method = 'POST'
        req.content_type = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_resume(self):
        self.flags(allow_admin_api=True)
        req = webob.Request.blank('/v1.0/servers/1/resume')
        req.method = 'POST'
        req.content_type = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_reset_network(self):
        self.flags(allow_admin_api=True)
        req = webob.Request.blank('/v1.0/servers/1/reset_network')
        req.method = 'POST'
        req.content_type = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_inject_network_info(self):
        self.flags(allow_admin_api=True)
        req = webob.Request.blank(
              '/v1.0/servers/1/inject_network_info')
        req.method = 'POST'
        req.content_type = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_diagnostics(self):
        self.flags(allow_admin_api=False)
        req = webob.Request.blank("/v1.0/servers/1/diagnostics")
        req.method = "GET"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_server_actions(self):
        self.flags(allow_admin_api=False)
        req = webob.Request.blank("/v1.0/servers/1/actions")
        req.method = "GET"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_delete_server_instance(self):
        req = webob.Request.blank('/v1.0/servers/1')
        req.method = 'DELETE'

        self.server_delete_called = False

        def instance_destroy_mock(context, id):
            self.server_delete_called = True

        self.stubs.Set(nova.db.api, 'instance_destroy',
            instance_destroy_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status, '202 Accepted')
        self.assertEqual(self.server_delete_called, True)

    def test_rescue_accepted(self):
        self.flags(allow_admin_api=True)
        body = {}

        self.called = False

        def rescue_mock(*args, **kwargs):
            self.called = True

        self.stubs.Set(nova.compute.api.API, 'rescue', rescue_mock)
        req = webob.Request.blank('/v1.0/servers/1/rescue')
        req.method = 'POST'
        req.content_type = 'application/json'

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(self.called, True)
        self.assertEqual(res.status_int, 202)

    def test_rescue_raises_handled(self):
        self.flags(allow_admin_api=True)
        body = {}

        def rescue_mock(*args, **kwargs):
            raise Exception('Who cares?')

        self.stubs.Set(nova.compute.api.API, 'rescue', rescue_mock)
        req = webob.Request.blank('/v1.0/servers/1/rescue')
        req.method = 'POST'
        req.content_type = 'application/json'

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 422)

    def test_delete_server_instance_v1_1(self):
        req = webob.Request.blank('/v1.1/fake/servers/1')
        req.method = 'DELETE'

        self.server_delete_called = False

        def instance_destroy_mock(context, id):
            self.server_delete_called = True

        self.stubs.Set(nova.db.api, 'instance_destroy',
            instance_destroy_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 204)
        self.assertEqual(self.server_delete_called, True)


class TestServerStatus(test.TestCase):

    def _get_with_state(self, vm_state, task_state=None):
        new_server = return_server_with_state(vm_state, task_state)
        self.stubs.Set(nova.db.api, 'instance_get', new_server)
        request = webob.Request.blank('/v1.0/servers/1')
        response = request.get_response(fakes.wsgi_app())
        self.assertEqual(response.status_int, 200)
        return json.loads(response.body)

    def test_active(self):
        response = self._get_with_state(vm_states.ACTIVE)
        self.assertEqual(response['server']['status'], 'ACTIVE')

    def test_reboot(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBOOTING)
        self.assertEqual(response['server']['status'], 'REBOOT')

    def test_rebuild(self):
        response = self._get_with_state(vm_states.REBUILDING)
        self.assertEqual(response['server']['status'], 'REBUILD')

    def test_rebuild_error(self):
        response = self._get_with_state(vm_states.ERROR)
        self.assertEqual(response['server']['status'], 'ERROR')

    def test_resize(self):
        response = self._get_with_state(vm_states.RESIZING)
        self.assertEqual(response['server']['status'], 'RESIZE')

    def test_verify_resize(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.RESIZE_VERIFY)
        self.assertEqual(response['server']['status'], 'VERIFY_RESIZE')

    def test_password_update(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.UPDATING_PASSWORD)
        self.assertEqual(response['server']['status'], 'PASSWORD')

    def test_stopped(self):
        response = self._get_with_state(vm_states.STOPPED)
        self.assertEqual(response['server']['status'], 'STOPPED')


class TestServerCreateRequestXMLDeserializerV10(unittest.TestCase):

    def setUp(self):
        self.deserializer = create_instance_helper.ServerXMLDeserializer()

    def test_minimal_request(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageId": "1",
                "flavorId": "1",
                "metadata": {},
                "personality": [],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_empty_metadata(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata/>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageId": "1",
                "flavorId": "1",
                "metadata": {},
                "personality": [],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_empty_personality(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <personality/>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageId": "1",
                "flavorId": "1",
                "metadata": {},
                "personality": [],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_empty_metadata_and_personality(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata/>
    <personality/>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageId": "1",
                "flavorId": "1",
                "metadata": {},
                "personality": [],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_empty_metadata_and_personality_reversed(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <personality/>
    <metadata/>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageId": "1",
                "flavorId": "1",
                "metadata": {},
                "personality": [],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_personality(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <personality>
        <file path="/etc/conf">aabbccdd</file>
    </personality>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = [{"path": "/etc/conf", "contents": "aabbccdd"}]
        self.assertEquals(request['body']["server"]["personality"], expected)

    def test_request_with_two_personalities(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
<personality><file path="/etc/conf">aabbccdd</file>
<file path="/etc/sudoers">abcd</file></personality></server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = [{"path": "/etc/conf", "contents": "aabbccdd"},
                    {"path": "/etc/sudoers", "contents": "abcd"}]
        self.assertEquals(request['body']["server"]["personality"], expected)

    def test_request_second_personality_node_ignored(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <personality>
        <file path="/etc/conf">aabbccdd</file>
    </personality>
    <personality>
        <file path="/etc/ignoreme">anything</file>
    </personality>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = [{"path": "/etc/conf", "contents": "aabbccdd"}]
        self.assertEquals(request['body']["server"]["personality"], expected)

    def test_request_with_one_personality_missing_path(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
<personality><file>aabbccdd</file></personality></server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = [{"contents": "aabbccdd"}]
        self.assertEquals(request['body']["server"]["personality"], expected)

    def test_request_with_one_personality_empty_contents(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
<personality><file path="/etc/conf"></file></personality></server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = [{"path": "/etc/conf", "contents": ""}]
        self.assertEquals(request['body']["server"]["personality"], expected)

    def test_request_with_one_personality_empty_contents_variation(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
<personality><file path="/etc/conf"/></personality></server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = [{"path": "/etc/conf", "contents": ""}]
        self.assertEquals(request['body']["server"]["personality"], expected)

    def test_request_with_one_metadata(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta key="alpha">beta</meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"alpha": "beta"}
        self.assertEquals(request['body']["server"]["metadata"], expected)

    def test_request_with_two_metadata(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta key="alpha">beta</meta>
        <meta key="foo">bar</meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"alpha": "beta", "foo": "bar"}
        self.assertEquals(request['body']["server"]["metadata"], expected)

    def test_request_with_metadata_missing_value(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta key="alpha"></meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"alpha": ""}
        self.assertEquals(request['body']["server"]["metadata"], expected)

    def test_request_with_two_metadata_missing_value(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta key="alpha"/>
        <meta key="delta"/>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"alpha": "", "delta": ""}
        self.assertEquals(request['body']["server"]["metadata"], expected)

    def test_request_with_metadata_missing_key(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta>beta</meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"": "beta"}
        self.assertEquals(request['body']["server"]["metadata"], expected)

    def test_request_with_two_metadata_missing_key(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta>beta</meta>
        <meta>gamma</meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"": "gamma"}
        self.assertEquals(request['body']["server"]["metadata"], expected)

    def test_request_with_metadata_duplicate_key(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta key="foo">bar</meta>
        <meta key="foo">baz</meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"foo": "baz"}
        self.assertEquals(request['body']["server"]["metadata"], expected)

    def test_canonical_request_from_docs(self):
        serial_request = """
<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"
 name="new-server-test" imageId="1" flavorId="1">
    <metadata>
        <meta key="My Server Name">Apache1</meta>
    </metadata>
    <personality>
        <file path="/etc/banner.txt">\
ICAgICAgDQoiQSBjbG91ZCBkb2VzIG5vdCBrbm93IHdoeSBp\
dCBtb3ZlcyBpbiBqdXN0IHN1Y2ggYSBkaXJlY3Rpb24gYW5k\
IGF0IHN1Y2ggYSBzcGVlZC4uLkl0IGZlZWxzIGFuIGltcHVs\
c2lvbi4uLnRoaXMgaXMgdGhlIHBsYWNlIHRvIGdvIG5vdy4g\
QnV0IHRoZSBza3kga25vd3MgdGhlIHJlYXNvbnMgYW5kIHRo\
ZSBwYXR0ZXJucyBiZWhpbmQgYWxsIGNsb3VkcywgYW5kIHlv\
dSB3aWxsIGtub3csIHRvbywgd2hlbiB5b3UgbGlmdCB5b3Vy\
c2VsZiBoaWdoIGVub3VnaCB0byBzZWUgYmV5b25kIGhvcml6\
b25zLiINCg0KLVJpY2hhcmQgQmFjaA==</file>
    </personality>
</server>"""
        expected = {"server": {
            "name": "new-server-test",
            "imageId": "1",
            "flavorId": "1",
            "metadata": {
                "My Server Name": "Apache1",
            },
            "personality": [
                {
                    "path": "/etc/banner.txt",
                    "contents": """\
ICAgICAgDQoiQSBjbG91ZCBkb2VzIG5vdCBrbm93IHdoeSBp\
dCBtb3ZlcyBpbiBqdXN0IHN1Y2ggYSBkaXJlY3Rpb24gYW5k\
IGF0IHN1Y2ggYSBzcGVlZC4uLkl0IGZlZWxzIGFuIGltcHVs\
c2lvbi4uLnRoaXMgaXMgdGhlIHBsYWNlIHRvIGdvIG5vdy4g\
QnV0IHRoZSBza3kga25vd3MgdGhlIHJlYXNvbnMgYW5kIHRo\
ZSBwYXR0ZXJucyBiZWhpbmQgYWxsIGNsb3VkcywgYW5kIHlv\
dSB3aWxsIGtub3csIHRvbywgd2hlbiB5b3UgbGlmdCB5b3Vy\
c2VsZiBoaWdoIGVub3VnaCB0byBzZWUgYmV5b25kIGhvcml6\
b25zLiINCg0KLVJpY2hhcmQgQmFjaA==""",
                },
            ],
        }}
        request = self.deserializer.deserialize(serial_request, 'create')
        self.assertEqual(request['body'], expected)


class TestServerCreateRequestXMLDeserializerV11(test.TestCase):

    def setUp(self):
        super(TestServerCreateRequestXMLDeserializerV11, self).setUp()
        self.deserializer = create_instance_helper.ServerXMLDeserializerV11()

    def test_minimal_request(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_access_ipv4(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        accessIPv4="1.2.3.4"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "accessIPv4": "1.2.3.4",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_access_ipv6(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        accessIPv6="fead::1234"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "accessIPv6": "fead::1234",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_access_ip(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        accessIPv4="1.2.3.4"
        accessIPv6="fead::1234"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "fead::1234",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_admin_pass(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        adminPass="1234"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "adminPass": "1234",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_image_link(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="http://localhost:8774/v1.1/images/2"
        flavorRef="3"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "http://localhost:8774/v1.1/images/2",
                "flavorRef": "3",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_flavor_link(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="http://localhost:8774/v1.1/flavors/3"/>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "http://localhost:8774/v1.1/flavors/3",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_empty_metadata_personality(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2">
    <metadata/>
    <personality/>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "metadata": {},
                "personality": [],
            },
        }
        self.assertEquals(request['body'], expected)

    def test_multiple_metadata_items(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2">
    <metadata>
        <meta key="one">two</meta>
        <meta key="open">snack</meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "metadata": {"one": "two", "open": "snack"},
            },
        }
        self.assertEquals(request['body'], expected)

    def test_multiple_personality_files(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        name="new-server-test"
        imageRef="1"
        flavorRef="2">
    <personality>
        <file path="/etc/banner.txt">MQ==</file>
        <file path="/etc/hosts">Mg==</file>
    </personality>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "personality": [
                    {"path": "/etc/banner.txt", "contents": "MQ=="},
                    {"path": "/etc/hosts", "contents": "Mg=="},
                ],
            },
        }
        self.assertDictMatch(request['body'], expected)

    def test_spec_request(self):
        image_bookmark_link = "http://servers.api.openstack.org/1234/" + \
                              "images/52415800-8b69-11e0-9b19-734f6f006e54"
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        imageRef="%s"
        flavorRef="52415800-8b69-11e0-9b19-734f1195ff37"
        name="new-server-test">
  <metadata>
    <meta key="My Server Name">Apache1</meta>
  </metadata>
  <personality>
    <file path="/etc/banner.txt">Mg==</file>
  </personality>
</server>""" % (image_bookmark_link)
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "http://servers.api.openstack.org/1234/" + \
                            "images/52415800-8b69-11e0-9b19-734f6f006e54",
                "flavorRef": "52415800-8b69-11e0-9b19-734f1195ff37",
                "metadata": {"My Server Name": "Apache1"},
                "personality": [
                    {
                        "path": "/etc/banner.txt",
                        "contents": "Mg==",
                    },
                ],
            },
        }
        self.assertEquals(request['body'], expected)

    def test_request_with_empty_networks(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks/>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1" fixed_ip="10.0.1.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_two_networks(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1" fixed_ip="10.0.1.12"/>
       <network uuid="2" fixed_ip="10.0.2.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": "10.0.1.12"},
                             {"uuid": "2", "fixed_ip": "10.0.2.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_second_network_node_ignored(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1" fixed_ip="10.0.1.12"/>
    </networks>
    <networks>
       <network uuid="2" fixed_ip="10.0.2.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_missing_id(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network fixed_ip="10.0.1.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_missing_fixed_ip(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_empty_id(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v1.1"
     name="new-server-test" imageRef="1" flavorRef="1">
        <networks>
           <network uuid="" fixed_ip="10.0.1.12"/>
        </networks>
    </server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "", "fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_empty_fixed_ip(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v1.1"
     name="new-server-test" imageRef="1" flavorRef="1">
        <networks>
           <network uuid="1" fixed_ip=""/>
        </networks>
    </server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": ""}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_networks_duplicate_ids(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v1.1"
     name="new-server-test" imageRef="1" flavorRef="1">
        <networks>
           <network uuid="1" fixed_ip="10.0.1.12"/>
           <network uuid="1" fixed_ip="10.0.2.12"/>
        </networks>
    </server>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": "10.0.1.12"},
                             {"uuid": "1", "fixed_ip": "10.0.2.12"}],
                }}
        self.assertEquals(request['body'], expected)


class TestAddressesXMLSerialization(test.TestCase):

    serializer = nova.api.openstack.ips.IPXMLSerializer()

    def test_show(self):
        fixture = {
            'network_2': [
                {'addr': '192.168.0.1', 'version': 4},
                {'addr': 'fe80::beef', 'version': 6},
            ],
        }
        output = self.serializer.serialize(fixture, 'show')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <network xmlns="http://docs.openstack.org/compute/api/v1.1"
                     id="network_2">
                <ip version="4" addr="192.168.0.1"/>
                <ip version="6" addr="fe80::beef"/>
            </network>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_index(self):
        fixture = {
            'addresses': {
                'network_1': [
                    {'addr': '192.168.0.3', 'version': 4},
                    {'addr': '192.168.0.5', 'version': 4},
                ],
                'network_2': [
                    {'addr': '192.168.0.1', 'version': 4},
                    {'addr': 'fe80::beef', 'version': 6},
                ],
            },
        }
        output = self.serializer.serialize(fixture, 'index')
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <addresses xmlns="http://docs.openstack.org/compute/api/v1.1">
                <network id="network_2">
                    <ip version="4" addr="192.168.0.1"/>
                    <ip version="6" addr="fe80::beef"/>
                </network>
                <network id="network_1">
                    <ip version="4" addr="192.168.0.3"/>
                    <ip version="4" addr="192.168.0.5"/>
                </network>
            </addresses>
        """.replace("  ", ""))

        self.assertEqual(expected.toxml(), actual.toxml())


class TestServerInstanceCreation(test.TestCase):

    def setUp(self):
        super(TestServerInstanceCreation, self).setUp()
        fakes.stub_out_image_service(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)

    def _setup_mock_compute_api_for_personality(self):

        class MockComputeAPI(nova.compute.API):

            def __init__(self):
                self.injected_files = None
                self.networks = None
                self.db = db

            def create(self, *args, **kwargs):
                if 'injected_files' in kwargs:
                    self.injected_files = kwargs['injected_files']
                else:
                    self.injected_files = None

                return [{'id': '1234', 'display_name': 'fakeinstance',
                         'user_id': 'fake',
                         'project_id': 'fake',
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
            nova.api.openstack.create_instance_helper.CreateInstanceHelper,
            '_get_kernel_ramdisk_from_image', make_stub_method((1, 1)))
        return compute_api

    def _create_personality_request_dict(self, personality_files):
        server = {}
        server['name'] = 'new-server-test'
        server['imageId'] = 1
        server['flavorId'] = 1
        if personality_files is not None:
            personalities = []
            for path, contents in personality_files:
                personalities.append({'path': path, 'contents': contents})
            server['personality'] = personalities
        return {'server': server}

    def _get_create_request_json(self, body_dict):
        req = webob.Request.blank('/v1.0/servers')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body_dict)
        return req

    def _run_create_instance_with_mock_compute_api(self, request):
        compute_api = self._setup_mock_compute_api_for_personality()
        response = request.get_response(fakes.wsgi_app())
        return compute_api, response

    def _format_xml_request_body(self, body_dict):
        server = body_dict['server']
        body_parts = []
        body_parts.extend([
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<server xmlns="http://docs.rackspacecloud.com/servers/api/v1.0"',
            ' name="%s" imageId="%s" flavorId="%s">' % (
                    server['name'], server['imageId'], server['flavorId'])])
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
        body_parts.append('</server>')
        return ''.join(body_parts)

    def _get_create_request_xml(self, body_dict):
        req = webob.Request.blank('/v1.0/servers')
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

    def test_create_instance_with_no_personality(self):
        request, response, injected_files = \
                self._create_instance_with_personality_json(personality=None)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(injected_files, [])

    def test_create_instance_with_no_personality_xml(self):
        request, response, injected_files = \
                self._create_instance_with_personality_xml(personality=None)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(injected_files, [])

    def test_create_instance_with_personality(self):
        path = '/my/file/path'
        contents = '#!/bin/bash\necho "Hello, World!"\n'
        b64contents = base64.b64encode(contents)
        personality = [(path, b64contents)]
        request, response, injected_files = \
            self._create_instance_with_personality_json(personality)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(injected_files, [(path, contents)])

    def test_create_instance_with_personality_xml(self):
        path = '/my/file/path'
        contents = '#!/bin/bash\necho "Hello, World!"\n'
        b64contents = base64.b64encode(contents)
        personality = [(path, b64contents)]
        request, response, injected_files = \
            self._create_instance_with_personality_xml(personality)
        self.assertEquals(response.status_int, 202)
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
        self.assertEquals(response.status_int, 202)

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
        self.assertEquals(response.status_int, 202)
        self.assertEquals(injected_files, files)

    def test_create_instance_personality_empty_content(self):
        path = '/my/file/path'
        contents = ''
        personality = [(path, contents)]
        request, response, injected_files = \
            self._create_instance_with_personality_json(personality)
        self.assertEquals(response.status_int, 202)
        self.assertEquals(injected_files, [(path, contents)])

    def test_create_instance_admin_pass_json(self):
        request, response, dummy = \
            self._create_instance_with_personality_json(None)
        self.assertEquals(response.status_int, 202)
        response = json.loads(response.body)
        self.assertTrue('adminPass' in response['server'])
        self.assertEqual(16, len(response['server']['adminPass']))

    def test_create_instance_admin_pass_xml(self):
        request, response, dummy = \
            self._create_instance_with_personality_xml(None)
        self.assertEquals(response.status_int, 202)
        dom = minidom.parseString(response.body)
        server = dom.childNodes[0]
        self.assertEquals(server.nodeName, 'server')
        self.assertEqual(16, len(server.getAttribute('adminPass')))


class TestGetKernelRamdiskFromImage(test.TestCase):
    """
    If we're building from an AMI-style image, we need to be able to fetch the
    kernel and ramdisk associated with the machine image. This information is
    stored with the image metadata and return via the ImageService.

    These tests ensure that we parse the metadata return the ImageService
    correctly and that we handle failure modes appropriately.
    """

    def test_status_not_active(self):
        """We should only allow fetching of kernel and ramdisk information if
        we have a 'fully-formed' image, aka 'active'
        """
        image_meta = {'id': 1, 'status': 'queued'}
        self.assertRaises(exception.Invalid, self._get_k_r, image_meta)

    def test_not_ami(self):
        """Anything other than ami should return no kernel and no ramdisk"""
        image_meta = {'id': 1, 'status': 'active', 'container_format': 'vhd'}
        kernel_id, ramdisk_id = self._get_k_r(image_meta)
        self.assertEqual(kernel_id, None)
        self.assertEqual(ramdisk_id, None)

    def test_ami_no_kernel(self):
        """If an ami is missing a kernel it should raise NotFound"""
        image_meta = {'id': 1, 'status': 'active', 'container_format': 'ami',
                      'properties': {'ramdisk_id': 1}}
        self.assertRaises(exception.NotFound, self._get_k_r, image_meta)

    def test_ami_no_ramdisk(self):
        """If an ami is missing a ramdisk, return kernel ID and None for
        ramdisk ID
        """
        image_meta = {'id': 1, 'status': 'active', 'container_format': 'ami',
                      'properties': {'kernel_id': 1}}
        kernel_id, ramdisk_id = self._get_k_r(image_meta)
        self.assertEqual(kernel_id, 1)
        self.assertEqual(ramdisk_id, None)

    def test_ami_kernel_ramdisk_present(self):
        """Return IDs if both kernel and ramdisk are present"""
        image_meta = {'id': 1, 'status': 'active', 'container_format': 'ami',
                      'properties': {'kernel_id': 1, 'ramdisk_id': 2}}
        kernel_id, ramdisk_id = self._get_k_r(image_meta)
        self.assertEqual(kernel_id, 1)
        self.assertEqual(ramdisk_id, 2)

    @staticmethod
    def _get_k_r(image_meta):
        """Rebinding function to a shorter name for convenience"""
        kernel_id, ramdisk_id = create_instance_helper.CreateInstanceHelper. \
                                _do_get_kernel_ramdisk_from_image(image_meta)
        return kernel_id, ramdisk_id


class ServersViewBuilderV11Test(test.TestCase):

    def setUp(self):
        self.instance = self._get_instance()
        self.view_builder = self._get_view_builder()

    def tearDown(self):
        pass

    def _get_instance(self):
        created_at = datetime.datetime(2010, 10, 10, 12, 0, 0)
        updated_at = datetime.datetime(2010, 11, 11, 11, 0, 0)
        instance = {
            "id": 1,
            "created_at": created_at,
            "updated_at": updated_at,
            "admin_pass": "",
            "user_id": "fake",
            "project_id": "fake",
            "image_ref": "5",
            "kernel_id": "",
            "ramdisk_id": "",
            "launch_index": 0,
            "key_name": "",
            "key_data": "",
            "vm_state": vm_states.BUILDING,
            "task_state": None,
            "memory_mb": 0,
            "vcpus": 0,
            "local_gb": 0,
            "hostname": "",
            "host": "",
            "instance_type": {
               "flavorid": 1,
            },
            "user_data": "",
            "reservation_id": "",
            "mac_address": "",
            "scheduled_at": utils.utcnow(),
            "launched_at": utils.utcnow(),
            "terminated_at": utils.utcnow(),
            "availability_zone": "",
            "display_name": "test_server",
            "locked": False,
            "metadata": [],
            "accessIPv4": "1.2.3.4",
            "accessIPv6": "fead::1234",
            #"address": ,
            #"floating_ips": [{"address":ip} for ip in public_addresses]}
            "uuid": "deadbeef-feed-edee-beef-d0ea7beefedd"}

        return instance

    def _get_view_builder(self, project_id=""):
        base_url = "http://localhost/v1.1"
        views = nova.api.openstack.views
        address_builder = views.addresses.ViewBuilderV11()
        flavor_builder = views.flavors.ViewBuilderV11(base_url, project_id)
        image_builder = views.images.ViewBuilderV11(base_url, project_id)

        view_builder = nova.api.openstack.views.servers.ViewBuilderV11(
            address_builder,
            flavor_builder,
            image_builder,
            base_url,
            project_id,
        )
        return view_builder

    def test_build_server(self):
        expected_server = {
            "server": {
                "id": 1,
                "uuid": self.instance['uuid'],
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/1",
                    },
                ],
            }
        }

        output = self.view_builder.build(self.instance, False)
        self.assertDictMatch(output, expected_server)

    def test_build_server_with_project_id(self):
        expected_server = {
            "server": {
                "id": 1,
                "uuid": self.instance['uuid'],
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/fake/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/1",
                    },
                ],
            }
        }

        view_builder = self._get_view_builder(project_id='fake')
        output = view_builder.build(self.instance, False)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail(self):
        image_bookmark = "http://localhost/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        expected_server = {
            "server": {
                "id": 1,
                "uuid": self.instance['uuid'],
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "accessIPv4": "",
                "accessIPv6": "",
                "hostId": '',
                "key_name": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {},
                "metadata": {},
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/1",
                    },
                ],
            }
        }

        output = self.view_builder.build(self.instance, True)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_active_status(self):
        #set the power state of the instance to running
        self.instance['vm_state'] = vm_states.ACTIVE
        image_bookmark = "http://localhost/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        expected_server = {
            "server": {
                "id": 1,
                "uuid": self.instance['uuid'],
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 100,
                "name": "test_server",
                "status": "ACTIVE",
                "accessIPv4": "",
                "accessIPv6": "",
                "hostId": '',
                "key_name": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {},
                "metadata": {},
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/1",
                    },
                ],
            }
        }

        output = self.view_builder.build(self.instance, True)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_accessipv4(self):

        self.instance['access_ip_v4'] = '1.2.3.4'

        image_bookmark = "http://localhost/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        expected_server = {
            "server": {
                "id": 1,
                "uuid": self.instance['uuid'],
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "key_name": "",
                "status": "BUILD",
                "hostId": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                                              {
                            "rel": "bookmark",
                            "href": flavor_bookmark,
                        },
                    ],
                },
                "addresses": {},
                "metadata": {},
                "config_drive": None,
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/1",
                    },
                ],
            }
        }

        output = self.view_builder.build(self.instance, True)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_accessipv6(self):

        self.instance['access_ip_v6'] = 'fead::1234'

        image_bookmark = "http://localhost/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        expected_server = {
            "server": {
                "id": 1,
                "uuid": self.instance['uuid'],
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "key_name": "",
                "status": "BUILD",
                "hostId": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                                              {
                            "rel": "bookmark",
                            "href": flavor_bookmark,
                        },
                    ],
                },
                "addresses": {},
                "metadata": {},
                "config_drive": None,
                "accessIPv4": "",
                "accessIPv6": "fead::1234",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/1",
                    },
                ],
            }
        }

        output = self.view_builder.build(self.instance, True)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_metadata(self):

        metadata = []
        metadata.append(InstanceMetadata(key="Open", value="Stack"))
        metadata.append(InstanceMetadata(key="Number", value=1))
        self.instance['metadata'] = metadata

        image_bookmark = "http://localhost/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        expected_server = {
            "server": {
                "id": 1,
                "uuid": self.instance['uuid'],
                "user_id": "fake",
                "tenant_id": "fake",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "accessIPv4": "",
                "accessIPv6": "",
                "hostId": '',
                "key_name": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                                              {
                            "rel": "bookmark",
                            "href": flavor_bookmark,
                        },
                    ],
                },
                "addresses": {},
                "metadata": {
                    "Open": "Stack",
                    "Number": "1",
                },
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1/servers/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/1",
                    },
                ],
            }
        }

        output = self.view_builder.build(self.instance, True)
        self.assertDictMatch(output, expected_server)


class ServerXMLSerializationTest(test.TestCase):

    TIMESTAMP = "2010-10-11T10:30:22Z"
    SERVER_HREF = 'http://localhost/v1.1/servers/123'
    SERVER_BOOKMARK = 'http://localhost/servers/123'
    IMAGE_BOOKMARK = 'http://localhost/images/5'
    FLAVOR_BOOKMARK = 'http://localhost/flavors/1'

    def setUp(self):
        self.maxDiff = None
        test.TestCase.setUp(self)

    def test_show(self):
        serializer = servers.ServerXMLSerializer()

        fixture = {
            "server": {
                "id": 1,
                "user_id": "fake",
                "tenant_id": "fake",
                "uuid": FAKE_UUID,
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "hostId": 'e4d909c290d0fb1ca068ffaddf22cbd0',
                "key_name": '',
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "fead::1234",
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.IMAGE_BOOKMARK,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.FLAVOR_BOOKMARK,
                        },
                    ],
                },
                "addresses": {
                    "network_one": [
                        {
                            "version": 4,
                            "addr": "67.23.10.138",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.138",
                        },
                    ],
                    "network_two": [
                        {
                            "version": 4,
                            "addr": "67.23.10.139",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.139",
                        },
                    ],
                },
                "metadata": {
                    "Open": "Stack",
                    "Number": "1",
                },
                'links': [
                    {
                        'href': self.SERVER_HREF,
                        'rel': 'self',
                    },
                    {
                        'href': self.SERVER_BOOKMARK,
                        'rel': 'bookmark',
                    },
                ],
            }
        }

        output = serializer.serialize(fixture, 'show')
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        expected_server_href = self.SERVER_HREF
        expected_server_bookmark = self.SERVER_BOOKMARK
        expected_image_bookmark = self.IMAGE_BOOKMARK
        expected_flavor_bookmark = self.FLAVOR_BOOKMARK
        expected_now = self.TIMESTAMP
        expected_uuid = FAKE_UUID
        server_dict = fixture['server']

        for key in ['name', 'id', 'uuid', 'created', 'accessIPv4',
                    'updated', 'progress', 'status', 'hostId',
                    'accessIPv6']:
            self.assertEqual(root.get(key), str(server_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(server_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 2)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = server_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        image_root = root.find('{0}image'.format(NS))
        self.assertEqual(image_root.get('id'), server_dict['image']['id'])
        link_nodes = image_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['image']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        flavor_root = root.find('{0}flavor'.format(NS))
        self.assertEqual(flavor_root.get('id'), server_dict['flavor']['id'])
        link_nodes = flavor_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['flavor']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        addresses_root = root.find('{0}addresses'.format(NS))
        addresses_dict = server_dict['addresses']
        network_elems = addresses_root.findall('{0}network'.format(NS))
        self.assertEqual(len(network_elems), 2)
        for i, network_elem in enumerate(network_elems):
            network = addresses_dict.items()[i]
            self.assertEqual(str(network_elem.get('id')), str(network[0]))
            ip_elems = network_elem.findall('{0}ip'.format(NS))
            for z, ip_elem in enumerate(ip_elems):
                ip = network[1][z]
                self.assertEqual(str(ip_elem.get('version')),
                                 str(ip['version']))
                self.assertEqual(str(ip_elem.get('addr')),
                                 str(ip['addr']))

    def test_create(self):
        serializer = servers.ServerXMLSerializer()

        fixture = {
            "server": {
                "id": 1,
                "uuid": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "fead::1234",
                "hostId": "e4d909c290d0fb1ca068ffaddf22cbd0",
                "adminPass": "test_password",
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.IMAGE_BOOKMARK,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.FLAVOR_BOOKMARK,
                        },
                    ],
                },
                "addresses": {
                    "network_one": [
                        {
                            "version": 4,
                            "addr": "67.23.10.138",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.138",
                        },
                    ],
                    "network_two": [
                        {
                            "version": 4,
                            "addr": "67.23.10.139",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.139",
                        },
                    ],
                },
                "metadata": {
                    "Open": "Stack",
                    "Number": "1",
                },
                'links': [
                    {
                        'href': self.SERVER_HREF,
                        'rel': 'self',
                    },
                    {
                        'href': self.SERVER_BOOKMARK,
                        'rel': 'bookmark',
                    },
                ],
            }
        }

        output = serializer.serialize(fixture, 'create')
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        expected_server_href = self.SERVER_HREF
        expected_server_bookmark = self.SERVER_BOOKMARK
        expected_image_bookmark = self.IMAGE_BOOKMARK
        expected_flavor_bookmark = self.FLAVOR_BOOKMARK
        expected_now = self.TIMESTAMP
        expected_uuid = FAKE_UUID
        server_dict = fixture['server']

        for key in ['name', 'id', 'uuid', 'created', 'accessIPv4',
                    'updated', 'progress', 'status', 'hostId',
                    'accessIPv6', 'adminPass']:
            self.assertEqual(root.get(key), str(server_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(server_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 2)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = server_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        image_root = root.find('{0}image'.format(NS))
        self.assertEqual(image_root.get('id'), server_dict['image']['id'])
        link_nodes = image_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['image']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        flavor_root = root.find('{0}flavor'.format(NS))
        self.assertEqual(flavor_root.get('id'), server_dict['flavor']['id'])
        link_nodes = flavor_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['flavor']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        addresses_root = root.find('{0}addresses'.format(NS))
        addresses_dict = server_dict['addresses']
        network_elems = addresses_root.findall('{0}network'.format(NS))
        self.assertEqual(len(network_elems), 2)
        for i, network_elem in enumerate(network_elems):
            network = addresses_dict.items()[i]
            self.assertEqual(str(network_elem.get('id')), str(network[0]))
            ip_elems = network_elem.findall('{0}ip'.format(NS))
            for z, ip_elem in enumerate(ip_elems):
                ip = network[1][z]
                self.assertEqual(str(ip_elem.get('version')),
                                 str(ip['version']))
                self.assertEqual(str(ip_elem.get('addr')),
                                 str(ip['addr']))

    def test_index(self):
        serializer = servers.ServerXMLSerializer()

        expected_server_href = 'http://localhost/v1.1/servers/1'
        expected_server_bookmark = 'http://localhost/servers/1'
        expected_server_href_2 = 'http://localhost/v1.1/servers/2'
        expected_server_bookmark_2 = 'http://localhost/servers/2'
        fixture = {"servers": [
            {
                "id": 1,
                "name": "test_server",
                'links': [
                    {
                        'href': expected_server_href,
                        'rel': 'self',
                    },
                    {
                        'href': expected_server_bookmark,
                        'rel': 'bookmark',
                    },
                ],
            },
            {
                "id": 2,
                "name": "test_server_2",
                'links': [
                    {
                        'href': expected_server_href_2,
                        'rel': 'self',
                    },
                    {
                        'href': expected_server_bookmark_2,
                        'rel': 'bookmark',
                    },
                ],
            },
        ]}

        output = serializer.serialize(fixture, 'index')
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'servers_index')
        server_elems = root.findall('{0}server'.format(NS))
        self.assertEqual(len(server_elems), 2)
        for i, server_elem in enumerate(server_elems):
            server_dict = fixture['servers'][i]
            for key in ['name', 'id']:
                self.assertEqual(server_elem.get(key), str(server_dict[key]))

            link_nodes = server_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(server_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

    def test_detail(self):
        serializer = servers.ServerXMLSerializer()

        expected_server_href = 'http://localhost/v1.1/servers/1'
        expected_server_bookmark = 'http://localhost/servers/1'
        expected_image_bookmark = self.IMAGE_BOOKMARK
        expected_flavor_bookmark = self.FLAVOR_BOOKMARK
        expected_now = self.TIMESTAMP
        expected_uuid = FAKE_UUID

        expected_server_href_2 = 'http://localhost/v1.1/servers/2'
        expected_server_bookmark_2 = 'http://localhost/servers/2'
        fixture = {"servers": [
            {
                "id": 1,
                "uuid": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "fead::1234",
                "hostId": 'e4d909c290d0fb1ca068ffaddf22cbd0',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": expected_image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": expected_flavor_bookmark,
                        },
                    ],
                },
                "addresses": {
                    "network_one": [
                        {
                            "version": 4,
                            "addr": "67.23.10.138",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.138",
                        },
                    ],
                },
                "metadata": {
                    "Number": "1",
                },
                "links": [
                    {
                        "href": expected_server_href,
                        "rel": "self",
                    },
                    {
                        "href": expected_server_bookmark,
                        "rel": "bookmark",
                    },
                ],
            },
            {
                "id": 2,
                "uuid": FAKE_UUID,
                "user_id": 'fake',
                "tenant_id": 'fake',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                "progress": 100,
                "name": "test_server_2",
                "status": "ACTIVE",
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "fead::1234",
                "hostId": 'e4d909c290d0fb1ca068ffaddf22cbd0',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": expected_image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": expected_flavor_bookmark,
                        },
                    ],
                },
                "addresses": {
                    "network_one": [
                        {
                            "version": 4,
                            "addr": "67.23.10.138",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.138",
                        },
                    ],
                },
                "metadata": {
                    "Number": "2",
                },
                "links": [
                    {
                        "href": expected_server_href_2,
                        "rel": "self",
                    },
                    {
                        "href": expected_server_bookmark_2,
                        "rel": "bookmark",
                    },
                ],
            },
        ]}

        output = serializer.serialize(fixture, 'detail')
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'servers')
        server_elems = root.findall('{0}server'.format(NS))
        self.assertEqual(len(server_elems), 2)
        for i, server_elem in enumerate(server_elems):
            server_dict = fixture['servers'][i]

            for key in ['name', 'id', 'uuid', 'created', 'accessIPv4',
                        'updated', 'progress', 'status', 'hostId',
                        'accessIPv6']:
                self.assertEqual(server_elem.get(key), str(server_dict[key]))

            link_nodes = server_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(server_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

            metadata_root = server_elem.find('{0}metadata'.format(NS))
            metadata_elems = metadata_root.findall('{0}meta'.format(NS))
            for i, metadata_elem in enumerate(metadata_elems):
                (meta_key, meta_value) = server_dict['metadata'].items()[i]
                self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
                self.assertEqual(str(metadata_elem.text).strip(),
                                 str(meta_value))

            image_root = server_elem.find('{0}image'.format(NS))
            self.assertEqual(image_root.get('id'), server_dict['image']['id'])
            link_nodes = image_root.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 1)
            for i, link in enumerate(server_dict['image']['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

            flavor_root = server_elem.find('{0}flavor'.format(NS))
            self.assertEqual(flavor_root.get('id'),
                             server_dict['flavor']['id'])
            link_nodes = flavor_root.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 1)
            for i, link in enumerate(server_dict['flavor']['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

            addresses_root = server_elem.find('{0}addresses'.format(NS))
            addresses_dict = server_dict['addresses']
            network_elems = addresses_root.findall('{0}network'.format(NS))
            for i, network_elem in enumerate(network_elems):
                network = addresses_dict.items()[i]
                self.assertEqual(str(network_elem.get('id')), str(network[0]))
                ip_elems = network_elem.findall('{0}ip'.format(NS))
                for z, ip_elem in enumerate(ip_elems):
                    ip = network[1][z]
                    self.assertEqual(str(ip_elem.get('version')),
                                     str(ip['version']))
                    self.assertEqual(str(ip_elem.get('addr')),
                                     str(ip['addr']))

    def test_update(self):
        serializer = servers.ServerXMLSerializer()

        fixture = {
            "server": {
                "id": 1,
                "user_id": "fake",
                "tenant_id": "fake",
                "uuid": FAKE_UUID,
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "hostId": 'e4d909c290d0fb1ca068ffaddf22cbd0',
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "fead::1234",
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.IMAGE_BOOKMARK,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.FLAVOR_BOOKMARK,
                        },
                    ],
                },
                "addresses": {
                    "network_one": [
                        {
                            "version": 4,
                            "addr": "67.23.10.138",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.138",
                        },
                    ],
                    "network_two": [
                        {
                            "version": 4,
                            "addr": "67.23.10.139",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.139",
                        },
                    ],
                },
                "metadata": {
                    "Open": "Stack",
                    "Number": "1",
                },
                'links': [
                    {
                        'href': self.SERVER_HREF,
                        'rel': 'self',
                    },
                    {
                        'href': self.SERVER_BOOKMARK,
                        'rel': 'bookmark',
                    },
                ],
            }
        }

        output = serializer.serialize(fixture, 'update')
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        expected_server_href = self.SERVER_HREF
        expected_server_bookmark = self.SERVER_BOOKMARK
        expected_image_bookmark = self.IMAGE_BOOKMARK
        expected_flavor_bookmark = self.FLAVOR_BOOKMARK
        expected_now = self.TIMESTAMP
        expected_uuid = FAKE_UUID
        server_dict = fixture['server']

        for key in ['name', 'id', 'uuid', 'created', 'accessIPv4',
                    'updated', 'progress', 'status', 'hostId',
                    'accessIPv6']:
            self.assertEqual(root.get(key), str(server_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(server_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 2)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = server_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        image_root = root.find('{0}image'.format(NS))
        self.assertEqual(image_root.get('id'), server_dict['image']['id'])
        link_nodes = image_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['image']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        flavor_root = root.find('{0}flavor'.format(NS))
        self.assertEqual(flavor_root.get('id'), server_dict['flavor']['id'])
        link_nodes = flavor_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['flavor']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        addresses_root = root.find('{0}addresses'.format(NS))
        addresses_dict = server_dict['addresses']
        network_elems = addresses_root.findall('{0}network'.format(NS))
        self.assertEqual(len(network_elems), 2)
        for i, network_elem in enumerate(network_elems):
            network = addresses_dict.items()[i]
            self.assertEqual(str(network_elem.get('id')), str(network[0]))
            ip_elems = network_elem.findall('{0}ip'.format(NS))
            for z, ip_elem in enumerate(ip_elems):
                ip = network[1][z]
                self.assertEqual(str(ip_elem.get('version')),
                                 str(ip['version']))
                self.assertEqual(str(ip_elem.get('addr')),
                                 str(ip['addr']))

    def test_action(self):
        serializer = servers.ServerXMLSerializer()

        fixture = {
            "server": {
                "id": 1,
                "uuid": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "fead::1234",
                "hostId": "e4d909c290d0fb1ca068ffaddf22cbd0",
                "adminPass": "test_password",
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.IMAGE_BOOKMARK,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.FLAVOR_BOOKMARK,
                        },
                    ],
                },
                "addresses": {
                    "network_one": [
                        {
                            "version": 4,
                            "addr": "67.23.10.138",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.138",
                        },
                    ],
                    "network_two": [
                        {
                            "version": 4,
                            "addr": "67.23.10.139",
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.139",
                        },
                    ],
                },
                "metadata": {
                    "Open": "Stack",
                    "Number": "1",
                },
                'links': [
                    {
                        'href': self.SERVER_HREF,
                        'rel': 'self',
                    },
                    {
                        'href': self.SERVER_BOOKMARK,
                        'rel': 'bookmark',
                    },
                ],
            }
        }

        output = serializer.serialize(fixture, 'action')
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        expected_server_href = self.SERVER_HREF
        expected_server_bookmark = self.SERVER_BOOKMARK
        expected_image_bookmark = self.IMAGE_BOOKMARK
        expected_flavor_bookmark = self.FLAVOR_BOOKMARK
        expected_now = self.TIMESTAMP
        expected_uuid = FAKE_UUID
        server_dict = fixture['server']

        for key in ['name', 'id', 'uuid', 'created', 'accessIPv4',
                    'updated', 'progress', 'status', 'hostId',
                    'accessIPv6', 'adminPass']:
            self.assertEqual(root.get(key), str(server_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(server_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 2)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = server_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        image_root = root.find('{0}image'.format(NS))
        self.assertEqual(image_root.get('id'), server_dict['image']['id'])
        link_nodes = image_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['image']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        flavor_root = root.find('{0}flavor'.format(NS))
        self.assertEqual(flavor_root.get('id'), server_dict['flavor']['id'])
        link_nodes = flavor_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 1)
        for i, link in enumerate(server_dict['flavor']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        addresses_root = root.find('{0}addresses'.format(NS))
        addresses_dict = server_dict['addresses']
        network_elems = addresses_root.findall('{0}network'.format(NS))
        self.assertEqual(len(network_elems), 2)
        for i, network_elem in enumerate(network_elems):
            network = addresses_dict.items()[i]
            self.assertEqual(str(network_elem.get('id')), str(network[0]))
            ip_elems = network_elem.findall('{0}ip'.format(NS))
            for z, ip_elem in enumerate(ip_elems):
                ip = network[1][z]
                self.assertEqual(str(ip_elem.get('version')),
                                 str(ip['version']))
                self.assertEqual(str(ip_elem.get('addr')),
                                 str(ip['addr']))
