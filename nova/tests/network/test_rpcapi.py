# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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

from oslo.config import cfg

from nova import context
from nova.network import rpcapi as network_rpcapi
from nova.openstack.common import rpc
from nova import test
from nova.tests import matchers

CONF = cfg.CONF


class NetworkRpcAPITestCase(test.NoDBTestCase):
    def setUp(self):
        super(NetworkRpcAPITestCase, self).setUp()
        self.flags(multi_host=True)

    def _test_network_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = network_rpcapi.NetworkAPI()
        expected_retval = 'foo' if method == 'call' else None
        expected_version = kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        expected_topic = CONF.network_topic
        expected_msg = rpcapi.make_msg(method, **kwargs)
        if 'source_compute' in expected_msg['args']:
            # Fix up for migrate_instance_* calls.
            args = expected_msg['args']
            args['source'] = args.pop('source_compute')
            args['dest'] = args.pop('dest_compute')
        targeted_methods = [
            'lease_fixed_ip', 'release_fixed_ip', 'rpc_setup_network_on_host',
            '_rpc_allocate_fixed_ip', 'deallocate_fixed_ip', 'update_dns',
            '_associate_floating_ip', '_disassociate_floating_ip',
            'lease_fixed_ip', 'release_fixed_ip', 'migrate_instance_start',
            'migrate_instance_finish',
            'allocate_for_instance', 'deallocate_for_instance',
        ]
        if method in targeted_methods and 'host' in kwargs:
            if method not in ['allocate_for_instance',
                              'deallocate_for_instance',
                              'deallocate_fixed_ip']:
                del expected_msg['args']['host']
            host = kwargs['host']
            if CONF.multi_host:
                expected_topic = rpc.queue_get_for(ctxt, CONF.network_topic,
                                                   host)
        expected_msg['version'] = expected_version

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        self.stubs.Set(rpc, rpc_method, _fake_rpc_method)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        self.assertIsNotNone(self.fake_args)
        self.assertIsNotNone(self.fake_kwargs)
        expected_args = [ctxt, expected_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            try:
                self.assertEqual(arg, expected_arg)
            except AssertionError:
                # actual_args may contain optional args, like the one that
                # have default values; therefore if arg and excepted_arg
                # do not match verify at least that the required ones do
                if isinstance(arg, dict) and isinstance(expected_arg, dict):
                    actual_args = arg.get('args')
                    required_args = expected_arg.get('args')
                    if actual_args and required_args:
                        self.assertThat(required_args,
                                        matchers.IsSubDictOf(actual_args))
                else:
                    raise

    def test_get_all_networks(self):
        self._test_network_api('get_all_networks', rpc_method='call')

    def test_get_network(self):
        self._test_network_api('get_network', rpc_method='call',
                network_uuid='fake_uuid')

    def test_create_networks(self):
        self._test_network_api('create_networks', rpc_method='call',
                arg1='arg', arg2='arg')

    def test_delete_network(self):
        self._test_network_api('delete_network', rpc_method='call',
                uuid='fake_uuid', fixed_range='range')

    def test_disassociate_network(self):
        self._test_network_api('disassociate_network', rpc_method='call',
                network_uuid='fake_uuid')

    def test_associate_host_and_project(self):
        self._test_network_api('associate', rpc_method='call',
                network_uuid='fake_uuid',
                associations={'host': "testHost",
                              'project': 'testProject'},
                version="1.5")

    def test_get_fixed_ip(self):
        self._test_network_api('get_fixed_ip', rpc_method='call', id='id')

    def test_get_fixed_ip_by_address(self):
        self._test_network_api('get_fixed_ip_by_address', rpc_method='call',
                address='a.b.c.d')

    def test_get_floating_ip(self):
        self._test_network_api('get_floating_ip', rpc_method='call', id='id')

    def test_get_floating_ip_pools(self):
        self._test_network_api('get_floating_ip_pools', rpc_method='call',
                               version="1.7")

    def test_get_floating_ip_by_address(self):
        self._test_network_api('get_floating_ip_by_address', rpc_method='call',
                address='a.b.c.d')

    def test_get_floating_ips_by_project(self):
        self._test_network_api('get_floating_ips_by_project',
                rpc_method='call')

    def test_get_floating_ips_by_fixed_address(self):
        self._test_network_api('get_floating_ips_by_fixed_address',
                rpc_method='call', fixed_address='w.x.y.z')

    def test_get_instance_id_by_floating_address(self):
        self._test_network_api('get_instance_id_by_floating_address',
                rpc_method='call', address='w.x.y.z')

    def test_get_vifs_by_instance(self):
        self._test_network_api('get_vifs_by_instance',
                rpc_method='call', instance_id='fake_id')

    def test_get_vif_by_mac_address(self):
        self._test_network_api('get_vif_by_mac_address',
                rpc_method='call', mac_address='fake_mac_addr')

    def test_allocate_floating_ip(self):
        self._test_network_api('allocate_floating_ip', rpc_method='call',
                project_id='fake_id', pool='fake_pool', auto_assigned=False)

    def test_deallocate_floating_ip(self):
        self._test_network_api('deallocate_floating_ip', rpc_method='call',
                address='addr', affect_auto_assigned=True)

    def test_allocate_floating_ip_no_multi(self):
        self.flags(multi_host=False)
        self._test_network_api('allocate_floating_ip', rpc_method='call',
                project_id='fake_id', pool='fake_pool', auto_assigned=False)

    def test_deallocate_floating_ip_no_multi(self):
        self.flags(multi_host=False)
        self._test_network_api('deallocate_floating_ip', rpc_method='call',
                address='addr', affect_auto_assigned=True)

    def test_associate_floating_ip(self):
        self._test_network_api('associate_floating_ip', rpc_method='call',
                floating_address='blah', fixed_address='foo',
                affect_auto_assigned=True)

    def test_disassociate_floating_ip(self):
        self._test_network_api('disassociate_floating_ip', rpc_method='call',
                address='addr', affect_auto_assigned=True)

    def test_allocate_for_instance(self):
        self._test_network_api('allocate_for_instance', rpc_method='call',
                instance_id='fake_id', project_id='fake_id', host='fake_host',
                rxtx_factor='fake_factor', vpn=False, requested_networks={},
                macs=[], version='1.9')

    def test_deallocate_for_instance(self):
        self._test_network_api('deallocate_for_instance', rpc_method='call',
                instance_id='fake_id', project_id='fake_id', host='fake_host')

    def test_deallocate_for_instance_with_expected_networks(self):
        self._test_network_api('deallocate_for_instance', rpc_method='call',
                instance_id='fake_id', project_id='fake_id',
                host='fake_host', requested_networks={})

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

    def test_get_instance_uuids_by_ip_filter(self):
        self._test_network_api('get_instance_uuids_by_ip_filter',
                rpc_method='call', filters={})

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
        self._test_network_api('setup_networks_on_host', rpc_method='call',
                instance_id='fake_id', host='fake_host', teardown=False)

    def test_lease_fixed_ip(self):
        self._test_network_api('lease_fixed_ip', rpc_method='cast',
                host='fake_host', address='fake_addr')

    def test_release_fixed_ip(self):
        self._test_network_api('release_fixed_ip', rpc_method='cast',
                host='fake_host', address='fake_addr')

    def test_set_network_host(self):
        self._test_network_api('set_network_host', rpc_method='call',
                network_ref={})

    def test_rpc_setup_network_on_host(self):
        self._test_network_api('rpc_setup_network_on_host', rpc_method='call',
                network_id='fake_id', teardown=False, host='fake_host')

    def test_rpc_allocate_fixed_ip(self):
        self._test_network_api('_rpc_allocate_fixed_ip', rpc_method='call',
                instance_id='fake_id', network_id='fake_id', address='addr',
                vpn=True, host='fake_host')

    def test_deallocate_fixed_ip(self):
        self._test_network_api('deallocate_fixed_ip', rpc_method='call',
                address='fake_addr', host='fake_host')

    def test_update_dns(self):
        self._test_network_api('update_dns', rpc_method='fanout_cast',
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
