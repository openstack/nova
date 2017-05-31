# Copyright 2015, 2017 IBM Corp.
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
from taskflow import engines as tf_eng
from taskflow.patterns import linear_flow as tf_lf
from taskflow import task as tf_tsk

from nova import exception
from nova import test
from nova.virt.powervm.tasks import vm as tf_vm


class TestVMTasks(test.TestCase):
    def setUp(self):
        super(TestVMTasks, self).setUp()
        self.apt = mock.Mock()
        self.instance = mock.Mock()

    @mock.patch('pypowervm.tasks.storage.add_lpar_storage_scrub_tasks',
                autospec=True)
    @mock.patch('nova.virt.powervm.vm.create_lpar')
    def test_create(self, mock_vm_crt, mock_stg):
        lpar_entry = mock.Mock()

        # Test create with normal (non-recreate) ftsk
        crt = tf_vm.Create(self.apt, 'host_wrapper', self.instance, 'ftsk')
        mock_vm_crt.return_value = lpar_entry
        crt.execute()

        mock_vm_crt.assert_called_once_with(self.apt, 'host_wrapper',
                                            self.instance)

        mock_stg.assert_called_once_with(
            [lpar_entry.id], 'ftsk', lpars_exist=True)
        mock_stg.assert_called_once_with([mock_vm_crt.return_value.id], 'ftsk',
                                         lpars_exist=True)

    @mock.patch('nova.virt.powervm.vm.power_on')
    def test_power_on(self, mock_pwron):
        pwron = tf_vm.PowerOn(self.apt, self.instance)
        pwron.execute()
        mock_pwron.assert_called_once_with(self.apt, self.instance)

    @mock.patch('nova.virt.powervm.vm.power_on')
    @mock.patch('nova.virt.powervm.vm.power_off')
    def test_power_on_revert(self, mock_pwroff, mock_pwron):
        flow = tf_lf.Flow('revert_power_on')
        pwron = tf_vm.PowerOn(self.apt, self.instance)
        flow.add(pwron)

        # Dummy Task that fails, triggering flow revert
        def failure(*a, **k):
            raise ValueError()
        flow.add(tf_tsk.FunctorTask(failure))

        # When PowerOn.execute doesn't fail, revert calls power_off
        self.assertRaises(ValueError, tf_eng.run, flow)
        mock_pwron.assert_called_once_with(self.apt, self.instance)
        mock_pwroff.assert_called_once_with(self.apt, self.instance,
                                            force_immediate=True)

        mock_pwron.reset_mock()
        mock_pwroff.reset_mock()

        # When PowerOn.execute fails, revert doesn't call power_off
        mock_pwron.side_effect = exception.NovaException()
        self.assertRaises(exception.NovaException, tf_eng.run, flow)
        mock_pwron.assert_called_once_with(self.apt, self.instance)
        mock_pwroff.assert_not_called()

    @mock.patch('nova.virt.powervm.vm.power_off')
    def test_power_off(self, mock_pwroff):
        # Default force_immediate
        pwroff = tf_vm.PowerOff(self.apt, self.instance)
        pwroff.execute()
        mock_pwroff.assert_called_once_with(self.apt, self.instance,
                                            force_immediate=False)

        mock_pwroff.reset_mock()

        # Explicit force_immediate
        pwroff = tf_vm.PowerOff(self.apt, self.instance, force_immediate=True)
        pwroff.execute()
        mock_pwroff.assert_called_once_with(self.apt, self.instance,
                                            force_immediate=True)

    @mock.patch('nova.virt.powervm.vm.delete_lpar')
    def test_delete(self, mock_dlt):
        delete = tf_vm.Delete(self.apt, self.instance)
        delete.execute()
        mock_dlt.assert_called_once_with(self.apt, self.instance)
