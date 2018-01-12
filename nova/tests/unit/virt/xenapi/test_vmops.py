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

import base64
import uuid
import zlib

try:
    import xmlrpclib
except ImportError:
    import six.moves.xmlrpc_client as xmlrpclib

from eventlet import greenthread
import fixtures
import mock
from os_xenapi.client import host_xenstore
from oslo_utils import importutils
from oslo_utils import timeutils
import six

from nova.compute import power_state
from nova.compute import task_states
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields
from nova.pci import manager as pci_manager
from nova import test
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.xenapi import stubs
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.virt import fake
from nova.virt.xenapi import agent as xenapi_agent
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi.image import utils as image_utils
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
        stubs.stubout_session(self, xenapi_fake.SessionBase)
        self._session = xenapi_fake.SessionBase(
            'http://localhost', 'root', 'test_pass')
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
        self.context = context.RequestContext('user', 'project')
        self.instance = fake_instance.fake_instance_obj(self.context)

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

        lookup_returns = [backup_made and 'foo' or None,
                          (not backup_made or new_made) and 'foo' or None]

        @mock.patch.object(vm_utils, 'lookup',
                           side_effect=lookup_returns)
        @mock.patch.object(self._vmops, '_destroy')
        @mock.patch.object(vm_utils, 'set_vm_name_label')
        @mock.patch.object(self._vmops, '_attach_mapped_block_devices')
        @mock.patch.object(self._vmops, '_start')
        @mock.patch.object(vm_utils, 'is_vm_shutdown',
                           return_value=vm_shutdown)
        def test(mock_is_vm, mock_start, mock_attach_bdm, mock_set_vm_name,
                 mock_destroy, mock_lookup):
            self._vmops.finish_revert_migration(context, instance, [])

            mock_lookup.assert_has_calls([mock.call(self._session, 'foo-orig'),
                                          mock.call(self._session, 'foo')])
            if backup_made:
                if new_made:
                    mock_destroy.assert_called_once_with(instance, 'foo')
                mock_set_vm_name.assert_called_once_with(self._session, 'foo',
                                                         'foo')
                mock_attach_bdm.assert_called_once_with(instance, [])

            mock_is_vm.assert_called_once_with(self._session, 'foo')
            if vm_shutdown:
                mock_start.assert_called_once_with(instance, 'foo')

        test()

    def test_finish_revert_migration_after_crash(self):
        self._test_finish_revert_migration_after_crash(True, True)

    def test_finish_revert_migration_after_crash_before_new(self):
        self._test_finish_revert_migration_after_crash(True, False)

    def test_finish_revert_migration_after_crash_before_backup(self):
        self._test_finish_revert_migration_after_crash(False, False)

    @mock.patch.object(vm_utils, 'lookup', return_value=None)
    def test_get_vm_opaque_ref_raises_instance_not_found(self, mock_lookup):
        instance = {"name": "dummy"}

        self.assertRaises(exception.InstanceNotFound,
                self._vmops._get_vm_opaque_ref, instance)
        mock_lookup.assert_called_once_with(self._session, instance['name'],
                                            False)

    @mock.patch.object(vm_utils, 'destroy_vm')
    @mock.patch.object(vm_utils, 'clean_shutdown_vm')
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    def test_clean_shutdown_no_bdm_on_destroy(self, hard_shutdown_vm,
            clean_shutdown_vm, destroy_vm):
        vm_ref = 'vm_ref'
        self._vmops._destroy(self.instance, vm_ref, destroy_disks=False)
        hard_shutdown_vm.assert_called_once_with(self._vmops._session,
                self.instance, vm_ref)
        self.assertEqual(0, clean_shutdown_vm.call_count)

    @mock.patch.object(vm_utils, 'destroy_vm')
    @mock.patch.object(vm_utils, 'clean_shutdown_vm')
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    def test_clean_shutdown_with_bdm_on_destroy(self, hard_shutdown_vm,
            clean_shutdown_vm, destroy_vm):
        vm_ref = 'vm_ref'
        block_device_info = {'block_device_mapping': ['fake']}
        self._vmops._destroy(self.instance, vm_ref, destroy_disks=False,
                block_device_info=block_device_info)
        clean_shutdown_vm.assert_called_once_with(self._vmops._session,
                self.instance, vm_ref)
        self.assertEqual(0, hard_shutdown_vm.call_count)

    @mock.patch.object(vm_utils, 'destroy_vm')
    @mock.patch.object(vm_utils, 'clean_shutdown_vm', return_value=False)
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    def test_clean_shutdown_with_bdm_failed_on_destroy(self, hard_shutdown_vm,
            clean_shutdown_vm, destroy_vm):
        vm_ref = 'vm_ref'
        block_device_info = {'block_device_mapping': ['fake']}
        self._vmops._destroy(self.instance, vm_ref, destroy_disks=False,
                block_device_info=block_device_info)
        clean_shutdown_vm.assert_called_once_with(self._vmops._session,
                self.instance, vm_ref)
        hard_shutdown_vm.assert_called_once_with(self._vmops._session,
                self.instance, vm_ref)

    @mock.patch.object(vm_utils, 'try_auto_configure_disk')
    @mock.patch.object(vm_utils, 'create_vbd',
            side_effect=test.TestingException)
    def test_attach_disks_rescue_auto_disk_config_false(self, create_vbd,
            try_auto_config):
        ctxt = context.RequestContext('user', 'project')
        instance = fake_instance.fake_instance_obj(ctxt)
        image_meta = objects.ImageMeta.from_dict(
            {'properties': {'auto_disk_config': 'false'}})
        vdis = {'root': {'ref': 'fake-ref'}}
        self.assertRaises(test.TestingException, self._vmops._attach_disks,
                ctxt, instance, image_meta=image_meta, vm_ref=None,
                name_label=None, vdis=vdis, disk_image_type='fake',
                network_info=[], rescue=True)
        self.assertFalse(try_auto_config.called)

    @mock.patch.object(vm_utils, 'try_auto_configure_disk')
    @mock.patch.object(vm_utils, 'create_vbd',
            side_effect=test.TestingException)
    def test_attach_disks_rescue_auto_disk_config_true(self, create_vbd,
            try_auto_config):
        ctxt = context.RequestContext('user', 'project')
        instance = fake_instance.fake_instance_obj(ctxt)
        image_meta = objects.ImageMeta.from_dict(
            {'properties': {'auto_disk_config': 'true'}})
        vdis = {'root': {'ref': 'fake-ref'}}
        self.assertRaises(test.TestingException, self._vmops._attach_disks,
                ctxt, instance, image_meta=image_meta, vm_ref=None,
                name_label=None, vdis=vdis, disk_image_type='fake',
                network_info=[], rescue=True)
        try_auto_config.assert_called_once_with(self._vmops._session,
                'fake-ref', instance.flavor.root_gb)

    @mock.patch.object(vm_utils, 'snapshot_attached_here')
    @mock.patch.object(timeutils, 'delta_seconds')
    @mock.patch.object(timeutils, 'utcnow')
    @mock.patch.object(image_utils, 'get_image_handler')
    def test_snapshot_using_image_handler(self,
                                          mock_get_image_handler,
                                          mock_utcnow,
                                          mock_delta_seconds,
                                          mock_snapshot_attached_here):
        mock_utcnow.side_effect = ['fake_start', 'fake_end']
        self.flags(image_handler='direct_vhd', group='xenserver')
        mock_get_image_handler.return_value = mock.Mock()

        class FakeVdiUuid(object):
            def __enter__(self):
                pass

            def __exit__(self, Type, value, traceback):
                pass

        fake_vdi_uuid = FakeVdiUuid()
        mock_snapshot_attached_here.return_value = fake_vdi_uuid
        self._setup_mock_vmops()
        vmops = self._vmops
        with mock.patch.object(vmops, '_get_vm_opaque_ref',
                               return_value='fake_ref') as mock_get_opa_ref:
            fake_instance = {'name': 'fake_name'}

            vmops.snapshot('fake_ctx', fake_instance, 'fake_image_id',
                                 mock.Mock())

            vmops.image_handler.upload_image.assert_called_once_with(
                'fake_ctx', vmops._session, fake_instance,
                'fake_image_id', None)
            mock_get_opa_ref.assert_called_once_with(fake_instance)
            mock_delta_seconds.assert_called_once_with('fake_start',
                                                       'fake_end')
            self.assertEqual(mock_utcnow.call_count, 2)

    @mock.patch.object(vm_utils, 'snapshot_attached_here')
    @mock.patch.object(timeutils, 'delta_seconds')
    @mock.patch.object(timeutils, 'utcnow')
    @mock.patch.object(image_utils, 'get_image_handler')
    @mock.patch.object(importutils, 'import_object')
    def test_snapshot_using_upload_image_handler(self,
                                                 mock_import_object,
                                                 mock_get_image_handler,
                                                 mock_utcnow,
                                                 mock_delta_seconds,
                                                 mock_snapshot_attached_here):
        mock_utcnow.side_effect = ['fake_start', 'fake_end']
        self.flags(image_upload_handler='image_upload_handler',
                   group='xenserver')
        mock_get_image_handler.return_value = mock.Mock()

        class FakeVdiUuid(object):
            def __enter__(self):
                pass

            def __exit__(self, Type, value, traceback):
                pass

        fake_vdi_uuid = FakeVdiUuid()
        mock_snapshot_attached_here.return_value = fake_vdi_uuid
        mock_import_object.return_value = mock.Mock()
        self._setup_mock_vmops()
        vmops = self._vmops
        with mock.patch.object(vmops, '_get_vm_opaque_ref',
                               return_value='fake_ref') as mock_get_opa_ref:
            fake_instance = {'name': 'fake_name'}

            vmops.snapshot('fake_ctx', fake_instance, 'fake_image_id',
                                 mock.Mock())

            vmops.image_upload_handler.upload_image.assert_called_once_with(
                'fake_ctx', vmops._session, fake_instance,
                'fake_image_id', None)
            mock_get_opa_ref.assert_called_once_with(fake_instance)
            mock_delta_seconds.assert_called_once_with('fake_start',
                                                       'fake_end')
            self.assertEqual(mock_utcnow.call_count, 2)


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
    def _mock_console_log(self, session, domid):
        if domid == 0:
            raise session.XenAPI.Failure('No console')
        return base64.b64encode(zlib.compress(six.b('dom_id: %s' % domid)))

    @mock.patch.object(vmops.vm_management, 'get_console_log')
    def test_get_console_output_works(self, mock_console_log):
        ctxt = context.RequestContext('user', 'project')
        mock_console_log.side_effect = self._mock_console_log
        instance = fake_instance.fake_instance_obj(ctxt)
        with mock.patch.object(self.vmops, '_get_last_dom_id',
                               return_value=42) as mock_last_dom:
            self.assertEqual(b"dom_id: 42",
                             self.vmops.get_console_output(instance))
            mock_last_dom.assert_called_once_with(instance, check_rescue=True)

    @mock.patch.object(vmops.vm_management, 'get_console_log')
    def test_get_console_output_not_available(self, mock_console_log):
        mock_console_log.side_effect = self._mock_console_log
        ctxt = context.RequestContext('user', 'project')
        instance = fake_instance.fake_instance_obj(ctxt)
        # dom_id=0 used to trigger exception in fake XenAPI
        with mock.patch.object(self.vmops, '_get_last_dom_id',
                               return_value=0) as mock_last_dom:
            self.assertRaises(exception.ConsoleNotAvailable,
                              self.vmops.get_console_output, instance)
            mock_last_dom.assert_called_once_with(instance, check_rescue=True)

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
        self.assertRaises(exception.InstanceNotFound,
                          self.vmops._get_dom_id, instance)

    def test_get_dom_id_works_with_vmref(self):
        vm, vm_ref = self.create_vm("dummy")
        instance = {'name': 'dummy'}
        self.assertEqual(vm["domid"],
                         self.vmops._get_dom_id(instance, vm_ref=vm_ref))

    def test_get_dom_id_fails_if_shutdown(self):
        vm, vm_ref = self.create_vm("dummy")
        instance = {'name': 'dummy'}
        self._session.VM.hard_shutdown(vm_ref)
        self.assertRaises(exception.InstanceNotFound,
                          self.vmops._get_dom_id, instance, vm_ref=vm_ref)


