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
from oslo_config import cfg
import webob

from nova.api.openstack.compute import floating_ips_bulk \
        as fipbulk_v21
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel as uuids

CONF = cfg.CONF


class FloatingIPBulkV21(test.TestCase):

    floating_ips_bulk = fipbulk_v21
    bad_request = exception.ValidationError

    def setUp(self):
        super(FloatingIPBulkV21, self).setUp()

        self.context = context.get_admin_context()
        self.controller = self.floating_ips_bulk.FloatingIPBulkController()
        self.req = fakes.HTTPRequest.blank('')

    def _setup_floating_ips(self, ip_range):
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        res_dict = self.controller.create(self.req, body=body)
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
        res_dict = self.controller.create(self.req, body=body)
        response = {"floating_ips_bulk_create": {
                'ip_range': ip_range,
                'pool': pool,
                'interface': CONF.public_interface}}
        self.assertEqual(res_dict, response)

    def test_list_ips(self):
        self._test_list_ips(self.req)

    def _test_list_ips(self, req):
        ip_range = '192.168.1.1/28'
        self._setup_floating_ips(ip_range)
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

    def test_list_ips_associated(self):
        self._test_list_ips_associated(self.req)

    @mock.patch('nova.objects.FloatingIPList.get_all')
    def _test_list_ips_associated(self, req, mock_get):
        instance_uuid = uuids.instance
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
        self._test_list_ip_by_host(self.req)

    def _test_list_ip_by_host(self, req):
        ip_range = '192.168.1.1/28'
        self._setup_floating_ips(ip_range)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'host')

    def test_delete_ips(self):
        self._test_delete_ips(self.req)

    def _test_delete_ips(self, req):
        ip_range = '192.168.1.0/29'
        self._setup_floating_ips(ip_range)

        body = {'ip_range': ip_range}
        res_dict = self.controller.update(req, "delete", body=body)

        response = {"floating_ips_bulk_delete": ip_range}
        self.assertEqual(res_dict, response)

        # Check that the IPs are actually deleted
        res_dict = self.controller.index(req)
        response = {'floating_ip_info': []}
        self.assertEqual(res_dict, response)

    def test_create_duplicate_fail(self):
        ip_range = '192.168.1.0/30'
        self._setup_floating_ips(ip_range)

        ip_range = '192.168.1.0/29'
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                          self.req, body=body)

    def test_create_bad_cidr_fail(self):
        # netaddr can't handle /32 or 31 cidrs
        ip_range = '192.168.1.1/32'
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, body=body)

    def test_create_invalid_cidr_fail(self):
        ip_range = 'not a cidr'
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body=body)


class FloatingIPBulkPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIPBulkPolicyEnforcementV21, self).setUp()
        self.controller = fipbulk_v21.FloatingIPBulkController()
        self.req = fakes.HTTPRequest.blank('')

    def _common_policy_check(self, func, *arg, **kwarg):
        rule_name = "os_compute_api:os-floating-ips-bulk"
        rule = {rule_name: "project:non_fake"}
        self.policy.set_rules(rule)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_policy_failed(self):
        self._common_policy_check(self.controller.index, self.req)

    def test_show_ip_policy_failed(self):
        self._common_policy_check(self.controller.show, self.req, "host")

    def test_create_policy_failed(self):
        ip_range = '192.168.1.0/28'
        body = {'floating_ips_bulk_create': {'ip_range': ip_range}}
        self._common_policy_check(self.controller.create, self.req, body=body)

    def test_update_policy_failed(self):
        ip_range = '192.168.1.0/29'
        body = {'ip_range': ip_range}
        self._common_policy_check(self.controller.update, self.req,
                                  "delete", body=body)


class FloatingIPBulkDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIPBulkDeprecationTest, self).setUp()
        self.controller = fipbulk_v21.FloatingIPBulkController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.update, self.req, fakes.FAKE_UUID, {})
