# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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
Test suite for VMwareAPI.
"""

import contextlib
import copy

import mock
import mox
from oslo.config import cfg
import suds

from nova import block_device
from nova.compute import api as compute_api
from nova.compute import power_state
from nova.compute import task_states
from nova import context
from nova import db
from nova import exception
from nova.openstack.common import jsonutils
from nova.openstack.common import uuidutils
from nova import test
import nova.tests.image.fake
from nova.tests import matchers
from nova.tests import utils
from nova.tests.virt.vmwareapi import db_fakes
from nova.tests.virt.vmwareapi import stubs
from nova import unit
from nova import utils as nova_utils
from nova.virt import driver as v_driver
from nova.virt import fake
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
from nova.virt.vmwareapi import vmware_images
from nova.virt.vmwareapi import volume_util
from nova.virt.vmwareapi import volumeops


class fake_vm_ref(object):
    def __init__(self):
        self.value = 4
        self._type = 'VirtualMachine'


class fake_service_content(object):
    def __init__(self):
        self.ServiceContent = vmwareapi_fake.DataObject()
        self.ServiceContent.fake = 'fake'


class VMwareSudsTest(test.NoDBTestCase):

    def setUp(self):
        super(VMwareSudsTest, self).setUp()

        def new_client_init(self, url, **kwargs):
            return

        mock.patch.object(suds.client.Client,
                          '__init__', new=new_client_init).start()
        self.vim = self._vim_create()
        self.addCleanup(mock.patch.stopall)

    def _vim_create(self):

        def fake_retrieve_service_content(fake):
            return fake_service_content()

        self.stubs.Set(vim.Vim, 'retrieve_service_content',
                fake_retrieve_service_content)
        return vim.Vim()

    def test_exception_with_deepcopy(self):
        self.assertIsNotNone(self.vim)
        self.assertRaises(error_util.VimException,
                          copy.deepcopy, self.vim)


class VMwareSessionTestCase(test.NoDBTestCase):

    def _fake_is_vim_object(self, module):
        return True

    @mock.patch('time.sleep')
    def test_call_method_vim_fault(self, mock_sleep):

        def _fake_create_session(self):
            session = vmwareapi_fake.DataObject()
            session.key = 'fake_key'
            session.userName = 'fake_username'
            self._session = session

        def _fake_session_is_active(self):
            return False

        with contextlib.nested(
            mock.patch.object(driver.VMwareAPISession, '_is_vim_object',
                              self._fake_is_vim_object),
            mock.patch.object(driver.VMwareAPISession, '_create_session',
                              _fake_create_session),
            mock.patch.object(driver.VMwareAPISession, '_session_is_active',
                              _fake_session_is_active)
        ) as (_fake_vim, _fake_create, _fake_is_active):
            api_session = driver.VMwareAPISession()
            args = ()
            kwargs = {}
            self.assertRaises(error_util.VimFaultException,
                              api_session._call_method,
                              stubs, 'fake_temp_method_exception',
                              *args, **kwargs)

    def test_call_method_vim_empty(self):

        def _fake_create_session(self):
            session = vmwareapi_fake.DataObject()
            session.key = 'fake_key'
            session.userName = 'fake_username'
            self._session = session

        def _fake_session_is_active(self):
            return True

        with contextlib.nested(
            mock.patch.object(driver.VMwareAPISession, '_is_vim_object',
                              self._fake_is_vim_object),
            mock.patch.object(driver.VMwareAPISession, '_create_session',
                              _fake_create_session),
            mock.patch.object(driver.VMwareAPISession, '_session_is_active',
                              _fake_session_is_active)
        ) as (_fake_vim, _fake_create, _fake_is_active):
            api_session = driver.VMwareAPISession()
            args = ()
            kwargs = {}
            res = api_session._call_method(stubs, 'fake_temp_method_exception',
                                           *args, **kwargs)
            self.assertEqual([], res)

    @mock.patch('time.sleep')
    def test_call_method_session_exception(self, mock_sleep):

        def _fake_create_session(self):
            session = vmwareapi_fake.DataObject()
            session.key = 'fake_key'
            session.userName = 'fake_username'
            self._session = session

        with contextlib.nested(
            mock.patch.object(driver.VMwareAPISession, '_is_vim_object',
                              self._fake_is_vim_object),
            mock.patch.object(driver.VMwareAPISession, '_create_session',
                              _fake_create_session),
        ) as (_fake_vim, _fake_create):
            api_session = driver.VMwareAPISession()
            args = ()
            kwargs = {}
            self.assertRaises(error_util.SessionConnectionException,
                              api_session._call_method,
                              stubs, 'fake_temp_session_exception',
                              *args, **kwargs)


class VMwareAPIConfTestCase(test.NoDBTestCase):
    """Unit tests for VMWare API configurations."""
    def setUp(self):
        super(VMwareAPIConfTestCase, self).setUp()

    def tearDown(self):
        super(VMwareAPIConfTestCase, self).tearDown()

    def test_configure_without_wsdl_loc_override(self):
        # Test the default configuration behavior. By default,
        # use the WSDL sitting on the host we are talking to in
        # order to bind the SOAP client.
        wsdl_loc = cfg.CONF.vmware.wsdl_location
        self.assertIsNone(wsdl_loc)
        wsdl_url = vim.Vim.get_wsdl_url("https", "www.example.com")
        url = vim.Vim.get_soap_url("https", "www.example.com")
        self.assertEqual("https://www.example.com/sdk/vimService.wsdl",
                         wsdl_url)
        self.assertEqual("https://www.example.com/sdk", url)

    def test_configure_without_wsdl_loc_override_using_ipv6(self):
        # Same as above but with ipv6 based host ip
        wsdl_loc = cfg.CONF.vmware.wsdl_location
        self.assertIsNone(wsdl_loc)
        wsdl_url = vim.Vim.get_wsdl_url("https", "::1")
        url = vim.Vim.get_soap_url("https", "::1")
        self.assertEqual("https://[::1]/sdk/vimService.wsdl",
                         wsdl_url)
        self.assertEqual("https://[::1]/sdk", url)

    def test_configure_with_wsdl_loc_override(self):
        # Use the setting vmwareapi_wsdl_loc to override the
        # default path to the WSDL.
        #
        # This is useful as a work-around for XML parsing issues
        # found when using some WSDL in combination with some XML
        # parsers.
        #
        # The wsdl_url should point to a different host than the one we
        # are actually going to send commands to.
        fake_wsdl = "https://www.test.com/sdk/foo.wsdl"
        self.flags(wsdl_location=fake_wsdl, group='vmware')
        wsdl_loc = cfg.CONF.vmware.wsdl_location
        self.assertIsNotNone(wsdl_loc)
        self.assertEqual(fake_wsdl, wsdl_loc)
        wsdl_url = vim.Vim.get_wsdl_url("https", "www.example.com")
        url = vim.Vim.get_soap_url("https", "www.example.com")
        self.assertEqual(fake_wsdl, wsdl_url)
        self.assertEqual("https://www.example.com/sdk", url)


class VMwareAPIVMTestCase(test.NoDBTestCase):
    """Unit tests for Vmware API connection calls."""

    def setUp(self):
        super(VMwareAPIVMTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake', is_admin=False)
        self.flags(host_ip='test_url',
                   host_username='test_username',
                   host_password='test_pass',
                   cluster_name='test_cluster',
                   use_linked_clone=False, group='vmware')
        self.flags(vnc_enabled=False,
                   image_cache_subdirectory_name='vmware_base')
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.node_name = 'test_url'
        self.ds = 'ds1'
        self.context = context.RequestContext(self.user_id, self.project_id)
        db_fakes.stub_out_db_instance_api(self.stubs)
        stubs.set_stubs(self.stubs)
        vmwareapi_fake.reset()
        self.conn = driver.VMwareESXDriver(fake.FakeVirtAPI)
        # NOTE(vish): none of the network plugging code is actually
        #             being tested
        self.network_info = utils.get_test_network_info()

        self.image = {
            'id': 'c1c8ce3d-c2e0-4247-890c-ccf5cc1c004c',
            'disk_format': 'vhd',
            'size': 512,
        }
        nova.tests.image.fake.stub_out_image_service(self.stubs)
        self.vnc_host = 'test_url'

    def tearDown(self):
        super(VMwareAPIVMTestCase, self).tearDown()
        vmwareapi_fake.cleanup()
        nova.tests.image.fake.FakeImageService_reset()

    def test_VC_Connection(self):
        self.attempts = 0
        self.login_session = vmwareapi_fake.FakeVim()._login()

        def _fake_login(_self):
            self.attempts += 1
            if self.attempts == 1:
                raise exception.NovaException('Here is my fake exception')
            return self.login_session

        self.stubs.Set(vmwareapi_fake.FakeVim, '_login', _fake_login)
        self.conn = driver.VMwareAPISession()
        self.assertEqual(self.attempts, 2)

    def _create_instance_in_the_db(self, node=None, set_image_ref=True,
                                   uuid=None):
        if not node:
            node = self.node_name
        if not uuid:
            uuid = uuidutils.generate_uuid()
        values = {'name': 'fake_name',
                  'id': 1,
                  'uuid': uuid,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'kernel_id': "fake_kernel_uuid",
                  'ramdisk_id': "fake_ramdisk_uuid",
                  'mac_address': "de:ad:be:ef:be:ef",
                  'instance_type': 'm1.large',
                  'node': node,
                  'root_gb': 80,
                  }
        if set_image_ref:
            values['image_ref'] = "fake_image_uuid"
        self.instance_node = node
        self.uuid = uuid
        self.instance = db.instance_create(None, values)

    def _create_vm(self, node=None, num_instances=1, uuid=None):
        """Create and spawn the VM."""
        if not node:
            node = self.node_name
        self._create_instance_in_the_db(node=node, uuid=uuid)
        self.type_data = db.flavor_get_by_name(None, 'm1.large')
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=None)
        self._check_vm_record(num_instances=num_instances)

    def _check_vm_record(self, num_instances=1):
        """
        Check if the spawned VM's properties correspond to the instance in
        the db.
        """
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), num_instances)

        # Get Nova record for VM
        vm_info = self.conn.get_info({'uuid': self.uuid,
                                      'name': 1,
                                      'node': self.instance_node})

        # Get record for VM
        vms = vmwareapi_fake._get_objects("VirtualMachine")
        vm = vms.objects[0]

        # Check that m1.large above turned into the right thing.
        mem_kib = long(self.type_data['memory_mb']) << 10
        vcpus = self.type_data['vcpus']
        self.assertEqual(vm_info['max_mem'], mem_kib)
        self.assertEqual(vm_info['mem'], mem_kib)
        self.assertEqual(vm.get("summary.config.numCpu"), vcpus)
        self.assertEqual(vm.get("summary.config.memorySizeMB"),
                         self.type_data['memory_mb'])

        self.assertEqual(
            vm.get("config.hardware.device")[2].device.obj_name,
            "ns0:VirtualE1000")
        # Check that the VM is running according to Nova
        self.assertEqual(vm_info['state'], power_state.RUNNING)

        # Check that the VM is running according to vSphere API.
        self.assertEqual(vm.get("runtime.powerState"), 'poweredOn')

        found_vm_uuid = False
        found_iface_id = False
        for c in vm.get("config.extraConfig"):
            if (c.key == "nvp.vm-uuid" and c.value == self.instance['uuid']):
                found_vm_uuid = True
            if (c.key == "nvp.iface-id.0" and c.value == "vif-xxx-yyy-zzz"):
                found_iface_id = True

        self.assertTrue(found_vm_uuid)
        self.assertTrue(found_iface_id)

    def _check_vm_info(self, info, pwr_state=power_state.RUNNING):
        """
        Check if the get_info returned values correspond to the instance
        object in the db.
        """
        mem_kib = long(self.type_data['memory_mb']) << 10
        self.assertEqual(info["state"], pwr_state)
        self.assertEqual(info["max_mem"], mem_kib)
        self.assertEqual(info["mem"], mem_kib)
        self.assertEqual(info["num_cpu"], self.type_data['vcpus'])

    def test_list_instances(self):
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 0)

    def test_list_instances_1(self):
        self._create_vm()
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 1)

    def test_list_instance_uuids(self):
        self._create_vm()
        uuids = self.conn.list_instance_uuids()
        self.assertEqual(len(uuids), 1)

    def test_list_instance_uuids_invalid_uuid(self):
        self._create_vm(uuid='fake_id')
        uuids = self.conn.list_instance_uuids()
        self.assertEqual(len(uuids), 0)

    def test_instance_dir_disk_created(self):
        """Test image file is cached when even when use_linked_clone
            is False
        """

        self._create_vm()
        inst_file_path = '[%s] %s/fake_name.vmdk' % (self.ds, self.uuid)
        cache = ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.vmdk' %
                 self.ds)
        self.assertTrue(vmwareapi_fake.get_file(inst_file_path))
        self.assertTrue(vmwareapi_fake.get_file(cache))

    def test_cache_dir_disk_created(self):
        """Test image disk is cached when use_linked_clone is True."""
        self.flags(use_linked_clone=True, group='vmware')
        self._create_vm()
        file = ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.vmdk' %
                self.ds)
        root = ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.80.vmdk' %
                self.ds)
        self.assertTrue(vmwareapi_fake.get_file(file))
        self.assertTrue(vmwareapi_fake.get_file(root))

    def test_spawn(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_disk_extend(self):
        self.mox.StubOutWithMock(self.conn._vmops, '_extend_virtual_disk')
        requested_size = 80 * unit.Mi
        self.conn._vmops._extend_virtual_disk(mox.IgnoreArg(),
                requested_size, mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_disk_extend_sparse(self):
        self.mox.StubOutWithMock(vmware_images, 'get_vmdk_size_and_properties')
        result = [1024, {"vmware_ostype": "otherGuest",
                         "vmware_adaptertype": "lsiLogic",
                         "vmware_disktype": "sparse"}]
        vmware_images.get_vmdk_size_and_properties(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(result)
        self.mox.StubOutWithMock(self.conn._vmops, '_extend_virtual_disk')
        requested_size = 80 * unit.Mi
        self.conn._vmops._extend_virtual_disk(mox.IgnoreArg(),
                requested_size, mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_disk_extend_insufficient_disk_space(self):
        self.flags(use_linked_clone=True, group='vmware')
        self.wait_task = self.conn._session._wait_for_task
        self.call_method = self.conn._session._call_method
        self.task_ref = None
        id = 'fake_image_uuid'
        cached_image = '[%s] vmware_base/%s/%s.80.vmdk' % (self.ds,
                                                           id, id)
        tmp_file = '[%s] vmware_base/%s/%s.80-flat.vmdk' % (self.ds,
                                                            id, id)

        def fake_wait_for_task(instance_uuid, task_ref):
            if task_ref == self.task_ref:
                self.task_ref = None
                self.assertTrue(vmwareapi_fake.get_file(cached_image))
                self.assertTrue(vmwareapi_fake.get_file(tmp_file))
                raise exception.NovaException('No space!')
            return self.wait_task(instance_uuid, task_ref)

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "ExtendVirtualDisk_Task":
                self.task_ref = task_ref
            return task_ref

        self.stubs.Set(self.conn._session, "_call_method", fake_call_method)
        self.stubs.Set(self.conn._session, "_wait_for_task",
                       fake_wait_for_task)

        self.assertRaises(exception.NovaException,
                          self._create_vm)
        self.assertFalse(vmwareapi_fake.get_file(cached_image))
        self.assertFalse(vmwareapi_fake.get_file(tmp_file))

    def test_spawn_disk_invalid_disk_size(self):
        self.mox.StubOutWithMock(vmware_images, 'get_vmdk_size_and_properties')
        result = [82 * unit.Gi,
                  {"vmware_ostype": "otherGuest",
                   "vmware_adaptertype": "lsiLogic",
                   "vmware_disktype": "sparse"}]
        vmware_images.get_vmdk_size_and_properties(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(result)
        self.mox.ReplayAll()
        self.assertRaises(exception.InstanceUnacceptable,
                          self._create_vm)

    def _spawn_attach_volume_vmdk(self, set_image_ref=True):
        self._create_instance_in_the_db(set_image_ref=set_image_ref)
        self.type_data = db.flavor_get_by_name(None, 'm1.large')
        self.mox.StubOutWithMock(block_device, 'volume_in_mapping')
        self.mox.StubOutWithMock(v_driver, 'block_device_info_get_mapping')
        connection_info = self._test_vmdk_connection_info('vmdk')
        root_disk = [{'connection_info': connection_info}]
        v_driver.block_device_info_get_mapping(
                mox.IgnoreArg()).AndReturn(root_disk)
        mount_point = '/dev/vdc'
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_get_res_pool_of_vm')
        volumeops.VMwareVolumeOps._get_res_pool_of_vm(
                 mox.IgnoreArg()).AndReturn('fake_res_pool')
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_relocate_vmdk_volume')
        volumeops.VMwareVolumeOps._relocate_vmdk_volume(mox.IgnoreArg(),
                 'fake_res_pool', mox.IgnoreArg())
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'attach_volume')
        volumeops.VMwareVolumeOps.attach_volume(connection_info,
                self.instance, mox.IgnoreArg())
        self.mox.ReplayAll()
        block_device_info = {'mount_device': 'vda'}
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=block_device_info)

    def test_spawn_attach_volume_vmdk(self):
        self._spawn_attach_volume_vmdk()

    def test_spawn_attach_volume_vmdk_no_image_ref(self):
        self._spawn_attach_volume_vmdk(set_image_ref=False)

    def test_spawn_attach_volume_iscsi(self):
        self._create_instance_in_the_db()
        self.type_data = db.flavor_get_by_name(None, 'm1.large')
        self.mox.StubOutWithMock(block_device, 'volume_in_mapping')
        self.mox.StubOutWithMock(v_driver, 'block_device_info_get_mapping')
        connection_info = self._test_vmdk_connection_info('iscsi')
        root_disk = [{'connection_info': connection_info}]
        v_driver.block_device_info_get_mapping(
                mox.IgnoreArg()).AndReturn(root_disk)
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'attach_volume')
        volumeops.VMwareVolumeOps.attach_volume(connection_info,
                self.instance, mox.IgnoreArg())
        self.mox.ReplayAll()
        block_device_info = {'mount_device': 'vda'}
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=block_device_info)

    def mock_upload_image(self, context, image, instance, **kwargs):
        self.assertEqual(image, 'Test-Snapshot')
        self.assertEqual(instance, self.instance)
        self.assertEqual(kwargs['disk_type'], 'preallocated')

    def _test_snapshot(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        with mock.patch.object(vmware_images, 'upload_image',
                               self.mock_upload_image):
            self.conn.snapshot(self.context, self.instance, "Test-Snapshot",
                               func_call_matcher.call)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.assertIsNone(func_call_matcher.match())

    def test_snapshot(self):
        self._create_vm()
        self._test_snapshot()

    def test_snapshot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.snapshot,
                          self.context, self.instance, "Test-Snapshot",
                          lambda *args, **kwargs: None)

    def test_reboot(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1, 'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        reboot_type = "SOFT"
        self.conn.reboot(self.context, self.instance, self.network_info,
                         reboot_type)
        info = self.conn.get_info({'name': 1, 'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_reboot_with_uuid(self):
        """Test fall back to use name when can't find by uuid."""
        self._create_vm()
        info = self.conn.get_info({'name': 'fake-name', 'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        reboot_type = "SOFT"
        self.conn.reboot(self.context, self.instance, self.network_info,
                         reboot_type)
        info = self.conn.get_info({'name': 'fake-name', 'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_reboot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.reboot,
                          self.context, self.instance, self.network_info,
                          'SOFT')

    def test_poll_rebooting_instances(self):
        self.mox.StubOutWithMock(compute_api.API, 'reboot')
        compute_api.API.reboot(mox.IgnoreArg(), mox.IgnoreArg(),
                               mox.IgnoreArg())
        self.mox.ReplayAll()
        self._create_vm()
        instances = [self.instance]
        self.conn.poll_rebooting_instances(60, instances)

    def test_reboot_not_poweredon(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.assertRaises(exception.InstanceRebootFailure, self.conn.reboot,
                          self.context, self.instance, self.network_info,
                          'SOFT')

    def test_suspend(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.SUSPENDED)

    def test_suspend_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.suspend,
                          self.instance)

    def test_resume(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.conn.resume(self.context, self.instance, self.network_info)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_resume_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.resume,
                          self.context, self.instance, self.network_info)

    def test_resume_not_suspended(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.assertRaises(exception.InstanceResumeFailure, self.conn.resume,
                          self.context, self.instance, self.network_info)

    def test_power_on(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.SHUTDOWN)
        self.conn.power_on(self.context, self.instance, self.network_info)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_power_on_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_on,
                          self.context, self.instance, self.network_info)

    def test_power_off(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.SHUTDOWN)

    def test_power_off_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_off,
                          self.instance)

    def test_power_off_suspended(self):
        self._create_vm()
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.assertRaises(exception.InstancePowerOffFailure,
                          self.conn.power_off, self.instance)

    def test_resume_state_on_host_boot(self):
        self._create_vm()
        self.mox.StubOutWithMock(vm_util, 'get_vm_state_from_name')
        self.mox.StubOutWithMock(self.conn, "reboot")
        vm_util.get_vm_state_from_name(mox.IgnoreArg(),
            self.instance['uuid']).AndReturn("poweredOff")
        self.conn.reboot(self.context, self.instance, 'network_info',
            'hard', None)
        self.mox.ReplayAll()
        self.conn.resume_state_on_host_boot(self.context, self.instance,
            'network_info')

    def test_resume_state_on_host_boot_no_reboot_1(self):
        """Don't call reboot on instance which is poweredon."""
        self._create_vm()
        self.mox.StubOutWithMock(vm_util, 'get_vm_state_from_name')
        self.mox.StubOutWithMock(self.conn, 'reboot')
        vm_util.get_vm_state_from_name(mox.IgnoreArg(),
            self.instance['uuid']).AndReturn("poweredOn")
        self.mox.ReplayAll()
        self.conn.resume_state_on_host_boot(self.context, self.instance,
            'network_info')

    def test_resume_state_on_host_boot_no_reboot_2(self):
        """Don't call reboot on instance which is suspended."""
        self._create_vm()
        self.mox.StubOutWithMock(vm_util, 'get_vm_state_from_name')
        self.mox.StubOutWithMock(self.conn, 'reboot')
        vm_util.get_vm_state_from_name(mox.IgnoreArg(),
            self.instance['uuid']).AndReturn("suspended")
        self.mox.ReplayAll()
        self.conn.resume_state_on_host_boot(self.context, self.instance,
            'network_info')

    def test_get_info(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_destroy(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 1)
        self.conn.destroy(self.context, self.instance, self.network_info)
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 0)

    def test_destroy_non_existent(self):
        self._create_instance_in_the_db()
        self.assertIsNone(self.conn.destroy(self.context, self.instance,
            self.network_info))

    def _rescue(self, config_drive=False):
        def fake_attach_disk_to_vm(*args, **kwargs):
            pass

        if config_drive:
            def fake_create_config_drive(instance, injected_files, password,
                                         data_store_name, folder,
                                         instance_uuid, cookies):
                self.assertTrue(uuidutils.is_uuid_like(instance['uuid']))

            self.stubs.Set(self.conn._vmops, '_create_config_drive',
                           fake_create_config_drive)

        self._create_vm()
        info = self.conn.get_info({'name': 1, 'uuid': self.uuid,
                                   'node': self.instance_node})
        self.stubs.Set(self.conn._volumeops, "attach_disk_to_vm",
                       fake_attach_disk_to_vm)
        self.conn.rescue(self.context, self.instance, self.network_info,
                         self.image, 'fake-password')
        info = self.conn.get_info({'name': '1-rescue',
                                   'uuid': '%s-rescue' % self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        info = self.conn.get_info({'name': 1, 'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.SHUTDOWN)

    def test_rescue(self):
        self._rescue()

    def test_rescue_with_config_drive(self):
        self.flags(force_config_drive=True)
        self._rescue(config_drive=True)

    def test_unrescue(self):
        self._rescue()

        def fake_detach_disk_from_vm(*args, **kwargs):
            pass

        self.stubs.Set(self.conn._volumeops, "detach_disk_from_vm",
                       fake_detach_disk_from_vm)

        self.conn.unrescue(self.instance, None)
        info = self.conn.get_info({'name': 1, 'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_pause(self):
        # Tests that the VMwareESXDriver does not implement the pause method.
        self.assertRaises(NotImplementedError, self.conn.pause, instance=None)

    def test_unpause(self):
        # Tests that the VMwareESXDriver does not implement the unpause method.
        self.assertRaises(NotImplementedError, self.conn.unpause,
                          instance=None)

    def test_get_diagnostics(self):
        self._create_vm()
        expected = {'memoryReservation': 0, 'suspendInterval': 0,
                    'maxCpuUsage': 2000, 'toolsInstallerMounted': False,
                    'consumedOverheadMemory': 20, 'numEthernetCards': 1,
                    'numCpu': 1, 'featureRequirement': [{'key': 'cpuid.AES'}],
                    'memoryOverhead': 21417984,
                    'guestMemoryUsage': 0, 'connectionState': 'connected',
                    'memorySizeMB': 512, 'balloonedMemory': 0,
                    'vmPathName': 'fake_path', 'template': False,
                    'overallCpuUsage': 0, 'powerState': 'poweredOn',
                    'cpuReservation': 0, 'overallCpuDemand': 0,
                    'numVirtualDisks': 1, 'hostMemoryUsage': 141}
        expected = dict([('vmware:' + k, v) for k, v in expected.items()])
        self.assertThat(
                self.conn.get_diagnostics({'name': 1, 'uuid': self.uuid,
                                           'node': self.instance_node}),
                matchers.DictMatches(expected))

    def test_get_console_output(self):
        self.assertRaises(NotImplementedError, self.conn.get_console_output,
            None, None)

    def _test_finish_migration(self, power_on, resize_instance=False):
        """
        Tests the finish_migration method on vmops
        """

        self.power_on_called = False

        def fake_power_on(instance):
            self.assertEqual(self.instance, instance)
            self.power_on_called = True

        def fake_vmops_update_instance_progress(context, instance, step,
                                                total_steps):
            self.assertEqual(self.context, context)
            self.assertEqual(self.instance, instance)
            self.assertEqual(4, step)
            self.assertEqual(vmops.RESIZE_TOTAL_STEPS, total_steps)

        self.stubs.Set(self.conn._vmops, "_power_on", fake_power_on)
        self.stubs.Set(self.conn._vmops, "_update_instance_progress",
                       fake_vmops_update_instance_progress)

        # setup the test instance in the database
        self._create_vm()
        # perform the migration on our stubbed methods
        self.conn.finish_migration(context=self.context,
                                   migration=None,
                                   instance=self.instance,
                                   disk_info=None,
                                   network_info=None,
                                   block_device_info=None,
                                   resize_instance=resize_instance,
                                   image_meta=None,
                                   power_on=power_on)

    def test_finish_migration_power_on(self):
        self.assertRaises(NotImplementedError,
                          self._test_finish_migration, power_on=True)

    def test_finish_migration_power_off(self):
        self.assertRaises(NotImplementedError,
                          self._test_finish_migration, power_on=False)

    def test_confirm_migration(self):
        self._create_vm()
        self.assertRaises(NotImplementedError,
                          self.conn.confirm_migration, self.context,
                          self.instance, None)

    def _test_finish_revert_migration(self, power_on):
        """
        Tests the finish_revert_migration method on vmops
        """

        # setup the test instance in the database
        self._create_vm()

        self.power_on_called = False
        self.vm_name = str(self.instance['name']) + '-orig'

        def fake_power_on(instance):
            self.assertEqual(self.instance, instance)
            self.power_on_called = True

        def fake_get_orig_vm_name_label(instance):
            self.assertEqual(self.instance, instance)
            return self.vm_name

        def fake_get_vm_ref_from_name(session, vm_name):
            self.assertEqual(self.vm_name, vm_name)
            return vmwareapi_fake._get_objects("VirtualMachine").objects[0]

        def fake_get_vm_ref_from_uuid(session, vm_uuid):
            return vmwareapi_fake._get_objects("VirtualMachine").objects[0]

        def fake_call_method(*args, **kwargs):
            pass

        def fake_wait_for_task(*args, **kwargs):
            pass

        self.stubs.Set(self.conn._vmops, "_power_on", fake_power_on)
        self.stubs.Set(self.conn._vmops, "_get_orig_vm_name_label",
                       fake_get_orig_vm_name_label)
        self.stubs.Set(vm_util, "get_vm_ref_from_uuid",
                       fake_get_vm_ref_from_uuid)
        self.stubs.Set(vm_util, "get_vm_ref_from_name",
                       fake_get_vm_ref_from_name)
        self.stubs.Set(self.conn._session, "_call_method", fake_call_method)
        self.stubs.Set(self.conn._session, "_wait_for_task",
                       fake_wait_for_task)

        # perform the revert on our stubbed methods
        self.conn.finish_revert_migration(self.context,
                                          instance=self.instance,
                                          network_info=None,
                                          power_on=power_on)

    def test_finish_revert_migration_power_on(self):
        self.assertRaises(NotImplementedError,
                          self._test_finish_migration, power_on=True)

    def test_finish_revert_migration_power_off(self):
        self.assertRaises(NotImplementedError,
                          self._test_finish_migration, power_on=False)

    def test_get_console_pool_info(self):
        info = self.conn.get_console_pool_info("console_type")
        self.assertEqual(info['address'], 'test_url')
        self.assertEqual(info['username'], 'test_username')
        self.assertEqual(info['password'], 'test_pass')

    def test_get_vnc_console_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound,
                          self.conn.get_vnc_console,
                          self.context,
                          self.instance)

    def _test_get_vnc_console(self):
        self._create_vm()
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0]
        fake_vm_id = int(fake_vm.obj.value.replace('vm-', ''))
        vnc_dict = self.conn.get_vnc_console(self.context, self.instance)
        self.assertEqual(vnc_dict['host'], self.vnc_host)
        self.assertEqual(vnc_dict['port'], cfg.CONF.vmware.vnc_port +
                         fake_vm_id % cfg.CONF.vmware.vnc_port_total)

    def test_get_vnc_console(self):
        self._test_get_vnc_console()

    def test_host_ip_addr(self):
        self.assertEqual(self.conn.get_host_ip_addr(), "test_url")

    def test_get_volume_connector(self):
        self._create_vm()
        connector_dict = self.conn.get_volume_connector(self.instance)
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0]
        fake_vm_id = fake_vm.obj.value
        self.assertEqual(connector_dict['ip'], 'test_url')
        self.assertEqual(connector_dict['initiator'], 'iscsi-name')
        self.assertEqual(connector_dict['host'], 'test_url')
        self.assertEqual(connector_dict['instance'], fake_vm_id)

    def _test_vmdk_connection_info(self, type):
        return {'driver_volume_type': type,
                'serial': 'volume-fake-id',
                'data': {'volume': 'vm-10',
                         'volume_id': 'volume-fake-id'}}

    def test_volume_attach_vmdk(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('vmdk')
        mount_point = '/dev/vdc'
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_attach_volume_vmdk')
        volumeops.VMwareVolumeOps._attach_volume_vmdk(connection_info,
                self.instance, mount_point)
        self.mox.ReplayAll()
        self.conn.attach_volume(None, connection_info, self.instance,
                                mount_point)

    def test_volume_detach_vmdk(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('vmdk')
        mount_point = '/dev/vdc'
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_detach_volume_vmdk')
        volumeops.VMwareVolumeOps._detach_volume_vmdk(connection_info,
                self.instance, mount_point)
        self.mox.ReplayAll()
        self.conn.detach_volume(connection_info, self.instance, mount_point,
                                encryption=None)

    def test_attach_vmdk_disk_to_vm(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('vmdk')
        mount_point = '/dev/vdc'
        discover = ('fake_name', 'fake_uuid')

        # create fake backing info
        volume_device = vmwareapi_fake.DataObject()
        volume_device.backing = vmwareapi_fake.DataObject()
        volume_device.backing.fileName = 'fake_path'

        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_get_vmdk_base_volume_device')
        volumeops.VMwareVolumeOps._get_vmdk_base_volume_device(
                mox.IgnoreArg()).AndReturn(volume_device)
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'attach_disk_to_vm')
        volumeops.VMwareVolumeOps.attach_disk_to_vm(mox.IgnoreArg(),
                self.instance, mox.IgnoreArg(), mox.IgnoreArg(),
                vmdk_path='fake_path',
                controller_key=mox.IgnoreArg(),
                unit_number=mox.IgnoreArg())
        self.mox.ReplayAll()
        self.conn.attach_volume(None, connection_info, self.instance,
                                mount_point)

    def test_detach_vmdk_disk_from_vm(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('vmdk')
        mount_point = '/dev/vdc'
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_get_volume_uuid')
        volumeops.VMwareVolumeOps._get_volume_uuid(mox.IgnoreArg(),
                'volume-fake-id').AndReturn('fake_disk_uuid')
        self.mox.StubOutWithMock(vm_util, 'get_vmdk_backed_disk_device')
        vm_util.get_vmdk_backed_disk_device(mox.IgnoreArg(),
                'fake_disk_uuid').AndReturn('fake_device')
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_consolidate_vmdk_volume')
        volumeops.VMwareVolumeOps._consolidate_vmdk_volume(self.instance,
                 mox.IgnoreArg(), 'fake_device', mox.IgnoreArg())
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'detach_disk_from_vm')
        volumeops.VMwareVolumeOps.detach_disk_from_vm(mox.IgnoreArg(),
                self.instance, mox.IgnoreArg())
        self.mox.ReplayAll()
        self.conn.detach_volume(connection_info, self.instance, mount_point,
                                encryption=None)

    def test_volume_attach_iscsi(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('iscsi')
        mount_point = '/dev/vdc'
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_attach_volume_iscsi')
        volumeops.VMwareVolumeOps._attach_volume_iscsi(connection_info,
                self.instance, mount_point)
        self.mox.ReplayAll()
        self.conn.attach_volume(None, connection_info, self.instance,
                                mount_point)

    def test_volume_detach_iscsi(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('iscsi')
        mount_point = '/dev/vdc'
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_detach_volume_iscsi')
        volumeops.VMwareVolumeOps._detach_volume_iscsi(connection_info,
                self.instance, mount_point)
        self.mox.ReplayAll()
        self.conn.detach_volume(connection_info, self.instance, mount_point,
                                encryption=None)

    def test_attach_iscsi_disk_to_vm(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('iscsi')
        connection_info['data']['target_portal'] = 'fake_target_portal'
        connection_info['data']['target_iqn'] = 'fake_target_iqn'
        mount_point = '/dev/vdc'
        discover = ('fake_name', 'fake_uuid')
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'discover_st')
        volumeops.VMwareVolumeOps.discover_st(
                connection_info['data']).AndReturn(discover)
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'attach_disk_to_vm')
        volumeops.VMwareVolumeOps.attach_disk_to_vm(mox.IgnoreArg(),
                self.instance, mox.IgnoreArg(), 'rdmp',
                controller_key=mox.IgnoreArg(),
                unit_number=mox.IgnoreArg(),
                device_name=mox.IgnoreArg())
        self.mox.ReplayAll()
        self.conn.attach_volume(None, connection_info, self.instance,
                                mount_point)

    def test_find_st(self):
        data = {'target_portal': 'fake_target_host:port',
                'target_iqn': 'fake_target_iqn'}
        host = vmwareapi_fake._get_objects('HostSystem').objects[0]
        host._add_iscsi_target(data)
        result = volume_util.find_st(self.conn._session, data)
        self.assertEqual(('fake-device', 'fake-uuid'), result)

    def test_detach_iscsi_disk_from_vm(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('iscsi')
        connection_info['data']['target_portal'] = 'fake_target_portal'
        connection_info['data']['target_iqn'] = 'fake_target_iqn'
        mount_point = '/dev/vdc'
        find = ('fake_name', 'fake_uuid')
        self.mox.StubOutWithMock(volume_util, 'find_st')
        volume_util.find_st(mox.IgnoreArg(), connection_info['data'],
                mox.IgnoreArg()).AndReturn(find)
        self.mox.StubOutWithMock(vm_util, 'get_rdm_disk')
        device = 'fake_device'
        vm_util.get_rdm_disk(mox.IgnoreArg(), 'fake_uuid').AndReturn(device)
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'detach_disk_from_vm')
        volumeops.VMwareVolumeOps.detach_disk_from_vm(mox.IgnoreArg(),
                self.instance, device, destroy_disk=True)
        self.mox.ReplayAll()
        self.conn.detach_volume(connection_info, self.instance, mount_point,
                                encryption=None)

    def test_connection_info_get(self):
        self._create_vm()
        connector = self.conn.get_volume_connector(self.instance)
        self.assertEqual(connector['ip'], 'test_url')
        self.assertEqual(connector['host'], 'test_url')
        self.assertEqual(connector['initiator'], 'iscsi-name')
        self.assertIn('instance', connector)

    def test_connection_info_get_after_destroy(self):
        self._create_vm()
        self.conn.destroy(self.context, self.instance, self.network_info)
        connector = self.conn.get_volume_connector(self.instance)
        self.assertEqual(connector['ip'], 'test_url')
        self.assertEqual(connector['host'], 'test_url')
        self.assertEqual(connector['initiator'], 'iscsi-name')
        self.assertNotIn('instance', connector)


class VMwareAPIHostTestCase(test.NoDBTestCase):
    """Unit tests for Vmware API host calls."""

    def setUp(self):
        super(VMwareAPIHostTestCase, self).setUp()
        self.flags(image_cache_subdirectory_name='vmware_base')
        self.flags(host_ip='test_url',
                   host_username='test_username',
                   host_password='test_pass', group='vmware')
        vmwareapi_fake.reset()
        stubs.set_stubs(self.stubs)
        self.conn = driver.VMwareESXDriver(False)

    def tearDown(self):
        super(VMwareAPIHostTestCase, self).tearDown()
        vmwareapi_fake.cleanup()

    def test_host_state(self):
        stats = self.conn.get_host_stats()
        self.assertEqual(stats['vcpus'], 16)
        self.assertEqual(stats['disk_total'], 1024)
        self.assertEqual(stats['disk_available'], 500)
        self.assertEqual(stats['disk_used'], 1024 - 500)
        self.assertEqual(stats['host_memory_total'], 1024)
        self.assertEqual(stats['host_memory_free'], 1024 - 500)
        self.assertEqual(stats['hypervisor_version'], 5000000)
        supported_instances = [('i686', 'vmware', 'hvm'),
                               ('x86_64', 'vmware', 'hvm')]
        self.assertEqual(stats['supported_instances'], supported_instances)

    def _test_host_action(self, method, action, expected=None):
        result = method('host', action)
        self.assertEqual(result, expected)

    def test_host_reboot(self):
        self._test_host_action(self.conn.host_power_action, 'reboot')

    def test_host_shutdown(self):
        self._test_host_action(self.conn.host_power_action, 'shutdown')

    def test_host_startup(self):
        self._test_host_action(self.conn.host_power_action, 'startup')

    def test_host_maintenance_on(self):
        self._test_host_action(self.conn.host_maintenance_mode, True)

    def test_host_maintenance_off(self):
        self._test_host_action(self.conn.host_maintenance_mode, False)

    def test_get_host_uptime(self):
        result = self.conn.get_host_uptime('host')
        self.assertEqual('Please refer to test_url for the uptime', result)


class VMwareAPIVCDriverTestCase(VMwareAPIVMTestCase):

    def setUp(self):
        super(VMwareAPIVCDriverTestCase, self).setUp()

        cluster_name = 'test_cluster'
        cluster_name2 = 'test_cluster2'
        self.flags(cluster_name=[cluster_name, cluster_name2],
                   task_poll_interval=10, datastore_regex='.*', group='vmware')
        self.flags(vnc_enabled=False,
                   image_cache_subdirectory_name='vmware_base')
        vmwareapi_fake.reset(vc=True)
        self.conn = driver.VMwareVCDriver(None, False)
        self.node_name = self.conn._resources.keys()[0]
        self.node_name2 = self.conn._resources.keys()[1]
        if cluster_name2 in self.node_name2:
            self.ds = 'ds1'
        else:
            self.ds = 'ds2'
        self.vnc_host = 'ha-host'

    def tearDown(self):
        super(VMwareAPIVCDriverTestCase, self).tearDown()
        vmwareapi_fake.cleanup()

    def test_datastore_regex_configured(self):
        for node in self.conn._resources.keys():
            self.assertEqual(self.conn._datastore_regex,
                    self.conn._resources[node]['vmops']._datastore_regex)

    def test_get_available_resource(self):
        stats = self.conn.get_available_resource(self.node_name)
        cpu_info = {"model": ["Intel(R) Xeon(R)", "Intel(R) Xeon(R)"],
                    "vendor": ["Intel", "Intel"],
                    "topology": {"cores": 16,
                                 "threads": 32}}
        self.assertEqual(stats['vcpus'], 32)
        self.assertEqual(stats['local_gb'], 1024)
        self.assertEqual(stats['local_gb_used'], 1024 - 500)
        self.assertEqual(stats['memory_mb'], 1000)
        self.assertEqual(stats['memory_mb_used'], 500)
        self.assertEqual(stats['hypervisor_type'], 'VMware vCenter Server')
        self.assertEqual(stats['hypervisor_version'], 5001000)
        self.assertEqual(stats['hypervisor_hostname'], self.node_name)
        self.assertEqual(stats['cpu_info'], jsonutils.dumps(cpu_info))
        self.assertEqual(stats['supported_instances'],
                '[["i686", "vmware", "hvm"], ["x86_64", "vmware", "hvm"]]')

    def test_invalid_datastore_regex(self):

        # Tests if we raise an exception for Invalid Regular Expression in
        # vmware_datastore_regex
        self.flags(cluster_name=['test_cluster'], datastore_regex='fake-ds(01',
                   group='vmware')
        self.assertRaises(exception.InvalidInput, driver.VMwareVCDriver, None)

    def test_get_available_nodes(self):
        nodelist = self.conn.get_available_nodes()
        self.assertEqual(len(nodelist), 2)
        self.assertIn(self.node_name, nodelist)
        self.assertIn(self.node_name2, nodelist)

    def test_spawn_multiple_node(self):

        def fake_is_neutron():
            return False

        self.stubs.Set(nova_utils, 'is_neutron', fake_is_neutron)
        uuid1 = uuidutils.generate_uuid()
        uuid2 = uuidutils.generate_uuid()
        self._create_vm(node=self.node_name, num_instances=1,
                        uuid=uuid1)
        info = self.conn.get_info({'uuid': uuid1,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.destroy(self.context, self.instance, self.network_info)
        self._create_vm(node=self.node_name2, num_instances=1,
                        uuid=uuid2)
        info = self.conn.get_info({'uuid': uuid2,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_finish_migration_power_on(self):
        self._test_finish_migration(power_on=True)
        self.assertEqual(True, self.power_on_called)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(power_on=False)
        self.assertEqual(False, self.power_on_called)

    def test_finish_migration_power_on_resize(self):
        self._test_finish_migration(power_on=True,
                                    resize_instance=True)
        self.assertEqual(True, self.power_on_called)

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(power_on=True)
        self.assertEqual(True, self.power_on_called)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(power_on=False)
        self.assertEqual(False, self.power_on_called)

    def test_snapshot(self):
        # Ensure VMwareVCVMOps's get_copy_virtual_disk_spec is getting called
        # two times
        self.mox.StubOutWithMock(vmops.VMwareVCVMOps,
                                 'get_copy_virtual_disk_spec')
        self.conn._vmops.get_copy_virtual_disk_spec(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(None)
        self.conn._vmops.get_copy_virtual_disk_spec(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(None)

        self.mox.ReplayAll()

        self._create_vm()
        self._test_snapshot()

    def test_snapshot_using_file_manager(self):
        self._create_vm()
        uuid_str = uuidutils.generate_uuid()
        self.mox.StubOutWithMock(uuidutils,
                                 'generate_uuid')
        uuidutils.generate_uuid().AndReturn(uuid_str)

        self.mox.StubOutWithMock(vmops.VMwareVMOps,
                                 '_delete_datastore_file')
        # Check calls for delete vmdk and -flat.vmdk pair
        self.conn._vmops._delete_datastore_file(
                mox.IgnoreArg(),
                "[%s] vmware_temp/%s-flat.vmdk" % (self.ds, uuid_str),
                mox.IgnoreArg()).AndReturn(None)
        self.conn._vmops._delete_datastore_file(
                mox.IgnoreArg(),
                "[%s] vmware_temp/%s.vmdk" % (self.ds, uuid_str),
                mox.IgnoreArg()).AndReturn(None)

        self.mox.ReplayAll()
        self._test_snapshot()

    def test_spawn_invalid_node(self):
        self._create_instance_in_the_db(node='InvalidNodeName')
        self.assertRaises(exception.NotFound, self.conn.spawn,
                          self.context, self.instance, self.image,
                          injected_files=[], admin_password=None,
                          network_info=self.network_info,
                          block_device_info=None)

    def test_spawn_with_sparse_image(self):
        # Only a sparse disk image triggers the copy
        self.mox.StubOutWithMock(vmware_images, 'get_vmdk_size_and_properties')
        result = [1024, {"vmware_ostype": "otherGuest",
                         "vmware_adaptertype": "lsiLogic",
                         "vmware_disktype": "sparse"}]
        vmware_images.get_vmdk_size_and_properties(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(result)

        # Ensure VMwareVCVMOps's get_copy_virtual_disk_spec is getting called
        # two times
        self.mox.StubOutWithMock(vmops.VMwareVCVMOps,
                                 'get_copy_virtual_disk_spec')
        self.conn._vmops.get_copy_virtual_disk_spec(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(None)
        self.conn._vmops.get_copy_virtual_disk_spec(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(None)

        self.mox.ReplayAll()
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_plug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self._create_instance_in_the_db()
        self.assertRaises(NotImplementedError,
                          self.conn.plug_vifs,
                          instance=self.instance, network_info=None)

    def test_unplug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self._create_instance_in_the_db()
        self.assertRaises(NotImplementedError,
                          self.conn.unplug_vifs,
                          instance=self.instance, network_info=None)

    def test_migrate_disk_and_power_off(self):
        def fake_update_instance_progress(context, instance, step,
                                          total_steps):
            pass

        def fake_get_host_ref_from_name(dest):
            return None

        self._create_vm()
        flavor = {'name': 'fake', 'flavorid': 'fake_id'}
        self.stubs.Set(self.conn._vmops, "_update_instance_progress",
                       fake_update_instance_progress)
        self.stubs.Set(self.conn._vmops, "_get_host_ref_from_name",
                       fake_get_host_ref_from_name)
        self.conn.migrate_disk_and_power_off(self.context, self.instance,
                                             'fake_dest', flavor,
                                             None)

    def test_confirm_migration(self):
        self._create_vm()
        self.conn.confirm_migration(self.context, self.instance, None)

    def test_pause(self):
        # Tests that the VMwareVCDriver does not implement the pause method.
        self._create_instance_in_the_db()
        self.assertRaises(NotImplementedError, self.conn.pause, self.instance)

    def test_unpause(self):
        # Tests that the VMwareVCDriver does not implement the unpause method.
        self._create_instance_in_the_db()
        self.assertRaises(NotImplementedError, self.conn.unpause,
                          self.instance)

    def test_datastore_dc_map(self):
        vmops = self.conn._resources[self.node_name]['vmops']
        self.assertEqual({}, vmops._datastore_dc_mapping)
        self._create_vm()
        # currently there are 2 data stores
        self.assertEqual(2, len(vmops._datastore_dc_mapping))

    def test_rollback_live_migration_at_destination(self):
        with mock.patch.object(self.conn, "destroy") as mock_destroy:
            self.conn.rollback_live_migration_at_destination(self.context,
                    "instance", [], None)
            mock_destroy.assert_called_once_with(self.context,
                    "instance", [], None)
