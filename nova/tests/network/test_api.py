# Copyright 2012 Red Hat, Inc.
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

"""Tests for network API."""

import contextlib
import itertools

import mock
import mox

from nova.compute import flavors
from nova import context
from nova import exception
from nova import network
from nova.network import api
from nova.network import base_api
from nova.network import floating_ips
from nova.network import model as network_model
from nova.network import rpcapi as network_rpcapi
from nova.objects import fields
from nova.objects import fixed_ip as fixed_ip_obj
from nova.objects import network as network_obj
from nova import policy
from nova import test
from nova.tests import fake_instance
from nova.tests.objects import test_fixed_ip
from nova.tests.objects import test_flavor
from nova import utils

FAKE_UUID = 'a47ae74e-ab08-547f-9eee-ffd23fc46c16'


class NetworkPolicyTestCase(test.TestCase):
    def setUp(self):
        super(NetworkPolicyTestCase, self).setUp()

        policy.reset()
        policy.init()

        self.context = context.get_admin_context()

    def tearDown(self):
        super(NetworkPolicyTestCase, self).tearDown()
        policy.reset()

    def test_check_policy(self):
        self.mox.StubOutWithMock(policy, 'enforce')
        target = {
            'project_id': self.context.project_id,
            'user_id': self.context.user_id,
        }
        policy.enforce(self.context, 'network:get_all', target)
        self.mox.ReplayAll()
        api.check_policy(self.context, 'get_all')


