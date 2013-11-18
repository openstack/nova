# vim: tabstop=4 shiftwidth=4 softtabstop=4

#  Copyright 2012 Cloudbase Solutions Srl
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

"""
Test suite for the Hyper-V driver and related APIs.
"""

import io
import mox
import os
import platform
import shutil
import time
import uuid

from oslo.config import cfg

from nova.api.metadata import base as instance_metadata
from nova.compute import power_state
from nova.compute import task_states
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova.openstack.common.gettextutils import _
from nova import test
from nova.tests import fake_network
from nova.tests.image import fake as fake_image
from nova.tests import matchers
from nova.tests.virt.hyperv import db_fakes
from nova.tests.virt.hyperv import fake
from nova import utils
from nova.virt import configdrive
from nova.virt import driver
from nova.virt.hyperv import basevolumeutils
from nova.virt.hyperv import constants
from nova.virt.hyperv import driver as driver_hyperv
from nova.virt.hyperv import hostutils
from nova.virt.hyperv import livemigrationutils
from nova.virt.hyperv import networkutils
from nova.virt.hyperv import networkutilsv2
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import utilsfactory
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vhdutilsv2
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import vmutilsv2
from nova.virt.hyperv import volumeutils
from nova.virt.hyperv import volumeutilsv2
from nova.virt import images

CONF = cfg.CONF
CONF.import_opt('vswitch_name', 'nova.virt.hyperv.vif', 'hyperv')