class SpawnTestCase(VMOpsTestBase):
    def _stub_out_common(self):
        self.mock_ensure_instance_name_unique = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_ensure_instance_name_unique')).mock
        self.mock_ensure_enough_free_mem = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_ensure_enough_free_mem')).mock
        self.mock_update_instance_progress = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_update_instance_progress')).mock
        self.mock_determine_disk_image_type = self.useFixture(
            fixtures.MockPatchObject(
                vm_utils, 'determine_disk_image_type')).mock
        self.mock_get_vdis_for_instance = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_get_vdis_for_instance')).mock
        self.mock_safe_destroy_vdis = self.useFixture(
            fixtures.MockPatchObject(
                vm_utils, 'safe_destroy_vdis')).mock
        self.mock_safe_cleanup_from_vdis = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops._volumeops, 'safe_cleanup_from_vdis')).mock
        self.mock_resize_up_vdis = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_resize_up_vdis')).mock
        self.mock_create_kernel_and_ramdisk = self.useFixture(
            fixtures.MockPatchObject(
                vm_utils, 'create_kernel_and_ramdisk')).mock
        self.mock_destroy_kernel_ramdisk = self.useFixture(
            fixtures.MockPatchObject(
                vm_utils, 'destroy_kernel_ramdisk')).mock
        self.mock_create_vm_record = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_create_vm_record')).mock
        self.mock_destroy = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_destroy')).mock
        self.mock_attach_disks = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_attach_disks')).mock
        self.mock_save_device_metadata = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_save_device_metadata')).mock
        self.mock_get_instance_pci_devs = self.useFixture(
            fixtures.MockPatchObject(
                pci_manager, 'get_instance_pci_devs')).mock
        self.mock_set_other_config_pci = self.useFixture(
            fixtures.MockPatchObject(
                vm_utils, 'set_other_config_pci')).mock
        self.mock_attach_orig_disks = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_attach_orig_disks')).mock
        self.mock_inject_network_info = self.useFixture(
            fixtures.MockPatchObject(self.vmops, 'inject_network_info')).mock
        self.mock_inject_hostname = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_inject_hostname')).mock
        self.mock_inject_instance_metadata = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_inject_instance_metadata')).mock
        self.mock_inject_auto_disk_config = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_inject_auto_disk_config')).mock
        self.mock_file_inject_vm_settings = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_file_inject_vm_settings')).mock
        self.mock_create_vifs = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_create_vifs')).mock
        self.mock_setup_basic_filtering = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops.firewall_driver, 'setup_basic_filtering')).mock
        self.mock_prepare_instance_filter = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops.firewall_driver, 'prepare_instance_filter')).mock
        self.mock_start = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_start')).mock
        self.mock_wait_for_instance_to_start = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_wait_for_instance_to_start')).mock
        self.mock_configure_new_instance_w_agent = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops, '_configure_new_instance_with_agent')).mock
        self.mock_remove_hostname = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_remove_hostname')).mock
        self.mock_apply_instance_filter = self.useFixture(
            fixtures.MockPatchObject(
                self.vmops.firewall_driver, 'apply_instance_filter')).mock
        self.mock_update_last_dom_id = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_update_last_dom_id')).mock
        self.mock_call_xenapi = self.useFixture(
            fixtures.MockPatchObject(self.vmops._session, 'call_xenapi')).mock
        self.mock_attach_vgpu = self.useFixture(
            fixtures.MockPatchObject(self.vmops, '_attach_vgpu')).mock

    @staticmethod
    def _new_instance(obj):
        class _Instance(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__
        return _Instance(**obj)

    def _test_spawn(self, name_label_param=None, block_device_info_param=None,
                    rescue=False, include_root_vdi=True, throw_exception=None,
                    attach_pci_dev=False, neutron_exception=False,
                    network_info=None, vgpu_info=None):
        self._stub_out_common()

        instance = self._new_instance({"name": "dummy", "uuid": "fake_uuid",
                                    "device_metadata": None})

        name_label = name_label_param
        if name_label is None:
            name_label = "dummy"
        image_meta = objects.ImageMeta.from_dict({"id": uuids.image_id})
        context = "context"
        session = self.vmops._session
        injected_files = "fake_files"
        admin_password = "password"
        if network_info is None:
            network_info = []
        steps = 10
        if rescue:
            steps += 1

        block_device_info = block_device_info_param
        if block_device_info and not block_device_info['root_device_name']:
            block_device_info = dict(block_device_info_param)
            block_device_info['root_device_name'] = \
                                                self.vmops.default_root_dev

        di_type = "di_type"
        self.mock_determine_disk_image_type.return_value = di_type

        expected_update_instance_progress_calls = []
        step = 1
        expected_update_instance_progress_calls.append(
            mock.call(context, instance, step, steps))

        vdis = {"other": {"ref": "fake_ref_2", "osvol": True}}
        if include_root_vdi:
            vdis["root"] = {"ref": "fake_ref"}
        self.mock_get_vdis_for_instance.return_value = vdis
        step += 1
        expected_update_instance_progress_calls.append(
            mock.call(context, instance, step, steps))

        kernel_file = "kernel"
        ramdisk_file = "ramdisk"
        self.mock_create_kernel_and_ramdisk.return_value = (kernel_file,
                                                            ramdisk_file)
        step += 1
        expected_update_instance_progress_calls.append(
            mock.call(context, instance, step, steps))

        vm_ref = "fake_vm_ref"
        self.mock_create_vm_record.return_value = vm_ref
        step += 1
        expected_update_instance_progress_calls.append(
            mock.call(context, instance, step, steps))

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
                'dev_type': fields.PciDeviceType.STANDARD,
                'status': 'available',
                'dev_id': 'devid',
                'label': 'label',
                'instance_uuid': None,
                'extra_info': '{}',
            }
            self.mock_get_instance_pci_devs.return_value = [fake_dev]
        else:
            self.mock_get_instance_pci_devs.return_value = []

        step += 1
        expected_update_instance_progress_calls.append(
            mock.call(context, instance, step, steps))

        step += 1
        expected_update_instance_progress_calls.append(
            mock.call(context, instance, step, steps))

        if neutron_exception:
            events = [('network-vif-plugged', 1)]
            self.stub_out('nova.virt.xenapi.vmops.VMOps.'
                          '_neutron_failed_callback',
                          lambda event_name, instance: None)
            self.stub_out('nova.virt.xenapi.vmops.VMOps.'
                          'wait_for_instance_event',
                          lambda instance, event_names,
                              deadline, error_callback: None)
            mock_wait_for_instance_event = self.useFixture(
                fixtures.MockPatchObject(
                    self.vmops._virtapi, 'wait_for_instance_event',
                    side_effect=(
                        exception.VirtualInterfaceCreateException))).mock
        else:
            self.mock_setup_basic_filtering.side_effect = NotImplementedError
            step += 1
            expected_update_instance_progress_calls.append(
                mock.call(context, instance, step, steps))

            if rescue:
                step += 1
                expected_update_instance_progress_calls.append(
                    mock.call(context, instance, step, steps))
            start_pause = True
            step += 1
            expected_update_instance_progress_calls.append(
                mock.call(context, instance, step, steps))
            step += 1
            expected_update_instance_progress_calls.append(
                mock.call(context, instance, step, steps))
            step += 1
            expected_update_instance_progress_calls.append(
                mock.call(context, instance, step, steps))

        if throw_exception:
            self.mock_update_instance_progress.side_effect = [
                None, None, None, None, None, None, None, None, None,
                throw_exception]

        self.vmops.spawn(context, instance, image_meta, injected_files,
                         admin_password, network_info, block_device_info_param,
                         vgpu_info, name_label_param, rescue)

        self.mock_ensure_instance_name_unique.assert_called_once_with(
            name_label)
        self.mock_ensure_enough_free_mem.assert_called_once_with(instance)
        self.mock_update_instance_progress.assert_has_calls(
            expected_update_instance_progress_calls)
        self.mock_determine_disk_image_type.assert_called_once_with(image_meta)
        self.mock_get_vdis_for_instance.assert_called_once_with(
            context, instance, name_label, image_meta, di_type,
            block_device_info)
        self.mock_resize_up_vdis.assert_called_once_with(instance, vdis)
        self.mock_create_kernel_and_ramdisk.assert_called_once_with(
            context, session, instance, name_label)
        self.mock_create_vm_record.assert_called_once_with(
            context, instance, name_label, di_type, kernel_file, ramdisk_file,
            image_meta, rescue)
        self.mock_attach_disks.assert_called_once_with(
            context, instance, image_meta, vm_ref, name_label, vdis, di_type,
            network_info, rescue, admin_password, injected_files)
        self.mock_save_device_metadata.assert_called_once_with(
            context, instance, block_device_info)
        self.mock_get_instance_pci_devs.assert_called_once_with(instance)
        self.mock_inject_network_info.assert_called_once_with(
            instance, network_info, vm_ref)
        self.mock_inject_hostname.assert_called_once_with(instance, vm_ref,
                                                          rescue)
        self.mock_inject_instance_metadata.assert_called_once_with(instance,
                                                                   vm_ref)
        self.mock_inject_auto_disk_config.assert_called_once_with(instance,
                                                                  vm_ref)
        self.mock_file_inject_vm_settings.assert_called_once_with(
            instance, vm_ref, vdis, network_info)
        self.mock_start.assert_called_once_with(instance, vm_ref,
                                                start_pause=start_pause)
        self.mock_attach_vgpu.assert_called_once_with(vm_ref, vgpu_info,
                                                      instance)

        if throw_exception or neutron_exception:
            self.mock_safe_destroy_vdis.assert_called_once_with(
                self.vmops._session, ["fake_ref"])
            self.mock_safe_cleanup_from_vdis.assert_called_once_with(
                ["fake_ref_2"])
            self.mock_destroy_kernel_ramdisk.assert_called_once_with(
                self.vmops._session, instance, kernel_file, ramdisk_file)
            self.mock_destroy.assert_called_once_with(
                instance, vm_ref, network_info=network_info)

        if attach_pci_dev:
            self.mock_set_other_config_pci.assert_called_once_with(
                self.vmops._session, vm_ref, "0/0000:00:00.0")

        if neutron_exception:
            mock_wait_for_instance_event.assert_called_once_with(
                instance, events, deadline=300,
                error_callback=self.vmops._neutron_failed_callback)
        else:
            self.mock_create_vifs.assert_called_once_with(instance, vm_ref,
                                                          network_info)
            self.mock_setup_basic_filtering.assert_called_once_with(
                instance, network_info)
            self.mock_prepare_instance_filter.assert_called_once_with(
                instance, network_info)
            self.mock_wait_for_instance_to_start.assert_called_once_with(
                instance, vm_ref)
            self.mock_configure_new_instance_w_agent.assert_called_once_with(
                instance, vm_ref, injected_files, admin_password)
            self.mock_remove_hostname.assert_called_once_with(
                instance, vm_ref)
            self.mock_apply_instance_filter.assert_called_once_with(
                instance, network_info)
            self.mock_update_last_dom_id.assert_called_once_with(vm_ref)
            self.mock_call_xenapi.assert_called_once_with('VM.unpause', vm_ref)

            if rescue:
                self.mock_attach_orig_disks.assert_called_once_with(instance,
                                                                    vm_ref)

    def test_spawn(self):
        self._test_spawn()

    def test_spawn_with_alternate_options(self):
        self._test_spawn(include_root_vdi=False, rescue=True,
                         name_label_param="bob",
                         block_device_info_param={"root_device_name": ""})

    def test_spawn_with_pci_available_on_the_host(self):
        self._test_spawn(attach_pci_dev=True)

    def test_spawn_with_vgpu(self):
        vgpu_info = {'grp_uuid': uuids.gpu_group_1,
                     'vgpu_type_uuid': uuids.vgpu_type_1}
        self._test_spawn(vgpu_info=vgpu_info)

    def test_spawn_performs_rollback_and_throws_exception(self):
        self.assertRaises(test.TestingException, self._test_spawn,
                          throw_exception=test.TestingException())

    @mock.patch.object(vmops.VMOps, '_get_neutron_events',
                       return_value=[('network-vif-plugged', 1)])
    def test_spawn_with_neutron(self, mock_get_neutron_events):
        self.flags(use_neutron=True)
        network_info = [{'id': 1, 'active': True}]
        self.stub_out('nova.virt.xenapi.vmops.VMOps.'
                      '_neutron_failed_callback',
                      lambda event_name, instance: None)

        self._test_spawn(network_info=network_info)

        mock_get_neutron_events.assert_called_once_with(
            network_info, True, True, False)

    @staticmethod
    def _dev_mock(obj):
        dev = mock.MagicMock(**obj)
        dev.__contains__.side_effect = (
            lambda attr: getattr(dev, attr, None) is not None)
        return dev

    @mock.patch.object(objects, 'XenDeviceBus')
    @mock.patch.object(objects, 'IDEDeviceBus')
    @mock.patch.object(objects, 'DiskMetadata')
    def test_prepare_disk_metadata(self, mock_DiskMetadata,
        mock_IDEDeviceBus, mock_XenDeviceBus):
        mock_IDEDeviceBus.side_effect = \
            lambda **kw: \
                self._dev_mock({"address": kw.get("address"), "bus": "ide"})
        mock_XenDeviceBus.side_effect = \
            lambda **kw: \
                self._dev_mock({"address": kw.get("address"), "bus": "xen"})
        mock_DiskMetadata.side_effect = \
            lambda **kw: self._dev_mock(dict(**kw))

        bdm = self._dev_mock({"device_name": "/dev/xvda", "tag": "disk_a"})
        disk_metadata = self.vmops._prepare_disk_metadata(bdm)

        self.assertEqual(disk_metadata[0].tags, ["disk_a"])
        self.assertEqual(disk_metadata[0].bus.bus, "ide")
        self.assertEqual(disk_metadata[0].bus.address, "0:0")
        self.assertEqual(disk_metadata[1].tags, ["disk_a"])
        self.assertEqual(disk_metadata[1].bus.bus, "xen")
        self.assertEqual(disk_metadata[1].bus.address, "000000")
        self.assertEqual(disk_metadata[2].tags, ["disk_a"])
        self.assertEqual(disk_metadata[2].bus.bus, "xen")
        self.assertEqual(disk_metadata[2].bus.address, "51712")
        self.assertEqual(disk_metadata[3].tags, ["disk_a"])
        self.assertEqual(disk_metadata[3].bus.bus, "xen")
        self.assertEqual(disk_metadata[3].bus.address, "768")

        bdm = self._dev_mock({"device_name": "/dev/xvdc", "tag": "disk_c"})
        disk_metadata = self.vmops._prepare_disk_metadata(bdm)

        self.assertEqual(disk_metadata[0].tags, ["disk_c"])
        self.assertEqual(disk_metadata[0].bus.bus, "ide")
        self.assertEqual(disk_metadata[0].bus.address, "1:0")
        self.assertEqual(disk_metadata[1].tags, ["disk_c"])
        self.assertEqual(disk_metadata[1].bus.bus, "xen")
        self.assertEqual(disk_metadata[1].bus.address, "000200")
        self.assertEqual(disk_metadata[2].tags, ["disk_c"])
        self.assertEqual(disk_metadata[2].bus.bus, "xen")
        self.assertEqual(disk_metadata[2].bus.address, "51744")
        self.assertEqual(disk_metadata[3].tags, ["disk_c"])
        self.assertEqual(disk_metadata[3].bus.bus, "xen")
        self.assertEqual(disk_metadata[3].bus.address, "5632")

        bdm = self._dev_mock({"device_name": "/dev/xvde", "tag": "disk_e"})
        disk_metadata = self.vmops._prepare_disk_metadata(bdm)

        self.assertEqual(disk_metadata[0].tags, ["disk_e"])
        self.assertEqual(disk_metadata[0].bus.bus, "xen")
        self.assertEqual(disk_metadata[0].bus.address, "000400")
        self.assertEqual(disk_metadata[1].tags, ["disk_e"])
        self.assertEqual(disk_metadata[1].bus.bus, "xen")
        self.assertEqual(disk_metadata[1].bus.address, "51776")

    @mock.patch.object(objects.VirtualInterfaceList, 'get_by_instance_uuid')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(objects, 'NetworkInterfaceMetadata')
    @mock.patch.object(objects, 'InstanceDeviceMetadata')
    @mock.patch.object(objects, 'PCIDeviceBus')
    @mock.patch.object(vmops.VMOps, '_prepare_disk_metadata')
    def test_save_device_metadata(self, mock_prepare_disk_metadata,
        mock_PCIDeviceBus, mock_InstanceDeviceMetadata,
        mock_NetworkInterfaceMetadata, mock_get_bdms, mock_get_vifs):
        context = {}
        instance = {"uuid": "fake_uuid"}
        vif = self._dev_mock({"address": "fake_address", "tag": "vif_tag"})
        bdm = self._dev_mock({"device_name": "/dev/xvdx", "tag": "bdm_tag"})
        block_device_info = {'block_device_mapping': [bdm]}

        mock_get_vifs.return_value = [vif]
        mock_get_bdms.return_value = [bdm]
        mock_InstanceDeviceMetadata.side_effect = \
            lambda **kw: {"devices": kw.get("devices")}
        mock_NetworkInterfaceMetadata.return_value = mock.sentinel.vif_metadata
        mock_prepare_disk_metadata.return_value = [mock.sentinel.bdm_metadata]

        dev_meta = self.vmops._save_device_metadata(context, instance,
            block_device_info)

        mock_get_vifs.assert_called_once_with(context, instance["uuid"])

        mock_NetworkInterfaceMetadata.assert_called_once_with(mac=vif.address,
                                            bus=mock_PCIDeviceBus.return_value,
                                            tags=[vif.tag])
        mock_prepare_disk_metadata.assert_called_once_with(bdm)
        self.assertEqual(dev_meta["devices"],
            [mock.sentinel.vif_metadata, mock.sentinel.bdm_metadata])

    @mock.patch.object(objects.VirtualInterfaceList, 'get_by_instance_uuid')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(vmops.VMOps, '_prepare_disk_metadata')
    def test_save_device_metadata_no_vifs_no_bdms(
            self, mock_prepare_disk_metadata, mock_get_bdms, mock_get_vifs):
        """Tests that we don't save any device metadata when there are no
        VIFs or BDMs.
        """
        ctxt = context.RequestContext('fake-user', 'fake-project')
        instance = objects.Instance(uuid=uuids.instance_uuid)
        block_device_info = {'block_device_mapping': []}

        mock_get_vifs.return_value = objects.VirtualInterfaceList()

        dev_meta = self.vmops._save_device_metadata(
            ctxt, instance, block_device_info)
        self.assertIsNone(dev_meta)

        mock_get_vifs.assert_called_once_with(ctxt, uuids.instance_uuid)
        mock_get_bdms.assert_not_called()
        mock_prepare_disk_metadata.assert_not_called()

    @mock.patch.object(vmops.VMOps, '_get_neutron_events')
    def test_spawn_with_neutron_exception(self, mock_get_neutron_events):
        mock_get_neutron_events.return_value = [('network-vif-plugged', 1)]
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          self._test_spawn, neutron_exception=True)
        mock_get_neutron_events.assert_called_once_with(
            [], True, True, False)

    @mock.patch.object(vmops.VMOps, '_attach_mapped_block_devices')
    @mock.patch.object(vm_utils, 'import_all_migrated_disks')
    @mock.patch.object(volumeops.VolumeOps, 'connect_volume')
    def _test_finish_migration(self, mock_connect_volume,
                               mock_import_all_migrated_disks,
                               mock_attach_mapped_block_devices,
                               power_on=True, resize_instance=True,
                               throw_exception=None, booted_from_volume=False,
                               vgpu_info=None):
        self._stub_out_common()

        context = "context"
        migration = {}
        name_label = "dummy"
        instance = self._new_instance({"name": name_label, "uuid": "fake_uuid",
                "root_device_name": "/dev/xvda", "device_metadata": None})
        disk_info = "disk_info"
        network_info = "net_info"
        image_meta = objects.ImageMeta.from_dict({"id": uuids.image_id})
        block_device_info = {}
        import_root = True

        expected_call_xenapi = []
        if booted_from_volume:
            block_device_info = {'block_device_mapping': [
                {'mount_device': '/dev/xvda',
                 'connection_info': {'data': 'fake-data'}}]}
            import_root = False
            mock_connect_volume.return_value = ('sr', 'vol-vdi-uuid')
            expected_call_xenapi.append(mock.call('VDI.get_by_uuid',
                                                  'vol-vdi-uuid'))
            self.mock_call_xenapi.return_value = 'vol-vdi-ref'
        session = self.vmops._session

        di_type = "di_type"
        self.mock_determine_disk_image_type.return_value = di_type

        root_vdi = {"ref": "fake_ref"}
        ephemeral_vdi = {"ref": "fake_ref_e"}
        vdis = {"root": root_vdi, "ephemerals": {4: ephemeral_vdi}}
        mock_import_all_migrated_disks.return_value = vdis

        kernel_file = "kernel"
        ramdisk_file = "ramdisk"
        self.mock_create_kernel_and_ramdisk.return_value = (kernel_file,
                                                            ramdisk_file)

        vm_ref = "fake_vm_ref"
        rescue = False
        self.mock_create_vm_record.return_value = vm_ref
        self.mock_get_instance_pci_devs.return_value = []
        self.mock_setup_basic_filtering.side_effect = NotImplementedError

        if power_on:
            expected_call_xenapi.append(mock.call('VM.unpause', vm_ref))

        if throw_exception:
            self.mock_update_instance_progress.side_effect = throw_exception

        self.vmops.finish_migration(context, migration, instance, disk_info,
                                    network_info, image_meta, resize_instance,
                                    block_device_info, power_on)

        self.mock_ensure_instance_name_unique.assert_called_once_with(
            name_label)
        self.mock_ensure_enough_free_mem.assert_called_once_with(instance)
        self.mock_update_instance_progress.assert_called_once_with(
            context, instance, step=5, total_steps=5)
        self.mock_determine_disk_image_type.assert_called_once_with(image_meta)
        self.mock_create_kernel_and_ramdisk.assert_called_once_with(
            context, session, instance, name_label)
        self.mock_create_vm_record.assert_called_once_with(
            context, instance, name_label, di_type, kernel_file, ramdisk_file,
            image_meta, rescue)
        self.mock_attach_disks.assert_called_once_with(
            context, instance, image_meta, vm_ref, name_label, vdis, di_type,
            network_info, False, None, None)
        self.mock_save_device_metadata.assert_called_once_with(
            context, instance, block_device_info)
        self.mock_get_instance_pci_devs.assert_called_once_with(instance)
        self.mock_inject_network_info.assert_called_once_with(
            instance, network_info, vm_ref)
        self.mock_inject_instance_metadata.assert_called_once_with(instance,
                                                                   vm_ref)
        self.mock_inject_auto_disk_config.assert_called_once_with(instance,
                                                                  vm_ref)
        self.mock_file_inject_vm_settings.assert_called_once_with(
            instance, vm_ref, vdis, network_info)
        self.mock_create_vifs.assert_called_once_with(
            instance, vm_ref, network_info)
        self.mock_setup_basic_filtering.assert_called_once_with(instance,
                                                                network_info)
        self.mock_prepare_instance_filter.assert_called_once_with(
            instance, network_info)
        self.mock_apply_instance_filter.assert_called_once_with(
            instance, network_info)
        self.mock_attach_vgpu.assert_called_once_with(vm_ref, vgpu_info,
                                                      instance)
        mock_import_all_migrated_disks.assert_called_once_with(
            self.vmops._session, instance, import_root=import_root)
        mock_attach_mapped_block_devices.assert_called_once_with(
            instance, block_device_info)

        if resize_instance:
            self.mock_resize_up_vdis.assert_called_once_with(
                instance, vdis)

        if throw_exception:
            self.mock_safe_destroy_vdis.assert_called_once_with(
                self.vmops._session, ["fake_ref_e", "fake_ref"])
            self.mock_destroy_kernel_ramdisk.assert_called_once_with(
                self.vmops._session, instance, kernel_file, ramdisk_file)
            self.mock_destroy.assert_called_once_with(
                instance, vm_ref, network_info=network_info)

        if power_on:
            self.mock_start.assert_called_once_with(instance, vm_ref,
                                                    start_pause=True)
            self.mock_wait_for_instance_to_start.assert_called_once_with(
                instance, vm_ref)
            self.mock_update_last_dom_id.assert_called_once_with(vm_ref)

        if expected_call_xenapi:
            self.mock_call_xenapi.assert_has_calls(expected_call_xenapi)
        else:
            self.mock_call_xenapi.assert_not_called()

        if booted_from_volume:
            mock_connect_volume.assert_called_once_with({'data': 'fake-data'})

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

    @mock.patch.object(xenapi_fake.SessionBase, 'call_xenapi')
    def test_remove_hostname(self, mock_call_xenapi):
        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": None}

        self.vmops._remove_hostname(instance, vm_ref)

        mock_call_xenapi.assert_called_once_with(
            "VM.remove_from_xenstore_data", vm_ref, "vm-data/hostname")

    @mock.patch.object(vmops.VMOps, '_remove_hostname')
    @mock.patch.object(vmops.VMOps, '_inject_hostname')
    @mock.patch.object(vmops.VMOps, '_get_agent')
    @mock.patch.object(vmops.VMOps, 'agent_enabled', return_value=True)
    def test_reset_network(self, mock_agent_enabled, mock_get_agent,
                           mock_inject_hostname, mock_remove_hostname):
        vm, vm_ref = self.create_vm("dummy")
        instance = {"name": "dummy", "uuid": "1234", "auto_disk_config": None}
        agent = mock.Mock()
        mock_get_agent.return_value = agent

        self.vmops.reset_network(instance)

        agent.resetnetwork.assert_called_once_with()
        mock_agent_enabled.assert_called_once_with(instance)
        mock_get_agent.assert_called_once_with(instance, vm_ref)
        mock_inject_hostname.assert_called_once_with(instance, vm_ref, False)
        mock_remove_hostname.assert_called_once_with(instance, vm_ref)

    @mock.patch.object(vmops.VMOps, '_add_to_param_xenstore')
    def test_inject_hostname(self, mock_add_to_param_xenstore):
        instance = {"hostname": "dummy", "os_type": "fake", "uuid": "uuid"}
        vm_ref = "vm_ref"

        self.vmops._inject_hostname(instance, vm_ref, rescue=False)

        mock_add_to_param_xenstore.assert_called_once_with(
            vm_ref, 'vm-data/hostname', 'dummy')

    @mock.patch.object(vmops.VMOps, '_add_to_param_xenstore')
    def test_inject_hostname_with_rescue_prefix(
            self, mock_add_to_param_xenstore):
        instance = {"hostname": "dummy", "os_type": "fake", "uuid": "uuid"}
        vm_ref = "vm_ref"

        self.vmops._inject_hostname(instance, vm_ref, rescue=True)

        mock_add_to_param_xenstore.assert_called_once_with(
            vm_ref, 'vm-data/hostname', 'RESCUE-dummy')

    @mock.patch.object(vmops.VMOps, '_add_to_param_xenstore')
    def test_inject_hostname_with_windows_name_truncation(
            self, mock_add_to_param_xenstore):
        instance = {"hostname": "dummydummydummydummydummy",
                    "os_type": "windows", "uuid": "uuid"}
        vm_ref = "vm_ref"

        self.vmops._inject_hostname(instance, vm_ref, rescue=True)

        mock_add_to_param_xenstore.assert_called_once_with(
            vm_ref, 'vm-data/hostname', 'RESCUE-dummydum')

    @mock.patch.object(greenthread, 'sleep')
    @mock.patch.object(vm_utils, 'get_power_state',
                       side_effect=[power_state.SHUTDOWN,
                                    power_state.RUNNING])
    def test_wait_for_instance_to_start(self, mock_get_power_state,
                                        mock_sleep):
        instance = {"uuid": "uuid"}
        vm_ref = "vm_ref"

        self.vmops._wait_for_instance_to_start(instance, vm_ref)

        mock_get_power_state.assert_has_calls(
            [mock.call(self._session, vm_ref),
             mock.call(self._session, vm_ref)])
        mock_sleep.assert_called_once_with(0.5)

    @mock.patch.object(vm_utils, 'lookup', return_value='ref')
    @mock.patch.object(vm_utils, 'create_vbd')
    def test_attach_orig_disks(self, mock_create_vbd, mock_lookup):
        instance = {"name": "dummy"}
        vm_ref = "vm_ref"
        vbd_refs = {vmops.DEVICE_ROOT: "vdi_ref"}

        with mock.patch.object(self.vmops, '_find_vdi_refs',
                               return_value=vbd_refs) as mock_find_vdi:
            self.vmops._attach_orig_disks(instance, vm_ref)
            mock_lookup.assert_called_once_with(self.vmops._session, 'dummy')
            mock_find_vdi.assert_called_once_with('ref', exclude_volumes=True)
            mock_create_vbd.assert_called_once_with(
                self.vmops._session, vm_ref, 'vdi_ref', vmops.DEVICE_RESCUE,
                bootable=False)

    @mock.patch.object(xenapi_agent.XenAPIBasedAgent, 'update_if_needed')
    @mock.patch.object(xenapi_agent.XenAPIBasedAgent, 'resetnetwork')
    @mock.patch.object(xenapi_agent.XenAPIBasedAgent, 'get_version',
                       return_value='1.2.3')
    @mock.patch.object(vmops.VMOps, '_get_agent')
    @mock.patch.object(xenapi_agent, 'should_use_agent',
                       return_value=True)
    def test_agent_update_setup(self, mock_should_use_agent, mock_get_agent,
                                mock_get_version, mock_resetnetwork,
                                mock_update_if_needed):
        # agent updates need to occur after networking is configured
        instance = {'name': 'betelgeuse',
                    'uuid': '1-2-3-4-5-6'}
        vm_ref = 'vm_ref'
        agent = xenapi_agent.XenAPIBasedAgent(self.vmops._session,
                self.vmops._virtapi, instance, vm_ref)
        mock_get_agent.return_value = agent

        self.vmops._configure_new_instance_with_agent(instance, vm_ref,
                None, None)

        mock_should_use_agent.assert_called_once_with(instance)
        mock_get_agent.assert_called_once_with(instance, vm_ref)
        mock_get_version.assert_called_once_with()
        mock_resetnetwork.assert_called_once_with()
        mock_update_if_needed.assert_called_once_with('1.2.3')

    @mock.patch.object(utils, 'is_neutron', return_value=True)
    def test_get_neutron_event(self, mock_is_neutron):
        network_info = [{"active": False, "id": 1},
                        {"active": True, "id": 2},
                        {"active": False, "id": 3},
                        {"id": 4}]
        power_on = True
        first_boot = True
        rescue = False
        events = self.vmops._get_neutron_events(network_info,
                                                power_on, first_boot, rescue)
        self.assertEqual("network-vif-plugged", events[0][0])
        self.assertEqual(1, events[0][1])
        self.assertEqual("network-vif-plugged", events[1][0])
        self.assertEqual(3, events[1][1])

    @mock.patch.object(utils, 'is_neutron', return_value=False)
    def test_get_neutron_event_not_neutron_network(self, mock_is_neutron):
        network_info = [{"active": False, "id": 1},
                        {"active": True, "id": 2},
                        {"active": False, "id": 3},
                        {"id": 4}]
        power_on = True
        first_boot = True
        rescue = False
        events = self.vmops._get_neutron_events(network_info,
                                                power_on, first_boot, rescue)
        self.assertEqual([], events)

    @mock.patch.object(utils, 'is_neutron', return_value=True)
    def test_get_neutron_event_power_off(self, mock_is_neutron):
        network_info = [{"active": False, "id": 1},
                        {"active": True, "id": 2},
                        {"active": False, "id": 3},
                        {"id": 4}]
        power_on = False
        first_boot = True
        rescue = False
        events = self.vmops._get_neutron_events(network_info,
                                                power_on, first_boot, rescue)
        self.assertEqual([], events)

    @mock.patch.object(utils, 'is_neutron', return_value=True)
    def test_get_neutron_event_not_first_boot(self, mock_is_neutron):
        network_info = [{"active": False, "id": 1},
                        {"active": True, "id": 2},
                        {"active": False, "id": 3},
                        {"id": 4}]
        power_on = True
        first_boot = False
        rescue = False
        events = self.vmops._get_neutron_events(network_info,
                                                power_on, first_boot, rescue)
        self.assertEqual([], events)

    @mock.patch.object(utils, 'is_neutron', return_value=True)
    def test_get_neutron_event_rescue(self, mock_is_neutron):
        network_info = [{"active": False, "id": 1},
                        {"active": True, "id": 2},
                        {"active": False, "id": 3},
                        {"id": 4}]
        power_on = True
        first_boot = True
        rescue = True
        events = self.vmops._get_neutron_events(network_info,
                                                power_on, first_boot, rescue)
        self.assertEqual([], events)


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
    def test_no_vm_orphaned_volume_old_sr(self, forget_sr, find_sr_by_uuid,
            hard_shutdown_vm, lookup):
        self.vmops.destroy(self.instance, 'network_info',
                {'block_device_mapping': [{'connection_info':
                    {'data': {'volume_id': 'fake-uuid'}}}]})
        find_sr_by_uuid.assert_called_once_with(self.vmops._session,
                'FA15E-D15C-fake-uuid')
        forget_sr.assert_called_once_with(self.vmops._session, 'sr_ref')
        self.assertEqual(0, hard_shutdown_vm.call_count)

    @mock.patch.object(vm_utils, 'lookup', side_effect=[None, None])
    @mock.patch.object(vm_utils, 'hard_shutdown_vm')
    @mock.patch.object(volume_utils, 'find_sr_by_uuid',
                       side_effect=[None, 'sr_ref'])
    @mock.patch.object(volume_utils, 'forget_sr')
    @mock.patch.object(uuid, 'uuid5', return_value='fake-uuid')
    def test_no_vm_orphaned_volume(self, uuid5, forget_sr,
            find_sr_by_uuid, hard_shutdown_vm, lookup):
        fake_data = {'volume_id': 'fake-uuid',
                     'target_portal': 'host:port',
                     'target_iqn': 'iqn'}
        self.vmops.destroy(self.instance, 'network_info',
                {'block_device_mapping': [{'connection_info':
                                           {'data': fake_data}}]})
        call1 = mock.call(self.vmops._session, 'FA15E-D15C-fake-uuid')
        call2 = mock.call(self.vmops._session, 'fake-uuid')
        uuid5.assert_called_once_with(volume_utils.SR_NAMESPACE,
                                      'host/port/iqn')
        find_sr_by_uuid.assert_has_calls([call1, call2])
        forget_sr.assert_called_once_with(self.vmops._session, 'sr_ref')
        self.assertEqual(0, hard_shutdown_vm.call_count)


