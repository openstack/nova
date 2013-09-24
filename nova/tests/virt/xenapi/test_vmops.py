# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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


from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_mode
from nova import exception
from nova import test
from nova.tests.virt.xenapi import stubs
from nova.virt import fake
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops


class VMOpsTestBase(stubs.XenAPITestBase):
    def setUp(self):
        super(VMOpsTestBase, self).setUp()
        self._setup_mock_vmops()
        self.vms = []

    def _setup_mock_vmops(self, product_brand=None, product_version=None):
        stubs.stubout_session(self.stubs, xenapi_fake.SessionBase)
        self._session = xenapi_conn.XenAPISession('test_url', 'root',
                                                  'test_pass',
                                                  fake.FakeVirtAPI())
        self.vmops = vmops.VMOps(self._session, fake.FakeVirtAPI())

    def create_vm(self, name, state="running"):
        vm_ref = xenapi_fake.create_vm(name, state)
        self.vms.append(vm_ref)
        vm = xenapi_fake.get_record("VM", vm_ref)
        return vm, vm_ref

    def tearDown(self):
        super(VMOpsTestBase, self).tearDown()
        for vm in self.vms:
            xenapi_fake.destroy_vm(vm)


class VMOpsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMOpsTestCase, self).setUp()
        self._setup_mock_vmops()

    def _setup_mock_vmops(self, product_brand=None, product_version=None):
        self._session = self._get_mock_session(product_brand, product_version)
        self._vmops = vmops.VMOps(self._session, fake.FakeVirtAPI())

    def _get_mock_session(self, product_brand, product_version):
        class Mock(object):
            pass

        mock_session = Mock()
        mock_session.product_brand = product_brand
        mock_session.product_version = product_version
        return mock_session

    def test_check_resize_func_name_defaults_to_VDI_resize(self):
        self.assertEquals(
            'VDI.resize',
            self._vmops.check_resize_func_name())

    def _test_finish_revert_migration_after_crash(self, backup_made, new_made):
        instance = {'name': 'foo',
                    'task_state': task_states.RESIZE_MIGRATING}

        self.mox.StubOutWithMock(vm_utils, 'lookup')
        self.mox.StubOutWithMock(self._vmops, '_destroy')
        self.mox.StubOutWithMock(vm_utils, 'set_vm_name_label')
        self.mox.StubOutWithMock(self._vmops, '_attach_mapped_block_devices')
        self.mox.StubOutWithMock(self._vmops, '_start')

        vm_utils.lookup(self._session, 'foo-orig').AndReturn(
            backup_made and 'foo' or None)
        vm_utils.lookup(self._session, 'foo').AndReturn(
            (not backup_made or new_made) and 'foo' or None)
        if backup_made:
            if new_made:
                self._vmops._destroy(instance, 'foo')
            vm_utils.set_vm_name_label(self._session, 'foo', 'foo')
            self._vmops._attach_mapped_block_devices(instance, [])
        self._vmops._start(instance, 'foo')

        self.mox.ReplayAll()

        self._vmops.finish_revert_migration(instance, [])

    def test_finish_revert_migration_after_crash(self):
        self._test_finish_revert_migration_after_crash(True, True)

    def test_finish_revert_migration_after_crash_before_new(self):
        self._test_finish_revert_migration_after_crash(True, False)

    def test_finish_revert_migration_after_crash_before_backup(self):
        self._test_finish_revert_migration_after_crash(False, False)

    def test_determine_vm_mode_returns_xen(self):
        self.mox.StubOutWithMock(vm_mode, 'get_from_instance')

        fake_instance = "instance"
        vm_mode.get_from_instance(fake_instance).AndReturn(vm_mode.XEN)

        self.mox.ReplayAll()
        self.assertEquals(vm_mode.XEN,
            self._vmops._determine_vm_mode(fake_instance, None, None))
        self.mox.VerifyAll()

    def test_determine_vm_mode_returns_hvm(self):
        self.mox.StubOutWithMock(vm_mode, 'get_from_instance')

        fake_instance = "instance"
        vm_mode.get_from_instance(fake_instance).AndReturn(vm_mode.HVM)

        self.mox.ReplayAll()
        self.assertEquals(vm_mode.HVM,
            self._vmops._determine_vm_mode(fake_instance, None, None))
        self.mox.VerifyAll()

    def test_determine_vm_mode_returns_is_pv(self):
        self.mox.StubOutWithMock(vm_mode, 'get_from_instance')
        self.mox.StubOutWithMock(vm_utils, 'determine_is_pv')

        fake_instance = {"os_type": "foo"}
        fake_vdis = {'root': {"ref": 'fake'}}
        fake_disk_type = "disk"
        vm_mode.get_from_instance(fake_instance).AndReturn(None)
        vm_utils.determine_is_pv(self._session, "fake", fake_disk_type,
            "foo").AndReturn(True)

        self.mox.ReplayAll()
        self.assertEquals(vm_mode.XEN,
            self._vmops._determine_vm_mode(fake_instance, fake_vdis,
                                     fake_disk_type))
        self.mox.VerifyAll()

    def test_determine_vm_mode_returns_is_not_pv(self):
        self.mox.StubOutWithMock(vm_mode, 'get_from_instance')
        self.mox.StubOutWithMock(vm_utils, 'determine_is_pv')

        fake_instance = {"os_type": "foo"}
        fake_vdis = {'root': {"ref": 'fake'}}
        fake_disk_type = "disk"
        vm_mode.get_from_instance(fake_instance).AndReturn(None)
        vm_utils.determine_is_pv(self._session, "fake", fake_disk_type,
            "foo").AndReturn(False)

        self.mox.ReplayAll()
        self.assertEquals(vm_mode.HVM,
            self._vmops._determine_vm_mode(fake_instance, fake_vdis,
                                     fake_disk_type))
        self.mox.VerifyAll()

    def test_determine_vm_mode_returns_is_not_pv_no_root_disk(self):
        self.mox.StubOutWithMock(vm_mode, 'get_from_instance')
        self.mox.StubOutWithMock(vm_utils, 'determine_is_pv')

        fake_instance = {"os_type": "foo"}
        fake_vdis = {'iso': {"ref": 'fake'}}
        fake_disk_type = "disk"
        vm_mode.get_from_instance(fake_instance).AndReturn(None)

        self.mox.ReplayAll()
        self.assertEquals(vm_mode.HVM,
            self._vmops._determine_vm_mode(fake_instance, fake_vdis,
                                     fake_disk_type))
        self.mox.VerifyAll()

    def test_xsm_sr_check_relaxed_cached(self):
        self.make_plugin_call_count = 0

        def fake_make_plugin_call(plugin, method, **args):
            self.make_plugin_call_count = self.make_plugin_call_count + 1
            return "true"

        self.stubs.Set(self._vmops, "_make_plugin_call",
                       fake_make_plugin_call)

        self.assertTrue(self._vmops._is_xsm_sr_check_relaxed())
        self.assertTrue(self._vmops._is_xsm_sr_check_relaxed())

        self.assertEqual(self.make_plugin_call_count, 1)

    def test_get_vm_opaque_ref_raises_instance_not_found(self):
        instance = {"name": "dummy"}
        self.mox.StubOutWithMock(vm_utils, 'lookup')
        vm_utils.lookup(self._session, instance['name'], False).AndReturn(None)
        self.mox.ReplayAll()

        self.assertRaises(exception.InstanceNotFound,
                self._vmops._get_vm_opaque_ref, instance)


