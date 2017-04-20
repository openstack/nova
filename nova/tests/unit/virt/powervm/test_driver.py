# Copyright 2017 IBM Corp.
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
from pypowervm.helpers import log_helper as pvm_hlp_log
from pypowervm.helpers import vios_busy as pvm_hlp_vbusy
from pypowervm.wrappers import managed_system as pvm_ms

from nova.compute import power_state
from nova import test
from nova.virt import hardware
from nova.virt.powervm import driver


class TestPowerVMDriver(test.NoDBTestCase):

    def setUp(self):
        super(TestPowerVMDriver, self).setUp()
        self.drv = driver.PowerVMDriver('virtapi')

    @mock.patch('pypowervm.adapter.Adapter', autospec=True)
    @mock.patch('pypowervm.adapter.Session', autospec=True)
    @mock.patch('pypowervm.tasks.partition.validate_vios_ready', autospec=True)
    @mock.patch('pypowervm.wrappers.managed_system.System', autospec=True)
    def test_init_host(self, mock_sys, mock_vvr, mock_sess, mock_adp):
        mock_sys.get.return_value = ['host_wrapper']
        self.drv.init_host('host')
        mock_sess.assert_called_once_with(conn_tries=60)
        mock_adp.assert_called_once_with(
            mock_sess.return_value, helpers=[
                pvm_hlp_log.log_helper, pvm_hlp_vbusy.vios_busy_retry_helper])
        mock_vvr.assert_called_once_with(mock_adp.return_value)
        self.assertEqual('host_wrapper', self.drv.host_wrapper)

    def test_get_info(self):
        info = self.drv.get_info('inst')
        self.assertIsInstance(info, hardware.InstanceInfo)
        self.assertEqual(power_state.NOSTATE, info.state)

    def test_list_instances(self):
        self.assertEqual([], self.drv.list_instances())

    def test_get_available_nodes(self):
        self.drv.host_wrapper = mock.create_autospec(pvm_ms.System,
                                                     instance=True)
        self.assertEqual([self.drv.host_wrapper.mtms.mtms_str],
                         self.drv.get_available_nodes('node'))

    @mock.patch('pypowervm.wrappers.managed_system.System', autospec=True)
    @mock.patch('nova.virt.powervm.host.build_host_resource_from_ms')
    def test_get_available_resource(self, mock_bhrfm, mock_sys):
        mock_sys.get.return_value = ['sys']
        self.drv.adapter = 'adap'
        mock_bhrfm.return_value = {'foo': 'bar'}
        self.assertEqual(
            {'foo': 'bar', 'local_gb': 100000, 'local_gb_used': 10},
            self.drv.get_available_resource('node'))
        mock_sys.get.assert_called_once_with('adap')
        mock_bhrfm.assert_called_once_with('sys')
        self.assertEqual('sys', self.drv.host_wrapper)

    def test_spawn(self):
        # TODO(efried): Real UT once spawn is implemented.
        inst = mock.Mock()
        self.drv.spawn('ctx', inst, 'img_meta', 'inj_files', 'admin_pass')
        self.drv.spawn('ctx', inst, 'img_meta', 'inj_files', 'admin_pass',
                       network_info='net_info', block_device_info='bdm')

    def test_destroy(self):
        # TODO(efried): Real UT once destroy is implemented.
        inst = mock.Mock()
        self.drv.destroy('ctx', inst, 'net_info')
        self.drv.destroy('ctx', inst, 'net_info', block_device_info='bdm',
                         destroy_disks=False, migrate_data='mig_data')