@mock.patch.object(vmops.VMOps, '_update_instance_progress')
@mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
@mock.patch.object(vm_utils, 'get_sr_path')
@mock.patch.object(vmops.VMOps, '_detach_block_devices_from_orig_vm')
@mock.patch.object(vmops.VMOps, '_migrate_disk_resizing_down')
@mock.patch.object(vmops.VMOps, '_migrate_disk_resizing_up')
class MigrateDiskAndPowerOffTestCase(VMOpsTestBase):
    def setUp(self):
        super(MigrateDiskAndPowerOffTestCase, self).setUp()
        self.context = context.RequestContext('user', 'project')

    def test_migrate_disk_and_power_off_works_down(self,
                migrate_up, migrate_down, *mocks):
        instance = objects.Instance(
            flavor=objects.Flavor(root_gb=2, ephemeral_gb=0),
            uuid=uuids.instance)
        flavor = fake_flavor.fake_flavor_obj(self.context, root_gb=1,
                                             ephemeral_gb=0)

        self.vmops.migrate_disk_and_power_off(None, instance, None,
                flavor, None)

        self.assertFalse(migrate_up.called)
        self.assertTrue(migrate_down.called)

    def test_migrate_disk_and_power_off_works_up(self,
                migrate_up, migrate_down, *mocks):
        instance = objects.Instance(
            flavor=objects.Flavor(root_gb=1,
                                  ephemeral_gb=1),
            uuid=uuids.instance)
        flavor = fake_flavor.fake_flavor_obj(self.context, root_gb=2,
                                             ephemeral_gb=2)

        self.vmops.migrate_disk_and_power_off(None, instance, None,
                flavor, None)

        self.assertFalse(migrate_down.called)
        self.assertTrue(migrate_up.called)

    def test_migrate_disk_and_power_off_resize_down_ephemeral_fails(self,
                migrate_up, migrate_down, *mocks):
        instance = objects.Instance(flavor=objects.Flavor(ephemeral_gb=2))
        flavor = fake_flavor.fake_flavor_obj(self.context, ephemeral_gb=1)

        self.assertRaises(exception.ResizeError,
                          self.vmops.migrate_disk_and_power_off,
                          None, instance, None, flavor, None)


