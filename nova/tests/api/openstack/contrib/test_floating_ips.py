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

import json
import stubout
import webob

from nova import compute
from nova import context
from nova import db
from nova import network
from nova import rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests.api.openstack import test_servers


from nova.api.openstack.contrib.floating_ips import FloatingIPController
from nova.api.openstack.contrib.floating_ips import _translate_floating_ip_view


def network_api_get_floating_ip(self, context, id):
    return {'id': 1, 'address': '10.10.10.10',
            'fixed_ip': None}


def network_api_get_floating_ip_by_ip(self, context, address):
    return {'id': 1, 'address': '10.10.10.10',
            'fixed_ip': {'address': '10.0.0.1', 'instance_id': 1}},


def network_api_list_floating_ips(self, context):
    return [{'id': 1,
             'address': '10.10.10.10',
             'fixed_ip': {'address': '10.0.0.1', 'instance_id': 1}},
            {'id': 2,
             'address': '10.10.10.11'}]


def network_api_allocate(self, context):
    return '10.10.10.10'


def network_api_release(self, context, address):
    pass


def compute_api_associate(self, context, instance_id, floating_ip):
    pass


def network_api_associate(self, context, floating_ip, fixed_ip):
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
        "user_id": 'fakeuser',
        "project_id": '123'}


