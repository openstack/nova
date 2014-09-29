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

from eventlet import greenthread
import mock

from nova.compute import power_state
from nova.compute import task_states
from nova import context
from nova import exception
from nova import objects
from nova.pci import manager as pci_manager
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.xenapi import stubs
from nova.virt import fake
from nova.virt.xenapi import agent as xenapi_agent
from nova.virt.xenapi.client import session as xenapi_session
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import volumeops


class VMOpsTestBase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(VMOpsTestBase, self).setUp()
        self._setup_mock_vmops()
        self.vms = []

    def _setup_mock_vmops(self, product_brand=None, product_version=None):
        stubs.stubout_session(self.stubs, xenapi_fake.SessionBase)
        self._session = xenapi_session.XenAPISession('test_url', 'root',
                                                     'test_pass')
        self.vmops = vmops.VMOps(self._session, fake.FakeVirtAPI())

    def create_vm(self, name, state="Running"):
        vm_ref = xenapi_fake.create_vm(name, state)
        self.vms.append(vm_ref)
        vm = xenapi_fake.get_record("VM", vm_ref)
        return vm, vm_ref

    def tearDown(self):
        super(VMOpsTestBase, self).tearDown()
        for vm in self.vms:
            xenapi_fake.destroy_vm(vm)


class VMOpsTestCase(VMOpsTestBase):
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

    def _test_finish_revert_migration_after_crash(self, backup_made, new_made,
                                                  vm_shutdown=True):
        instance = {'name': 'foo',
                    'task_state': task_states.RESIZE_MIGRATING}
        context = 'fake_context'

        self.mox.StubOutWithMock(vm_utils, 'lookup')
        self.mox.StubOutWithMock(self._vmops, '_destroy')
        self.mox.StubOutWithMock(vm_utils, 'set_vm_name_label')
        self.mox.StubOutWithMock(self._vmops, '_attach_mapped_block_devices')
        self.mox.StubOutWithMock(self._vmops, '_start')
        self.mox.StubOutWithMock(vm_utils, 'is_vm_shutdown')

        vm_utils.lookup(self._session, 'foo-orig').AndReturn(
            backup_made and 'foo' or None)
        vm_utils.lookup(self._session, 'foo').AndReturn(
            (not backup_made or new_made) and 'foo' or None)
        if backup_made:
            if new_made:
                self._vmops._destroy(instance, 'foo')
            vm_utils.set_vm_name_label(self._session, 'foo', 'foo')
            self._vmops._attach_mapped_block_devices(instance, [])

        vm_utils.is_vm_shutdown(self._session, 'foo').AndReturn(vm_shutdown)
        if vm_shutdown:
            self._vmops._start(instance, 'foo')

        self.mox.ReplayAll()

        self._vmops.finish_revert_migration(context, instance, [])

    def test_finish_revert_migration_after_crash(self):
        self._test_finish_revert_migration_after_crash(True, True)

    def test_finish_revert_migration_after_crash_before_new(self):
        self._test_finish_revert_migration_after_crash(True, False)

    def test_finish_revert_migration_after_crash_before_backup(self):
        self._test_finish_revert_migration_after_crash(False, False)

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
    def test_inject_auto_disk_config_when_present(self):
        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": True}
        self.vmops._inject_auto_disk_config(instance, vm_ref)
        xenstore_data = vm['xenstore_data']
        self.assertEqual(xenstore_data['vm-data/auto-disk-config'], 'True')

    def test_inject_auto_disk_config_none_as_false(self):
        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": None}
        self.vmops._inject_auto_disk_config(instance, vm_ref)
        xenstore_data = vm['xenstore_data']
        self.assertEqual(xenstore_data['vm-data/auto-disk-config'], 'False')


