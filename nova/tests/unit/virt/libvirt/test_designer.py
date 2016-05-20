# Copyright (C) 2013 eNovance SAS <licensing@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from nova.pci import utils as pci_utils
from nova import test
from nova.tests.unit import matchers
from nova.virt.libvirt import config
from nova.virt.libvirt import designer


class DesignerTestCase(test.NoDBTestCase):

    def test_set_vif_bandwidth_config_no_extra_specs(self):
        # Test whether test_set_vif_bandwidth_config_no_extra_specs fails when
        # its second parameter has no 'extra_specs' field.

        try:
            # The conf will never be user be used, so we can use 'None'.
            # An empty dictionary is fine: all that matters it that there is no
            # 'extra_specs' field.
            designer.set_vif_bandwidth_config(None, {})
        except KeyError as e:
            self.fail('KeyError: %s' % e)

    def test_set_vif_guest_frontend_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_guest_frontend_config(conf, 'fake-mac',
                                               'fake-model', 'fake-driver',
                                               'fake-queues')
        self.assertEqual('fake-mac', conf.mac_addr)
        self.assertEqual('fake-model', conf.model)
        self.assertEqual('fake-driver', conf.driver_name)
        self.assertEqual('fake-queues', conf.vhost_queues)

    def test_set_vif_host_backend_bridge_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_bridge_config(conf, 'fake-bridge',
                                                    'fake-tap')
        self.assertEqual('bridge', conf.net_type)
        self.assertEqual('fake-bridge', conf.source_dev)
        self.assertEqual('fake-tap', conf.target_dev)

    def test_set_vif_host_backend_ethernet_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_ethernet_config(conf, 'fake-tap')
        self.assertEqual('ethernet', conf.net_type)
        self.assertEqual('fake-tap', conf.target_dev)
        self.assertEqual('', conf.script)

    def test_set_vif_host_backend_ovs_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_ovs_config(conf, 'fake-bridge',
                                                 'fake-interface', 'fake-tap')
        self.assertEqual('bridge', conf.net_type)
        self.assertEqual('fake-bridge', conf.source_dev)
        self.assertEqual('openvswitch', conf.vporttype)
        self.assertEqual('fake-tap', conf.target_dev)

    def test_set_vif_host_backend_802qbg_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_802qbg_config(conf, 'fake-devname',
                                                    'fake-managerid',
                                                    'fake-typeid',
                                                    'fake-typeidversion',
                                                    'fake-instanceid',
                                                    'fake-tap')
        self.assertEqual('direct', conf.net_type)
        self.assertEqual('fake-devname', conf.source_dev)
        self.assertEqual('vepa', conf.source_mode)
        self.assertEqual('802.1Qbg', conf.vporttype)
        expected = [{'key': 'managerid', 'value': 'fake-managerid'},
                    {'key': 'typeid', 'value': 'fake-typeid'},
                    {'key': 'typeidversion', 'value': 'fake-typeidversion'},
                    {'key': 'instanceid', 'value': 'fake-instanceid'}]
        self.assertThat(expected, matchers.DictListMatches(conf.vportparams))
        self.assertEqual('fake-tap', conf.target_dev)

    @mock.patch.object(pci_utils, 'get_ifname_by_pci_address',
                       return_value='fake-devname')
    def test_set_vif_host_backend_802qbh_config_direct(self,
                                                       mock_pci):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_802qbh_config(conf, 'direct',
                                                    'fake-pci-dev',
                                                    'fake-profileid',
                                                    'fake-tap')
        self.assertEqual('direct', conf.net_type)
        self.assertEqual('fake-devname', conf.source_dev)
        self.assertEqual('passthrough', conf.source_mode)
        self.assertEqual('vhost', conf.driver_name)
        mock_pci.assert_called_with('fake-pci-dev')
        self.assertEqual('802.1Qbh', conf.vporttype)
        self.assertEqual('fake-tap', conf.target_dev)

    def test_set_vif_host_backend_802qbh_config_hostdev(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_802qbh_config(conf, 'hostdev',
                                                    'fake-devname',
                                                    'fake-profileid',
                                                    'fake-tap')
        self.assertEqual('hostdev', conf.net_type)
        self.assertEqual('fake-devname', conf.source_dev)
        self.assertIsNone(conf.model)
        self.assertEqual('802.1Qbh', conf.vporttype)
        self.assertEqual('fake-tap', conf.target_dev)

    @mock.patch.object(pci_utils, 'get_ifname_by_pci_address',
                       return_value='fake-devname')
    def test_set_vif_host_backend_hw_veb_direct(self,
                                                mock_pci):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_hw_veb(conf, 'direct',
                                             'fake-pci-dev',
                                             'fake-vlan',
                                             'fake-tap')
        self.assertEqual('direct', conf.net_type)
        self.assertEqual('fake-devname', conf.source_dev)
        self.assertEqual('passthrough', conf.source_mode)
        self.assertEqual('vhost', conf.driver_name)
        self.assertEqual('fake-tap', conf.target_dev)
        mock_pci.assert_called_with('fake-pci-dev')

    def test_set_vif_host_backend_hw_veb_hostdev(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_hw_veb(conf, 'hostdev',
                                             'fake-devname',
                                             'fake-vlan',
                                             'fake-tap')
        self.assertEqual('hostdev', conf.net_type)
        self.assertEqual('fake-devname', conf.source_dev)
        self.assertIsNone(conf.model)
        self.assertEqual('fake-vlan', conf.vlan)
        self.assertEqual('fake-tap', conf.target_dev)

    @mock.patch.object(pci_utils, 'get_pci_address_fields',
                       return_value=('fake-domain', 'fake-bus',
                                     'fake-slot', 'fake-function'))
    def test_set_vif_host_backend_hostdev_pci_config(self, mock_pci_fields):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_hostdev_pci_config(conf,
                                                        'fake-pci-slot')
        self.assertEqual('fake-domain', conf.domain)
        self.assertEqual('fake-bus', conf.bus)
        self.assertEqual('fake-slot', conf.slot)
        self.assertEqual('fake-function', conf.function)
        mock_pci_fields.assert_called_with('fake-pci-slot')

    def test_set_vif_host_backend_direct_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_direct_config(conf, 'fake-devname',
                                                    mode="passthrough")
        self.assertEqual('direct', conf.net_type)
        self.assertEqual('fake-devname', conf.source_dev)
        self.assertEqual('passthrough', conf.source_mode)
        self.assertEqual('virtio', conf.model)

    def test_set_vif_host_backend_vhostuser_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_vhostuser_config(conf, 'fake-mode',
                                                       'fake-path')
        self.assertEqual('vhostuser', conf.net_type)
        self.assertEqual('unix', conf.vhostuser_type)
        self.assertEqual('fake-mode', conf.vhostuser_mode)
        self.assertEqual('fake-path', conf.vhostuser_path)
