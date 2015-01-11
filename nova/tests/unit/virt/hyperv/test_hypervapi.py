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

import os
import shutil
import time
import uuid

import mock
from mox3 import mox
from oslo_config import cfg
from oslo_utils import units

from nova.api.metadata import base as instance_metadata
from nova.compute import power_state
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova import objects
from nova.openstack.common import fileutils
from nova import test
from nova.tests.unit import fake_network
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit.virt.hyperv import db_fakes
from nova.tests.unit.virt.hyperv import fake
from nova import utils
from nova.virt import configdrive
from nova.virt import driver
from nova.virt.hyperv import basevolumeutils
from nova.virt.hyperv import constants
from nova.virt.hyperv import driver as driver_hyperv
from nova.virt.hyperv import hostutils
from nova.virt.hyperv import imagecache
from nova.virt.hyperv import ioutils
from nova.virt.hyperv import networkutils
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import rdpconsoleutils
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import volumeops
from nova.virt.hyperv import volumeutils
from nova.virt.hyperv import volumeutilsv2
from nova.virt import images

CONF = cfg.CONF
CONF.import_opt('vswitch_name', 'nova.virt.hyperv.vif', 'hyperv')


class HyperVAPIBaseTestCase(test.NoDBTestCase):
    """Base unit tests class for Hyper-V driver calls."""

    def __init__(self, test_case_name):
        self._mox = mox.Mox()
        super(HyperVAPIBaseTestCase, self).__init__(test_case_name)

    def setUp(self):
        super(HyperVAPIBaseTestCase, self).setUp()

        self._user_id = 'fake'
        self._project_id = 'fake'
        self._instance_data = None
        self._image_metadata = None
        self._fetched_image = None
        self._update_image_raise_exception = False
        self._volume_target_portal = 'testtargetportal:3260'
        self._volume_id = '0ef5d708-45ab-4129-8c59-d774d2837eb7'
        self._context = context.RequestContext(self._user_id, self._project_id)
        self._instance_disks = []
        self._instance_dvds = []
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
            if [major, minor] >= [6, 3]:
                return False
            return self._check_min_windows_version_satisfied
        self.stubs.Set(hostutils.HostUtils, 'check_min_windows_version',
                       fake_check_min_windows_version)

        def fake_sleep(ms):
            pass
        self.stubs.Set(time, 'sleep', fake_sleep)

        class FakeIOThread(object):
            def __init__(self, src, dest, max_bytes):
                pass

            def start(self):
                pass

        self.stubs.Set(pathutils, 'PathUtils', fake.PathUtils)
        self.stubs.Set(ioutils, 'IOThread', FakeIOThread)
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
        self._mox.StubOutWithMock(fake.PathUtils, 'get_vm_console_log_paths')

        self._mox.StubOutWithMock(vmutils.VMUtils, 'vm_exists')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_vm')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'destroy_vm')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'attach_ide_drive')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'attach_scsi_drive')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_scsi_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'create_nic')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'set_vm_state')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'list_instances')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_summary_info')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'set_nic_connection')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_scsi_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_ide_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_attached_disks')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'attach_volume_to_controller')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'get_mounted_disk_by_drive_number')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'detach_vm_disk')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_storage_paths')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'get_controller_volume_paths')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_free_controller_slot')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'enable_vm_metrics_collection')
        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_id')
        self._mox.StubOutWithMock(vmutils.VMUtils,
                                  'get_vm_serial_port_connection')

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

        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_local_ips')

        self._mox.StubOutWithMock(imagecache.ImageCache, 'get_image_details')

        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'get_external_vswitch')
        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'create_vswitch_port')
        self._mox.StubOutWithMock(networkutils.NetworkUtils,
                                  'vswitch_port_needed')

        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'volume_in_mapping')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_session_id_from_mounted_disk')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_device_number_for_target')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_target_from_disk_path')
        self._mox.StubOutWithMock(basevolumeutils.BaseVolumeUtils,
                                  'get_target_lun_count')

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

        self._mox.StubOutWithMock(rdpconsoleutils.RDPConsoleUtils,
                                  'get_rdp_console_port')

        self._mox.StubOutClassWithMocks(instance_metadata, 'InstanceMetadata')
        self._mox.StubOutWithMock(instance_metadata.InstanceMetadata,
                                  'metadata_for_config_drive')

        # Can't use StubOutClassWithMocks due to __exit__ and __enter__
        self._mox.StubOutWithMock(configdrive, 'ConfigDriveBuilder')
        self._mox.StubOutWithMock(configdrive.ConfigDriveBuilder, 'make_drive')

        self._mox.StubOutWithMock(fileutils, 'delete_if_exists')
        self._mox.StubOutWithMock(utils, 'execute')

    def tearDown(self):
        self._mox.UnsetStubs()
        super(HyperVAPIBaseTestCase, self).tearDown()