class InjectAutoDiskConfigTestCase(VMOpsTestBase):
    def setUp(self):
        super(InjectAutoDiskConfigTestCase, self).setUp()

    def test_inject_auto_disk_config_when_present(self):
        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": True}
        self.vmops._inject_auto_disk_config(instance, vm_ref)
        xenstore_data = vm['xenstore_data']
        self.assertEquals(xenstore_data['vm-data/auto-disk-config'], 'True')

    def test_inject_auto_disk_config_none_as_false(self):
        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": None}
        self.vmops._inject_auto_disk_config(instance, vm_ref)
        xenstore_data = vm['xenstore_data']
        self.assertEquals(xenstore_data['vm-data/auto-disk-config'], 'False')


class GetConsoleOutputTestCase(VMOpsTestBase):
    def setUp(self):
        super(GetConsoleOutputTestCase, self).setUp()

    def test_get_console_output_works(self):
        self.mox.StubOutWithMock(self.vmops, '_get_dom_id')

        instance = {"name": "dummy"}
        self.vmops._get_dom_id(instance, check_rescue=True).AndReturn(42)
        self.mox.ReplayAll()

        self.assertEqual("dom_id: 42", self.vmops.get_console_output(instance))

    def test_get_console_output_throws_nova_exception(self):
        self.mox.StubOutWithMock(self.vmops, '_get_dom_id')

        instance = {"name": "dummy"}
        # dom_id=0 used to trigger exception in fake XenAPI
        self.vmops._get_dom_id(instance, check_rescue=True).AndReturn(0)
        self.mox.ReplayAll()

        self.assertRaises(exception.NovaException,
                self.vmops.get_console_output, instance)

    def test_get_dom_id_works(self):
        instance = {"name": "dummy"}
        vm, vm_ref = self.create_vm("dummy")
        self.assertEqual(vm["domid"], self.vmops._get_dom_id(instance))

    def test_get_dom_id_works_with_rescue_vm(self):
        instance = {"name": "dummy"}
        vm, vm_ref = self.create_vm("dummy-rescue")
        self.assertEqual(vm["domid"],
                self.vmops._get_dom_id(instance, check_rescue=True))

    def test_get_dom_id_raises_not_found(self):
        instance = {"name": "dummy"}
        self.create_vm("not-dummy")
        self.assertRaises(exception.NotFound, self.vmops._get_dom_id, instance)

    def test_get_dom_id_works_with_vmref(self):
        vm, vm_ref = self.create_vm("dummy")
        self.assertEqual(vm["domid"],
                         self.vmops._get_dom_id(vm_ref=vm_ref))


