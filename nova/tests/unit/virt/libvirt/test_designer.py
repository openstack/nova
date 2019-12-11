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
from nova.tests.unit.virt.libvirt import fake_libvirt_data
from nova.virt.libvirt import config
from nova.virt.libvirt import designer
from nova.virt.libvirt import host


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
                                               'fake-queues', None)
        self.assertEqual('fake-mac', conf.mac_addr)
        self.assertEqual('fake-model', conf.model)
        self.assertEqual('fake-driver', conf.driver_name)
        self.assertEqual('fake-queues', conf.vhost_queues)
        self.assertIsNone(conf.vhost_rx_queue_size)

    def test_set_vif_guest_frontend_config_rx_queue_size(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_guest_frontend_config(conf, 'fake-mac',
                                               'fake-model', 'fake-driver',
                                               'fake-queues', 1024)
        self.assertEqual('fake-mac', conf.mac_addr)
        self.assertEqual('fake-model', conf.model)
        self.assertEqual('fake-driver', conf.driver_name)
        self.assertEqual('fake-queues', conf.vhost_queues)
        self.assertEqual(1024, conf.vhost_rx_queue_size)

    def test_set_vif_host_backend_ethernet_config_libvirt_1_3_3(self):
        conf = config.LibvirtConfigGuestInterface()
        mock_host = mock.Mock(autospec=host.Host)
        mock_host.has_min_version.return_value = True
        designer.set_vif_host_backend_ethernet_config(
            conf, 'fake-tap', mock_host)
        self.assertEqual('ethernet', conf.net_type)
        self.assertEqual('fake-tap', conf.target_dev)
        self.assertIsNone(conf.script)

    def test_set_vif_host_backend_ethernet_config_libvirt_pre_1_3_3(self):
        conf = config.LibvirtConfigGuestInterface()
        mock_host = mock.Mock(autospec=host.Host)
        mock_host.has_min_version.return_value = False
        designer.set_vif_host_backend_ethernet_config(
            conf, 'fake-tap', mock_host)
        self.assertEqual('ethernet', conf.net_type)
        self.assertEqual('fake-tap', conf.target_dev)
        self.assertEqual('', conf.script)

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
                                                       'fake-path', None, None)
        self.assertEqual('vhostuser', conf.net_type)
        self.assertEqual('unix', conf.vhostuser_type)
        self.assertEqual('fake-mode', conf.vhostuser_mode)
        self.assertEqual('fake-path', conf.vhostuser_path)
        self.assertIsNone(conf.vhost_rx_queue_size)
        self.assertIsNone(conf.vhost_tx_queue_size)

    def test_set_vif_host_backend_vhostuser_config_queue_size(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_vhostuser_config(conf, 'fake-mode',
                                                       'fake-path', 512, 1024)
        self.assertEqual('vhostuser', conf.net_type)
        self.assertEqual('unix', conf.vhostuser_type)
        self.assertEqual('fake-mode', conf.vhostuser_mode)
        self.assertEqual('fake-path', conf.vhostuser_path)
        self.assertEqual(512, conf.vhost_rx_queue_size)
        self.assertEqual(1024, conf.vhost_tx_queue_size)

    def test_set_vif_host_backend_vhostuser_config_tx_queue_size(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_vhostuser_config(conf, 'fake-mode',
                                                       'fake-path', None, 1024)
        self.assertEqual('vhostuser', conf.net_type)
        self.assertEqual('unix', conf.vhostuser_type)
        self.assertEqual('fake-mode', conf.vhostuser_mode)
        self.assertEqual('fake-path', conf.vhostuser_path)
        self.assertIsNone(conf.vhost_rx_queue_size)
        self.assertEqual(1024, conf.vhost_tx_queue_size)

    def test_set_vif_host_backend_vhostuser_config_rx_queue_size(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_host_backend_vhostuser_config(conf, 'fake-mode',
                                                       'fake-path', 512, None)
        self.assertEqual('vhostuser', conf.net_type)
        self.assertEqual('unix', conf.vhostuser_type)
        self.assertEqual('fake-mode', conf.vhostuser_mode)
        self.assertEqual('fake-path', conf.vhostuser_path)
        self.assertEqual(512, conf.vhost_rx_queue_size)
        self.assertIsNone(conf.vhost_tx_queue_size)

    def test_set_vif_mtu_config(self):
        conf = config.LibvirtConfigGuestInterface()
        designer.set_vif_mtu_config(conf, 9000)
        self.assertEqual(9000, conf.mtu)

    def test_set_driver_iommu_for_sev(self):
        conf = fake_libvirt_data.fake_kvm_guest()

        # obj.devices[11]
        controller = config.LibvirtConfigGuestController()
        controller.type = 'virtio-serial'
        controller.index = 0
        conf.add_device(controller)

        designer.set_driver_iommu_for_sev(conf)

        # All disks/interfaces/memballoon are expected to be virtio,
        # thus driver_iommu should be on
        self.assertEqual(11, len(conf.devices))
        for i in (0, 2, 3, 6, 8, 9, 10):
            dev = conf.devices[i]
            self.assertTrue(
                dev.driver_iommu,
                "expected device %d to have driver_iommu enabled\n%s" %
                (i, dev.to_xml()))

        for i in (1, 4):
            dev = conf.devices[i]
            self.assertFalse(
                dev.driver_iommu,
                "didn't expect device %i to have driver_iommu enabled\n%s" %
                (i, dev.to_xml()))