@mock.patch.object(vm_utils, 'get_vdi_for_vm_safely')
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
            mock_is_booted_from_volume, mock_apply_orig, mock_update_progress,
            mock_get_all_vdi_uuids, mock_shutdown, mock_migrate_vhd,
            mock_get_vdi_for_vm):
        context = "ctxt"
        instance = {"name": "fake", "uuid": "uuid"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"

        mock_get_all_vdi_uuids.return_value = None
        mock_get_vdi_for_vm.return_value = ({}, {"uuid": "root"})

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
                          mock.call(self.vmops._session, instance, "root",
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
    def test_migrate_disk_resizing_up_ephemerals_no_volume(self,
            mock_is_booted_from_volume, mock_apply_orig, mock_update_progress,
            mock_get_all_vdi_uuids, mock_shutdown, mock_migrate_vhd,
            mock_get_vdi_for_vm):
        context = "ctxt"
        instance = {"name": "fake", "uuid": "uuid"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"

        mock_get_all_vdi_uuids.return_value = ["vdi-eph1", "vdi-eph2"]
        mock_get_vdi_for_vm.side_effect = [({}, {"uuid": "root"}),
                                           ({}, {"uuid": "4-root"}),
                                           ({}, {"uuid": "5-root"})]

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
                                    "root", dest, sr_path, 0),
                          mock.call(self.vmops._session, instance,
                                    "4-root", dest, sr_path, 0, 1),
                          mock.call(self.vmops._session, instance,
                                    "5-root", dest, sr_path, 0, 2)]
        self.assertEqual(m_vhd_expected, mock_migrate_vhd.call_args_list)

        prog_expected = [
            mock.call(context, instance, 1, 5),
            mock.call(context, instance, 2, 5),
            mock.call(context, instance, 3, 5),
            mock.call(context, instance, 4, 5)
            # 5/5: step to be executed by finish migration.
            ]
        self.assertEqual(prog_expected, mock_update_progress.call_args_list)

    @mock.patch.object(volume_utils, 'is_booted_from_volume')
    def test_migrate_disk_resizing_up_ephemerals_mixed_volumes(self,
            mock_is_booted_from_volume, mock_apply_orig, mock_update_progress,
            mock_get_all_vdi_uuids, mock_shutdown, mock_migrate_vhd,
            mock_get_vdi_for_vm):
        context = "ctxt"
        instance = {"name": "fake", "uuid": "uuid"}
        dest = "dest"
        vm_ref = "vm_ref"
        sr_path = "sr_path"

        mock_get_all_vdi_uuids.return_value = ["vdi-eph1", "vdi-eph2"]
        mock_get_vdi_for_vm.side_effect = [({}, {"uuid": "4-root"}),
                                           ({}, {"uuid": "5-root"})]
        # Here we mock the is_booted_from_volume call to emulate the
        # 4-root and 4-parent VDI's being volume based, while 5-root
        # and 5-Parent are local ephemeral drives that should be migrated.
        mock_is_booted_from_volume.side_effect = [True, False, True, False]

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
                                    "4-root", dest, sr_path, 0, 1)]

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
            mock_shutdown, mock_migrate_vhd, mock_get_vdi_for_vm):
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
        instance = objects.Instance(vm_mode="vm_mode", uuid=uuids.instance)
        name_label = "dummy"
        disk_image_type = "vhd"
        kernel_file = "kernel"
        ramdisk_file = "ram"
        device_id = "0002"
        image_properties = {"xenapi_device_id": device_id}
        image_meta = objects.ImageMeta.from_dict(
            {"properties": image_properties})
        rescue = False
        session = "session"
        self.vmops._session = session
        mock_get_vm_device_id.return_value = device_id
        mock_determine_vm_mode.return_value = "vm_mode"

        self.vmops._create_vm_record(context, instance, name_label,
            disk_image_type, kernel_file, ramdisk_file, image_meta, rescue)

        mock_get_vm_device_id.assert_called_with(session, image_meta)
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
        instance = fake_instance.fake_instance_obj(
            None, flavor=objects.Flavor(root_gb=20))
        vdis = {'root': {'osvol': False, 'ref': 'vdi_ref'}}
        self.vmops._resize_up_vdis(instance, vdis)
        self.assertTrue(mock_resize.called)

    def test_dont_resize_root_volumes_osvol_true(self, mock_resize):
        instance = fake_instance.fake_instance_obj(
            None, flavor=objects.Flavor(root_gb=20))
        vdis = {'root': {'osvol': True}}
        self.vmops._resize_up_vdis(instance, vdis)
        self.assertFalse(mock_resize.called)

    def test_dont_resize_root_volumes_no_osvol(self, mock_resize):
        instance = fake_instance.fake_instance_obj(
            None, flavor=objects.Flavor(root_gb=20))
        vdis = {'root': {}}
        self.vmops._resize_up_vdis(instance, vdis)
        self.assertFalse(mock_resize.called)

    @mock.patch.object(vm_utils, 'get_ephemeral_disk_sizes')
    def test_ensure_ephemeral_resize_with_root_volume(self, mock_sizes,
                                                       mock_resize):
        mock_sizes.return_value = [2000, 1000]
        instance = fake_instance.fake_instance_obj(
            None, flavor=objects.Flavor(root_gb=20, ephemeral_gb=20))
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
        instance = objects.Instance(flavor=objects.Flavor(root_gb=20,
                                                          ephemeral_gb=0))
        self.vmops._resize_up_vdis(instance, {"root": {"ref": "vdi_ref"}})
        mock_resize.assert_called_once_with(self.vmops._session, instance,
                                            "vdi_ref", 20)

    def test_resize_up_vdis_zero_disks(self, mock_resize):
        instance = objects.Instance(flavor=objects.Flavor(root_gb=0,
                                                          ephemeral_gb=0))
        self.vmops._resize_up_vdis(instance, {"root": {}})
        self.assertFalse(mock_resize.called)

    def test_resize_up_vdis_no_vdis_like_initial_spawn(self, mock_resize):
        instance = objects.Instance(flavor=objects.Flavor(root_gb=0,
                                                          ephemeral_gb=3000))
        vdis = {}

        self.vmops._resize_up_vdis(instance, vdis)

        self.assertFalse(mock_resize.called)

    @mock.patch.object(vm_utils, 'get_ephemeral_disk_sizes')
    def test_resize_up_vdis_ephemeral(self, mock_sizes, mock_resize):
        mock_sizes.return_value = [2000, 1000]
        instance = objects.Instance(flavor=objects.Flavor(root_gb=0,
                                                          ephemeral_gb=3000))
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
        instance = objects.Instance(uuid=uuids.instance,
                                    flavor=objects.Flavor(root_gb=0,
                                                          ephemeral_gb=3000))
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