class SpawnTestCase(VMOpsTestBase):
    def _stub_out_common(self):
        self.mox.StubOutWithMock(self.vmops, '_ensure_instance_name_unique')
        self.mox.StubOutWithMock(self.vmops, '_ensure_enough_free_mem')
        self.mox.StubOutWithMock(self.vmops, '_update_instance_progress')
        self.mox.StubOutWithMock(vm_utils, 'determine_disk_image_type')
        self.mox.StubOutWithMock(vm_utils, 'get_vdis_for_instance')
        self.mox.StubOutWithMock(vm_utils, 'safe_destroy_vdis')
        self.mox.StubOutWithMock(self.vmops, '_resize_up_root_vdi')
        self.mox.StubOutWithMock(vm_utils,
                                 'create_kernel_and_ramdisk')
        self.mox.StubOutWithMock(vm_utils, 'destroy_kernel_ramdisk')
        self.mox.StubOutWithMock(self.vmops, '_create_vm_record')
        self.mox.StubOutWithMock(self.vmops, '_destroy')
        self.mox.StubOutWithMock(self.vmops, '_attach_disks')
        self.mox.StubOutWithMock(self.vmops, '_attach_orig_disk_for_rescue')
        self.mox.StubOutWithMock(self.vmops, 'inject_network_info')
        self.mox.StubOutWithMock(self.vmops, '_inject_hostname')
        self.mox.StubOutWithMock(self.vmops, '_inject_instance_metadata')
        self.mox.StubOutWithMock(self.vmops, '_inject_auto_disk_config')
        self.mox.StubOutWithMock(self.vmops, '_file_inject_vm_settings')
        self.mox.StubOutWithMock(self.vmops, '_create_vifs')
        self.mox.StubOutWithMock(self.vmops.firewall_driver,
                                 'setup_basic_filtering')
        self.mox.StubOutWithMock(self.vmops.firewall_driver,
                                 'prepare_instance_filter')
        self.mox.StubOutWithMock(self.vmops, '_start')
        self.mox.StubOutWithMock(self.vmops, '_wait_for_instance_to_start')
        self.mox.StubOutWithMock(self.vmops,
                                 '_configure_new_instance_with_agent')
        self.mox.StubOutWithMock(self.vmops, '_remove_hostname')
        self.mox.StubOutWithMock(self.vmops.firewall_driver,
                                 'apply_instance_filter')

    def _test_spawn(self, name_label_param=None, block_device_info_param=None,
                    rescue=False, include_root_vdi=True,
                    throw_exception=None):
        self._stub_out_common()

        instance = {"name": "dummy", "uuid": "fake_uuid"}
        name_label = name_label_param
        if name_label is None:
            name_label = "dummy"
        image_meta = {"id": "image_id"}
        context = "context"
        session = self.vmops._session
        injected_files = "fake_files"
        admin_password = "password"
        network_info = "net_info"
        steps = 10
        if rescue:
            steps += 1

        block_device_info = block_device_info_param
        if block_device_info and not block_device_info['root_device_name']:
            block_device_info = dict(block_device_info_param)
            block_device_info['root_device_name'] = \
                                                self.vmops.default_root_dev

        di_type = "di_type"
        vm_utils.determine_disk_image_type(image_meta).AndReturn(di_type)
        step = 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        vdis = {"other": {"ref": "fake_ref_2", "osvol": True}}
        if include_root_vdi:
            vdis["root"] = {"ref": "fake_ref"}
        vm_utils.get_vdis_for_instance(context, session, instance, name_label,
                    "image_id", di_type,
                    block_device_info=block_device_info).AndReturn(vdis)
        if include_root_vdi:
            self.vmops._resize_up_root_vdi(instance, vdis["root"])
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        kernel_file = "kernel"
        ramdisk_file = "ramdisk"
        vm_utils.create_kernel_and_ramdisk(context, session,
                instance, name_label).AndReturn((kernel_file, ramdisk_file))
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        vm_ref = "fake_vm_ref"
        self.vmops._ensure_instance_name_unique(name_label)
        self.vmops._ensure_enough_free_mem(instance)
        self.vmops._create_vm_record(context, instance, name_label, vdis,
                di_type, kernel_file, ramdisk_file).AndReturn(vm_ref)
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        self.vmops._attach_disks(instance, vm_ref, name_label, vdis, di_type,
                          admin_password, injected_files)
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        self.vmops._inject_instance_metadata(instance, vm_ref)
        self.vmops._inject_auto_disk_config(instance, vm_ref)
        self.vmops._inject_hostname(instance, vm_ref, rescue)
        self.vmops._file_inject_vm_settings(instance, vm_ref, vdis,
                                            network_info)
        self.vmops.inject_network_info(instance, network_info, vm_ref)
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        self.vmops._create_vifs(instance, vm_ref, network_info)
        self.vmops.firewall_driver.setup_basic_filtering(instance,
                network_info).AndRaise(NotImplementedError)
        self.vmops.firewall_driver.prepare_instance_filter(instance,
                                                           network_info)
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        if rescue:
            self.vmops._attach_orig_disk_for_rescue(instance, vm_ref)
            step += 1
            self.vmops._update_instance_progress(context, instance, step,
                                                 steps)
        self.vmops._start(instance, vm_ref)
        self.vmops._wait_for_instance_to_start(instance, vm_ref)
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        self.vmops._configure_new_instance_with_agent(instance, vm_ref,
                injected_files, admin_password)
        self.vmops._remove_hostname(instance, vm_ref)
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        self.vmops.firewall_driver.apply_instance_filter(instance,
                                                         network_info)
        step += 1
        last_call = self.vmops._update_instance_progress(context, instance,
                                                         step, steps)
        if throw_exception:
            last_call.AndRaise(throw_exception)
            self.vmops._destroy(instance, vm_ref, network_info=network_info)
            vm_utils.destroy_kernel_ramdisk(self.vmops._session, instance,
                                            kernel_file, ramdisk_file)
            vm_utils.safe_destroy_vdis(self.vmops._session, ["fake_ref"])

        self.mox.ReplayAll()
        self.vmops.spawn(context, instance, image_meta, injected_files,
                         admin_password, network_info,
                         block_device_info_param, name_label_param, rescue)

    def test_spawn(self):
        self._test_spawn()

    def test_spawn_with_alternate_options(self):
        self._test_spawn(include_root_vdi=False, rescue=True,
                         name_label_param="bob",
                         block_device_info_param={"root_device_name": ""})

    def test_spawn_performs_rollback_and_throws_exception(self):
        self.assertRaises(test.TestingException, self._test_spawn,
                          throw_exception=test.TestingException())

    def _test_finish_migration(self, power_on=True, resize_instance=True,
                               throw_exception=None):
        self._stub_out_common()
        self.mox.StubOutWithMock(vm_utils, "move_disks")
        self.mox.StubOutWithMock(self.vmops, "_attach_mapped_block_devices")

        context = "context"
        migration = {}
        name_label = "dummy"
        instance = {"name": name_label, "uuid": "fake_uuid"}
        disk_info = "disk_info"
        network_info = "net_info"
        image_meta = {"id": "image_id"}
        block_device_info = "bdi"
        session = self.vmops._session

        self.vmops._ensure_instance_name_unique(name_label)
        self.vmops._ensure_enough_free_mem(instance)

        di_type = "di_type"
        vm_utils.determine_disk_image_type(image_meta).AndReturn(di_type)

        root_vdi = {"ref": "fake_ref"}
        vdis = {"root": root_vdi}
        vm_utils.move_disks(self.vmops._session, instance,
                            disk_info).AndReturn(root_vdi)

        kernel_file = "kernel"
        ramdisk_file = "ramdisk"
        vm_utils.create_kernel_and_ramdisk(context, session,
                instance, name_label).AndReturn((kernel_file, ramdisk_file))

        vm_ref = "fake_vm_ref"
        self.vmops._create_vm_record(context, instance, name_label, vdis,
                di_type, kernel_file, ramdisk_file).AndReturn(vm_ref)

        if resize_instance:
            self.vmops._resize_up_root_vdi(instance, root_vdi)
        self.vmops._attach_disks(instance, vm_ref, name_label, vdis, di_type,
                                 None, None)
        self.vmops._attach_mapped_block_devices(instance, block_device_info)

        self.vmops._inject_instance_metadata(instance, vm_ref)
        self.vmops._inject_auto_disk_config(instance, vm_ref)
        self.vmops._file_inject_vm_settings(instance, vm_ref, vdis,
                                            network_info)
        self.vmops.inject_network_info(instance, network_info, vm_ref)

        self.vmops._create_vifs(instance, vm_ref, network_info)
        self.vmops.firewall_driver.setup_basic_filtering(instance,
                network_info).AndRaise(NotImplementedError)
        self.vmops.firewall_driver.prepare_instance_filter(instance,
                                                           network_info)

        if power_on:
            self.vmops._start(instance, vm_ref)
            self.vmops._wait_for_instance_to_start(instance, vm_ref)

        self.vmops.firewall_driver.apply_instance_filter(instance,
                                                         network_info)

        last_call = self.vmops._update_instance_progress(context, instance,
                                                        step=5, total_steps=5)
        if throw_exception:
            last_call.AndRaise(throw_exception)
            self.vmops._destroy(instance, vm_ref, network_info=network_info)
            vm_utils.destroy_kernel_ramdisk(self.vmops._session, instance,
                                            kernel_file, ramdisk_file)
            vm_utils.safe_destroy_vdis(self.vmops._session, ["fake_ref"])

        self.mox.ReplayAll()
        self.vmops.finish_migration(context, migration, instance, disk_info,
                                    network_info, image_meta, resize_instance,
                                    block_device_info, power_on)

    def test_finish_migration(self):
        self._test_finish_migration()

    def test_finish_migration_no_power_on(self):
        self._test_finish_migration(power_on=False, resize_instance=False)

    def test_finish_migrate_performs_rollback_on_error(self):
        self.assertRaises(test.TestingException, self._test_finish_migration,
                          power_on=False, resize_instance=False,
                          throw_exception=test.TestingException())

    def test_remove_hostname(self):
        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": None}
        self.mox.StubOutWithMock(self._session, 'call_xenapi')
        self._session.call_xenapi("VM.remove_from_xenstore_data", vm_ref,
                                  "vm-data/hostname")

        self.mox.ReplayAll()
        self.vmops._remove_hostname(instance, vm_ref)
        self.mox.VerifyAll()

    def test_inject_hostname(self):
        instance = {"hostname": "dummy", "os_type": "fake", "uuid": "uuid"}
        vm_ref = "vm_ref"

        self.mox.StubOutWithMock(self.vmops, '_add_to_param_xenstore')
        self.vmops._add_to_param_xenstore(vm_ref, 'vm-data/hostname', 'dummy')

        self.mox.ReplayAll()
        self.vmops._inject_hostname(instance, vm_ref, rescue=False)

    def test_inject_hostname_with_rescue_prefix(self):
        instance = {"hostname": "dummy", "os_type": "fake", "uuid": "uuid"}
        vm_ref = "vm_ref"

        self.mox.StubOutWithMock(self.vmops, '_add_to_param_xenstore')
        self.vmops._add_to_param_xenstore(vm_ref, 'vm-data/hostname',
                                          'RESCUE-dummy')

        self.mox.ReplayAll()
        self.vmops._inject_hostname(instance, vm_ref, rescue=True)

    def test_inject_hostname_with_windows_name_truncation(self):
        instance = {"hostname": "dummydummydummydummydummy",
                    "os_type": "windows", "uuid": "uuid"}
        vm_ref = "vm_ref"

        self.mox.StubOutWithMock(self.vmops, '_add_to_param_xenstore')
        self.vmops._add_to_param_xenstore(vm_ref, 'vm-data/hostname',
                                          'RESCUE-dummydum')

        self.mox.ReplayAll()
        self.vmops._inject_hostname(instance, vm_ref, rescue=True)

    def test_wait_for_instance_to_start(self):
        instance = {"uuid": "uuid"}
        vm_ref = "vm_ref"

        self.mox.StubOutWithMock(self.vmops, 'get_info')
        self.vmops.get_info(instance, vm_ref).AndReturn({"state": "asdf"})
        self.vmops.get_info(instance, vm_ref).AndReturn({
                                            "state": power_state.RUNNING})

        self.mox.ReplayAll()
        self.vmops._wait_for_instance_to_start(instance, vm_ref)

    def test_attach_orig_disk_for_rescue(self):
        instance = {"name": "dummy"}
        vm_ref = "vm_ref"

        self.mox.StubOutWithMock(vm_utils, 'lookup')
        self.mox.StubOutWithMock(self.vmops, '_find_root_vdi_ref')
        self.mox.StubOutWithMock(vm_utils, 'create_vbd')

        vm_utils.lookup(self.vmops._session, "dummy").AndReturn("ref")
        self.vmops._find_root_vdi_ref("ref").AndReturn("vdi_ref")
        vm_utils.create_vbd(self.vmops._session, vm_ref, "vdi_ref",
                            vmops.DEVICE_RESCUE, bootable=False)

        self.mox.ReplayAll()
        self.vmops._attach_orig_disk_for_rescue(instance, vm_ref)
