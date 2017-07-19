# Copyright 2013 Red Hat, Inc.
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

"""
Unit Tests for nova.network.rpcapi
"""

import collections

import mock
from oslo_config import cfg

from nova import context
from nova import exception
from nova.network import rpcapi as network_rpcapi
from nova.objects import base as objects_base
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network

CONF = cfg.CONF


class NetworkRpcAPITestCase(test.NoDBTestCase):
    def setUp(self):
        super(NetworkRpcAPITestCase, self).setUp()
        self.flags(multi_host=True)

    # Used to specify the default value expected if no real value is passed
    DefaultArg = collections.namedtuple('DefaultArg', ['value'])

    def _test_network_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = network_rpcapi.NetworkAPI()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(network_rpcapi.RPC_TOPIC,
                         rpcapi.client.target.topic)

        expected_retval = 'foo' if rpc_method == 'call' else None
        expected_version = kwargs.pop('version', None)
        expected_fanout = kwargs.pop('fanout', None)
        expected_kwargs = kwargs.copy()

        for k, v in expected_kwargs.items():
            if isinstance(v, self.DefaultArg):
                expected_kwargs[k] = v.value
                kwargs.pop(k)

        prepare_kwargs = {}
        if expected_version:
            prepare_kwargs['version'] = expected_version
        if expected_fanout:
            prepare_kwargs['fanout'] = True

        if 'source_compute' in expected_kwargs:
            # Fix up for migrate_instance_* calls.
            expected_kwargs['source'] = expected_kwargs.pop('source_compute')
            expected_kwargs['dest'] = expected_kwargs.pop('dest_compute')

        targeted_methods = [
            'lease_fixed_ip', 'release_fixed_ip', 'rpc_setup_network_on_host',
            '_rpc_allocate_fixed_ip', 'deallocate_fixed_ip', 'update_dns',
            '_associate_floating_ip', '_disassociate_floating_ip',
            'lease_fixed_ip', 'release_fixed_ip', 'migrate_instance_start',
            'migrate_instance_finish',
            'allocate_for_instance', 'deallocate_for_instance',
        ]
        targeted_by_instance = ['deallocate_for_instance']
        if method in targeted_methods and ('host' in expected_kwargs or
                'instance' in expected_kwargs):
            if method in targeted_by_instance:
                host = expected_kwargs['instance']['host']
            else:
                host = expected_kwargs['host']
                if method not in ['allocate_for_instance',
                                  'deallocate_fixed_ip']:
                    expected_kwargs.pop('host')
            if CONF.multi_host:
                prepare_kwargs['server'] = host

        with test.nested(
            mock.patch.object(rpcapi.client, rpc_method),
            mock.patch.object(rpcapi.client, 'prepare'),
            mock.patch.object(rpcapi.client, 'can_send_version'),
        ) as (
            rpc_mock, prepare_mock, csv_mock
        ):

            version_check = [
                'deallocate_for_instance', 'deallocate_fixed_ip',
                'allocate_for_instance', 'release_fixed_ip',
                'set_network_host', 'setup_networks_on_host'
            ]
            if method in version_check:
                csv_mock.return_value = True

            if prepare_kwargs:
                prepare_mock.return_value = rpcapi.client

            if rpc_method == 'call':
                rpc_mock.return_value = 'foo'
            else:
                rpc_mock.return_value = None

            retval = getattr(rpcapi, method)(ctxt, **kwargs)
            self.assertEqual(expected_retval, retval)

            if method in version_check:
                csv_mock.assert_called_once_with(mock.ANY)
            if prepare_kwargs:
                prepare_mock.assert_called_once_with(**prepare_kwargs)
            rpc_mock.assert_called_once_with(ctxt, method, **expected_kwargs)

    def test_create_networks(self):
        self._test_network_api('create_networks', rpc_method='call',
                arg1='arg', arg2='arg')

    def test_delete_network(self):
        self._test_network_api('delete_network', rpc_method='call',
                uuid='fake_uuid', fixed_range='range')

    def test_allocate_for_instance(self):
        self._test_network_api('allocate_for_instance', rpc_method='call',
                instance_id='fake_id', project_id='fake_id', host='fake_host',
                rxtx_factor='fake_factor', vpn=False, requested_networks={},
                macs=[], version='1.13')

    def test_deallocate_for_instance(self):
        instance = fake_instance.fake_instance_obj(context.get_admin_context())
        self._test_network_api('deallocate_for_instance', rpc_method='call',
                requested_networks=self.DefaultArg(None), instance=instance,
                version='1.11')

    def test_deallocate_for_instance_with_expected_networks(self):
        instance = fake_instance.fake_instance_obj(context.get_admin_context())
        self._test_network_api('deallocate_for_instance', rpc_method='call',
                instance=instance, requested_networks={}, version='1.11')

    def test_release_dhcp(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        dev = 'eth0'
        address = '192.168.65.158'
        vif_address = '00:0c:29:2c:b2:64'
        host = 'fake-host'

        rpcapi = network_rpcapi.NetworkAPI()
        call_mock = mock.Mock()
        cctxt_mock = mock.Mock(call=call_mock)

        with test.nested(
            mock.patch.object(rpcapi.client, 'can_send_version',
                              return_value=True),
            mock.patch.object(rpcapi.client, 'prepare',
                              return_value=cctxt_mock)
        ) as (
            can_send_mock, prepare_mock
        ):
            rpcapi.release_dhcp(ctxt, host, dev, address, vif_address)

        can_send_mock.assert_called_once_with('1.17')
        prepare_mock.assert_called_once_with(server=host, version='1.17')
        call_mock.assert_called_once_with(ctxt, 'release_dhcp', dev=dev,
                                          address=address,
                                          vif_address=vif_address)

    def test_release_dhcp_v116(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        dev = 'eth0'
        address = '192.168.65.158'
        vif_address = '00:0c:29:2c:b2:64'
        host = 'fake-host'
        rpcapi = network_rpcapi.NetworkAPI()

        with mock.patch.object(rpcapi.client, 'can_send_version',
                               return_value=False) as can_send_mock:
            self.assertRaises(exception.RPCPinnedToOldVersion,
                              rpcapi.release_dhcp, ctxt, host, dev, address,
                              vif_address)
            can_send_mock.assert_called_once_with('1.17')

    def test_add_fixed_ip_to_instance(self):
        self._test_network_api('add_fixed_ip_to_instance', rpc_method='call',
                instance_id='fake_id', rxtx_factor='fake_factor',
                host='fake_host', network_id='fake_id', version='1.9')

    def test_remove_fixed_ip_from_instance(self):
        self._test_network_api('remove_fixed_ip_from_instance',
                rpc_method='call', instance_id='fake_id',
                rxtx_factor='fake_factor', host='fake_host',
                address='fake_address', version='1.9')

    def test_add_network_to_project(self):
        self._test_network_api('add_network_to_project', rpc_method='call',
                project_id='fake_id', network_uuid='fake_uuid')

    def test_get_instance_nw_info(self):
        self._test_network_api('get_instance_nw_info', rpc_method='call',
                instance_id='fake_id', rxtx_factor='fake_factor',
                host='fake_host', project_id='fake_id', version='1.9')

    def test_validate_networks(self):
        self._test_network_api('validate_networks', rpc_method='call',
                networks={})

    def test_get_dns_domains(self):
        self._test_network_api('get_dns_domains', rpc_method='call')

    def test_add_dns_entry(self):
        self._test_network_api('add_dns_entry', rpc_method='call',
                address='addr', name='name', dns_type='foo', domain='domain')

    def test_modify_dns_entry(self):
        self._test_network_api('modify_dns_entry', rpc_method='call',
                address='addr', name='name', domain='domain')

    def test_delete_dns_entry(self):
        self._test_network_api('delete_dns_entry', rpc_method='call',
                name='name', domain='domain')

    def test_delete_dns_domain(self):
        self._test_network_api('delete_dns_domain', rpc_method='call',
                domain='fake_domain')

    def test_get_dns_entries_by_address(self):
        self._test_network_api('get_dns_entries_by_address', rpc_method='call',
                address='fake_address', domain='fake_domain')

    def test_get_dns_entries_by_name(self):
        self._test_network_api('get_dns_entries_by_name', rpc_method='call',
                name='fake_name', domain='fake_domain')

    def test_create_private_dns_domain(self):
        self._test_network_api('create_private_dns_domain', rpc_method='call',
                domain='fake_domain', av_zone='fake_zone')

    def test_create_public_dns_domain(self):
        self._test_network_api('create_public_dns_domain', rpc_method='call',
                domain='fake_domain', project='fake_project')

    def test_setup_networks_on_host(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        instance = fake_instance.fake_instance_obj(ctxt)
        self._test_network_api('setup_networks_on_host', rpc_method='call',
                instance_id=instance.id, host='fake_host', teardown=False,
                instance=instance, version='1.16')

    def test_setup_networks_on_host_v1_0(self):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        instance = fake_instance.fake_instance_obj(ctxt)
        host = 'fake_host'
        teardown = True
        rpcapi = network_rpcapi.NetworkAPI()
        call_mock = mock.Mock()
        cctxt_mock = mock.Mock(call=call_mock)
        with test.nested(
            mock.patch.object(rpcapi.client, 'can_send_version',
                              return_value=False),
            mock.patch.object(rpcapi.client, 'prepare',
                              return_value=cctxt_mock)
        ) as (
            can_send_mock, prepare_mock
        ):
            rpcapi.setup_networks_on_host(ctxt, instance.id, host, teardown,
                                          instance)
        # assert our mocks were called as expected
        can_send_mock.assert_called_once_with('1.16')
        prepare_mock.assert_called_once_with(version='1.0')
        call_mock.assert_called_once_with(ctxt, 'setup_networks_on_host',
                                          host=host, teardown=teardown,
                                          instance_id=instance.id)

    def test_lease_fixed_ip(self):
        self._test_network_api('lease_fixed_ip', rpc_method='cast',
                host='fake_host', address='fake_addr')

    def test_release_fixed_ip(self):
        self._test_network_api('release_fixed_ip', rpc_method='cast',
                host='fake_host', address='fake_addr', mac='fake_mac',
                version='1.14')

    def test_release_fixed_ip_no_mac_support(self):
        # Tests that the mac kwarg is not passed when we can't send version
        # 1.14 to the network manager.
        ctxt = context.RequestContext('fake_user', 'fake_project')
        address = '192.168.65.158'
        host = 'fake-host'
        mac = '00:0c:29:2c:b2:64'
        rpcapi = network_rpcapi.NetworkAPI()
        cast_mock = mock.Mock()
        cctxt_mock = mock.Mock(cast=cast_mock)
        with test.nested(
            mock.patch.object(rpcapi.client, 'can_send_version',
                              return_value=False),
            mock.patch.object(rpcapi.client, 'prepare',
                              return_value=cctxt_mock)
        ) as (
            can_send_mock, prepare_mock
        ):
            rpcapi.release_fixed_ip(ctxt, address, host, mac)
        # assert our mocks were called as expected     232
        can_send_mock.assert_called_once_with('1.14')
        prepare_mock.assert_called_once_with(server=host, version='1.0')
        cast_mock.assert_called_once_with(ctxt, 'release_fixed_ip',
                                          address=address)

    def test_set_network_host(self):
        network = fake_network.fake_network_obj(context.get_admin_context())
        self._test_network_api('set_network_host', rpc_method='call',
                               network_ref=network, version='1.15')

    def test_set_network_host_network_object_to_primitive(self):
        # Tests that the network object is converted to a primitive if it
        # can't send version 1.15.
        ctxt = context.RequestContext('fake_user', 'fake_project')
        network = fake_network.fake_network_obj(ctxt)
        network_dict = objects_base.obj_to_primitive(network)
        rpcapi = network_rpcapi.NetworkAPI()
        call_mock = mock.Mock()
        cctxt_mock = mock.Mock(call=call_mock)
        with test.nested(
            mock.patch.object(rpcapi.client, 'can_send_version',
                              return_value=False),
            mock.patch.object(rpcapi.client, 'prepare',
                              return_value=cctxt_mock)
        ) as (
            can_send_mock, prepare_mock
        ):
            rpcapi.set_network_host(ctxt, network)
        # assert our mocks were called as expected
        can_send_mock.assert_called_once_with('1.15')
        prepare_mock.assert_called_once_with(version='1.0')
        call_mock.assert_called_once_with(ctxt, 'set_network_host',
                                          network_ref=network_dict)

    def test_rpc_setup_network_on_host(self):
        self._test_network_api('rpc_setup_network_on_host', rpc_method='call',
                network_id='fake_id', teardown=False, host='fake_host')

    def test_rpc_allocate_fixed_ip(self):
        self._test_network_api('_rpc_allocate_fixed_ip', rpc_method='call',
                instance_id='fake_id', network_id='fake_id', address='addr',
                vpn=True, host='fake_host')

    def test_deallocate_fixed_ip(self):
        instance = fake_instance.fake_db_instance()
        self._test_network_api('deallocate_fixed_ip', rpc_method='call',
                address='fake_addr', host='fake_host', instance=instance,
                version='1.12')

    def test_update_dns(self):
        self._test_network_api('update_dns', rpc_method='cast', fanout=True,
                network_ids='fake_id', version='1.3')

    def test__associate_floating_ip(self):
        self._test_network_api('_associate_floating_ip', rpc_method='call',
                floating_address='fake_addr', fixed_address='fixed_address',
                interface='fake_interface', host='fake_host',
                instance_uuid='fake_uuid', version='1.6')

    def test__disassociate_floating_ip(self):
        self._test_network_api('_disassociate_floating_ip', rpc_method='call',
                address='fake_addr', interface='fake_interface',
                host='fake_host', instance_uuid='fake_uuid', version='1.6')

    def test_migrate_instance_start(self):
        self._test_network_api('migrate_instance_start', rpc_method='call',
                instance_uuid='fake_instance_uuid',
                rxtx_factor='fake_factor',
                project_id='fake_project',
                source_compute='fake_src_compute',
                dest_compute='fake_dest_compute',
                floating_addresses='fake_floating_addresses',
                host=self.DefaultArg(None),
                version='1.2')

    def test_migrate_instance_start_multi_host(self):
        self._test_network_api('migrate_instance_start', rpc_method='call',
                instance_uuid='fake_instance_uuid',
                rxtx_factor='fake_factor',
                project_id='fake_project',
                source_compute='fake_src_compute',
                dest_compute='fake_dest_compute',
                floating_addresses='fake_floating_addresses',
                host='fake_host',
                version='1.2')

    def test_migrate_instance_finish(self):
        self._test_network_api('migrate_instance_finish', rpc_method='call',
                instance_uuid='fake_instance_uuid',
                rxtx_factor='fake_factor',
                project_id='fake_project',
                source_compute='fake_src_compute',
                dest_compute='fake_dest_compute',
                floating_addresses='fake_floating_addresses',
                host=self.DefaultArg(None),
                version='1.2')

    def test_migrate_instance_finish_multi_host(self):
        self._test_network_api('migrate_instance_finish', rpc_method='call',
                instance_uuid='fake_instance_uuid',
                rxtx_factor='fake_factor',
                project_id='fake_project',
                source_compute='fake_src_compute',
                dest_compute='fake_dest_compute',
                floating_addresses='fake_floating_addresses',
                host='fake_host',
                version='1.2')
