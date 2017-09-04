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

import copy
import itertools

import mock
from oslo_utils import uuidutils

from nova.compute import flavors
from nova import context
from nova import exception
from nova import network
from nova.network import api
from nova.network import base_api
from nova.network import floating_ips
from nova.network import model as network_model
from nova import objects
from nova.objects import fields
from nova.objects import network_request as net_req_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_fixed_ip
from nova.tests.unit.objects import test_virtual_interface
from nova.tests import uuidsentinel as uuids

FAKE_UUID = 'a47ae74e-ab08-547f-9eee-ffd23fc46c16'

fake_info_cache = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'instance_uuid': uuids.instance,
    'network_info': '[]',
    }


class ApiTestCase(test.TestCase):
    def setUp(self):
        super(ApiTestCase, self).setUp()
        self.flags(use_neutron=False)
        self.network_api = network.API()
        self.context = context.RequestContext('fake-user',
                                              fakes.FAKE_PROJECT_ID)

    @mock.patch('nova.objects.NetworkList.get_all')
    def test_get_all(self, mock_get_all):
        mock_get_all.return_value = mock.sentinel.get_all
        self.assertEqual(mock.sentinel.get_all,
                         self.network_api.get_all(self.context))
        mock_get_all.assert_called_once_with(self.context,
                                             project_only=True)

    @mock.patch('nova.objects.NetworkList.get_all')
    def test_get_all_liberal(self, mock_get_all):
        self.flags(network_manager='nova.network.manager.FlatDHCPManager')
        mock_get_all.return_value = mock.sentinel.get_all
        self.assertEqual(mock.sentinel.get_all,
                         self.network_api.get_all(self.context))
        mock_get_all.assert_called_once_with(self.context,
                                             project_only="allow_none")

    @mock.patch('nova.objects.NetworkList.get_all')
    def test_get_all_no_networks(self, mock_get_all):
        mock_get_all.side_effect = exception.NoNetworksFound
        self.assertEqual([], self.network_api.get_all(self.context))
        mock_get_all.assert_called_once_with(self.context,
                                             project_only=True)

    @mock.patch('nova.objects.Network.get_by_uuid')
    def test_get(self, mock_get):
        mock_get.return_value = mock.sentinel.get_by_uuid
        self.assertEqual(mock.sentinel.get_by_uuid,
                         self.network_api.get(self.context, uuids.instance))

    @mock.patch('nova.objects.Network.get_by_id')
    @mock.patch('nova.db.virtual_interface_get_by_instance')
    def test_get_vifs_by_instance(self, mock_get_by_instance,
                                  mock_get_by_id):
        mock_get_by_instance.return_value = [
            dict(test_virtual_interface.fake_vif,
                 network_id=123)]
        mock_get_by_id.return_value = objects.Network()
        mock_get_by_id.return_value.uuid = uuids.network_1
        instance = objects.Instance(uuid=uuids.instance)
        vifs = self.network_api.get_vifs_by_instance(self.context,
                                                     instance)
        self.assertEqual(1, len(vifs))
        self.assertEqual(123, vifs[0].network_id)
        self.assertEqual(uuids.network_1, vifs[0].net_uuid)
        mock_get_by_instance.assert_called_once_with(
            self.context, uuids.instance)
        mock_get_by_id.assert_called_once_with(self.context, 123,
                                               project_only='allow_none')

    @mock.patch('nova.objects.Network.get_by_id')
    @mock.patch('nova.db.virtual_interface_get_by_address')
    def test_get_vif_by_mac_address(self, mock_get_by_address,
                                    mock_get_by_id):
        mock_get_by_address.return_value = dict(
            test_virtual_interface.fake_vif, network_id=123)
        mock_get_by_id.return_value = objects.Network(
            uuid=uuids.network_1)
        vif = self.network_api.get_vif_by_mac_address(self.context,
                                                      mock.sentinel.mac)
        self.assertEqual(123, vif.network_id)
        self.assertEqual(uuids.network_1, vif.net_uuid)
        mock_get_by_address.assert_called_once_with(self.context,
                                                    mock.sentinel.mac)
        mock_get_by_id.assert_called_once_with(self.context, 123,
                                               project_only='allow_none')

    def test_allocate_for_instance_handles_macs_passed(self):
        # If a macs argument is supplied to the 'nova-network' API, it is just
        # ignored. This test checks that the call down to the rpcapi layer
        # doesn't pass macs down: nova-network doesn't support hypervisor
        # mac address limits (today anyhow).
        macs = set(['ab:cd:ef:01:23:34'])
        with mock.patch.object(self.network_api.network_rpcapi,
                               "allocate_for_instance") as mock_alloc:
            kwargs = dict(zip(['host', 'instance_id', 'project_id',
                               'requested_networks', 'rxtx_factor', 'vpn',
                                'macs'],
                              itertools.repeat(mock.ANY)))
            mock_alloc.return_value = []
            flavor = flavors.get_default_flavor()
            flavor['rxtx_factor'] = 0
            instance = objects.Instance(id=1, uuid=uuids.instance,
                                        project_id='project_id',
                                        host='host', system_metadata={},
                                        flavor=flavor, deleted=False)
            self.network_api.allocate_for_instance(
                self.context, instance, 'vpn', requested_networks=None,
                macs=macs)
            mock_alloc.assert_called_once_with(self.context, **kwargs)

    def _do_test_associate_floating_ip(self, orig_instance_uuid):
        """Test post-association logic."""

        new_instance = objects.Instance(uuid=FAKE_UUID)

        def fake_associate(*args, **kwargs):
            return orig_instance_uuid

        def fake_instance_get_by_uuid(context, instance_uuid,
                                      columns_to_join=None,
                                      use_slave=None):
            if instance_uuid == orig_instance_uuid:
                self.assertIn('extra.flavor', columns_to_join)
            return fake_instance.fake_db_instance(uuid=instance_uuid)

        def fake_get_nw_info(ctxt, instance):
            class FakeNWInfo(object):
                def json(self):
                    pass
            return FakeNWInfo()

        if orig_instance_uuid:
            expected_updated_instances = [new_instance.uuid,
                                          orig_instance_uuid]
        else:
            expected_updated_instances = [new_instance.uuid]

        def fake_instance_info_cache_update(context, instance_uuid, cache):
            self.assertEqual(instance_uuid,
                             expected_updated_instances.pop())
            return fake_info_cache

        def fake_update_instance_cache_with_nw_info(api, context, instance,
                                                    nw_info=None,
                                                    update_cells=True):
            return

        with test.nested(
            mock.patch.object(floating_ips.FloatingIP, 'associate_floating_ip',
                              fake_associate),
            mock.patch.object(self.network_api.db, 'instance_get_by_uuid',
                              fake_instance_get_by_uuid),
            mock.patch.object(self.network_api, '_get_instance_nw_info',
                              fake_get_nw_info),
            mock.patch.object(self.network_api.db,
                              'instance_info_cache_update',
                              fake_instance_info_cache_update),
            mock.patch.object(base_api, "update_instance_cache_with_nw_info",
                              fake_update_instance_cache_with_nw_info)
        ):
            self.network_api.associate_floating_ip(self.context,
                                                   new_instance,
                                                   '172.24.4.225',
                                                   '10.0.0.2')

    def test_associate_preassociated_floating_ip(self):
        self._do_test_associate_floating_ip(uuids.orig_uuid)

    def test_associate_unassociated_floating_ip(self):
        self._do_test_associate_floating_ip(None)

    def test_get_floating_ip_invalid_id(self):
        self.assertRaises(exception.InvalidID,
                          self.network_api.get_floating_ip,
                          self.context, '123zzz')

    @mock.patch('nova.objects.FloatingIP.get_by_id')
    def test_get_floating_ip(self, mock_get):
        floating = mock.sentinel.floating
        mock_get.return_value = floating
        self.assertEqual(floating,
                         self.network_api.get_floating_ip(self.context, 123))
        mock_get.assert_called_once_with(self.context, 123)

    @mock.patch('nova.objects.FloatingIP.get_pool_names')
    def test_get_floating_ip_pools(self, mock_get):
        pools = ['foo', 'bar']
        mock_get.return_value = pools
        self.assertEqual(pools,
                         self.network_api.get_floating_ip_pools(
                             self.context))

    @mock.patch('nova.objects.FloatingIP.get_by_address')
    def test_get_floating_ip_by_address(self, mock_get):
        floating = mock.sentinel.floating
        mock_get.return_value = floating
        self.assertEqual(floating,
                         self.network_api.get_floating_ip_by_address(
                             self.context, mock.sentinel.address))
        mock_get.assert_called_once_with(self.context,
                                         mock.sentinel.address)

    @mock.patch('nova.objects.FloatingIPList.get_by_project')
    def test_get_floating_ips_by_project(self, mock_get):
        floatings = mock.sentinel.floating_ips
        mock_get.return_value = floatings
        self.assertEqual(floatings,
                         self.network_api.get_floating_ips_by_project(
                             self.context))
        mock_get.assert_called_once_with(self.context,
                                         self.context.project_id)

    def _stub_migrate_instance_calls(self, method, multi_host, info):
        fake_flavor = flavors.get_default_flavor()
        fake_flavor['rxtx_factor'] = 1.21
        fake_instance = objects.Instance(
            uuid=uuidutils.generate_uuid(dashed=False),
            project_id='fake_project_id',
            instance_type_id=fake_flavor['id'],
            flavor=fake_flavor,
            system_metadata={})
        fake_migration = {'source_compute': 'fake_compute_source',
                          'dest_compute': 'fake_compute_dest'}

        def fake_mig_inst_method(*args, **kwargs):
            info['kwargs'] = kwargs

        def fake_get_multi_addresses(*args, **kwargs):
            return multi_host, ['fake_float1', 'fake_float2']

        self.stub_out('nova.network.rpcapi.NetworkAPI.' + method,
                fake_mig_inst_method)
        self.stub_out('nova.network.api.API._get_multi_addresses',
                fake_get_multi_addresses)

        expected = {'instance_uuid': fake_instance.uuid,
                    'source_compute': 'fake_compute_source',
                    'dest_compute': 'fake_compute_dest',
                    'rxtx_factor': 1.21,
                    'project_id': 'fake_project_id',
                    'floating_addresses': None}
        if multi_host:
            expected['floating_addresses'] = ['fake_float1', 'fake_float2']
        return fake_instance, fake_migration, expected

    def test_migrate_instance_start_with_multihost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_start', True, info)
        expected['host'] = 'fake_compute_source'
        self.network_api.migrate_instance_start(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_migrate_instance_start_without_multihost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_start', False, info)
        self.network_api.migrate_instance_start(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_migrate_instance_finish_with_multihost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_finish', True, info)
        expected['host'] = 'fake_compute_dest'
        self.network_api.migrate_instance_finish(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_migrate_instance_finish_without_multihost(self):
        info = {'kwargs': {}}
        arg1, arg2, expected = self._stub_migrate_instance_calls(
                'migrate_instance_finish', False, info)
        self.network_api.migrate_instance_finish(self.context, arg1, arg2)
        self.assertEqual(info['kwargs'], expected)

    def test_is_multi_host_instance_has_no_fixed_ip(self):
        with mock.patch.object(self.network_api.db, 'fixed_ip_get_by_instance',
            side_effect=exception.FixedIpNotFoundForInstance(
                instance_uuid=FAKE_UUID)):
            instance = objects.Instance(uuid=FAKE_UUID)
            result, floats = (
                self.network_api._get_multi_addresses(self.context, instance))
            self.assertFalse(result)

    @mock.patch('nova.objects.fixed_ip.FixedIPList.get_by_instance_uuid')
    def _test_is_multi_host_network_has_no_project_id(self, is_multi_host,
                                                      fip_get):
        network = objects.Network(
            id=123, project_id=None,
            multi_host=is_multi_host)
        fip_get.return_value = [
            objects.FixedIP(instance_uuid=FAKE_UUID, network=network,
                            floating_ips=objects.FloatingIPList())]
        instance = objects.Instance(uuid=FAKE_UUID)
        result, floats = self.network_api._get_multi_addresses(self.context,
                                                               instance)
        self.assertEqual(is_multi_host, result)

    def test_is_multi_host_network_has_no_project_id_multi(self):
        self._test_is_multi_host_network_has_no_project_id(True)

    def test_is_multi_host_network_has_no_project_id_non_multi(self):
        self._test_is_multi_host_network_has_no_project_id(False)

    @mock.patch('nova.objects.fixed_ip.FixedIPList.get_by_instance_uuid')
    def _test_is_multi_host_network_has_project_id(self, is_multi_host,
                                                   fip_get):
        network = objects.Network(
            id=123, project_id=self.context.project_id,
            multi_host=is_multi_host)
        fip_get.return_value = [
            objects.FixedIP(instance_uuid=FAKE_UUID, network=network,
                            floating_ips=objects.FloatingIPList())]
        instance = objects.Instance(uuid=FAKE_UUID)
        result, floats = self.network_api._get_multi_addresses(self.context,
                                                               instance)
        self.assertEqual(is_multi_host, result)

    def test_is_multi_host_network_has_project_id_multi(self):
        self._test_is_multi_host_network_has_project_id(True)

    def test_is_multi_host_network_has_project_id_non_multi(self):
        self._test_is_multi_host_network_has_project_id(False)

    @mock.patch('nova.objects.Network.get_by_uuid')
    @mock.patch('nova.objects.Network.disassociate')
    def test_network_disassociate_project(self, mock_disassociate, mock_get):
        net_obj = objects.Network(context=self.context, id=1)
        mock_get.return_value = net_obj
        self.network_api.associate(self.context, FAKE_UUID, project=None)
        mock_disassociate.assert_called_once_with(self.context, net_obj.id,
                                                  host=False, project=True)

    @mock.patch('nova.objects.Network.get_by_uuid')
    @mock.patch('nova.objects.Network.disassociate')
    def test_network_disassociate_host(self, mock_disassociate, mock_get):
        net_obj = objects.Network(context=self.context, id=1)
        mock_get.return_value = net_obj
        self.network_api.associate(self.context, FAKE_UUID, host=None)
        mock_disassociate.assert_called_once_with(self.context, net_obj.id,
                                                  host=True, project=False)

    @mock.patch('nova.objects.Network.get_by_uuid')
    @mock.patch('nova.objects.Network.associate')
    def test_network_associate_project(self, mock_associate, mock_get):
        net_obj = objects.Network(context=self.context, id=1)
        mock_get.return_value = net_obj
        project = mock.sentinel.project
        self.network_api.associate(self.context, FAKE_UUID, project=project)
        mock_associate.assert_called_once_with(self.context, project,
                                               network_id=net_obj.id,
                                               force=True)

    @mock.patch('nova.objects.Network.get_by_uuid')
    @mock.patch('nova.objects.Network.save')
    def test_network_associate_host(self, mock_save, mock_get):
        net_obj = objects.Network(context=self.context, id=1)
        mock_get.return_value = net_obj
        host = str(mock.sentinel.host)
        self.network_api.associate(self.context, FAKE_UUID, host=host)
        mock_save.assert_called_once_with()
        self.assertEqual(host, net_obj.host)

    @mock.patch('nova.objects.Network.get_by_uuid')
    @mock.patch('nova.objects.Network.disassociate')
    def test_network_disassociate(self, mock_disassociate, mock_get):
        mock_get.return_value = objects.Network(context=self.context, id=123)
        self.network_api.disassociate(self.context, FAKE_UUID)
        mock_disassociate.assert_called_once_with(self.context, 123,
                                                  project=True, host=True)

    def _test_refresh_cache(self, method, *args, **kwargs):
        # This test verifies that no call to get_instance_nw_info() is made
        # from the @refresh_cache decorator for the tested method.
        with test.nested(
            mock.patch.object(self.network_api.network_rpcapi, method),
            mock.patch.object(self.network_api.network_rpcapi,
                              'get_instance_nw_info'),
            mock.patch.object(network_model.NetworkInfo, 'hydrate'),
            mock.patch.object(objects.InstanceInfoCache, 'save'),
        ) as (
            method_mock, nwinfo_mock, hydrate_mock, save_mock
        ):
            nw_info = network_model.NetworkInfo([])
            method_mock.return_value = nw_info
            hydrate_mock.return_value = nw_info
            getattr(self.network_api, method)(*args, **kwargs)
            hydrate_mock.assert_called_once_with(nw_info)
            self.assertFalse(nwinfo_mock.called)

    def test_allocate_for_instance_refresh_cache(self):
        instance = fake_instance.fake_instance_obj(self.context)
        vpn = 'fake-vpn'
        requested_networks = [('fake-networks', None)]
        self._test_refresh_cache('allocate_for_instance', self.context,
                                 instance, vpn, requested_networks)

    @mock.patch('nova.network.rpcapi.NetworkAPI.allocate_for_instance')
    def test_allocate_for_instance_no_nets_no_auto(self, mock_rpc_alloc):
        # Tests that nothing fails if no networks are returned and auto
        # allocation wasn't requested.
        mock_rpc_alloc.return_value = []
        instance = fake_instance.fake_instance_obj(self.context)
        nw_info = self.network_api.allocate_for_instance(
            self.context, instance, mock.sentinel.vpn, requested_networks=None)
        self.assertEqual(0, len(nw_info))

    @mock.patch('nova.network.rpcapi.NetworkAPI.allocate_for_instance')
    def test_allocate_for_instance_no_nets_auto_allocate(self, mock_rpc_alloc):
        # Tests that we fail when no networks are allocated and auto-allocation
        # was requested.

        def fake_rpc_allocate(context, *args, **kwargs):
            # assert that requested_networks is nulled out
            self.assertIn('requested_networks', kwargs)
            self.assertIsNone(kwargs['requested_networks'])
            return []

        mock_rpc_alloc.side_effect = fake_rpc_allocate
        instance = fake_instance.fake_instance_obj(self.context)
        self.assertRaises(exception.UnableToAutoAllocateNetwork,
                          self.network_api.allocate_for_instance,
                          self.context, instance, mock.sentinel.vpn,
                          [(net_req_obj.NETWORK_ID_AUTO, None)])
        self.assertEqual(1, mock_rpc_alloc.call_count)

    @mock.patch('nova.network.rpcapi.NetworkAPI.deallocate_for_instance')
    def test_deallocate_for_instance_auto_allocate(self, mock_rpc_dealloc):
        # Tests that we pass requested_networks=None to the RPC API when
        # we're auto-allocating.
        instance = fake_instance.fake_instance_obj(self.context)
        req_net = objects.NetworkRequest(
            network_id=net_req_obj.NETWORK_ID_AUTO)
        requested_networks = objects.NetworkRequestList(objects=[req_net])
        self.network_api.deallocate_for_instance(
            self.context, instance, requested_networks)
        mock_rpc_dealloc.assert_called_once_with(self.context,
                                                 instance=instance,
                                                 requested_networks=None)

    def test_add_fixed_ip_to_instance_refresh_cache(self):
        instance = fake_instance.fake_instance_obj(self.context)
        network_id = 'fake-network-id'
        self._test_refresh_cache('add_fixed_ip_to_instance', self.context,
                                 instance, network_id)

    def test_remove_fixed_ip_from_instance_refresh_cache(self):
        instance = fake_instance.fake_instance_obj(self.context)
        address = 'fake-address'
        self._test_refresh_cache('remove_fixed_ip_from_instance', self.context,
                                 instance, address)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    def test_get_fixed_ip_by_address(self, fip_get):
        fip_get.return_value = test_fixed_ip.fake_fixed_ip
        fip = self.network_api.get_fixed_ip_by_address(self.context,
                                                       'fake-addr')
        self.assertIsInstance(fip, objects.FixedIP)

    @mock.patch('nova.objects.FixedIP.get_by_id')
    def test_get_fixed_ip(self, mock_get_by_id):
        mock_get_by_id.return_value = mock.sentinel.fixed_ip
        self.assertEqual(mock.sentinel.fixed_ip,
                         self.network_api.get_fixed_ip(self.context,
                                                       mock.sentinel.id))
        mock_get_by_id.assert_called_once_with(self.context, mock.sentinel.id)

    @mock.patch('nova.objects.FixedIP.get_by_floating_address')
    def test_get_instance_by_floating_address(self, mock_get_by_floating):
        mock_get_by_floating.return_value = objects.FixedIP(
            instance_uuid = uuids.instance)
        self.assertEqual(uuids.instance,
                         self.network_api.get_instance_id_by_floating_address(
                             self.context, mock.sentinel.floating))
        mock_get_by_floating.assert_called_once_with(self.context,
                                                     mock.sentinel.floating)

    @mock.patch('nova.objects.FixedIP.get_by_floating_address')
    def test_get_instance_by_floating_address_none(self, mock_get_by_floating):
        mock_get_by_floating.return_value = None
        self.assertIsNone(
            self.network_api.get_instance_id_by_floating_address(
                self.context, mock.sentinel.floating))
        mock_get_by_floating.assert_called_once_with(self.context,
                                                     mock.sentinel.floating)

    @mock.patch('nova.network.api.API.migrate_instance_start')
    def test_cleanup_instance_network_on_host(self, fake_migrate_start):
        instance = fake_instance.fake_instance_obj(self.context)
        self.network_api.cleanup_instance_network_on_host(
            self.context, instance, 'fake_compute_source')
        fake_migrate_start.assert_called_once_with(
            self.context, instance,
            {'source_compute': 'fake_compute_source', 'dest_compute': None})

    @mock.patch('nova.network.api.API.migrate_instance_finish')
    def test_setup_instance_network_on_host(self, fake_migrate_finish):
        instance = fake_instance.fake_instance_obj(self.context)
        self.network_api.setup_instance_network_on_host(
            self.context, instance, 'fake_compute_source')
        fake_migrate_finish.assert_called_once_with(
            self.context, instance,
            {'source_compute': None, 'dest_compute': 'fake_compute_source'})

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(api.API, '_get_instance_nw_info')
    @mock.patch('nova.network.base_api.update_instance_cache_with_nw_info')
    def test_get_instance_nw_info(self, mock_update, mock_get, mock_lock):
        fake_result = mock.sentinel.get_nw_info_result
        mock_get.return_value = fake_result
        instance = fake_instance.fake_instance_obj(self.context)
        result = self.network_api.get_instance_nw_info(self.context, instance)
        mock_get.assert_called_once_with(self.context, instance)
        mock_update.assert_called_once_with(self.network_api, self.context,
                                            instance, nw_info=fake_result,
                                            update_cells=False)
        self.assertEqual(fake_result, result)


@mock.patch('nova.network.api.API')
@mock.patch('nova.db.instance_info_cache_update')
class TestUpdateInstanceCache(test.NoDBTestCase):
    def setUp(self):
        super(TestUpdateInstanceCache, self).setUp()
        self.context = context.get_admin_context()
        self.instance = objects.Instance(uuid=FAKE_UUID, deleted=False)
        vifs = [network_model.VIF(id='super_vif')]
        self.nw_info = network_model.NetworkInfo(vifs)
        self.nw_json = fields.NetworkModel.to_primitive(self, 'network_info',
                                                        self.nw_info)

    def test_update_nw_info_none(self, db_mock, api_mock):
        api_mock._get_instance_nw_info.return_value = self.nw_info
        info_cache = copy.deepcopy(fake_info_cache)
        info_cache.update({'network_info': self.nw_json})
        db_mock.return_value = info_cache
        base_api.update_instance_cache_with_nw_info(api_mock, self.context,
                                               self.instance, None)
        api_mock._get_instance_nw_info.assert_called_once_with(self.context,
                                                                self.instance)
        db_mock.assert_called_once_with(self.context, self.instance.uuid,
                                        {'network_info': self.nw_json})
        self.assertEqual(self.nw_info, self.instance.info_cache.network_info)

    def test_update_nw_info_none_instance_deleted(self, db_mock, api_mock):
        instance = objects.Instance(uuid=FAKE_UUID, deleted=True)
        base_api.update_instance_cache_with_nw_info(
            api_mock, self.context, instance)
        self.assertFalse(api_mock.called)

    def test_update_nw_info_one_network(self, db_mock, api_mock):
        info_cache = copy.deepcopy(fake_info_cache)
        info_cache.update({'network_info': self.nw_json})
        db_mock.return_value = info_cache
        base_api.update_instance_cache_with_nw_info(api_mock, self.context,
                                               self.instance, self.nw_info)
        self.assertFalse(api_mock._get_instance_nw_info.called)
        db_mock.assert_called_once_with(self.context, self.instance.uuid,
                                        {'network_info': self.nw_json})
        self.assertEqual(self.nw_info, self.instance.info_cache.network_info)

    def test_update_nw_info_empty_list(self, db_mock, api_mock):
        new_nw_info = network_model.NetworkInfo([])
        db_mock.return_value = fake_info_cache
        base_api.update_instance_cache_with_nw_info(api_mock, self.context,
                                                self.instance, new_nw_info)
        self.assertFalse(api_mock._get_instance_nw_info.called)
        db_mock.assert_called_once_with(self.context, self.instance.uuid,
                                        {'network_info': '[]'})
        self.assertEqual(new_nw_info, self.instance.info_cache.network_info)

    def test_decorator_return_object(self, db_mock, api_mock):
        db_mock.return_value = fake_info_cache

        @base_api.refresh_cache
        def func(self, context, instance):
            return network_model.NetworkInfo([])
        func(api_mock, self.context, self.instance)
        self.assertFalse(api_mock._get_instance_nw_info.called)
        db_mock.assert_called_once_with(self.context, self.instance.uuid,
                                        {'network_info': '[]'})

    def test_decorator_return_none(self, db_mock, api_mock):
        db_mock.return_value = fake_info_cache

        @base_api.refresh_cache
        def func(self, context, instance):
            pass
        api_mock._get_instance_nw_info.return_value = self.nw_info
        func(api_mock, self.context, self.instance)
        api_mock._get_instance_nw_info.assert_called_once_with(self.context,
                                                                self.instance)
        db_mock.assert_called_once_with(self.context, self.instance.uuid,
                                        {'network_info': self.nw_json})


class NetworkHooksTestCase(test.BaseHookTestCase):
    def test_instance_network_info_hook(self):
        info_func = base_api.update_instance_cache_with_nw_info
        self.assert_has_hook('instance_network_info', info_func)