class GetConsoleOutputTestCase(VMOpsTestBase):
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
        self.mox.StubOutWithMock(self.vmops, '_get_vdis_for_instance')
        self.mox.StubOutWithMock(vm_utils, 'safe_destroy_vdis')
        self.mox.StubOutWithMock(self.vmops._volumeops,
                                 'safe_cleanup_from_vdis')
        self.mox.StubOutWithMock(self.vmops, '_resize_up_vdis')
        self.mox.StubOutWithMock(vm_utils,
                                 'create_kernel_and_ramdisk')
        self.mox.StubOutWithMock(vm_utils, 'destroy_kernel_ramdisk')
        self.mox.StubOutWithMock(self.vmops, '_create_vm_record')
        self.mox.StubOutWithMock(self.vmops, '_destroy')
        self.mox.StubOutWithMock(self.vmops, '_attach_disks')
        self.mox.StubOutWithMock(pci_manager, 'get_instance_pci_devs')
        self.mox.StubOutWithMock(vm_utils, 'set_other_config_pci')
        self.mox.StubOutWithMock(self.vmops, '_attach_orig_disks')
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
                    rescue=False, include_root_vdi=True, throw_exception=None,
                    attach_pci_dev=False):
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
        self.vmops._get_vdis_for_instance(context, instance,
                name_label, "image_id", di_type,
                block_device_info).AndReturn(vdis)
        self.vmops._resize_up_vdis(instance, vdis)
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
        self.vmops._create_vm_record(context, instance, name_label,
                di_type, kernel_file,
                ramdisk_file, image_meta).AndReturn(vm_ref)
        step += 1
        self.vmops._update_instance_progress(context, instance, step, steps)

        self.vmops._attach_disks(instance, vm_ref, name_label, vdis, di_type,
                          network_info, rescue, admin_password, injected_files)
        if attach_pci_dev:
            fake_dev = {
                'created_at': None,
                'updated_at': None,
                'deleted_at': None,
                'deleted': None,
                'id': 1,
                'compute_node_id': 1,
                'address': '00:00.0',
                'vendor_id': '1234',
                'product_id': 'abcd',
                'dev_type': 'type-PCI',
                'status': 'available',
                'dev_id': 'devid',
                'label': 'label',
                'instance_uuid': None,
                'extra_info': '{}',
            }
            pci_manager.get_instance_pci_devs(instance).AndReturn([fake_dev])
            vm_utils.set_other_config_pci(self.vmops._session,
                                          vm_ref,
                                          "0/0000:00:00.0")
        else:
            pci_manager.get_instance_pci_devs(instance).AndReturn([])
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
            self.vmops._attach_orig_disks(instance, vm_ref)
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
            self.vmops._volumeops.safe_cleanup_from_vdis(["fake_ref_2"])

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

    def test_spawn_with_pci_available_on_the_host(self):
        self._test_spawn(attach_pci_dev=True)

    def test_spawn_performs_rollback_and_throws_exception(self):
        self.assertRaises(test.TestingException, self._test_spawn,
                          throw_exception=test.TestingException())

    def _test_finish_migration(self, power_on=True, resize_instance=True,
                               throw_exception=None, booted_from_volume=False):
        self._stub_out_common()
        self.mox.StubOutWithMock(volumeops.VolumeOps, "connect_volume")
        self.mox.StubOutWithMock(self.vmops._session, 'call_xenapi')
        self.mox.StubOutWithMock(vm_utils, "import_all_migrated_disks")
        self.mox.StubOutWithMock(self.vmops, "_attach_mapped_block_devices")

        context = "context"
        migration = {}
        name_label = "dummy"
        instance = {"name": name_label, "uuid": "fake_uuid",
                "root_device_name": "/dev/xvda"}
        disk_info = "disk_info"
        network_info = "net_info"
        image_meta = {"id": "image_id"}
        block_device_info = {}
        import_root = True
        if booted_from_volume:
            block_device_info = {'block_device_mapping': [
                {'mount_device': '/dev/xvda',
                 'connection_info': {'data': 'fake-data'}}]}
            import_root = False
            volumeops.VolumeOps.connect_volume(
                    {'data': 'fake-data'}).AndReturn(('sr', 'vol-vdi-uuid'))
            self.vmops._session.call_xenapi('VDI.get_by_uuid',
                    'vol-vdi-uuid').AndReturn('vol-vdi-ref')
        session = self.vmops._session

        self.vmops._ensure_instance_name_unique(name_label)
        self.vmops._ensure_enough_free_mem(instance)

        di_type = "di_type"
        vm_utils.determine_disk_image_type(image_meta).AndReturn(di_type)

        root_vdi = {"ref": "fake_ref"}
        ephemeral_vdi = {"ref": "fake_ref_e"}
        vdis = {"root": root_vdi, "ephemerals": {4: ephemeral_vdi}}
        vm_utils.import_all_migrated_disks(self.vmops._session, instance,
                import_root=import_root).AndReturn(vdis)

        kernel_file = "kernel"
        ramdisk_file = "ramdisk"
        vm_utils.create_kernel_and_ramdisk(context, session,
                instance, name_label).AndReturn((kernel_file, ramdisk_file))

        vm_ref = "fake_vm_ref"
        self.vmops._create_vm_record(context, instance, name_label,
                di_type, kernel_file,
                ramdisk_file, image_meta).AndReturn(vm_ref)

        if resize_instance:
            self.vmops._resize_up_vdis(instance, vdis)
        self.vmops._attach_disks(instance, vm_ref, name_label, vdis, di_type,
                                 network_info, False, None, None)
        self.vmops._attach_mapped_block_devices(instance, block_device_info)
        pci_manager.get_instance_pci_devs(instance).AndReturn([])

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
            vm_utils.safe_destroy_vdis(self.vmops._session,
                                       ["fake_ref_e", "fake_ref"])

        self.mox.ReplayAll()
        self.vmops.finish_migration(context, migration, instance, disk_info,
                                    network_info, image_meta, resize_instance,
                                    block_device_info, power_on)

    def test_finish_migration(self):
        self._test_finish_migration()

    def test_finish_migration_no_power_on(self):
        self._test_finish_migration(power_on=False, resize_instance=False)

    def test_finish_migration_booted_from_volume(self):
        self._test_finish_migration(booted_from_volume=True)

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

    def test_reset_network(self):
        class mock_agent(object):
            def __init__(self):
                self.called = False

            def resetnetwork(self):
                self.called = True

        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": None}
        agent = mock_agent()

        self.mox.StubOutWithMock(self.vmops, 'agent_enabled')
        self.mox.StubOutWithMock(self.vmops, '_get_agent')
        self.mox.StubOutWithMock(self.vmops, '_inject_hostname')
        self.mox.StubOutWithMock(self.vmops, '_remove_hostname')

        self.vmops.agent_enabled(instance).AndReturn(True)
        self.vmops._get_agent(instance, vm_ref).AndReturn(agent)
        self.vmops._inject_hostname(instance, vm_ref, False)
        self.vmops._remove_hostname(instance, vm_ref)
        self.mox.ReplayAll()
        self.vmops.reset_network(instance)
        self.assertTrue(agent.called)
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

        self.mox.StubOutWithMock(vm_utils, 'get_power_state')
        self.mox.StubOutWithMock(greenthread, 'sleep')
        vm_utils.get_power_state(self._session, vm_ref).AndReturn(
                                             power_state.SHUTDOWN)
        greenthread.sleep(0.5)
        vm_utils.get_power_state(self._session, vm_ref).AndReturn(
                                            power_state.RUNNING)

        self.mox.ReplayAll()
        self.vmops._wait_for_instance_to_start(instance, vm_ref)

    def test_attach_orig_disks(self):
        instance = {"name": "dummy"}
        vm_ref = "vm_ref"
        vbd_refs = {vmops.DEVICE_ROOT: "vdi_ref"}

        self.mox.StubOutWithMock(vm_utils, 'lookup')
        self.mox.StubOutWithMock(self.vmops, '_find_vdi_refs')
        self.mox.StubOutWithMock(vm_utils, 'create_vbd')

        vm_utils.lookup(self.vmops._session, "dummy").AndReturn("ref")
        self.vmops._find_vdi_refs("ref", exclude_volumes=True).AndReturn(
                vbd_refs)
        vm_utils.create_vbd(self.vmops._session, vm_ref, "vdi_ref",
                            vmops.DEVICE_RESCUE, bootable=False)

        self.mox.ReplayAll()
        self.vmops._attach_orig_disks(instance, vm_ref)

    def test_agent_update_setup(self):
        # agent updates need to occur after networking is configured
        instance = {'name': 'betelgeuse',
                    'uuid': '1-2-3-4-5-6'}
        vm_ref = 'vm_ref'
        agent = xenapi_agent.XenAPIBasedAgent(self.vmops._session,
                self.vmops._virtapi, instance, vm_ref)

        self.mox.StubOutWithMock(xenapi_agent, 'should_use_agent')
        self.mox.StubOutWithMock(self.vmops, '_get_agent')
        self.mox.StubOutWithMock(agent, 'get_version')
        self.mox.StubOutWithMock(agent, 'resetnetwork')
        self.mox.StubOutWithMock(agent, 'update_if_needed')

        xenapi_agent.should_use_agent(instance).AndReturn(True)
        self.vmops._get_agent(instance, vm_ref).AndReturn(agent)
        agent.get_version().AndReturn('1.2.3')
        agent.resetnetwork()
        agent.update_if_needed('1.2.3')

        self.mox.ReplayAll()
        self.vmops._configure_new_instance_with_agent(instance, vm_ref,
                None, None)


