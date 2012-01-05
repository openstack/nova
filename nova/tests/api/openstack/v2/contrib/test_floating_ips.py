# Copyright 2011 Eldar Nugaev
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

from nova.api.openstack.v2.contrib import floating_ips
from nova import context
from nova import db
from nova import network
from nova import rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def network_api_get_floating_ip(self, context, id):
    return {'id': 1, 'address': '10.10.10.10',
            'fixed_ip': None}


def network_api_get_floating_ip_by_address(self, context, address):
    return {'id': 1, 'address': '10.10.10.10',
            'fixed_ip': {'address': '10.0.0.1',
                         'instance': {'uuid': FAKE_UUID}}}


def network_api_get_floating_ips_by_project(self, context):
    return [{'id': 1,
             'address': '10.10.10.10',
             'fixed_ip': {'address': '10.0.0.1',
                          'instance': {'uuid': FAKE_UUID}}},
            {'id': 2,
             'address': '10.10.10.11'}]


def network_api_allocate(self, context):
    return '10.10.10.10'


def network_api_release(self, context, address):
    pass


def compute_api_associate(self, context, instance_id, address):
    pass


def network_api_associate(self, context, floating_address, fixed_address):
    pass


def network_api_disassociate(self, context, floating_address):
    pass


def network_get_instance_nw_info(self, context, instance):
    info = {
        'label': 'fake',
        'gateway': 'fake',
        'dhcp_server': 'fake',
        'broadcast': 'fake',
        'mac': 'fake',
        'vif_uuid': 'fake',
        'rxtx_cap': 'fake',
        'dns': [],
        'ips': [{'ip': '10.0.0.1'}],
        'should_create_bridge': False,
        'should_create_vlan': False}

    return [['ignore', info]]


def fake_instance_get(context, instance_id):
        return {
        "id": 1,
        "uuid": utils.gen_uuid(),
        "name": 'fake',
        "user_id": 'fakeuser',
        "project_id": '123'}


class StubExtensionManager(object):
    def register(self, *args):
        pass


class FloatingIpTest(test.TestCase):
    floating_ip = "10.10.10.10"

    def _create_floating_ip(self):
        """Create a floating ip object."""
        host = "fake_host"
        return db.floating_ip_create(self.context,
                                     {'address': self.floating_ip,
                                      'host': host})

    def _delete_floating_ip(self):
        db.floating_ip_destroy(self.context, self.floating_ip)

    def setUp(self):
        super(FloatingIpTest, self).setUp()
        self.stubs.Set(network.api.API, "get_floating_ip",
                       network_api_get_floating_ip)
        self.stubs.Set(network.api.API, "get_floating_ip_by_address",
                       network_api_get_floating_ip_by_address)
        self.stubs.Set(network.api.API, "get_floating_ips_by_project",
                       network_api_get_floating_ips_by_project)
        self.stubs.Set(network.api.API, "release_floating_ip",
                       network_api_release)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       network_api_disassociate)
        self.stubs.Set(network.api.API, "get_instance_nw_info",
                       network_get_instance_nw_info)
        self.stubs.Set(db, 'instance_get',
                       fake_instance_get)

        self.context = context.get_admin_context()
        self._create_floating_ip()

        self.controller = floating_ips.FloatingIPController()
        self.manager = floating_ips.Floating_ips(StubExtensionManager())

    def tearDown(self):
        self._delete_floating_ip()
        super(FloatingIpTest, self).tearDown()

    def test_translate_floating_ip_view(self):
        floating_ip_address = self._create_floating_ip()
        floating_ip = db.floating_ip_get_by_address(self.context,
                                                    floating_ip_address)
        view = floating_ips._translate_floating_ip_view(floating_ip)
        self.assertTrue('floating_ip' in view)
        self.assertTrue(view['floating_ip']['id'])
        self.assertEqual(view['floating_ip']['ip'], self.floating_ip)
        self.assertEqual(view['floating_ip']['fixed_ip'], None)
        self.assertEqual(view['floating_ip']['instance_id'], None)

    def test_translate_floating_ip_view_dict(self):
        floating_ip = {'id': 0, 'address': '10.0.0.10', 'fixed_ip': None}
        view = floating_ips._translate_floating_ip_view(floating_ip)
        self.assertTrue('floating_ip' in view)

    def test_floating_ips_list(self):
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ips')
        res_dict = self.controller.index(req)

        response = {'floating_ips': [{'instance_id': FAKE_UUID,
                                      'ip': '10.10.10.10',
                                      'fixed_ip': '10.0.0.1',
                                      'id': 1},
                                     {'instance_id': None,
                                      'ip': '10.10.10.11',
                                      'fixed_ip': None,
                                      'id': 2}]}
        self.assertEqual(res_dict, response)

    def test_floating_ip_show(self):
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ips/1')
        res_dict = self.controller.show(req, 1)

        self.assertEqual(res_dict['floating_ip']['id'], 1)
        self.assertEqual(res_dict['floating_ip']['ip'], '10.10.10.10')
        self.assertEqual(res_dict['floating_ip']['instance_id'], None)

    def test_show_associated_floating_ip(self):
        def get_floating_ip(self, context, id):
            return {'id': 1, 'address': '10.10.10.10',
                    'fixed_ip': {'address': '10.0.0.1',
                                 'instance': {'uuid': FAKE_UUID}}}
        self.stubs.Set(network.api.API, "get_floating_ip", get_floating_ip)

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ips/1')
        res_dict = self.controller.show(req, 1)

        self.assertEqual(res_dict['floating_ip']['id'], 1)
        self.assertEqual(res_dict['floating_ip']['ip'], '10.10.10.10')
        self.assertEqual(res_dict['floating_ip']['instance_id'], FAKE_UUID)

