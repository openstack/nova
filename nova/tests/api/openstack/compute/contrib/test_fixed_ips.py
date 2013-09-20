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

from nova.api.openstack.compute.contrib import fixed_ips
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


fake_fixed_ips = [{'id': 1,
                   'address': '192.168.1.1',
                   'network_id': 1,
                   'virtual_interface_id': 1,
                   'instance_uuid': '1',
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'host': None,
                   'deleted': False},
                  {'id': 2,
                   'address': '192.168.1.2',
                   'network_id': 1,
                   'virtual_interface_id': 2,
                   'instance_uuid': '2',
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'host': None,
                   'deleted': False},
                  {'id': 3,
                   'address': '10.0.0.2',
                   'network_id': 1,
                   'virtual_interface_id': 3,
                   'instance_uuid': '3',
                   'allocated': False,
                   'leased': False,
                   'reserved': False,
                   'host': None,
                   'deleted': True},
                  ]


def fake_fixed_ip_get_by_address(context, address):
    for fixed_ip in fake_fixed_ips:
        if fixed_ip['address'] == address and not fixed_ip['deleted']:
            return fixed_ip
    raise exception.FixedIpNotFoundForAddress(address=address)


def fake_fixed_ip_get_by_address_detailed(context, address):
    network = {'id': 1,
               'cidr': "192.168.1.0/24"}
    for fixed_ip in fake_fixed_ips:
        if fixed_ip['address'] == address and not fixed_ip['deleted']:
            return (fixed_ip, FakeModel(network), None)
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


class FixedIpTest(test.NoDBTestCase):

    def setUp(self):
        super(FixedIpTest, self).setUp()

        self.stubs.Set(db, "fixed_ip_get_by_address",
                       fake_fixed_ip_get_by_address)
        self.stubs.Set(db, "fixed_ip_get_by_address_detailed",
                       fake_fixed_ip_get_by_address_detailed)
        self.stubs.Set(db, "fixed_ip_update", fake_fixed_ip_update)

        self.context = context.get_admin_context()
        self.controller = fixed_ips.FixedIPController()

    def test_fixed_ips_get(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-fixed-ips/192.168.1.1')
        res_dict = self.controller.show(req, '192.168.1.1')
        response = {'fixed_ip': {'cidr': '192.168.1.0/24',
                                 'hostname': None,
                                 'host': None,
                                 'address': '192.168.1.1'}}
        self.assertEqual(response, res_dict)

    def test_fixed_ips_get_bad_ip_fail(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-fixed-ips/10.0.0.1')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show, req,
                          '10.0.0.1')

    def test_fixed_ips_get_invalid_ip_address(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-fixed-ips/inv.ali.d.ip')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show, req,
                          'inv.ali.d.ip')

    def test_fixed_ips_get_deleted_ip_fail(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-fixed-ips/10.0.0.2')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show, req,
                          '10.0.0.2')

    def test_fixed_ip_reserve(self):
        fake_fixed_ips[0]['reserved'] = False
        body = {'reserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/192.168.1.1/action')
        result = self.controller.action(req, "192.168.1.1", body)

        self.assertEqual('202 Accepted', result.status)
        self.assertEqual(fake_fixed_ips[0]['reserved'], True)

    def test_fixed_ip_reserve_bad_ip(self):
        body = {'reserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/10.0.0.1/action')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.action, req,
                          '10.0.0.1', body)

    def test_fixed_ip_reserve_invalid_ip_address(self):
        body = {'reserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/inv.ali.d.ip/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.action, req, 'inv.ali.d.ip', body)

    def test_fixed_ip_reserve_deleted_ip(self):
        body = {'reserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/10.0.0.2/action')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.action, req,
                          '10.0.0.2', body)

    def test_fixed_ip_unreserve(self):
        fake_fixed_ips[0]['reserved'] = True
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/192.168.1.1/action')
        result = self.controller.action(req, "192.168.1.1", body)

        self.assertEqual('202 Accepted', result.status)
        self.assertEqual(fake_fixed_ips[0]['reserved'], False)

    def test_fixed_ip_unreserve_bad_ip(self):
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/10.0.0.1/action')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.action, req,
                          '10.0.0.1', body)

    def test_fixed_ip_unreserve_invalid_ip_address(self):
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/inv.ali.d.ip/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.action, req, 'inv.ali.d.ip', body)

    def test_fixed_ip_unreserve_deleted_ip(self):
        body = {'unreserve': None}
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-fixed-ips/10.0.0.2/action')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.action, req,
                          '10.0.0.2', body)
