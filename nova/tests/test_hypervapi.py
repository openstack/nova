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

import os
import platform
import shutil
import sys
import uuid

from nova.compute import power_state
from nova import context
from nova import db
from nova import flags
from nova.image import glance
from nova.tests import fake_network
from nova.tests.hyperv import basetestcase
from nova.tests.hyperv import db_fakes
from nova.tests.hyperv import hypervutils
from nova.tests.hyperv import mockproxy
import nova.tests.image.fake as fake_image
from nova.virt.hyperv import constants
from nova.virt.hyperv import driver as driver_hyperv
from nova.virt.hyperv import vmutils
from nova.virt import images


class HyperVAPITestCase(basetestcase.BaseTestCase):
    """Unit tests for Hyper-V driver calls."""

    def setUp(self):
        super(HyperVAPITestCase, self).setUp()

        self._user_id = 'fake'
        self._project_id = 'fake'
        self._instance_data = None
        self._image_metadata = None
        self._dest_server = None
        self._fetched_image = None
        self._update_image_raise_exception = False
        self._post_method_called = False
        self._recover_method_called = False
        self._volume_target_portal = '192.168.1.112:3260'
        self._volume_id = '10958016-e196-42e3-9e7f-5d8927ae3099'
        self._context = context.RequestContext(self._user_id, self._project_id)

        self._setup_stubs()

        self.flags(instances_path=r'C:\Hyper-V\test\instances',
                        vswitch_name='external')

        self._hypervutils = hypervutils.HyperVUtils()
        self._conn = driver_hyperv.HyperVDriver()

    def _setup_stubs(self):
        db_fakes.stub_out_db_instance_api(self.stubs)
        fake_image.stub_out_image_service(self.stubs)

        def fake_fetch(context, image_id, target, user, project):
            self._fetched_image = target
            if not os.path.exists(target):
                self._hypervutils.create_vhd(target)
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

        # Modules to mock
        modules_to_mock = [
            'wmi',
            'os',
            'shutil',
            'uuid',
            'time',
            'subprocess',
            'multiprocessing',
            '_winreg'
        ]

        # Modules in which the mocks are going to be injected
        from nova.virt.hyperv import baseops
        from nova.virt.hyperv import livemigrationops
        from nova.virt.hyperv import snapshotops
        from nova.virt.hyperv import vmops
        from nova.virt.hyperv import volumeops
        from nova.virt.hyperv import volumeutils

        modules_to_test = [
            driver_hyperv,
            baseops,
            vmops,
            vmutils,
            volumeops,
            volumeutils,
            snapshotops,
            livemigrationops,
            hypervutils,
            sys.modules[__name__]
        ]

        self._inject_mocks_in_modules(modules_to_mock, modules_to_test)

        if isinstance(snapshotops.wmi, mockproxy.Mock):
            from nova.virt.hyperv import ioutils
            import StringIO

            def fake_open(name, mode):
                return StringIO.StringIO("fake file content")
            self.stubs.Set(ioutils, 'open', fake_open)

    def tearDown(self):
        try:
            if self._instance_data and self._hypervutils.vm_exists(
                    self._instance_data["name"]):
                self._hypervutils.remove_vm(self._instance_data["name"])

            if self._dest_server and \
                    self._hypervutils.remote_vm_exists(self._dest_server,
                        self._instance_data["name"]):
                self._hypervutils.remove_remote_vm(self._dest_server,
                    self._instance_data["name"])

            self._hypervutils.logout_iscsi_volume_sessions(self._volume_id)

            shutil.rmtree(flags.FLAGS.instances_path, True)

            fake_image.FakeImageService_reset()
        finally:
            super(HyperVAPITestCase, self).tearDown()

    def test_get_available_resource(self):
        dic = self._conn.get_available_resource()

        self.assertEquals(dic['hypervisor_hostname'], platform.node())

    def test_list_instances(self):
        num_vms = self._hypervutils.get_vm_count()
        instances = self._conn.list_instances()

        self.assertEquals(len(instances), num_vms)

    def test_get_info(self):
        self._spawn_instance(True)
        info = self._conn.get_info(self._instance_data)

        self.assertEquals(info["state"], str(power_state.RUNNING))

    def test_spawn_cow_image(self):
        self._test_spawn_instance(True)

    def test_spawn_no_cow_image(self):
        self._test_spawn_instance(False)

    def test_spawn_no_vswitch_exception(self):
        # Set flag to a non existing vswitch
        self.flags(vswitch_name=str(uuid.uuid4()))
        self.assertRaises(vmutils.HyperVException, self._spawn_instance, True)

        self.assertFalse(self._hypervutils.vm_exists(
            self._instance_data["name"]))

    def _test_vm_state_change(self, action, from_state, to_state):
        self._spawn_instance(True)
        if from_state:
            self._hypervutils.set_vm_state(self._instance_data["name"],
                from_state)
        action(self._instance_data)

        vmstate = self._hypervutils.get_vm_state(self._instance_data["name"])
        self.assertEquals(vmstate, to_state)

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
        self._test_vm_state_change(self._conn.resume,
            constants.HYPERV_VM_STATE_SUSPENDED,
            constants.HYPERV_VM_STATE_ENABLED)

    def test_resume_already_running(self):
        self._test_vm_state_change(self._conn.resume, None,
            constants.HYPERV_VM_STATE_ENABLED)

    def test_power_off(self):
        self._test_vm_state_change(self._conn.power_off, None,
            constants.HYPERV_VM_STATE_DISABLED)

    def test_power_off_already_powered_off(self):
        self._test_vm_state_change(self._conn.suspend,
            constants.HYPERV_VM_STATE_DISABLED,
            constants.HYPERV_VM_STATE_DISABLED)

    def test_power_on(self):
        self._test_vm_state_change(self._conn.power_on,
            constants.HYPERV_VM_STATE_DISABLED,
            constants.HYPERV_VM_STATE_ENABLED)

    def test_power_on_already_running(self):
        self._test_vm_state_change(self._conn.power_on, None,
            constants.HYPERV_VM_STATE_ENABLED)

    def test_reboot(self):
        self._spawn_instance(True)

        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        self._conn.reboot(self._instance_data, network_info, None)

        vmstate = self._hypervutils.get_vm_state(self._instance_data["name"])
        self.assertEquals(vmstate, constants.HYPERV_VM_STATE_ENABLED)

    def test_destroy(self):
        self._spawn_instance(True)
        (vhd_paths, _) = self._hypervutils.get_vm_disks(
            self._instance_data["name"])

        self._conn.destroy(self._instance_data)

        self.assertFalse(self._hypervutils.vm_exists(
            self._instance_data["name"]))
        self._instance_data = None

        for vhd_path in vhd_paths:
            self.assertFalse(os.path.exists(vhd_path))

    def test_live_migration(self):
        self.flags(limit_cpu_features=True)
        self._spawn_instance(False)

        # Existing server
        self._dest_server = "HV12RCTest1"

        self._live_migration(self._dest_server)

        instance_name = self._instance_data["name"]
        self.assertFalse(self._hypervutils.vm_exists(instance_name))
        self.assertTrue(self._hypervutils.remote_vm_exists(self._dest_server,
            instance_name))

        self.assertTrue(self._post_method_called)
        self.assertFalse(self._recover_method_called)

    def test_live_migration_with_target_failure(self):
        self.flags(limit_cpu_features=True)
        self._spawn_instance(False)

        dest_server = "nonexistingserver"

        exception_raised = False
        try:
            self._live_migration(dest_server)
        except Exception:
            exception_raised = True

        # Cannot use assertRaises with pythoncom.com_error on Linux
        self.assertTrue(exception_raised)

        instance_name = self._instance_data["name"]
        self.assertTrue(self._hypervutils.vm_exists(instance_name))

        self.assertFalse(self._post_method_called)
        self.assertTrue(self._recover_method_called)

    def _live_migration(self, dest_server):
        def fake_post_method(context, instance_ref, dest, block_migration):
                self._post_method_called = True

        def fake_recover_method(context, instance_ref, dest, block_migration):
            self._recover_method_called = True

        self._conn.live_migration(self._context, self._instance_data,
            dest_server, fake_post_method, fake_recover_method)

    def test_pre_live_migration_cow_image(self):
        self._test_pre_live_migration(True)

    def test_pre_live_migration_no_cow_image(self):
        self._test_pre_live_migration(False)

    def _test_pre_live_migration(self, cow):
        self.flags(use_cow_images=cow)

        instance_name = 'openstack_unit_test_vm_' + str(uuid.uuid4())

        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)
        instance_data = db_fakes.get_fake_instance_data(instance_name,
            self._project_id, self._user_id)
        block_device_info = None

        self._conn.pre_live_migration(self._context, instance_data,
            block_device_info, network_info)

        if cow:
            self.assertTrue(not self._fetched_image is None)
        else:
            self.assertTrue(self._fetched_image is None)

    def test_snapshot_with_update_failure(self):
        self._spawn_instance(True)

        self._update_image_raise_exception = True
        snapshot_name = 'test_snapshot_' + str(uuid.uuid4())
        self.assertRaises(vmutils.HyperVException, self._conn.snapshot,
            self._context, self._instance_data, snapshot_name)

        # assert VM snapshots have been removed
        self.assertEquals(self._hypervutils.get_vm_snapshots_count(
            self._instance_data["name"]), 0)

    def test_snapshot(self):
        self._spawn_instance(True)

        snapshot_name = 'test_snapshot_' + str(uuid.uuid4())
        self._conn.snapshot(self._context, self._instance_data, snapshot_name)

        self.assertTrue(self._image_metadata and
                "disk_format" in self._image_metadata and
                self._image_metadata["disk_format"] == "vhd")

        # assert VM snapshots have been removed
        self.assertEquals(self._hypervutils.get_vm_snapshots_count(
            self._instance_data["name"]), 0)

    def _spawn_instance(self, cow, block_device_info=None):
        self.flags(use_cow_images=cow)

        instance_name = 'openstack_unit_test_vm_' + str(uuid.uuid4())

        self._instance_data = db_fakes.get_fake_instance_data(instance_name,
                self._project_id, self._user_id)
        instance = db.instance_create(self._context, self._instance_data)

        image = db_fakes.get_fake_image_data(self._project_id, self._user_id)

        network_info = fake_network.fake_get_instance_nw_info(self.stubs,
                                                              spectacular=True)

        self._conn.spawn(self._context, instance, image,
                         injected_files=[], admin_password=None,
                         network_info=network_info,
                         block_device_info=block_device_info)

    def _test_spawn_instance(self, cow):
        self._spawn_instance(cow)

        self.assertTrue(self._hypervutils.vm_exists(
            self._instance_data["name"]))

        vmstate = self._hypervutils.get_vm_state(self._instance_data["name"])
        self.assertEquals(vmstate, constants.HYPERV_VM_STATE_ENABLED)

        (vhd_paths, _) = self._hypervutils.get_vm_disks(
            self._instance_data["name"])
        self.assertEquals(len(vhd_paths), 1)

        parent_path = self._hypervutils.get_vhd_parent_path(vhd_paths[0])
        if cow:
            self.assertTrue(not parent_path is None)
            self.assertEquals(self._fetched_image, parent_path)
        else:
            self.assertTrue(parent_path is None)
            self.assertEquals(self._fetched_image, vhd_paths[0])

    def _attach_volume(self):
        self._spawn_instance(True)
        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)

        self._conn.attach_volume(connection_info,
            self._instance_data["name"], '/dev/sdc')

    def test_attach_volume(self):
        self._attach_volume()

        (_, volumes_paths) = self._hypervutils.get_vm_disks(
            self._instance_data["name"])
        self.assertEquals(len(volumes_paths), 1)

        sessions_exist = self._hypervutils.iscsi_volume_sessions_exist(
            self._volume_id)
        self.assertTrue(sessions_exist)

    def test_detach_volume(self):
        self._attach_volume()
        connection_info = db_fakes.get_fake_volume_info_data(
            self._volume_target_portal, self._volume_id)

        self._conn.detach_volume(connection_info,
            self._instance_data["name"], '/dev/sdc')

        (_, volumes_paths) = self._hypervutils.get_vm_disks(
            self._instance_data["name"])
        self.assertEquals(len(volumes_paths), 0)

        sessions_exist = self._hypervutils.iscsi_volume_sessions_exist(
            self._volume_id)
        self.assertFalse(sessions_exist)

    def test_boot_from_volume(self):
        block_device_info = db_fakes.get_fake_block_device_info(
            self._volume_target_portal, self._volume_id)

        self._spawn_instance(False, block_device_info)

        (_, volumes_paths) = self._hypervutils.get_vm_disks(
            self._instance_data["name"])

        self.assertEquals(len(volumes_paths), 1)

        sessions_exist = self._hypervutils.iscsi_volume_sessions_exist(
            self._volume_id)
        self.assertTrue(sessions_exist)

    def test_attach_volume_with_target_connection_failure(self):
        self._spawn_instance(True)

        target = 'nonexistingtarget:3260'
        connection_info = db_fakes.get_fake_volume_info_data(target,
            self._volume_id)

        self.assertRaises(vmutils.HyperVException, self._conn.attach_volume,
            connection_info, self._instance_data["name"], '/dev/sdc')
