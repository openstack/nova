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

import datetime
import json
import urlparse

import iso8601
from lxml import etree
import webob

import nova.api.openstack.compute
from nova.api.openstack.compute import ips
from nova.api.openstack.compute import servers
from nova.api.openstack.compute import views
from nova.api.openstack import xmlutil
import nova.compute.api
from nova.compute import instance_types
from nova.compute import task_states
from nova.compute import vm_states
import nova.db
from nova.db.sqlalchemy import models
from nova import flags
import nova.image.fake
import nova.rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_network
from nova import utils


FLAGS = flags.FLAGS
FAKE_UUID = fakes.FAKE_UUID
NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
XPATH_NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/compute/api/v1.1'
}


def fake_gen_uuid():
    return FAKE_UUID


def return_servers_by_reservation(context, reservation_id=""):
    return [fakes.stub_instance(i + 1,
            reservation_id=reservation_id) for i in xrange(5)]


def return_servers_by_reservation_empty(context, reservation_id=""):
    return []


def return_security_group(context, instance_id, security_group_id):
    pass


def instance_update(context, instance_id, values):
    inst = fakes.stub_instance(instance_id, name=values.get('display_name'))
    return (inst, inst)


def fake_compute_api(cls, req, id):
    return True


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance_id, password):
        self.instance_id = instance_id
        self.password = password