class HyperVAPITestCase(test.NoDBTestCase):
    """Unit tests for Hyper-V driver calls."""

    def __init__(self, test_case_name):
        self._mox = mox.Mox()
        super(HyperVAPITestCase, self).__init__(test_case_name)

    def setUp(self):
        super(HyperVAPITestCase, self).setUp()

        self._user_id = 'fake'
        self._project_id = 'fake'
        self._instance_data = None
        self._image_metadata = None
        self._fetched_image = None
        self._update_image_raise_exception = False
        self._volume_target_portal = 'testtargetportal:3260'
        self._volume_id = '0ef5d708-45ab-4129-8c59-d774d2837eb7'
        self._context = context.RequestContext(self._user_id, self._project_id)
        self._instance_ide_disks = []
        self._instance_ide_dvds = []
        self._instance_volume_disks = []
        self._test_vm_name = None
        self._test_instance_dir = 'C:\\FakeInstancesPath\\instance-0000001'
        self._check_min_windows_version_satisfied = True

        self._setup_stubs()

        self.flags(instances_path=r'C:\Hyper-V\test\instances',
                   network_api_class='nova.network.neutronv2.api.API')
        self.flags(force_volumeutils_v1=True, group='hyperv')
        self.flags(force_hyperv_utils_v1=True, group='hyperv')

        self._conn = driver_hyperv.HyperVDriver(None)

    def _setup_stubs(self):
        db_fakes.stub_out_db_instance_api(self.stubs)
        fake_image.stub_out_image_service(self.stubs)
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)

        def fake_fetch(context, image_id, target, user, project):
            self._fetched_image = target
        self.stubs.Set(images, 'fetch', fake_fetch)

        def fake_get_remote_image_service(context, name):
            class FakeGlanceImageService(object):
                def update(self_fake, context, image_id, image_metadata, f):
                    if self._update_image_raise_exception:
                        raise vmutils.HyperVException(
                            "Simulated update failure")
                    self._image_metadata = image_metadata
            return (FakeGlanceImageService(), 1)
        self.stubs.Set(glance, 'get_remote_image_service',
                       fake_get_remote_image_service)

        def fake_check_min_windows_version(fake_self, major, minor):
            return self._check_min_windows_version_satisfied
        self.stubs.Set(hostutils.HostUtils, 'check_min_windows_version',
                       fake_check_min_windows_version)

        def fake_sleep(ms):
            pass
        self.stubs.Set(time, 'sleep', fake_sleep)

        def fake_vmutils__init__(self, host='.'):
            pass
        vmutils.VMUtils.__init__ = fake_vmutils__init__

        self.stubs.Set(pathutils, 'PathUtils', fake.PathUtils)
        self._mox.StubOutWithMock(fake.PathUtils, 'open')
        self._mox.StubOutWithMock(fake.PathUtils, 'copyfile')
        self._mox.StubOutWithMock(fake.PathUtils, 'rmtree')
        self._mox.StubOutWithMock(fake.PathUtils, 'copy')
        self._mox.StubOutWithMock(fake.PathUtils, 'remove')
        self._mox.StubOutWithMock(fake.PathUtils, 'rename')
        self._mox.StubOutWithMock(fake.PathUtils, 'makedirs')
        self._mox.StubOutWithMock(fake.PathUtils,
                                  'get_instance_migr_revert_dir')
        self._mox.StubOutWithMock(fake.PathUtils, 'get_instance_dir')

        self._mox.StubOutWithMock(vmutils.VMUtils, 'vm_exists')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_vm')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'destroy_vm')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'attach_ide_drive')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_scsi_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_nic')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'set_vm_state')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'list_instances')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_summary_info')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'take_vm_snapshot')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'remove_vm_snapshot')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'set_nic_connection')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_scsi_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_ide_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_attached_disks_count')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'attach_volume_to_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'get_mounted_disk_by_drive_number')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'detach_vm_disk')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_storage_paths')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'get_controller_volume_paths')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'enable_vm_metrics_collection')

        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'create_differencing_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'reconnect_parent_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'merge_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'get_vhd_parent_path')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'get_vhd_info')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'resize_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils,
                                  'get_internal_vhd_size_by_file_size')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'validate_vhd')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'get_vhd_format')
        self._mox.StubOutWithMock(vhdutils.VHDUtils, 'create_dynamic_vhd')

        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_cpus_info')
        self._mox.StubOutWithMock(hostutils.HostUtils,
                                  'is_cpu_feature_present')
        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_memory_info')
        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_volume_info')
        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_windows_version')
        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_local_ips')

        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'get_external_vswitch')
        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'create_vswitch_port')
        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'vswitch_port_needed')

        self._mox.StubOutWithMock(livemigrationutils.LiveMigrationUtils,
                                  'live_migrate_vm')
        self._mox.StubOutWithMock(livemigrationutils.LiveMigrationUtils,
                                  'check_live_migration_config')

        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'volume_in_mapping')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_session_id_from_mounted_disk')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_device_number_for_target')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_target_from_disk_path')

        self._mox.StubOutWithMock(volumeutils.VolumeUtils,
                                  'login_storage_target')
        self._mox.StubOutWithMock(volumeutils.VolumeUtils,
                                  'logout_storage_target')
        self._mox.StubOutWithMock(volumeutils.VolumeUtils,
                                  'execute_log_out')
        self._mox.StubOutWithMock(volumeutils.VolumeUtils,
                                  'get_iscsi_initiator')

        self._mox.StubOutWithMock(volumeutilsv2.VolumeUtilsV2,
                                  'login_storage_target')
        self._mox.StubOutWithMock(volumeutilsv2.VolumeUtilsV2,
                                  'logout_storage_target')
        self._mox.StubOutWithMock(volumeutilsv2.VolumeUtilsV2,
                                  'execute_log_out')

        self._mox.StubOutClassWithMocks(instance_metadata, 'InstanceMetadata')
        self._mox.StubOutWithMock(instance_metadata.InstanceMetadata,
                                  'metadata_for_config_drive')

        # Can't use StubOutClassWithMocks due to __exit__ and __enter__
        self._mox.StubOutWithMock(configdrive, 'ConfigDriveBuilder')
        self._mox.StubOutWithMock(configdrive.ConfigDriveBuilder, 'make_drive')

        self._mox.StubOutWithMock(utils, 'execute')

    def tearDown(self):
        self._mox.UnsetStubs()
        super(HyperVAPITestCase, self).tearDown()

    def test_get_available_resource(self):
        cpu_info = {'Architecture': 'fake',
                    'Name': 'fake',
                    'Manufacturer': 'ACME, Inc.',
                    'NumberOfCores': 2,
                    'NumberOfLogicalProcessors': 4}

        tot_mem_kb = 2000000L
        free_mem_kb = 1000000L

        tot_hdd_b = 4L * 1024 ** 3
        free_hdd_b = 3L * 1024 ** 3

        windows_version = '6.2.9200'

        hostutils.HostUtils.get_memory_info().AndReturn((tot_mem_kb,
                                                        free_mem_kb))

        m = hostutils.HostUtils.get_volume_info(mox.IsA(str))
        m.AndReturn((tot_hdd_b, free_hdd_b))

        hostutils.HostUtils.get_cpus_info().AndReturn([cpu_info])
        m = hostutils.HostUtils.is_cpu_feature_present(mox.IsA(int))
        m.MultipleTimes()

        m = hostutils.HostUtils.get_windows_version()
        m.AndReturn(windows_version)

        self._mox.ReplayAll()
        dic = self._conn.get_available_resource(None)
        self._mox.VerifyAll()

        self.assertEquals(dic['vcpus'], cpu_info['NumberOfLogicalProcessors'])
        self.assertEquals(dic['hypervisor_hostname'], platform.node())
        self.assertEquals(dic['memory_mb'], tot_mem_kb / 1024)
        self.assertEquals(dic['memory_mb_used'],
                          tot_mem_kb / 1024 - free_mem_kb / 1024)
        self.assertEquals(dic['local_gb'], tot_hdd_b / 1024 ** 3)
        self.assertEquals(dic['local_gb_used'],
                          tot_hdd_b / 1024 ** 3 - free_hdd_b / 1024 ** 3)
        self.assertEquals(dic['hypervisor_version'],
                          windows_version.replace('.', ''))
        self.assertEquals(dic['supported_instances'],
                '[["i686", "hyperv", "hvm"], ["x86_64", "hyperv", "hvm"]]')

    def test_get_host_stats(self):
        tot_mem_kb = 2000000L
        free_mem_kb = 1000000L

        tot_hdd_b = 4L * 1024 ** 3
        free_hdd_b = 3L * 1024 ** 3

        hostutils.HostUtils.get_memory_info().AndReturn((tot_mem_kb,
                                                        free_mem_kb))

        m = hostutils.HostUtils.get_volume_info(mox.IsA(str))
        m.AndReturn((tot_hdd_b, free_hdd_b))

        self._mox.ReplayAll()
        dic = self._conn.get_host_stats(True)
        self._mox.VerifyAll()

        self.assertEquals(dic['disk_total'], tot_hdd_b / 1024 ** 3)
        self.assertEquals(dic['disk_available'], free_hdd_b / 1024 ** 3)

        self.assertEquals(dic['host_memory_total'], tot_mem_kb / 1024)
        self.assertEquals(dic['host_memory_free'], free_mem_kb / 1024)

        self.assertEquals(dic['disk_total'],
                          dic['disk_used'] + dic['disk_available'])
        self.assertEquals(dic['host_memory_total'],
                          dic['host_memory_overhead'] +
                          dic['host_memory_free'])

    def test_list_instances(self):
        fake_instances = ['fake1', 'fake2']
        vmutils.VMUtils.list_instances().AndReturn(fake_instances)

        self._mox.ReplayAll()
        instances = self._conn.list_instances()
        self._mox.VerifyAll()

        self.assertEquals(instances, fake_instances)

    def test_get_info(self):
        self._instance_data = self._get_instance_data()

        summary_info = {'NumberOfProcessors': 2,
                        'EnabledState': constants.HYPERV_VM_STATE_ENABLED,
                        'MemoryUsage': 1000,
                        'UpTime': 1}

        m = vmutils.VMUtils.vm_exists(mox.Func(self._check_instance_name))
        m.AndReturn(True)

        func = mox.Func(self._check_instance_name)
        m = vmutils.VMUtils.get_vm_summary_info(func)
        m.AndReturn(summary_info)

        self._mox.ReplayAll()
        info = self._conn.get_info(self._instance_data)
        self._mox.VerifyAll()

        self.assertEquals(info["state"], power_state.RUNNING)

    def test_get_info_instance_not_found(self):
        # Tests that InstanceNotFound is raised if the instance isn't found
        # from the vmutils.vm_exists method.
        self._instance_data = self._get_instance_data()

        m = vmutils.VMUtils.vm_exists(mox.Func(self._check_instance_name))
        m.AndReturn(False)

        self._mox.ReplayAll()
        self.assertRaises(exception.InstanceNotFound, self._conn.get_info,
                          self._instance_data)
        self._mox.VerifyAll()

    def test_spawn_cow_image(self):
        self._test_spawn_instance(True)

    def test_spawn_cow_image_vhdx(self):
        self._test_spawn_instance(True, vhd_format=constants.DISK_FORMAT_VHDX)

    def test_spawn_no_cow_image(self):
        self._test_spawn_instance(False)

    def test_spawn_dynamic_memory(self):
        CONF.set_override('dynamic_memory_ratio', 2.0, 'hyperv')
        self._test_spawn_instance()

    def test_spawn_no_cow_image_vhdx(self):
        self._test_spawn_instance(False, vhd_format=constants.DISK_FORMAT_VHDX)

    def _setup_spawn_config_drive_mocks(self, use_cdrom):
        im = instance_metadata.InstanceMetadata(mox.IgnoreArg(),
                                                content=mox.IsA(list),
                                                extra_md=mox.IsA(dict))

        m = fake.PathUtils.get_instance_dir(mox.IsA(str))
        m.AndReturn(self._test_instance_dir)

        cdb = self._mox.CreateMockAnything()
        m = configdrive.ConfigDriveBuilder(instance_md=mox.IgnoreArg())
        m.AndReturn(cdb)
        # __enter__ and __exit__ are required by "with"
        cdb.__enter__().AndReturn(cdb)
        cdb.make_drive(mox.IsA(str))
        cdb.__exit__(None, None, None).AndReturn(None)

        if not use_cdrom:
            utils.execute(CONF.hyperv.qemu_img_cmd,
                          'convert',
                          '-f',
                          'raw',
                          '-O',
                          'vpc',
                          mox.IsA(str),
                          mox.IsA(str),
                          attempts=1)
            fake.PathUtils.remove(mox.IsA(str))

        m = vmutils.VMUtils.attach_ide_drive(mox.IsA(str),
                                             mox.IsA(str),
                                             mox.IsA(int),
                                             mox.IsA(int),
                                             mox.IsA(str))
        m.WithSideEffects(self._add_ide_disk)

    def _test_spawn_config_drive(self, use_cdrom):
        self.flags(force_config_drive=True)
        self.flags(config_drive_cdrom=use_cdrom, group='hyperv')
        self.flags(mkisofs_cmd='mkisofs.exe')

        if use_cdrom:
            expected_ide_disks = 1
            expected_ide_dvds = 1
        else:
            expected_ide_disks = 2
            expected_ide_dvds = 0

        self._test_spawn_instance(expected_ide_disks=expected_ide_disks,
                                  expected_ide_dvds=expected_ide_dvds,
                                  config_drive=True,
                                  use_cdrom=use_cdrom)

    def test_spawn_config_drive(self):
        self._test_spawn_config_drive(False)

    def test_spawn_config_drive_cdrom(self):
        self._test_spawn_config_drive(True)

    def test_spawn_no_config_drive(self):
        self.flags(force_config_drive=False)

        expected_ide_disks = 1
        expected_ide_dvds = 0

        self._test_spawn_instance(expected_ide_disks=expected_ide_disks,
                                  expected_ide_dvds=expected_ide_dvds)

    def _test_spawn_nova_net_vif(self, with_port):
        self.flags(network_api_class='nova.network.api.API')
        # Reinstantiate driver, as the VIF plugin is loaded during __init__
        self._conn = driver_hyperv.HyperVDriver(None)

        def setup_vif_mocks():
            fake_vswitch_path = 'fake vswitch path'
            fake_vswitch_port = 'fake port'

            m = networkutils.NetworkUtils.get_external_vswitch(
                CONF.hyperv.vswitch_name)
            m.AndReturn(fake_vswitch_path)

            m = networkutils.NetworkUtils.vswitch_port_needed()
            m.AndReturn(with_port)

            if with_port:
                m = networkutils.NetworkUtils.create_vswitch_port(
                    fake_vswitch_path, mox.IsA(str))
                m.AndReturn(fake_vswitch_port)
                vswitch_conn_data = fake_vswitch_port
            else:
                vswitch_conn_data = fake_vswitch_path

            vmutils.VMUtils.set_nic_connection(mox.IsA(str), mox.IsA(str),
                                               vswitch_conn_data)

        self._test_spawn_instance(setup_vif_mocks_func=setup_vif_mocks)

    def test_spawn_nova_net_vif_with_port(self):
        self._test_spawn_nova_net_vif(True)

    def test_spawn_nova_net_vif_without_port(self):
        self._test_spawn_nova_net_vif(False)

    def test_spawn_nova_net_vif_no_vswitch_exception(self):
        self.flags(network_api_class='nova.network.api.API')
        # Reinstantiate driver, as the VIF plugin is loaded during __init__
        self._conn = driver_hyperv.HyperVDriver(None)

        def setup_vif_mocks():
            m = networkutils.NetworkUtils.get_external_vswitch(
                CONF.hyperv.vswitch_name)
            m.AndRaise(vmutils.HyperVException(_('fake vswitch not found')))

        self.assertRaises(vmutils.HyperVException, self._test_spawn_instance,
                          setup_vif_mocks_func=setup_vif_mocks,
                          with_exception=True)

    def test_spawn_with_metrics_collection(self):
        self.flags(enable_instance_metrics_collection=True, group='hyperv')
        self._test_spawn_instance(False)

    def test_spawn_with_ephemeral_storage(self):
        self._test_spawn_instance(True, expected_ide_disks=2,
                                  ephemeral_storage=True)

    def _check_instance_name(self, vm_name):
        return vm_name == self._instance_data['name']

    def _test_vm_state_change(self, action, from_state, to_state):
        self._instance_data = self._get_instance_data()

        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     to_state)

        self._mox.ReplayAll()
        action(self._instance_data)
        self._mox.VerifyAll()

    def test_pause(self):
        self._test_vm_state_change(self._conn.pause, None,
                                   constants.HYPERV_VM_STATE_PAUSED)

    def test_pause_already_paused(self):
        self._test_vm_state_change(self._conn.pause,
                                   constants.HYPERV_VM_STATE_PAUSED,
                                   constants.HYPERV_VM_STATE_PAUSED)

    def test_unpause(self):
        self._test_vm_state_change(self._conn.unpause,
                                   constants.HYPERV_VM_STATE_PAUSED,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_unpause_already_running(self):
        self._test_vm_state_change(self._conn.unpause, None,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_suspend(self):
        self._test_vm_state_change(self._conn.suspend, None,
                                   constants.HYPERV_VM_STATE_SUSPENDED)

    def test_suspend_already_suspended(self):
        self._test_vm_state_change(self._conn.suspend,
                                   constants.HYPERV_VM_STATE_SUSPENDED,
                                   constants.HYPERV_VM_STATE_SUSPENDED)

    def test_resume(self):
        self._test_vm_state_change(lambda i: self._conn.resume(i, None),
                                   constants.HYPERV_VM_STATE_SUSPENDED,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_resume_already_running(self):
        self._test_vm_state_change(lambda i: self._conn.resume(i, None), None,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_power_off(self):
        self._test_vm_state_change(self._conn.power_off, None,
                                   constants.HYPERV_VM_STATE_DISABLED)

    def test_power_off_already_powered_off(self):
        self._test_vm_state_change(self._conn.power_off,
                                   constants.HYPERV_VM_STATE_DISABLED,
                                   constants.HYPERV_VM_STATE_DISABLED)

    def test_power_on(self):
        self._instance_data = self._get_instance_data()
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)
        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     constants.HYPERV_VM_STATE_ENABLED)
        self._mox.ReplayAll()
        self._conn.power_on(self._context, self._instance_data, network_info)
        self._mox.VerifyAll()

    def test_power_on_already_running(self):
        self._instance_data = self._get_instance_data()
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)
        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     constants.HYPERV_VM_STATE_ENABLED)
        self._mox.ReplayAll()
        self._conn.power_on(self._context, self._instance_data, network_info)
        self._mox.VerifyAll()

    def test_reboot(self):

        network_info = fake_network.fake_get_instance_nw_info(self.stubs)
        self._instance_data = self._get_instance_data()

        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     constants.HYPERV_VM_STATE_REBOOT)

        self._mox.ReplayAll()
        self._conn.reboot(self._context, self._instance_data, network_info,
                          None)
        self._mox.VerifyAll()

    def _setup_destroy_mocks(self, destroy_disks=True):
        m = vmutils.VMUtils.vm_exists(mox.Func(self._check_instance_name))
        m.AndReturn(True)

        func = mox.Func(self._check_instance_name)
        vmutils.VMUtils.set_vm_state(func, constants.HYPERV_VM_STATE_DISABLED)

        m = vmutils.VMUtils.get_vm_storage_paths(func)
        m.AndReturn(([], []))

        vmutils.VMUtils.destroy_vm(func)

        if destroy_disks:
            m = fake.PathUtils.get_instance_dir(mox.IsA(str),
                                                create_dir=False,
                                                remove_dir=True)
            m.AndReturn(self._test_instance_dir)

    def test_destroy(self):
        self._instance_data = self._get_instance_data()

        self._setup_destroy_mocks()

        self._mox.ReplayAll()
        self._conn.destroy(self._instance_data, None)
        self._mox.VerifyAll()

    def test_live_migration_unsupported_os(self):
        self._check_min_windows_version_satisfied = False
        self._conn = driver_hyperv.HyperVDriver(None)
        self._test_live_migration(unsupported_os=True)

    def test_live_migration_without_volumes(self):
        self._test_live_migration()

    def test_live_migration_with_volumes(self):
        self._test_live_migration(with_volumes=True)

    def test_live_migration_with_target_failure(self):
        self._test_live_migration(test_failure=True)

    def _test_live_migration(self, test_failure=False,
                             with_volumes=False,
                             unsupported_os=False):
        dest_server = 'fake_server'

        instance_data = self._get_instance_data()
        instance_name = instance_data['name']

        fake_post_method = self._mox.CreateMockAnything()
        if not test_failure and not unsupported_os:
            fake_post_method(self._context, instance_data, dest_server,
                             False)

        fake_recover_method = self._mox.CreateMockAnything()
        if test_failure:
            fake_recover_method(self._context, instance_data, dest_server,
                                False)

        fake_ide_controller_path = 'fakeide'
        fake_scsi_controller_path = 'fakescsi'

        if with_volumes:
            fake_scsi_disk_path = 'fake_scsi_disk_path'
            fake_target_iqn = 'fake_target_iqn'
            fake_target_lun = 1
            fake_scsi_paths = {0: fake_scsi_disk_path}
        else:
            fake_scsi_paths = {}

        if not unsupported_os:
            m = livemigrationutils.LiveMigrationUtils.live_migrate_vm(
                instance_data['name'], dest_server)
            if test_failure:
                m.AndRaise(vmutils.HyperVException('Simulated failure'))

            if with_volumes:
                m.AndReturn([(fake_target_iqn, fake_target_lun)])
                volumeutils.VolumeUtils.logout_storage_target(fake_target_iqn)
            else:
                m.AndReturn([])

        self._mox.ReplayAll()
        try:
            hyperv_exception_raised = False
            unsupported_os_exception_raised = False
            self._conn.live_migration(self._context, instance_data,
                                      dest_server, fake_post_method,
                                      fake_recover_method)
        except vmutils.HyperVException:
            hyperv_exception_raised = True
        except NotImplementedError:
            unsupported_os_exception_raised = True

        self.assertTrue(not test_failure ^ hyperv_exception_raised)
        self.assertTrue(not unsupported_os ^ unsupported_os_exception_raised)
        self._mox.VerifyAll()

    def test_pre_live_migration_cow_image(self):
        self._test_pre_live_migration(True, False)

    def test_pre_live_migration_no_cow_image(self):
        self._test_pre_live_migration(False, False)

    def test_pre_live_migration_with_volumes(self):
        self._test_pre_live_migration(False, True)

    def _test_pre_live_migration(self, cow, with_volumes):
        self.flags(use_cow_images=cow)

        instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, instance_data)
        instance['system_metadata'] = {}

        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        m = livemigrationutils.LiveMigrationUtils.check_live_migration_config()
        m.AndReturn(True)

        if cow:
            m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(mox.IsA(str),
                                                                  None)
            m.AndReturn(False)

            self._setup_get_cached_image_mocks(cow)

        if with_volumes:
            block_device_info = db_fakes.get_fake_block_device_info(
                self._volume_target_portal, self._volume_id)

            mapping = driver.block_device_info_get_mapping(block_device_info)
            data = mapping[0]['connection_info']['data']
            target_lun = data['target_lun']
            target_iqn = data['target_iqn']
            target_portal = data['target_portal']

            fake_mounted_disk = "fake_mounted_disk"
            fake_device_number = 0

            self._mock_login_storage_target(target_iqn, target_lun,
                                            target_portal,
                                            fake_mounted_disk,
                                            fake_device_number)
        else:
            block_device_info = None

        self._mox.ReplayAll()
        self._conn.pre_live_migration(self._context, instance,
                                      block_device_info, None, network_info)
        self._mox.VerifyAll()

        if cow:
            self.assertTrue(self._fetched_image is not None)
        else:
            self.assertTrue(self._fetched_image is None)

    def test_snapshot_with_update_failure(self):
        (snapshot_name, func_call_matcher) = self._setup_snapshot_mocks()

        self._update_image_raise_exception = True

        self._mox.ReplayAll()
        self.assertRaises(vmutils.HyperVException, self._conn.snapshot,
                          self._context, self._instance_data, snapshot_name,
                          func_call_matcher.call)
        self._mox.VerifyAll()

        # Assert states changed in correct order
        self.assertIsNone(func_call_matcher.match())

    def _setup_snapshot_mocks(self):
        expected_calls = [
            {'args': (),
             'kwargs': {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs': {'task_state': task_states.IMAGE_UPLOADING,
                        'expected_state': task_states.IMAGE_PENDING_UPLOAD}}
        ]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        snapshot_name = 'test_snapshot_' + str(uuid.uuid4())

        fake_hv_snapshot_path = 'fake_snapshot_path'
        fake_parent_vhd_path = 'C:\\fake_vhd_path\\parent.vhd'

        self._instance_data = self._get_instance_data()

        func = mox.Func(self._check_instance_name)
        m = vmutils.VMUtils.take_vm_snapshot(func)
        m.AndReturn(fake_hv_snapshot_path)

        m = fake.PathUtils.get_instance_dir(mox.IsA(str))
        m.AndReturn(self._test_instance_dir)

        m = vhdutils.VHDUtils.get_vhd_parent_path(mox.IsA(str))
        m.AndReturn(fake_parent_vhd_path)

        self._fake_dest_disk_path = None

        def copy_dest_disk_path(src, dest):
            self._fake_dest_disk_path = dest

        m = fake.PathUtils.copyfile(mox.IsA(str), mox.IsA(str))
        m.WithSideEffects(copy_dest_disk_path)

        self._fake_dest_base_disk_path = None

        def copy_dest_base_disk_path(src, dest):
            self._fake_dest_base_disk_path = dest

        m = fake.PathUtils.copyfile(fake_parent_vhd_path, mox.IsA(str))
        m.WithSideEffects(copy_dest_base_disk_path)

        def check_dest_disk_path(path):
            return path == self._fake_dest_disk_path

        def check_dest_base_disk_path(path):
            return path == self._fake_dest_base_disk_path

        func1 = mox.Func(check_dest_disk_path)
        func2 = mox.Func(check_dest_base_disk_path)
        # Make sure that the hyper-v base and differential VHDs are merged
        vhdutils.VHDUtils.reconnect_parent_vhd(func1, func2)
        vhdutils.VHDUtils.merge_vhd(func1, func2)

        def check_snapshot_path(snapshot_path):
            return snapshot_path == fake_hv_snapshot_path

        # Make sure that the Hyper-V snapshot is removed
        func = mox.Func(check_snapshot_path)
        vmutils.VMUtils.remove_vm_snapshot(func)

        fake.PathUtils.rmtree(mox.IsA(str))

        m = fake.PathUtils.open(func2, 'rb')
        m.AndReturn(io.BytesIO(b'fake content'))

        return (snapshot_name, func_call_matcher)

    def test_snapshot(self):
        (snapshot_name, func_call_matcher) = self._setup_snapshot_mocks()

        self._mox.ReplayAll()
        self._conn.snapshot(self._context, self._instance_data, snapshot_name,
                            func_call_matcher.call)
        self._mox.VerifyAll()

        self.assertTrue(self._image_metadata and
                        "disk_format" in self._image_metadata and
                        self._image_metadata["disk_format"] == "vhd")

        # Assert states changed in correct order
        self.assertIsNone(func_call_matcher.match())

    def _get_instance_data(self):
        instance_name = 'openstack_unit_test_vm_' + str(uuid.uuid4())
        return db_fakes.get_fake_instance_data(instance_name,
                                               self._project_id,
                                               self._user_id)

    def _spawn_instance(self, cow, block_device_info=None,
                        ephemeral_storage=False):
        self.flags(use_cow_images=cow)

        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        instance['system_metadata'] = {}

        if ephemeral_storage:
            instance['ephemeral_gb'] = 1

        image = db_fakes.get_fake_image_data(self._project_id, self._user_id)

        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        self._conn.spawn(self._context, instance, image,
                         injected_files=[], admin_password=None,
                         network_info=network_info,
                         block_device_info=block_device_info)

    def _add_ide_disk(self, vm_name, path, ctrller_addr,
                      drive_addr, drive_type):
        if drive_type == constants.IDE_DISK:
            self._instance_ide_disks.append(path)
        elif drive_type == constants.IDE_DVD:
            self._instance_ide_dvds.append(path)

    def _add_volume_disk(self, vm_name, controller_path, address,
                         mounted_disk_path):
        self._instance_volume_disks.append(mounted_disk_path)

    def _check_img_path(self, image_path):
        return image_path == self._fetched_image

    def _setup_create_instance_mocks(self, setup_vif_mocks_func=None,
                                     boot_from_volume=False,
                                     block_device_info=None,
                                     admin_permissions=True,
                                     ephemeral_storage=False):
        vmutils.VMUtils.create_vm(mox.Func(self._check_vm_name), mox.IsA(int),
                                  mox.IsA(int), mox.IsA(bool),
                                  CONF.hyperv.dynamic_memory_ratio)

        if not boot_from_volume:
            m = vmutils.VMUtils.attach_ide_drive(mox.Func(self._check_vm_name),
                                                 mox.IsA(str),
                                                 mox.IsA(int),
                                                 mox.IsA(int),
                                                 mox.IsA(str))
            m.WithSideEffects(self._add_ide_disk).InAnyOrder()

        if ephemeral_storage:
            m = vmutils.VMUtils.attach_ide_drive(mox.Func(self._check_vm_name),
                                                 mox.IsA(str),
                                                 mox.IsA(int),
                                                 mox.IsA(int),
                                                 mox.IsA(str))
            m.WithSideEffects(self._add_ide_disk).InAnyOrder()

        func = mox.Func(self._check_vm_name)
        m = vmutils.VMUtils.create_scsi_controller(func)
        m.InAnyOrder()

        if boot_from_volume:
            mapping = driver.block_device_info_get_mapping(block_device_info)
            data = mapping[0]['connection_info']['data']
            target_lun = data['target_lun']
            target_iqn = data['target_iqn']
            target_portal = data['target_portal']

            self._mock_attach_volume(mox.Func(self._check_vm_name), target_iqn,
                                     target_lun, target_portal, True)

        vmutils.VMUtils.create_nic(mox.Func(self._check_vm_name), mox.IsA(str),
                                   mox.IsA(str)).InAnyOrder()

        if setup_vif_mocks_func:
            setup_vif_mocks_func()

        if CONF.hyperv.enable_instance_metrics_collection:
            vmutils.VMUtils.enable_vm_metrics_collection(
                mox.Func(self._check_vm_name))

    def _set_vm_name(self, vm_name):
        self._test_vm_name = vm_name

    def _check_vm_name(self, vm_name):
        return vm_name == self._test_vm_name

    def _setup_check_admin_permissions_mocks(self, admin_permissions=True):
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'check_admin_permissions')
        m = vmutils.VMUtils.check_admin_permissions()
        if admin_permissions:
            m.AndReturn(None)
        else:
            m.AndRaise(vmutils.HyperVAuthorizationException(_(
                                                'Simulated failure')))

    def _setup_get_cached_image_mocks(self, cow=True,
                                      vhd_format=constants.DISK_FORMAT_VHD):
        m = vhdutils.VHDUtils.get_vhd_format(
            mox.Func(self._check_img_path))
        m.AndReturn(vhd_format)

        def check_img_path_with_ext(image_path):
            return image_path == self._fetched_image + '.' + vhd_format.lower()

        fake.PathUtils.rename(mox.Func(self._check_img_path),
                              mox.Func(check_img_path_with_ext))

        if cow and vhd_format == constants.DISK_FORMAT_VHD:
            m = vhdutils.VHDUtils.get_vhd_info(
                mox.Func(check_img_path_with_ext))
            m.AndReturn({'MaxInternalSize': 1024})

            fake.PathUtils.copyfile(mox.IsA(str), mox.IsA(str))

            m = vhdutils.VHDUtils.get_internal_vhd_size_by_file_size(
                mox.IsA(str), mox.IsA(object))
            m.AndReturn(1025)

            vhdutils.VHDUtils.resize_vhd(mox.IsA(str), mox.IsA(object))

    def _setup_spawn_instance_mocks(self, cow, setup_vif_mocks_func=None,
                                    with_exception=False,
                                    block_device_info=None,
                                    boot_from_volume=False,
                                    config_drive=False,
                                    use_cdrom=False,
                                    admin_permissions=True,
                                    vhd_format=constants.DISK_FORMAT_VHD,
                                    ephemeral_storage=False):
        m = vmutils.VMUtils.vm_exists(mox.IsA(str))
        m.WithSideEffects(self._set_vm_name).AndReturn(False)

        m = fake.PathUtils.get_instance_dir(mox.IsA(str),
                                            create_dir=False,
                                            remove_dir=True)
        m.AndReturn(self._test_instance_dir)

        m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(
            mox.IsA(str), block_device_info)
        m.AndReturn(boot_from_volume)

        if not boot_from_volume:
            m = fake.PathUtils.get_instance_dir(mox.Func(self._check_vm_name))
            m.AndReturn(self._test_instance_dir)

            self._setup_get_cached_image_mocks(cow, vhd_format)

            if cow:
                vhdutils.VHDUtils.create_differencing_vhd(mox.IsA(str),
                                                          mox.IsA(str))
            else:
                fake.PathUtils.copyfile(mox.IsA(str), mox.IsA(str))
                m = vhdutils.VHDUtils.get_vhd_info(mox.IsA(str))
                m.AndReturn({'MaxInternalSize': 1024, 'FileSize': 1024,
                             'Type': 2})
                m = vhdutils.VHDUtils.get_internal_vhd_size_by_file_size(
                    mox.IsA(str), mox.IsA(object))
                m.AndReturn(1025)
                vhdutils.VHDUtils.resize_vhd(mox.IsA(str), mox.IsA(object))

        self._setup_check_admin_permissions_mocks(
                                          admin_permissions=admin_permissions)
        if ephemeral_storage:
            m = fake.PathUtils.get_instance_dir(mox.Func(self._check_vm_name))
            m.AndReturn(self._test_instance_dir)
            vhdutils.VHDUtils.create_dynamic_vhd(mox.IsA(str), mox.IsA(int),
                                                 mox.IsA(str))

        self._setup_create_instance_mocks(setup_vif_mocks_func,
                                          boot_from_volume,
                                          block_device_info,
                                          ephemeral_storage=ephemeral_storage)

        if config_drive:
            self._setup_spawn_config_drive_mocks(use_cdrom)

        # TODO(alexpilotti) Based on where the exception is thrown
        # some of the above mock calls need to be skipped
        if with_exception:
            self._setup_destroy_mocks()
        else:
            vmutils.VMUtils.set_vm_state(mox.Func(self._check_vm_name),
                                         constants.HYPERV_VM_STATE_ENABLED)

    def _test_spawn_instance(self, cow=True,
                             expected_ide_disks=1,
                             expected_ide_dvds=0,
                             setup_vif_mocks_func=None,
                             with_exception=False,
                             config_drive=False,
                             use_cdrom=False,
                             admin_permissions=True,
                             vhd_format=constants.DISK_FORMAT_VHD,
                             ephemeral_storage=False):
        self._setup_spawn_instance_mocks(cow,
                                         setup_vif_mocks_func,
                                         with_exception,
                                         config_drive=config_drive,
                                         use_cdrom=use_cdrom,
                                         admin_permissions=admin_permissions,
                                         vhd_format=vhd_format,
                                         ephemeral_storage=ephemeral_storage)

        self._mox.ReplayAll()
        self._spawn_instance(cow, ephemeral_storage=ephemeral_storage)
        self._mox.VerifyAll()

        self.assertEquals(len(self._instance_ide_disks), expected_ide_disks)
        self.assertEquals(len(self._instance_ide_dvds), expected_ide_dvds)

        vhd_path = os.path.join(self._test_instance_dir, 'root.' +
                                vhd_format.lower())
        self.assertEquals(vhd_path, self._instance_ide_disks[0])

    def _mock_get_mounted_disk_from_lun(self, target_iqn, target_lun,
                                        fake_mounted_disk,
                                        fake_device_number):
        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndReturn(fake_device_number)

        m = vmutils.VMUtils.get_mounted_disk_by_drive_number(
            fake_device_number)
        m.AndReturn(fake_mounted_disk)

    def _mock_login_storage_target(self, target_iqn, target_lun, target_portal,
                                   fake_mounted_disk, fake_device_number):
        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndReturn(fake_device_number)

        volumeutils.VolumeUtils.login_storage_target(target_lun,
                                                     target_iqn,
                                                     target_portal)

        self._mock_get_mounted_disk_from_lun(target_iqn, target_lun,
                                             fake_mounted_disk,
                                             fake_device_number)

    def _mock_attach_volume(self, instance_name, target_iqn, target_lun,
                            target_portal=None, boot_from_volume=False):
        fake_mounted_disk = "fake_mounted_disk"
        fake_device_number = 0
        fake_controller_path = 'fake_scsi_controller_path'

        self._mock_login_storage_target(target_iqn, target_lun,
                                        target_portal,
                                        fake_mounted_disk,
                                        fake_device_number)

        self._mock_get_mounted_disk_from_lun(target_iqn, target_lun,
                                             fake_mounted_disk,
                                             fake_device_number)

        if boot_from_volume:
            m = vmutils.VMUtils.get_vm_ide_controller(instance_name, 0)
            m.AndReturn(fake_controller_path)
            fake_free_slot = 0
        else:
            m = vmutils.VMUtils.get_vm_scsi_controller(instance_name)
            m.AndReturn(fake_controller_path)

            fake_free_slot = 1
            m = vmutils.VMUtils.get_attached_disks_count(fake_controller_path)
            m.AndReturn(fake_free_slot)

        m = vmutils.VMUtils.attach_volume_to_controller(instance_name,
                                                        fake_controller_path,
                                                        fake_free_slot,
                                                        fake_mounted_disk)
        m.WithSideEffects(self._add_volume_disk)

    def _test_util_class_version(self, v1_class, v2_class,
                                 get_instance_action, is_hyperv_2012,
                                 force_v1_flag, force_utils_v1):
        self._check_min_windows_version_satisfied = is_hyperv_2012
        CONF.set_override(force_v1_flag, force_v1_flag, 'hyperv')
        self._conn = driver_hyperv.HyperVDriver(None)

        instance = get_instance_action()
        is_v1 = isinstance(instance, v1_class)
        # v2_class can inherit from v1_class
        is_v2 = isinstance(instance, v2_class)

        self.assertTrue((is_hyperv_2012 and not force_v1_flag) ^
                        (is_v1 and not is_v2))

    def test_volumeutils_version_hyperv_2012(self):
        self._test_util_class_version(volumeutils.VolumeUtils,
                                      volumeutilsv2.VolumeUtilsV2,
                                      lambda: utilsfactory.get_volumeutils(),
                                      True, 'force_volumeutils_v1', False)

    def test_volumeutils_version_hyperv_2012_force_v1(self):
        self._test_util_class_version(volumeutils.VolumeUtils,
                                      volumeutilsv2.VolumeUtilsV2,
                                      lambda: utilsfactory.get_volumeutils(),
                                      True, 'force_volumeutils_v1', True)

    def test_volumeutils_version_hyperv_2008R2(self):
        self._test_util_class_version(volumeutils.VolumeUtils,
                                      volumeutilsv2.VolumeUtilsV2,
                                      lambda: utilsfactory.get_volumeutils(),
                                      False, 'force_volumeutils_v1', False)

    def test_vmutils_version_hyperv_2012(self):
        self._test_util_class_version(vmutils.VMUtils, vmutilsv2.VMUtilsV2,
                                      lambda: utilsfactory.get_vmutils(),
                                      True, 'force_hyperv_utils_v1', False)

    def test_vmutils_version_hyperv_2012_force_v1(self):
        self._test_util_class_version(vmutils.VMUtils, vmutilsv2.VMUtilsV2,
                                      lambda: utilsfactory.get_vmutils(),
                                      True, 'force_hyperv_utils_v1', True)

    def test_vmutils_version_hyperv_2008R2(self):
        self._test_util_class_version(vmutils.VMUtils, vmutilsv2.VMUtilsV2,
                                      lambda: utilsfactory.get_vmutils(),
                                      False, 'force_hyperv_utils_v1', False)

    def test_vhdutils_version_hyperv_2012(self):
        self._test_util_class_version(vhdutils.VHDUtils,
                                      vhdutilsv2.VHDUtilsV2,
                                      lambda: utilsfactory.get_vhdutils(),
                                      True, 'force_hyperv_utils_v1', False)

    def test_vhdutils_version_hyperv_2012_force_v1(self):
        self._test_util_class_version(vhdutils.VHDUtils,
                                      vhdutilsv2.VHDUtilsV2,
                                      lambda: utilsfactory.get_vhdutils(),
                                      True, 'force_hyperv_utils_v1', True)

    def test_vhdutils_version_hyperv_2008R2(self):
        self._test_util_class_version(vhdutils.VHDUtils,
                                      vhdutilsv2.VHDUtilsV2,
                                      lambda: utilsfactory.get_vhdutils(),
                                      False, 'force_hyperv_utils_v1', False)

    def test_networkutils_version_hyperv_2012(self):
        self._test_util_class_version(networkutils.NetworkUtils,
                                      networkutilsv2.NetworkUtilsV2,
                                      lambda: utilsfactory.get_networkutils(),
                                      True, 'force_hyperv_utils_v1', False)

    def test_networkutils_version_hyperv_2012_force_v1(self):
        self._test_util_class_version(networkutils.NetworkUtils,
                                      networkutilsv2.NetworkUtilsV2,
                                      lambda: utilsfactory.get_networkutils(),
                                      True, 'force_hyperv_utils_v1', True)

    def test_networkutils_version_hyperv_2008R2(self):
        self._test_util_class_version(networkutils.NetworkUtils,
                                      networkutilsv2.NetworkUtilsV2,
                                      lambda: utilsfactory.get_networkutils(),
                                      False, 'force_hyperv_utils_v1', False)

    def test_attach_volume(self):
        instance_data = self._get_instance_data()

        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        mount_point = '/dev/sdc'

        self._mock_attach_volume(instance_data['name'], target_iqn, target_lun,
                                 target_portal)

        self._mox.ReplayAll()
        self._conn.attach_volume(None, connection_info, instance_data,
                                 mount_point)
        self._mox.VerifyAll()

        self.assertEquals(len(self._instance_volume_disks), 1)

    def _mock_get_mounted_disk_from_lun_error(self, target_iqn, target_lun,
                                              fake_mounted_disk,
                                              fake_device_number):
        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndRaise(vmutils.HyperVException('Simulated failure'))

    def _mock_attach_volume_target_logout(self, instance_name, target_iqn,
                                          target_lun, target_portal=None,
                                          boot_from_volume=False):
        fake_mounted_disk = "fake_mounted disk"
        fake_device_number = 0
        fake_controller_path = "fake_scsi_controller_path"

        self._mock_login_storage_target(target_iqn, target_lun,
                                       target_portal,
                                       fake_mounted_disk,
                                       fake_device_number)

        self._mock_get_mounted_disk_from_lun_error(target_iqn, target_lun,
                                                   fake_mounted_disk,
                                                   fake_device_number)

        m = volumeutils.VolumeUtils.logout_storage_target(target_iqn)

    def test_attach_volume_logout(self):
        instance_data = self._get_instance_data()

        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        mount_point = '/dev/sdc'

        self._mock_attach_volume_target_logout(instance_data['name'],
                                        target_iqn, target_lun,
                                        target_portal)

        self._mox.ReplayAll()
        self.assertRaises(vmutils.HyperVException, self._conn.attach_volume,
                          None, connection_info, instance_data, mount_point)
        self._mox.VerifyAll()

    def test_attach_volume_connection_error(self):
        instance_data = self._get_instance_data()

        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        mount_point = '/dev/sdc'

        def fake_login_storage_target(connection_info):
            raise Exception('Fake connection exception')

        self.stubs.Set(self._conn._volumeops, '_login_storage_target',
                       fake_login_storage_target)
        self.assertRaises(vmutils.HyperVException, self._conn.attach_volume,
                          None, connection_info, instance_data, mount_point)

    def _mock_detach_volume(self, target_iqn, target_lun):
        mount_point = '/dev/sdc'

        fake_mounted_disk = "fake_mounted_disk"
        fake_device_number = 0
        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndReturn(fake_device_number)

        m = vmutils.VMUtils.get_mounted_disk_by_drive_number(
            fake_device_number)
        m.AndReturn(fake_mounted_disk)

        vmutils.VMUtils.detach_vm_disk(mox.IsA(str), fake_mounted_disk)

        volumeutils.VolumeUtils.logout_storage_target(mox.IsA(str))

    def test_detach_volume(self):
        instance_data = self._get_instance_data()
        instance_name = instance_data['name']

        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']

        mount_point = '/dev/sdc'

        self._mock_detach_volume(target_iqn, target_lun)

        self._mox.ReplayAll()
        self._conn.detach_volume(connection_info, instance_data, mount_point)
        self._mox.VerifyAll()

    def test_boot_from_volume(self):
        block_device_info = db_fakes.get_fake_block_device_info(
            self._volume_target_portal, self._volume_id)

        self._setup_spawn_instance_mocks(cow=False,
                                         block_device_info=block_device_info,
                                         boot_from_volume=True)

        self._mox.ReplayAll()
        self._spawn_instance(False, block_device_info)
        self._mox.VerifyAll()

        self.assertEquals(len(self._instance_volume_disks), 1)

    def test_get_volume_connector(self):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)

        fake_my_ip = "fake_ip"
        fake_host = "fake_host"
        fake_initiator = "fake_initiator"

        self.flags(my_ip=fake_my_ip)
        self.flags(host=fake_host)

        m = volumeutils.VolumeUtils.get_iscsi_initiator()
        m.AndReturn(fake_initiator)

        self._mox.ReplayAll()
        data = self._conn.get_volume_connector(instance)
        self._mox.VerifyAll()

        self.assertEquals(fake_my_ip, data.get('ip'))
        self.assertEquals(fake_host, data.get('host'))
        self.assertEquals(fake_initiator, data.get('initiator'))

    def _setup_test_migrate_disk_and_power_off_mocks(self, same_host=False,
                                                     copy_exception=False,
                                                     size_exception=False):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        instance['root_gb'] = 10

        fake_local_ip = '10.0.0.1'
        if same_host:
            fake_dest_ip = fake_local_ip
        else:
            fake_dest_ip = '10.0.0.2'

        if size_exception:
            flavor = 'm1.tiny'
        else:
            flavor = 'm1.small'

        instance_type = db.flavor_get_by_name(self._context, flavor)

        if not size_exception:
            fake_root_vhd_path = 'C:\\FakePath\\root.vhd'
            fake_revert_path = os.path.join(self._test_instance_dir, '_revert')

            func = mox.Func(self._check_instance_name)
            vmutils.VMUtils.set_vm_state(func,
                                         constants.HYPERV_VM_STATE_DISABLED)

            m = vmutils.VMUtils.get_vm_storage_paths(func)
            m.AndReturn(([fake_root_vhd_path], []))

            m = hostutils.HostUtils.get_local_ips()
            m.AndReturn([fake_local_ip])

            m = fake.PathUtils.get_instance_dir(mox.IsA(str))
            m.AndReturn(self._test_instance_dir)

            m = pathutils.PathUtils.get_instance_migr_revert_dir(
                instance['name'], remove_dir=True)
            m.AndReturn(fake_revert_path)

            if same_host:
                fake.PathUtils.makedirs(mox.IsA(str))

            m = fake.PathUtils.copy(fake_root_vhd_path, mox.IsA(str))
            if copy_exception:
                m.AndRaise(shutil.Error('Simulated copy error'))
                m = fake.PathUtils.get_instance_dir(mox.IsA(str),
                                                    mox.IsA(str),
                                                    remove_dir=True)
                m.AndReturn(self._test_instance_dir)
            else:
                fake.PathUtils.rename(mox.IsA(str), mox.IsA(str))
                destroy_disks = True
                if same_host:
                    fake.PathUtils.rename(mox.IsA(str), mox.IsA(str))
                    destroy_disks = False

                self._setup_destroy_mocks(False)

                if destroy_disks:
                    m = fake.PathUtils.get_instance_dir(mox.IsA(str),
                                                        mox.IsA(str),
                                                        remove_dir=True)
                    m.AndReturn(self._test_instance_dir)

        return (instance, fake_dest_ip, network_info, instance_type)

    def test_migrate_disk_and_power_off(self):
        (instance,
         fake_dest_ip,
         network_info,
         instance_type) = self._setup_test_migrate_disk_and_power_off_mocks()

        self._mox.ReplayAll()
        self._conn.migrate_disk_and_power_off(self._context, instance,
                                              fake_dest_ip, instance_type,
                                              network_info)
        self._mox.VerifyAll()

    def test_migrate_disk_and_power_off_same_host(self):
        args = self._setup_test_migrate_disk_and_power_off_mocks(
            same_host=True)
        (instance, fake_dest_ip, network_info, instance_type) = args

        self._mox.ReplayAll()
        self._conn.migrate_disk_and_power_off(self._context, instance,
                                              fake_dest_ip, instance_type,
                                              network_info)
        self._mox.VerifyAll()

    def test_migrate_disk_and_power_off_copy_exception(self):
        args = self._setup_test_migrate_disk_and_power_off_mocks(
            copy_exception=True)
        (instance, fake_dest_ip, network_info, instance_type) = args

        self._mox.ReplayAll()
        self.assertRaises(shutil.Error, self._conn.migrate_disk_and_power_off,
                          self._context, instance, fake_dest_ip,
                          instance_type, network_info)
        self._mox.VerifyAll()

    def test_migrate_disk_and_power_off_smaller_root_vhd_size_exception(self):
        args = self._setup_test_migrate_disk_and_power_off_mocks(
            size_exception=True)
        (instance, fake_dest_ip, network_info, instance_type) = args

        self._mox.ReplayAll()
        self.assertRaises(vmutils.VHDResizeException,
                          self._conn.migrate_disk_and_power_off,
                          self._context, instance, fake_dest_ip,
                          instance_type, network_info)
        self._mox.VerifyAll()

    def _test_finish_migration(self, power_on, ephemeral_storage=False):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        instance['system_metadata'] = {}
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(mox.IsA(str),
                                                              None)
        m.AndReturn(False)

        m = fake.PathUtils.get_instance_dir(mox.IsA(str))
        m.AndReturn(self._test_instance_dir)

        self._mox.StubOutWithMock(fake.PathUtils, 'exists')
        m = fake.PathUtils.exists(mox.IsA(str))
        m.AndReturn(True)

        fake_parent_vhd_path = (os.path.join('FakeParentPath', '%s.vhd' %
                                instance["image_ref"]))

        m = vhdutils.VHDUtils.get_vhd_info(mox.IsA(str))
        m.AndReturn({'ParentPath': fake_parent_vhd_path,
                     'MaxInternalSize': 1})
        m = vhdutils.VHDUtils.get_internal_vhd_size_by_file_size(
            mox.IsA(str), mox.IsA(object))
        m.AndReturn(1025)

        vhdutils.VHDUtils.reconnect_parent_vhd(mox.IsA(str), mox.IsA(str))

        m = vhdutils.VHDUtils.get_vhd_info(mox.IsA(str))
        m.AndReturn({'MaxInternalSize': 1024})

        m = fake.PathUtils.exists(mox.IsA(str))
        m.AndReturn(True)

        m = fake.PathUtils.get_instance_dir(mox.IsA(str))
        if ephemeral_storage:
            return m.AndReturn(self._test_instance_dir)
        else:
            m.AndReturn(None)

        self._set_vm_name(instance['name'])
        self._setup_create_instance_mocks(None, False,
                                          ephemeral_storage=ephemeral_storage)

        if power_on:
            vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                         constants.HYPERV_VM_STATE_ENABLED)

        self._mox.ReplayAll()
        self._conn.finish_migration(self._context, None, instance, "",
                                    network_info, None, False, None, power_on)
        self._mox.VerifyAll()

    def test_finish_migration_power_on(self):
        self._test_finish_migration(True)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(False)

    def test_finish_migration_with_ephemeral_storage(self):
        self._test_finish_migration(False, ephemeral_storage=True)

    def test_confirm_migration(self):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        pathutils.PathUtils.get_instance_migr_revert_dir(instance['name'],
                                                         remove_dir=True)
        self._mox.ReplayAll()
        self._conn.confirm_migration(None, instance, network_info)
        self._mox.VerifyAll()

    def _test_finish_revert_migration(self, power_on, ephemeral_storage=False):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        fake_revert_path = ('C:\\FakeInstancesPath\\%s\\_revert' %
                            instance['name'])

        m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(mox.IsA(str),
                                                              None)
        m.AndReturn(False)

        m = fake.PathUtils.get_instance_dir(mox.IsA(str),
                                            create_dir=False,
                                            remove_dir=True)
        m.AndReturn(self._test_instance_dir)

        m = pathutils.PathUtils.get_instance_migr_revert_dir(instance['name'])
        m.AndReturn(fake_revert_path)
        fake.PathUtils.rename(fake_revert_path, mox.IsA(str))

        m = fake.PathUtils.get_instance_dir(mox.IsA(str))
        m.AndReturn(self._test_instance_dir)

        m = fake.PathUtils.get_instance_dir(mox.IsA(str))
        if ephemeral_storage:
            m.AndReturn(self._test_instance_dir)
        else:
            m.AndReturn(None)

        self._set_vm_name(instance['name'])
        self._setup_create_instance_mocks(None, False,
                                          ephemeral_storage=ephemeral_storage)

        if power_on:
            vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                         constants.HYPERV_VM_STATE_ENABLED)

        self._mox.ReplayAll()
        self._conn.finish_revert_migration(instance, network_info, None,
                                           power_on)
        self._mox.VerifyAll()

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(True)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(False)

    def test_spawn_no_admin_permissions(self):
        self.assertRaises(vmutils.HyperVAuthorizationException,
                          self._test_spawn_instance,
                          with_exception=True,
                          admin_permissions=False)

    def test_finish_revert_migration_with_ephemeral_storage(self):
        self._test_finish_revert_migration(False, ephemeral_storage=True)
