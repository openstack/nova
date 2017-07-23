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
import six
import webob

from nova.api.openstack.compute import floating_ips as fips_v21
from nova import compute
from nova import context
from nova import db
from nova import exception
from nova import network
from nova import objects
from nova.objects import base as obj_base
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_network
from nova.tests import uuidsentinel as uuids


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


def compute_api_get(self, context, instance_id, expected_attrs=None):
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
        "project_id": '123'})


def stub_nw_info(test):
    def get_nw_info_for_instance(instance):
        return fake_network.fake_get_instance_nw_info(test)
    return get_nw_info_for_instance


def get_instance_by_floating_ip_addr(self, context, address):
    return None


class FloatingIpTestNeutronV21(test.NoDBTestCase):
    floating_ips = fips_v21

    def setUp(self):
        super(FloatingIpTestNeutronV21, self).setUp()
        self.flags(use_neutron=True)
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


class FloatingIpTestV21(test.TestCase):
    floating_ip = "10.10.10.10"
    floating_ip_2 = "10.10.10.11"
    floating_ips = fips_v21
    validation_error = exception.ValidationError

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
        super(FloatingIpTestV21, self).setUp()
        self.flags(use_neutron=False)
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
        self.stub_out('nova.db.instance_get',
                      fake_instance_get)

        self.context = context.get_admin_context()
        self._create_floating_ips()

        self.controller = self.floating_ips.FloatingIPController()
        self.manager = self.floating_ips.\
                            FloatingIPActionController()
        self.fake_req = fakes.HTTPRequest.blank('')

    def tearDown(self):
        self._delete_floating_ip()
        super(FloatingIpTestV21, self).tearDown()

    def test_floatingip_delete(self):
        fip_val = {'address': '1.1.1.1', 'fixed_ip_id': '192.168.1.2'}
        with test.nested(
            mock.patch.object(self.controller.network_api,
                              'disassociate_floating_ip'),
            mock.patch.object(self.controller.network_api,
                              'release_floating_ip'),
            mock.patch.object(self.controller.network_api,
                             'get_instance_id_by_floating_address',
                              return_value=None),
            mock.patch.object(self.controller.network_api,
                              'get_floating_ip',
                              return_value=fip_val)) as (
                disoc_fip, rel_fip, _, _):
            self.controller.delete(self.fake_req, 1)
            self.assertTrue(disoc_fip.called)
            self.assertTrue(rel_fip.called)

    def _test_floatingip_delete_not_found(self, ex,
                                          expect_ex=webob.exc.HTTPNotFound):
        with mock.patch.object(self.controller.network_api,
                               'get_floating_ip', side_effect=ex):
            self.assertRaises(expect_ex,
                              self.controller.delete, self.fake_req, 1)

    def test_floatingip_delete_not_found_ip(self):
        ex = exception.FloatingIpNotFound(id=1)
        self._test_floatingip_delete_not_found(ex)

    def test_floatingip_delete_not_found(self):
        ex = exception.NotFound
        self._test_floatingip_delete_not_found(ex)

    def test_floatingip_delete_invalid_id(self):
        ex = exception.InvalidID(id=1)
        self._test_floatingip_delete_not_found(ex, webob.exc.HTTPBadRequest)

    def test_translate_floating_ip_view(self):
        floating_ip_address = self.floating_ip
        floating_ip = db.floating_ip_get_by_address(self.context,
                                                    floating_ip_address)
        # NOTE(vish): network_get uses the id not the address
        floating_ip = db.floating_ip_get(self.context, floating_ip['id'])
        floating_obj = objects.FloatingIP()
        objects.FloatingIP._from_db_object(self.context, floating_obj,
                                           floating_ip)

        view = self.floating_ips._translate_floating_ip_view(floating_obj)

        self.assertIn('floating_ip', view)
        self.assertTrue(view['floating_ip']['id'])
        self.assertEqual(view['floating_ip']['ip'], floating_obj.address)
        self.assertIsNone(view['floating_ip']['fixed_ip'])
        self.assertIsNone(view['floating_ip']['instance_id'])

    def test_translate_floating_ip_view_neutronesque(self):
        uuid = 'ca469a10-fa76-11e5-86aa-5e5517507c66'
        fixed_id = 'ae900cf4-fb73-11e5-86aa-5e5517507c66'
        floating_ip = objects.floating_ip.NeutronFloatingIP(id=uuid,
            address='1.2.3.4', pool='pool', context='ctxt',
            fixed_ip_id=fixed_id)
        view = self.floating_ips._translate_floating_ip_view(floating_ip)
        self.assertEqual(uuid, view['floating_ip']['id'])

    def test_translate_floating_ip_view_dict(self):
        floating_ip = {'id': 0, 'address': '10.0.0.10', 'pool': 'nova',
                       'fixed_ip': None}
        view = self.floating_ips._translate_floating_ip_view(floating_ip)
        self.assertIn('floating_ip', view)

    def test_translate_floating_ip_view_obj(self):
        fip = objects.FixedIP(address='192.168.1.2', instance_uuid=FAKE_UUID)
        floater = self._build_floating_ip('10.0.0.2', fip)

        result = self.floating_ips._translate_floating_ip_view(floater)

        expected = self._build_expected(floater, fip.address,
                                        fip.instance_uuid)
        self._test_result(expected, result)

    def test_translate_floating_ip_bad_address(self):
        fip = objects.FixedIP(instance_uuid=FAKE_UUID)
        floater = self._build_floating_ip('10.0.0.2', fip)

        result = self.floating_ips._translate_floating_ip_view(floater)

        expected = self._build_expected(floater, None, fip.instance_uuid)
        self._test_result(expected, result)

    def test_translate_floating_ip_bad_instance_id(self):
        fip = objects.FixedIP(address='192.168.1.2')
        floater = self._build_floating_ip('10.0.0.2', fip)

        result = self.floating_ips._translate_floating_ip_view(floater)

        expected = self._build_expected(floater, fip.address, None)
        self._test_result(expected, result)

    def test_translate_floating_ip_bad_instance_and_address(self):
        fip = objects.FixedIP()
        floater = self._build_floating_ip('10.0.0.2', fip)

        result = self.floating_ips._translate_floating_ip_view(floater)

        expected = self._build_expected(floater, None, None)
        self._test_result(expected, result)

    def test_translate_floating_ip_null_fixed(self):
        floater = self._build_floating_ip('10.0.0.2', None)

        result = self.floating_ips._translate_floating_ip_view(floater)

        expected = self._build_expected(floater, None, None)
        self._test_result(expected, result)

    def test_translate_floating_ip_unset_fixed(self):
        floater = objects.FloatingIP(id=1, address='10.0.0.2', pool='foo')

        result = self.floating_ips._translate_floating_ip_view(floater)

        expected = self._build_expected(floater, None, None)
        self._test_result(expected, result)

    def test_translate_floating_ips_view(self):
        mock_trans = mock.Mock()
        mock_trans.return_value = {'floating_ip': 'foo'}
        self.floating_ips._translate_floating_ip_view = mock_trans
        fip1 = objects.FixedIP(address='192.168.1.2', instance_uuid=FAKE_UUID)
        fip2 = objects.FixedIP(address='192.168.1.3', instance_uuid=FAKE_UUID)

        floaters = [self._build_floating_ip('10.0.0.2', fip1),
                    self._build_floating_ip('10.0.0.3', fip2)]

        result = self.floating_ips._translate_floating_ips_view(floaters)

        called_floaters = [call[0][0] for call in mock_trans.call_args_list]
        self.assertTrue(any(obj_base.obj_equal_prims(floaters[0], f)
                            for f in called_floaters),
                        "_translate_floating_ip_view was not called with all "
                        "floating ips")
        self.assertTrue(any(obj_base.obj_equal_prims(floaters[1], f)
                            for f in called_floaters),
                        "_translate_floating_ip_view was not called with all "
                        "floating ips")
        expected_result = {'floating_ips': ['foo', 'foo']}
        self.assertEqual(expected_result, result)

    def test_floating_ips_list(self):
        res_dict = self.controller.index(self.fake_req)

        response = {'floating_ips': [{'instance_id': FAKE_UUID,
                                      'ip': '10.10.10.10',
                                      'pool': 'nova',
                                      'fixed_ip': '10.0.0.1',
                                      'id': 1},
                                     {'instance_id': None,
                                      'ip': '10.10.10.11',
                                      'pool': 'nova',
                                      'fixed_ip': None,
                                      'id': 2}]}
        self.assertEqual(res_dict, response)

    def test_floating_ip_release_nonexisting(self):
        def fake_get_floating_ip(*args, **kwargs):
            raise exception.FloatingIpNotFound(id=id)

        self.stubs.Set(network.api.API, "get_floating_ip",
                       fake_get_floating_ip)

        ex = self.assertRaises(webob.exc.HTTPNotFound,
                               self.controller.delete, self.fake_req, '9876')
        self.assertIn("Floating IP not found for ID 9876", ex.explanation)

    def test_floating_ip_release_race_cond(self):
        def fake_get_floating_ip(*args, **kwargs):
            return {'fixed_ip_id': 1, 'address': self.floating_ip}

        def fake_get_instance_by_floating_ip_addr(*args, **kwargs):
            return 'test-inst'

        def fake_disassociate_floating_ip(*args, **kwargs):
            raise exception.FloatingIpNotAssociated(args[3])

        self.stubs.Set(network.api.API, "get_floating_ip",
                fake_get_floating_ip)
        self.stubs.Set(self.floating_ips, "get_instance_by_floating_ip_addr",
                fake_get_instance_by_floating_ip_addr)
        self.stubs.Set(self.floating_ips, "disassociate_floating_ip",
                fake_disassociate_floating_ip)

        delete = self.controller.delete
        res = delete(self.fake_req, '9876')
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller,
                      fips_v21.FloatingIPController):
            status_int = delete.wsgi_code
        else:
            status_int = res.status_int
        self.assertEqual(status_int, 202)

    def test_floating_ip_show(self):
        res_dict = self.controller.show(self.fake_req, 1)

        self.assertEqual(res_dict['floating_ip']['id'], 1)
        self.assertEqual(res_dict['floating_ip']['ip'], '10.10.10.10')
        self.assertIsNone(res_dict['floating_ip']['instance_id'])

    def test_floating_ip_show_not_found(self):
        def fake_get_floating_ip(*args, **kwargs):
            raise exception.FloatingIpNotFound(id='fake')

        self.stubs.Set(network.api.API, "get_floating_ip",
                       fake_get_floating_ip)

        ex = self.assertRaises(webob.exc.HTTPNotFound,
                               self.controller.show, self.fake_req, '9876')
        self.assertIn("Floating IP not found for ID 9876", ex.explanation)

    def test_show_associated_floating_ip(self):
        def get_floating_ip(self, context, id):
            return {'id': 1, 'address': '10.10.10.10', 'pool': 'nova',
                    'fixed_ip': {'address': '10.0.0.1',
                                 'instance_uuid': FAKE_UUID,
                                 'instance': {'uuid': FAKE_UUID}}}

        self.stubs.Set(network.api.API, "get_floating_ip", get_floating_ip)

        res_dict = self.controller.show(self.fake_req, 1)

        self.assertEqual(res_dict['floating_ip']['id'], 1)
        self.assertEqual(res_dict['floating_ip']['ip'], '10.10.10.10')
        self.assertEqual(res_dict['floating_ip']['fixed_ip'], '10.0.0.1')
        self.assertEqual(res_dict['floating_ip']['instance_id'], FAKE_UUID)

    def test_recreation_of_floating_ip(self):
        self._delete_floating_ip()
        self._create_floating_ips()

    def test_floating_ip_in_bulk_creation(self):
        self._delete_floating_ip()

        self._create_floating_ips([self.floating_ip, self.floating_ip_2])
        all_ips = db.floating_ip_get_all(self.context)
        ip_list = [ip['address'] for ip in all_ips]
        self.assertIn(self.floating_ip, ip_list)
        self.assertIn(self.floating_ip_2, ip_list)

    def test_fail_floating_ip_in_bulk_creation(self):
        self.assertRaises(exception.FloatingIpExists,
                          self._create_floating_ips,
                          [self.floating_ip, self.floating_ip_2])
        all_ips = db.floating_ip_get_all(self.context)
        ip_list = [ip['address'] for ip in all_ips]
        self.assertIn(self.floating_ip, ip_list)
        self.assertNotIn(self.floating_ip_2, ip_list)

    def test_floating_ip_allocate_no_free_ips(self):
        def fake_allocate(*args, **kwargs):
            raise exception.NoMoreFloatingIps()

        self.stubs.Set(network.api.API, "allocate_floating_ip", fake_allocate)

        ex = self.assertRaises(webob.exc.HTTPNotFound,
                               self.controller.create, self.fake_req)

        self.assertIn('No more floating IPs', ex.explanation)

    def test_floating_ip_allocate_no_free_ips_pool(self):
        def fake_allocate(*args, **kwargs):
            raise exception.NoMoreFloatingIps()

        self.stubs.Set(network.api.API, "allocate_floating_ip", fake_allocate)

        ex = self.assertRaises(webob.exc.HTTPNotFound,
                               self.controller.create, self.fake_req,
                               {'pool': 'non_existent_pool'})

        self.assertIn('No more floating IPs in pool non_existent_pool',
                      ex.explanation)

    @mock.patch.object(network.api.API, 'allocate_floating_ip',
                       side_effect=exception.FloatingIpBadRequest(
        'Bad floatingip request: Network '
        'c8f0e88f-ae41-47cb-be6c-d8256ba80576 does not contain any '
        'IPv4 subnet'))
    def test_floating_ip_allocate_no_ipv4_subnet(self, allocate_mock):
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create, self.fake_req,
                               {'pool': 'non_existent_pool'})
        self.assertIn("does not contain any IPv4 subnet",
                      six.text_type(ex))

    @mock.patch('nova.network.api.API.allocate_floating_ip',
                side_effect=exception.FloatingIpLimitExceeded())
    def test_floating_ip_allocate_over_quota(self, allocate_mock):
        ex = self.assertRaises(webob.exc.HTTPForbidden,
                               self.controller.create, self.fake_req)

        self.assertIn('IP allocation over quota', ex.explanation)

    @mock.patch('nova.objects.FloatingIP.deallocate')
    @mock.patch('nova.objects.FloatingIP.allocate_address')
    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    def test_floating_ip_allocate_over_quota_during_recheck(self, check_mock,
                                                            alloc_mock,
                                                            dealloc_mock):
        ctxt = self.fake_req.environ['nova.context']

        # Simulate a race where the first check passes and the recheck fails.
        check_mock.side_effect = [None,
                                  exception.OverQuota(overs='floating_ips')]

        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.create, self.fake_req)

        self.assertEqual(2, check_mock.call_count)
        call1 = mock.call(ctxt, {'floating_ips': 1}, ctxt.project_id)
        call2 = mock.call(ctxt, {'floating_ips': 0}, ctxt.project_id)
        check_mock.assert_has_calls([call1, call2])

        # Verify we removed the floating IP that was added after the first
        # quota check passed.
        dealloc_mock.assert_called_once_with(ctxt,
                                             alloc_mock.return_value.address)

    @mock.patch('nova.objects.FloatingIP.allocate_address')
    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    def test_floating_ip_allocate_no_quota_recheck(self, check_mock,
                                                   alloc_mock):
        # Disable recheck_quota.
        self.flags(recheck_quota=False, group='quota')

        ctxt = self.fake_req.environ['nova.context']
        self.controller.create(self.fake_req)

        # check_deltas should have been called only once.
        check_mock.assert_called_once_with(ctxt, {'floating_ips': 1},
                                           ctxt.project_id)

    @mock.patch('nova.network.api.API.allocate_floating_ip',
                side_effect=exception.FloatingIpLimitExceeded())
    def test_floating_ip_allocate_quota_exceed_in_pool(self, allocate_mock):
        ex = self.assertRaises(webob.exc.HTTPForbidden,
                               self.controller.create, self.fake_req,
                               {'pool': 'non_existent_pool'})

        self.assertIn('IP allocation over quota in pool non_existent_pool.',
                      ex.explanation)

    @mock.patch('nova.network.api.API.allocate_floating_ip',
                side_effect=exception.FloatingIpPoolNotFound())
    def test_floating_ip_create_with_unknown_pool(self, allocate_mock):
        ex = self.assertRaises(webob.exc.HTTPNotFound,
                               self.controller.create, self.fake_req,
                               {'pool': 'non_existent_pool'})

        self.assertIn('Floating IP pool not found.', ex.explanation)

    def test_floating_ip_allocate(self):
        def fake1(*args, **kwargs):
            pass

        def fake2(*args, **kwargs):
            return {'id': 1, 'address': '10.10.10.10', 'pool': 'nova'}

        self.stubs.Set(network.api.API, "allocate_floating_ip",
                       fake1)
        self.stubs.Set(network.api.API, "get_floating_ip_by_address",
                       fake2)

        res_dict = self.controller.create(self.fake_req)

        ip = res_dict['floating_ip']

        expected = {
            "id": 1,
            "instance_id": None,
            "ip": "10.10.10.10",
            "fixed_ip": None,
            "pool": 'nova'}
        self.assertEqual(ip, expected)

    def test_floating_ip_release(self):
        self.controller.delete(self.fake_req, 1)

    def _test_floating_ip_associate(self, fixed_address):
        def fake_associate_floating_ip(*args, **kwargs):
            self.assertEqual(fixed_address, kwargs['fixed_address'])

        self.stubs.Set(network.api.API, "associate_floating_ip",
                       fake_associate_floating_ip)
        body = dict(addFloatingIp=dict(address=self.floating_ip))

        rsp = self.manager._add_floating_ip(self.fake_req, TEST_INST,
                                            body=body)
        self.assertEqual(202, rsp.status_int)

    def test_floating_ip_associate(self):
        self._test_floating_ip_associate(fixed_address='192.168.1.100')

    @mock.patch.object(network.model.NetworkInfo, 'fixed_ips')
    def test_associate_floating_ip_v4v6_fixed_ip(self, fixed_ips_mock):
        fixed_address = '192.168.1.100'
        fixed_ips_mock.return_value = [{'address': 'fc00:2001:db8::100'},
                                       {'address': ''},
                                       {'address': fixed_address}]
        self._test_floating_ip_associate(fixed_address=fixed_address)

    @mock.patch.object(network.model.NetworkInfo, 'fixed_ips',
                       return_value=[{'address': 'fc00:2001:db8::100'}])
    def test_associate_floating_ip_v6_fixed_ip(self, fixed_ips_mock):
        body = dict(addFloatingIp=dict(address=self.floating_ip))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._add_floating_ip, self.fake_req,
                          TEST_INST, body=body)

    def test_floating_ip_associate_invalid_instance(self):

        def fake_get(self, context, id, expected_attrs=None):
            raise exception.InstanceNotFound(instance_id=id)

        self.stubs.Set(compute.api.API, "get", fake_get)

        body = dict(addFloatingIp=dict(address=self.floating_ip))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._add_floating_ip, self.fake_req,
                          'test_inst', body=body)

    def test_associate_not_allocated_floating_ip_to_instance(self):
        def fake_associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
            raise exception.FloatingIpNotFoundForAddress(
                address=floating_address)
        self.stubs.Set(network.api.API, "associate_floating_ip",
                       fake_associate_floating_ip)
        floating_ip = '10.10.10.11'
        body = dict(addFloatingIp=dict(address=floating_ip))
        ex = self.assertRaises(webob.exc.HTTPNotFound,
                               self.manager._add_floating_ip,
                               self.fake_req, TEST_INST, body=body)

        self.assertIn("floating IP not found", ex.explanation)

    @mock.patch.object(network.api.API, 'associate_floating_ip',
                       side_effect=exception.Forbidden)
    def test_associate_floating_ip_forbidden(self, associate_mock):
        body = dict(addFloatingIp=dict(address='10.10.10.11'))
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.manager._add_floating_ip, self.fake_req,
                          TEST_INST, body=body)

    @mock.patch.object(network.api.API, 'associate_floating_ip',
                       side_effect=exception.FloatingIpAssociateFailed(
                           address='10.10.10.11'))
    def test_associate_floating_ip_failed(self, associate_mock):
        body = dict(addFloatingIp=dict(address='10.10.10.11'))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._add_floating_ip, self.fake_req,
                          TEST_INST, body=body)

    def test_associate_floating_ip_bad_address_key(self):
        body = dict(addFloatingIp=dict(bad_address='10.10.10.11'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        self.assertRaises(self.validation_error,
                          self.manager._add_floating_ip, req, 'test_inst',
                          body=body)

    def test_associate_floating_ip_bad_addfloatingip_key(self):
        body = dict(bad_addFloatingIp=dict(address='10.10.10.11'))
        req = fakes.HTTPRequest.blank('/v2/fake/servers/test_inst/action')
        self.assertRaises(self.validation_error,
                          self.manager._add_floating_ip, req, 'test_inst',
                          body=body)

    def test_floating_ip_disassociate(self):
        def get_instance_by_floating_ip_addr(self, context, address):
            if address == '10.10.10.10':
                return TEST_INST

        self.stubs.Set(network.api.API, "get_instance_id_by_floating_address",
                       get_instance_by_floating_ip_addr)

        body = dict(removeFloatingIp=dict(address='10.10.10.10'))

        rsp = self.manager._remove_floating_ip(self.fake_req, TEST_INST,
                                               body=body)
        self.assertEqual(202, rsp.status_int)

    def test_floating_ip_disassociate_missing(self):
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))

        self.assertRaises(webob.exc.HTTPConflict,
                          self.manager._remove_floating_ip,
                          self.fake_req, 'test_inst', body=body)

    def test_floating_ip_associate_non_existent_ip(self):
        def fake_network_api_associate(self, context, instance,
                                             floating_address=None,
                                             fixed_address=None):
            floating_ips = ["10.10.10.10", "10.10.10.11"]
            if floating_address not in floating_ips:
                    raise exception.FloatingIpNotFoundForAddress(
                            address=floating_address)

        self.stubs.Set(network.api.API, "associate_floating_ip",
                       fake_network_api_associate)

        body = dict(addFloatingIp=dict(address='1.1.1.1'))
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._add_floating_ip,
                          self.fake_req, TEST_INST, body=body)

    def test_floating_ip_disassociate_non_existent_ip(self):
        def network_api_get_floating_ip_by_address(self, context,
                                                         floating_address):
            floating_ips = ["10.10.10.10", "10.10.10.11"]
            if floating_address not in floating_ips:
                    raise exception.FloatingIpNotFoundForAddress(
                            address=floating_address)

        self.stubs.Set(network.api.API, "get_floating_ip_by_address",
                       network_api_get_floating_ip_by_address)

        body = dict(removeFloatingIp=dict(address='1.1.1.1'))
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._remove_floating_ip,
                          self.fake_req, TEST_INST, body=body)

    def test_floating_ip_disassociate_wrong_instance_uuid(self):
        def get_instance_by_floating_ip_addr(self, context, address):
            if address == '10.10.10.10':
                return TEST_INST

        self.stubs.Set(network.api.API, "get_instance_id_by_floating_address",
                       get_instance_by_floating_ip_addr)

        wrong_uuid = 'aaaaaaaa-ffff-ffff-ffff-aaaaaaaaaaaa'
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))

        self.assertRaises(webob.exc.HTTPConflict,
                          self.manager._remove_floating_ip,
                          self.fake_req, wrong_uuid, body=body)

    def test_floating_ip_disassociate_wrong_instance_id(self):
        def get_instance_by_floating_ip_addr(self, context, address):
            if address == '10.10.10.10':
                return WRONG_INST

        self.stubs.Set(network.api.API, "get_instance_id_by_floating_address",
                       get_instance_by_floating_ip_addr)

        body = dict(removeFloatingIp=dict(address='10.10.10.10'))

        self.assertRaises(webob.exc.HTTPConflict,
                          self.manager._remove_floating_ip,
                          self.fake_req, TEST_INST, body=body)

    def test_floating_ip_disassociate_auto_assigned(self):
        def fake_get_floating_ip_addr_auto_assigned(self, context, address):
            return {'id': 1, 'address': '10.10.10.10', 'pool': 'nova',
            'fixed_ip_id': 10, 'auto_assigned': 1}

        def get_instance_by_floating_ip_addr(self, context, address):
            if address == '10.10.10.10':
                return TEST_INST

        def network_api_disassociate(self, context, instance,
                                     floating_address):
            raise exception.CannotDisassociateAutoAssignedFloatingIP()

        self.stubs.Set(network.api.API, "get_floating_ip_by_address",
                       fake_get_floating_ip_addr_auto_assigned)
        self.stubs.Set(network.api.API, "get_instance_id_by_floating_address",
                       get_instance_by_floating_ip_addr)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       network_api_disassociate)
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.manager._remove_floating_ip,
                          self.fake_req, TEST_INST, body=body)

    def test_floating_ip_disassociate_map_authorization_exc(self):
        def fake_get_floating_ip_addr_auto_assigned(self, context, address):
            return {'id': 1, 'address': '10.10.10.10', 'pool': 'nova',
            'fixed_ip_id': 10, 'auto_assigned': 1}

        def get_instance_by_floating_ip_addr(self, context, address):
            if address == '10.10.10.10':
                return TEST_INST

        def network_api_disassociate(self, context, instance, address):
            raise exception.Forbidden()

        self.stubs.Set(network.api.API, "get_floating_ip_by_address",
                       fake_get_floating_ip_addr_auto_assigned)
        self.stubs.Set(network.api.API, "get_instance_id_by_floating_address",
                       get_instance_by_floating_ip_addr)
        self.stubs.Set(network.api.API, "disassociate_floating_ip",
                       network_api_disassociate)
        body = dict(removeFloatingIp=dict(address='10.10.10.10'))
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.manager._remove_floating_ip,
                          self.fake_req, TEST_INST, body=body)

