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
from pypowervm import const as pvm_const
from pypowervm import exceptions as pvm_exc
from pypowervm.helpers import log_helper as pvm_hlp_log
from pypowervm.helpers import vios_busy as pvm_hlp_vbusy
from pypowervm.utils import transaction as pvm_tx
from pypowervm.wrappers import virtual_io_server as pvm_vios

from nova import exception
from nova import test
from nova.tests.unit.virt import powervm
from nova.virt import hardware
from nova.virt.powervm.disk import ssp
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

        self.pwron = self.useFixture(fixtures.MockPatch(
            'nova.virt.powervm.vm.power_on')).mock
        self.pwroff = self.useFixture(fixtures.MockPatch(
            'nova.virt.powervm.vm.power_off')).mock

        # Create an instance to test with
        self.inst = powervm.TEST_INSTANCE

    @mock.patch('nova.image.API')
    @mock.patch('pypowervm.tasks.storage.ComprehensiveScrub', autospec=True)
    @mock.patch('nova.virt.powervm.disk.ssp.SSPDiskAdapter')
    @mock.patch('pypowervm.wrappers.managed_system.System', autospec=True)
    @mock.patch('pypowervm.tasks.partition.validate_vios_ready', autospec=True)
    def test_init_host(self, mock_vvr, mock_sys, mock_ssp, mock_scrub,
                       mock_img):
        mock_hostw = mock.Mock(uuid='uuid')
        mock_sys.get.return_value = [mock_hostw]
        self.drv.init_host('host')
        self.sess.assert_called_once_with(conn_tries=60)
        self.adp.assert_called_once_with(
            self.sess.return_value, helpers=[
                pvm_hlp_log.log_helper, pvm_hlp_vbusy.vios_busy_retry_helper])
        mock_vvr.assert_called_once_with(self.drv.adapter)
        mock_sys.get.assert_called_once_with(self.drv.adapter)
        self.assertEqual(mock_hostw, self.drv.host_wrapper)
        mock_scrub.assert_called_once_with(self.drv.adapter)
        mock_scrub.return_value.execute.assert_called_once_with()
        mock_ssp.assert_called_once_with(self.drv.adapter, 'uuid')
        self.assertEqual(mock_ssp.return_value, self.drv.disk_dvr)
        mock_img.assert_called_once_with()
        self.assertEqual(mock_img.return_value, self.drv.image_api)

    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid')
    @mock.patch('nova.virt.powervm.vm.get_vm_qp')
    @mock.patch('nova.virt.powervm.vm._translate_vm_state')
    def test_get_info(self, mock_tx_state, mock_qp, mock_uuid):
        mock_tx_state.return_value = 'fake-state'
        self.assertEqual(hardware.InstanceInfo('fake-state'),
                         self.drv.get_info('inst'))
        mock_uuid.assert_called_once_with('inst')
        mock_qp.assert_called_once_with(
            self.drv.adapter, mock_uuid.return_value, 'PartitionState')
        mock_tx_state.assert_called_once_with(mock_qp.return_value)

    @mock.patch('nova.virt.powervm.vm.get_lpar_names')
    def test_list_instances(self, mock_names):
        mock_names.return_value = ['one', 'two', 'three']
        self.assertEqual(['one', 'two', 'three'], self.drv.list_instances())
        mock_names.assert_called_once_with(self.adp)

    def test_get_available_nodes(self):
        self.flags(host='hostname')
        self.assertEqual(['hostname'], self.drv.get_available_nodes('node'))

    @mock.patch('pypowervm.wrappers.managed_system.System', autospec=True)
    @mock.patch('nova.virt.powervm.host.build_host_resource_from_ms')
    def test_get_available_resource(self, mock_bhrfm, mock_sys):
        mock_sys.get.return_value = ['sys']
        mock_bhrfm.return_value = {'foo': 'bar'}
        self.drv.disk_dvr = mock.create_autospec(ssp.SSPDiskAdapter,
                                                 instance=True)
        self.assertEqual(
            {'foo': 'bar', 'local_gb': self.drv.disk_dvr.capacity,
             'local_gb_used': self.drv.disk_dvr.capacity_used},
            self.drv.get_available_resource('node'))
        mock_sys.get.assert_called_once_with(self.adp)
        mock_bhrfm.assert_called_once_with('sys')
        self.assertEqual('sys', self.drv.host_wrapper)

    @mock.patch('nova.virt.powervm.tasks.network.PlugMgmtVif.execute')
    @mock.patch('nova.virt.powervm.tasks.network.PlugVifs.execute')
    @mock.patch('nova.virt.powervm.media.ConfigDrivePowerVM')
    @mock.patch('nova.virt.configdrive.required_by')
    @mock.patch('nova.virt.powervm.vm.create_lpar')
    @mock.patch('pypowervm.tasks.partition.build_active_vio_feed_task',
                autospec=True)
    @mock.patch('pypowervm.tasks.storage.add_lpar_storage_scrub_tasks',
                autospec=True)
    def test_spawn_ops(self, mock_scrub, mock_bldftsk, mock_crt_lpar,
                       mock_cdrb, mock_cfg_drv, mock_plug_vifs,
                       mock_plug_mgmt_vif):
        """Validates the 'typical' spawn flow of the spawn of an instance. """
        mock_cdrb.return_value = True
        self.drv.host_wrapper = mock.Mock()
        self.drv.disk_dvr = mock.create_autospec(ssp.SSPDiskAdapter,
                                                 instance=True)
        mock_ftsk = pvm_tx.FeedTask('fake', [mock.Mock(spec=pvm_vios.VIOS)])
        mock_bldftsk.return_value = mock_ftsk
        self.drv.spawn('context', self.inst, 'img_meta', 'files', 'password',
                       'allocs', network_info='netinfo')
        mock_crt_lpar.assert_called_once_with(
            self.adp, self.drv.host_wrapper, self.inst)
        mock_bldftsk.assert_called_once_with(
            self.adp, xag={pvm_const.XAG.VIO_SMAP, pvm_const.XAG.VIO_FMAP})
        self.assertTrue(mock_plug_vifs.called)
        self.assertTrue(mock_plug_mgmt_vif.called)
        mock_scrub.assert_called_once_with(
            [mock_crt_lpar.return_value.id], mock_ftsk, lpars_exist=True)
        self.drv.disk_dvr.create_disk_from_image.assert_called_once_with(
            'context', self.inst, 'img_meta')
        self.drv.disk_dvr.attach_disk.assert_called_once_with(
            self.inst, self.drv.disk_dvr.create_disk_from_image.return_value,
            mock_ftsk)
        mock_cfg_drv.assert_called_once_with(self.adp)
        mock_cfg_drv.return_value.create_cfg_drv_vopt.assert_called_once_with(
            self.inst, 'files', 'netinfo', mock_ftsk, admin_pass='password',
            mgmt_cna=mock.ANY)
        self.pwron.assert_called_once_with(self.adp, self.inst)

        mock_cfg_drv.reset_mock()

        # No config drive
        mock_cdrb.return_value = False
        self.drv.spawn('context', self.inst, 'img_meta', 'files', 'password',
                       'allocs')
        mock_cfg_drv.assert_not_called()

    @mock.patch('nova.virt.powervm.tasks.network.UnplugVifs.execute')
    @mock.patch('nova.virt.powervm.vm.delete_lpar')
    @mock.patch('nova.virt.powervm.media.ConfigDrivePowerVM')
    @mock.patch('nova.virt.configdrive.required_by')
    @mock.patch('pypowervm.tasks.partition.build_active_vio_feed_task',
                autospec=True)
    def test_destroy(self, mock_bldftsk, mock_cdrb, mock_cfgdrv,
                     mock_dlt_lpar, mock_unplug):
        """Validates PowerVM destroy."""
        self.drv.host_wrapper = mock.Mock()
        self.drv.disk_dvr = mock.create_autospec(ssp.SSPDiskAdapter,
                                                 instance=True)

        mock_ftsk = pvm_tx.FeedTask('fake', [mock.Mock(spec=pvm_vios.VIOS)])
        mock_bldftsk.return_value = mock_ftsk

        # Good path, with config drive, destroy disks
        mock_cdrb.return_value = True
        self.drv.destroy('context', self.inst, [], block_device_info={})
        self.pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=True)
        mock_bldftsk.assert_called_once_with(
            self.adp, xag=[pvm_const.XAG.VIO_SMAP])
        mock_unplug.assert_called_once()
        mock_cdrb.assert_called_once_with(self.inst)
        mock_cfgdrv.assert_called_once_with(self.adp)
        mock_cfgdrv.return_value.dlt_vopt.assert_called_once_with(
            self.inst, stg_ftsk=mock_bldftsk.return_value)
        self.drv.disk_dvr.detach_disk.assert_called_once_with(
            self.inst)
        self.drv.disk_dvr.delete_disks.assert_called_once_with(
            self.drv.disk_dvr.detach_disk.return_value)
        mock_dlt_lpar.assert_called_once_with(self.adp, self.inst)

        self.pwroff.reset_mock()
        mock_bldftsk.reset_mock()
        mock_unplug.reset_mock()
        mock_cdrb.reset_mock()
        mock_cfgdrv.reset_mock()
        self.drv.disk_dvr.detach_disk.reset_mock()
        self.drv.disk_dvr.delete_disks.reset_mock()
        mock_dlt_lpar.reset_mock()

        # No config drive, preserve disks
        mock_cdrb.return_value = False
        self.drv.destroy('context', self.inst, [], block_device_info={},
                         destroy_disks=False)
        mock_cfgdrv.return_value.dlt_vopt.assert_not_called()
        self.drv.disk_dvr.delete_disks.assert_not_called()

        # Non-forced power_off, since preserving disks
        self.pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=False)
        mock_bldftsk.assert_called_once_with(
            self.adp, xag=[pvm_const.XAG.VIO_SMAP])
        mock_unplug.assert_called_once()
        mock_cdrb.assert_called_once_with(self.inst)
        mock_cfgdrv.assert_not_called()
        mock_cfgdrv.return_value.dlt_vopt.assert_not_called()
        self.drv.disk_dvr.detach_disk.assert_called_once_with(
            self.inst)
        self.drv.disk_dvr.delete_disks.assert_not_called()
        mock_dlt_lpar.assert_called_once_with(self.adp, self.inst)

        self.pwroff.reset_mock()
        mock_bldftsk.reset_mock()
        mock_unplug.reset_mock()
        mock_cdrb.reset_mock()
        mock_cfgdrv.reset_mock()
        self.drv.disk_dvr.detach_disk.reset_mock()
        self.drv.disk_dvr.delete_disks.reset_mock()
        mock_dlt_lpar.reset_mock()

        # InstanceNotFound exception, non-forced
        self.pwroff.side_effect = exception.InstanceNotFound(
            instance_id='something')
        self.drv.destroy('context', self.inst, [], block_device_info={},
                         destroy_disks=False)
        self.pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=False)
        self.drv.disk_dvr.detach_disk.assert_not_called()
        mock_unplug.assert_not_called()
        self.drv.disk_dvr.delete_disks.assert_not_called()
        mock_dlt_lpar.assert_not_called()

        self.pwroff.reset_mock()
        self.pwroff.side_effect = None
        mock_unplug.reset_mock()

        # Convertible (PowerVM) exception
        mock_dlt_lpar.side_effect = pvm_exc.TimeoutError("Timed out")
        self.assertRaises(exception.InstanceTerminationFailure,
                          self.drv.destroy, 'context', self.inst, [],
                          block_device_info={})

        # Everything got called
        self.pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=True)
        mock_unplug.assert_called_once()
        self.drv.disk_dvr.detach_disk.assert_called_once_with(self.inst)
        self.drv.disk_dvr.delete_disks.assert_called_once_with(
            self.drv.disk_dvr.detach_disk.return_value)
        mock_dlt_lpar.assert_called_once_with(self.adp, self.inst)

        # Other random exception raises directly
        mock_dlt_lpar.side_effect = ValueError()
        self.assertRaises(ValueError,
                          self.drv.destroy, 'context', self.inst, [],
                          block_device_info={})

    def test_power_on(self):
        self.drv.power_on('context', self.inst, 'network_info')
        self.pwron.assert_called_once_with(self.adp, self.inst)

    def test_power_off(self):
        self.drv.power_off(self.inst)
        self.pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=True, timeout=None)

    def test_power_off_timeout(self):
        # Long timeout (retry interval means nothing on powervm)
        self.drv.power_off(self.inst, timeout=500, retry_interval=10)
        self.pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=False, timeout=500)

    @mock.patch('nova.virt.powervm.vm.reboot')
    def test_reboot_soft(self, mock_reboot):
        inst = mock.Mock()
        self.drv.reboot('context', inst, 'network_info', 'SOFT')
        mock_reboot.assert_called_once_with(self.adp, inst, False)

    @mock.patch('nova.virt.powervm.vm.reboot')
    def test_reboot_hard(self, mock_reboot):
        inst = mock.Mock()
        self.drv.reboot('context', inst, 'network_info', 'HARD')
        mock_reboot.assert_called_once_with(self.adp, inst, True)

    @mock.patch('pypowervm.tasks.vterm.open_remotable_vnc_vterm',
                autospec=True)
    @mock.patch('nova.virt.powervm.vm.get_pvm_uuid',
                new=mock.Mock(return_value='uuid'))
    def test_get_vnc_console(self, mock_vterm):
        # Success
        mock_vterm.return_value = '10'
        resp = self.drv.get_vnc_console(mock.ANY, self.inst)
        self.assertEqual('127.0.0.1', resp.host)
        self.assertEqual('10', resp.port)
        self.assertEqual('uuid', resp.internal_access_path)
        mock_vterm.assert_called_once_with(
            mock.ANY, 'uuid', mock.ANY, vnc_path='uuid')

        # VNC failure - exception is raised directly
        mock_vterm.side_effect = pvm_exc.VNCBasedTerminalFailedToOpen(err='xx')
        self.assertRaises(pvm_exc.VNCBasedTerminalFailedToOpen,
                          self.drv.get_vnc_console, mock.ANY, self.inst)

        # 404
        mock_vterm.side_effect = pvm_exc.HttpError(mock.Mock(status=404))
        self.assertRaises(exception.InstanceNotFound, self.drv.get_vnc_console,
                          mock.ANY, self.inst)

    def test_deallocate_networks_on_reschedule(self):
        candeallocate = self.drv.deallocate_networks_on_reschedule(mock.Mock())
        self.assertTrue(candeallocate)