# test floating ip allocate/release(deallocate)
    def test_floating_ip_allocate_no_free_ips(self):
        def fake_call(*args, **kwargs):
            raise(rpc.RemoteError('NoMoreFloatingIps', '', ''))

        self.stubs.Set(rpc, "call", fake_call)

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ips')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req)

    def test_floating_ip_allocate(self):
        def fake1(*args, **kwargs):
            pass

        def fake2(*args, **kwargs):
            return {'id': 1, 'address': '10.10.10.10'}

        self.stubs.Set(network.api.API, "allocate_floating_ip",
                       fake1)
        self.stubs.Set(network.api.API, "get_floating_ip_by_address",
                       fake2)

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ips')
        res_dict = self.controller.create(req)

        ip = res_dict['floating_ip']

        expected = {
            "id": 1,
            "instance_id": None,
            "ip": "10.10.10.10",
            "fixed_ip": None}
        self.assertEqual(ip, expected)

    def test_floating_ip_release(self):
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ips/1')
        self.controller.delete(req, 1)

# test floating ip add/remove -> associate/disassociate

    def test_floating_ip_associate(self):
        body = dict(addFloatingIp=dict(address=self.floating_ip))

        req = fakes.HTTPRequest.blank('/v2/123/servers/test_inst/action')
        self.manager._add_floating_ip(body, req, 'test_inst')

    def test_floating_ip_disassociate(self):
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))

        req = fakes.HTTPRequest.blank('/v2/123/servers/test_inst/action')
        self.manager._remove_floating_ip(body, req, 'test_inst')

# these are a few bad param tests

    def test_bad_address_param_in_remove_floating_ip(self):
        body = dict(removeFloatingIp=dict(badparam='11.0.0.1'))

        req = fakes.HTTPRequest.blank('/v2/123/servers/test_inst/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._add_floating_ip, body, req,
                          'test_inst')

    def test_missing_dict_param_in_remove_floating_ip(self):
        body = dict(removeFloatingIp='11.0.0.1')

        req = fakes.HTTPRequest.blank('/v2/123/servers/test_inst/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._remove_floating_ip, body, req,
                          'test_inst')

    def test_missing_dict_param_in_add_floating_ip(self):
        body = dict(addFloatingIp='11.0.0.1')

        req = fakes.HTTPRequest.blank('/v2/123/servers/test_inst/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._add_floating_ip, body, req,
                          'test_inst')


class FloatingIpSerializerTest(test.TestCase):
    def test_default_serializer(self):
        serializer = floating_ips.FloatingIPSerializer()
        text = serializer.serialize(dict(
                floating_ip=dict(
                    instance_id=1,
                    ip='10.10.10.10',
                    fixed_ip='10.0.0.1',
                    id=1)))

        tree = etree.fromstring(text)

        self.assertEqual('floating_ip', tree.tag)
        self.assertEqual('1', tree.get('instance_id'))
        self.assertEqual('10.10.10.10', tree.get('ip'))
        self.assertEqual('10.0.0.1', tree.get('fixed_ip'))
        self.assertEqual('1', tree.get('id'))

    def test_index_serializer(self):
        serializer = floating_ips.FloatingIPSerializer()
        text = serializer.serialize(dict(
                floating_ips=[
                    dict(instance_id=1,
                         ip='10.10.10.10',
                         fixed_ip='10.0.0.1',
                         id=1),
                    dict(instance_id=None,
                         ip='10.10.10.11',
                         fixed_ip=None,
                         id=2)]), 'index')

        tree = etree.fromstring(text)

        self.assertEqual('floating_ips', tree.tag)
        self.assertEqual(2, len(tree))
        self.assertEqual('floating_ip', tree[0].tag)
        self.assertEqual('floating_ip', tree[1].tag)
        self.assertEqual('1', tree[0].get('instance_id'))
        self.assertEqual('None', tree[1].get('instance_id'))
        self.assertEqual('10.10.10.10', tree[0].get('ip'))
        self.assertEqual('10.10.10.11', tree[1].get('ip'))
        self.assertEqual('10.0.0.1', tree[0].get('fixed_ip'))
        self.assertEqual('None', tree[1].get('fixed_ip'))
        self.assertEqual('1', tree[0].get('id'))
        self.assertEqual('2', tree[1].get('id'))
