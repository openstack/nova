# Copyright 2010-2011 OpenStack Foundation
# Copyright 2011 Piston Cloud Computing, Inc.
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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
import uuid

import iso8601
from lxml import etree
import mox
from oslo.config import cfg
import six.moves.urllib.parse as urlparse
import testtools
import webob

from nova.api.openstack import compute
from nova.api.openstack.compute import ips
from nova.api.openstack.compute import servers
from nova.api.openstack.compute import views
from nova.api.openstack import extensions
from nova.api.openstack import xmlutil
from nova import block_device
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova.image import glance
from nova.network import manager
from nova.network.neutronv2 import api as neutron_api
from nova.objects import instance as instance_obj
from nova.objects import service as service_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import policy as common_policy
from nova.openstack.common import timeutils
from nova import policy
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests import fake_network
from nova.tests.image import fake
from nova.tests import matchers
from nova.tests.objects import test_keypair
from nova.tests import utils
from nova import utils as nova_utils

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')

FAKE_UUID = fakes.FAKE_UUID
NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
XPATH_NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/compute/api/v1.1'
}

INSTANCE_IDS = {FAKE_UUID: 1}

FIELDS = instance_obj.INSTANCE_DEFAULT_FIELDS


def fake_gen_uuid():
    return FAKE_UUID


def return_servers_empty(context, *args, **kwargs):
    return []


def return_security_group(context, instance_id, security_group_id):
    pass


def instance_update_and_get_original(context, instance_uuid, values,
                                     update_cells=True,
                                     columns_to_join=None,
                                     ):
    inst = fakes.stub_instance(INSTANCE_IDS.get(instance_uuid),
                               name=values.get('display_name'))
    inst = dict(inst, **values)
    return (inst, inst)


def instance_update(context, instance_uuid, values, update_cells=True):
    inst = fakes.stub_instance(INSTANCE_IDS.get(instance_uuid),
                               name=values.get('display_name'))
    inst = dict(inst, **values)
    return inst


def fake_compute_api(cls, req, id):
    return True


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance_id, password):
        self.instance_id = instance_id
        self.password = password


class Base64ValidationTest(test.TestCase):
    def setUp(self):
        super(Base64ValidationTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = servers.Controller(self.ext_mgr)

    def test_decode_base64(self):
        value = "A random string"
        result = self.controller._decode_base64(base64.b64encode(value))
        self.assertEqual(result, value)

    def test_decode_base64_binary(self):
        value = "\x00\x12\x75\x99"
        result = self.controller._decode_base64(base64.b64encode(value))
        self.assertEqual(result, value)

    def test_decode_base64_whitespace(self):
        value = "A random string"
        encoded = base64.b64encode(value)
        white = "\n \n%s\t%s\n" % (encoded[:2], encoded[2:])
        result = self.controller._decode_base64(white)
        self.assertEqual(result, value)

    def test_decode_base64_invalid(self):
        invalid = "A random string"
        result = self.controller._decode_base64(invalid)
        self.assertIsNone(result)

    def test_decode_base64_illegal_bytes(self):
        value = "A random string"
        encoded = base64.b64encode(value)
        white = ">\x01%s*%s()" % (encoded[:2], encoded[2:])
        result = self.controller._decode_base64(white)
        self.assertIsNone(result)


class NeutronV2Subclass(neutron_api.API):
    """Used to ensure that API handles subclasses properly."""
    pass


class ControllerTest(test.TestCase):

    def setUp(self):
        super(ControllerTest, self).setUp()
        self.flags(verbose=True, use_ipv6=False)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fake.stub_out_image_service(self.stubs)
        return_server = fakes.fake_instance_get()
        return_servers = fakes.fake_instance_get_all_by_filters()
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       return_server)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'instance_update_and_get_original',
                       instance_update_and_get_original)

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = servers.Controller(self.ext_mgr)
        self.ips_controller = ips.Controller()
        policy.reset()
        policy.init()
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)


