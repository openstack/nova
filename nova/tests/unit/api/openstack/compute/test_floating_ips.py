# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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

import mock
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import floating_ips as fips_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


class FloatingIpTestV21(test.NoDBTestCase):
    floating_ips = fips_v21

    def setUp(self):
        super(FloatingIpTestV21, self).setUp()
        self.controller = self.floating_ips.FloatingIPController()

    def test_floatingip_delete(self):
        req = fakes.HTTPRequest.blank('')
        fip_val = {
            'floating_ip_address': '1.1.1.1',
            'fixed_ip_address': '192.168.1.2',
        }
        with test.nested(
            mock.patch.object(self.controller.network_api,
                              'disassociate_floating_ip'),
            mock.patch.object(self.controller.network_api,
                              'disassociate_and_release_floating_ip'),
            mock.patch.object(self.controller.network_api,
                              'release_floating_ip'),
            mock.patch.object(self.controller.network_api,
                             'get_instance_id_by_floating_address',
                              return_value=None),
            mock.patch.object(self.controller.network_api,
                              'get_floating_ip',
                              return_value=fip_val)) as (
                disoc_fip, dis_and_del, rel_fip, _, _):
            self.controller.delete(req, 1)
            self.assertFalse(disoc_fip.called)
            self.assertFalse(rel_fip.called)
            # Only disassociate_and_release_floating_ip is
            # called if using neutron
            self.assertTrue(dis_and_del.called)

    def _test_floatingip_delete_not_found(self, ex,
                                          expect_ex=webob.exc.HTTPNotFound):
        req = fakes.HTTPRequest.blank('')
        with mock.patch.object(self.controller.network_api,
                               'get_floating_ip', side_effect=ex):
            self.assertRaises(expect_ex,
                              self.controller.delete, req, 1)

    def test_floatingip_delete_not_found_ip(self):
        ex = exception.FloatingIpNotFound(id=1)
        self._test_floatingip_delete_not_found(ex)

    def test_floatingip_delete_not_found(self):
        ex = exception.NotFound
        self._test_floatingip_delete_not_found(ex)

    def test_floatingip_delete_invalid_id(self):
        ex = exception.InvalidID(id=1)
        self._test_floatingip_delete_not_found(ex, webob.exc.HTTPBadRequest)

    def _test_floatingip_delete_error_disassociate(self, raised_exc,
                                                   expected_exc):
        """Ensure that various exceptions are correctly transformed.

        Handle the myriad exceptions that could be raised from the
        'disassociate_and_release_floating_ip' call.
        """
        req = fakes.HTTPRequest.blank('')
        with mock.patch.object(self.controller.network_api,
                               'get_floating_ip',
                               return_value={'floating_ip_address': 'foo'}), \
             mock.patch.object(self.controller.network_api,
                               'get_instance_id_by_floating_address',
                               return_value=None), \
             mock.patch.object(self.controller.network_api,
                               'disassociate_and_release_floating_ip',
                               side_effect=raised_exc):
            self.assertRaises(expected_exc,
                              self.controller.delete, req, 1)

    def test_floatingip_delete_error_disassociate_1(self):
        raised_exc = exception.Forbidden
        expected_exc = webob.exc.HTTPForbidden
        self._test_floatingip_delete_error_disassociate(raised_exc,
                                                        expected_exc)

    def test_floatingip_delete_error_disassociate_2(self):
        raised_exc = exception.FloatingIpNotFoundForAddress(address='1.1.1.1')
        expected_exc = webob.exc.HTTPNotFound
        self._test_floatingip_delete_error_disassociate(raised_exc,
                                                        expected_exc)


class FloatingIPPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIPPolicyEnforcementV21, self).setUp()
        self.controller = fips_v21.FloatingIPController()
        self.req = fakes.HTTPRequest.blank('')

    def _common_policy_check(self, func, *arg, **kwarg):
        rule_name = "os_compute_api:os-floating-ips"
        rule = {rule_name: "project:non_fake"}
        self.policy.set_rules(rule)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
        exc.format_message())

    def test_index_policy_failed(self):
        self._common_policy_check(self.controller.index, self.req)

    def test_show_policy_failed(self):
        self._common_policy_check(self.controller.show, self.req, uuids.fake)

    def test_create_policy_failed(self):
        self._common_policy_check(self.controller.create, self.req)

    def test_delete_policy_failed(self):
        self._common_policy_check(self.controller.delete, self.req, uuids.fake)


class FloatingIPActionPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIPActionPolicyEnforcementV21, self).setUp()
        self.controller = fips_v21.FloatingIPActionController()
        self.req = fakes.HTTPRequest.blank('')

    def _common_policy_check(self, func, *arg, **kwarg):
        rule_name = "os_compute_api:os-floating-ips"
        rule = {rule_name: "project:non_fake"}
        self.policy.set_rules(rule)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
        exc.format_message())

    def test_add_policy_failed(self):
        body = dict(addFloatingIp=dict(address='10.10.10.11'))
        self._common_policy_check(
            self.controller._add_floating_ip, self.req, uuids.fake, body=body)

    def test_remove_policy_failed(self):
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        self._common_policy_check(
            self.controller._remove_floating_ip, self.req,
            uuids.fake, body=body)


class FloatingIpsDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIpsDeprecationTest, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version='2.36')
        self.controller = fips_v21.FloatingIPController()

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, uuids.fake)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, uuids.fake)


class FloatingIpActionDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIpActionDeprecationTest, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version='2.44')
        self.controller = fips_v21.FloatingIPActionController()

    def test_add_floating_ip_not_found(self):
        body = dict(addFloatingIp=dict(address='10.10.10.11'))
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._add_floating_ip, self.req, uuids.fake, body=body)

    def test_remove_floating_ip_not_found(self):
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._remove_floating_ip, self.req, uuids.fake,
            body=body)
