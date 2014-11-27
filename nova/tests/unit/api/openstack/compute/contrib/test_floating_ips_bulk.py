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

import mock
import netaddr
from oslo.config import cfg
import webob

from nova.api.openstack.compute.contrib import floating_ips_bulk as fipbulk_v2
from nova.api.openstack.compute.plugins.v3 import floating_ips_bulk as\
                                                      fipbulk_v21
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF


class FloatingIPBulkV21(test.TestCase):

    floating_ips_bulk = fipbulk_v21
    url = '/v2/fake/os-floating-ips-bulk'
    delete_url = '/v2/fake/os-fixed-ips/delete'
    bad_request = exception.ValidationError

    def setUp(self):
        super(FloatingIPBulkV21, self).setUp()

        self.context = context.get_admin_context()
        self.controller = self.floating_ips_bulk.FloatingIPBulkController()

    def _setup_floating_ips(self, ip_range):
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.create(req, body=body)
        response = {"floating_ips_bulk_create": {
                'ip_range': ip_range,
                'pool': CONF.default_floating_pool,
                'interface': CONF.public_interface}}
        self.assertEqual(res_dict, response)

    def test_create_ips(self):
        ip_range = '192.168.1.0/28'
        self._setup_floating_ips(ip_range)

    def test_create_ips_pool(self):
        ip_range = '10.0.1.0/29'
        pool = 'a new pool'
        body = {'floating_ips_bulk_create':
                {'ip_range': ip_range,
                 'pool': pool}}
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.create(req, body=body)
        response = {"floating_ips_bulk_create": {
                'ip_range': ip_range,
                'pool': pool,
                'interface': CONF.public_interface}}
        self.assertEqual(res_dict, response)

    def test_list_ips(self):
        ip_range = '192.168.1.1/28'
        self._setup_floating_ips(ip_range)
        req = fakes.HTTPRequest.blank(self.url, use_admin_context=True)
        res_dict = self.controller.index(req)

        ip_info = [{'address': str(ip_addr),
                    'pool': CONF.default_floating_pool,
                    'interface': CONF.public_interface,
                    'project_id': None,
                    'instance_uuid': None,
                    'fixed_ip': None}
                   for ip_addr in netaddr.IPNetwork(ip_range).iter_hosts()]
        response = {'floating_ip_info': ip_info}

        self.assertEqual(res_dict, response)

    @mock.patch('nova.objects.FloatingIPList.get_all')
    def test_list_ips_associated(self, mock_get):
        instance_uuid = "fake-uuid"
        fixed_address = "10.0.0.1"
        floating_address = "192.168.0.1"
        fixed_ip = objects.FixedIP(instance_uuid=instance_uuid,
                                   address=fixed_address)
        floating_ip = objects.FloatingIP(address=floating_address,
                                         fixed_ip=fixed_ip,
                                         pool=CONF.default_floating_pool,
                                         interface=CONF.public_interface,
                                         project_id=None)
        floating_list = objects.FloatingIPList(objects=[floating_ip])
        mock_get.return_value = floating_list
        req = fakes.HTTPRequest.blank('/v2/fake/os-floating-ips-bulk',
                                      use_admin_context=True)
        res_dict = self.controller.index(req)

        ip_info = [{'address': floating_address,
                    'pool': CONF.default_floating_pool,
                    'interface': CONF.public_interface,
                    'project_id': None,
                    'instance_uuid': instance_uuid,
                    'fixed_ip': fixed_address}]
        response = {'floating_ip_info': ip_info}

        self.assertEqual(res_dict, response)

    def test_list_ip_by_host(self):
        ip_range = '192.168.1.1/28'
        self._setup_floating_ips(ip_range)
        req = fakes.HTTPRequest.blank(self.url, use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'host')

    def test_delete_ips(self):
        ip_range = '192.168.1.0/29'
        self._setup_floating_ips(ip_range)

        body = {'ip_range': ip_range}
        req = fakes.HTTPRequest.blank(self.delete_url)
        res_dict = self.controller.update(req, "delete", body=body)

        response = {"floating_ips_bulk_delete": ip_range}
        self.assertEqual(res_dict, response)

        # Check that the IPs are actually deleted
        req = fakes.HTTPRequest.blank(self.url, use_admin_context=True)
        res_dict = self.controller.index(req)
        response = {'floating_ip_info': []}
        self.assertEqual(res_dict, response)

    def test_create_duplicate_fail(self):
        ip_range = '192.168.1.0/30'
        self._setup_floating_ips(ip_range)

        ip_range = '192.168.1.0/29'
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                          req, body=body)

    def test_create_bad_cidr_fail(self):
        # netaddr can't handle /32 or 31 cidrs
        ip_range = '192.168.1.1/32'
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body=body)

    def test_create_invalid_cidr_fail(self):
        ip_range = 'not a cidr'
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(self.bad_request, self.controller.create,
                          req, body=body)


class FloatingIPBulkV2(FloatingIPBulkV21):
    floating_ips_bulk = fipbulk_v2
    bad_request = webob.exc.HTTPBadRequest