class ServersControllerTest(ControllerTest):

    def setUp(self):
        super(ServersControllerTest, self).setUp()
        nova_utils.reset_is_neutron()

    def test_can_check_loaded_extensions(self):
        self.ext_mgr.extensions = {'os-fake': None}
        self.assertTrue(self.controller.ext_mgr.is_loaded('os-fake'))
        self.assertFalse(self.controller.ext_mgr.is_loaded('os-not-loaded'))

    def test_requested_networks_prefix(self):
        uuid = 'br-00000000-0000-0000-0000-000000000000'
        requested_networks = [{'uuid': uuid}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertIn((uuid, None), res)

    def test_requested_networks_neutronv2_enabled_with_port(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_requested_networks_neutronv2_enabled_with_network(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        requested_networks = [{'uuid': network}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(network, None, None)])

    def test_requested_networks_neutronv2_enabled_with_network_and_port(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_requested_networks_neutronv2_disabled_with_port(self):
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port}]
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller._get_requested_networks,
            requested_networks)

    def test_requested_networks_api_enabled_with_v2_subclass(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_requested_networks_neutronv2_subclass_with_port(self):
        cls = 'nova.tests.api.openstack.compute.test_servers.NeutronV2Subclass'
        self.flags(network_api_class=cls)
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_get_server_by_uuid(self):
        req = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        res_dict = self.controller.show(req, FAKE_UUID)
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)

    def test_unique_host_id(self):
        """Create two servers with the same host and different
           project_ids and check that the hostId's are unique.
        """
        def return_instance_with_host(self, *args, **kwargs):
            project_id = str(uuid.uuid4())
            return fakes.stub_instance(id=1, uuid=FAKE_UUID,
                                       project_id=project_id,
                                       host='fake_host')

        self.stubs.Set(db, 'instance_get_by_uuid',
                       return_instance_with_host)
        self.stubs.Set(db, 'instance_get',
                       return_instance_with_host)

        req = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        server1 = self.controller.show(req, FAKE_UUID)
        server2 = self.controller.show(req, FAKE_UUID)

        self.assertNotEqual(server1['server']['hostId'],
                            server2['server']['hostId'])

    def _get_server_data_dict(self, uuid, image_bookmark, flavor_bookmark,
                              status="ACTIVE", progress=100):
        return {
            "server": {
                "id": uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": progress,
                "name": "server1",
                "status": status,
                "accessIPv4": "",
                "accessIPv6": "",
                "hostId": '',
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

    def test_get_server_by_id(self):
        self.flags(use_ipv6=True)
        image_bookmark = "http://localhost/fake/images/10"
        flavor_bookmark = "http://localhost/fake/flavors/1"

        uuid = FAKE_UUID
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)

        expected_server = self._get_server_data_dict(uuid,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     status="BUILD",
                                                     progress=0)
        self.assertThat(res_dict, matchers.DictMatches(expected_server))

    def test_get_server_with_active_status_by_id(self):
        image_bookmark = "http://localhost/fake/images/10"
        flavor_bookmark = "http://localhost/fake/flavors/1"

        new_return_server = fakes.fake_instance_get(
                vm_state=vm_states.ACTIVE, progress=100)
        self.stubs.Set(db, 'instance_get_by_uuid', new_return_server)

        uuid = FAKE_UUID
        req = fakes.HTTPRequest.blank('/fake/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        expected_server = self._get_server_data_dict(uuid,
                                                     image_bookmark,
                                                     flavor_bookmark)
        self.assertThat(res_dict, matchers.DictMatches(expected_server))

    def test_get_server_with_id_image_ref_by_id(self):
        image_ref = "10"
        image_bookmark = "http://localhost/fake/images/10"
        flavor_id = "1"
        flavor_bookmark = "http://localhost/fake/flavors/1"

        new_return_server = fakes.fake_instance_get(
                vm_state=vm_states.ACTIVE, image_ref=image_ref,
                flavor_id=flavor_id, progress=100)
        self.stubs.Set(db, 'instance_get_by_uuid', new_return_server)

        uuid = FAKE_UUID
        req = fakes.HTTPRequest.blank('/fake/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        expected_server = self._get_server_data_dict(uuid,
                                                     image_bookmark,
                                                     flavor_bookmark)
        self.assertThat(res_dict, matchers.DictMatches(expected_server))

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
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

        req = fakes.HTTPRequest.blank('/fake/servers/%s/ips' % FAKE_UUID)
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
        self.assertThat(res_dict, matchers.DictMatches(expected))

    def test_get_server_addresses_nonexistent_network(self):
        url = '/fake/servers/%s/ips/network_0' % FAKE_UUID
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPNotFound, self.ips_controller.show,
                          req, FAKE_UUID, 'network_0')

    def test_get_server_addresses_nonexistent_server(self):
        def fake_instance_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)

        server_id = str(uuid.uuid4())
        req = fakes.HTTPRequest.blank('/fake/servers/%s/ips' % server_id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.ips_controller.index, req, server_id)

    def test_get_server_list_empty(self):
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers_empty)

        req = fakes.HTTPRequest.blank('/fake/servers')
        res_dict = self.controller.index(req)

        num_servers = len(res_dict['servers'])
        self.assertEqual(0, num_servers)

    def test_get_server_list_with_reservation_id(self):
        req = fakes.HTTPRequest.blank('/fake/servers?reservation_id=foo')
        res_dict = self.controller.index(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_empty(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail?'
                                      'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_details(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail?'
                                      'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        res_dict = self.controller.index(req)

        self.assertEqual(len(res_dict['servers']), 5)
        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['name'], 'server%d' % (i + 1))
            self.assertIsNone(s.get('image', None))

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
        req = fakes.HTTPRequest.blank('/fake/servers?limit=3')
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
        self.assertThat(params, matchers.DictMatches(expected_params))

    def test_get_servers_with_limit_bad_value(self):
        req = fakes.HTTPRequest.blank('/fake/servers?limit=aaa')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_server_details_empty(self):
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers_empty)

        req = fakes.HTTPRequest.blank('/fake/servers/detail')
        res_dict = self.controller.detail(req)

        num_servers = len(res_dict['servers'])
        self.assertEqual(0, num_servers)

    def test_get_server_details_with_limit(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail?limit=3')
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
        self.assertThat(params, matchers.DictMatches(expected))

    def test_get_server_details_with_limit_bad_value(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail?limit=aaa')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail, req)

    def test_get_server_details_with_limit_and_other_params(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail'
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
        expected = {'limit': ['3'], 'blah': ['2:t'],
                    'marker': [fakes.get_fake_uuid(2)]}
        self.assertThat(params, matchers.DictMatches(expected))

    def test_get_servers_with_too_big_limit(self):
        req = fakes.HTTPRequest.blank('/fake/servers?limit=30')
        res_dict = self.controller.index(req)
        self.assertNotIn('servers_links', res_dict)

    def test_get_servers_with_bad_limit(self):
        req = fakes.HTTPRequest.blank('/fake/servers?limit=asdf')
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
        req = fakes.HTTPRequest.blank('/fake/servers?limit=2&marker=asdf')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_servers_with_bad_option(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?unknownoption=whee')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_image(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('image', search_opts)
            self.assertEqual(search_opts['image'], '12345')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?image=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_tenant_id_filter_converts_to_project_id_for_admin(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False):
            self.assertIsNotNone(filters)
            self.assertEqual(filters['project_id'], 'newfake')
            self.assertFalse(filters.get('tenant_id'))
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers'
                                      '?all_tenants=1&tenant_id=newfake',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_normal(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False):
            self.assertNotIn('project_id', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?all_tenants',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_one(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False):
            self.assertNotIn('project_id', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?all_tenants=1',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_zero(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False):
            self.assertNotIn('all_tenants', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?all_tenants=0',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_false(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False):
            self.assertNotIn('all_tenants', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?all_tenants=false',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_invalid(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None):
            self.assertNotIn('all_tenants', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?all_tenants=xxx',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_admin_restricted_tenant(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False):
            self.assertIsNotNone(filters)
            self.assertEqual(filters['project_id'], 'fake')
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_pass_policy(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False):
            self.assertIsNotNone(filters)
            self.assertNotIn('project_id', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        rules = {
            "compute:get_all_tenants":
                common_policy.parse_rule("project_id:fake"),
            "compute:get_all":
                common_policy.parse_rule("project_id:fake"),
        }

        common_policy.set_rules(common_policy.Rules(rules))

        req = fakes.HTTPRequest.blank('/fake/servers?all_tenants=1')
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_fail_policy(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None):
            self.assertIsNotNone(filters)
            return [fakes.stub_instance(100)]

        rules = {
            "compute:get_all_tenants":
                common_policy.parse_rule("project_id:non_fake"),
            "compute:get_all":
                common_policy.parse_rule("project_id:fake"),
        }

        common_policy.set_rules(common_policy.Rules(rules))
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?all_tenants=1')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index, req)

    def test_get_servers_allows_flavor(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('flavor', search_opts)
            # flavor is an integer ID
            self.assertEqual(search_opts['flavor'], '12345')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?flavor=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_with_bad_flavor(self):
        req = fakes.HTTPRequest.blank('/fake/servers?flavor=abcde')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 0)

    def test_get_server_details_with_bad_flavor(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail?flavor=abcde')
        servers = self.controller.detail(req)['servers']

        self.assertThat(servers, testtools.matchers.HasLength(0))

    def test_get_servers_allows_status(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'], [vm_states.ACTIVE])
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?status=active')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_task_status(self):
        server_uuid = str(uuid.uuid4())
        task_state = task_states.REBOOTING

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('task_state', search_opts)
            self.assertEqual([task_states.REBOOT_PENDING,
                              task_states.REBOOT_STARTED,
                              task_states.REBOOTING],
                             search_opts['task_state'])
            db_list = [fakes.stub_instance(100, uuid=server_uuid,
                                                task_state=task_state)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/servers?status=reboot')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_resize_status(self):
        # Test when resize status, it maps list of vm states.
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'],
                             [vm_states.ACTIVE, vm_states.STOPPED])

            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?status=resize')

        servers = self.controller.detail(req)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_invalid_status(self):
        # Test getting servers by invalid status.
        req = fakes.HTTPRequest.blank('/fake/servers?status=baloney',
                                      use_admin_context=False)
        servers = self.controller.index(req)['servers']
        self.assertEqual(len(servers), 0)

    def test_get_servers_deleted_status_as_user(self):
        req = fakes.HTTPRequest.blank('/fake/servers?status=deleted',
                                      use_admin_context=False)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.detail, req)

    def test_get_servers_deleted_status_as_admin(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'], ['deleted'])

            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?status=deleted',
                                      use_admin_context=True)

        servers = self.controller.detail(req)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_name(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('name', search_opts)
            self.assertEqual(search_opts['name'], 'whee.*')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?name=whee.*')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_changes_since(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('changes-since', search_opts)
            changes_since = datetime.datetime(2011, 1, 24, 17, 8, 1,
                                              tzinfo=iso8601.iso8601.UTC)
            self.assertEqual(search_opts['changes-since'], changes_since)
            self.assertNotIn('deleted', search_opts)
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        params = 'changes-since=2011-01-24T17:08:01Z'
        req = fakes.HTTPRequest.blank('/fake/servers?%s' % params)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_changes_since_bad_value(self):
        params = 'changes-since=asdf'
        req = fakes.HTTPRequest.blank('/fake/servers?%s' % params)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index, req)

    def test_get_servers_admin_filters_as_user(self):
        """Test getting servers by admin-only or unknown options when
        context is not admin. Make sure the admin and unknown options
        are stripped before they get to compute_api.get_all()
        """
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            # Allowed by user
            self.assertIn('name', search_opts)
            self.assertIn('ip', search_opts)
            # OSAPI converts status to vm_state
            self.assertIn('vm_state', search_opts)
            # Allowed only by admins with admin API on
            self.assertNotIn('unknown_option', search_opts)
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = fakes.HTTPRequest.blank('/fake/servers?%s' % query_str)
        res = self.controller.index(req)

        servers = res['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_admin_options_as_admin(self):
        """Test getting servers by admin-only or unknown options when
        context is admin. All options should be passed
        """
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            # Allowed by user
            self.assertIn('name', search_opts)
            # OSAPI converts status to vm_state
            self.assertIn('vm_state', search_opts)
            # Allowed only by admins with admin API on
            self.assertIn('ip', search_opts)
            self.assertIn('unknown_option', search_opts)
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = fakes.HTTPRequest.blank('/fake/servers?%s' % query_str,
                                      use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_ip(self):
        """Test getting servers by ip."""
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('ip', search_opts)
            self.assertEqual(search_opts['ip'], '10\..*')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?ip=10\..*')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_admin_allows_ip6(self):
        """Test getting servers by ip6 with admin_api enabled and
        admin context
        """
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('ip6', search_opts)
            self.assertEqual(search_opts['ip6'], 'ffff.*')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequest.blank('/fake/servers?ip6=ffff.*',
                                      use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

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
        req = fakes.HTTPRequest.blank('/fake/servers/detail')
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
        """We want to make sure that if two instances are on the same host,
        then they return the same hostId. If two instances are on different
        hosts, they should return different hostId's. In this test, there
        are 5 instances - 2 on one host and 3 on another.
        """

        def return_servers_with_host(context, *args, **kwargs):
            return [fakes.stub_instance(i + 1, 'fake', 'fake', host=i % 2,
                                        uuid=fakes.get_fake_uuid(i))
                    for i in xrange(5)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers_with_host)

        req = fakes.HTTPRequest.blank('/fake/servers/detail')
        res_dict = self.controller.detail(req)

        server_list = res_dict['servers']
        host_ids = [server_list[0]['hostId'], server_list[1]['hostId']]
        self.assertTrue(host_ids[0] and host_ids[1])
        self.assertNotEqual(host_ids[0], host_ids[1])

        for i, s in enumerate(server_list):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['hostId'], host_ids[i % 2])
            self.assertEqual(s['name'], 'server%d' % (i + 1))


class ServersControllerUpdateTest(ControllerTest):

    def _get_request(self, body=None, content_type='json', options=None):
        if options:
            self.stubs.Set(db, 'instance_get',
                           fakes.fake_instance_get(**options))
        req = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/%s' % content_type
        req.body = jsonutils.dumps(body)
        return req

    def test_update_server_all_attributes(self):
        body = {'server': {
                  'name': 'server_test',
                  'accessIPv4': '0.0.0.0',
                  'accessIPv6': 'beef::0123',
               }}
        req = self._get_request(body, {'name': 'server_test',
                                       'access_ipv4': '0.0.0.0',
                                       'access_ipv6': 'beef::0123'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')
        self.assertEqual(res_dict['server']['accessIPv4'], '0.0.0.0')
        self.assertEqual(res_dict['server']['accessIPv6'], 'beef::123')

    def test_update_server_invalid_xml_raises_lookup(self):
        body = """<?xml version="1.0" encoding="TF-8"?>
            <metadata
            xmlns="http://docs.openstack.org/compute/api/v1.1"
            key="Label"></meta>"""
        req = self._get_request(body, content_type='xml')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_server_invalid_xml_raises_expat(self):
        body = """<?xml version="1.0" encoding="UTF-8"?>
            <metadata
            xmlns="http://docs.openstack.org/compute/api/v1.1"
            key="Label"></meta>"""
        req = self._get_request(body, content_type='xml')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_update_server_name(self):
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body, {'name': 'server_test'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_name_too_long(self):
        body = {'server': {'name': 'x' * 256}}
        req = self._get_request(body, {'name': 'server_test'})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                            req, FAKE_UUID, body)

    def test_update_server_name_all_blank_spaces(self):
        body = {'server': {'name': ' ' * 64}}
        req = self._get_request(body, {'name': 'server_test'})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, FAKE_UUID, body)

    def test_update_server_access_ipv4(self):
        body = {'server': {'accessIPv4': '0.0.0.0'}}
        req = self._get_request(body, {'access_ipv4': '0.0.0.0'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv4'], '0.0.0.0')

    def test_update_server_access_ipv4_bad_format(self):
        body = {'server': {'accessIPv4': 'bad_format'}}
        req = self._get_request(body, {'access_ipv4': '0.0.0.0'})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                            req, FAKE_UUID, body)

    def test_update_server_access_ipv4_none(self):
        body = {'server': {'accessIPv4': None}}
        req = self._get_request(body, {'access_ipv4': '0.0.0.0'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv4'], '')

    def test_update_server_access_ipv4_blank(self):
        body = {'server': {'accessIPv4': ''}}
        req = self._get_request(body, {'access_ipv4': '0.0.0.0'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv4'], '')

    def test_update_server_access_ipv6(self):
        body = {'server': {'accessIPv6': 'beef::0123'}}
        req = self._get_request(body, {'access_ipv6': 'beef::0123'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv6'], 'beef::123')

    def test_update_server_access_ipv6_bad_format(self):
        body = {'server': {'accessIPv6': 'bad_format'}}
        req = self._get_request(body, {'access_ipv6': 'beef::0123'})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                            req, FAKE_UUID, body)

    def test_update_server_access_ipv6_none(self):
        body = {'server': {'accessIPv6': None}}
        req = self._get_request(body, {'access_ipv6': 'beef::0123'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv6'], '')

    def test_update_server_access_ipv6_blank(self):
        body = {'server': {'accessIPv6': ''}}
        req = self._get_request(body, {'access_ipv6': 'beef::0123'})
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['accessIPv6'], '')

    def test_update_server_personality(self):
        body = {
            'server': {
                'personality': []
            }
        }
        req = self._get_request(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller.update, req, FAKE_UUID, body)

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

        self.stubs.Set(db, 'instance_update', server_update)
        # FIXME (comstud)
        #        self.stubs.Set(db, 'instance_get',
        #                return_server_with_attributes(name='server_test'))

        req = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = jsonutils.dumps(body)
        res_dict = self.controller.update(req, FAKE_UUID, body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_not_found(self):
        def fake_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(compute_api.API, 'get', fake_get)
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body)

    def test_update_server_not_found_on_update(self):
        def fake_update(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(db, 'instance_update_and_get_original', fake_update)
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body)

    def test_update_server_policy_fail(self):
        rule = {'compute:update': common_policy.parse_rule('role:admin')}
        common_policy.set_rules(common_policy.Rules(rule))
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body, {'name': 'server_test'})
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller.update, req, FAKE_UUID, body)


class ServersControllerDeleteTest(ControllerTest):

    def setUp(self):
        super(ServersControllerDeleteTest, self).setUp()
        self.server_delete_called = False

        def instance_destroy_mock(*args, **kwargs):
            self.server_delete_called = True
            deleted_at = timeutils.utcnow()
            return fake_instance.fake_db_instance(deleted_at=deleted_at)

        self.stubs.Set(db, 'instance_destroy', instance_destroy_mock)

    def _create_delete_request(self, uuid):
        fakes.stub_out_instance_quota(self.stubs, 0, 10)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s' % uuid)
        req.method = 'DELETE'
        return req

    def _delete_server_instance(self, uuid=FAKE_UUID):
        req = self._create_delete_request(uuid)
        self.stubs.Set(db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        self.controller.delete(req, uuid)

    def test_delete_server_instance(self):
        self._delete_server_instance()
        self.assertTrue(self.server_delete_called)

    def test_delete_server_instance_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self._delete_server_instance,
                          uuid='non-existent-uuid')

    def test_delete_locked_server(self):
        req = self._create_delete_request(FAKE_UUID)
        self.stubs.Set(compute_api.API, 'soft_delete',
                       fakes.fake_actions_to_locked_server)
        self.stubs.Set(compute_api.API, 'delete',
                       fakes.fake_actions_to_locked_server)

        self.assertRaises(webob.exc.HTTPConflict, self.controller.delete,
                          req, FAKE_UUID)

    def test_delete_server_instance_while_building(self):
        fakes.stub_out_instance_quota(self.stubs, 0, 10)
        request = self._create_delete_request(FAKE_UUID)
        self.controller.delete(request, FAKE_UUID)

        self.assertTrue(self.server_delete_called)

    def test_delete_server_instance_while_deleting_host_up(self):
        req = self._create_delete_request(FAKE_UUID)
        self.stubs.Set(db, 'instance_get_by_uuid',
            fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                    task_state=task_states.DELETING,
                                    host='fake_host'))
        self.stubs.Set(instance_obj.Instance, 'save',
                       lambda *args, **kwargs: None)

        @classmethod
        def fake_get_by_compute_host(cls, context, host):
            return {'updated_at': timeutils.utcnow()}
        self.stubs.Set(service_obj.Service, 'get_by_compute_host',
                       fake_get_by_compute_host)

        self.controller.delete(req, FAKE_UUID)
        # Delete request can be ignored, because it's been accepted and
        # forwarded to the compute service already.
        self.assertFalse(self.server_delete_called)

    def test_delete_server_instance_while_deleting_host_down(self):
        fake_network.stub_out_network_cleanup(self.stubs)
        req = self._create_delete_request(FAKE_UUID)
        self.stubs.Set(db, 'instance_get_by_uuid',
            fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                    task_state=task_states.DELETING,
                                    host='fake_host'))
        self.stubs.Set(instance_obj.Instance, 'save',
                       lambda *args, **kwargs: None)

        @classmethod
        def fake_get_by_compute_host(cls, context, host):
            return {'updated_at': datetime.datetime.min}
        self.stubs.Set(service_obj.Service, 'get_by_compute_host',
                       fake_get_by_compute_host)

        self.controller.delete(req, FAKE_UUID)
        # Delete request would be ignored, because it's been accepted before
        # but since the host is down, api should remove the instance anyway.
        self.assertTrue(self.server_delete_called)

    def test_delete_server_instance_while_resize(self):
        req = self._create_delete_request(FAKE_UUID)
        self.stubs.Set(db, 'instance_get_by_uuid',
            fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                    task_state=task_states.RESIZE_PREP))

        self.controller.delete(req, FAKE_UUID)
        # Delete shoud be allowed in any case, even during resizing,
        # because it may get stuck.
        self.assertTrue(self.server_delete_called)

    def test_delete_server_instance_if_not_launched(self):
        self.flags(reclaim_instance_interval=3600)
        req = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        req.method = 'DELETE'

        self.server_delete_called = False

        self.stubs.Set(db, 'instance_get_by_uuid',
            fakes.fake_instance_get(launched_at=None))

        def instance_destroy_mock(*args, **kwargs):
            self.server_delete_called = True
            deleted_at = timeutils.utcnow()
            return fake_instance.fake_db_instance(deleted_at=deleted_at)
        self.stubs.Set(db, 'instance_destroy', instance_destroy_mock)

        self.controller.delete(req, FAKE_UUID)
        # delete() should be called for instance which has never been active,
        # even if reclaim_instance_interval has been set.
        self.assertEqual(self.server_delete_called, True)


class ServersControllerRebuildInstanceTest(ControllerTest):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    image_href = 'http://localhost/v2/fake/images/%s' % image_uuid

    def setUp(self):
        super(ServersControllerRebuildInstanceTest, self).setUp()
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        self.body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': self.image_href,
                'metadata': {
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
        self.req = fakes.HTTPRequest.blank('/fake/servers/a/action')
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"

    def test_rebuild_instance_with_access_ipv4_bad_format(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        self.body['rebuild']['accessIPv4'] = 'bad_format'
        self.body['rebuild']['accessIPv6'] = 'fead::1234'
        self.body['rebuild']['metadata']['hello'] = 'world'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, self.body)

    def test_rebuild_instance_with_blank_metadata_key(self):
        self.body['rebuild']['accessIPv4'] = '0.0.0.0'
        self.body['rebuild']['accessIPv6'] = 'fead::1234'
        self.body['rebuild']['metadata'][''] = 'world'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, self.body)

    def test_rebuild_instance_with_metadata_key_too_long(self):
        self.body['rebuild']['accessIPv4'] = '0.0.0.0'
        self.body['rebuild']['accessIPv6'] = 'fead::1234'
        self.body['rebuild']['metadata'][('a' * 260)] = 'world'

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, self.body)

    def test_rebuild_instance_with_metadata_value_too_long(self):
        self.body['rebuild']['accessIPv4'] = '0.0.0.0'
        self.body['rebuild']['accessIPv6'] = 'fead::1234'
        self.body['rebuild']['metadata']['key1'] = ('a' * 260)

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, self.body)

    def test_rebuild_instance_fails_when_min_ram_too_small(self):
        # make min_ram larger than our instance ram size
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='active', properties={'key1': 'value1'},
                        min_ram="4096", min_disk="10")

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, self.body)

    def test_rebuild_instance_fails_when_min_disk_too_small(self):
        # make min_disk larger than our instance disk size
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='active', properties={'key1': 'value1'},
                        min_ram="128", min_disk="100000")

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild, self.req,
                          FAKE_UUID, self.body)

    def test_rebuild_instance_image_too_large(self):
        # make image size larger than our instance disk size
        size = str(1000 * (1024 ** 3))

        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='active', size=size)

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, self.req, FAKE_UUID, self.body)

    def test_rebuild_instance_with_deleted_image(self):
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='DELETED')

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller._action_rebuild, self.req, FAKE_UUID, self.body)

    def test_rebuild_instance_with_access_ipv6_bad_format(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        self.body['rebuild']['accessIPv4'] = '1.2.3.4'
        self.body['rebuild']['accessIPv6'] = 'bad_format'
        self.body['rebuild']['metadata']['hello'] = 'world'
        self.req.body = jsonutils.dumps(self.body)
        self.req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, self.body)


class ServerStatusTest(test.TestCase):

    def setUp(self):
        super(ServerStatusTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = servers.Controller(self.ext_mgr)

        def _fake_get_server(context, req, id):
            return fakes.stub_instance(id)

        self.stubs.Set(self.controller, '_get_server', _fake_get_server)

    def _get_with_state(self, vm_state, task_state=None):
        self.stubs.Set(db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_state,
                                        task_state=task_state))

        request = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        return self.controller.show(request, FAKE_UUID)

    def _req_with_policy_fail(self, policy_rule_name):
        rule = {'compute:%s' % policy_rule_name:
                common_policy.parse_rule('role:admin')}
        common_policy.set_rules(common_policy.Rules(rule))
        return fakes.HTTPRequest.blank('/fake/servers/1234/action')

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

    def test_reboot_resize_policy_fail(self):
        req = self._req_with_policy_fail('reboot')
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_reboot, req, '1234',
                {'reboot': {'type': 'HARD'}})

    def test_rebuild(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBUILDING)
        self.assertEqual(response['server']['status'], 'REBUILD')

    def test_rebuild_error(self):
        response = self._get_with_state(vm_states.ERROR)
        self.assertEqual(response['server']['status'], 'ERROR')

    def test_resize(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.RESIZE_PREP)
        self.assertEqual(response['server']['status'], 'RESIZE')

    def test_confirm_resize_policy_fail(self):
        req = self._req_with_policy_fail('confirm_resize')
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_confirm_resize, req, '1234', {})

    def test_verify_resize(self):
        response = self._get_with_state(vm_states.RESIZED, None)
        self.assertEqual(response['server']['status'], 'VERIFY_RESIZE')

    def test_revert_resize(self):
        response = self._get_with_state(vm_states.RESIZED,
                                        task_states.RESIZE_REVERTING)
        self.assertEqual(response['server']['status'], 'REVERT_RESIZE')

    def test_revert_resize_policy_fail(self):
        req = self._req_with_policy_fail('revert_resize')
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_revert_resize, req, '1234', {})

    def test_password_update(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.UPDATING_PASSWORD)
        self.assertEqual(response['server']['status'], 'PASSWORD')

    def test_stopped(self):
        response = self._get_with_state(vm_states.STOPPED)
        self.assertEqual(response['server']['status'], 'SHUTOFF')


class ServersControllerCreateTest(test.TestCase):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    flavor_ref = 'http://localhost/123/flavors/3'

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(verbose=True,
                   enable_instance_password=True)
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        fakes.stub_out_nw_api(self.stubs)

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = servers.Controller(self.ext_mgr)
        nova_utils.reset_is_neutron()

        self.volume_id = 'fake'

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
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
                "root_device_name": inst.get('root_device_name', 'vda'),
                "security_groups": inst['security_groups'],
            })

            self.instance_cache_by_id[instance['id']] = instance
            self.instance_cache_by_uuid[instance['uuid']] = instance
            return instance

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache_by_id[instance_id]

        def instance_update(context, uuid, values):
            instance = self.instance_cache_by_uuid[uuid]
            instance.update(values)
            return instance

        def server_update(context, instance_uuid, params, update_cells=False):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return inst

        def server_update_and_get_original(
                context, instance_uuid, params, update_cells=False,
                columns_to_join=None):
            inst = self.instance_cache_by_uuid[instance_uuid]
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
        fake.stub_out_image_service(self.stubs)
        self.stubs.Set(uuid, 'uuid4', fake_gen_uuid)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(db, 'instance_create', instance_create)
        self.stubs.Set(db, 'instance_system_metadata_update',
                       fake_method)
        self.stubs.Set(db, 'instance_get', instance_get)
        self.stubs.Set(db, 'instance_update', instance_update)
        self.stubs.Set(db, 'instance_update_and_get_original',
                       server_update_and_get_original)
        self.stubs.Set(manager.VlanManager, 'allocate_fixed_ip',
                       fake_method)
        self.body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'imageRef': self.image_uuid,
                'flavorRef': self.flavor_ref,
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
        self.bdm = [{'delete_on_termination': 1,
                     'device_name': 123,
                     'volume_size': 1,
                     'volume_id': '11111111-1111-1111-1111-111111111111'}]

        self.req = fakes.HTTPRequest.blank('/fake/servers')
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"

    def _check_admin_pass_len(self, server_dict):
        """utility function - check server_dict for adminPass length."""
        self.assertEqual(CONF.password_length,
                         len(server_dict["adminPass"]))

    def _check_admin_pass_missing(self, server_dict):
        """utility function - check server_dict for absence of adminPass."""
        self.assertNotIn("adminPass", server_dict)

    def _test_create_instance(self, flavor=2):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        self.body['server']['imageRef'] = image_uuid
        self.body['server']['flavorRef'] = flavor
        self.req.body = jsonutils.dumps(self.body)
        server = self.controller.create(self.req, self.body).obj['server']
        self._check_admin_pass_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_private_flavor(self):
        values = {
            'name': 'fake_name',
            'memory_mb': 512,
            'vcpus': 1,
            'root_gb': 10,
            'ephemeral_gb': 10,
            'flavorid': '1324',
            'swap': 0,
            'rxtx_factor': 0.5,
            'vcpu_weight': 1,
            'disabled': False,
            'is_public': False,
        }
        db.flavor_create(context.get_admin_context(), values)
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_create_instance,
                          flavor=1324)

    def test_create_server_bad_image_href(self):
        image_href = 1
        self.body['server']['imageRef'] = image_href,
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, self.body)

    def test_create_server_with_invalid_networks_parameter(self):
        self.ext_mgr.extensions = {'os-networks': 'fake'}
        self.body['server']['networks'] = {
            'uuid': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req,
                          self.body)

    def test_create_server_with_deleted_image(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        # Get the fake image service so we can set the status to deleted
        (image_service, image_id) = glance.get_remote_image_service(
                context, '')
        image_service.update(context, image_uuid, {'status': 'DELETED'})
        self.addCleanup(image_service.update, context, image_uuid,
                        {'status': 'active'})

        self.body['server']['flavorRef'] = 2
        self.req.body = jsonutils.dumps(self.body)
        with testtools.ExpectedException(
                webob.exc.HTTPBadRequest,
                'Image 76fa36fc-c930-4bf3-8c8a-ea2a2420deb6 is not active.'):
            self.controller.create(self.req, self.body)

    def test_create_server_image_too_large(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        # Get the fake image service so we can set the status to deleted
        (image_service, image_id) = glance.get_remote_image_service(context,
                                                                    image_uuid)
        image = image_service.show(context, image_id)
        orig_size = image['size']
        new_size = str(1000 * (1024 ** 3))
        image_service.update(context, image_uuid, {'size': new_size})

        self.addCleanup(image_service.update, context, image_uuid,
                        {'size': orig_size})

        self.body['server']['flavorRef'] = 2
        self.req.body = jsonutils.dumps(self.body)
        with testtools.ExpectedException(
                webob.exc.HTTPBadRequest,
                "Flavor's disk is too small for requested image."):
            self.controller.create(self.req, self.body)

    def test_create_instance_invalid_negative_min(self):
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.body['server']['min_count'] = -1
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req,
                          self.body)

    def test_create_instance_invalid_negative_max(self):
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.body['server']['max_count'] = -1
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req,
                          self.body)

    def test_create_instance_invalid_alpha_min(self):
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.body['server']['min_count'] = 'abcd',
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req,
                          self.body)

    def test_create_instance_invalid_alpha_max(self):
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.body['server']['max_count'] = 'abcd',
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req,
                          self.body)

    def test_create_multiple_instances(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj
        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_pass_len(res["server"])

    def test_create_multiple_instances_pass_disabled(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.flags(enable_instance_password=False)
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj
        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_pass_missing(res["server"])

    def test_create_multiple_instances_resv_id_return(self):
        """Test creating multiple instances with asking for
        reservation_id
        """
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.body['server']['return_reservation_id'] = True
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body)
        reservation_id = res.obj.get('reservation_id')
        self.assertNotEqual(reservation_id, "")
        self.assertIsNotNone(reservation_id)
        self.assertTrue(len(reservation_id) > 1)

    def test_create_multiple_instances_with_multiple_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested with a list of block device mappings for volumes.
        """
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        min_count = 2
        bdm = [{'device_name': 'foo1', 'volume_id': 'vol-xxxx'},
               {'device_name': 'foo2', 'volume_id': 'vol-yyyy'}
        ]
        params = {
                  'block_device_mapping': bdm,
                  'min_count': min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(len(kwargs['block_device_mapping']), 2)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params, no_image=True)

    def test_create_multiple_instances_with_single_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested to boot from a single volume.
        """
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        min_count = 2
        bdm = [{'device_name': 'foo1', 'volume_id': 'vol-xxxx'}]
        params = {
                 'block_device_mapping': bdm,
                 'min_count': min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['block_device_mapping']['volume_id'],
                            'vol-xxxx')
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params, no_image=True)

    def test_create_multiple_instance_with_non_integer_max_count(self):
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.body['server']['max_count'] = 2.5
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_multiple_instance_with_non_integer_min_count(self):
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        self.body['server']['min_count'] = 2.5
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_image_ref_is_bookmark(self):
        image_href = 'http://localhost/fake/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj
        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_image_ref_is_invalid(self):
        image_uuid = 'this_is_not_a_valid_uuid'
        image_href = 'http://localhost/fake/images/%s' % image_uuid
        self.body['server']['imageRef'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, self.body)

    def test_create_instance_no_key_pair(self):
        fakes.stub_out_key_pair_funcs(self.stubs, have_key_pair=False)
        self._test_create_instance()

    def _test_create_extra(self, params, no_image=False):
        self.body['server']['flavorRef'] = 2
        if no_image:
            self.body['server'].pop('imageRef', None)
        self.body['server'].update(params)
        self.req.body = jsonutils.dumps(self.body)
        server = self.controller.create(self.req, self.body).obj['server']

    def test_create_instance_with_security_group_enabled(self):
        self.ext_mgr.extensions = {'os-security-groups': 'fake'}
        group = 'foo'
        old_create = compute_api.API.create

        def sec_group_get(ctx, proj, name):
            if name == group:
                return True
            else:
                raise exception.SecurityGroupNotFoundForProject(
                    project_id=proj, security_group_id=name)

        def create(*args, **kwargs):
            self.assertEqual(kwargs['security_group'], [group])
            return old_create(*args, **kwargs)

        self.stubs.Set(db, 'security_group_get_by_name', sec_group_get)
        # negative test
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra,
                          {'security_groups': [{'name': 'bogus'}]})
        # positive test - extra assert in create path
        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra({'security_groups': [{'name': group}]})

    def test_create_instance_with_non_unique_secgroup_name(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network}]
        params = {'networks': requested_networks,
                  'security_groups': [{'name': 'dup'}, {'name': 'dup'}]}

        def fake_create(*args, **kwargs):
            raise exception.NoUniqueMatch("No Unique match found for ...")

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPConflict,
                          self._test_create_extra, params)

    def test_create_instance_with_port_with_no_fixed_ips(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        port_id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port_id}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.PortRequiresFixedIP(port_id=port_id)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_network_with_no_subnet(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.NetworkRequiresSubnet(network_uuid=network)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_access_ip(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_href = 'http://localhost/v2/fake/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['accessIPv4'] = '1.2.3.4'
        self.body['server']['accessIPv6'] = 'fead::1234'

        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj
        server = res['server']
        self._check_admin_pass_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_with_access_ip_pass_disabled(self):
        # test with admin passwords disabled See lp bug 921814
        # proper local hrefs must start with 'http://localhost/v2/'
        self.flags(enable_instance_password=False)
        image_href = 'http://localhost/v2/fake/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['accessIPv4'] = '1.2.3.4'
        self.body['server']['accessIPv6'] = 'fead::1234'
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj

        server = res['server']
        self._check_admin_pass_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_bad_format_access_ip_v4(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_href = 'http://localhost/v2/fake/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['accessIPv4'] = 'bad_format'
        self.body['server']['accessIPv6'] = 'fead::1234'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, self.body)

    def test_create_instance_bad_format_access_ip_v6(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_href = 'http://localhost/v2/fake/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['accessIPv4'] = '1.2.3.4'
        self.body['server']['accessIPv6'] = 'bad_format'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, self.body)

    def test_create_instance_name_all_blank_spaces(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['name'] = ' ' * 64
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_name_too_long(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['name'] = 'X' * 256
        self.body['server']['imageRef'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, self.body)

    def test_create_instance(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj

        server = res['server']
        self._check_admin_pass_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_pass_disabled(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        self.flags(enable_instance_password=False)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj

        server = res['server']
        self._check_admin_pass_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_too_much_metadata(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['metadata']['vote'] = 'fiddletown'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, self.req, self.body)

    def test_create_instance_metadata_key_too_long(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['metadata'] = {('a' * 260): '12345'}

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, self.req, self.body)

    def test_create_instance_metadata_value_too_long(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['metadata'] = {'key1': ('a' * 260)}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, self.req, self.body)

    def test_create_instance_metadata_key_blank(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['metadata'] = {'': 'abcd'}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_metadata_not_dict(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['metadata'] = 'string'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_metadata_key_not_string(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['metadata'] = {1: 'test'}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_metadata_value_not_string(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.body['server']['metadata'] = {'test': ['a', 'list']}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_user_data_malformed_bad_request(self):
        self.ext_mgr.extensions = {'os-user-data': 'fake'}
        params = {'user_data': 'u1234!'}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_invalid_key_name(self):
        image_href = 'http://localhost/v2/images/2'
        self.body['server']['imageRef'] = image_href
        self.body['server']['key_name'] = 'nonexistentkey'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_valid_key_name(self):
        self.body['server']['key_name'] = 'key'
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_pass_len(res["server"])

    def test_create_instance_invalid_flavor_href(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = 'http://localhost/v2/flavors/asdf'
        self.body['server']['imageRef'] = image_href
        self.body['server']['flavorRef'] = flavor_ref
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_invalid_flavor_id_int(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = -1
        self.body['server']['imageRef'] = image_href
        self.body['server']['flavorRef'] = flavor_ref
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_bad_flavor_href(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = 'http://localhost/v2/flavors/17'
        self.body['server']['imageRef'] = image_href
        self.body['server']['flavorRef'] = flavor_ref
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_with_config_drive(self):
        self.ext_mgr.extensions = {'os-config-drive': 'fake'}
        self.body['server']['config_drive'] = "true"
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj
        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_with_bad_config_drive(self):
        self.ext_mgr.extensions = {'os-config-drive': 'fake'}
        self.body['server']['config_drive'] = 'adcd'
        self.req.body = jsonutils.dumps(self.body)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_without_config_drive(self):
        self.ext_mgr.extensions = {'os-config-drive': 'fake'}
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj
        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_with_config_drive_disabled(self):
        config_drive = [{'config_drive': 'foo'}]
        params = {'config_drive': config_drive}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['config_drive'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_bad_href(self):
        image_href = 'asdf'
        self.body['server']['imageRef'] = image_href
        self.req.body = jsonutils.dumps(self.body)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_instance_local_href(self):
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_admin_pass(self):
        self.body['server']['flavorRef'] = 3,
        self.body['server']['adminPass'] = 'testpass'
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj

        server = res['server']
        self.assertEqual(server['adminPass'], self.body['server']['adminPass'])

    def test_create_instance_admin_pass_pass_disabled(self):
        self.flags(enable_instance_password=False)
        self.body['server']['flavorRef'] = 3,
        self.body['server']['adminPass'] = 'testpass'
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, self.body).obj

        server = res['server']
        self.assertIn('adminPass', self.body['server'])
        self.assertNotIn('adminPass', server)

    def test_create_instance_admin_pass_empty(self):
        self.body['server']['flavorRef'] = 3,
        self.body['server']['adminPass'] = ''
        self.req.body = jsonutils.dumps(self.body)

        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, self.body)

    def _do_test_create_instance_above_quota(self, resource, allowed, quota,
                                             expected_msg):
        fakes.stub_out_instance_quota(self.stubs, allowed, quota, resource)
        self.body['server']['flavorRef'] = 3
        self.req.body = jsonutils.dumps(self.body)
        try:
            server = self.controller.create(self.req, self.body).obj['server']
            self.fail('expected quota to be exceeded')
        except webob.exc.HTTPRequestEntityTooLarge as e:
            self.assertEqual(e.explanation, expected_msg)

    def test_create_instance_with_security_group_disabled(self):
        group = 'foo'
        params = {'security_groups': [{'name': group}]}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            # NOTE(vish): if the security groups extension is not
            #             enabled, then security groups passed in
            #             are ignored.
            self.assertEqual(kwargs['security_group'], ['default'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_disk_config_enabled(self):
        self.ext_mgr.extensions = {'OS-DCF': 'fake'}
        # NOTE(vish): the extension converts OS-DCF:disk_config into
        #             auto_disk_config, so we are testing with
        #             the_internal_value
        params = {'auto_disk_config': 'AUTO'}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['auto_disk_config'], 'AUTO')
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_disk_config_disabled(self):
        params = {'auto_disk_config': True}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['auto_disk_config'], False)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_scheduler_hints_enabled(self):
        self.ext_mgr.extensions = {'OS-SCH-HNT': 'fake'}
        hints = {'a': 'b'}
        params = {'scheduler_hints': hints}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], hints)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_scheduler_hints_disabled(self):
        hints = {'a': 'b'}
        params = {'scheduler_hints': hints}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {})
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_volumes_enabled(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        bdm = [{'device_name': 'foo', 'volume_id': 'fake_vol'}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], bdm)
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.stubs.Set(compute_api.API, '_validate_bdm', _validate_bdm)
        self._test_create_extra(params)

    def test_create_instance_with_volumes_enabled_no_image(self):
        """Test that the create will fail if there is no image
        and no bdms supplied in the request
        """
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('imageRef', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, {}, no_image=True)

    def test_create_instance_with_bdm_v2_enabled_no_image(self):
        self.ext_mgr.extensions = {'os-block-device-mapping-v2-boot': 'fake'}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('imageRef', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, {}, no_image=True)

    def test_create_instance_with_volumes_enabled_and_bdms_no_image(self):
        """Test that the create works if there is no image supplied but
        os-volumes extension is enabled and bdms are supplied
        """
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        self.mox.StubOutWithMock(compute_api.API, '_validate_bdm')
        self.mox.StubOutWithMock(compute_api.API, '_get_bdm_image_metadata')
        bdm = [{
            'id': 1,
            'no_device': None,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': self.volume_id,
            'status': 'active',
            'device_name': 'vda',
            'delete_on_termination': False,
            'volume_image_metadata':
                {'test_key': 'test_value'}
        }]
        volume = bdm[0]
        compute_api.API._validate_bdm(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(True)
        compute_api.API._get_bdm_image_metadata(mox.IgnoreArg(),
                                                bdm, True).AndReturn(volume)
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], bdm)
            self.assertNotIn('imageRef', kwargs)
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.mox.ReplayAll()
        self._test_create_extra(params, no_image=True)

    def test_create_instance_with_bdm_v2_enabled_and_bdms_no_image(self):
        self.ext_mgr.extensions = {
            'os-volumes': 'fake',
            'os-block-device-mapping-v2-boot': 'fake'}
        bdm_v2 = [{
            'no_device': None,
            'source_type': 'volume',
            'destination_type': 'volume',
            'uuid': self.volume_id,
            'device_name': 'vda',
            'delete_on_termination': False,
        }]
        params = {'block_device_mapping_v2': bdm_v2}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertThat(block_device.BlockDeviceDict(bdm_v2[0]),
                            matchers.DictMatches(
                                kwargs['block_device_mapping'][0]))
            self.assertNotIn('imageRef', kwargs)
            return old_create(*args, **kwargs)

        self.mox.StubOutWithMock(compute_api.API, '_validate_bdm')
        self.mox.StubOutWithMock(compute_api.API, '_get_bdm_image_metadata')

        compute_api.API._validate_bdm(
            mox.IgnoreArg(), mox.IgnoreArg(),
            mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(True)
        compute_api.API._get_bdm_image_metadata(
            mox.IgnoreArg(), mox.IgnoreArg(), False).AndReturn({})
        self.mox.ReplayAll()
        self.stubs.Set(compute_api.API, 'create', create)

        self._test_create_extra(params, no_image=True)

    def test_create_instance_with_volumes_disabled(self):
        bdm = [{'device_name': 'foo'}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['block_device_mapping'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_device_name_not_string(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        old_create = compute_api.API.create
        self.params = {'block_device_mapping': self.bdm}

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, self.params)

    def test_create_instance_with_device_name_empty(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        self.bdm[0]['device_name'] = ''
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_device_name_too_long(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        self.bdm[0]['device_name'] = 'a' * 256,
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_space_in_device_name(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        self.bdm[0]['device_name'] = 'vd a',
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertTrue(kwargs['legacy_bdm'])
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_invalid_size(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        bdm = [{'delete_on_termination': 1,
                'device_name': 'vda',
                'volume_size': "hello world",
                'volume_id': '11111111-1111-1111-1111-111111111111'}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], bdm)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_bdm_api_validation_fails(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake',
                                   'os-block-device-mapping-v2-boot': 'fake'}
        bdm = {'delete_on_termination': 1,
                'device_name': 'vda',
                'source_type': 'volume',
                'destination_type': 'volume',
                'volume_size': 1,
                'boot_index': 0,
                'uuid': '11111111-1111-1111-1111-111111111111'}
        self.validation_fail_test_validate_called = False
        self.validation_fail_instance_destroy_called = False

        bdm_exceptions = ((exception.InvalidBDMSnapshot, {'id': 'fake'}),
                          (exception.InvalidBDMVolume, {'id': 'fake'}),
                          (exception.InvalidBDMImage, {'id': 'fake'}),
                          (exception.InvalidBDMBootSequence, {}),
                          (exception.InvalidBDMLocalsLimit, {}))

        ex_iter = iter(bdm_exceptions)

        def _validate_bdm(*args, **kwargs):
            self.validation_fail_test_validate_called = True
            ex, kargs = ex_iter.next()
            raise ex(**kargs)

        def _instance_destroy(*args, **kwargs):
            self.validation_fail_instance_destroy_called = True

        self.stubs.Set(compute_api.API, '_validate_bdm', _validate_bdm)
        self.stubs.Set(instance_obj.Instance, 'destroy', _instance_destroy)

        for _ in xrange(len(bdm_exceptions)):
            params = {'block_device_mapping_v2': [bdm.copy()]}
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self._test_create_extra, params)
            self.assertTrue(self.validation_fail_test_validate_called)
            self.assertTrue(self.validation_fail_instance_destroy_called)
            self.validation_fail_test_validate_called = False
            self.validation_fail_instance_destroy_called = False

    def test_create_instance_with_bdm_delete_on_termination(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake'}
        bdm = [{'device_name': 'foo1', 'volume_id': 'fake_vol',
                'delete_on_termination': 1},
               {'device_name': 'foo2', 'volume_id': 'fake_vol',
                'delete_on_termination': True},
               {'device_name': 'foo3', 'volume_id': 'fake_vol',
                'delete_on_termination': 'invalid'},
               {'device_name': 'foo4', 'volume_id': 'fake_vol',
                'delete_on_termination': 0},
               {'device_name': 'foo5', 'volume_id': 'fake_vol',
                'delete_on_termination': False}]
        expected_bdm = [
            {'device_name': 'foo1', 'volume_id': 'fake_vol',
             'delete_on_termination': True},
            {'device_name': 'foo2', 'volume_id': 'fake_vol',
             'delete_on_termination': True},
            {'device_name': 'foo3', 'volume_id': 'fake_vol',
             'delete_on_termination': False},
            {'device_name': 'foo4', 'volume_id': 'fake_vol',
             'delete_on_termination': False},
            {'device_name': 'foo5', 'volume_id': 'fake_vol',
             'delete_on_termination': False}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(expected_bdm, kwargs['block_device_mapping'])
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.stubs.Set(compute_api.API, '_validate_bdm', _validate_bdm)
        self._test_create_extra(params)

    def test_create_instance_bdm_v2(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake',
                                   'os-block-device-mapping-v2-boot': 'fake'}
        bdm_v2 = [{'source_type': 'volume',
                   'device_name': 'fake_dev',
                   'uuid': 'fake_vol'}]
        bdm_v2_expected = [{'source_type': 'volume',
                            'device_name': 'fake_dev',
                            'volume_id': 'fake_vol'}]
        params = {'block_device_mapping_v2': bdm_v2}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertFalse(kwargs['legacy_bdm'])
            for expected, received in zip(bdm_v2_expected,
                                          kwargs['block_device_mapping']):
                self.assertThat(block_device.BlockDeviceDict(expected),
                                matchers.DictMatches(received))
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.stubs.Set(compute_api.API, '_validate_bdm', _validate_bdm)
        self._test_create_extra(params)

    def test_create_instance_decide_format_legacy(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake',
                                   'os-block-device-mapping-v2-boot': 'fake'}
        bdm = [{'device_name': 'foo1',
                'volume_id': 'fake_vol',
                'delete_on_termination': 1}]

        expected_legacy_flag = True

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['legacy_bdm'], expected_legacy_flag)
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.stubs.Set(compute_api.API, '_validate_bdm',
                       _validate_bdm)

        self._test_create_extra({})

        params = {'block_device_mapping': bdm}
        self._test_create_extra(params)

    def test_create_instance_decide_format_new(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake',
                                   'os-block-device-mapping-v2-boot': 'fake'}

        bdm_v2 = [{'source_type': 'volume',
                   'device_name': 'fake_dev',
                   'uuid': 'fake_vol'}]

        old_create = compute_api.API.create

        expected_legacy_flag = False

        def create(*args, **kwargs):
            self.assertEqual(kwargs['legacy_bdm'], expected_legacy_flag)
            return old_create(*args, **kwargs)

        def _validate_bdm(*args, **kwargs):
            pass

        self.stubs.Set(compute_api.API, 'create', create)
        self.stubs.Set(compute_api.API, '_validate_bdm',
                       _validate_bdm)

        params = {'block_device_mapping_v2': bdm_v2}
        self._test_create_extra(params)

    def test_create_instance_both_bdm_formats(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake',
                                   'os-block-device-mapping-v2-boot': 'fake'}
        bdm = [{'device_name': 'foo'}]
        bdm_v2 = [{'source_type': 'volume',
                   'uuid': 'fake_vol'}]
        params = {'block_device_mapping': bdm,
                  'block_device_mapping_v2': bdm_v2}

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_bdm_v2_validation_error(self):
        self.ext_mgr.extensions = {'os-volumes': 'fake',
                                   'os-block-device-mapping-v2-boot': 'fake'}
        bdm_v2 = [{'device_name': 'bogus device'}]
        params = {'block_device_mapping_v2': bdm_v2}

        def _validate(*args, **kwargs):
            raise exception.InvalidBDMFormat()

        self.stubs.Set(block_device.BlockDeviceDict,
                      '_validate', _validate)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_user_data_enabled(self):
        self.ext_mgr.extensions = {'os-user-data': 'fake'}
        user_data = 'fake'
        params = {'user_data': user_data}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['user_data'], user_data)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_user_data_disabled(self):
        user_data = 'fake'
        params = {'user_data': user_data}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['user_data'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_keypairs_enabled(self):
        self.ext_mgr.extensions = {'os-keypairs': 'fake'}
        key_name = 'green'

        params = {'key_name': key_name}
        old_create = compute_api.API.create

        # NOTE(sdague): key pair goes back to the database,
        # so we need to stub it out for tests
        def key_pair_get(context, user_id, name):
            return dict(test_keypair.fake_keypair,
                        public_key='FAKE_KEY',
                        fingerprint='FAKE_FINGERPRINT',
                        name=name)

        def create(*args, **kwargs):
            self.assertEqual(kwargs['key_name'], key_name)
            return old_create(*args, **kwargs)

        self.stubs.Set(db, 'key_pair_get', key_pair_get)
        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_keypairs_disabled(self):
        key_name = 'green'

        params = {'key_name': key_name}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['key_name'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_availability_zone_enabled(self):
        self.ext_mgr.extensions = {'os-availability-zone': 'fake'}
        availability_zone = 'fake'
        params = {'availability_zone': availability_zone}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['availability_zone'], availability_zone)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)

        try:
            self._test_create_extra(params)
        except webob.exc.HTTPBadRequest as e:
            expected = 'The requested availability zone is not available'
            self.assertEqual(e.explanation, expected)
        admin_context = context.get_admin_context()
        service1 = db.service_create(admin_context, {'host': 'host1_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0})
        agg = db.aggregate_create(admin_context,
                {'name': 'agg1'}, {'availability_zone': availability_zone})
        db.aggregate_host_add(admin_context, agg['id'], 'host1_zones')
        self._test_create_extra(params)

    def test_create_instance_with_availability_zone_disabled(self):
        availability_zone = 'fake'
        params = {'availability_zone': availability_zone}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['availability_zone'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_multiple_create_enabled(self):
        self.ext_mgr.extensions = {'os-multiple-create': 'fake'}
        min_count = 2
        max_count = 3
        params = {
            'min_count': min_count,
            'max_count': max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['max_count'], 3)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_multiple_create_disabled(self):
        ret_res_id = True
        min_count = 2
        max_count = 3
        params = {
            'min_count': min_count,
            'max_count': max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 1)
            self.assertEqual(kwargs['max_count'], 1)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_networks_enabled(self):
        self.ext_mgr.extensions = {'os-networks': 'fake'}
        net_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        requested_networks = [{'uuid': net_uuid}]
        params = {'networks': requested_networks}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            result = [('76fa36fc-c930-4bf3-8c8a-ea2a2420deb6', None)]
            self.assertEqual(kwargs['requested_networks'], result)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_neutronv2_port_in_use(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.PortInUse(port_id=port)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPConflict,
                                          self._test_create_extra, params)

    def test_create_instance_with_neturonv2_not_found_network(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        requested_networks = [{'uuid': network}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.NetworkNotFound(network_id=network)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_neutronv2_port_not_found(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.PortNotFound(port_id=port)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                                        self._test_create_extra, params)

    def test_create_multiple_instance_with_neutronv2_port(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        self.body['server']['max_count'] = 2
        requested_networks = [{'uuid': network, 'port': port}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            msg = _("Unable to launch multiple instances with"
                    " a single configured port ID. Please launch your"
                    " instance one by one with different ports.")
            raise exception.MultiplePortsNotApplicable(reason=msg)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                                        self._test_create_extra, params)

    def test_create_instance_with_networks_disabled_neutronv2(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        net_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        requested_networks = [{'uuid': net_uuid}]
        params = {'networks': requested_networks}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            result = [('76fa36fc-c930-4bf3-8c8a-ea2a2420deb6', None,
                       None)]
            self.assertEqual(kwargs['requested_networks'], result)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_networks_disabled(self):
        self.ext_mgr.extensions = {}
        net_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        requested_networks = [{'uuid': net_uuid}]
        params = {'networks': requested_networks}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['requested_networks'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_invalid_personality(self):

        def fake_create(*args, **kwargs):
            codec = 'utf8'
            content = 'b25zLiINCg0KLVJpY2hhcmQgQ$$%QQmFjaA=='
            start_position = 19
            end_position = 20
            msg = 'invalid start byte'
            raise UnicodeDecodeError(codec, content, start_position,
                                     end_position, msg)
        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.body['server']['personality'] = [
            {
                "path": "/etc/banner.txt",
                "contents": "b25zLiINCg0KLVJpY2hhcmQgQ$$%QQmFjaA==",
            },
        ]
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, self.body)

    def test_create_location(self):
        selfhref = 'http://localhost/v2/fake/servers/%s' % FAKE_UUID
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['imageRef'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        robj = self.controller.create(self.req, self.body)
        self.assertEqual(robj['Location'], selfhref)

    def _do_test_create_instance_above_quota(self, resource, allowed, quota,
                                             expected_msg):
        fakes.stub_out_instance_quota(self.stubs, allowed, quota, resource)
        self.body['server']['flavorRef'] = 3
        self.req.body = jsonutils.dumps(self.body)
        try:
            server = self.controller.create(self.req, self.body).obj['server']
            self.fail('expected quota to be exceeded')
        except webob.exc.HTTPRequestEntityTooLarge as e:
            self.assertEqual(e.explanation, expected_msg)

    def test_create_instance_above_quota_instances(self):
        msg = _('Quota exceeded for instances: Requested 1, but'
                ' already used 10 of 10 instances')
        self._do_test_create_instance_above_quota('instances', 0, 10, msg)

    def test_create_instance_above_quota_ram(self):
        msg = _('Quota exceeded for ram: Requested 4096, but'
                ' already used 8192 of 10240 ram')
        self._do_test_create_instance_above_quota('ram', 2048, 10 * 1024, msg)

    def test_create_instance_above_quota_cores(self):
        msg = _('Quota exceeded for cores: Requested 2, but'
                ' already used 9 of 10 cores')
        self._do_test_create_instance_above_quota('cores', 1, 10, msg)


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
        self.assertEqual(request['body'], expected)

    def test_request_with_alternate_namespace_prefix(self):
        serial_request = """
<ns2:server xmlns:ns2="http://docs.openstack.org/compute/api/v2"
        name="new-server-test"
        imageRef="1"
        flavorRef="2">
        <ns2:metadata><ns2:meta key="hello">world</ns2:meta></ns2:metadata>
        </ns2:server>
        """
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                'metadata': {"hello": "world"},
                },
            }
        self.assertEqual(request['body'], expected)

    def test_request_with_scheduler_hints_and_alternate_namespace_prefix(self):
        serial_request = """
<ns2:server xmlns:ns2="http://docs.openstack.org/compute/api/v2"
     name="new-server-test"
     imageRef="1"
     flavorRef="2">
     <ns2:metadata><ns2:meta key="hello">world</ns2:meta></ns2:metadata>
     <os:scheduler_hints
     xmlns:os="http://docs.openstack.org/compute/ext/scheduler-hints/api/v2">
             <hypervisor>xen</hypervisor>
             <near>eb999657-dd6b-464e-8713-95c532ac3b18</near>
     </os:scheduler_hints>
     </ns2:server>
        """
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server": {
                'OS-SCH-HNT:scheduler_hints': {
                    'hypervisor': ['xen'],
                    'near': ['eb999657-dd6b-464e-8713-95c532ac3b18']
                },
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "2",
                "metadata": {
                    "hello": "world"
                }
            }
        }
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertThat(request['body'], matchers.DictMatches(expected))

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

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
        self.assertEqual(request['body'], expected)

    def test_request_with_availability_zone(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     name="new-server-test" imageRef="1" flavorRef="1"
     availability_zone="some_zone:some_host">
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "availability_zone": "some_zone:some_host",
                }}
        self.assertEqual(request['body'], expected)

    def test_request_with_multiple_create_args(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     name="new-server-test" imageRef="1" flavorRef="1"
     min_count="1" max_count="3" return_reservation_id="True">
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "min_count": "1",
                "max_count": "3",
                "return_reservation_id": True,
                }}
        self.assertEqual(request['body'], expected)

    def test_request_with_disk_config(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     xmlns:OS-DCF="http://docs.openstack.org/compute/ext/disk_config/api/v1.1"
     name="new-server-test" imageRef="1" flavorRef="1"
     OS-DCF:diskConfig="AUTO">
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "OS-DCF:diskConfig": "AUTO",
                }}
        self.assertEqual(request['body'], expected)

    def test_request_with_scheduler_hints(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     xmlns:OS-SCH-HNT=
     "http://docs.openstack.org/compute/ext/scheduler-hints/api/v2"
     name="new-server-test" imageRef="1" flavorRef="1">
       <OS-SCH-HNT:scheduler_hints>
         <different_host>
           7329b667-50c7-46a6-b913-cb2a09dfeee0
         </different_host>
         <different_host>
           f31efb24-34d2-43e1-8b44-316052956a39
         </different_host>
       </OS-SCH-HNT:scheduler_hints>
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "OS-SCH-HNT:scheduler_hints": {
                    "different_host": [
                        "7329b667-50c7-46a6-b913-cb2a09dfeee0",
                        "f31efb24-34d2-43e1-8b44-316052956a39",
                    ]
                }
                }}
        self.assertEqual(request['body'], expected)

    def test_request_with_block_device_mapping(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
     name="new-server-test" imageRef="1" flavorRef="1">
       <block_device_mapping>
         <mapping volume_id="7329b667-50c7-46a6-b913-cb2a09dfeee0"
          device_name="/dev/vda" virtual_name="root"
          delete_on_termination="False" />
         <mapping snapshot_id="f31efb24-34d2-43e1-8b44-316052956a39"
          device_name="/dev/vdb" virtual_name="ephemeral0"
          delete_on_termination="False" />
         <mapping device_name="/dev/vdc" no_device="True" />
       </block_device_mapping>
    </server>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {"server": {
                "name": "new-server-test",
                "imageRef": "1",
                "flavorRef": "1",
                "block_device_mapping": [
                    {
                        "volume_id": "7329b667-50c7-46a6-b913-cb2a09dfeee0",
                        "device_name": "/dev/vda",
                        "virtual_name": "root",
                        "delete_on_termination": False,
                    },
                    {
                        "snapshot_id": "f31efb24-34d2-43e1-8b44-316052956a39",
                        "device_name": "/dev/vdb",
                        "virtual_name": "ephemeral0",
                        "delete_on_termination": False,
                    },
                    {
                        "device_name": "/dev/vdc",
                        "no_device": True,
                    },
                ]
                }}
        self.assertEqual(request['body'], expected)

    def test_request_with_config_drive(self):
        serial_request = """
    <server xmlns="http://docs.openstack.org/compute/api/v2"
        name="config_drive_test"
        imageRef="1"
        flavorRef="1"
        config_drive="true"/>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server": {
                "name": "config_drive_test",
                "imageRef": "1",
                "flavorRef": "1",
                "config_drive": "true"
            },
        }
        self.assertEqual(request['body'], expected)

    def test_corrupt_xml(self):
        """Should throw a 400 error on corrupt xml."""
        self.assertRaises(
                exception.MalformedRequestBody,
                self.deserializer.deserialize,
                utils.killer_xml_body())


class TestServerActionRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerActionRequestXMLDeserializer, self).setUp()
        self.deserializer = servers.ActionDeserializer()

    def _generate_request(self, action, disk_cfg, ref):
        return """
<%(action)s xmlns="http://docs.openstack.org/compute/api/v1.1"
   xmlns:OS-DCF="http://docs.openstack.org/compute/ext/disk_config/api/v1.1"
   %(disk_config)s="MANUAL" %(ref)s="1"/>""" % (
               {'action': action, 'disk_config': disk_cfg, 'ref': ref})

    def _generate_expected(self, action, ref):
        return {
            "%s" % action: {
                "%s" % ref: "1",
                "OS-DCF:diskConfig": "MANUAL",
            },
        }

    def test_rebuild_request(self):
        serial_request = self._generate_request("rebuild", "OS-DCF:diskConfig",
                                                "imageRef")
        request = self.deserializer.deserialize(serial_request)
        expected = self._generate_expected("rebuild", "imageRef")
        self.assertEqual(request['body'], expected)

    def test_rebuild_request_auto_disk_config_compat(self):
        serial_request = self._generate_request("rebuild", "auto_disk_config",
                                                "imageRef")
        request = self.deserializer.deserialize(serial_request)
        expected = self._generate_expected("rebuild", "imageRef")
        self.assertEqual(request['body'], expected)

    def test_resize_request(self):
        serial_request = self._generate_request("resize", "OS-DCF:diskConfig",
                                                "flavorRef")
        request = self.deserializer.deserialize(serial_request)
        expected = self._generate_expected("resize", "flavorRef")
        self.assertEqual(request['body'], expected)

    def test_resize_request_auto_disk_config_compat(self):
        serial_request = self._generate_request("resize", "auto_disk_config",
                                                "flavorRef")
        request = self.deserializer.deserialize(serial_request)
        expected = self._generate_expected("resize", "flavorRef")
        self.assertEqual(request['body'], expected)


class TestAddressesXMLSerialization(test.TestCase):

    index_serializer = ips.AddressesTemplate()
    show_serializer = ips.NetworkTemplate()

    def _serializer_test_data(self):
        return {
            'network_2': [
                {'addr': '192.168.0.1', 'version': 4},
                {'addr': 'fe80::beef', 'version': 6},
            ],
        }

    def test_xml_declaration(self):
        output = self.show_serializer.serialize(self._serializer_test_data())
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        output = self.show_serializer.serialize(self._serializer_test_data())
        root = etree.XML(output)
        network = self._serializer_test_data()['network_2']
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

    image_bookmark = "http://localhost/fake/images/5"
    flavor_bookmark = "http://localhost/fake/flavors/1"

    def setUp(self):
        super(ServersViewBuilderTest, self).setUp()
        self.flags(use_ipv6=True)
        db_inst = fakes.stub_instance(
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

        self.uuid = db_inst['uuid']
        self.view_builder = views.servers.ViewBuilder()
        self.request = fakes.HTTPRequest.blank("/v2/fake")
        self.request.context = context.RequestContext('fake', 'fake')
        self.instance = fake_instance.fake_instance_obj(
                    self.request.context,
                    expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS,
                    **db_inst)
        self.self_link = "http://localhost/v2/fake/servers/%s" % self.uuid
        self.bookmark_link = "http://localhost/fake/servers/%s" % self.uuid
        self.expected_detailed_server = {
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
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": self.image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": self.flavor_bookmark,
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
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
            }
        }

        self.expected_server = {
            "server": {
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
            }
        }

    def test_get_flavor_valid_flavor(self):
        expected = {"id": "1",
                    "links": [{"rel": "bookmark",
                               "href": self.flavor_bookmark}]}
        result = self.view_builder._get_flavor(self.request, self.instance)
        self.assertEqual(result, expected)

    def test_build_server(self):
        output = self.view_builder.basic(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_server))

    def test_build_server_with_project_id(self):

        output = self.view_builder.basic(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_server))

    def test_build_server_detail(self):

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_detailed_server))

    def test_build_server_no_image(self):
        self.instance["image_ref"] = ""
        output = self.view_builder.show(self.request, self.instance)
        self.assertEqual(output['server']['image'], "")

    def test_build_server_detail_with_fault(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                     self.request.context, self.uuid)

        self.expected_detailed_server["server"]["status"] = "ERROR"
        self.expected_detailed_server["server"]["fault"] = {
                    "code": 404,
                    "created": "2010-10-10T12:00:00Z",
                    "message": "HTTPNotFound",
                    "details": "Stock details for test",
                }
        del self.expected_detailed_server["server"]["progress"]

        self.request.context = context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_detailed_server))

    def test_build_server_detail_with_fault_that_has_been_deleted(self):
        self.instance['deleted'] = 1
        self.instance['vm_state'] = vm_states.ERROR
        fault = fake_instance.fake_fault_obj(self.request.context,
                                             self.uuid, code=500,
                                             message="No valid host was found")
        self.instance['fault'] = fault

        # Regardless of the vm_state deleted servers sholud have DELETED status
        self.expected_detailed_server["server"]["status"] = "DELETED"
        self.expected_detailed_server["server"]["fault"] = {
                    "code": 500,
                    "created": "2010-10-10T12:00:00Z",
                    "message": "No valid host was found",
                }
        del self.expected_detailed_server["server"]["progress"]

        self.request.context = context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_detailed_server))

    def test_build_server_detail_with_fault_no_details_not_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.context = context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error",
                          'details': 'Stock details for test'}

        self.request.environ['nova.context'].is_admin = True
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_no_details_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error',
                                                   details='')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.environ['nova.context'].is_admin = True
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_but_active(self):
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                     self.request.context, self.uuid)

        output = self.view_builder.show(self.request, self.instance)
        self.assertNotIn('fault', output['server'])

    def test_build_server_detail_active_status(self):
        #set the power state of the instance to running
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100

        self.expected_detailed_server["server"]["status"] = "ACTIVE"
        self.expected_detailed_server["server"]["progress"] = 100

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_detailed_server))

    def test_build_server_detail_with_accessipv4(self):

        access_ip_v4 = '1.2.3.4'
        self.instance['access_ip_v4'] = access_ip_v4

        self.expected_detailed_server["server"]["accessIPv4"] = access_ip_v4
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_detailed_server))

    def test_build_server_detail_with_accessipv6(self):

        access_ip_v6 = 'fead::1234'
        self.instance['access_ip_v6'] = access_ip_v6

        self.expected_detailed_server["server"]["accessIPv6"] = access_ip_v6

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_detailed_server))

    def test_build_server_detail_with_metadata(self):

        metadata = []
        metadata.append(models.InstanceMetadata(key="Open", value="Stack"))
        metadata = nova_utils.metadata_to_dict(metadata)
        self.instance['metadata'] = metadata

        self.expected_detailed_server["server"]["metadata"] = {"Open": "Stack"}
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output,
                matchers.DictMatches(self.expected_detailed_server))


class ServerXMLSerializationTest(test.TestCase):

    TIMESTAMP = "2010-10-11T10:30:22Z"
    SERVER_HREF = 'http://localhost/v2/servers/%s' % FAKE_UUID
    SERVER_NEXT = 'http://localhost/v2/servers?limit=%s&marker=%s'
    SERVER_BOOKMARK = 'http://localhost/servers/%s' % FAKE_UUID
    IMAGE_BOOKMARK = 'http://localhost/images/5'
    FLAVOR_BOOKMARK = 'http://localhost/flavors/1'
    USERS_ATTRIBUTES = ['name', 'id', 'created', 'accessIPv4',
                    'updated', 'progress', 'status', 'hostId',
                    'accessIPv6']
    ADMINS_ATTRIBUTES = USERS_ATTRIBUTES + ['adminPass']

    def setUp(self):
        super(ServerXMLSerializationTest, self).setUp()
        self.body = {
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

    def _validate_xml(self, root, server_dict):

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

    def _validate_required_attributes(self, root, server_dict, attributes):
        for key in attributes:
            self.assertEqual(root.get(key), str(server_dict[key]))

    def test_xml_declaration(self):
        serializer = servers.ServerTemplate()

        output = serializer.serialize(self.body)
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        serializer = servers.ServerTemplate()

        output = serializer.serialize(self.body)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = self.body['server']

        self._validate_required_attributes(root, server_dict,
                self.USERS_ATTRIBUTES)
        self._validate_xml(root, server_dict)

    def test_create(self):
        serializer = servers.FullServerTemplate()

        self.body["server"]["adminPass"] = "test_password"

        output = serializer.serialize(self.body)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = self.body['server']

        self._validate_required_attributes(root, server_dict,
                self.ADMINS_ATTRIBUTES)
        self._validate_xml(root, server_dict)

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
            self._validate_required_attributes(server_elem, server_dict,
                    self.USERS_ATTRIBUTES)
            self._validate_xml(server_elem, server_dict)

    def test_update(self):
        serializer = servers.ServerTemplate()

        self.body["server"]["fault"] = {
                    "code": 500,
                    "created": self.TIMESTAMP,
                    "message": "Error Message",
                    "details": "Fault details",
                }
        output = serializer.serialize(self.body)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = self.body['server']

        self._validate_required_attributes(root, server_dict,
                self.USERS_ATTRIBUTES)

        self._validate_xml(root, server_dict)
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

        self.body["server"]["adminPass"] = "test_password"
        output = serializer.serialize(self.body)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'server')

        server_dict = self.body['server']

        self._validate_required_attributes(root, server_dict,
                self.ADMINS_ATTRIBUTES)

        self._validate_xml(root, server_dict)


class ServersAllExtensionsTestCase(test.TestCase):
    """Servers tests using default API router with all extensions enabled.

    The intent here is to catch cases where extensions end up throwing
    an exception because of a malformed request before the core API
    gets a chance to validate the request and return a 422 response.

    For example, ServerDiskConfigController extends servers.Controller:

      @wsgi.extends
      def create(self, req, body):
          if 'server' in body:
                self._set_disk_config(body['server'])
          resp_obj = (yield)
          self._show(req, resp_obj)

    we want to ensure that the extension isn't barfing on an invalid
    body.
    """

    def setUp(self):
        super(ServersAllExtensionsTestCase, self).setUp()
        self.app = compute.APIRouter()

    def test_create_missing_server(self):
        # Test create with malformed body.

        def fake_create(*args, **kwargs):
            raise test.TestingException("Should not reach the compute API.")

        self.stubs.Set(compute_api.API, 'create', fake_create)

        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'foo': {'a': 'b'}}

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(422, res.status_int)

    def test_update_missing_server(self):
        # Test create with malformed body.

        def fake_update(*args, **kwargs):
            raise test.TestingException("Should not reach the compute API.")

        self.stubs.Set(compute_api.API, 'create', fake_update)

        req = fakes.HTTPRequest.blank('/fake/servers/1')
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'foo': {'a': 'b'}}

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(422, res.status_int)


class ServersUnprocessableEntityTestCase(test.TestCase):
    """Tests of places we throw 422 Unprocessable Entity from."""

    def setUp(self):
        super(ServersUnprocessableEntityTestCase, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = servers.Controller(self.ext_mgr)

    def _unprocessable_server_create(self, body):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, body)

    def test_create_server_no_body(self):
        self._unprocessable_server_create(body=None)

    def test_create_server_missing_server(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_server_create(body=body)

    def test_create_server_malformed_entity(self):
        body = {'server': 'string'}
        self._unprocessable_server_create(body=body)

    def _unprocessable_server_update(self, body):
        req = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update, req, FAKE_UUID, body)

    def test_update_server_no_body(self):
        self._unprocessable_server_update(body=None)

    def test_update_server_missing_server(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_server_update(body=body)

    def test_create_update_malformed_entity(self):
        body = {'server': 'string'}
        self._unprocessable_server_update(body=body)
