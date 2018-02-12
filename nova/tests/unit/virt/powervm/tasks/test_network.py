# Copyright 2015, 2017 IBM Corp.
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

import copy

import eventlet
import mock
from pypowervm.wrappers import network as pvm_net

from nova import exception
from nova import test
from nova.tests.unit.virt import powervm
from nova.virt.powervm.tasks import network as tf_net


def cna(mac):
    """Builds a mock Client Network Adapter for unit tests."""
    return mock.MagicMock(mac=mac, vswitch_uri='fake_href')


class TestNetwork(test.NoDBTestCase):
    def setUp(self):
        super(TestNetwork, self).setUp()
        self.flags(host='host1')
        self.apt = mock.Mock()

        self.mock_lpar_wrap = mock.MagicMock()
        self.mock_lpar_wrap.can_modify_io.return_value = True, None

    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper')
    @mock.patch('nova.virt.powervm.vif.unplug')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_unplug_vifs(self, mock_vm_get, mock_unplug, mock_get_wrap):
        """Tests that a delete of the vif can be done."""
        inst = powervm.TEST_INSTANCE

        # Mock up the CNA responses.
        cnas = [cna('AABBCCDDEEFF'), cna('AABBCCDDEE11'), cna('AABBCCDDEE22')]
        mock_vm_get.return_value = cnas

        # Mock up the network info.  This also validates that they will be
        # sanitized to upper case.
        net_info = [
            {'address': 'aa:bb:cc:dd:ee:ff'}, {'address': 'aa:bb:cc:dd:ee:22'},
            {'address': 'aa:bb:cc:dd:ee:33'}
        ]

        # Mock out the instance wrapper
        mock_get_wrap.return_value = self.mock_lpar_wrap

        # Mock out the vif driver
        def validate_unplug(adapter, instance, vif, cna_w_list=None):
            self.assertEqual(adapter, self.apt)
            self.assertEqual(instance, inst)
            self.assertIn(vif, net_info)
            self.assertEqual(cna_w_list, cnas)

        mock_unplug.side_effect = validate_unplug

        # Run method
        p_vifs = tf_net.UnplugVifs(self.apt, inst, net_info)
        p_vifs.execute()

        # Make sure the unplug was invoked, so that we know that the validation
        # code was called
        self.assertEqual(3, mock_unplug.call_count)

        # Validate args on taskflow.task.Task instantiation
        with mock.patch('taskflow.task.Task.__init__') as tf:
            tf_net.UnplugVifs(self.apt, inst, net_info)
        tf.assert_called_once_with(name='unplug_vifs')

    @mock.patch('nova.virt.powervm.vm.get_instance_wrapper')
    def test_unplug_vifs_invalid_state(self, mock_get_wrap):
        """Tests that the delete raises an exception if bad VM state."""
        inst = powervm.TEST_INSTANCE

        # Mock out the instance wrapper
        mock_get_wrap.return_value = self.mock_lpar_wrap

        # Mock that the state is incorrect
        self.mock_lpar_wrap.can_modify_io.return_value = False, 'bad'

        # Run method
        p_vifs = tf_net.UnplugVifs(self.apt, inst, mock.Mock())
        self.assertRaises(exception.VirtualInterfaceUnplugException,
                          p_vifs.execute)

    @mock.patch('nova.virt.powervm.vif.plug')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_plug_vifs_rmc(self, mock_cna_get, mock_plug):
        """Tests that a crt vif can be done with secure RMC."""
        inst = powervm.TEST_INSTANCE

        # Mock up the CNA response.  One should already exist, the other
        # should not.
        pre_cnas = [cna('AABBCCDDEEFF'), cna('AABBCCDDEE11')]
        mock_cna_get.return_value = copy.deepcopy(pre_cnas)

        # Mock up the network info.  This also validates that they will be
        # sanitized to upper case.
        net_info = [
            {'address': 'aa:bb:cc:dd:ee:ff', 'vnic_type': 'normal'},
            {'address': 'aa:bb:cc:dd:ee:22', 'vnic_type': 'normal'},
        ]

        # First run the CNA update, then the CNA create.
        mock_new_cna = mock.Mock(spec=pvm_net.CNA)
        mock_plug.side_effect = ['upd_cna', mock_new_cna]

        # Run method
        p_vifs = tf_net.PlugVifs(mock.MagicMock(), self.apt, inst, net_info)

        all_cnas = p_vifs.execute(self.mock_lpar_wrap)

        # new vif should be created twice.
        mock_plug.assert_any_call(self.apt, inst, net_info[0], new_vif=False)
        mock_plug.assert_any_call(self.apt, inst, net_info[1], new_vif=True)

        # The Task provides the list of original CNAs plus only CNAs that were
        # created.
        self.assertEqual(pre_cnas + [mock_new_cna], all_cnas)

        # Validate args on taskflow.task.Task instantiation
        with mock.patch('taskflow.task.Task.__init__') as tf:
            tf_net.PlugVifs(mock.MagicMock(), self.apt, inst, net_info)
        tf.assert_called_once_with(
            name='plug_vifs', provides='vm_cnas', requires=['lpar_wrap'])

    @mock.patch('nova.virt.powervm.vif.plug')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_plug_vifs_rmc_no_create(self, mock_vm_get, mock_plug):
        """Verifies if no creates are needed, none are done."""
        inst = powervm.TEST_INSTANCE

        # Mock up the CNA response.  Both should already exist.
        mock_vm_get.return_value = [cna('AABBCCDDEEFF'), cna('AABBCCDDEE11')]

        # Mock up the network info.  This also validates that they will be
        # sanitized to upper case.  This also validates that we don't call
        # get_vnics if no nets have vnic_type 'direct'.
        net_info = [
            {'address': 'aa:bb:cc:dd:ee:ff', 'vnic_type': 'normal'},
            {'address': 'aa:bb:cc:dd:ee:11', 'vnic_type': 'normal'}
        ]

        # Run method
        p_vifs = tf_net.PlugVifs(mock.MagicMock(), self.apt, inst, net_info)
        p_vifs.execute(self.mock_lpar_wrap)

        # The create should have been called with new_vif as False.
        mock_plug.assert_any_call(self.apt, inst, net_info[0], new_vif=False)
        mock_plug.assert_any_call(self.apt, inst, net_info[1], new_vif=False)

    @mock.patch('nova.virt.powervm.vif.plug')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_plug_vifs_invalid_state(self, mock_vm_get, mock_plug):
        """Tests that a crt_vif fails when the LPAR state is bad."""
        inst = powervm.TEST_INSTANCE

        # Mock up the CNA response.  Only doing one for simplicity
        mock_vm_get.return_value = []
        net_info = [{'address': 'aa:bb:cc:dd:ee:ff', 'vnic_type': 'normal'}]

        # Mock that the state is incorrect
        self.mock_lpar_wrap.can_modify_io.return_value = False, 'bad'

        # Run method
        p_vifs = tf_net.PlugVifs(mock.MagicMock(), self.apt, inst, net_info)
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          p_vifs.execute, self.mock_lpar_wrap)

        # The create should not have been invoked
        self.assertEqual(0, mock_plug.call_count)

    @mock.patch('nova.virt.powervm.vif.plug')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_plug_vifs_timeout(self, mock_vm_get, mock_plug):
        """Tests that crt vif failure via loss of neutron callback."""
        inst = powervm.TEST_INSTANCE

        # Mock up the CNA response.  Only doing one for simplicity
        mock_vm_get.return_value = [cna('AABBCCDDEE11')]

        # Mock up the network info.
        net_info = [{'address': 'aa:bb:cc:dd:ee:ff', 'vnic_type': 'normal'}]

        # Ensure that an exception is raised by a timeout.
        mock_plug.side_effect = eventlet.timeout.Timeout()

        # Run method
        p_vifs = tf_net.PlugVifs(mock.MagicMock(), self.apt, inst, net_info)
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          p_vifs.execute, self.mock_lpar_wrap)

        # The create should have only been called once.
        self.assertEqual(1, mock_plug.call_count)

    @mock.patch('nova.virt.powervm.vif.unplug')
    @mock.patch('nova.virt.powervm.vif.plug')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_plug_vifs_revert(self, mock_vm_get, mock_plug, mock_unplug):
        """Tests that the revert flow works properly."""
        inst = powervm.TEST_INSTANCE

        # Fake CNA list.  The one pre-existing VIF should *not* get reverted.
        cna_list = [cna('AABBCCDDEEFF'), cna('FFEEDDCCBBAA')]
        mock_vm_get.return_value = cna_list

        # Mock up the network info.  Three roll backs.
        net_info = [
            {'address': 'aa:bb:cc:dd:ee:ff', 'vnic_type': 'normal'},
            {'address': 'aa:bb:cc:dd:ee:22', 'vnic_type': 'normal'},
            {'address': 'aa:bb:cc:dd:ee:33', 'vnic_type': 'normal'}
        ]

        # Make sure we test raising an exception
        mock_unplug.side_effect = [exception.NovaException(), None]

        # Run method
        p_vifs = tf_net.PlugVifs(mock.MagicMock(), self.apt, inst, net_info)
        p_vifs.execute(self.mock_lpar_wrap)
        p_vifs.revert(self.mock_lpar_wrap, mock.Mock(), mock.Mock())

        # The unplug should be called twice.  The exception shouldn't stop the
        # second call.
        self.assertEqual(2, mock_unplug.call_count)

        # Make sure each call is invoked correctly.  The first plug was not a
        # new vif, so it should not be reverted.
        c2 = mock.call(self.apt, inst, net_info[1], cna_w_list=cna_list)
        c3 = mock.call(self.apt, inst, net_info[2], cna_w_list=cna_list)
        mock_unplug.assert_has_calls([c2, c3])

    @mock.patch('pypowervm.tasks.cna.crt_cna')
    @mock.patch('pypowervm.wrappers.network.VSwitch.search')
    @mock.patch('nova.virt.powervm.vif.plug')
    @mock.patch('nova.virt.powervm.vm.get_cnas')
    def test_plug_mgmt_vif(self, mock_vm_get, mock_plug, mock_vs_search,
                           mock_crt_cna):
        """Tests that a mgmt vif can be created."""
        inst = powervm.TEST_INSTANCE

        # Mock up the rmc vswitch
        vswitch_w = mock.MagicMock()
        vswitch_w.href = 'fake_mgmt_uri'
        mock_vs_search.return_value = [vswitch_w]

        # Run method such that it triggers a fresh CNA search
        p_vifs = tf_net.PlugMgmtVif(self.apt, inst)
        p_vifs.execute(None)

        # With the default get_cnas mock (which returns a Mock()), we think we
        # found an existing management CNA.
        mock_crt_cna.assert_not_called()
        mock_vm_get.assert_called_once_with(
            self.apt, inst, vswitch_uri='fake_mgmt_uri')

        # Now mock get_cnas to return no hits
        mock_vm_get.reset_mock()
        mock_vm_get.return_value = []
        p_vifs.execute(None)

        # Get was called; and since it didn't have the mgmt CNA, so was plug.
        self.assertEqual(1, mock_crt_cna.call_count)
        mock_vm_get.assert_called_once_with(
            self.apt, inst, vswitch_uri='fake_mgmt_uri')

        # Now pass CNAs, but not the mgmt vif, "from PlugVifs"
        cnas = [mock.Mock(vswitch_uri='uri1'), mock.Mock(vswitch_uri='uri2')]
        mock_crt_cna.reset_mock()
        mock_vm_get.reset_mock()
        p_vifs.execute(cnas)

        # Get wasn't called, since the CNAs were passed "from PlugVifs"; but
        # since the mgmt vif wasn't included, plug was called.
        mock_vm_get.assert_not_called()
        mock_crt_cna.assert_called()

        # Finally, pass CNAs including the mgmt.
        cnas.append(mock.Mock(vswitch_uri='fake_mgmt_uri'))
        mock_crt_cna.reset_mock()
        p_vifs.execute(cnas)

        # Neither get nor plug was called.
        mock_vm_get.assert_not_called()
        mock_crt_cna.assert_not_called()

        # Validate args on taskflow.task.Task instantiation
        with mock.patch('taskflow.task.Task.__init__') as tf:
            tf_net.PlugMgmtVif(self.apt, inst)
        tf.assert_called_once_with(
            name='plug_mgmt_vif', provides='mgmt_cna', requires=['vm_cnas'])

    def test_get_vif_events(self):
        # Set up common mocks.
        inst = powervm.TEST_INSTANCE
        net_info = [mock.MagicMock(), mock.MagicMock()]
        net_info[0]['id'] = 'a'
        net_info[0].get.return_value = False
        net_info[1]['id'] = 'b'
        net_info[1].get.return_value = True

        # Set up the runner.
        p_vifs = tf_net.PlugVifs(mock.MagicMock(), self.apt, inst, net_info)
        p_vifs.crt_network_infos = net_info
        resp = p_vifs._get_vif_events()

        # Only one should be returned since only one was active.
        self.assertEqual(1, len(resp))