class ServersControllerTest(test.TestCase):
    def setUp(self):
        super(ServersControllerTest, self).setUp()
        self.flags(verbose=True, use_ipv6=False)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_image_service(self.stubs)
        return_server = fakes.fake_instance_get()
        return_servers = fakes.fake_instance_get_all_by_filters()
        self.stubs.Set(nova.db, 'instance_get_all_by_filters',
                return_servers)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server)
        self.stubs.Set(nova.db, 'instance_get_all_by_project',
                       return_servers)
        self.stubs.Set(nova.db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(nova.db, 'instance_update_and_get_original',
                instance_update)

        self.controller = servers.Controller()
        self.ips_controller = ips.Controller()

        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs,
                                                          spectacular=True)

    def test_get_server_by_uuid(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        res_dict = self.controller.show(req, FAKE_UUID)
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)

    def test_unique_host_id(self):
        """Create two servers with the same host and different
           project_ids and check that the hostId's are unique"""
        def return_instance_with_host(self, *args):
            project_id = str(utils.gen_uuid())
            return fakes.stub_instance(id=1, uuid=FAKE_UUID,
                                       project_id=project_id,
                                       host='fake_host')

        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_instance_with_host)
        self.stubs.Set(nova.db, 'instance_get',
                       return_instance_with_host)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        server1 = self.controller.show(req, FAKE_UUID)
        server2 = self.controller.show(req, FAKE_UUID)

        self.assertNotEqual(server1['server']['hostId'],
                            server2['server']['hostId'])

    def test_get_server_by_id(self):
        self.flags(use_ipv6=True)
        image_bookmark = "http://localhost/fake/images/10"
        flavor_bookmark = "http://localhost/fake/flavors/1"

        uuid = FAKE_UUID
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)

        expected_server = {
            "server": {
                "id": uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {
                    "seq": "1",
                },
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/servers/%s" % uuid,
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/%s" % uuid,
                    },
                ],
            }
        }

        self.assertDictMatch(res_dict, expected_server)

    def test_get_server_with_active_status_by_id(self):
        image_bookmark = "http://localhost/fake/images/10"
        flavor_bookmark = "http://localhost/fake/flavors/1"

        new_return_server = fakes.fake_instance_get(
                vm_state=vm_states.ACTIVE, progress=100)
        self.stubs.Set(nova.db, 'instance_get_by_uuid', new_return_server)

        uuid = FAKE_UUID
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        expected_server = {
            "server": {
                "id": uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {
                    "seq": "1",
                },
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/servers/%s" % uuid,
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/%s" % uuid,
                    },
                ],
            }
        }

        self.assertDictMatch(res_dict, expected_server)

    def test_get_server_with_id_image_ref_by_id(self):
        image_ref = "10"
        image_bookmark = "http://localhost/fake/images/10"
        flavor_id = "1"
        flavor_bookmark = "http://localhost/fake/flavors/1"

        new_return_server = fakes.fake_instance_get(
                vm_state=vm_states.ACTIVE, image_ref=image_ref,
                flavor_id=flavor_id, progress=100)
        self.stubs.Set(nova.db, 'instance_get_by_uuid', new_return_server)

        uuid = FAKE_UUID
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        expected_server = {
            "server": {
                "id": uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {
                    "seq": "1",
                },
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/servers/%s" % uuid,
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/%s" % uuid,
                    },
                ],
            }
        }

        self.assertDictMatch(res_dict, expected_server)

    def test_get_server_addresses_from_cache(self):
        pub0 = ('172.19.0.1', '172.19.0.2',)
        pub1 = ('1.2.3.4',)
        pub2 = ('b33f::fdee:ddff:fecc:bbaa',)
        priv0 = ('192.168.0.3', '192.168.0.4',)

        def _ip(ip):
            return {'address': ip, 'type': 'fixed'}

        nw_cache = [
            {'address': 'aa:aa:aa:aa:aa:aa',
             'id': 1,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'public',
                         'subnets': [{'cidr': '172.19.0.0/24',
                                      'ips': [_ip(ip) for ip in pub0]},
                                      {'cidr': '1.2.3.0/16',
                                       'ips': [_ip(ip) for ip in pub1]},
                                      {'cidr': 'b33f::/64',
                                       'ips': [_ip(ip) for ip in pub2]}]}},
            {'address': 'bb:bb:bb:bb:bb:bb',
             'id': 2,
             'network': {'bridge': 'br1',
                         'id': 2,
                         'label': 'private',
                         'subnets': [{'cidr': '192.168.0.0/24',
                                      'ips': [_ip(ip) for ip in priv0]}]}}]

        return_server = fakes.fake_instance_get(nw_cache=nw_cache)
        self.stubs.Set(nova.db, 'instance_get_by_uuid', return_server)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/ips' % FAKE_UUID)
        res_dict = self.ips_controller.index(req, FAKE_UUID)

        expected = {
            'addresses': {
                'private': [
                    {'version': 4, 'addr': '192.168.0.3'},
                    {'version': 4, 'addr': '192.168.0.4'},
                ],
                'public': [
                    {'version': 4, 'addr': '172.19.0.1'},
                    {'version': 4, 'addr': '172.19.0.2'},
                    {'version': 4, 'addr': '1.2.3.4'},
                    {'version': 6, 'addr': 'b33f::fdee:ddff:fecc:bbaa'},
                ],
            },
        }
        self.assertDictMatch(res_dict, expected)

    def test_get_server_addresses_nonexistant_network(self):
        url = '/v2/fake/servers/%s/ips/network_0' % FAKE_UUID
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPNotFound, self.ips_controller.show,
                          req, FAKE_UUID, 'network_0')

    def test_get_server_addresses_nonexistant_server(self):
        def fake_instance_get(*args, **kwargs):
            raise nova.exception.InstanceNotFound()

        self.stubs.Set(nova.db, 'instance_get_by_uuid', fake_instance_get)

        server_id = str(utils.gen_uuid())
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/ips' % server_id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.ips_controller.index, req, server_id)

    def test_get_server_list_with_reservation_id(self):
        self.stubs.Set(nova.db, 'instance_get_all_by_reservation',
                       return_servers_by_reservation)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?reservation_id=foo')
        res_dict = self.controller.index(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_empty(self):
        self.stubs.Set(nova.db, 'instance_get_all_by_reservation',
                       return_servers_by_reservation_empty)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail?'
                                      'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_details(self):
        self.stubs.Set(nova.db, 'instance_get_all_by_reservation',
                       return_servers_by_reservation)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail?'
                                      'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        res_dict = self.controller.index(req)

        self.assertEqual(len(res_dict['servers']), 5)
        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['name'], 'server%d' % (i + 1))
            self.assertEqual(s.get('image', None), None)

            expected_links = [
                {
                    "rel": "self",
                    "href": "http://localhost/v2/fake/servers/%s" % s['id'],
                },
                {
                    "rel": "bookmark",
                    "href": "http://localhost/fake/servers/%s" % s['id'],
                },
            ]

            self.assertEqual(s['links'], expected_links)

    def test_get_servers_with_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers?limit=3')
        res_dict = self.controller.index(req)

        servers = res_dict['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in xrange(len(servers))])

        servers_links = res_dict['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')
        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual('/v2/fake/servers', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected_params = {'limit': ['3'],
                           'marker': [fakes.get_fake_uuid(2)]}
        self.assertDictMatch(expected_params, params)

    def test_get_servers_with_limit_bad_value(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers?limit=aaa')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_server_details_with_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail?limit=3')
        res = self.controller.detail(req)

        servers = res['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in xrange(len(servers))])

        servers_links = res['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual('/v2/fake/servers', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected = {'limit': ['3'], 'marker': [fakes.get_fake_uuid(2)]}
        self.assertDictMatch(expected, params)

    def test_get_server_details_with_limit_bad_value(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail?limit=aaa')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail, req)

    def test_get_server_details_with_limit_and_other_params(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail'
                                      '?limit=3&blah=2:t')
        res = self.controller.detail(req)

        servers = res['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in xrange(len(servers))])

        servers_links = res['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual('/v2/fake/servers', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)

        self.assertDictMatch({'limit': ['3'], 'blah': ['2:t'],
                              'marker': [fakes.get_fake_uuid(2)]}, params)

    def test_get_servers_with_too_big_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers?limit=30')
        res_dict = self.controller.index(req)
        self.assertTrue('servers_links' not in res_dict)

    def test_get_servers_with_bad_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers?limit=asdf')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_servers_with_marker(self):
        url = '/v2/fake/servers?marker=%s' % fakes.get_fake_uuid(2)
        req = fakes.HTTPRequest.blank(url)
        servers = self.controller.index(req)['servers']
        self.assertEqual([s['name'] for s in servers], ["server4", "server5"])

    def test_get_servers_with_limit_and_marker(self):
        url = '/v2/fake/servers?limit=2&marker=%s' % fakes.get_fake_uuid(1)
        req = fakes.HTTPRequest.blank(url)
        servers = self.controller.index(req)['servers']
        self.assertEqual([s['name'] for s in servers], ['server3', 'server4'])

    def test_get_servers_with_bad_marker(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers?limit=2&marker=asdf')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_servers_with_bad_option(self):
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?unknownoption=whee')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_image(self):
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('image' in search_opts)
            self.assertEqual(search_opts['image'], '12345')
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?image=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_tenant_id_filter_converts_to_project_id_for_admin(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc'):
            self.assertNotEqual(filters, None)
            self.assertEqual(filters['project_id'], 'fake')
            self.assertFalse(filters.get('tenant_id'))
            return [fakes.stub_instance(100)]

        self.stubs.Set(nova.db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?tenant_id=fake',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertTrue('servers' in res)

    def test_admin_restricted_tenant(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc'):
            self.assertNotEqual(filters, None)
            self.assertEqual(filters['project_id'], 'fake')
            return [fakes.stub_instance(100)]

        self.stubs.Set(nova.db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertTrue('servers' in res)

    def test_admin_all_tenants(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc'):
            self.assertNotEqual(filters, None)
            self.assertTrue('project_id' not in filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(nova.db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?all_tenants=1',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertTrue('servers' in res)

    def test_all_tenants(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc'):
            self.assertNotEqual(filters, None)
            self.assertEqual(filters['project_id'], 'fake')
            return [fakes.stub_instance(100)]

        self.stubs.Set(nova.db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?all_tenants=1')
        res = self.controller.index(req)

        self.assertTrue('servers' in res)

    def test_get_servers_allows_flavor(self):
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('flavor' in search_opts)
            # flavor is an integer ID
            self.assertEqual(search_opts['flavor'], '12345')
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?flavor=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_status(self):
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('vm_state' in search_opts)
            self.assertEqual(search_opts['vm_state'], vm_states.ACTIVE)
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?status=active')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_invalid_status(self):
        """Test getting servers by invalid status"""
        req = fakes.HTTPRequest.blank('/v2/fake/servers?status=unknown',
                                      use_admin_context=False)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index, req)

    def test_get_servers_allows_name(self):
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('name' in search_opts)
            self.assertEqual(search_opts['name'], 'whee.*')
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?name=whee.*')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_changes_since(self):
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('changes-since' in search_opts)
            changes_since = datetime.datetime(2011, 1, 24, 17, 8, 1,
                                              tzinfo=iso8601.iso8601.UTC)
            self.assertEqual(search_opts['changes-since'], changes_since)
            self.assertTrue('deleted' not in search_opts)
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        params = 'changes-since=2011-01-24T17:08:01Z'
        req = fakes.HTTPRequest.blank('/v2/fake/servers?%s' % params)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_changes_since_bad_value(self):
        params = 'changes-since=asdf'
        req = fakes.HTTPRequest.blank('/v2/fake/servers?%s' % params)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index, req)

    def test_get_servers_admin_filters_as_user(self):
        """Test getting servers by admin-only or unknown options when
        context is not admin. Make sure the admin and unknown options
        are stripped before they get to compute_api.get_all()
        """
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            # Allowed by user
            self.assertTrue('name' in search_opts)
            # OSAPI converts status to vm_state
            self.assertTrue('vm_state' in search_opts)
            # Allowed only by admins with admin API on
            self.assertFalse('ip' in search_opts)
            self.assertFalse('unknown_option' in search_opts)
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = fakes.HTTPRequest.blank('/v2/fake/servers?%s' % query_str)
        res = self.controller.index(req)

        servers = res['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_admin_options_as_admin(self):
        """Test getting servers by admin-only or unknown options when
        context is admin. All options should be passed
        """
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            # Allowed by user
            self.assertTrue('name' in search_opts)
            # OSAPI converts status to vm_state
            self.assertTrue('vm_state' in search_opts)
            # Allowed only by admins with admin API on
            self.assertTrue('ip' in search_opts)
            self.assertTrue('unknown_option' in search_opts)
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = fakes.HTTPRequest.blank('/v2/fake/servers?%s' % query_str,
                                      use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_admin_allows_ip(self):
        """Test getting servers by ip with admin_api enabled and
        admin context
        """
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('ip' in search_opts)
            self.assertEqual(search_opts['ip'], '10\..*')
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?ip=10\..*',
                                      use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_admin_allows_ip6(self):
        """Test getting servers by ip6 with admin_api enabled and
        admin context
        """
        server_uuid = str(utils.gen_uuid())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc'):
            self.assertNotEqual(search_opts, None)
            self.assertTrue('ip6' in search_opts)
            self.assertEqual(search_opts['ip6'], 'ffff.*')
            return [fakes.stub_instance(100, uuid=server_uuid)]

        self.stubs.Set(nova.compute.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/v2/fake/servers?ip6=ffff.*',
                                      use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_update_server_no_body(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update, req, FAKE_UUID, None)

    def test_update_server_all_attributes(self):
        self.stubs.Set(nova.db, 'instance_get',
                fakes.fake_instance_get(name='server_test',
                                        access_ipv4='0.0.0.0',
                                        access_ipv6='beef::0123'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'accessIPv4': '0.0.0.0',
                  'accessIPv6': 'beef::0123',
               }}
        req.body = json.dumps(body)
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')
        self.assertEqual(res_dict['server']['accessIPv4'], '0.0.0.0')
        self.assertEqual(res_dict['server']['accessIPv6'], 'beef::0123')

    def test_update_server_name(self):
        self.stubs.Set(nova.db, 'instance_get',
                fakes.fake_instance_get(name='server_test'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'name': 'server_test'}}
        req.body = json.dumps(body)
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_name_too_long(self):
        self.stubs.Set(nova.db, 'instance_get',
                fakes.fake_instance_get(name='server_test'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'name': 'x' * 256}}
        req.body = json.dumps(body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                            req, FAKE_UUID, body)

    def test_update_server_access_ipv4(self):
        self.stubs.Set(nova.db, 'instance_get',
                fakes.fake_instance_get(access_ipv4='0.0.0.0'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'accessIPv4': '0.0.0.0'}}
        req.body = json.dumps(body)
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv4'], '0.0.0.0')

    def test_update_server_access_ipv4_bad_format(self):
        self.stubs.Set(nova.db, 'instance_get',
                fakes.fake_instance_get(access_ipv4='0.0.0.0'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'accessIPv4': 'bad_format'}}
        req.body = json.dumps(body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                            req, FAKE_UUID, body)

    def test_update_server_access_ipv6(self):
        self.stubs.Set(nova.db, 'instance_get',
                fakes.fake_instance_get(access_ipv6='beef::0123'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'accessIPv6': 'beef::0123'}}
        req.body = json.dumps(body)
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv6'], 'beef::0123')

    def test_update_server_access_ipv6_bad_format(self):
        self.stubs.Set(nova.db, 'instance_get',
                fakes.fake_instance_get(access_ipv6='beef::0123'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'accessIPv6': 'bad_format'}}
        req.body = json.dumps(body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                            req, FAKE_UUID, body)

    def test_update_server_adminPass_ignored(self):
        inst_dict = dict(name='server_test', adminPass='bacon')
        body = dict(server=inst_dict)

        def server_update(context, id, params):
            filtered_dict = {
                'display_name': 'server_test',
            }
            self.assertEqual(params, filtered_dict)
            filtered_dict['uuid'] = id
            return filtered_dict

        self.stubs.Set(nova.db, 'instance_update', server_update)
        # FIXME (comstud)
        #        self.stubs.Set(nova.db, 'instance_get',
        #                return_server_with_attributes(name='server_test'))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = json.dumps(body)
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_not_found(self):
        def fake_get(*args, **kwargs):
            raise nova.exception.InstanceNotFound()

        self.stubs.Set(nova.compute.API, 'get', fake_get)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'name': 'server_test'}}
        req.body = json.dumps(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body)

    def test_update_server_not_found_on_update(self):
        def fake_update(*args, **kwargs):
            raise nova.exception.InstanceNotFound()

        self.stubs.Set(nova.compute.API, 'update', fake_update)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'name': 'server_test'}}
        req.body = json.dumps(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body)

    def test_rebuild_instance_with_access_ipv4_bad_format(self):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        access_ipv4 = 'bad_format'
        access_ipv6 = 'fead::1234'
        body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': image_href,
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers/a/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, req, FAKE_UUID, body)

    def test_rebuild_instance_with_blank_metadata_key(self):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        access_ipv4 = '0.0.0.0'
        access_ipv6 = 'fead::1234'
        body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': image_href,
                'accessIPv4': access_ipv4,
                'accessIPv6': access_ipv6,
                'metadata': {
                    '': 'world',
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers/a/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, req, FAKE_UUID, body)

    def test_rebuild_instance_with_metadata_key_too_long(self):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        access_ipv4 = '0.0.0.0'
        access_ipv6 = 'fead::1234'
        body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': image_href,
                'accessIPv4': access_ipv4,
                'accessIPv6': access_ipv6,
                'metadata': {
                    ('a' * 260): 'world',
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers/a/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, req, FAKE_UUID, body)

    def test_rebuild_instance_with_metadata_value_too_long(self):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        access_ipv4 = '0.0.0.0'
        access_ipv6 = 'fead::1234'
        body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': image_href,
                'accessIPv4': access_ipv4,
                'accessIPv6': access_ipv6,
                'metadata': {
                    'key1': ('a' * 260),
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers/a/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, req, FAKE_UUID, body)

    def test_rebuild_instance_fails_when_min_ram_too_small(self):
        # make min_ram larger than our instance ram size
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                name='public image', is_public=True,
                status='active', properties={'key1': 'value1'},
                min_ram="4096", min_disk="10")
        self.stubs.Set(nova.compute.api.API, '_get_image',
                fake_get_image)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': image_href,
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers/a/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, req, FAKE_UUID, body)

    def test_rebuild_instance_fails_when_min_disk_too_small(self):
        # make min_disk larger than our instance disk size
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                name='public image', is_public=True,
                status='active', properties={'key1': 'value1'},
                min_ram="128", min_disk="100000")
        self.stubs.Set(nova.compute.api.API, '_get_image',
                fake_get_image)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': image_href,
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers/a/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, req, FAKE_UUID, body)

    def test_rebuild_instance_with_access_ipv6_bad_format(self):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        access_ipv4 = '1.2.3.4'
        access_ipv6 = 'bad_format'
        body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': image_href,
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers/a/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, req, FAKE_UUID, body)

    def test_get_all_server_details(self):
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
        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail')
        res_dict = self.controller.detail(req)

        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['hostId'], '')
            self.assertEqual(s['name'], 'server%d' % (i + 1))
            self.assertEqual(s['image'], expected_image)
            self.assertEqual(s['flavor'], expected_flavor)
            self.assertEqual(s['status'], 'BUILD')
            self.assertEqual(s['metadata']['seq'], str(i + 1))

    def test_get_all_server_details_with_host(self):
        '''
        We want to make sure that if two instances are on the same host, then
        they return the same hostId. If two instances are on different hosts,
        they should return different hostId's. In this test, there are 5
        instances - 2 on one host and 3 on another.
        '''

        def return_servers_with_host(context, *args, **kwargs):
            return [fakes.stub_instance(i + 1, 'fake', 'fake', host=i % 2,
                                  uuid=fakes.get_fake_uuid(i))
                    for i in xrange(5)]

        self.stubs.Set(nova.db, 'instance_get_all_by_filters',
                return_servers_with_host)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/detail')
        res_dict = self.controller.detail(req)

        server_list = res_dict['servers']
        host_ids = [server_list[0]['hostId'], server_list[1]['hostId']]
        self.assertTrue(host_ids[0] and host_ids[1])
        self.assertNotEqual(host_ids[0], host_ids[1])

        for i, s in enumerate(server_list):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['hostId'], host_ids[i % 2])
            self.assertEqual(s['name'], 'server%d' % (i + 1))

    def test_delete_server_instance(self):
        fakes.stub_out_instance_quota(self.stubs, 0)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'DELETE'

        self.server_delete_called = False

        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))

        def instance_destroy_mock(context, id):
            self.server_delete_called = True
        self.stubs.Set(nova.db, 'instance_destroy', instance_destroy_mock)

        self.controller.delete(req, FAKE_UUID)

        self.assertEqual(self.server_delete_called, True)

    def test_delete_server_instance_while_building(self):
        fakes.stub_out_instance_quota(self.stubs, 0)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'DELETE'

        self.server_delete_called = False

        def instance_destroy_mock(context, id):
            self.server_delete_called = True
        self.stubs.Set(nova.db, 'instance_destroy', instance_destroy_mock)

        self.controller.delete(req, FAKE_UUID)

        self.assertEqual(self.server_delete_called, True)

    def test_delete_server_instance_while_resize(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        req.method = 'DELETE'

        self.server_delete_called = False

        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.RESIZING))

        def instance_destroy_mock(context, id):
            self.server_delete_called = True
        self.stubs.Set(nova.db, 'instance_destroy', instance_destroy_mock)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.delete,
                          req,
                          FAKE_UUID)


class ServerStatusTest(test.TestCase):

    def setUp(self):
        super(ServerStatusTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)

        self.controller = servers.Controller()

    def _get_with_state(self, vm_state, task_state=None):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_state,
                                        task_state=task_state))

        request = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % FAKE_UUID)
        return self.controller.show(request, FAKE_UUID)

    def test_active(self):
        response = self._get_with_state(vm_states.ACTIVE)
        self.assertEqual(response['server']['status'], 'ACTIVE')

    def test_reboot(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBOOTING)
        self.assertEqual(response['server']['status'], 'REBOOT')

    def test_reboot_hard(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBOOTING_HARD)
        self.assertEqual(response['server']['status'], 'HARD_REBOOT')

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

    def test_revert_resize(self):
        response = self._get_with_state(vm_states.RESIZING,
                                        task_states.RESIZE_REVERTING)
        self.assertEqual(response['server']['status'], 'REVERT_RESIZE')

    def test_password_update(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.UPDATING_PASSWORD)
        self.assertEqual(response['server']['status'], 'PASSWORD')

    def test_stopped(self):
        response = self._get_with_state(vm_states.STOPPED)
        self.assertEqual(response['server']['status'], 'STOPPED')