class ApiTestCase(test.TestCase):
    def setUp(self):
        super(ApiTestCase, self).setUp()
        self.network_api = network.API()
        self.context = context.RequestContext('fake-user',
                                              'fake-project')

    def test_allocate_for_instance_handles_macs_passed(self):
        # If a macs argument is supplied to the 'nova-network' API, it is just
        # ignored. This test checks that the call down to the rpcapi layer
        # doesn't pass macs down: nova-network doesn't support hypervisor
        # mac address limits (today anyhow).
        macs = set(['ab:cd:ef:01:23:34'])
        self.mox.StubOutWithMock(
            self.network_api.network_rpcapi, "allocate_for_instance")
        kwargs = dict(zip(['host', 'instance_id', 'project_id',
                'requested_networks', 'rxtx_factor', 'vpn', 'macs',
                'dhcp_options'],
                itertools.repeat(mox.IgnoreArg())))
        self.network_api.network_rpcapi.allocate_for_instance(
            mox.IgnoreArg(), **kwargs).AndReturn([])
        self.mox.ReplayAll()
        flavor = flavors.get_default_flavor()
        flavor['rxtx_factor'] = 0
        sys_meta = flavors.save_flavor_info({}, flavor)
        instance = dict(id='id', uuid='uuid', project_id='project_id',
            host='host', system_metadata=utils.dict_to_metadata(sys_meta))
        self.network_api.allocate_for_instance(
            self.context, instance, 'vpn', 'requested_networks', macs=macs)

    def _do_test_associate_floating_ip(self, orig_instance_uuid):
        """Test post-association logic."""

        new_instance = {'uuid': 'new-uuid'}

        def fake_associate(*args, **kwargs):
            return orig_instance_uuid

        self.stubs.Set(floating_ips.FloatingIP, 'associate_floating_ip',
                       fake_associate)

        def fake_instance_get_by_uuid(context, instance_uuid):
            return {'uuid': instance_uuid}

        self.stubs.Set(self.network_api.db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid)

        def fake_get_nw_info(ctxt, instance):
            class FakeNWInfo(object):
                def json(self):
                    pass
            return FakeNWInfo()

        self.stubs.Set(self.network_api, '_get_instance_nw_info',
                       fake_get_nw_info)

        if orig_instance_uuid:
            expected_updated_instances = [new_instance['uuid'],
                                          orig_instance_uuid]
        else:
            expected_updated_instances = [new_instance['uuid']]

        def fake_instance_info_cache_update(context, instance_uuid, cache):
            self.assertEqual(instance_uuid,
                             expected_updated_instances.pop())

        self.stubs.Set(self.network_api.db, 'instance_info_cache_update',
                       fake_instance_info_cache_update)

        def fake_update_instance_cache_with_nw_info(api, context, instance,
                                                    nw_info=None,
                                                    update_cells=True):
            return

        self.stubs.Set(base_api, "update_instance_cache_with_nw_info",
                       fake_update_instance_cache_with_nw_info)

        self.network_api.associate_floating_ip(self.context,
                                               new_instance,
                                               '172.24.4.225',
                                               '10.0.0.2')

    def test_associate_preassociated_floating_ip(self):
        self._do_test_associate_floating_ip('orig-uuid')

    def test_associate_unassociated_floating_ip(self):
        self._do_test_associate_floating_ip(None)

    def test_get_floating_ip_invalid_id(self):
        self.assertRaises(exception.InvalidID,
                          self.network_api.get_floating_ip,
                          self.context, '123zzz')

    def _stub_migrate_instance_calls(self, method, multi_host, info):
        fake_flavor = flavors.get_default_flavor()
        fake_flavor['rxtx_factor'] = 1.21
        sys_meta = utils.dict_to_metadata(
            flavors.save_flavor_info({}, fake_flavor))
        fake_instance = {'uuid': 'fake_uuid',
                         'instance_type_id': fake_flavor['id'],
                         'project_id': 'fake_project_id',
                         'system_metadata': sys_meta}
        fake_migration = {'source_compute': 'fake_compute_source',
                          'dest_compute': 'fake_compute_dest'}

        def fake_mig_inst_method(*args, **kwargs):
            info['kwargs'] = kwargs

        def fake_is_multi_host(*args, **kwargs):
            return multi_host

        def fake_get_floaters(*args, **kwargs):
            return ['fake_float1', 'fake_float2']

        self.stubs.Set(network_rpcapi.NetworkAPI, method,
                fake_mig_inst_method)
        self.stubs.Set(self.network_api, '_is_multi_host',
                fake_is_multi_host)
        self.stubs.Set(self.network_api, '_get_floating_ip_addresses',
                fake_get_floaters)

        expected = {'instance_uuid': 'fake_uuid',
                    'source_compute': 'fake_compute_source',
                    'dest_compute': 'fake_compute_dest',
                    'rxtx_factor': 1.21,
                    'project_id': 'fake_project_id',
                    'floating_addresses': None}
        if multi_host:
            expected['floating_addresses'] = ['fake_float1', 'fake_float2']
        return fake_instance, fake_migration, expected

    def test_migrate_instance_start_with_multhost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_start', True, info)
        expected['host'] = 'fake_compute_source'
        self.network_api.migrate_instance_start(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_migrate_instance_start_without_multhost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_start', False, info)
        self.network_api.migrate_instance_start(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_migrate_instance_finish_with_multhost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_finish', True, info)
        expected['host'] = 'fake_compute_dest'
        self.network_api.migrate_instance_finish(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_migrate_instance_finish_without_multhost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_finish', False, info)
        self.network_api.migrate_instance_finish(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_is_multi_host_instance_has_no_fixed_ip(self):
        def fake_fixed_ip_get_by_instance(ctxt, uuid):
            raise exception.FixedIpNotFoundForInstance(instance_uuid=uuid)
        self.stubs.Set(self.network_api.db, 'fixed_ip_get_by_instance',
                       fake_fixed_ip_get_by_instance)
        instance = {'uuid': FAKE_UUID}
        self.assertFalse(self.network_api._is_multi_host(self.context,
                                                         instance))

    @mock.patch('nova.objects.fixed_ip.FixedIPList.get_by_instance_uuid')
    @mock.patch('nova.objects.network.Network.get_by_id')
    def _test_is_multi_host_network_has_no_project_id(self, is_multi_host,
                                                      net_get, fip_get):
        net_get.return_value = network_obj.Network(id=123,
                                                   project_id=None,
                                                   multi_host=is_multi_host)
        fip_get.return_value = [fixed_ip_obj.FixedIP(
                network_id=123, instance_uuid=FAKE_UUID)]
        instance = {'uuid': FAKE_UUID}
        result = self.network_api._is_multi_host(self.context, instance)
        self.assertEqual(is_multi_host, result)

    def test_is_multi_host_network_has_no_project_id_multi(self):
        self._test_is_multi_host_network_has_no_project_id(True)

    def test_is_multi_host_network_has_no_project_id_non_multi(self):
        self._test_is_multi_host_network_has_no_project_id(False)

    @mock.patch('nova.objects.fixed_ip.FixedIPList.get_by_instance_uuid')
    @mock.patch('nova.objects.network.Network.get_by_id')
    def _test_is_multi_host_network_has_project_id(self, is_multi_host,
                                                   net_get, fip_get):
        net_get.return_value = network_obj.Network(
            id=123, project_id=self.context.project_id,
            multi_host=is_multi_host)
        fip_get.return_value = [
            fixed_ip_obj.FixedIP(network_id=123, instance_uuid=FAKE_UUID)]
        instance = {'uuid': FAKE_UUID}
        result = self.network_api._is_multi_host(self.context, instance)
        self.assertEqual(is_multi_host, result)

    def test_is_multi_host_network_has_project_id_multi(self):
        self._test_is_multi_host_network_has_project_id(True)

    def test_is_multi_host_network_has_project_id_non_multi(self):
        self._test_is_multi_host_network_has_project_id(False)

    def test_network_disassociate_project(self):
        def fake_network_disassociate(ctx, network_id, disassociate_host,
                                      disassociate_project):
            self.assertEqual(network_id, 1)
            self.assertEqual(disassociate_host, False)
            self.assertEqual(disassociate_project, True)

        def fake_get(context, network_uuid):
            return {'id': 1}

        self.stubs.Set(self.network_api.db, 'network_disassociate',
                       fake_network_disassociate)
        self.stubs.Set(self.network_api, 'get', fake_get)

        self.network_api.associate(self.context, FAKE_UUID, project=None)

    def _test_refresh_cache(self, method, *args, **kwargs):
        # This test verifies that no call to get_instance_nw_info() is made
        # from the @refresh_cache decorator for the tested method.
        with contextlib.nested(
            mock.patch.object(self.network_api.network_rpcapi, method),
            mock.patch.object(self.network_api.network_rpcapi,
                              'get_instance_nw_info'),
        ) as (
            method_mock, nwinfo_mock
        ):
            method_mock.return_value = network_model.NetworkInfo([])
            getattr(self.network_api, method)(*args, **kwargs)
            self.assertFalse(nwinfo_mock.called)

    def test_allocate_for_instance_refresh_cache(self):
        sys_meta = flavors.save_flavor_info({}, test_flavor.fake_flavor)
        instance = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'],
            system_metadata=sys_meta)
        vpn = 'fake-vpn'
        requested_networks = 'fake-networks'
        self._test_refresh_cache('allocate_for_instance', self.context,
                                 instance, vpn, requested_networks)

    def test_add_fixed_ip_to_instance_refresh_cache(self):
        sys_meta = flavors.save_flavor_info({}, test_flavor.fake_flavor)
        instance = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'],
            system_metadata=sys_meta)
        network_id = 'fake-network-id'
        self._test_refresh_cache('add_fixed_ip_to_instance', self.context,
                                 instance, network_id)

    def test_remove_fixed_ip_from_instance_refresh_cache(self):
        sys_meta = flavors.save_flavor_info({}, test_flavor.fake_flavor)
        instance = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'],
            system_metadata=sys_meta)
        address = 'fake-address'
        self._test_refresh_cache('remove_fixed_ip_from_instance', self.context,
                                 instance, address)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    def test_get_fixed_ip_by_address(self, fip_get):
        fip_get.return_value = test_fixed_ip.fake_fixed_ip
        fip = self.network_api.get_fixed_ip_by_address(self.context,
                                                       'fake-addr')
        self.assertIsInstance(fip, fixed_ip_obj.FixedIP)


@mock.patch('nova.network.api.API')
@mock.patch('nova.db.instance_info_cache_update')
class TestUpdateInstanceCache(test.TestCase):
    def setUp(self):
        super(TestUpdateInstanceCache, self).setUp()
        self.context = context.get_admin_context()
        self.instance = {'uuid': FAKE_UUID}
        vifs = [network_model.VIF(id='super_vif')]
        self.nw_info = network_model.NetworkInfo(vifs)
        self.nw_json = fields.NetworkModel.to_primitive(self, 'network_info',
                                                        self.nw_info)

    def test_update_nw_info_none(self, db_mock, api_mock):
        api_mock._get_instance_nw_info.return_value = self.nw_info

        base_api.update_instance_cache_with_nw_info(api_mock, self.context,
                                               self.instance, None)
        api_mock._get_instance_nw_info.assert_called_once_with(self.context,
                                                                self.instance)
        db_mock.assert_called_once_with(self.context, self.instance['uuid'],
                                        {'network_info': self.nw_json})

    def test_update_nw_info_one_network(self, db_mock, api_mock):
        api_mock._get_instance_nw_info.return_value = self.nw_info
        base_api.update_instance_cache_with_nw_info(api_mock, self.context,
                                               self.instance, self.nw_info)
        self.assertFalse(api_mock._get_instance_nw_info.called)
        db_mock.assert_called_once_with(self.context, self.instance['uuid'],
                                        {'network_info': self.nw_json})

    def test_update_nw_info_empty_list(self, db_mock, api_mock):
        api_mock._get_instance_nw_info.return_value = self.nw_info
        base_api.update_instance_cache_with_nw_info(api_mock, self.context,
                                                self.instance,
                                                network_model.NetworkInfo([]))
        self.assertFalse(api_mock._get_instance_nw_info.called)
        db_mock.assert_called_once_with(self.context, self.instance['uuid'],
                                        {'network_info': '[]'})

    def test_decorator_return_object(self, db_mock, api_mock):
        @base_api.refresh_cache
        def func(self, context, instance):
            return network_model.NetworkInfo([])
        func(api_mock, self.context, self.instance)
        self.assertFalse(api_mock._get_instance_nw_info.called)
        db_mock.assert_called_once_with(self.context, self.instance['uuid'],
                                        {'network_info': '[]'})

    def test_decorator_return_none(self, db_mock, api_mock):
        @base_api.refresh_cache
        def func(self, context, instance):
            pass
        api_mock._get_instance_nw_info.return_value = self.nw_info
        func(api_mock, self.context, self.instance)
        api_mock._get_instance_nw_info.assert_called_once_with(self.context,
                                                                self.instance)
        db_mock.assert_called_once_with(self.context, self.instance['uuid'],
                                        {'network_info': self.nw_json})


class NetworkHooksTestCase(test.BaseHookTestCase):
    def test_instance_network_info_hook(self):
        info_func = base_api.update_instance_cache_with_nw_info
        self.assert_has_hook('instance_network_info', info_func)
