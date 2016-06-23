# Copyright 2012 IBM Corp.
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

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import fixed_ips as fixed_ips_v21
from nova.api.openstack import wsgi as os_wsgi
from nova import context
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.objects import test_network
from nova.tests import uuidsentinel as uuids


fake_fixed_ips = [{'id': 1,
                   'address': '192.168.1.1',
                   'network_id': 1,
                   'virtual_interface_id': 1,
                   'instance_uuid': uuids.instance_1,
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'host': None,
                   'instance': None,
                   'network': test_network.fake_network,
                   'created_at': None,
                   'updated_at': None,
                   'deleted_at': None,
                   'deleted': False},
                  {'id': 2,
                   'address': '192.168.1.2',
                   'network_id': 1,
                   'virtual_interface_id': 2,
                   'instance_uuid': uuids.instance_2,
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'host': None,
                   'instance': None,
                   'network': test_network.fake_network,
                   'created_at': None,
                   'updated_at': None,
                   'deleted_at': None,
                   'deleted': False},
                  {'id': 3,
                   'address': '10.0.0.2',
                   'network_id': 1,
                   'virtual_interface_id': 3,
                   'instance_uuid': uuids.instance_3,
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'host': None,
                   'instance': None,
                   'network': test_network.fake_network,
                   'created_at': None,
                   'updated_at': None,
                   'deleted_at': None,
                   'deleted': True},
                  ]


def fake_fixed_ip_get_by_address(context, address, columns_to_join=None):
    if address == 'inv.ali.d.ip':
        msg = "Invalid fixed IP Address %s in request" % address
        raise exception.FixedIpInvalid(msg)
    for fixed_ip in fake_fixed_ips:
        if fixed_ip['address'] == address and not fixed_ip['deleted']:
            return fixed_ip
    raise exception.FixedIpNotFoundForAddress(address=address)


def fake_fixed_ip_update(context, address, values):
    fixed_ip = fake_fixed_ip_get_by_address(context, address)
    if fixed_ip is None:
        raise exception.FixedIpNotFoundForAddress(address=address)
    else:
        for key in values:
            fixed_ip[key] = values[key]


class FakeModel(object):
    """Stubs out for model."""
    def __init__(self, values):
        self.values = values

    def __getattr__(self, name):
        return self.values[name]

    def __getitem__(self, key):
        if key in self.values:
            return self.values[key]
        else:
            raise NotImplementedError()

    def __repr__(self):
        return '<FakeModel: %s>' % self.values


def fake_network_get_all(context):
    network = {'id': 1,
               'cidr': "192.168.1.0/24"}
    return [FakeModel(network)]