class ServersControllerCreateTest(test.TestCase):

    def setUp(self):
        """Shared implementation for tests below that create instance"""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(verbose=True,
                   enable_instance_password=True)
        self.instance_cache_num = 0
        self.instance_cache = {}

        self.controller = servers.Controller()

        def instance_create(context, inst):
            inst_type = instance_types.get_instance_type_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = {
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': FAKE_UUID,
                'instance_type': dict(inst_type),
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "config_drive": None,
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
            }
            self.instance_cache[instance['id']] = instance
            return instance

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache[instance_id]

        def rpc_call_wrapper(context, topic, msg, timeout=None):
            """Stub out the scheduler creating the instance entry"""
            if (topic == FLAGS.scheduler_topic and
                msg['method'] == 'run_instance'):
                request_spec = msg['args']['request_spec']
                num_instances = request_spec.get('num_instances', 1)
                instances = []
                for x in xrange(num_instances):
                    instances.append(instance_create(context,
                        request_spec['instance_properties']))
                return instances

        def server_update(context, instance_id, params):
            inst = self.instance_cache[instance_id]
            inst.update(params)
            return (inst, inst)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_image_service(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(utils, 'gen_uuid', fake_gen_uuid)
        self.stubs.Set(nova.db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(nova.db, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(nova.db, 'instance_create', instance_create)
        self.stubs.Set(nova.db, 'instance_system_metadata_update',
                fake_method)
        self.stubs.Set(nova.db, 'instance_get', instance_get)
        self.stubs.Set(nova.rpc, 'cast', fake_method)
        self.stubs.Set(nova.rpc, 'call', rpc_call_wrapper)
        self.stubs.Set(nova.db, 'instance_update_and_get_original',
                server_update)
        self.stubs.Set(nova.rpc, 'queue_get_for', queue_get_for)
        self.stubs.Set(nova.network.manager.VlanManager, 'allocate_fixed_ip',
                       fake_method)

    def _check_admin_pass_len(self, server_dict):
        """ utility function - check server_dict for adminPass
        length.

        """
        self.assertEqual(FLAGS.password_length,
                         len(server_dict["adminPass"]))

    def _check_admin_pass_missing(self, server_dict):
        """ utility function - check server_dict for absence
        of adminPass
        """
        self.assertTrue("adminPass" not in server_dict)

    def _test_create_instance(self):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        body = dict(server=dict(
            name='server_test', imageRef=image_uuid, flavorRef=2,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        server = self.controller.create(req, body).obj['server']

        self._check_admin_pass_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_server_bad_image_href(self):
        image_href = 1
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'min_count': 1,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_create_multiple_instances(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
                'personality': []
            }
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_pass_len(res["server"])

    def test_create_multiple_instances_pass_disabled(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        self.flags(enable_instance_password=False)
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
                'personality': []
            }
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_pass_missing(res["server"])

    def test_create_multiple_instances_resv_id_return(self):
        """Test creating multiple instances with asking for
        reservation_id
        """
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
                'personality': [],
                'return_reservation_id': True
            }
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body)

        reservation_id = res.get('reservation_id')
        self.assertNotEqual(reservation_id, "")
        self.assertNotEqual(reservation_id, None)
        self.assertTrue(len(reservation_id) > 1)

    def test_create_instance_image_ref_is_bookmark(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/fake/images/%s' % image_uuid
        flavor_ref = 'http://localhost/fake/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_image_ref_is_invalid(self):
        image_uuid = 'this_is_not_a_valid_uuid'
        image_href = 'http://localhost/fake/images/%s' % image_uuid
        flavor_ref = 'http://localhost/fake/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_create_instance_no_key_pair(self):
        fakes.stub_out_key_pair_funcs(self.stubs, have_key_pair=False)
        self._test_create_instance()

    def test_create_instance_with_access_ip(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        flavor_ref = 'http://localhost/fake/flavors/3'
        access_ipv4 = '1.2.3.4'
        access_ipv6 = 'fead::1234'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self._check_admin_pass_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_with_access_ip_pass_disabled(self):
        # test with admin passwords disabled See lp bug 921814
        self.flags(enable_instance_password=False)

        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        flavor_ref = 'http://localhost/fake/flavors/3'
        access_ipv4 = '1.2.3.4'
        access_ipv6 = 'fead::1234'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self._check_admin_pass_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_bad_format_access_ip_v4(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        flavor_ref = 'http://localhost/fake/flavors/3'
        access_ipv4 = 'bad_format'
        access_ipv6 = 'fead::1234'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                            req, body)

    def test_create_instance_bad_format_access_ip_v6(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/fake/images/%s' % image_uuid
        flavor_ref = 'http://localhost/fake/flavors/3'
        access_ipv4 = '1.2.3.4'
        access_ipv6 = 'bad_format'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                            req, body)

    def test_create_instance_name_too_long(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'name': 'X' * 256,
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                            req, body)

    def test_create_instance(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self._check_admin_pass_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_pass_disabled(self):
        self.flags(enable_instance_password=False)
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self._check_admin_pass_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_too_much_metadata(self):
        self.flags(quota_metadata_items=1)
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                    'vote': 'fiddletown',
                },
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, body)

    def test_create_instance_metadata_key_too_long(self):
        self.flags(quota_metadata_items=1)
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    ('a' * 260): '12345',
                },
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_metadata_value_too_long(self):
        self.flags(quota_metadata_items=1)
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'key1': ('a' * 260),
                },
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_metadata_key_blank(self):
        self.flags(quota_metadata_items=1)
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    '': '12345',
                },
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_invalid_key_name(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = 'http://localhost/flavors/3'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            key_name='nonexistentkey'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_valid_key_name(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/flavors/3'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            key_name='key'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_pass_len(res["server"])

    def test_create_instance_invalid_flavor_href(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = 'http://localhost/v2/flavors/asdf'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_invalid_flavor_id_int(self):
        image_href = 'http://localhost/v2/fake/images/2'
        flavor_ref = -1
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_bad_flavor_href(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = 'http://localhost/v2/flavors/17'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_with_config_drive(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v2/fake/flavors/3'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_with_config_drive_as_id(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v2/fake/flavors/3'
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
                'config_drive': image_href,
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_with_bad_config_drive(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v2/fake/flavors/3'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_without_config_drive(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v2/fake/flavors/3'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_bad_href(self):
        image_href = 'asdf'
        flavor_ref = 'http://localhost/v2/flavors/3'
        body = dict(server=dict(
            name='server_test', imageRef=image_href, flavorRef=flavor_ref,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_instance_local_href(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v2/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_uuid,
                'flavorRef': flavor_ref,
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_admin_pass(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_uuid,
                'flavorRef': 3,
                'adminPass': 'testpass',
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertEqual(server['adminPass'], body['server']['adminPass'])

    def test_create_instance_admin_pass_pass_disabled(self):
        self.flags(enable_instance_password=False)
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_uuid,
                'flavorRef': 3,
                'adminPass': 'testpass',
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = "application/json"
        res = self.controller.create(req, body).obj

        server = res['server']
        self.assertTrue('adminPass' in body['server'])
        self.assertTrue('adminPass' not in server)

    def test_create_instance_admin_pass_empty(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_uuid,
                'flavorRef': 3,
                'adminPass': '',
            },
        }

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = "application/json"

        # The fact that the action doesn't raise is enough validation
        self.controller.create(req, body)

    def test_create_instance_malformed_entity(self):
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        body = {'server': 'string'}
        req.body = json.dumps(body)
        req.headers['content-type'] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_location(self):
        selfhref = 'http://localhost/v2/fake/servers/%s' % FAKE_UUID
        bookhref = 'http://localhost/fake/servers/%s' % FAKE_UUID
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v2/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
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

        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'
        robj = self.controller.create(req, body)

        self.assertEqual(robj['Location'], selfhref)

    def test_create_instance_above_quota(self):
        fakes.stub_out_instance_quota(self.stubs, 0)
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        body = dict(server=dict(
            name='server_test', imageRef=image_uuid, flavorRef=2,
            metadata={'hello': 'world', 'open': 'stack'},
            personality={}))
        req = fakes.HTTPRequest.blank('/v2/fake/servers')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        try:
            server = self.controller.create(req, body).obj['server']
            self.fail('expected quota to be exceeded')
        except webob.exc.HTTPRequestEntityTooLarge as e:
            self.assertEquals(e.explanation,
                      _('Quota exceeded: already used 1 of 1 instances'))


class TestServerCreateRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerCreateRequestXMLDeserializer, self).setUp()
        self.deserializer = servers.CreateDeserializer()

    def test_minimal_request(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"/>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        accessIPv4="1.2.3.4"/>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        accessIPv6="fead::1234"/>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        accessIPv4="1.2.3.4"
        accessIPv6="fead::1234"/>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2"
        adminPass="1234"/>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="http://localhost:8774/v2/images/2"
        flavorRef="3"/>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "http://localhost:8774/v2/images/2",
                "flavorRef": "3",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_flavor_link(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="http://localhost:8774/v2/flavors/3"/>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "http://localhost:8774/v2/flavors/3",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_empty_metadata_personality(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2">
    <metadata/>
    <personality/>
</server>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2">
    <metadata>
        <meta key="one">two</meta>
        <meta key="open">snack</meta>
    </metadata>
</server>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2">
    <personality>
        <file path="/etc/banner.txt">MQ==</file>
        <file path="/etc/hosts">Mg==</file>
    </personality>
</server>"""
        request = self.deserializer.deserialize(serial_request)
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
        image_bookmark_link = ("http://servers.api.openstack.org/1234/"
                               "images/52415800-8b69-11e0-9b19-734f6f006e54")
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
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
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": ("http://servers.api.openstack.org/1234/"
                             "images/52415800-8b69-11e0-9b19-734f6f006e54"),
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks/>
</server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1" fixed_ip="10.0.1.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_two_networks(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1" fixed_ip="10.0.1.12"/>
       <network uuid="2" fixed_ip="10.0.2.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request)
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
<server xmlns="http://docs.openstack.org/compute/api/v2"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1" fixed_ip="10.0.1.12"/>
    </networks>
    <networks>
       <network uuid="2" fixed_ip="10.0.2.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_missing_id(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network fixed_ip="10.0.1.12"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_missing_fixed_ip(self):
        serial_request = """
<server xmlns="http://docs.openstack.org/compute/api/v2"
 name="new-server-test" imageRef="1" flavorRef="1">
    <networks>
       <network uuid="1"/>
    </networks>
</server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_empty_id(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     name="new-server-test" imageRef="1" flavorRef="1">
        <networks>
           <network uuid="" fixed_ip="10.0.1.12"/>
        </networks>
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "", "fixed_ip": "10.0.1.12"}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_one_network_empty_fixed_ip(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     name="new-server-test" imageRef="1" flavorRef="1">
        <networks>
           <network uuid="1" fixed_ip=""/>
        </networks>
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": ""}],
                }}
        self.assertEquals(request['body'], expected)

    def test_request_with_networks_duplicate_ids(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     name="new-server-test" imageRef="1" flavorRef="1">
        <networks>
           <network uuid="1" fixed_ip="10.0.1.12"/>
           <network uuid="1" fixed_ip="10.0.2.12"/>
        </networks>
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "networks": [{"uuid": "1", "fixed_ip": "10.0.1.12"},
                             {"uuid": "1", "fixed_ip": "10.0.2.12"}],
                }}
        self.assertEquals(request['body'], expected)


class TestAddressesXMLSerialization(test.TestCase):

    index_serializer = nova.api.openstack.compute.ips.AddressesTemplate()
    show_serializer = nova.api.openstack.compute.ips.NetworkTemplate()

    def test_xml_declaration(self):
        fixture = {
            'network_2': [
                {'addr': '192.168.0.1', 'version': 4},
                {'addr': 'fe80::beef', 'version': 6},
            ],
        }
        output = self.show_serializer.serialize(fixture)
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        fixture = {
            'network_2': [
                {'addr': '192.168.0.1', 'version': 4},
                {'addr': 'fe80::beef', 'version': 6},
            ],
        }
        output = self.show_serializer.serialize(fixture)
        root = etree.XML(output)
        network = fixture['network_2']
        self.assertEqual(str(root.get('id')), 'network_2')
        ip_elems = root.findall('{0}ip'.format(NS))
        for z, ip_elem in enumerate(ip_elems):
            ip = network[z]
            self.assertEqual(str(ip_elem.get('version')),
                             str(ip['version']))
            self.assertEqual(str(ip_elem.get('addr')),
                             str(ip['addr']))

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
        output = self.index_serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'addresses')
        addresses_dict = fixture['addresses']
        network_elems = root.findall('{0}network'.format(NS))
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


class ServersViewBuilderTest(test.TestCase):

    def setUp(self):
        super(ServersViewBuilderTest, self).setUp()
        self.flags(use_ipv6=True)
        self.instance = fakes.stub_instance(
            id=1,
            image_ref="5",
            uuid="deadbeef-feed-edee-beef-d0ea7beefedd",
            display_name="test_server",
            include_fake_metadata=False)

        privates = ['172.19.0.1']
        publics = ['192.168.0.3']
        public6s = ['b33f::fdee:ddff:fecc:bbaa']

        def nw_info(*args, **kwargs):
            return [(None, {'label': 'public',
                            'ips': [dict(ip=ip) for ip in publics],
                            'ip6s': [dict(ip=ip) for ip in public6s]}),
                    (None, {'label': 'private',
                            'ips': [dict(ip=ip) for ip in privates]})]

        def floaters(*args, **kwargs):
            return []

        fakes.stub_out_nw_api_get_instance_nw_info(self.stubs, nw_info)
        fakes.stub_out_nw_api_get_floating_ips_by_fixed_address(self.stubs,
                                                                floaters)

        self.uuid = self.instance['uuid']
        self.view_builder = views.servers.ViewBuilder()
        self.request = fakes.HTTPRequest.blank("/v2")

    def test_build_server(self):
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.basic(self.request, self.instance)
        self.assertDictMatch(output, expected_server)

    def test_build_server_with_project_id(self):
        expected_server = {
            "server": {
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/servers/%s" %
                                self.uuid,
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/servers/%s" % self.uuid,
                    },
                ],
            }
        }

        output = self.view_builder.basic(self.request, self.instance)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail(self):
        image_bookmark = "http://localhost/fake/images/5"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {},
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_fault(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = {
            'code': 404,
            'instance_uuid': self.uuid,
            'message': "HTTPNotFound",
            'details': "Stock details for test",
            'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
        }

        image_bookmark = "http://localhost/fake/images/5"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "name": "test_server",
                "status": "ERROR",
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
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {},
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
                "fault": {
                    "code": 404,
                    "created": "2010-10-10T12:00:00Z",
                    "message": "HTTPNotFound",
                    "details": "Stock details for test",
                },
            }
        }

        self.request.context = nova.context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_fault_no_details_not_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = {
            'code': 500,
            'instance_uuid': self.uuid,
            'message': "Error",
            'details': 'Stock details for test',
            'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
        }

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.context = nova.context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output['server']['fault'], expected_fault)

    def test_build_server_detail_with_fault_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = {
            'code': 500,
            'instance_uuid': self.uuid,
            'message': "Error",
            'details': 'Stock details for test',
            'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
        }

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error",
                          'details': 'Stock details for test'}

        self.request.context = nova.context.get_admin_context()
        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output['server']['fault'], expected_fault)

    def test_build_server_detail_with_fault_no_details_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = {
            'code': 500,
            'instance_uuid': self.uuid,
            'message': "Error",
            'details': '',
            'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
        }

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.context = nova.context.get_admin_context()
        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output['server']['fault'], expected_fault)

    def test_build_server_detail_with_fault_but_active(self):
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100
        self.instance['fault'] = {
            'code': 404,
            'instance_uuid': self.uuid,
            'message': "HTTPNotFound",
            'details': "Stock details for test",
            'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
        }

        image_bookmark = "http://localhost/fake/images/5"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid

        output = self.view_builder.show(self.request, self.instance)
        self.assertFalse('fault' in output['server'])

    def test_build_server_detail_active_status(self):
        #set the power state of the instance to running
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100
        image_bookmark = "http://localhost/fake/images/5"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {},
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_accessipv4(self):

        self.instance['access_ip_v4'] = '1.2.3.4'

        image_bookmark = "http://localhost/fake/images/5"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {},
                "config_drive": None,
                "accessIPv4": "1.2.3.4",
                "accessIPv6": "",
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_accessipv6(self):

        self.instance['access_ip_v6'] = 'fead::1234'

        image_bookmark = "http://localhost/fake/images/5"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {},
                "config_drive": None,
                "accessIPv4": "",
                "accessIPv6": "fead::1234",
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output, expected_server)

    def test_build_server_detail_with_metadata(self):

        metadata = []
        metadata.append(models.InstanceMetadata(key="Open", value="Stack"))
        self.instance['metadata'] = metadata

        image_bookmark = "http://localhost/fake/images/5"
        flavor_bookmark = "http://localhost/fake/flavors/1"
        self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
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
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100'},
                        {'version': 6, 'addr': '2001:db8:0:1::1'}
                    ]
                },
                "metadata": {"Open": "Stack"},
                "config_drive": None,
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertDictMatch(output, expected_server)