class HyperVAPITestCase(HyperVAPIBaseTestCase):
    """Unit tests for Hyper-V driver calls."""

    def test_public_api_signatures(self):
        self.assertPublicAPISignatures(driver.ComputeDriver(None), self._conn)

    def test_list_instances(self):
        fake_instances = ['fake1', 'fake2']
        vmutils.VMUtils.list_instances().AndReturn(fake_instances)

        self._mox.ReplayAll()
        instances = self._conn.list_instances()
        self._mox.VerifyAll()

        self.assertEqual(instances, fake_instances)

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

        self.assertEqual(info.state, power_state.RUNNING)

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

    def _setup_spawn_config_drive_mocks(self, use_cdrom):
        instance_metadata.InstanceMetadata(mox.IgnoreArg(),
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
        m.WithSideEffects(self._add_disk)

    def _check_instance_name(self, vm_name):
        return vm_name == self._instance_data['name']

    def _test_vm_state_change(self, action, from_state, to_state):
        self._instance_data = self._get_instance_data()

        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     to_state)

        if to_state in (constants.HYPERV_VM_STATE_DISABLED,
                        constants.HYPERV_VM_STATE_REBOOT):
            self._setup_delete_vm_log_mocks()
        if to_state in (constants.HYPERV_VM_STATE_ENABLED,
                        constants.HYPERV_VM_STATE_REBOOT):
            self._setup_log_vm_output_mocks()

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
        self._test_vm_state_change(lambda i: self._conn.resume(self._context,
                                                               i, None),
                                   constants.HYPERV_VM_STATE_SUSPENDED,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_resume_already_running(self):
        self._test_vm_state_change(lambda i: self._conn.resume(self._context,
                                                               i, None), None,
                                   constants.HYPERV_VM_STATE_ENABLED)

    def test_power_off(self):
        self._test_vm_state_change(self._conn.power_off, None,
                                   constants.HYPERV_VM_STATE_DISABLED)

    def test_power_off_already_powered_off(self):
        self._test_vm_state_change(self._conn.power_off,
                                   constants.HYPERV_VM_STATE_DISABLED,
                                   constants.HYPERV_VM_STATE_DISABLED)

    def _test_power_on(self, block_device_info):
        self._instance_data = self._get_instance_data()
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     constants.HYPERV_VM_STATE_ENABLED)
        if block_device_info:
            self._mox.StubOutWithMock(volumeops.VolumeOps,
                                      'fix_instance_volume_disk_paths')
            volumeops.VolumeOps.fix_instance_volume_disk_paths(
                mox.Func(self._check_instance_name), block_device_info)

        self._setup_log_vm_output_mocks()

        self._mox.ReplayAll()
        self._conn.power_on(self._context, self._instance_data, network_info,
                            block_device_info=block_device_info)
        self._mox.VerifyAll()

    def test_power_on_having_block_devices(self):
        block_device_info = db_fakes.get_fake_block_device_info(
            self._volume_target_portal, self._volume_id)
        self._test_power_on(block_device_info=block_device_info)

    def test_power_on_without_block_devices(self):
        self._test_power_on(block_device_info=None)

    def test_power_on_already_running(self):
        self._instance_data = self._get_instance_data()
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)
        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     constants.HYPERV_VM_STATE_ENABLED)
        self._setup_log_vm_output_mocks()
        self._mox.ReplayAll()
        self._conn.power_on(self._context, self._instance_data, network_info)
        self._mox.VerifyAll()

    def test_reboot(self):

        network_info = fake_network.fake_get_instance_nw_info(self.stubs)
        self._instance_data = self._get_instance_data()

        vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                     constants.HYPERV_VM_STATE_REBOOT)

        self._setup_delete_vm_log_mocks()
        self._setup_log_vm_output_mocks()

        self._mox.ReplayAll()
        self._conn.reboot(self._context, self._instance_data, network_info,
                          None)
        self._mox.VerifyAll()

    def _setup_destroy_mocks(self, destroy_disks=True):
        m = vmutils.VMUtils.vm_exists(mox.Func(self._check_instance_name))
        m.AndReturn(True)

        func = mox.Func(self._check_instance_name)
        vmutils.VMUtils.set_vm_state(func, constants.HYPERV_VM_STATE_DISABLED)

        self._setup_delete_vm_log_mocks()

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
        self._conn.destroy(self._context, self._instance_data, None)
        self._mox.VerifyAll()

    def test_get_instance_disk_info_is_implemented(self):
        instance = objects.Instance()
        # Ensure that the method has been implemented in the driver
        try:
            disk_info = self._conn.get_instance_disk_info(instance)
            self.assertIsNone(disk_info)
        except NotImplementedError:
            self.fail("test_get_instance_disk_info() should not raise "
                      "NotImplementedError")

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

    def _add_disk(self, vm_name, path, ctrller_addr,
                  drive_addr, drive_type):
        if drive_type == constants.DISK:
            self._instance_disks.append(path)
        elif drive_type == constants.DVD:
            self._instance_dvds.append(path)

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
                                  CONF.hyperv.dynamic_memory_ratio,
                                  mox.IsA(int),
                                  mox.IsA(list))

        if not boot_from_volume:
            m = vmutils.VMUtils.attach_ide_drive(mox.Func(self._check_vm_name),
                                                 mox.IsA(str),
                                                 mox.IsA(int),
                                                 mox.IsA(int),
                                                 mox.IsA(str))
            m.WithSideEffects(self._add_disk).InAnyOrder()

        if ephemeral_storage:
            m = vmutils.VMUtils.attach_ide_drive(mox.Func(self._check_vm_name),
                                                 mox.IsA(str),
                                                 mox.IsA(int),
                                                 mox.IsA(int),
                                                 mox.IsA(str))
            m.WithSideEffects(self._add_disk).InAnyOrder()

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

        vmutils.VMUtils.create_nic(mox.Func(self._check_vm_name),
                mox.IsA(str), mox.IsA(unicode)).InAnyOrder()

        if setup_vif_mocks_func:
            setup_vif_mocks_func()

        if CONF.hyperv.enable_instance_metrics_collection:
            vmutils.VMUtils.enable_vm_metrics_collection(
                mox.Func(self._check_vm_name))

        vmutils.VMUtils.get_vm_serial_port_connection(
            mox.IsA(str), update_connection=mox.IsA(str))

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
            m.AndRaise(vmutils.HyperVAuthorizationException(
                'Simulated failure'))

    def _setup_log_vm_output_mocks(self):
        m = fake.PathUtils.get_vm_console_log_paths(mox.IsA(str))
        m.AndReturn(('fake_vm_log_path', 'fake_vm_log_path.1'))
        ioutils.IOThread('fake_pipe', 'fake_vm_log_path',
                         units.Mi).start()

    def _setup_delete_vm_log_mocks(self):
        m = fake.PathUtils.get_vm_console_log_paths(mox.IsA(str))
        m.AndReturn(('fake_vm_log_path', 'fake_vm_log_path.1'))
        fileutils.delete_if_exists(mox.IsA(str))
        fileutils.delete_if_exists(mox.IsA(str))

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

            vhdutils.VHDUtils.resize_vhd(mox.IsA(str), mox.IsA(object),
                                         is_file_max_size=False)

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

        if block_device_info:
            m = basevolumeutils.BaseVolumeUtils.volume_in_mapping(
                'fake_root_device_name', block_device_info)
            m.AndReturn(boot_from_volume)

        if not boot_from_volume:
            m = fake.PathUtils.get_instance_dir(mox.Func(self._check_vm_name))
            m.AndReturn(self._test_instance_dir)

            self._setup_get_cached_image_mocks(cow, vhd_format)
            m = vhdutils.VHDUtils.get_vhd_info(mox.IsA(str))
            m.AndReturn({'MaxInternalSize': 1024, 'FileSize': 1024,
                         'Type': 2})

            if cow:
                vhdutils.VHDUtils.create_differencing_vhd(mox.IsA(str),
                                                          mox.IsA(str))
                m = vhdutils.VHDUtils.get_vhd_format(mox.IsA(str))
                m.AndReturn(vhd_format)
            else:
                fake.PathUtils.copyfile(mox.IsA(str), mox.IsA(str))

            if not (cow and vhd_format == constants.DISK_FORMAT_VHD):
                m = vhdutils.VHDUtils.get_internal_vhd_size_by_file_size(
                    mox.IsA(str), mox.IsA(object))
                m.AndReturn(1025)
                vhdutils.VHDUtils.resize_vhd(mox.IsA(str), mox.IsA(object),
                                             is_file_max_size=False)

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

        if config_drive and not with_exception:
            self._setup_spawn_config_drive_mocks(use_cdrom)

        # TODO(alexpilotti) Based on where the exception is thrown
        # some of the above mock calls need to be skipped
        if with_exception:
            self._setup_destroy_mocks()
        else:
            vmutils.VMUtils.set_vm_state(mox.Func(self._check_vm_name),
                                         constants.HYPERV_VM_STATE_ENABLED)
            self._setup_log_vm_output_mocks()

    def _test_spawn_instance(self, cow=True,
                             expected_disks=1,
                             expected_dvds=0,
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

        self.assertEqual(len(self._instance_disks), expected_disks)
        self.assertEqual(len(self._instance_dvds), expected_dvds)

        vhd_path = os.path.join(self._test_instance_dir, 'root.' +
                                vhd_format.lower())
        self.assertEqual(vhd_path, self._instance_disks[0])

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
                                                     target_portal,
                                                     'fake_username',
                                                     'fake_password')

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
            m = vmutils.VMUtils.get_free_controller_slot(
                fake_controller_path)
            m.AndReturn(fake_free_slot)

        m = vmutils.VMUtils.attach_volume_to_controller(instance_name,
                                                        fake_controller_path,
                                                        fake_free_slot,
                                                        fake_mounted_disk)
        m.WithSideEffects(self._add_volume_disk)

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

        self.assertEqual(len(self._instance_volume_disks), 1)

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

        self._mock_login_storage_target(target_iqn, target_lun,
                                       target_portal,
                                       fake_mounted_disk,
                                       fake_device_number)

        self._mock_get_mounted_disk_from_lun_error(target_iqn, target_lun,
                                                   fake_mounted_disk,
                                                   fake_device_number)

        self._mock_logout_storage_target(target_iqn)

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

        def fake_login_storage_target(self, connection_info):
            raise vmutils.HyperVException('Fake connection exception')

        self.stubs.Set(volumeops.ISCSIVolumeDriver, 'login_storage_target',
                       fake_login_storage_target)
        self.assertRaises(vmutils.HyperVException, self._conn.attach_volume,
                          None, connection_info, instance_data, mount_point)

    def _mock_detach_volume(self, target_iqn, target_lun,
                            other_luns_available=False):
        fake_mounted_disk = "fake_mounted_disk"
        fake_device_number = 0
        m = volumeutils.VolumeUtils.get_device_number_for_target(target_iqn,
                                                                 target_lun)
        m.AndReturn(fake_device_number)

        m = vmutils.VMUtils.get_mounted_disk_by_drive_number(
            fake_device_number)
        m.AndReturn(fake_mounted_disk)

        vmutils.VMUtils.detach_vm_disk(mox.IsA(str), fake_mounted_disk)

        self._mock_logout_storage_target(target_iqn, other_luns_available)

    def _mock_logout_storage_target(self, target_iqn,
                                    other_luns_available=False):

        m = volumeutils.VolumeUtils.get_target_lun_count(target_iqn)
        m.AndReturn(1 + int(other_luns_available))

        if not other_luns_available:
            volumeutils.VolumeUtils.logout_storage_target(target_iqn)

    def _test_detach_volume(self, other_luns_available=False):
        instance_data = self._get_instance_data()
        self.assertIn('name', instance_data)

        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        self.assertIn('target_portal', data)

        mount_point = '/dev/sdc'

        self._mock_detach_volume(target_iqn, target_lun, other_luns_available)
        self._mox.ReplayAll()
        self._conn.detach_volume(connection_info, instance_data, mount_point)
        self._mox.VerifyAll()

    def test_detach_volume(self):
        self._test_detach_volume()

    def test_detach_volume_multiple_luns_per_target(self):
        # The iSCSI target should not be disconnected in this case.
        self._test_detach_volume(other_luns_available=True)

    def test_boot_from_volume(self):
        block_device_info = db_fakes.get_fake_block_device_info(
            self._volume_target_portal, self._volume_id)

        self._setup_spawn_instance_mocks(cow=False,
                                         block_device_info=block_device_info,
                                         boot_from_volume=True)

        self._mox.ReplayAll()
        self._spawn_instance(False, block_device_info)
        self._mox.VerifyAll()

        self.assertEqual(len(self._instance_volume_disks), 1)

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

        self.assertEqual(fake_my_ip, data.get('ip'))
        self.assertEqual(fake_host, data.get('host'))
        self.assertEqual(fake_initiator, data.get('initiator'))

    def test_get_volume_connector_storage_ip(self):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)

        fake_my_ip = "fake_ip"
        fake_my_block_ip = "fake_block_ip"
        fake_host = "fake_host"
        fake_initiator = "fake_initiator"

        self.flags(my_ip=fake_my_ip)
        self.flags(my_block_storage_ip=fake_my_block_ip)
        self.flags(host=fake_host)

        with mock.patch.object(volumeutils.VolumeUtils,
                               "get_iscsi_initiator") as mock_initiator:
            mock_initiator.return_value = fake_initiator
            data = self._conn.get_volume_connector(instance)

        self.assertEqual(fake_my_block_ip, data.get('ip'))
        self.assertEqual(fake_host, data.get('host'))
        self.assertEqual(fake_initiator, data.get('initiator'))

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

        flavor = db.flavor_get_by_name(self._context, flavor)

        if not size_exception:
            fake_root_vhd_path = 'C:\\FakePath\\root.vhd'
            fake_revert_path = os.path.join(self._test_instance_dir, '_revert')

            func = mox.Func(self._check_instance_name)
            vmutils.VMUtils.set_vm_state(func,
                                         constants.HYPERV_VM_STATE_DISABLED)

            self._setup_delete_vm_log_mocks()

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

        return (instance, fake_dest_ip, network_info, flavor)

    def test_migrate_disk_and_power_off(self):
        (instance,
         fake_dest_ip,
         network_info,
         flavor) = self._setup_test_migrate_disk_and_power_off_mocks()

        self._mox.ReplayAll()
        self._conn.migrate_disk_and_power_off(self._context, instance,
                                              fake_dest_ip, flavor,
                                              network_info)
        self._mox.VerifyAll()

    def test_migrate_disk_and_power_off_same_host(self):
        args = self._setup_test_migrate_disk_and_power_off_mocks(
            same_host=True)
        (instance, fake_dest_ip, network_info, flavor) = args

        self._mox.ReplayAll()
        self._conn.migrate_disk_and_power_off(self._context, instance,
                                              fake_dest_ip, flavor,
                                              network_info)
        self._mox.VerifyAll()

    def test_migrate_disk_and_power_off_copy_exception(self):
        args = self._setup_test_migrate_disk_and_power_off_mocks(
            copy_exception=True)
        (instance, fake_dest_ip, network_info, flavor) = args

        self._mox.ReplayAll()
        self.assertRaises(shutil.Error, self._conn.migrate_disk_and_power_off,
                          self._context, instance, fake_dest_ip,
                          flavor, network_info)
        self._mox.VerifyAll()

    def test_migrate_disk_and_power_off_smaller_root_vhd_size_exception(self):
        args = self._setup_test_migrate_disk_and_power_off_mocks(
            size_exception=True)
        (instance, fake_dest_ip, network_info, flavor) = args

        self._mox.ReplayAll()
        self.assertRaises(exception.InstanceFaultRollback,
                          self._conn.migrate_disk_and_power_off,
                          self._context, instance, fake_dest_ip,
                          flavor, network_info)
        self._mox.VerifyAll()

    def _mock_attach_config_drive(self, instance, config_drive_format):
        instance['config_drive'] = True
        self._mox.StubOutWithMock(fake.PathUtils, 'lookup_configdrive_path')
        m = fake.PathUtils.lookup_configdrive_path(
            mox.Func(self._check_instance_name))

        if config_drive_format in constants.DISK_FORMAT_MAP:
            m.AndReturn(self._test_instance_dir + '/configdrive.' +
                        config_drive_format)
        else:
            m.AndReturn(None)

        m = vmutils.VMUtils.attach_ide_drive(
            mox.Func(self._check_instance_name),
            mox.IsA(str),
            mox.IsA(int),
            mox.IsA(int),
            mox.IsA(str))
        m.WithSideEffects(self._add_disk).InAnyOrder()

    def _verify_attach_config_drive(self, config_drive_format):
        if config_drive_format == constants.DISK_FORMAT.lower():
            self.assertEqual(self._instance_disks[1],
                self._test_instance_dir + '/configdrive.' +
                config_drive_format)
        elif config_drive_format == constants.DVD_FORMAT.lower():
            self.assertEqual(self._instance_dvds[0],
                self._test_instance_dir + '/configdrive.' +
                config_drive_format)

    def _test_finish_migration(self, power_on, ephemeral_storage=False,
                               config_drive=False,
                               config_drive_format='iso'):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        instance['system_metadata'] = {}
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

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
            self._setup_log_vm_output_mocks()

        if config_drive:
            self._mock_attach_config_drive(instance, config_drive_format)

        self._mox.ReplayAll()

        image_meta = {'properties': {constants.IMAGE_PROP_VM_GEN:
                                     constants.IMAGE_PROP_VM_GEN_1}}
        self._conn.finish_migration(self._context, None, instance, "",
                                    network_info, image_meta, False, None,
                                    power_on)
        self._mox.VerifyAll()

        if config_drive:
            self._verify_attach_config_drive(config_drive_format)

    def test_finish_migration_power_on(self):
        self._test_finish_migration(True)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(False)

    def test_finish_migration_with_ephemeral_storage(self):
        self._test_finish_migration(False, ephemeral_storage=True)

    def test_finish_migration_attach_config_drive_iso(self):
        self._test_finish_migration(False, config_drive=True,
            config_drive_format=constants.DVD_FORMAT.lower())

    def test_finish_migration_attach_config_drive_vhd(self):
        self._test_finish_migration(False, config_drive=True,
            config_drive_format=constants.DISK_FORMAT.lower())

    def test_confirm_migration(self):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        pathutils.PathUtils.get_instance_migr_revert_dir(instance['name'],
                                                         remove_dir=True)
        self._mox.ReplayAll()
        self._conn.confirm_migration(None, instance, network_info)
        self._mox.VerifyAll()

    def _test_finish_revert_migration(self, power_on, ephemeral_storage=False,
                                      config_drive=False,
                                      config_drive_format='iso'):
        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)
        network_info = fake_network.fake_get_instance_nw_info(self.stubs)

        fake_revert_path = ('C:\\FakeInstancesPath\\%s\\_revert' %
                            instance['name'])

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

        m = imagecache.ImageCache.get_image_details(mox.IsA(object),
                                                    mox.IsA(object))
        m.AndReturn({'properties': {constants.IMAGE_PROP_VM_GEN:
                                    constants.IMAGE_PROP_VM_GEN_1}})

        self._set_vm_name(instance['name'])
        self._setup_create_instance_mocks(None, False,
                                          ephemeral_storage=ephemeral_storage)

        if power_on:
            vmutils.VMUtils.set_vm_state(mox.Func(self._check_instance_name),
                                         constants.HYPERV_VM_STATE_ENABLED)
            self._setup_log_vm_output_mocks()

        if config_drive:
            self._mock_attach_config_drive(instance, config_drive_format)

        self._mox.ReplayAll()
        self._conn.finish_revert_migration(self._context, instance,
                                           network_info, None,
                                           power_on)
        self._mox.VerifyAll()

        if config_drive:
            self._verify_attach_config_drive(config_drive_format)

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(True)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(False)

    def test_finish_revert_migration_with_ephemeral_storage(self):
        self._test_finish_revert_migration(False, ephemeral_storage=True)

    def test_finish_revert_migration_attach_config_drive_iso(self):
        self._test_finish_revert_migration(False, config_drive=True,
            config_drive_format=constants.DVD_FORMAT.lower())

    def test_finish_revert_migration_attach_config_drive_vhd(self):
        self._test_finish_revert_migration(False, config_drive=True,
            config_drive_format=constants.DISK_FORMAT.lower())

    def test_plug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self.assertRaises(NotImplementedError,
                          self._conn.plug_vifs,
                          instance=self._test_spawn_instance,
                          network_info=None)

    def test_unplug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self.assertRaises(NotImplementedError,
                          self._conn.unplug_vifs,
                          instance=self._test_spawn_instance,
                          network_info=None)

    def test_refresh_instance_security_rules(self):
        self.assertRaises(NotImplementedError,
                          self._conn.refresh_instance_security_rules,
                          instance=None)

    def test_get_rdp_console(self):
        self.flags(my_ip="192.168.1.1")

        self._instance_data = self._get_instance_data()
        instance = db.instance_create(self._context, self._instance_data)

        fake_port = 9999
        fake_vm_id = "fake_vm_id"

        m = rdpconsoleutils.RDPConsoleUtils.get_rdp_console_port()
        m.AndReturn(fake_port)

        m = vmutils.VMUtils.get_vm_id(mox.IsA(str))
        m.AndReturn(fake_vm_id)

        self._mox.ReplayAll()
        connect_info = self._conn.get_rdp_console(self._context, instance)
        self._mox.VerifyAll()

        self.assertEqual(CONF.my_ip, connect_info.host)
        self.assertEqual(fake_port, connect_info.port)
        self.assertEqual(fake_vm_id, connect_info.internal_access_path)