class XenstoreCallsTestCase(VMOpsTestBase):
    """Test cases for Read/Write/Delete/Update xenstore calls
    from vmops.
    """

    @mock.patch.object(vmops.VMOps, '_get_dom_id')
    @mock.patch.object(host_xenstore, 'read_record')
    def test_read_from_xenstore(self, mock_read_record, mock_dom_id):
        mock_read_record.return_value = "fake_xapi_return"
        mock_dom_id.return_value = "fake_dom_id"
        fake_instance = {"name": "fake_instance"}
        path = "attr/PVAddons/MajorVersion"
        self.assertEqual("fake_xapi_return",
                         self.vmops._read_from_xenstore(fake_instance, path,
                                                        vm_ref="vm_ref"))
        mock_dom_id.assert_called_once_with(fake_instance, "vm_ref")

    @mock.patch.object(vmops.VMOps, '_get_dom_id')
    @mock.patch.object(host_xenstore, 'read_record')
    def test_read_from_xenstore_ignore_missing_path(self, mock_read_record,
                                                    mock_dom_id):
        mock_read_record.return_value = "fake_xapi_return"
        mock_dom_id.return_value = "fake_dom_id"
        fake_instance = {"name": "fake_instance"}
        path = "attr/PVAddons/MajorVersion"
        self.vmops._read_from_xenstore(fake_instance, path, vm_ref="vm_ref")
        mock_read_record.assert_called_once_with(
            self._session, "fake_dom_id", path, ignore_missing_path=True)

    @mock.patch.object(vmops.VMOps, '_get_dom_id')
    @mock.patch.object(host_xenstore, 'read_record')
    def test_read_from_xenstore_missing_path(self, mock_read_record,
                                             mock_dom_id):
        mock_read_record.return_value = "fake_xapi_return"
        mock_dom_id.return_value = "fake_dom_id"
        fake_instance = {"name": "fake_instance"}
        path = "attr/PVAddons/MajorVersion"
        self.vmops._read_from_xenstore(fake_instance, path, vm_ref="vm_ref",
                                       ignore_missing_path=False)
        mock_read_record.assert_called_once_with(self._session, "fake_dom_id",
                                                 path,
                                                 ignore_missing_path=False)


