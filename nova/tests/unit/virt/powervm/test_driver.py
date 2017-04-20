# Copyright 2016, 2017 IBM Corp.
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

from __future__ import absolute_import

import fixtures
import mock
from pypowervm import exceptions as pvm_exc
from pypowervm.helpers import log_helper as pvm_hlp_log
from pypowervm.helpers import vios_busy as pvm_hlp_vbusy
from pypowervm.wrappers import managed_system as pvm_ms

from nova import exception
from nova import test
from nova.tests.unit.virt import powervm
from nova.virt import hardware
from nova.virt.powervm import driver


class TestPowerVMDriver(test.NoDBTestCase):

    def setUp(self):
        super(TestPowerVMDriver, self).setUp()
        self.drv = driver.PowerVMDriver('virtapi')
        self.adp = self.useFixture(fixtures.MockPatch(
            'pypowervm.adapter.Adapter', autospec=True)).mock
        self.drv.adapter = self.adp
        self.sess = self.useFixture(fixtures.MockPatch(
            'pypowervm.adapter.Session', autospec=True)).mock

        # Create an instance to test with
        self.inst = powervm.TEST_INSTANCE

    @mock.patch('pypowervm.wrappers.managed_system.System', autospec=True)
    @mock.patch('pypowervm.tasks.partition.validate_vios_ready', autospec=True)
    def test_init_host(self, mock_vvr, mock_sys):
        mock_sys.get.return_value = ['sys']
        self.drv.init_host('host')
        self.sess.assert_called_once_with(conn_tries=60)
        self.adp.assert_called_once_with(
            self.sess.return_value, helpers=[
                pvm_hlp_log.log_helper, pvm_hlp_vbusy.vios_busy_retry_helper])
        mock_vvr.assert_called_once_with(self.adp.return_value)
        self.assertEqual('sys', self.drv.host_wrapper)

    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
    def test_get_info(self, mock_uuid):
        mock_uuid.return_value = 'uuid'
        info = self.drv.get_info('inst')
        self.assertIsInstance(info, hardware.InstanceInfo)
        self.assertEqual('uuid', info.id)
        mock_uuid.assert_called_once_with('inst')

    @mock.patch('nova.virt.powervm.vm.get_lpar_names')
    def test_list_instances(self, mock_names):
        mock_names.return_value = ['one', 'two', 'three']
        self.assertEqual(['one', 'two', 'three'], self.drv.list_instances())
        mock_names.assert_called_once_with(self.adp)

    def test_get_available_nodes(self):
        self.drv.host_wrapper = mock.create_autospec(pvm_ms.System,
                                                     instance=True)
        self.assertEqual([self.drv.host_wrapper.mtms.mtms_str],
                         self.drv.get_available_nodes('node'))

    @mock.patch('pypowervm.wrappers.managed_system.System', autospec=True)
    @mock.patch('nova.virt.powervm.host.build_host_resource_from_ms')
    def test_get_available_resource(self, mock_bhrfm, mock_sys):
        mock_sys.get.return_value = ['sys']
        mock_bhrfm.return_value = {'foo': 'bar'}
        self.assertEqual(
            {'foo': 'bar', 'local_gb': 100000, 'local_gb_used': 10},
            self.drv.get_available_resource('node'))
        mock_sys.get.assert_called_once_with(self.adp)
        mock_bhrfm.assert_called_once_with('sys')
        self.assertEqual('sys', self.drv.host_wrapper)

    @mock.patch('nova.virt.powervm.vm.create_lpar')
    @mock.patch('nova.virt.powervm.vm.power_on')
    def test_spawn_ops(self, mock_pwron, mock_crt_lpar):
        """Validates the 'typical' spawn flow of the spawn of an instance. """
        self.drv.host_wrapper = 'sys'
        self.drv.spawn('context', self.inst, 'img_meta', 'files', 'password')
        mock_crt_lpar.assert_called_once_with(self.adp, 'sys', self.inst)
        mock_pwron.assert_called_once_with(self.adp, self.inst)

    @mock.patch('nova.virt.powervm.vm.delete_lpar')
    @mock.patch('nova.virt.powervm.vm.power_off')
    def test_destroy(self, mock_pwroff, mock_del):
        """Validates PowerVM destroy."""
        # Good path
        self.drv.destroy('context', self.inst, [], block_device_info={})
        mock_pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=True)
        mock_del.assert_called_once_with(self.adp, self.inst)

        mock_pwroff.reset_mock()
        mock_del.reset_mock()

        # InstanceNotFound exception, non-forced
        mock_pwroff.side_effect = exception.InstanceNotFound
        self.drv.destroy('context', self.inst, [], block_device_info={},
                         destroy_disks=False)
        mock_pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=False)
        mock_del.assert_not_called()

        mock_pwroff.reset_mock()
        mock_pwroff.side_effect = None

        # Convertible (PowerVM) exception
        mock_del.side_effect = pvm_exc.TimeoutError("Timed out")
        self.assertRaises(exception.InstanceTerminationFailure,
                          self.drv.destroy, 'context', self.inst, [],
                          block_device_info={})
        # Everything got called
        mock_pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=True)
        mock_del.assert_called_once_with(self.adp, self.inst)

        # Other random exception raises directly
        mock_del.side_effect = ValueError()
        self.assertRaises(ValueError,
                          self.drv.destroy, 'context', self.inst, [],
                          block_device_info={})
