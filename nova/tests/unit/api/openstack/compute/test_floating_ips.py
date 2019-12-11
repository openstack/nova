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
from nova import compute
from nova import context
from nova.db import api as db
from nova import exception
from nova import network
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_network


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
TEST_INST = 1
WRONG_INST = 9999


def network_api_get_floating_ip(self, context, id):
    return {'id': 1, 'address': '10.10.10.10', 'pool': 'nova',
            'fixed_ip_id': None}


def network_api_get_floating_ip_by_address(self, context, address):
    return {'id': 1, 'address': '10.10.10.10', 'pool': 'nova',
            'fixed_ip_id': 10}


def network_api_get_floating_ips_by_project(self, context):
    return [{'id': 1,
             'address': '10.10.10.10',
             'pool': 'nova',
             'fixed_ip': {'address': '10.0.0.1',
                          'instance_uuid': FAKE_UUID,
                          'instance': objects.Instance(
                              **{'uuid': FAKE_UUID})}},
            {'id': 2,
             'pool': 'nova', 'interface': 'eth0',
             'address': '10.10.10.11',
             'fixed_ip': None}]


def compute_api_get(self, context, instance_id, expected_attrs=None,
                    cell_down_support=False):
    return objects.Instance(uuid=FAKE_UUID, id=instance_id,
                            instance_type_id=1, host='bob')


def network_api_allocate(self, context):
    return '10.10.10.10'


def network_api_release(self, context, address):
    pass


def compute_api_associate(self, context, instance_id, address):
    pass


def network_api_associate(self, context, floating_address, fixed_address):
    pass


def network_api_disassociate(self, context, instance, floating_address):
    pass


def fake_instance_get(context, instance_id):
    return objects.Instance(**{
        "id": 1,
        "uuid": uuids.fake,
        "name": 'fake',
        "user_id": 'fakeuser',
        "project_id": '123'
    })


def stub_nw_info(test):
    def get_nw_info_for_instance(instance):
        return fake_network.fake_get_instance_nw_info(test)
    return get_nw_info_for_instance


def get_instance_by_floating_ip_addr(self, context, address):
    return None


class FloatingIpTestV21(test.NoDBTestCase):
    floating_ips = fips_v21

    def setUp(self):
        super(FloatingIpTestV21, self).setUp()
        self.controller = self.floating_ips.FloatingIPController()

    def test_floatingip_delete(self):
        req = fakes.HTTPRequest.blank('')
        fip_val = {'address': '1.1.1.1', 'fixed_ip_id': '192.168.1.2'}
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
                               return_value={'address': 'foo'}), \
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
        raised_exc = exception.CannotDisassociateAutoAssignedFloatingIP
        expected_exc = webob.exc.HTTPForbidden
        self._test_floatingip_delete_error_disassociate(raised_exc,
                                                        expected_exc)

    def test_floatingip_delete_error_disassociate_3(self):
        raised_exc = exception.FloatingIpNotFoundForAddress(address='1.1.1.1')
        expected_exc = webob.exc.HTTPNotFound
        self._test_floatingip_delete_error_disassociate(raised_exc,
                                                        expected_exc)


class ExtendedFloatingIpTestV21(test.TestCase):
    floating_ip = "10.10.10.10"
    floating_ip_2 = "10.10.10.11"
    floating_ips = fips_v21

    def _create_floating_ips(self, floating_ips=None):
        """Create a floating IP object."""
        if floating_ips is None:
            floating_ips = [self.floating_ip]
        elif not isinstance(floating_ips, (list, tuple)):
            floating_ips = [floating_ips]

        dict_ = {'pool': 'nova', 'host': 'fake_host'}
        return db.floating_ip_bulk_create(
            self.context, [dict(address=ip, **dict_) for ip in floating_ips],
        )

    def _delete_floating_ip(self):
        db.floating_ip_destroy(self.context, self.floating_ip)

    def setUp(self):
        super(ExtendedFloatingIpTestV21, self).setUp()
        self.stubs.Set(compute.api.API, "get",
                       compute_api_get)
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
        self.stubs.Set(network.api.API, "get_instance_id_by_floating_address",
                       get_instance_by_floating_ip_addr)
        self.stubs.Set(objects.Instance, "get_network_info",
                       stub_nw_info(self))

        fake_network.stub_out_nw_api_get_instance_nw_info(self)
        self.stub_out('nova.db.api.instance_get',
                      fake_instance_get)

        self.context = context.get_admin_context()
        self._create_floating_ips()

        self.controller = self.floating_ips.FloatingIPController()
        self.manager = self.floating_ips.\
                       FloatingIPActionController()
        self.fake_req = fakes.HTTPRequest.blank('')

    def tearDown(self):
        self._delete_floating_ip()
        super(ExtendedFloatingIpTestV21, self).tearDown()

    def test_extended_floating_ip_associate_fixed(self):
        fixed_address = '192.168.1.101'

        def fake_associate_floating_ip(*args, **kwargs):
            self.assertEqual(fixed_address, kwargs['fixed_address'])

        body = dict(addFloatingIp=dict(address=self.floating_ip,
                                       fixed_address=fixed_address))

        with mock.patch.object(self.manager.network_api,
                               'associate_floating_ip',
                               fake_associate_floating_ip):
            rsp = self.manager._add_floating_ip(self.fake_req, TEST_INST,
                                                body=body)
        self.assertEqual(202, rsp.status_int)

    def test_extended_floating_ip_associate_fixed_not_allocated(self):
        def fake_associate_floating_ip(*args, **kwargs):
            pass

        self.stubs.Set(network.api.API, "associate_floating_ip",
                       fake_associate_floating_ip)
        body = dict(addFloatingIp=dict(address=self.floating_ip,
                                       fixed_address='11.11.11.11'))

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.manager._add_floating_ip,
                               self.fake_req, TEST_INST, body=body)

        self.assertIn("Specified fixed address not assigned to instance",
                      ex.explanation)


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
        self._common_policy_check(self.controller.show, self.req, FAKE_UUID)

    def test_create_policy_failed(self):
        self._common_policy_check(self.controller.create, self.req)

    def test_delete_policy_failed(self):
        self._common_policy_check(self.controller.delete, self.req, FAKE_UUID)


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
            self.controller._add_floating_ip, self.req, FAKE_UUID, body=body)

    def test_remove_policy_failed(self):
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        self._common_policy_check(
            self.controller._remove_floating_ip, self.req,
            FAKE_UUID, body=body)


class FloatingIpsDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIpsDeprecationTest, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version='2.36')
        self.controller = fips_v21.FloatingIPController()

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID)


class FloatingIpActionDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIpActionDeprecationTest, self).setUp()
        self.req = fakes.HTTPRequest.blank('', version='2.44')
        self.controller = fips_v21.FloatingIPActionController()

    def test_add_floating_ip_not_found(self):
        body = dict(addFloatingIp=dict(address='10.10.10.11'))
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._add_floating_ip, self.req, FAKE_UUID, body=body)

    def test_remove_floating_ip_not_found(self):
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._remove_floating_ip, self.req, FAKE_UUID,
            body=body)