class LiveMigrateTestCase(VMOpsTestBase):

    @mock.patch.object(vmops.VMOps, '_get_network_ref')
    @mock.patch.object(vm_utils, 'host_in_this_pool')
    def _test_check_can_live_migrate_destination_shared_storage(
                                                self,
                                                shared,
                                                mock_is_same_pool,
                                                mock_net_ref):
        fake_instance = objects.Instance(host="fake_host")
        block_migration = None
        disk_over_commit = False
        ctxt = 'ctxt'
        mock_net_ref.return_value = 'fake_net_ref'
        if shared:
            mock_is_same_pool.return_value = True
        else:
            mock_is_same_pool.return_value = False

        with mock.patch.object(self._session, 'get_rec') as fake_sr_rec, \
                mock.patch.object(self._session, 'host.get_by_name_label') \
                as fake_get_ref:
            fake_get_ref.return_value = ['fake_host_ref']
            fake_sr_rec.return_value = {'shared': shared}
            migrate_data_ret = self.vmops.check_can_live_migrate_destination(
                ctxt, fake_instance, block_migration, disk_over_commit)

        if shared:
            self.assertFalse(migrate_data_ret.block_migration)
        else:
            self.assertTrue(migrate_data_ret.block_migration)
        self.assertEqual({'': 'fake_net_ref'},
                         migrate_data_ret.vif_uuid_map)

    def test_check_can_live_migrate_destination_shared_storage(self):
        self._test_check_can_live_migrate_destination_shared_storage(True)

    def test_check_can_live_migrate_destination_shared_storage_false(self):
        self._test_check_can_live_migrate_destination_shared_storage(False)

    @mock.patch.object(vmops.VMOps, '_get_network_ref')
    def test_check_can_live_migrate_destination_block_migration(
                                                                self,
                                                                mock_net_ref):
        fake_instance = objects.Instance(host="fake_host")
        block_migration = None
        disk_over_commit = False
        ctxt = 'ctxt'
        mock_net_ref.return_value = 'fake_net_ref'

        with mock.patch.object(self._session, 'host.get_by_name_label') \
                as fake_get_ref:
            fake_get_ref.return_value = ['fake_host_ref']
            migrate_data_ret = self.vmops.check_can_live_migrate_destination(
                ctxt, fake_instance, block_migration, disk_over_commit)

            self.assertTrue(migrate_data_ret.block_migration)
            self.assertEqual(vm_utils.safe_find_sr(self._session),
                             migrate_data_ret.destination_sr_ref)
            self.assertEqual({'value': 'fake_migrate_data'},
                             migrate_data_ret.migrate_send_data)
            self.assertEqual({'': 'fake_net_ref'},
                             migrate_data_ret.vif_uuid_map)

    @mock.patch.object(vmops.VMOps, '_migrate_receive')
    @mock.patch.object(vm_utils, 'safe_find_sr')
    @mock.patch.object(vmops.VMOps, '_get_network_ref')
    def test_no_hosts_found_with_the_name_label(self,
                                                mock_get_network_ref,
                                                mock_safe_find_sr,
                                                mock_migrate_receive):
        # Can find the dest host in current pool, do block live migrate
        fake_instance = objects.Instance(host="fake_host")
        mock_migrate_receive.return_value = {'fake_key': 'fake_data'}
        mock_safe_find_sr.return_value = 'fake_destination_sr_ref'
        mock_get_network_ref.return_value = 'fake_net_ref'
        block_migration = None
        disk_over_commit = False
        ctxt = 'ctxt'
        with mock.patch.object(self._session, 'host.get_by_name_label') \
                as fake_get_ref:
            fake_get_ref.return_value = []
            migrate_data_ret = self.vmops.check_can_live_migrate_destination(
                ctxt, fake_instance, block_migration, disk_over_commit)
            self.assertTrue(migrate_data_ret.block_migration)
            self.assertEqual(migrate_data_ret.vif_uuid_map,
                             {'': 'fake_net_ref'})

    def test_multiple_hosts_found_with_same_name(self):
        # More than one host found with the dest host name, raise exception
        fake_instance = objects.Instance(host="fake_host")
        block_migration = None
        disk_over_commit = False
        ctxt = 'ctxt'
        with mock.patch.object(self._session, 'host.get_by_name_label') \
                as fake_get_ref:
            fake_get_ref.return_value = ['fake_host_ref1', 'fake_host_ref2']
            self.assertRaises(exception.MigrationPreCheckError,
                              self.vmops.check_can_live_migrate_destination,
                              ctxt, fake_instance, block_migration,
                              disk_over_commit)

    @mock.patch.object(vm_utils, 'host_in_this_pool')
    def test_request_pool_migrate_to_outer_pool_host(self, mock_is_same_pool):
        # Caller asks for no block live migrate while the dest host is not in
        # the same pool with the src host, raise exception
        fake_instance = objects.Instance(host="fake_host")
        block_migration = False
        disk_over_commit = False
        ctxt = 'ctxt'
        mock_is_same_pool.return_value = False
        with mock.patch.object(self._session, 'host.get_by_name_label') \
                as fake_get_ref:
            fake_get_ref.return_value = ['fake_host_ref1']
            self.assertRaises(exception.MigrationPreCheckError,
                              self.vmops.check_can_live_migrate_destination,
                              ctxt, fake_instance, block_migration,
                              disk_over_commit)

    @mock.patch.object(vmops.VMOps, 'create_interim_networks')
    @mock.patch.object(vmops.VMOps, 'connect_block_device_volumes')
    def test_pre_live_migration(self, mock_connect, mock_create):
        migrate_data = objects.XenapiLiveMigrateData()
        migrate_data.block_migration = True
        sr_uuid_map = {"sr_uuid": "sr_ref"}
        vif_uuid_map = {"neutron_vif_uuid": "dest_network_ref"}
        mock_connect.return_value = {"sr_uuid": "sr_ref"}
        mock_create.return_value = {"neutron_vif_uuid": "dest_network_ref"}
        result = self.vmops.pre_live_migration(
                None, None, "bdi", "fake_network_info", None, migrate_data)

        self.assertTrue(result.block_migration)
        self.assertEqual(result.sr_uuid_map, sr_uuid_map)
        self.assertEqual(result.vif_uuid_map, vif_uuid_map)
        mock_connect.assert_called_once_with("bdi")
        mock_create.assert_called_once_with("fake_network_info")

    @mock.patch.object(vmops.VMOps, '_delete_networks_and_bridges')
    def test_post_live_migration_at_source(self, mock_delete):
        self.vmops.post_live_migration_at_source('fake_context',
                                                 'fake_instance',
                                                 'fake_network_info')
        mock_delete.assert_called_once_with('fake_instance',
                                            'fake_network_info')