# these are a few bad param tests

    def test_bad_address_param_in_remove_floating_ip(self):
        body = dict(removeFloatingIp=dict(badparam='11.0.0.1'))

        self.assertRaises(self.validation_error,
                          self.manager._remove_floating_ip, self.fake_req,
                          TEST_INST, body=body)

    def test_missing_dict_param_in_remove_floating_ip(self):
        body = dict(removeFloatingIp='11.0.0.1')

        self.assertRaises(self.validation_error,
                          self.manager._remove_floating_ip, self.fake_req,
                          TEST_INST, body=body)

    def test_missing_dict_param_in_add_floating_ip(self):
        body = dict(addFloatingIp='11.0.0.1')

        self.assertRaises(self.validation_error,
                          self.manager._add_floating_ip, self.fake_req,
                          TEST_INST, body=body)

    def _build_floating_ip(self, address, fixed_ip):
        floating = objects.FloatingIP(id=1, address=address, pool='foo',
                                      fixed_ip=fixed_ip)
        return floating

    def _build_expected(self, floating_ip, fixed_ip, instance_id):
        return {'floating_ip': {'id': floating_ip.id,
                                'ip': floating_ip.address,
                                'pool': floating_ip.pool,
                                'fixed_ip': fixed_ip,
                                'instance_id': instance_id}}

    def _test_result(self, expected, actual):
        expected_fl = expected['floating_ip']
        actual_fl = actual['floating_ip']

        self.assertEqual(expected_fl, actual_fl)


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
        self.stub_out('nova.db.instance_get',
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