class FloatingIpTest(test.TestCase):
    address = "10.10.10.10"

    def _create_floating_ip(self):
        """Create a floating ip object."""
        host = "fake_host"
        return db.floating_ip_create(self.context,
                                     {'address': self.address,
                                      'host': host})

    def _delete_floating_ip(self):
        db.floating_ip_destroy(self.context, self.address)

    def setUp(self):
        super(FloatingIpTest, self).setUp()
        self.stubs.Set(network.api.API, "get_floating_ip",
                       network_api_get_floating_ip)
        self.stubs.Set(network.api.API, "get_floating_ip_by_ip",
                       network_api_get_floating_ip)
        self.stubs.Set(network.api.API, "list_floating_ips",
                       network_api_list_floating_ips)
        self.stubs.Set(network.api.API, "release_floating_ip",
                       network_api_release)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       network_api_disassociate)
        self.stubs.Set(network.api.API, "get_instance_nw_info",
                       network_get_instance_nw_info)
        self.stubs.Set(db.api, 'instance_get',
                       fake_instance_get)

        self.context = context.get_admin_context()
        self._create_floating_ip()

    def tearDown(self):
        self._delete_floating_ip()
        super(FloatingIpTest, self).tearDown()

    def test_translate_floating_ip_view(self):
        floating_ip_address = self._create_floating_ip()
        floating_ip = db.floating_ip_get_by_address(self.context,
                                                    floating_ip_address)
        view = _translate_floating_ip_view(floating_ip)
        self.assertTrue('floating_ip' in view)
        self.assertTrue(view['floating_ip']['id'])
        self.assertEqual(view['floating_ip']['ip'], self.address)
        self.assertEqual(view['floating_ip']['fixed_ip'], None)
        self.assertEqual(view['floating_ip']['instance_id'], None)

    def test_translate_floating_ip_view_dict(self):
        floating_ip = {'id': 0, 'address': '10.0.0.10', 'fixed_ip': None}
        view = _translate_floating_ip_view(floating_ip)
        self.assertTrue('floating_ip' in view)

    def test_floating_ips_list(self):
        req = webob.Request.blank('/v1.1/123/os-floating-ips')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        response = {'floating_ips': [{'instance_id': 1,
                                      'ip': '10.10.10.10',
                                      'fixed_ip': '10.0.0.1',
                                      'id': 1},
                                     {'instance_id': None,
                                      'ip': '10.10.10.11',
                                      'fixed_ip': None,
                                      'id': 2}]}
        self.assertEqual(res_dict, response)

    def test_floating_ip_show(self):
        req = webob.Request.blank('/v1.1/123/os-floating-ips/1')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['floating_ip']['id'], 1)
        self.assertEqual(res_dict['floating_ip']['ip'], '10.10.10.10')
        self.assertEqual(res_dict['floating_ip']['instance_id'], None)

    def test_show_associated_floating_ip(self):
        def get_floating_ip(self, context, id):
            return {'id': 1, 'address': '10.10.10.10',
                    'fixed_ip': {'address': '10.0.0.1', 'instance_id': 1}}
        self.stubs.Set(network.api.API, "get_floating_ip", get_floating_ip)

        req = webob.Request.blank('/v1.1/123/os-floating-ips/1')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertEqual(res_dict['floating_ip']['id'], 1)
        self.assertEqual(res_dict['floating_ip']['ip'], '10.10.10.10')
        self.assertEqual(res_dict['floating_ip']['instance_id'], 1)

    def test_floating_ip_allocate_no_free_ips(self):
        def fake_call(*args, **kwargs):
            raise(rpc.RemoteError('NoMoreFloatingIps', '', ''))

        self.stubs.Set(rpc, "call", fake_call)
        req = webob.Request.blank('/v1.1/123/os-floating-ips')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_floating_ip_allocate(self):
        self.stubs.Set(network.api.API, "allocate_floating_ip",
                       network_api_allocate)
        req = webob.Request.blank('/v1.1/123/os-floating-ips')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        ip = json.loads(res.body)['floating_ip']

        expected = {
            "id": 1,
            "instance_id": None,
            "ip": "10.10.10.10",
            "fixed_ip": None}
        self.assertEqual(ip, expected)

    def test_floating_ip_release_associated(self):
        self.disassociated = False

        def get_floating_ip(ignore, context, id):
            return {'id': 1, 'address': '10.10.10.10',
                    'fixed_ip': {'id': 1}}

        def disassociate(ignore, context, floating_address):
            self.disassociated = True

        self.stubs.Set(network.api.API, "get_floating_ip",
                       get_floating_ip)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       disassociate)
        req = webob.Request.blank('/v1.1/123/os-floating-ips/1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertTrue(self.disassociated)

    def test_floating_ip_release_disassociated(self):
        self.disassociated = False

        def fake_get_floating_ip(ignore, context, id):
            return {'id': 1, 'address': '10.10.10.10',
                    'fixed_ip': None}

        def fake_disassociate(ignore, context, floating_address):
            self.disassociated = True

        self.stubs.Set(network.api.API, "get_floating_ip",
                       fake_get_floating_ip)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       fake_disassociate)
        req = webob.Request.blank('/v1.1/123/os-floating-ips/1')
        req.method = 'DELETE'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertFalse(self.disassociated)

    def test_add_floating_ip_to_instance(self):
        self.stubs.Set(network.api.API, "associate_floating_ip",
                       network_api_associate)
        body = dict(addFloatingIp=dict(address='11.0.0.1'))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)

    def test_associate_floating_ip_to_instance_wrong_project_id(self):
        def fake_fixed_ip_get_by_address(ctx, address, session=None):
            return {'address': address, 'network': {'multi_host': None,
                                                    'host': 'fake'}}
        self.stubs.Set(db.api, "fixed_ip_get_by_address",
                       fake_fixed_ip_get_by_address)
        db.floating_ip_update(self.context, self.address, {'project_id': 'bad',
                                                           'fixed_ip_id': 1})
        body = dict(addFloatingIp=dict(address=self.address))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 401)

    def test_associate_floating_ip_to_instance_no_project_id(self):
        def fake_fixed_ip_get_by_address(ctx, address, session=None):
            return {'address': address, 'network': {'multi_host': None,
                                                    'host': 'fake'}}
        self.stubs.Set(db.api, "fixed_ip_get_by_address",
                       fake_fixed_ip_get_by_address)
        db.floating_ip_update(self.context, self.address, {'project_id': None,
                                                           'fixed_ip_id': 1})
        body = dict(addFloatingIp=dict(address=self.address))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_add_associated_floating_ip_to_instance(self):
        def fake_fixed_ip_get_by_address(ctx, address, session=None):
            return {'address': address, 'network': {'multi_host': None,
                                                    'host': 'fake'}}

        self.disassociated = False

        def fake_network_api_disassociate(local_self, ctx, floating_address):
            self.disassociated = True

        db.floating_ip_update(self.context, self.address, {'project_id': '123',
                                                           'fixed_ip_id': 1})
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       fake_network_api_disassociate)
        self.stubs.Set(db.api, "fixed_ip_get_by_address",
                       fake_fixed_ip_get_by_address)

        body = dict(addFloatingIp=dict(address=self.address))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)
        self.assertTrue(self.disassociated)

    def test_remove_associated_floating_ip_from_instance(self):
        self.disassociated = False

        def fake_get_floating_ip_by_ip(ignore, context, ip):
            return {'id': 1, 'address': '10.10.10.10',
                    'fixed_ip': {'id': 1}}

        def fake_disassociate(ignore, context, floating_address):
            self.disassociated = True

        self.stubs.Set(network.api.API, "get_floating_ip_by_ip",
                       fake_get_floating_ip_by_ip)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       fake_disassociate)
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)
        self.assertTrue(self.disassociated)

    def test_remove_disassociated_floating_ip_from_instance(self):
        self.disassociated = False

        def fake_get_floating_ip_by_ip(ignore, context, ip):
            return {'id': 1, 'address': '10.10.10.10',
                    'fixed_ip': None}

        def fake_disassociate(ignore, context, floating_address):
            self.disassociated = True

        self.stubs.Set(network.api.API, "get_floating_ip_by_ip",
                       fake_get_floating_ip_by_ip)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       fake_disassociate)
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)
        self.assertFalse(self.disassociated)

    def test_bad_address_param_in_remove_floating_ip(self):
        body = dict(removeFloatingIp=dict(badparam='11.0.0.1'))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_missing_dict_param_in_remove_floating_ip(self):
        body = dict(removeFloatingIp='11.0.0.1')
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_bad_address_param_in_add_floating_ip(self):
        body = dict(addFloatingIp=dict(badparam='11.0.0.1'))
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_missing_dict_param_in_add_floating_ip(self):
        body = dict(addFloatingIp='11.0.0.1')
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)
