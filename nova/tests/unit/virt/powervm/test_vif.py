# Copyright 2017 IBM Corp.
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
from oslo_config import cfg
from pypowervm import exceptions as pvm_ex
from pypowervm.wrappers import network as pvm_net

from nova import exception
from nova.network import model
from nova import test
from nova.virt.powervm import vif

CONF = cfg.CONF


def cna(mac):
    """Builds a mock Client Network Adapter for unit tests."""
    return mock.Mock(spec=pvm_net.CNA, mac=mac, vswitch_uri='fake_href')


class TestVifFunctions(test.NoDBTestCase):

    def setUp(self):
        super(TestVifFunctions, self).setUp()

        self.adpt = mock.Mock()

    @mock.patch('nova.virt.powervm.vif.PvmOvsVifDriver')
    def test_build_vif_driver(self, mock_driver):
        # Valid vif type
        driver = vif._build_vif_driver(self.adpt, 'instance', {'type': 'ovs'})
        self.assertEqual(mock_driver.return_value, driver)

        mock_driver.reset_mock()

        # Fail if no vif type
        self.assertRaises(exception.VirtualInterfacePlugException,
                          vif._build_vif_driver, self.adpt, 'instance',
                          {'type': None})
        mock_driver.assert_not_called()

        # Fail if invalid vif type
        self.assertRaises(exception.VirtualInterfacePlugException,
                          vif._build_vif_driver, self.adpt, 'instance',
                          {'type': 'bad_type'})
        mock_driver.assert_not_called()

    @mock.patch('oslo_serialization.jsonutils.dumps')
    @mock.patch('pypowervm.wrappers.event.Event')
    def test_push_vif_event(self, mock_event, mock_dumps):
        mock_vif = mock.Mock(mac='MAC', href='HREF')
        vif._push_vif_event(self.adpt, 'action', mock_vif, mock.Mock(),
                            'pvm_sea')
        mock_dumps.assert_called_once_with(
            {'provider': 'NOVA_PVM_VIF', 'action': 'action', 'mac': 'MAC',
             'type': 'pvm_sea'})
        mock_event.bld.assert_called_once_with(self.adpt, 'HREF',
                                               mock_dumps.return_value)
        mock_event.bld.return_value.create.assert_called_once_with()

        mock_dumps.reset_mock()
        mock_event.bld.reset_mock()
        mock_event.bld.return_value.create.reset_mock()

        # Exception reraises
        mock_event.bld.return_value.create.side_effect = IndexError
        self.assertRaises(IndexError, vif._push_vif_event, self.adpt, 'action',
                          mock_vif, mock.Mock(), 'pvm_sea')
        mock_dumps.assert_called_once_with(
            {'provider': 'NOVA_PVM_VIF', 'action': 'action', 'mac': 'MAC',
             'type': 'pvm_sea'})
        mock_event.bld.assert_called_once_with(self.adpt, 'HREF',
                                               mock_dumps.return_value)
        mock_event.bld.return_value.create.assert_called_once_with()

    @mock.patch('nova.virt.powervm.vif._push_vif_event')
    @mock.patch('nova.virt.powervm.vif._build_vif_driver')
    def test_plug(self, mock_bld_drv, mock_event):
        """Test the top-level plug method."""
        mock_vif = {'address': 'MAC', 'type': 'pvm_sea'}

        # 1) With new_vif=True (default)
        vnet = vif.plug(self.adpt, 'instance', mock_vif)

        mock_bld_drv.assert_called_once_with(self.adpt, 'instance', mock_vif)
        mock_bld_drv.return_value.plug.assert_called_once_with(mock_vif,
                                                               new_vif=True)
        self.assertEqual(mock_bld_drv.return_value.plug.return_value, vnet)
        mock_event.assert_called_once_with(self.adpt, 'plug', vnet, mock.ANY,
                                           'pvm_sea')

        # Clean up
        mock_bld_drv.reset_mock()
        mock_bld_drv.return_value.plug.reset_mock()
        mock_event.reset_mock()

        # 2) Plug returns None (which it should IRL whenever new_vif=False).
        mock_bld_drv.return_value.plug.return_value = None
        vnet = vif.plug(self.adpt, 'instance', mock_vif, new_vif=False)

        mock_bld_drv.assert_called_once_with(self.adpt, 'instance', mock_vif)
        mock_bld_drv.return_value.plug.assert_called_once_with(mock_vif,
                                                               new_vif=False)
        self.assertIsNone(vnet)
        mock_event.assert_not_called()

    @mock.patch('nova.virt.powervm.vif._build_vif_driver')
    def test_plug_raises(self, mock_vif_drv):
        """HttpError is converted to VirtualInterfacePlugException."""
        vif_drv = mock.Mock(plug=mock.Mock(side_effect=pvm_ex.HttpError(
            resp=mock.Mock())))
        mock_vif_drv.return_value = vif_drv
        mock_vif = {'address': 'vifaddr'}
        self.assertRaises(exception.VirtualInterfacePlugException,
                          vif.plug, 'adap', 'inst', mock_vif,
                          new_vif='new_vif')
        mock_vif_drv.assert_called_once_with('adap', 'inst', mock_vif)
        vif_drv.plug.assert_called_once_with(mock_vif, new_vif='new_vif')

    @mock.patch('nova.virt.powervm.vif._push_vif_event')
    @mock.patch('nova.virt.powervm.vif._build_vif_driver')
    def test_unplug(self, mock_bld_drv, mock_event):
        """Test the top-level unplug method."""
        mock_vif = {'address': 'MAC', 'type': 'pvm_sea'}

        # 1) With default cna_w_list
        mock_bld_drv.return_value.unplug.return_value = 'vnet_w'
        vif.unplug(self.adpt, 'instance', mock_vif)
        mock_bld_drv.assert_called_once_with(self.adpt, 'instance', mock_vif)
        mock_bld_drv.return_value.unplug.assert_called_once_with(
            mock_vif, cna_w_list=None)
        mock_event.assert_called_once_with(self.adpt, 'unplug', 'vnet_w',
                                           mock.ANY, 'pvm_sea')
        # Clean up
        mock_bld_drv.reset_mock()
        mock_bld_drv.return_value.unplug.reset_mock()
        mock_event.reset_mock()

        # 2) With specified cna_w_list
        mock_bld_drv.return_value.unplug.return_value = None
        vif.unplug(self.adpt, 'instance', mock_vif, cna_w_list='cnalist')
        mock_bld_drv.assert_called_once_with(self.adpt, 'instance', mock_vif)
        mock_bld_drv.return_value.unplug.assert_called_once_with(
            mock_vif, cna_w_list='cnalist')
        mock_event.assert_not_called()

    @mock.patch('nova.virt.powervm.vif._build_vif_driver')
    def test_unplug_raises(self, mock_vif_drv):
        """HttpError is converted to VirtualInterfacePlugException."""
        vif_drv = mock.Mock(unplug=mock.Mock(side_effect=pvm_ex.HttpError(
            resp=mock.Mock())))
        mock_vif_drv.return_value = vif_drv
        mock_vif = {'address': 'vifaddr'}
        self.assertRaises(exception.VirtualInterfaceUnplugException,
                          vif.unplug, 'adap', 'inst', mock_vif,
                          cna_w_list='cna_w_list')
        mock_vif_drv.assert_called_once_with('adap', 'inst', mock_vif)
        vif_drv.unplug.assert_called_once_with(
            mock_vif, cna_w_list='cna_w_list')