class DestroyTestCase(VMOpsTestBase):
    def setUp(self):
        super(DestroyTestCase, self).setUp()
        self.context = context.RequestContext(user_id=None, project_id=None)
        self.instance = fake_instance.fake_instance_obj(self.context)

    @mock.patch.object(vm_utils, 'lookup', side_effect=[None, None])
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    @mock.patch.object(volume_utils, 'find_sr_by_uuid')
    @mock.patch.object(volume_utils, 'forget_sr')
    def test_no_vm_no_bdm(self, forget_sr, find_sr_by_uuid, hard_shutdown_vm,
            lookup):
        self.vmops.destroy(self.instance, 'network_info',
                {'block_device_mapping': []})
        self.assertEqual(0, find_sr_by_uuid.call_count)
        self.assertEqual(0, forget_sr.call_count)
        self.assertEqual(0, hard_shutdown_vm.call_count)

    @mock.patch.object(vm_utils, 'lookup', side_effect=[None, None])
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    @mock.patch.object(volume_utils, 'find_sr_by_uuid', return_value=None)
    @mock.patch.object(volume_utils, 'forget_sr')
    def test_no_vm_orphaned_volume_no_sr(self, forget_sr, find_sr_by_uuid,
            hard_shutdown_vm, lookup):
        self.vmops.destroy(self.instance, 'network_info',
                {'block_device_mapping': [{'connection_info':
                    {'data': {'volume_id': 'fake-uuid'}}}]})
        find_sr_by_uuid.assert_called_once_with(self.vmops._session,
                'FA15E-D15C-fake-uuid')
        self.assertEqual(0, forget_sr.call_count)
        self.assertEqual(0, hard_shutdown_vm.call_count)

    @mock.patch.object(vm_utils, 'lookup', side_effect=[None, None])
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    @mock.patch.object(volume_utils, 'find_sr_by_uuid', return_value='sr_ref')
    @mock.patch.object(volume_utils, 'forget_sr')
    def test_no_vm_orphaned_volume(self, forget_sr, find_sr_by_uuid,
            hard_shutdown_vm, lookup):
        self.vmops.destroy(self.instance, 'network_info',
                {'block_device_mapping': [{'connection_info':
                    {'data': {'volume_id': 'fake-uuid'}}}]})
        find_sr_by_uuid.assert_called_once_with(self.vmops._session,
                'FA15E-D15C-fake-uuid')
        forget_sr.assert_called_once_with(self.vmops._session, 'sr_ref')
        self.assertEqual(0, hard_shutdown_vm.call_count)