class FixedIpTestV21(test.NoDBTestCase):

    fixed_ips = fixed_ips_v21
    url = '/v2/fake/os-fixed-ips'
    wsgi_api_version = os_wsgi.DEFAULT_API_VERSION

    def setUp(self):
        super(FixedIpTestV21, self).setUp()

        self.stub_out("nova.db.fixed_ip_get_by_address",
                      fake_fixed_ip_get_by_address)
        self.stub_out("nova.db.fixed_ip_update", fake_fixed_ip_update)

        self.context = context.get_admin_context()
        self.controller = self.fixed_ips.FixedIPController()

    def _assert_equal(self, ret, exp):
        self.assertEqual(ret.wsgi_code, exp)

    def _get_reserve_action(self):
        return self.controller.reserve

    def _get_unreserve_action(self):
        return self.controller.unreserve

    def _get_reserved_status(self, address):
        return {}

    def test_fixed_ips_get(self):
        req = fakes.HTTPRequest.blank('%s/192.168.1.1' % self.url)
        req.api_version_request = api_version_request.APIVersionRequest(
                                        self.wsgi_api_version)
        res_dict = self.controller.show(req, '192.168.1.1')
        response = {'fixed_ip': {'cidr': '192.168.1.0/24',
                                 'hostname': None,
                                 'host': None,
                                 'address': '192.168.1.1'}}
        response['fixed_ip'].update(self._get_reserved_status('192.168.1.1'))
        self.assertEqual(response, res_dict, self.wsgi_api_version)

    def test_fixed_ips_get_bad_ip_fail(self):
        req = fakes.HTTPRequest.blank('%s/10.0.0.1' % self.url)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show, req,
                          '10.0.0.1')

    def test_fixed_ips_get_invalid_ip_address(self):
        req = fakes.HTTPRequest.blank('%s/inv.ali.d.ip' % self.url)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.show, req,
                          'inv.ali.d.ip')

    def test_fixed_ips_get_deleted_ip_fail(self):
        req = fakes.HTTPRequest.blank('%s/10.0.0.2' % self.url)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show, req,
                          '10.0.0.2')

    def test_fixed_ip_reserve(self):
        fake_fixed_ips[0]['reserved'] = False
        body = {'reserve': None}
        req = fakes.HTTPRequest.blank('%s/192.168.1.1/action' % self.url)
        action = self._get_reserve_action()
        result = action(req, "192.168.1.1", body=body)

        self._assert_equal(result or action, 202)
        self.assertTrue(fake_fixed_ips[0]['reserved'])

    def test_fixed_ip_reserve_bad_ip(self):
        body = {'reserve': None}
        req = fakes.HTTPRequest.blank('%s/10.0.0.1/action' % self.url)
        action = self._get_reserve_action()

        self.assertRaises(webob.exc.HTTPNotFound, action, req,
                          '10.0.0.1', body=body)

    def test_fixed_ip_reserve_invalid_ip_address(self):
        body = {'reserve': None}
        req = fakes.HTTPRequest.blank('%s/inv.ali.d.ip/action' % self.url)
        action = self._get_reserve_action()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          action, req, 'inv.ali.d.ip', body=body)

    def test_fixed_ip_reserve_deleted_ip(self):
        body = {'reserve': None}
        action = self._get_reserve_action()

        req = fakes.HTTPRequest.blank('%s/10.0.0.2/action' % self.url)
        self.assertRaises(webob.exc.HTTPNotFound, action, req,
                          '10.0.0.2', body=body)

    def test_fixed_ip_unreserve(self):
        fake_fixed_ips[0]['reserved'] = True
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank('%s/192.168.1.1/action' % self.url)
        action = self._get_unreserve_action()
        result = action(req, "192.168.1.1", body=body)

        self._assert_equal(result or action, 202)
        self.assertFalse(fake_fixed_ips[0]['reserved'])

    def test_fixed_ip_unreserve_bad_ip(self):
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank('%s/10.0.0.1/action' % self.url)
        action = self._get_unreserve_action()

        self.assertRaises(webob.exc.HTTPNotFound, action, req,
                          '10.0.0.1', body=body)

    def test_fixed_ip_unreserve_invalid_ip_address(self):
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank('%s/inv.ali.d.ip/action' % self.url)
        action = self._get_unreserve_action()
        self.assertRaises(webob.exc.HTTPBadRequest,
                          action, req, 'inv.ali.d.ip', body=body)

    def test_fixed_ip_unreserve_deleted_ip(self):
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank('%s/10.0.0.2/action' % self.url)
        action = self._get_unreserve_action()
        self.assertRaises(webob.exc.HTTPNotFound, action, req,
                          '10.0.0.2', body=body)


class FixedIpTestV24(FixedIpTestV21):

    wsgi_api_version = '2.4'

    def _get_reserved_status(self, address):
        for fixed_ip in fake_fixed_ips:
            if address == fixed_ip['address']:
                return {'reserved': fixed_ip['reserved']}
        self.fail('Invalid address: %s' % address)


class FixedIpDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FixedIpDeprecationTest, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version='2.36')
        self.controller = fixed_ips_v21.FixedIPController()

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.reserve, self.req, fakes.FAKE_UUID, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.unreserve, self.req, fakes.FAKE_UUID, {})
