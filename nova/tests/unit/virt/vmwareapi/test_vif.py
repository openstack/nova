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

    def tearDown(self):
        super(VMwareVifTestCase, self).tearDown()

    def test_ensure_vlan_bridge(self):
        self.mox.StubOutWithMock(network_util, 'get_network_with_the_name')
        self.mox.StubOutWithMock(network_util,
            'get_vswitch_for_vlan_interface')
        self.mox.StubOutWithMock(network_util,
            'check_if_vlan_interface_exists')
        self.mox.StubOutWithMock(network_util, 'create_port_group')
        network_util.get_network_with_the_name(self.session, 'fa0',
            self.cluster).AndReturn(None)
        network_util.get_vswitch_for_vlan_interface(self.session, 'vmnet0',
            self.cluster).AndReturn('vmnet0')
        network_util.check_if_vlan_interface_exists(self.session, 'vmnet0',
            self.cluster).AndReturn(True)
        network_util.create_port_group(self.session, 'fa0', 'vmnet0', 3,
            self.cluster)
        network_util.get_network_with_the_name(self.session, 'fa0', None)

        self.mox.ReplayAll()
        vif.ensure_vlan_bridge(self.session, self.vif, create_vlan=True)

    # FlatDHCP network mode without vlan - network doesn't exist with the host
    def test_ensure_vlan_bridge_without_vlan(self):
        self.mox.StubOutWithMock(network_util, 'get_network_with_the_name')
        self.mox.StubOutWithMock(network_util,
            'get_vswitch_for_vlan_interface')
        self.mox.StubOutWithMock(network_util,
            'check_if_vlan_interface_exists')
        self.mox.StubOutWithMock(network_util, 'create_port_group')

        network_util.get_network_with_the_name(self.session, 'fa0',
            self.cluster).AndReturn(None)
        network_util.get_vswitch_for_vlan_interface(self.session, 'vmnet0',
            self.cluster).AndReturn('vmnet0')
        network_util.check_if_vlan_interface_exists(self.session, 'vmnet0',
        self.cluster).AndReturn(True)
        network_util.create_port_group(self.session, 'fa0', 'vmnet0', 0,
            self.cluster)
        network_util.get_network_with_the_name(self.session, 'fa0', None)
        self.mox.ReplayAll()
        vif.ensure_vlan_bridge(self.session, self.vif, create_vlan=False)

    # FlatDHCP network mode without vlan - network exists with the host
    # Get vswitch and check vlan interface should not be called
    def test_ensure_vlan_bridge_with_network(self):
        self.mox.StubOutWithMock(network_util, 'get_network_with_the_name')
        self.mox.StubOutWithMock(network_util,
            'get_vswitch_for_vlan_interface')
        self.mox.StubOutWithMock(network_util,
            'check_if_vlan_interface_exists')
        self.mox.StubOutWithMock(network_util, 'create_port_group')
        vm_network = {'name': 'VM Network', 'type': 'Network'}
        network_util.get_network_with_the_name(self.session, 'fa0',
            self.cluster).AndReturn(vm_network)
        self.mox.ReplayAll()
        vif.ensure_vlan_bridge(self.session, self.vif, create_vlan=False)

    # Flat network mode with DVS
    def test_ensure_vlan_bridge_with_existing_dvs(self):
        network_ref = {'dvpg': 'dvportgroup-2062',
                       'type': 'DistributedVirtualPortgroup'}
        self.mox.StubOutWithMock(network_util, 'get_network_with_the_name')
        self.mox.StubOutWithMock(network_util,
            'get_vswitch_for_vlan_interface')
        self.mox.StubOutWithMock(network_util,
            'check_if_vlan_interface_exists')
        self.mox.StubOutWithMock(network_util, 'create_port_group')

        network_util.get_network_with_the_name(self.session, 'fa0',
            self.cluster).AndReturn(network_ref)
        self.mox.ReplayAll()
        ref = vif.ensure_vlan_bridge(self.session,
                                     self.vif,
                                     create_vlan=False)
        self.assertThat(ref, matchers.DictMatches(network_ref))

    def test_get_network_ref_flat_dhcp(self):
        self.mox.StubOutWithMock(vif, 'ensure_vlan_bridge')
        vif.ensure_vlan_bridge(self.session, self.vif, cluster=self.cluster,
                               create_vlan=False)
        self.mox.ReplayAll()
        vif.get_network_ref(self.session, self.cluster, self.vif, False)

    def test_get_network_ref_bridge(self):
        self.mox.StubOutWithMock(vif, 'ensure_vlan_bridge')
        vif.ensure_vlan_bridge(self.session, self.vif, cluster=self.cluster,
                               create_vlan=True)
        self.mox.ReplayAll()
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
        expected = [{'iface_id': 'vif-xxx-yyy-zzz',
                     'mac_address': 'fake',
                     'network_name': 'fake',
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