@mock.patch.object(vmops.VMOps, '_update_instance_progress')
@mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
@mock.patch.object(vm_utils, 'get_sr_path')
@mock.patch.object(vmops.VMOps, '_detach_block_devices_from_orig_vm')
@mock.patch.object(vmops.VMOps, '_migrate_disk_resizing_down')
@mock.patch.object(vmops.VMOps, '_migrate_disk_resizing_up')
class MigrateDiskAndPowerOffTestCase(VMOpsTestBase):
    def test_migrate_disk_and_power_off_works_down(self,
                migrate_up, migrate_down, *mocks):
        instance = {"root_gb": 2, "ephemeral_gb": 0, "uuid": "uuid"}
        flavor = {"root_gb": 1, "ephemeral_gb": 0}

        self.vmops.migrate_disk_and_power_off(None, instance, None,
                flavor, None)

        self.assertFalse(migrate_up.called)
        self.assertTrue(migrate_down.called)

    def test_migrate_disk_and_power_off_works_up(self,
                migrate_up, migrate_down, *mocks):
        instance = {"root_gb": 1, "ephemeral_gb": 1, "uuid": "uuid"}
        flavor = {"root_gb": 2, "ephemeral_gb": 2}

        self.vmops.migrate_disk_and_power_off(None, instance, None,
                flavor, None)

        self.assertFalse(migrate_down.called)
        self.assertTrue(migrate_up.called)

    def test_migrate_disk_and_power_off_resize_down_ephemeral_fails(self,
                migrate_up, migrate_down, *mocks):
        instance = {"ephemeral_gb": 2}
        flavor = {"ephemeral_gb": 1}

        self.assertRaises(exception.ResizeError,
                          self.vmops.migrate_disk_and_power_off,
                          None, instance, None, flavor, None)