class LiveMigrateFakeVersionTestCase(VMOpsTestBase):
    @mock.patch.object(vmops.VMOps, '_pv_device_reported')
    @mock.patch.object(vmops.VMOps, '_pv_driver_version_reported')
    @mock.patch.object(vmops.VMOps, '_write_fake_pv_version')
    def test_ensure_pv_driver_info_for_live_migration(
        self,
        mock_write_fake_pv_version,
        mock_pv_driver_version_reported,
        mock_pv_device_reported):

        mock_pv_device_reported.return_value = True
        mock_pv_driver_version_reported.return_value = False
        fake_instance = {"name": "fake_instance"}
        self.vmops._ensure_pv_driver_info_for_live_migration(fake_instance,
                                                             "vm_rec")

        mock_write_fake_pv_version.assert_called_once_with(fake_instance,
                                                           "vm_rec")

    @mock.patch.object(vmops.VMOps, '_read_from_xenstore')
    def test_pv_driver_version_reported_None(self, fake_read_from_xenstore):
        fake_read_from_xenstore.return_value = '"None"'
        fake_instance = {"name": "fake_instance"}
        self.assertFalse(self.vmops._pv_driver_version_reported(fake_instance,
                                                                "vm_ref"))

    @mock.patch.object(vmops.VMOps, '_read_from_xenstore')
    def test_pv_driver_version_reported(self, fake_read_from_xenstore):
        fake_read_from_xenstore.return_value = '6.2.0'
        fake_instance = {"name": "fake_instance"}
        self.assertTrue(self.vmops._pv_driver_version_reported(fake_instance,
                                                               "vm_ref"))

    @mock.patch.object(vmops.VMOps, '_read_from_xenstore')
    def test_pv_device_reported(self, fake_read_from_xenstore):
        with mock.patch.object(self._session.VM, 'get_record') as fake_vm_rec:
            fake_vm_rec.return_value = {'VIFs': 'fake-vif-object'}
            with mock.patch.object(self._session, 'call_xenapi') as fake_call:
                fake_call.return_value = {'device': '0'}
                fake_read_from_xenstore.return_value = '4'
                fake_instance = {"name": "fake_instance"}
                self.assertTrue(self.vmops._pv_device_reported(fake_instance,
                                "vm_ref"))

    @mock.patch.object(vmops.VMOps, '_read_from_xenstore')
    def test_pv_device_not_reported(self, fake_read_from_xenstore):
        with mock.patch.object(self._session.VM, 'get_record') as fake_vm_rec:
            fake_vm_rec.return_value = {'VIFs': 'fake-vif-object'}
            with mock.patch.object(self._session, 'call_xenapi') as fake_call:
                fake_call.return_value = {'device': '0'}
                fake_read_from_xenstore.return_value = '0'
                fake_instance = {"name": "fake_instance"}
                self.assertFalse(self.vmops._pv_device_reported(fake_instance,
                                 "vm_ref"))

    @mock.patch.object(vmops.VMOps, '_read_from_xenstore')
    def test_pv_device_None_reported(self, fake_read_from_xenstore):
        with mock.patch.object(self._session.VM, 'get_record') as fake_vm_rec:
            fake_vm_rec.return_value = {'VIFs': 'fake-vif-object'}
            with mock.patch.object(self._session, 'call_xenapi') as fake_call:
                fake_call.return_value = {'device': '0'}
                fake_read_from_xenstore.return_value = '"None"'
                fake_instance = {"name": "fake_instance"}
                self.assertFalse(self.vmops._pv_device_reported(fake_instance,
                                 "vm_ref"))

    @mock.patch.object(vmops.VMOps, '_write_to_xenstore')
    def test_write_fake_pv_version(self, fake_write_to_xenstore):
        fake_write_to_xenstore.return_value = 'fake_return'
        fake_instance = {"name": "fake_instance"}
        with mock.patch.object(self._session, 'product_version') as version:
            version.return_value = ('6', '2', '0')
            self.assertIsNone(self.vmops._write_fake_pv_version(fake_instance,
                                                                "vm_ref"))


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

    @mock.patch.object(volumeops.VolumeOps, "connect_volume")
    @mock.patch.object(volume_utils, 'forget_sr')
    def test_connect_block_device_volumes_calls_forget_sr(self, mock_forget,
                                                          mock_connect):
        bdms = [{'connection_info': 'info1'},
                {'connection_info': 'info2'}]

        def fake_connect(connection_info):
            expected = bdms[mock_connect.call_count - 1]['connection_info']
            self.assertEqual(expected, connection_info)

            if mock_connect.call_count == 2:
                raise exception.VolumeDriverNotFound(driver_type='123')

            return ('sr_uuid_1', None)

        def fake_call_xenapi(method, uuid):
            self.assertEqual('sr_uuid_1', uuid)
            return 'sr_ref_1'

        mock_connect.side_effect = fake_connect

        with mock.patch.object(self.vmops._session, "call_xenapi",
                               side_effect=fake_call_xenapi):
            self.assertRaises(exception.VolumeDriverNotFound,
                              self.vmops.connect_block_device_volumes,
                              {'block_device_mapping': bdms})
            mock_forget.assert_called_once_with(self.vmops._session,
                                                'sr_ref_1')

    def _call_live_migrate_command_with_migrate_send_data(self, migrate_data):
        command_name = 'test_command'
        vm_ref = "vm_ref"

        def side_effect(method, *args):
            if method == "SR.get_by_uuid":
                return "sr_ref_new"
            xmlrpclib.dumps(args, method, allow_none=1)

        with mock.patch.object(self.vmops,
                               "_generate_vdi_map") as mock_gen_vdi_map, \
                mock.patch.object(self.vmops._session,
                                  'call_xenapi') as mock_call_xenapi, \
                mock.patch.object(vm_utils, 'host_in_this_pool'
                                  ) as mock_host_in_this_pool, \
                mock.patch.object(self.vmops,
                                  "_generate_vif_network_map") as mock_vif_map:
            mock_call_xenapi.side_effect = side_effect
            mock_gen_vdi_map.side_effect = [
                    {"vdi": "sr_ref"}, {"vdi": "sr_ref_2"}]
            mock_vif_map.return_value = {"vif_ref1": "dest_net_ref"}
            mock_host_in_this_pool.return_value = False

            self.vmops._call_live_migrate_command(command_name,
                                                  vm_ref, migrate_data)

            expect_vif_map = {}
            if 'vif_uuid_map' in migrate_data:
                expect_vif_map.update({"vif_ref1": "dest_net_ref"})
            expected_vdi_map = {'vdi': 'sr_ref'}
            if 'sr_uuid_map' in migrate_data:
                expected_vdi_map = {'vdi': 'sr_ref_2'}
            self.assertEqual(mock_call_xenapi.call_args_list[-1],
                mock.call(command_name, vm_ref,
                    migrate_data.migrate_send_data, True,
                    expected_vdi_map, expect_vif_map, {}))

            self.assertEqual(mock_gen_vdi_map.call_args_list[0],
                mock.call(migrate_data.destination_sr_ref, vm_ref))
            if 'sr_uuid_map' in migrate_data:
                self.assertEqual(mock_gen_vdi_map.call_args_list[1],
                    mock.call(migrate_data.sr_uuid_map["sr_uuid2"], vm_ref,
                              "sr_ref_new"))

    def test_call_live_migrate_command_with_full_data(self):
        migrate_data = objects.XenapiLiveMigrateData()
        migrate_data.migrate_send_data = {"foo": "bar"}
        migrate_data.destination_sr_ref = "sr_ref"
        migrate_data.sr_uuid_map = {"sr_uuid2": "sr_ref_3"}
        migrate_data.vif_uuid_map = {"vif_id": "dest_net_ref"}
        self._call_live_migrate_command_with_migrate_send_data(migrate_data)

    def test_call_live_migrate_command_with_no_sr_uuid_map(self):
        migrate_data = objects.XenapiLiveMigrateData()
        migrate_data.migrate_send_data = {"foo": "baz"}
        migrate_data.destination_sr_ref = "sr_ref"
        self._call_live_migrate_command_with_migrate_send_data(migrate_data)

    def test_call_live_migrate_command_with_no_migrate_send_data(self):
        migrate_data = objects.XenapiLiveMigrateData()
        self.assertRaises(exception.InvalidParameterValue,
                self._call_live_migrate_command_with_migrate_send_data,
                migrate_data)

    @mock.patch.object(vmops.VMOps, '_call_live_migrate_command')
    def test_check_can_live_migrate_source_with_xcp2(self, mock_call_migrate):
        ctxt = 'ctxt'
        fake_instance = {"name": "fake_instance"}
        fake_dest_check_data = objects.XenapiLiveMigrateData()
        fake_dest_check_data.block_migration = True
        mock_call_migrate.side_effect = \
            xenapi_fake.xenapi_session.XenAPI.Failure(['VDI_NOT_IN_MAP'])

        with mock.patch.object(self.vmops,
                               '_get_iscsi_srs') as mock_iscsi_srs, \
            mock.patch.object(self.vmops,
                              '_get_vm_opaque_ref') as mock_vm, \
            mock.patch.object(self.vmops,
                              '_get_host_software_versions') as mock_host_sw:
            mock_iscsi_srs.return_value = []
            mock_vm.return_value = 'vm_ref'
            mock_host_sw.return_value = {'platform_name': 'XCP',
                                         'platform_version': '2.1.0'}
            fake_returned_data = self.vmops.check_can_live_migrate_source(
                ctxt, fake_instance, fake_dest_check_data)

        self.assertEqual(fake_returned_data, fake_dest_check_data)

    @mock.patch.object(vmops.VMOps, '_call_live_migrate_command')
    def test_check_can_live_migrate_source_with_xcp2_vif_raise(self,
                                                            mock_call_migrate):
        ctxt = 'ctxt'
        fake_instance = {"name": "fake_instance"}
        fake_dest_check_data = objects.XenapiLiveMigrateData()
        fake_dest_check_data.block_migration = True
        mock_call_migrate.side_effect = \
            xenapi_fake.xenapi_session.XenAPI.Failure(['VIF_NOT_IN_MAP'])

        with mock.patch.object(self.vmops,
                               '_get_iscsi_srs') as mock_iscsi_srs, \
            mock.patch.object(self.vmops,
                              '_get_vm_opaque_ref') as mock_vm, \
            mock.patch.object(self.vmops,
                              '_get_host_software_versions') as mock_host_sw:
            mock_iscsi_srs.return_value = []
            mock_vm.return_value = 'vm_ref'
            mock_host_sw.return_value = {'platform_name': 'XCP',
                                         'platform_version': '2.1.0'}
            self.assertRaises(exception.MigrationPreCheckError,
                              self.vmops.check_can_live_migrate_source, ctxt,
                              fake_instance, fake_dest_check_data)

    @mock.patch.object(vmops.VMOps, '_call_live_migrate_command')
    def test_check_can_live_migrate_source_with_xcp2_sw_raise(self,
                                                            mock_call_migrate):
        ctxt = 'ctxt'
        fake_instance = {"name": "fake_instance"}
        fake_dest_check_data = objects.XenapiLiveMigrateData()
        fake_dest_check_data.block_migration = True
        mock_call_migrate.side_effect = \
            xenapi_fake.xenapi_session.XenAPI.Failure(['VDI_NOT_IN_MAP'])

        with mock.patch.object(self.vmops,
                               '_get_iscsi_srs') as mock_iscsi_srs, \
            mock.patch.object(self.vmops,
                              '_get_vm_opaque_ref') as mock_vm, \
            mock.patch.object(self.vmops,
                              '_get_host_software_versions') as mock_host_sw:
            mock_iscsi_srs.return_value = []
            mock_vm.return_value = 'vm_ref'
            mock_host_sw.return_value = {'platform_name': 'XCP',
                                         'platform_version': '1.1.0'}
            self.assertRaises(exception.MigrationPreCheckError,
                              self.vmops.check_can_live_migrate_source, ctxt,
                              fake_instance, fake_dest_check_data)

    def test_generate_vif_network_map(self):
        with mock.patch.object(self._session.VIF,
                               'get_other_config') as mock_other_config, \
             mock.patch.object(self._session.VM,
                              'get_VIFs') as mock_get_vif:
            mock_other_config.side_effect = [{'neutron-port-id': 'vif_id_a'},
                                             {'neutron-port-id': 'vif_id_b'}]
            mock_get_vif.return_value = ['vif_ref1', 'vif_ref2']
            vif_uuid_map = {'vif_id_b': 'dest_net_ref2',
                            'vif_id_a': 'dest_net_ref1'}
            vif_map = self.vmops._generate_vif_network_map('vm_ref',
                                                           vif_uuid_map)
            expected = {'vif_ref1': 'dest_net_ref1',
                        'vif_ref2': 'dest_net_ref2'}
            self.assertEqual(vif_map, expected)

    def test_generate_vif_network_map_default_net(self):
        with mock.patch.object(self._session.VIF,
                               'get_other_config') as mock_other_config, \
             mock.patch.object(self._session.VM,
                              'get_VIFs') as mock_get_vif:
            mock_other_config.side_effect = [{'neutron-port-id': 'vif_id_a'},
                                             {'neutron-port-id': 'vif_id_b'}]
            mock_get_vif.return_value = ['vif_ref1']
            vif_uuid_map = {'': 'default_net_ref'}
            vif_map = self.vmops._generate_vif_network_map('vm_ref',
                                                           vif_uuid_map)
            expected = {'vif_ref1': 'default_net_ref'}
            self.assertEqual(vif_map, expected)

    def test_generate_vif_network_map_exception(self):
        with mock.patch.object(self._session.VIF,
                               'get_other_config') as mock_other_config, \
             mock.patch.object(self._session.VM,
                              'get_VIFs') as mock_get_vif:
            mock_other_config.side_effect = [{'neutron-port-id': 'vif_id_a'},
                                             {'neutron-port-id': 'vif_id_b'}]
            mock_get_vif.return_value = ['vif_ref1', 'vif_ref2']
            vif_uuid_map = {'vif_id_c': 'dest_net_ref2',
                            'vif_id_d': 'dest_net_ref1'}
            self.assertRaises(exception.MigrationError,
                              self.vmops._generate_vif_network_map,
                              'vm_ref', vif_uuid_map)

    def test_generate_vif_network_map_exception_no_iface(self):
        with mock.patch.object(self._session.VIF,
                               'get_other_config') as mock_other_config, \
             mock.patch.object(self._session.VM,
                              'get_VIFs') as mock_get_vif:
            mock_other_config.return_value = {}
            mock_get_vif.return_value = ['vif_ref1']
            vif_uuid_map = {}
            self.assertRaises(exception.MigrationError,
                              self.vmops._generate_vif_network_map,
                              'vm_ref', vif_uuid_map)

    def test_delete_networks_and_bridges(self):
        self.vmops.vif_driver = mock.Mock()
        network_info = [{'id': 'fake_vif'}]
        self.vmops._delete_networks_and_bridges('fake_instance', network_info)
        self.vmops.vif_driver.delete_network_and_bridge.\
            assert_called_once_with('fake_instance', 'fake_vif')

    def test_create_interim_networks(self):
        class FakeVifDriver(object):
            def create_vif_interim_network(self, vif):
                if vif['id'] == "vif_1":
                    return "network_ref_1"
                if vif['id'] == "vif_2":
                    return "network_ref_2"

        network_info = [{'id': "vif_1"}, {'id': 'vif_2'}]
        self.vmops.vif_driver = FakeVifDriver()
        vif_map = self.vmops.create_interim_networks(network_info)
        self.assertEqual(vif_map, {'vif_1': 'network_ref_1',
                                   'vif_2': 'network_ref_2'})