class ServerXMLSerializationTest(test.TestCase):

    TIMESTAMP = "2010-10-11T10:30:22Z"
    SERVER_HREF = 'http://localhost/v2/servers/%s' % FAKE_UUID
    SERVER_NEXT = 'http://localhost/v2/servers?limit=%s&marker=%s'
    SERVER_BOOKMARK = 'http://localhost/servers/%s' % FAKE_UUID
    IMAGE_BOOKMARK = 'http://localhost/images/5'
    FLAVOR_BOOKMARK = 'http://localhost/flavors/1'

    def test_xml_declaration(self):
        serializer = servers.ServerTemplate()

        fixture = {
            "server": {
                'id': FAKE_UUID,
                'user_id': 'fake_user_id',
                'tenant_id': 'fake_tenant_id',
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

        output = serializer.serialize(fixture)
        print output
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        serializer = servers.ServerTemplate()

        fixture = {
            "server": {
                "id": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
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

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = fixture['server']

        for key in ['name', 'id', 'created', 'accessIPv4',
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
        serializer = servers.FullServerTemplate()

        fixture = {
            "server": {
                "id": FAKE_UUID,
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

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = fixture['server']

        for key in ['name', 'id', 'created', 'accessIPv4',
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
        serializer = servers.MinimalServersTemplate()

        uuid1 = fakes.get_fake_uuid(1)
        uuid2 = fakes.get_fake_uuid(2)
        expected_server_href = 'http://localhost/v2/servers/%s' % uuid1
        expected_server_bookmark = 'http://localhost/servers/%s' % uuid1
        expected_server_href_2 = 'http://localhost/v2/servers/%s' % uuid2
        expected_server_bookmark_2 = 'http://localhost/servers/%s' % uuid2
        fixture = {"servers": [
            {
                "id": fakes.get_fake_uuid(1),
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
                "id": fakes.get_fake_uuid(2),
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

        output = serializer.serialize(fixture)
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

    def test_index_with_servers_links(self):
        serializer = servers.MinimalServersTemplate()

        uuid1 = fakes.get_fake_uuid(1)
        uuid2 = fakes.get_fake_uuid(2)
        expected_server_href = 'http://localhost/v2/servers/%s' % uuid1
        expected_server_next = self.SERVER_NEXT % (2, 2)
        expected_server_bookmark = 'http://localhost/servers/%s' % uuid1
        expected_server_href_2 = 'http://localhost/v2/servers/%s' % uuid2
        expected_server_bookmark_2 = 'http://localhost/servers/%s' % uuid2
        fixture = {"servers": [
            {
                "id": fakes.get_fake_uuid(1),
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
                "id": fakes.get_fake_uuid(2),
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
        ],
        "servers_links": [
            {
                'rel': 'next',
                'href': expected_server_next,
            },
        ]}

        output = serializer.serialize(fixture)
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

        # Check servers_links
        servers_links = root.findall('{0}link'.format(ATOMNS))
        for i, link in enumerate(fixture['servers_links']):
            for key, value in link.items():
                self.assertEqual(servers_links[i].get(key), value)

    def test_detail(self):
        serializer = servers.ServersTemplate()

        uuid1 = fakes.get_fake_uuid(1)
        expected_server_href = 'http://localhost/v2/servers/%s' % uuid1
        expected_server_bookmark = 'http://localhost/servers/%s' % uuid1
        expected_image_bookmark = self.IMAGE_BOOKMARK
        expected_flavor_bookmark = self.FLAVOR_BOOKMARK

        uuid2 = fakes.get_fake_uuid(2)
        expected_server_href_2 = 'http://localhost/v2/servers/%s' % uuid2
        expected_server_bookmark_2 = 'http://localhost/servers/%s' % uuid2
        fixture = {"servers": [
            {
                "id": fakes.get_fake_uuid(1),
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
                "id": fakes.get_fake_uuid(2),
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

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'servers')
        server_elems = root.findall('{0}server'.format(NS))
        self.assertEqual(len(server_elems), 2)
        for i, server_elem in enumerate(server_elems):
            server_dict = fixture['servers'][i]

            for key in ['name', 'id', 'created', 'accessIPv4',
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
        serializer = servers.ServerTemplate()

        fixture = {
            "server": {
                "id": FAKE_UUID,
                "user_id": "fake",
                "tenant_id": "fake",
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
                "fault": {
                    "code": 500,
                    "created": self.TIMESTAMP,
                    "message": "Error Message",
                    "details": "Fault details",
                }
            }
        }

        output = serializer.serialize(fixture)
        print output
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = fixture['server']

        for key in ['name', 'id', 'created', 'accessIPv4',
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

        fault_root = root.find('{0}fault'.format(NS))
        fault_dict = server_dict['fault']
        self.assertEqual(fault_root.get("code"), str(fault_dict["code"]))
        self.assertEqual(fault_root.get("created"), fault_dict["created"])
        msg_elem = fault_root.find('{0}message'.format(NS))
        self.assertEqual(msg_elem.text, fault_dict["message"])
        det_elem = fault_root.find('{0}details'.format(NS))
        self.assertEqual(det_elem.text, fault_dict["details"])

    def test_action(self):
        serializer = servers.FullServerTemplate()

        fixture = {
            "server": {
                "id": FAKE_UUID,
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

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = fixture['server']

        for key in ['name', 'id', 'created', 'accessIPv4',
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