@mock.patch.object(vm_utils, 'migrate_vhd')
@mock.patch.object(vmops.VMOps, '_resize_ensure_vm_is_shutdown')
@mock.patch.object(vm_utils, 'get_all_vdi_uuids_for_vm')
@mock.patch.object(vmops.VMOps, '_update_instance_progress')
@mock.patch.object(vmops.VMOps, '_apply_orig_vm_name_label')
class MigrateDiskResizingUpTestCase(VMOpsTestBase):
    def _fake_snapshot_attached_here(self, session, instance, vm_ref, label,
                                     userdevice, post_snapshot_callback):
        self.assertIsInstance(instance, dict)
        if userdevice == '0':
            self.assertEqual("vm_ref", vm_ref)
            self.assertEqual("fake-snapshot", label)
            yield ["leaf", "parent", "grandp"]
        else:
            leaf = userdevice + "-leaf"
            parent = userdevice + "-parent"
            yield [leaf, parent]

    @mock.patch.object(volume_utils, 'is_booted_from_volume',
            return_value=False)
    def test_migrate_disk_resizing_up_works_no_ephemeral(self,
            mock_is_booted_from_volume,
            mock_apply_orig, mock_update_progress, mock_get_all_vdi_uuids,
            mock_shutdown, mock_migrate_vhd):
        context = "ctxt"
        instance = {"name": "fake", "uuid": "uuid"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"

        mock_get_all_vdi_uuids.return_value = None

        with mock.patch.object(vm_utils, '_snapshot_attached_here_impl',
                               self._fake_snapshot_attached_here):
            self.vmops._migrate_disk_resizing_up(context, instance, dest,
                                                 vm_ref, sr_path)

        mock_get_all_vdi_uuids.assert_called_once_with(self.vmops._session,
                vm_ref, min_userdevice=4)
        mock_apply_orig.assert_called_once_with(instance, vm_ref)
        mock_shutdown.assert_called_once_with(instance, vm_ref)

        m_vhd_expected = [mock.call(self.vmops._session, instance, "parent",
                                    dest, sr_path, 1),
                          mock.call(self.vmops._session, instance, "grandp",
                                    dest, sr_path, 2),
                          mock.call(self.vmops._session, instance, "leaf",
                                    dest, sr_path, 0)]
        self.assertEqual(m_vhd_expected, mock_migrate_vhd.call_args_list)

        prog_expected = [
            mock.call(context, instance, 1, 5),
            mock.call(context, instance, 2, 5),
            mock.call(context, instance, 3, 5),
            mock.call(context, instance, 4, 5)
            # 5/5: step to be executed by finish migration.
            ]
        self.assertEqual(prog_expected, mock_update_progress.call_args_list)

    @mock.patch.object(volume_utils, 'is_booted_from_volume',
            return_value=False)
    def test_migrate_disk_resizing_up_works_with_two_ephemeral(self,
            mock_is_booted_from_volume,
            mock_apply_orig, mock_update_progress, mock_get_all_vdi_uuids,
            mock_shutdown, mock_migrate_vhd):
        context = "ctxt"
        instance = {"name": "fake", "uuid": "uuid"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"

        mock_get_all_vdi_uuids.return_value = ["vdi-eph1", "vdi-eph2"]

        with mock.patch.object(vm_utils, '_snapshot_attached_here_impl',
                               self._fake_snapshot_attached_here):
            self.vmops._migrate_disk_resizing_up(context, instance, dest,
                                                 vm_ref, sr_path)

        mock_get_all_vdi_uuids.assert_called_once_with(self.vmops._session,
                vm_ref, min_userdevice=4)
        mock_apply_orig.assert_called_once_with(instance, vm_ref)
        mock_shutdown.assert_called_once_with(instance, vm_ref)

        m_vhd_expected = [mock.call(self.vmops._session, instance,
                                    "parent", dest, sr_path, 1),
                          mock.call(self.vmops._session, instance,
                                    "grandp", dest, sr_path, 2),
                          mock.call(self.vmops._session, instance,
                                    "4-parent", dest, sr_path, 1, 1),
                          mock.call(self.vmops._session, instance,
                                    "5-parent", dest, sr_path, 1, 2),
                          mock.call(self.vmops._session, instance,
                                    "leaf", dest, sr_path, 0),
                          mock.call(self.vmops._session, instance,
                                    "4-leaf", dest, sr_path, 0, 1),
                          mock.call(self.vmops._session, instance,
                                    "5-leaf", dest, sr_path, 0, 2)]
        self.assertEqual(m_vhd_expected, mock_migrate_vhd.call_args_list)

        prog_expected = [
            mock.call(context, instance, 1, 5),
            mock.call(context, instance, 2, 5),
            mock.call(context, instance, 3, 5),
            mock.call(context, instance, 4, 5)
            # 5/5: step to be executed by finish migration.
            ]
        self.assertEqual(prog_expected, mock_update_progress.call_args_list)

    @mock.patch.object(volume_utils, 'is_booted_from_volume',
            return_value=True)
    def test_migrate_disk_resizing_up_booted_from_volume(self,
            mock_is_booted_from_volume,
            mock_apply_orig, mock_update_progress, mock_get_all_vdi_uuids,
            mock_shutdown, mock_migrate_vhd):
        context = "ctxt"
        instance = {"name": "fake", "uuid": "uuid"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"

        mock_get_all_vdi_uuids.return_value = ["vdi-eph1", "vdi-eph2"]

        with mock.patch.object(vm_utils, '_snapshot_attached_here_impl',
                self._fake_snapshot_attached_here):
            self.vmops._migrate_disk_resizing_up(context, instance, dest,
                                                 vm_ref, sr_path)

        mock_get_all_vdi_uuids.assert_called_once_with(self.vmops._session,
                vm_ref, min_userdevice=4)
        mock_apply_orig.assert_called_once_with(instance, vm_ref)
        mock_shutdown.assert_called_once_with(instance, vm_ref)

        m_vhd_expected = [mock.call(self.vmops._session, instance,
                                    "4-parent", dest, sr_path, 1, 1),
                          mock.call(self.vmops._session, instance,
                                    "5-parent", dest, sr_path, 1, 2),
                          mock.call(self.vmops._session, instance,
                                    "4-leaf", dest, sr_path, 0, 1),
                          mock.call(self.vmops._session, instance,
                                    "5-leaf", dest, sr_path, 0, 2)]
        self.assertEqual(m_vhd_expected, mock_migrate_vhd.call_args_list)

        prog_expected = [
            mock.call(context, instance, 1, 5),
            mock.call(context, instance, 2, 5),
            mock.call(context, instance, 3, 5),
            mock.call(context, instance, 4, 5)
            # 5/5: step to be executed by finish migration.
            ]
        self.assertEqual(prog_expected, mock_update_progress.call_args_list)

    @mock.patch.object(vmops.VMOps, '_restore_orig_vm_and_cleanup_orphan')
    @mock.patch.object(volume_utils, 'is_booted_from_volume',
            return_value=False)
    def test_migrate_disk_resizing_up_rollback(self,
            mock_is_booted_from_volume,
            mock_restore,
            mock_apply_orig, mock_update_progress, mock_get_all_vdi_uuids,
            mock_shutdown, mock_migrate_vhd):
        context = "ctxt"
        instance = {"name": "fake", "uuid": "fake"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"

        mock_migrate_vhd.side_effect = test.TestingException
        mock_restore.side_effect = test.TestingException

        with mock.patch.object(vm_utils, '_snapshot_attached_here_impl',
                               self._fake_snapshot_attached_here):
            self.assertRaises(exception.InstanceFaultRollback,
                              self.vmops._migrate_disk_resizing_up,
                              context, instance, dest, vm_ref, sr_path)

        mock_apply_orig.assert_called_once_with(instance, vm_ref)
        mock_restore.assert_called_once_with(instance)
        mock_migrate_vhd.assert_called_once_with(self.vmops._session,
                instance, "parent", dest, sr_path, 1)


class CreateVMRecordTestCase(VMOpsTestBase):
    @mock.patch.object(vm_utils, 'determine_vm_mode')
    @mock.patch.object(vm_utils, 'get_vm_device_id')
    @mock.patch.object(vm_utils, 'create_vm')
    def test_create_vm_record_with_vm_device_id(self, mock_create_vm,
            mock_get_vm_device_id, mock_determine_vm_mode):

        context = "context"
        instance = objects.Instance(vm_mode="vm_mode", uuid="uuid123")
        name_label = "dummy"
        disk_image_type = "vhd"
        kernel_file = "kernel"
        ramdisk_file = "ram"
        device_id = "0002"
        image_properties = {"xenapi_device_id": device_id}
        image_meta = {"properties": image_properties}
        session = "session"
        self.vmops._session = session
        mock_get_vm_device_id.return_value = device_id
        mock_determine_vm_mode.return_value = "vm_mode"

        self.vmops._create_vm_record(context, instance, name_label,
            disk_image_type, kernel_file, ramdisk_file, image_meta)

        mock_get_vm_device_id.assert_called_with(session, image_properties)
        mock_create_vm.assert_called_with(session, instance, name_label,
            kernel_file, ramdisk_file, False, device_id)


class BootableTestCase(VMOpsTestBase):

    def setUp(self):
        super(BootableTestCase, self).setUp()

        self.instance = {"name": "test", "uuid": "fake"}
        vm_rec, self.vm_ref = self.create_vm('test')

        # sanity check bootlock is initially disabled:
        self.assertEqual({}, vm_rec['blocked_operations'])

    def _get_blocked(self):
        vm_rec = self._session.call_xenapi("VM.get_record", self.vm_ref)
        return vm_rec['blocked_operations']

    def test_acquire_bootlock(self):
        self.vmops._acquire_bootlock(self.vm_ref)
        blocked = self._get_blocked()
        self.assertIn('start', blocked)

    def test_release_bootlock(self):
        self.vmops._acquire_bootlock(self.vm_ref)
        self.vmops._release_bootlock(self.vm_ref)
        blocked = self._get_blocked()
        self.assertNotIn('start', blocked)

    def test_set_bootable(self):
        self.vmops.set_bootable(self.instance, True)
        blocked = self._get_blocked()
        self.assertNotIn('start', blocked)

    def test_set_not_bootable(self):
        self.vmops.set_bootable(self.instance, False)
        blocked = self._get_blocked()
        self.assertIn('start', blocked)


@mock.patch.object(vm_utils, 'update_vdi_virtual_size', autospec=True)
class ResizeVdisTestCase(VMOpsTestBase):
    def test_dont_resize_root_volumes_osvol_false(self, mock_resize):
        instance = fake_instance.fake_db_instance(root_gb=20)
        vdis = {'root': {'osvol': False, 'ref': 'vdi_ref'}}
        self.vmops._resize_up_vdis(instance, vdis)
        self.assertTrue(mock_resize.called)

    def test_dont_resize_root_volumes_osvol_true(self, mock_resize):
        instance = fake_instance.fake_db_instance(root_gb=20)
        vdis = {'root': {'osvol': True}}
        self.vmops._resize_up_vdis(instance, vdis)
        self.assertFalse(mock_resize.called)

    def test_dont_resize_root_volumes_no_osvol(self, mock_resize):
        instance = fake_instance.fake_db_instance(root_gb=20)
        vdis = {'root': {}}
        self.vmops._resize_up_vdis(instance, vdis)
        self.assertFalse(mock_resize.called)

    @mock.patch.object(vm_utils, 'get_ephemeral_disk_sizes')
    def test_ensure_ephemeral_resize_with_root_volume(self, mock_sizes,
                                                       mock_resize):
        mock_sizes.return_value = [2000, 1000]
        instance = fake_instance.fake_db_instance(root_gb=20, ephemeral_gb=20)
        ephemerals = {"4": {"ref": 4}, "5": {"ref": 5}}
        vdis = {'root': {'osvol': True, 'ref': 'vdi_ref'},
                'ephemerals': ephemerals}
        with mock.patch.object(vm_utils, 'generate_single_ephemeral',
                               autospec=True) as g:
            self.vmops._resize_up_vdis(instance, vdis)
            self.assertEqual([mock.call(self.vmops._session, instance, 4,
                                        2000),
                              mock.call(self.vmops._session, instance, 5,
                                        1000)],
                             mock_resize.call_args_list)
            self.assertFalse(g.called)

    def test_resize_up_vdis_root(self, mock_resize):
        instance = {"root_gb": 20, "ephemeral_gb": 0}
        self.vmops._resize_up_vdis(instance, {"root": {"ref": "vdi_ref"}})
        mock_resize.assert_called_once_with(self.vmops._session, instance,
                                            "vdi_ref", 20)

    def test_resize_up_vdis_zero_disks(self, mock_resize):
        instance = {"root_gb": 0, "ephemeral_gb": 0}
        self.vmops._resize_up_vdis(instance, {"root": {}})
        self.assertFalse(mock_resize.called)

    def test_resize_up_vdis_no_vdis_like_initial_spawn(self, mock_resize):
        instance = {"root_gb": 0, "ephemeral_gb": 3000}
        vdis = {}

        self.vmops._resize_up_vdis(instance, vdis)

        self.assertFalse(mock_resize.called)

    @mock.patch.object(vm_utils, 'get_ephemeral_disk_sizes')
    def test_resize_up_vdis_ephemeral(self, mock_sizes, mock_resize):
        mock_sizes.return_value = [2000, 1000]
        instance = {"root_gb": 0, "ephemeral_gb": 3000}
        ephemerals = {"4": {"ref": 4}, "5": {"ref": 5}}
        vdis = {"ephemerals": ephemerals}

        self.vmops._resize_up_vdis(instance, vdis)

        mock_sizes.assert_called_once_with(3000)
        expected = [mock.call(self.vmops._session, instance, 4, 2000),
                    mock.call(self.vmops._session, instance, 5, 1000)]
        self.assertEqual(expected, mock_resize.call_args_list)

    @mock.patch.object(vm_utils, 'generate_single_ephemeral')
    @mock.patch.object(vm_utils, 'get_ephemeral_disk_sizes')
    def test_resize_up_vdis_ephemeral_with_generate(self, mock_sizes,
                                                    mock_generate,
                                                    mock_resize):
        mock_sizes.return_value = [2000, 1000]
        instance = {"root_gb": 0, "ephemeral_gb": 3000, "uuid": "a"}
        ephemerals = {"4": {"ref": 4}}
        vdis = {"ephemerals": ephemerals}

        self.vmops._resize_up_vdis(instance, vdis)

        mock_sizes.assert_called_once_with(3000)
        mock_resize.assert_called_once_with(self.vmops._session, instance,
                                            4, 2000)
        mock_generate.assert_called_once_with(self.vmops._session, instance,
                                              None, 5, 1000)


@mock.patch.object(vm_utils, 'remove_old_snapshots')
class CleanupFailedSnapshotTestCase(VMOpsTestBase):
    def test_post_interrupted_snapshot_cleanup(self, mock_remove):
        self.vmops._get_vm_opaque_ref = mock.Mock()
        self.vmops._get_vm_opaque_ref.return_value = "vm_ref"

        self.vmops.post_interrupted_snapshot_cleanup("context", "instance")

        mock_remove.assert_called_once_with(self.vmops._session,
                "instance", "vm_ref")


class LiveMigrateHelperTestCase(VMOpsTestBase):
    def test_connect_block_device_volumes_none(self):
        self.assertEqual({}, self.vmops.connect_block_device_volumes(None))

    @mock.patch.object(volumeops.VolumeOps, "connect_volume")
    def test_connect_block_device_volumes_calls_connect(self, mock_connect):
        with mock.patch.object(self.vmops._session,
                               "call_xenapi") as mock_session:
            mock_connect.return_value = ("sr_uuid", None)
            mock_session.return_value = "sr_ref"
            bdm = {"connection_info": "c_info"}
            bdi = {"block_device_mapping": [bdm]}
            result = self.vmops.connect_block_device_volumes(bdi)

            self.assertEqual({'sr_uuid': 'sr_ref'}, result)

            mock_connect.assert_called_once_with("c_info")
            mock_session.assert_called_once_with("SR.get_by_uuid",
                                                 "sr_uuid")


@mock.patch.object(vmops.VMOps, '_resize_ensure_vm_is_shutdown')
@mock.patch.object(vmops.VMOps, '_apply_orig_vm_name_label')
@mock.patch.object(vmops.VMOps, '_update_instance_progress')
@mock.patch.object(vm_utils, 'get_vdi_for_vm_safely')
@mock.patch.object(vm_utils, 'resize_disk')
@mock.patch.object(vm_utils, 'migrate_vhd')
@mock.patch.object(vm_utils, 'destroy_vdi')
class MigrateDiskResizingDownTestCase(VMOpsTestBase):
    def test_migrate_disk_resizing_down_works_no_ephemeral(
        self,
        mock_destroy_vdi,
        mock_migrate_vhd,
        mock_resize_disk,
        mock_get_vdi_for_vm_safely,
        mock_update_instance_progress,
        mock_apply_orig_vm_name_label,
        mock_resize_ensure_vm_is_shutdown):

        context = "ctx"
        instance = {"name": "fake", "uuid": "uuid"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"
        instance_type = dict(root_gb=1)
        old_vdi_ref = "old_ref"
        new_vdi_ref = "new_ref"
        new_vdi_uuid = "new_uuid"

        mock_get_vdi_for_vm_safely.return_value = (old_vdi_ref, None)
        mock_resize_disk.return_value = (new_vdi_ref, new_vdi_uuid)

        self.vmops._migrate_disk_resizing_down(context, instance, dest,
                                               instance_type, vm_ref, sr_path)

        mock_get_vdi_for_vm_safely.assert_called_once_with(
            self.vmops._session,
            vm_ref)
        mock_resize_ensure_vm_is_shutdown.assert_called_once_with(
            instance, vm_ref)
        mock_apply_orig_vm_name_label.assert_called_once_with(
            instance, vm_ref)
        mock_resize_disk.assert_called_once_with(
            self.vmops._session,
            instance,
            old_vdi_ref,
            instance_type)
        mock_migrate_vhd.assert_called_once_with(
            self.vmops._session,
            instance,
            new_vdi_uuid,
            dest,
            sr_path, 0)
        mock_destroy_vdi.assert_called_once_with(
            self.vmops._session,
            new_vdi_ref)

        prog_expected = [
            mock.call(context, instance, 1, 5),
            mock.call(context, instance, 2, 5),
            mock.call(context, instance, 3, 5),
            mock.call(context, instance, 4, 5)
            # 5/5: step to be executed by finish migration.
            ]
        self.assertEqual(prog_expected,
                         mock_update_instance_progress.call_args_list)


class GetVdisForInstanceTestCase(VMOpsTestBase):
    """Tests get_vdis_for_instance utility method."""
    def setUp(self):
        super(GetVdisForInstanceTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.context.auth_token = 'auth_token'
        self.session = mock.Mock()
        self.vmops._session = self.session
        self.instance = fake_instance.fake_instance_obj(self.context)
        self.name_label = 'name'
        self.image = 'fake_image_id'

    @mock.patch.object(volumeops.VolumeOps, "connect_volume",
                       return_value=("sr", "vdi_uuid"))
    def test_vdis_for_instance_bdi_password_scrubbed(self, get_uuid_mock):
        # setup fake data
        data = {'name_label': self.name_label,
                'sr_uuid': 'fake',
                'auth_password': 'scrubme'}
        bdm = [{'mount_device': '/dev/vda',
                'connection_info': {'data': data}}]
        bdi = {'root_device_name': 'vda',
               'block_device_mapping': bdm}

        # Tests that the parameters to the to_xml method are sanitized for
        # passwords when logged.
        def fake_debug(*args, **kwargs):
            if 'auth_password' in args[0]:
                self.assertNotIn('scrubme', args[0])
                fake_debug.matched = True

        fake_debug.matched = False

        with mock.patch.object(vmops.LOG, 'debug',
                               side_effect=fake_debug) as debug_mock:
            vdis = self.vmops._get_vdis_for_instance(self.context,
                    self.instance, self.name_label, self.image,
                    image_type=4, block_device_info=bdi)
            self.assertEqual(1, len(vdis))
            get_uuid_mock.assert_called_once_with({"data": data})
            # we don't care what the log message is, we just want to make sure
            # our stub method is called which asserts the password is scrubbed
            self.assertTrue(debug_mock.called)
            self.assertTrue(fake_debug.matched)
