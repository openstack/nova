# Copyright 2016, 2018 IBM Corp.
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
import contextlib

import fixtures
import mock
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from pypowervm import const as pvm_const
from pypowervm import exceptions as pvm_exc
from pypowervm.helpers import log_helper as pvm_hlp_log
from pypowervm.helpers import vios_busy as pvm_hlp_vbusy
from pypowervm.utils import transaction as pvm_tx
from pypowervm.wrappers import virtual_io_server as pvm_vios
import six

from nova import block_device as nova_block_device
from nova.compute import provider_tree
from nova import conf as cfg
from nova import exception
from nova.objects import block_device as bdmobj
from nova import test
from nova.tests.unit.virt import powervm
from nova.virt import block_device as nova_virt_bdm
from nova.virt import driver as nova_driver
from nova.virt.driver import ComputeDriver
from nova.virt import hardware
from nova.virt.powervm.disk import ssp
from nova.virt.powervm import driver

CONF = cfg.CONF


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

    def test_driver_capabilities(self):
        """Test the driver capabilities."""
        # check that the driver reports all capabilities
        self.assertEqual(set(ComputeDriver.capabilities),
                         set(self.drv.capabilities))
        # check the values for each capability
        self.assertFalse(self.drv.capabilities['has_imagecache'])
        self.assertFalse(self.drv.capabilities['supports_evacuate'])
        self.assertFalse(
            self.drv.capabilities['supports_migrate_to_same_host'])
        self.assertTrue(self.drv.capabilities['supports_attach_interface'])
        self.assertFalse(self.drv.capabilities['supports_device_tagging'])
        self.assertFalse(
            self.drv.capabilities['supports_tagged_attach_interface'])
        self.assertFalse(
            self.drv.capabilities['supports_tagged_attach_volume'])
        self.assertTrue(self.drv.capabilities['supports_extend_volume'])
        self.assertFalse(self.drv.capabilities['supports_multiattach'])

    @mock.patch('nova.image.glance.API')
    @mock.patch('pypowervm.tasks.storage.ComprehensiveScrub', autospec=True)
    @mock.patch('oslo_utils.importutils.import_object_ns', autospec=True)
    @mock.patch('pypowervm.wrappers.managed_system.System', autospec=True)
    @mock.patch('pypowervm.tasks.partition.validate_vios_ready', autospec=True)
    def test_init_host(self, mock_vvr, mock_sys, mock_import, mock_scrub,
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
        mock_import.assert_called_once_with(
            'nova.virt.powervm.disk', 'localdisk.LocalStorage',
            self.drv.adapter, 'uuid')
        self.assertEqual(mock_import.return_value, self.drv.disk_dvr)
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

    @contextlib.contextmanager
    def _update_provider_tree(self, allocations=None):
        """Host resource dict gets converted properly to provider tree inv."""

        with mock.patch('nova.virt.powervm.host.'
                        'build_host_resource_from_ms') as mock_bhrfm:
            mock_bhrfm.return_value = {
                'vcpus': 8,
                'memory_mb': 2048,
            }
            self.drv.host_wrapper = 'host_wrapper'
            # Validate that this gets converted to int with floor
            self.drv.disk_dvr = mock.Mock(capacity=2091.8)
            exp_inv = {
                'VCPU': {
                    'total': 8,
                    'max_unit': 8,
                    'allocation_ratio': 16.0,
                    'reserved': 0,
                },
                'MEMORY_MB': {
                    'total': 2048,
                    'max_unit': 2048,
                    'allocation_ratio': 1.5,
                    'reserved': 512,
                },
                'DISK_GB': {
                    'total': 2091,
                    'max_unit': 2091,
                    'allocation_ratio': 1.0,
                    'reserved': 0,
                },
            }
            ptree = provider_tree.ProviderTree()
            ptree.new_root('compute_host', uuids.cn)
            # Let the caller muck with these
            yield ptree, exp_inv
            self.drv.update_provider_tree(ptree, 'compute_host',
                                          allocations=allocations)
            self.assertEqual(exp_inv, ptree.data('compute_host').inventory)
            mock_bhrfm.assert_called_once_with('host_wrapper')

    def test_update_provider_tree(self):
        # Basic: no inventory already on the provider, no extra providers, no
        # aggregates or traits.
        with self._update_provider_tree():
            pass

    def test_update_provider_tree_ignore_allocations(self):
        with self._update_provider_tree(allocations="This is ignored"):
            pass

    def test_update_provider_tree_conf_overrides(self):
        # Non-default CONF values for allocation ratios and reserved.
        self.flags(cpu_allocation_ratio=12.3,
                   reserved_host_cpus=4,
                   ram_allocation_ratio=4.5,
                   reserved_host_memory_mb=32,
                   disk_allocation_ratio=6.7,
                   # This gets int(ceil)'d
                   reserved_host_disk_mb=5432.1)
        with self._update_provider_tree() as (_, exp_inv):
            exp_inv['VCPU']['allocation_ratio'] = 12.3
            exp_inv['VCPU']['reserved'] = 4
            exp_inv['MEMORY_MB']['allocation_ratio'] = 4.5
            exp_inv['MEMORY_MB']['reserved'] = 32
            exp_inv['DISK_GB']['allocation_ratio'] = 6.7
            exp_inv['DISK_GB']['reserved'] = 6

    def test_update_provider_tree_complex_ptree(self):
        # Overrides inventory already on the provider; leaves other providers
        # and aggregates/traits alone.
        with self._update_provider_tree() as (ptree, exp_inv):
            ptree.update_inventory('compute_host', {
                # these should get blown away
                'VCPU': {
                    'total': 16,
                    'max_unit': 2,
                    'allocation_ratio': 1.0,
                    'reserved': 10,
                },
                'CUSTOM_BOGUS': {
                    'total': 1234,
                }
            })
            ptree.update_aggregates('compute_host',
                                    [uuids.ss_agg, uuids.other_agg])
            ptree.update_traits('compute_host', ['CUSTOM_FOO', 'CUSTOM_BAR'])
            ptree.new_root('ssp', uuids.ssp)
            ptree.update_inventory('ssp', {'sentinel': 'inventory',
                                           'for': 'ssp'})
            ptree.update_aggregates('ssp', [uuids.ss_agg])
            ptree.new_child('sriov', 'compute_host', uuid=uuids.sriov)
            # Since CONF.cpu_allocation_ratio is not set and this is not
            # the initial upt call (so CONF.initial_cpu_allocation_ratio would
            # be used), the existing allocation ratio value from the tree is
            # used.
            exp_inv['VCPU']['allocation_ratio'] = 1.0

        # Make sure the compute's agg and traits were left alone
        cndata = ptree.data('compute_host')
        self.assertEqual(set([uuids.ss_agg, uuids.other_agg]),
                         cndata.aggregates)
        self.assertEqual(set(['CUSTOM_FOO', 'CUSTOM_BAR']), cndata.traits)
        # And the other providers were left alone
        self.assertEqual(set([uuids.cn, uuids.ssp, uuids.sriov]),
                         set(ptree.get_provider_uuids()))
        # ...including the ssp's aggregates
        self.assertEqual(set([uuids.ss_agg]), ptree.data('ssp').aggregates)

    @mock.patch('nova.virt.powervm.tasks.storage.AttachVolume.execute')
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
                       mock_plug_mgmt_vif, mock_attach_vol):
        """Validates the 'typical' spawn flow of the spawn of an instance. """
        mock_cdrb.return_value = True
        self.drv.host_wrapper = mock.Mock()
        self.drv.disk_dvr = mock.create_autospec(ssp.SSPDiskAdapter,
                                                 instance=True)
        mock_ftsk = pvm_tx.FeedTask('fake', [mock.Mock(spec=pvm_vios.VIOS)])
        mock_bldftsk.return_value = mock_ftsk
        block_device_info = self._fake_bdms()
        self.drv.spawn('context', self.inst, 'img_meta', 'files', 'password',
                       'allocs', network_info='netinfo',
                       block_device_info=block_device_info)
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
        self.assertEqual(2, mock_attach_vol.call_count)
        mock_cfg_drv.assert_called_once_with(self.adp)
        mock_cfg_drv.return_value.create_cfg_drv_vopt.assert_called_once_with(
            self.inst, 'files', 'netinfo', mock_ftsk, admin_pass='password',
            mgmt_cna=mock.ANY)
        self.pwron.assert_called_once_with(self.adp, self.inst)

        mock_cfg_drv.reset_mock()
        mock_attach_vol.reset_mock()

        # No config drive, no bdms
        mock_cdrb.return_value = False
        self.drv.spawn('context', self.inst, 'img_meta', 'files', 'password',
                       'allocs')
        mock_cfg_drv.assert_not_called()
        mock_attach_vol.assert_not_called()

    @mock.patch('nova.virt.powervm.tasks.storage.DetachVolume.execute')
    @mock.patch('nova.virt.powervm.tasks.network.UnplugVifs.execute')
    @mock.patch('nova.virt.powervm.vm.delete_lpar')
    @mock.patch('nova.virt.powervm.media.ConfigDrivePowerVM')
    @mock.patch('nova.virt.configdrive.required_by')
    @mock.patch('pypowervm.tasks.partition.build_active_vio_feed_task',
                autospec=True)
    def test_destroy(self, mock_bldftsk, mock_cdrb, mock_cfgdrv,
                     mock_dlt_lpar, mock_unplug, mock_detach_vol):
        """Validates PowerVM destroy."""
        self.drv.host_wrapper = mock.Mock()
        self.drv.disk_dvr = mock.create_autospec(ssp.SSPDiskAdapter,
                                                 instance=True)

        mock_ftsk = pvm_tx.FeedTask('fake', [mock.Mock(spec=pvm_vios.VIOS)])
        mock_bldftsk.return_value = mock_ftsk
        block_device_info = self._fake_bdms()

        # Good path, with config drive, destroy disks
        mock_cdrb.return_value = True
        self.drv.destroy('context', self.inst, [],
                         block_device_info=block_device_info)
        self.pwroff.assert_called_once_with(
            self.adp, self.inst, force_immediate=True)
        mock_bldftsk.assert_called_once_with(
            self.adp, xag=[pvm_const.XAG.VIO_SMAP])
        mock_unplug.assert_called_once()
        mock_cdrb.assert_called_once_with(self.inst)
        mock_cfgdrv.assert_called_once_with(self.adp)
        mock_cfgdrv.return_value.dlt_vopt.assert_called_once_with(
            self.inst, stg_ftsk=mock_bldftsk.return_value)
        self.assertEqual(2, mock_detach_vol.call_count)
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
        mock_detach_vol.reset_mock()
        mock_dlt_lpar.reset_mock()

        # No config drive, preserve disks, no block device info
        mock_cdrb.return_value = False
        self.drv.destroy('context', self.inst, [], block_device_info={},
                         destroy_disks=False)
        mock_cfgdrv.return_value.dlt_vopt.assert_not_called()
        mock_detach_vol.assert_not_called()
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

    @mock.patch('nova.virt.powervm.tasks.image.UpdateTaskState.'
                'execute', autospec=True)
    @mock.patch('nova.virt.powervm.tasks.storage.InstanceDiskToMgmt.'
                'execute', autospec=True)
    @mock.patch('nova.virt.powervm.tasks.image.StreamToGlance.execute')
    @mock.patch('nova.virt.powervm.tasks.storage.RemoveInstanceDiskFromMgmt.'
                'execute')
    def test_snapshot(self, mock_rm, mock_stream, mock_conn, mock_update):
        self.drv.disk_dvr = mock.Mock()
        self.drv.image_api = mock.Mock()
        mock_conn.return_value = 'stg_elem', 'vios_wrap', 'disk_path'
        self.drv.snapshot('context', self.inst, 'image_id',
                          'update_task_state')
        self.assertEqual(2, mock_update.call_count)
        self.assertEqual(1, mock_conn.call_count)
        mock_stream.assert_called_once_with(disk_path='disk_path')
        mock_rm.assert_called_once_with(
            stg_elem='stg_elem', vios_wrap='vios_wrap', disk_path='disk_path')

        self.drv.disk_dvr.capabilities = {'snapshot': False}
        self.assertRaises(exception.NotSupportedWithOption, self.drv.snapshot,
                         'context', self.inst, 'image_id', 'update_task_state')

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

    @mock.patch('nova.virt.powervm.driver.PowerVMDriver.plug_vifs')
    def test_attach_interface(self, mock_plug_vifs):
        self.drv.attach_interface('context', 'inst', 'image_meta', 'vif')
        mock_plug_vifs.assert_called_once_with('inst', ['vif'])

    @mock.patch('nova.virt.powervm.driver.PowerVMDriver.unplug_vifs')
    def test_detach_interface(self, mock_unplug_vifs):
        self.drv.detach_interface('context', 'inst', 'vif')
        mock_unplug_vifs.assert_called_once_with('inst', ['vif'])

    @mock.patch('nova.virt.powervm.tasks.vm.Get', autospec=True)
    @mock.patch('nova.virt.powervm.tasks.base.run', autospec=True)
    @mock.patch('nova.virt.powervm.tasks.network.PlugVifs', autospec=True)
    @mock.patch('taskflow.patterns.linear_flow.Flow', autospec=True)
    def test_plug_vifs(self, mock_tf, mock_plug_vifs, mock_tf_run, mock_get):
        # Successful plug
        mock_inst = mock.Mock()
        self.drv.plug_vifs(mock_inst, 'net_info')
        mock_get.assert_called_once_with(self.adp, mock_inst)
        mock_plug_vifs.assert_called_once_with(
            self.drv.virtapi, self.adp, mock_inst, 'net_info')
        add_calls = [mock.call(mock_get.return_value),
                     mock.call(mock_plug_vifs.return_value)]
        mock_tf.return_value.add.assert_has_calls(add_calls)
        mock_tf_run.assert_called_once_with(
            mock_tf.return_value, instance=mock_inst)

        # InstanceNotFound and generic exception both raise
        mock_tf_run.side_effect = exception.InstanceNotFound('id')
        exc = self.assertRaises(exception.VirtualInterfacePlugException,
                                self.drv.plug_vifs, mock_inst, 'net_info')
        self.assertIn('instance', six.text_type(exc))
        mock_tf_run.side_effect = Exception
        exc = self.assertRaises(exception.VirtualInterfacePlugException,
                                self.drv.plug_vifs, mock_inst, 'net_info')
        self.assertIn('unexpected', six.text_type(exc))

    @mock.patch('nova.virt.powervm.tasks.base.run', autospec=True)
    @mock.patch('nova.virt.powervm.tasks.network.UnplugVifs', autospec=True)
    @mock.patch('taskflow.patterns.linear_flow.Flow', autospec=True)
    def test_unplug_vifs(self, mock_tf, mock_unplug_vifs, mock_tf_run):
        # Successful unplug
        mock_inst = mock.Mock()
        self.drv.unplug_vifs(mock_inst, 'net_info')
        mock_unplug_vifs.assert_called_once_with(self.adp, mock_inst,
                                                 'net_info')
        mock_tf.return_value.add.assert_called_once_with(
            mock_unplug_vifs.return_value)
        mock_tf_run.assert_called_once_with(mock_tf.return_value,
                                            instance=mock_inst)

        # InstanceNotFound should pass
        mock_tf_run.side_effect = exception.InstanceNotFound(instance_id='1')
        self.drv.unplug_vifs(mock_inst, 'net_info')

        # Raise InterfaceDetachFailed otherwise
        mock_tf_run.side_effect = Exception
        self.assertRaises(exception.InterfaceDetachFailed,
                          self.drv.unplug_vifs, mock_inst, 'net_info')

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

    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter')
    def test_attach_volume(self, mock_vscsi_adpt):
        """Validates the basic PowerVM attach volume."""
        # BDMs
        mock_bdm = self._fake_bdms()['block_device_mapping'][0]

        with mock.patch.object(self.inst, 'save') as mock_save:
            # Invoke the method.
            self.drv.attach_volume('context', mock_bdm.get('connection_info'),
                                   self.inst, mock.sentinel.stg_ftsk)

        # Verify the connect volume was invoked
        mock_vscsi_adpt.return_value.attach_volume.assert_called_once_with()
        mock_save.assert_called_once_with()

    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter')
    def test_detach_volume(self, mock_vscsi_adpt):
        """Validates the basic PowerVM detach volume."""
        # BDMs
        mock_bdm = self._fake_bdms()['block_device_mapping'][0]

        # Invoke the method, good path test.
        self.drv.detach_volume('context', mock_bdm.get('connection_info'),
                               self.inst, mock.sentinel.stg_ftsk)
        # Verify the disconnect volume was invoked
        mock_vscsi_adpt.return_value.detach_volume.assert_called_once_with()

    @mock.patch('nova.virt.powervm.volume.fcvscsi.FCVscsiVolumeAdapter')
    def test_extend_volume(self, mock_vscsi_adpt):
        mock_bdm = self._fake_bdms()['block_device_mapping'][0]
        self.drv.extend_volume(
            'context', mock_bdm.get('connection_info'), self.inst, 0)
        mock_vscsi_adpt.return_value.extend_volume.assert_called_once_with()

    def test_vol_drv_iter(self):
        block_device_info = self._fake_bdms()
        bdms = nova_driver.block_device_info_get_mapping(block_device_info)
        vol_adpt = mock.Mock()

        def _get_results(bdms):
            # Patch so we get the same mock back each time.
            with mock.patch('nova.virt.powervm.volume.fcvscsi.'
                            'FCVscsiVolumeAdapter', return_value=vol_adpt):
                return [
                    (bdm, vol_drv) for bdm, vol_drv in self.drv._vol_drv_iter(
                        'context', self.inst, bdms)]

        results = _get_results(bdms)
        self.assertEqual(
            'fake_vol1',
            results[0][0]['connection_info']['data']['volume_id'])
        self.assertEqual(vol_adpt, results[0][1])
        self.assertEqual(
            'fake_vol2',
            results[1][0]['connection_info']['data']['volume_id'])
        self.assertEqual(vol_adpt, results[1][1])

        # Test with empty bdms
        self.assertEqual([], _get_results([]))

    @staticmethod
    def _fake_bdms():
        def _fake_bdm(volume_id, target_lun):
            connection_info = {'driver_volume_type': 'fibre_channel',
                               'data': {'volume_id': volume_id,
                                        'target_lun': target_lun,
                                        'initiator_target_map':
                                        {'21000024F5': ['50050768']}}}
            mapping_dict = {'source_type': 'volume', 'volume_id': volume_id,
                            'destination_type': 'volume',
                            'connection_info':
                            jsonutils.dumps(connection_info),
                            }
            bdm_dict = nova_block_device.BlockDeviceDict(mapping_dict)
            bdm_obj = bdmobj.BlockDeviceMapping(**bdm_dict)

            return nova_virt_bdm.DriverVolumeBlockDevice(bdm_obj)

        bdm_list = [_fake_bdm('fake_vol1', 0), _fake_bdm('fake_vol2', 1)]
        block_device_info = {'block_device_mapping': bdm_list}

        return block_device_info

    @mock.patch('nova.virt.powervm.volume.fcvscsi.wwpns', autospec=True)
    def test_get_volume_connector(self, mock_wwpns):
        vol_connector = self.drv.get_volume_connector(mock.Mock())
        self.assertEqual(mock_wwpns.return_value, vol_connector['wwpns'])
        self.assertFalse(vol_connector['multipath'])
        self.assertEqual(vol_connector['host'], CONF.host)
        self.assertIsNone(vol_connector['initiator'])
