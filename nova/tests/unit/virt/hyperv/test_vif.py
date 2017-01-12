# Copyright 2015 Cloudbase Solutions Srl
#
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

import nova.conf
from nova import exception
from nova.network import model
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import vif

CONF = nova.conf.CONF


class HyperVNovaNetworkVIFPluginTestCase(test_base.HyperVBaseTestCase):
    def setUp(self):
        super(HyperVNovaNetworkVIFPluginTestCase, self).setUp()
        self.vif_driver = vif.HyperVNovaNetworkVIFPlugin()

    def test_plug(self):
        self.flags(vswitch_name='fake_vswitch_name', group='hyperv')
        fake_vif = {'id': mock.sentinel.fake_id}

        self.vif_driver.plug(mock.sentinel.instance, fake_vif)
        netutils = self.vif_driver._netutils
        netutils.connect_vnic_to_vswitch.assert_called_once_with(
            'fake_vswitch_name', mock.sentinel.fake_id)


class HyperVVIFDriverTestCase(test_base.HyperVBaseTestCase):
    def setUp(self):
        super(HyperVVIFDriverTestCase, self).setUp()
        self.vif_driver = vif.HyperVVIFDriver()
        self.vif_driver._netutils = mock.MagicMock()
        self.vif_driver._vif_plugin = mock.MagicMock()

    @mock.patch.object(vif.nova.network, 'is_neutron')
    def test_init_neutron(self, mock_is_neutron):
        mock_is_neutron.return_value = True

        driver = vif.HyperVVIFDriver()
        self.assertIsInstance(driver._vif_plugin, vif.HyperVNeutronVIFPlugin)

    @mock.patch.object(vif.nova.network, 'is_neutron')
    def test_init_nova(self, mock_is_neutron):
        mock_is_neutron.return_value = False

        driver = vif.HyperVVIFDriver()
        self.assertIsInstance(driver._vif_plugin,
                              vif.HyperVNovaNetworkVIFPlugin)

    def test_plug(self):
        vif = {'type': model.VIF_TYPE_HYPERV}
        self.vif_driver.plug(mock.sentinel.instance, vif)

        self.vif_driver._vif_plugin.plug.assert_called_once_with(
            mock.sentinel.instance, vif)

    @mock.patch.object(vif, 'os_vif')
    @mock.patch.object(vif.os_vif_util, 'nova_to_osvif_instance')
    @mock.patch.object(vif.os_vif_util, 'nova_to_osvif_vif')
    def test_plug_ovs(self, mock_nova_to_osvif_vif,
                      mock_nova_to_osvif_instance, mock_os_vif):
        vif = {'type': model.VIF_TYPE_OVS}
        self.vif_driver.plug(mock.sentinel.instance, vif)

        mock_nova_to_osvif_vif.assert_called_once_with(vif)
        mock_nova_to_osvif_instance.assert_called_once_with(
            mock.sentinel.instance)
        connect_vnic = self.vif_driver._netutils.connect_vnic_to_vswitch
        connect_vnic.assert_called_once_with(
            CONF.hyperv.vswitch_name, mock_nova_to_osvif_vif.return_value.id)
        mock_os_vif.plug.assert_called_once_with(
            mock_nova_to_osvif_vif.return_value,
            mock_nova_to_osvif_instance.return_value)

    def test_plug_type_unknown(self):
        vif = {'type': mock.sentinel.vif_type}
        self.assertRaises(exception.VirtualInterfacePlugException,
                          self.vif_driver.plug,
                          mock.sentinel.instance, vif)

    def test_unplug(self):
        vif = {'type': model.VIF_TYPE_HYPERV}
        self.vif_driver.unplug(mock.sentinel.instance, vif)

        self.vif_driver._vif_plugin.unplug.assert_called_once_with(
            mock.sentinel.instance, vif)

    @mock.patch.object(vif, 'os_vif')
    @mock.patch.object(vif.os_vif_util, 'nova_to_osvif_instance')
    @mock.patch.object(vif.os_vif_util, 'nova_to_osvif_vif')
    def test_unplug_ovs(self, mock_nova_to_osvif_vif,
                        mock_nova_to_osvif_instance, mock_os_vif):
        vif = {'type': model.VIF_TYPE_OVS}
        self.vif_driver.unplug(mock.sentinel.instance, vif)

        mock_nova_to_osvif_vif.assert_called_once_with(vif)
        mock_nova_to_osvif_instance.assert_called_once_with(
            mock.sentinel.instance)
        mock_os_vif.unplug.assert_called_once_with(
            mock_nova_to_osvif_vif.return_value,
            mock_nova_to_osvif_instance.return_value)

    def test_unplug_type_unknown(self):
        vif = {'type': mock.sentinel.vif_type}
        self.assertRaises(exception.VirtualInterfaceUnplugException,
                          self.vif_driver.unplug,
                          mock.sentinel.instance, vif)