class TestVifOvsDriver(test.NoDBTestCase):

    def setUp(self):
        super(TestVifOvsDriver, self).setUp()

        self.adpt = mock.Mock()
        self.inst = mock.MagicMock(uuid='inst_uuid')
        self.drv = vif.PvmOvsVifDriver(self.adpt, self.inst)

    @mock.patch('pypowervm.tasks.cna.crt_p2p_cna', autospec=True)
    @mock.patch('pypowervm.tasks.partition.get_this_partition', autospec=True)
    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
    def test_plug(self, mock_pvm_uuid, mock_mgmt_lpar, mock_p2p_cna,):
        # Mock the data
        mock_pvm_uuid.return_value = 'lpar_uuid'
        mock_mgmt_lpar.return_value = mock.Mock(uuid='mgmt_uuid')
        # mock_trunk_dev_name.return_value = 'device'

        cna_w, trunk_wraps = mock.MagicMock(), [mock.MagicMock()]
        mock_p2p_cna.return_value = cna_w, trunk_wraps

        # Run the plug
        network_model = model.Model({'bridge': 'br0', 'meta': {'mtu': 1450}})
        mock_vif = model.VIF(address='aa:bb:cc:dd:ee:ff', id='vif_id',
                             network=network_model, devname='device')
        self.drv.plug(mock_vif)

        # Validate the calls
        ovs_ext_ids = ('iface-id=vif_id,iface-status=active,'
                       'attached-mac=aa:bb:cc:dd:ee:ff,vm-uuid=inst_uuid')
        mock_p2p_cna.assert_called_once_with(
            self.adpt, None, 'lpar_uuid', ['mgmt_uuid'],
            'NovaLinkVEABridge', configured_mtu=1450, crt_vswitch=True,
            mac_addr='aa:bb:cc:dd:ee:ff', dev_name='device', ovs_bridge='br0',
            ovs_ext_ids=ovs_ext_ids)

    @mock.patch('pypowervm.tasks.partition.get_this_partition', autospec=True)
    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    @mock.patch('pypowervm.tasks.cna.find_trunks', autospec=True)
    def test_plug_existing_vif(self, mock_find_trunks, mock_get_cnas,
                               mock_pvm_uuid, mock_mgmt_lpar):
        # Mock the data
        t1, t2 = mock.MagicMock(), mock.MagicMock()
        mock_find_trunks.return_value = [t1, t2]

        mock_cna = mock.Mock(mac='aa:bb:cc:dd:ee:ff')
        mock_get_cnas.return_value = [mock_cna]

        mock_pvm_uuid.return_value = 'lpar_uuid'

        mock_mgmt_lpar.return_value = mock.Mock(uuid='mgmt_uuid')

        self.inst = mock.MagicMock(uuid='c2e7ff9f-b9b6-46fa-8716-93bbb795b8b4')
        self.drv = vif.PvmOvsVifDriver(self.adpt, self.inst)

        # Run the plug
        network_model = model.Model({'bridge': 'br0', 'meta': {'mtu': 1500}})
        mock_vif = model.VIF(address='aa:bb:cc:dd:ee:ff', id='vif_id',
                             network=network_model, devname='devname')
        resp = self.drv.plug(mock_vif, new_vif=False)

        self.assertIsNone(resp)

        # Validate if trunk.update got invoked for all trunks of CNA of vif
        self.assertTrue(t1.update.called)
        self.assertTrue(t2.update.called)

    @mock.patch('pypowervm.tasks.cna.find_trunks')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_unplug(self, mock_get_cnas, mock_find_trunks):
        # Set up the mocks
        mock_cna = mock.Mock(mac='aa:bb:cc:dd:ee:ff')
        mock_get_cnas.return_value = [mock_cna]

        t1, t2 = mock.MagicMock(), mock.MagicMock()
        mock_find_trunks.return_value = [t1, t2]

        # Call the unplug
        mock_vif = {'address': 'aa:bb:cc:dd:ee:ff',
                    'network': {'bridge': 'br-int'}}
        self.drv.unplug(mock_vif)

        # The trunks and the cna should have been deleted
        self.assertTrue(t1.delete.called)
        self.assertTrue(t2.delete.called)
        self.assertTrue(mock_cna.delete.called)


