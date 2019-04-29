# Copyright 2013 Canonical Corp.
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
from oslo_vmware import exceptions as vexc
from oslo_vmware import vim_util

from nova import exception
from nova.network import model as network_model
from nova import test
from nova.tests.unit import matchers
from nova.tests.unit import utils
from nova.tests.unit.virt.vmwareapi import fake
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import network_util
from nova.virt.vmwareapi import vif
from nova.virt.vmwareapi import vm_util


class VMwareVifTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMwareVifTestCase, self).setUp()
        self.flags(vlan_interface='vmnet0', group='vmware')
        network = network_model.Network(id=0,
                                        bridge='fa0',
                                        label='fake',
                                        vlan=3,
                                        bridge_interface='eth0',
                                        injected=True)
        self._network = network
        self.vif = network_model.NetworkInfo([
                network_model.VIF(id=None,
                                  address='DE:AD:BE:EF:00:00',
                                  network=network,
                                  type=None,
                                  devname=None,
                                  ovs_interfaceid=None,
                                  rxtx_cap=3)
        ])[0]
        self.session = fake.FakeSession()
        self.cluster = None

    @mock.patch.object(network_util, 'get_network_with_the_name',
                       return_value=None)
    @mock.patch.object(network_util, 'get_vswitch_for_vlan_interface',
                       return_value='vmnet0')
    @mock.patch.object(network_util, 'check_if_vlan_interface_exists',
                       return_value=True)
    @mock.patch.object(network_util, 'create_port_group')
    def test_ensure_vlan_bridge(self,
                                mock_create_port_group,
                                mock_check_if_vlan_exists,
                                mock_get_vswitch_for_vlan,
                                mock_get_network_with_name):

        vif.ensure_vlan_bridge(self.session, self.vif, create_vlan=True)

        expected_calls = [mock.call(self.session, 'fa0', self.cluster),
                          mock.call(self.session, 'fa0', None)]
        mock_get_network_with_name.assert_has_calls(expected_calls)
        self.assertEqual(2, mock_get_network_with_name.call_count)
        mock_get_vswitch_for_vlan.assert_called_once_with(
            self.session, 'vmnet0', self.cluster)
        mock_check_if_vlan_exists.assert_called_once_with(
            self.session, 'vmnet0', self.cluster)
        mock_create_port_group.assert_called_once_with(
            self.session, 'fa0', 'vmnet0', 3, self.cluster)

    # FlatDHCP network mode without vlan - network doesn't exist with the host
    @mock.patch.object(network_util, 'get_network_with_the_name',
                       return_value=None)
    @mock.patch.object(network_util, 'get_vswitch_for_vlan_interface',
                       return_value='vmnet0')
    @mock.patch.object(network_util, 'check_if_vlan_interface_exists',
                       return_value=True)
    @mock.patch.object(network_util, 'create_port_group')
    def test_ensure_vlan_bridge_without_vlan(self,
                                             mock_create_port_group,
                                             mock_check_if_vlan_exists,
                                             mock_get_vswitch_for_vlan,
                                             mock_get_network_with_name):
        vif.ensure_vlan_bridge(self.session, self.vif, create_vlan=False)

        expected_calls = [mock.call(self.session, 'fa0', self.cluster),
                          mock.call(self.session, 'fa0', None)]
        mock_get_network_with_name.assert_has_calls(expected_calls)
        self.assertEqual(2, mock_get_network_with_name.call_count)
        mock_get_vswitch_for_vlan.assert_called_once_with(
            self.session, 'vmnet0', self.cluster)
        mock_check_if_vlan_exists.assert_called_once_with(
            self.session, 'vmnet0', self.cluster)
        mock_create_port_group.assert_called_once_with(
            self.session, 'fa0', 'vmnet0', 0, self.cluster)

    # FlatDHCP network mode without vlan - network exists with the host
    # Get vswitch and check vlan interface should not be called
    @mock.patch.object(network_util, 'get_network_with_the_name')
    @mock.patch.object(network_util, 'get_vswitch_for_vlan_interface')
    @mock.patch.object(network_util, 'check_if_vlan_interface_exists')
    @mock.patch.object(network_util, 'create_port_group')
    def test_ensure_vlan_bridge_with_network(self,
                                             mock_create_port_group,
                                             mock_check_if_vlan_exists,
                                             mock_get_vswitch_for_vlan,
                                             mock_get_network_with_name
                                             ):
        vm_network = {'name': 'VM Network', 'type': 'Network'}
        mock_get_network_with_name.return_value = vm_network
        vif.ensure_vlan_bridge(self.session, self.vif, create_vlan=False)
        mock_get_network_with_name.assert_called_once_with(self.session,
                                                           'fa0',
                                                           self.cluster)
        mock_check_if_vlan_exists.assert_not_called()
        mock_get_vswitch_for_vlan.assert_not_called()
        mock_create_port_group.assert_not_called()

    # Flat network mode with DVS
    @mock.patch.object(network_util, 'get_network_with_the_name')
    @mock.patch.object(network_util, 'get_vswitch_for_vlan_interface')
    @mock.patch.object(network_util, 'check_if_vlan_interface_exists')
    @mock.patch.object(network_util, 'create_port_group')
    def test_ensure_vlan_bridge_with_existing_dvs(self,
                                             mock_create_port_group,
                                             mock_check_if_vlan_exists,
                                             mock_get_vswitch_for_vlan,
                                             mock_get_network_with_name
                                             ):
        network_ref = {'dvpg': 'dvportgroup-2062',
                       'type': 'DistributedVirtualPortgroup'}
        mock_get_network_with_name.return_value = network_ref
        ref = vif.ensure_vlan_bridge(self.session,
                                     self.vif,
                                     create_vlan=False)

        self.assertThat(ref, matchers.DictMatches(network_ref))
        mock_get_network_with_name.assert_called_once_with(self.session,
                                                           'fa0',
                                                           self.cluster)
        mock_check_if_vlan_exists.assert_not_called()
        mock_get_vswitch_for_vlan.assert_not_called()
        mock_create_port_group.assert_not_called()

    @mock.patch.object(vif, 'ensure_vlan_bridge')
    def test_get_network_ref_flat_dhcp(self, mock_ensure_vlan_bridge):
        vif.get_network_ref(self.session, self.cluster, self.vif, False)
        mock_ensure_vlan_bridge.assert_called_once_with(
            self.session, self.vif, cluster=self.cluster, create_vlan=False)

    @mock.patch.object(vif, 'ensure_vlan_bridge')
    def test_get_network_ref_bridge(self, mock_ensure_vlan_bridge):
        network = network_model.Network(id=0,
                                        bridge='fa0',
                                        label='fake',
                                        vlan=3,
                                        bridge_interface='eth0',
                                        injected=True,
                                        should_create_vlan=True)
        self.vif = network_model.NetworkInfo([
                network_model.VIF(id=None,
                                  address='DE:AD:BE:EF:00:00',
                                  network=network,
                                  type=None,
                                  devname=None,
                                  ovs_interfaceid=None,
                                  rxtx_cap=3)
        ])[0]
        vif.get_network_ref(self.session, self.cluster, self.vif, False)
        mock_ensure_vlan_bridge.assert_called_once_with(
            self.session, self.vif, cluster=self.cluster, create_vlan=True)

    def test_create_port_group_already_exists(self):
        def fake_call_method(module, method, *args, **kwargs):
            if method == 'AddPortGroup':
                raise vexc.AlreadyExistsException()

        with test.nested(
            mock.patch.object(vm_util, 'get_add_vswitch_port_group_spec'),
            mock.patch.object(vm_util, 'get_host_ref'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_add_vswitch, _get_host, _call_method):
            network_util.create_port_group(self.session, 'pg_name',
                                           'vswitch_name', vlan_id=0,
                                           cluster=None)

    def test_create_port_group_exception(self):
        def fake_call_method(module, method, *args, **kwargs):
            if method == 'AddPortGroup':
                raise vexc.VMwareDriverException()

        with test.nested(
            mock.patch.object(vm_util, 'get_add_vswitch_port_group_spec'),
            mock.patch.object(vm_util, 'get_host_ref'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_add_vswitch, _get_host, _call_method):
            self.assertRaises(vexc.VMwareDriverException,
                              network_util.create_port_group,
                              self.session, 'pg_name',
                              'vswitch_name', vlan_id=0,
                              cluster=None)

    def test_get_vif_info_none(self):
        vif_info = vif.get_vif_info('fake_session', 'fake_cluster',
                                    'is_neutron', 'fake_model', None)
        self.assertEqual([], vif_info)

    def test_get_vif_info_empty_list(self):
        vif_info = vif.get_vif_info('fake_session', 'fake_cluster',
                                    'is_neutron', 'fake_model', [])
        self.assertEqual([], vif_info)

    @mock.patch.object(vif, 'get_network_ref', return_value='fake_ref')
    def test_get_vif_info(self, mock_get_network_ref):
        network_info = utils.get_test_network_info()
        vif_info = vif.get_vif_info('fake_session', 'fake_cluster',
                                    'is_neutron', 'fake_model', network_info)
        expected = [{'iface_id': utils.FAKE_VIF_UUID,
                     'mac_address': utils.FAKE_VIF_MAC,
                     'network_name': utils.FAKE_NETWORK_BRIDGE,
                     'network_ref': 'fake_ref',
                     'vif_model': 'fake_model'}]
        self.assertEqual(expected, vif_info)

    @mock.patch.object(vif, '_check_ovs_supported_version')
    def test_get_neutron_network_ovs_integration_bridge(self,
                                                        mock_check):
        self.flags(integration_bridge='fake-bridge-id', group='vmware')
        vif_info = network_model.NetworkInfo([
                network_model.VIF(type=network_model.VIF_TYPE_OVS,
                                  address='DE:AD:BE:EF:00:00',
                                  network=self._network)]
        )[0]
        network_ref = vif._get_neutron_network('fake-session',
                                               'fake-cluster',
                                               vif_info)
        expected_ref = {'type': 'OpaqueNetwork',
                        'network-id': 'fake-bridge-id',
                        'network-type': 'opaque',
                        'use-external-id': False}
        self.assertEqual(expected_ref, network_ref)
        mock_check.assert_called_once_with('fake-session')

    @mock.patch.object(vif, '_check_ovs_supported_version')
    def test_get_neutron_network_ovs(self, mock_check):
        vif_info = network_model.NetworkInfo([
                network_model.VIF(type=network_model.VIF_TYPE_OVS,
                                  address='DE:AD:BE:EF:00:00',
                                  network=self._network)]
        )[0]
        network_ref = vif._get_neutron_network('fake-session',
                                               'fake-cluster',
                                               vif_info)
        expected_ref = {'type': 'OpaqueNetwork',
                        'network-id': 0,
                        'network-type': 'nsx.LogicalSwitch',
                        'use-external-id': True}
        self.assertEqual(expected_ref, network_ref)
        mock_check.assert_called_once_with('fake-session')

    @mock.patch.object(vif, '_check_ovs_supported_version')
    def test_get_neutron_network_ovs_logical_switch_id(self, mock_check):
        vif_info = network_model.NetworkInfo([
                network_model.VIF(type=network_model.VIF_TYPE_OVS,
                                  address='DE:AD:BE:EF:00:00',
                                  network=self._network,
                                  details={'nsx-logical-switch-id':
                                           'fake-nsx-id'})]
        )[0]
        network_ref = vif._get_neutron_network('fake-session',
                                               'fake-cluster',
                                               vif_info)
        expected_ref = {'type': 'OpaqueNetwork',
                        'network-id': 'fake-nsx-id',
                        'network-type': 'nsx.LogicalSwitch',
                        'use-external-id': True}
        self.assertEqual(expected_ref, network_ref)
        mock_check.assert_called_once_with('fake-session')

    @mock.patch.object(network_util, 'get_network_with_the_name')
    def test_get_neutron_network_dvs(self, mock_network_name):
        fake_network_obj = {'type': 'DistributedVirtualPortgroup',
                            'dvpg': 'fake-key',
                            'dvsw': 'fake-props'}
        mock_network_name.return_value = fake_network_obj
        vif_info = network_model.NetworkInfo([
                network_model.VIF(type=network_model.VIF_TYPE_DVS,
                                  address='DE:AD:BE:EF:00:00',
                                  network=self._network)]
        )[0]
        network_ref = vif._get_neutron_network('fake-session',
                                               'fake-cluster',
                                               vif_info)
        mock_network_name.assert_called_once_with('fake-session',
                                                  'fa0',
                                                  'fake-cluster')
        self.assertEqual(fake_network_obj, network_ref)

    @mock.patch.object(network_util, 'get_network_with_the_name')
    def test_get_neutron_network_dvs_vif_details(self, mock_network_name):
        fake_network_obj = {'type': 'DistributedVirtualPortgroup',
                            'dvpg': 'pg1',
                            'dvsw': 'fake-props'}
        mock_network_name.return_value = fake_network_obj
        vif_info = network_model.NetworkInfo([
                network_model.VIF(type=network_model.VIF_TYPE_DVS,
                                  details={'dvs_port_key': 'key1',
                                           'dvs_port_group_name': 'pg1'},
                                  address='DE:AD:BE:EF:00:00',
                                  network=self._network)])[0]
        network_ref = vif._get_neutron_network('fake-session',
                                               'fake-cluster',
                                               vif_info)
        mock_network_name.assert_called_once_with('fake-session',
                                                  'pg1',
                                                  'fake-cluster')
        self.assertEqual(fake_network_obj, network_ref)

    @mock.patch.object(network_util, 'get_network_with_the_name',
                       return_value=None)
    def test_get_neutron_network_dvs_no_match(self, mock_network_name):
        vif_info = network_model.NetworkInfo([
                network_model.VIF(type=network_model.VIF_TYPE_DVS,
                                  address='DE:AD:BE:EF:00:00',
                                  network=self._network)]
        )[0]
        self.assertRaises(exception.NetworkNotFoundForBridge,
                          vif._get_neutron_network,
                          'fake-session',
                          'fake-cluster',
                          vif_info)

    def test_get_neutron_network_invalid_type(self):
        vif_info = network_model.NetworkInfo([
                network_model.VIF(address='DE:AD:BE:EF:00:00',
                                  network=self._network)]
        )[0]
        self.assertRaises(exception.InvalidInput,
                          vif._get_neutron_network,
                          'fake-session',
                          'fake-cluster',
                          vif_info)

    @mock.patch.object(vif.LOG, 'warning')
    @mock.patch.object(vim_util, 'get_vc_version',
                       return_value='5.0.0')
    def test_check_invalid_ovs_version(self, mock_version, mock_warning):
        vif._check_ovs_supported_version('fake_session')
        # assert that the min version is in a warning message
        expected_arg = {'version': constants.MIN_VC_OVS_VERSION}
        version_arg_found = False
        for call in mock_warning.call_args_list:
            if call[0][1] == expected_arg:
                version_arg_found = True
                break
        self.assertTrue(version_arg_found)

    @mock.patch.object(network_util, 'get_network_with_the_name')
    def test_get_neutron_network_dvs_provider(self, mock_network_name):
        fake_network_obj = {'type': 'DistributedVirtualPortgroup',
                            'dvpg': 'fake-key',
                            'dvsw': 'fake-props'}
        mock_network_name.side_effect = [fake_network_obj]
        vif_info = network_model.NetworkInfo([
                network_model.VIF(type=network_model.VIF_TYPE_DVS,
                                  address='DE:AD:BE:EF:00:00',
                                  network=self._network)]
        )[0]
        network_ref = vif._get_neutron_network('fake-session',
                                               'fake-cluster',
                                               vif_info)
        calls = [mock.call('fake-session', 'fa0', 'fake-cluster')]
        mock_network_name.assert_has_calls(calls)
        self.assertEqual(fake_network_obj, network_ref)

    @mock.patch.object(network_util, 'get_network_with_the_name',
                       return_value=None)
    def test_raise_neutron_network_dvs(self, mock_network_name):
        mock_network_name.side_effect = None
        vif_info = network_model.NetworkInfo([
            network_model.VIF(type=network_model.VIF_TYPE_DVS,
                              address='DE:AD:BE:EF:00:00',
                              network=self._network)]
        )[0]

        self.assertRaises(exception.NetworkNotFoundForBridge,
                          vif._get_neutron_network,
                          'fake-session',
                          'fake-cluster',
                          vif_info)

    @mock.patch.object(network_util, 'get_network_with_the_name')
    def test_get_neutron_network_dvs_with_dvs_pg_id(self, mock_network_name):
        fake_network_obj = {'type': 'DistributedVirtualPortgroup',
                            'dvpg': 'fake-key',
                            'dvsw': 'fake-props'}
        mock_network_name.side_effect = [fake_network_obj]
        vif_details = {
                'dvs_id': 'fake-props',
                'pg_id': 'fake-key'
        }
        vif_info = network_model.NetworkInfo([
            network_model.VIF(type=network_model.VIF_TYPE_DVS,
                              address='DE:AD:BE:EF:00:00',
                              network=self._network,
                              details=vif_details)]
        )[0]
        network_ref = vif._get_neutron_network('fake-session',
                                               'fake-cluster',
                                               vif_info)

        fake_network_ref = {'type': 'DistributedVirtualPortgroup',
                            'dvpg': 'fake-key',
                            'dvsw': 'fake-props'}

        self.assertEqual(network_ref, fake_network_ref)
        calls = []
        mock_network_name.assert_has_calls(calls)
        self.assertEqual(fake_network_obj, network_ref)