class RollbackLiveMigrateDestinationTestCase(VMOpsTestBase):
    @mock.patch.object(vmops.VMOps, '_delete_networks_and_bridges')
    @mock.patch.object(volume_utils, 'find_sr_by_uuid', return_value='sr_ref')
    @mock.patch.object(volume_utils, 'forget_sr')
    def test_rollback_dest_calls_sr_forget(self, forget_sr, sr_ref,
                                           delete_networks_bridges):
        block_device_info = {'block_device_mapping': [{'connection_info':
                                {'data': {'volume_id': 'fake-uuid',
                                          'target_iqn': 'fake-iqn',
                                          'target_portal': 'fake-portal'}}}]}
        network_info = [{'id': 'vif1'}]
        self.vmops.rollback_live_migration_at_destination('instance',
                                                          network_info,
                                                          block_device_info)
        forget_sr.assert_called_once_with(self.vmops._session, 'sr_ref')
        delete_networks_bridges.assert_called_once_with(
            'instance', [{'id': 'vif1'}])

    @mock.patch.object(vmops.VMOps, '_delete_networks_and_bridges')
    @mock.patch.object(volume_utils, 'forget_sr')
    @mock.patch.object(volume_utils, 'find_sr_by_uuid',
                       side_effect=test.TestingException)
    def test_rollback_dest_handles_exception(self, find_sr_ref, forget_sr,
                                             delete_networks_bridges):
        block_device_info = {'block_device_mapping': [{'connection_info':
                                {'data': {'volume_id': 'fake-uuid',
                                          'target_iqn': 'fake-iqn',
                                          'target_portal': 'fake-portal'}}}]}
        network_info = [{'id': 'vif1'}]
        self.vmops.rollback_live_migration_at_destination('instance',
                                                          network_info,
                                                          block_device_info)
        self.assertFalse(forget_sr.called)
        delete_networks_bridges.assert_called_once_with(
            'instance', [{'id': 'vif1'}])


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


class AttachInterfaceTestCase(VMOpsTestBase):
    """Test VIF hot plug/unplug"""
    def setUp(self):
        super(AttachInterfaceTestCase, self).setUp()
        self.vmops.vif_driver = mock.Mock()
        self.fake_vif = {'id': '12345'}
        self.fake_instance = mock.Mock()
        self.fake_instance.uuid = '6478'

    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
    def test_attach_interface(self, mock_get_vm_opaque_ref):
        mock_get_vm_opaque_ref.return_value = 'fake_vm_ref'
        with mock.patch.object(self._session.VM, 'get_allowed_VIF_devices')\
            as fake_devices:
            fake_devices.return_value = [2, 3, 4]
            self.vmops.attach_interface(self.fake_instance, self.fake_vif)
            fake_devices.assert_called_once_with('fake_vm_ref')
            mock_get_vm_opaque_ref.assert_called_once_with(self.fake_instance)
            self.vmops.vif_driver.plug.assert_called_once_with(
                self.fake_instance, self.fake_vif, vm_ref='fake_vm_ref',
                device=2)

    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
    def test_attach_interface_no_devices(self, mock_get_vm_opaque_ref):
        mock_get_vm_opaque_ref.return_value = 'fake_vm_ref'
        with mock.patch.object(self._session.VM, 'get_allowed_VIF_devices')\
            as fake_devices:
            fake_devices.return_value = []
            self.assertRaises(exception.InterfaceAttachFailed,
                              self.vmops.attach_interface,
                              self.fake_instance, self.fake_vif)

    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
    def test_attach_interface_plug_failed(self, mock_get_vm_opaque_ref):
        mock_get_vm_opaque_ref.return_value = 'fake_vm_ref'
        with mock.patch.object(self._session.VM, 'get_allowed_VIF_devices')\
            as fake_devices:
            fake_devices.return_value = [2, 3, 4]
            self.vmops.vif_driver.plug.side_effect =\
                exception.VirtualInterfacePlugException('Failed to plug VIF')
            self.assertRaises(exception.VirtualInterfacePlugException,
                              self.vmops.attach_interface,
                              self.fake_instance, self.fake_vif)
            self.vmops.vif_driver.plug.assert_called_once_with(
                self.fake_instance, self.fake_vif, vm_ref='fake_vm_ref',
                device=2)
            self.vmops.vif_driver.unplug.assert_called_once_with(
                self.fake_instance, self.fake_vif, 'fake_vm_ref')

    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
    def test_attach_interface_reraise_exception(self, mock_get_vm_opaque_ref):
        mock_get_vm_opaque_ref.return_value = 'fake_vm_ref'
        with mock.patch.object(self._session.VM, 'get_allowed_VIF_devices')\
            as fake_devices:
            fake_devices.return_value = [2, 3, 4]
            self.vmops.vif_driver.plug.side_effect =\
                exception.VirtualInterfacePlugException('Failed to plug VIF')
            self.vmops.vif_driver.unplug.side_effect =\
                exception.VirtualInterfaceUnplugException(
                    'Failed to unplug VIF')
            ex = self.assertRaises(exception.VirtualInterfacePlugException,
                                   self.vmops.attach_interface,
                                   self.fake_instance, self.fake_vif)
            self.assertEqual('Failed to plug VIF', six.text_type(ex))
            self.vmops.vif_driver.plug.assert_called_once_with(
                self.fake_instance, self.fake_vif, vm_ref='fake_vm_ref',
                device=2)
            self.vmops.vif_driver.unplug.assert_called_once_with(
                self.fake_instance, self.fake_vif, 'fake_vm_ref')

    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
    def test_detach_interface(self, mock_get_vm_opaque_ref):
        mock_get_vm_opaque_ref.return_value = 'fake_vm_ref'
        self.vmops.detach_interface(self.fake_instance, self.fake_vif)
        mock_get_vm_opaque_ref.assert_called_once_with(self.fake_instance)
        self.vmops.vif_driver.unplug.assert_called_once_with(
            self.fake_instance, self.fake_vif, 'fake_vm_ref')

    @mock.patch('nova.virt.xenapi.vmops.LOG.exception')
    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref')
    def test_detach_interface_exception(self, mock_get_vm_opaque_ref,
                                        mock_log_exception):
        mock_get_vm_opaque_ref.return_value = 'fake_vm_ref'
        self.vmops.vif_driver.unplug.side_effect =\
            exception.VirtualInterfaceUnplugException('Failed to unplug VIF')

        self.assertRaises(exception.VirtualInterfaceUnplugException,
                          self.vmops.detach_interface,
                          self.fake_instance, self.fake_vif)
        mock_log_exception.assert_called()

    @mock.patch('nova.virt.xenapi.vmops.LOG.exception',
                new_callable=mock.NonCallableMock)
    @mock.patch.object(vmops.VMOps, '_get_vm_opaque_ref',
                       side_effect=exception.InstanceNotFound(
                           instance_id='fake_vm_ref'))
    def test_detach_interface_instance_not_found(
            self, mock_get_vm_opaque_ref, mock_log_exception):
        self.assertRaises(exception.InstanceNotFound,
                          self.vmops.detach_interface,
                          self.fake_instance, self.fake_vif)