class TestVifSeaDriver(test.NoDBTestCase):

    def setUp(self):
        super(TestVifSeaDriver, self).setUp()

        self.adpt = mock.Mock()
        self.inst = mock.Mock()
        self.drv = vif.PvmSeaVifDriver(self.adpt, self.inst)

    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
    @mock.patch('pypowervm.tasks.cna.crt_cna')
    def test_plug_from_neutron(self, mock_crt_cna, mock_pvm_uuid):
        """Tests that a VIF can be created.  Mocks Neutron net"""

        # Set up the mocks.  Look like Neutron
        fake_vif = {'details': {'vlan': 5}, 'network': {'meta': {}},
                    'address': 'aabbccddeeff'}

        def validate_crt(adpt, host_uuid, lpar_uuid, vlan, mac_addr=None):
            self.assertIsNone(host_uuid)
            self.assertEqual(5, vlan)
            self.assertEqual('aabbccddeeff', mac_addr)
            return pvm_net.CNA.bld(self.adpt, 5, 'host_uuid',
                                   mac_addr=mac_addr)
        mock_crt_cna.side_effect = validate_crt

        # Invoke
        resp = self.drv.plug(fake_vif)

        # Validate (along with validate method above)
        self.assertEqual(1, mock_crt_cna.call_count)
        self.assertIsNotNone(resp)
        self.assertIsInstance(resp, pvm_net.CNA)

    def test_plug_existing_vif(self):
        """Tests that a VIF need not be created."""

        # Set up the mocks
        fake_vif = {'network': {'meta': {'vlan': 5}},
                    'address': 'aabbccddeeff'}

        # Invoke
        resp = self.drv.plug(fake_vif, new_vif=False)

        self.assertIsNone(resp)

    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_unplug_vifs(self, mock_vm_get):
        """Tests that a delete of the vif can be done."""
        # Mock up the CNA response.  Two should already exist, the other
        # should not.
        cnas = [cna('AABBCCDDEEFF'), cna('AABBCCDDEE11'), cna('AABBCCDDEE22')]
        mock_vm_get.return_value = cnas

        # Run method.  The AABBCCDDEE11 won't be unplugged (wasn't invoked
        # below) and the last unplug will also just no-op because its not on
        # the VM.
        self.drv.unplug({'address': 'aa:bb:cc:dd:ee:ff'})
        self.drv.unplug({'address': 'aa:bb:cc:dd:ee:22'})
        self.drv.unplug({'address': 'aa:bb:cc:dd:ee:33'})

        # The delete should have only been called once for each applicable vif.
        # The second CNA didn't have a matching mac so it should be skipped.
        self.assertEqual(1, cnas[0].delete.call_count)
        self.assertEqual(0, cnas[1].delete.call_count)
        self.assertEqual(1, cnas[2].delete.call_count)
