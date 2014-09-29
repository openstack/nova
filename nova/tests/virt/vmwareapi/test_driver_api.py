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

import collections
import contextlib
import copy
import datetime
import time

import mock
import mox
from oslo.config import cfg
import suds

from nova import block_device
from nova.compute import api as compute_api
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova.openstack.common import units
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import fake_instance
import nova.tests.image.fake
from nova.tests import matchers
from nova.tests import test_flavors
from nova.tests import utils
from nova.tests.virt.vmwareapi import stubs
from nova import utils as nova_utils
from nova.virt import driver as v_driver
from nova.virt import fake
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import imagecache
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
from nova.virt.vmwareapi import vmware_images
from nova.virt.vmwareapi import volume_util
from nova.virt.vmwareapi import volumeops

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('remove_unused_original_minimum_age_seconds',
                'nova.virt.imagecache')


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

    def test_call_method_session_file_exists_exception(self):

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
            self.assertRaises(error_util.FileAlreadyExistsException,
                              api_session._call_method,
                              stubs, 'fake_session_file_exception',
                              *args, **kwargs)

    def test_call_method_session_no_permission_exception(self):

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
            e = self.assertRaises(error_util.NoPermissionException,
                                  api_session._call_method,
                                  stubs, 'fake_session_permission_exception',
                                  *args, **kwargs)
            fault_string = 'Permission to perform this operation was denied.'
            details = {'privilegeId': 'Resource.AssignVMToPool',
                       'object': 'domain-c7'}
            exception_string = '%s %s' % (fault_string, details)
            self.assertEqual(exception_string, str(e))


class VMwareAPIConfTestCase(test.NoDBTestCase):
    """Unit tests for VMWare API configurations."""
    def setUp(self):
        super(VMwareAPIConfTestCase, self).setUp()
        vm_util.vm_refs_cache_reset()

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
        vm_util.vm_refs_cache_reset()
        self.context = context.RequestContext('fake', 'fake', is_admin=False)
        self.flags(host_ip='test_url',
                   host_username='test_username',
                   host_password='test_pass',
                   datastore_regex='.*',
                   api_retry_count=1,
                   use_linked_clone=False, group='vmware')
        self.flags(vnc_enabled=False,
                   image_cache_subdirectory_name='vmware_base',
                   my_ip='')
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.node_name = 'test_url'
        self.ds = 'ds1'
        self.context = context.RequestContext(self.user_id, self.project_id)
        stubs.set_stubs(self.stubs)
        vmwareapi_fake.reset()
        self.conn = driver.VMwareESXDriver(fake.FakeVirtAPI)
        # NOTE(vish): none of the network plugging code is actually
        #             being tested
        self.network_info = utils.get_test_network_info()

        self.image = {
            'id': 'c1c8ce3d-c2e0-4247-890c-ccf5cc1c004c',
            'disk_format': 'vmdk',
            'size': 512,
        }
        nova.tests.image.fake.stub_out_image_service(self.stubs)
        self.vnc_host = 'test_url'
        self._set_exception_vars()
        self.instance_without_compute = {'node': None,
                                         'vm_state': 'building',
                                         'project_id': 'fake',
                                         'user_id': 'fake',
                                         'name': '1',
                                         'display_description': '1',
                                         'kernel_id': '1',
                                         'ramdisk_id': '1',
                                         'mac_addresses': [
                                            {'address': 'de:ad:be:ef:be:ef'}
                                         ],
                                         'memory_mb': 8192,
                                         'instance_type': 'm1.large',
                                         'vcpus': 4,
                                         'root_gb': 80,
                                         'image_ref': '1',
                                         'host': 'fake_host',
                                         'task_state':
                                         'scheduling',
                                         'reservation_id': 'r-3t8muvr0',
                                         'id': 1,
                                         'uuid': 'fake-uuid',
                                         'metadata': []}

    def tearDown(self):
        super(VMwareAPIVMTestCase, self).tearDown()
        vmwareapi_fake.cleanup()
        nova.tests.image.fake.FakeImageService_reset()

    def _set_exception_vars(self):
        self.wait_task = self.conn._session._wait_for_task
        self.call_method = self.conn._session._call_method
        self.task_ref = None
        self.exception = False

    def test_driver_capabilities(self):
        self.assertTrue(self.conn.capabilities['has_imagecache'])
        self.assertFalse(self.conn.capabilities['supports_recreate'])

    def test_login_retries(self):
        self.attempts = 0
        self.login_session = vmwareapi_fake.FakeVim()._login()

        def _fake_login(_self):
            self.attempts += 1
            if self.attempts == 1:
                raise exception.NovaException('Here is my fake exception')
            return self.login_session

        def _fake_check_session(_self):
            return True

        self.stubs.Set(vmwareapi_fake.FakeVim, '_login', _fake_login)
        self.stubs.Set(time, 'sleep', lambda x: None)
        self.stubs.Set(vmwareapi_fake.FakeVim, '_check_session',
                       _fake_check_session)
        self.conn = driver.VMwareAPISession()
        self.assertEqual(self.attempts, 2)

    def test_wait_for_task_exception(self):
        self.flags(task_poll_interval=1, group='vmware')
        self.login_session = vmwareapi_fake.FakeVim()._login()
        self.stop_called = 0

        def _fake_login(_self):
            return self.login_session

        self.stubs.Set(vmwareapi_fake.FakeVim, '_login', _fake_login)

        def fake_poll_task(task_ref, done):
            done.send_exception(exception.NovaException('fake exception'))

        def fake_stop_loop(loop):
            self.stop_called += 1
            return loop.stop()

        self.conn = driver.VMwareAPISession()
        self.stubs.Set(self.conn, "_poll_task",
                       fake_poll_task)
        self.stubs.Set(self.conn, "_stop_loop",
                       fake_stop_loop)
        self.assertRaises(exception.NovaException,
                          self.conn._wait_for_task, 'fake-ref')
        self.assertEqual(self.stop_called, 1)

    def _get_instance_type_by_name(self, type):
        for instance_type in test_flavors.DEFAULT_FLAVORS:
            if instance_type['name'] == type:
                return instance_type
        if type == 'm1.micro':
            return {'memory_mb': 128, 'root_gb': 0, 'deleted_at': None,
                    'name': 'm1.micro', 'deleted': 0, 'created_at': None,
                    'ephemeral_gb': 0, 'updated_at': None,
                    'disabled': False, 'vcpus': 1, 'extra_specs': {},
                    'swap': 0, 'rxtx_factor': 1.0, 'is_public': True,
                    'flavorid': '1', 'vcpu_weight': None, 'id': 2}

    def _create_instance(self, node=None, set_image_ref=True,
                         uuid=None, instance_type='m1.large'):
        if not node:
            node = self.node_name
        if not uuid:
            uuid = uuidutils.generate_uuid()
        self.type_data = self._get_instance_type_by_name(instance_type)
        values = {'name': 'fake_name',
                  'id': 1,
                  'uuid': uuid,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'kernel_id': "fake_kernel_uuid",
                  'ramdisk_id': "fake_ramdisk_uuid",
                  'mac_address': "de:ad:be:ef:be:ef",
                  'flavor': instance_type,
                  'node': node,
                  'memory_mb': self.type_data['memory_mb'],
                  'root_gb': self.type_data['root_gb'],
                  'ephemeral_gb': self.type_data['ephemeral_gb'],
                  'vcpus': self.type_data['vcpus'],
                  'swap': self.type_data['swap'],
        }
        if set_image_ref:
            values['image_ref'] = "fake_image_uuid"
        self.instance_node = node
        self.uuid = uuid
        self.instance = fake_instance.fake_instance_obj(
                self.context, **values)

    def _create_vm(self, node=None, num_instances=1, uuid=None,
                   instance_type='m1.large'):
        """Create and spawn the VM."""
        if not node:
            node = self.node_name
        self._create_instance(node=node, uuid=uuid,
                              instance_type=instance_type)
        self.assertIsNone(vm_util.vm_ref_cache_get(self.uuid))
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=None)
        self._check_vm_record(num_instances=num_instances)
        self.assertIsNotNone(vm_util.vm_ref_cache_get(self.uuid))

    def _check_vm_record(self, num_instances=1):
        """Check if the spawned VM's properties correspond to the instance in
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
        for vm in vms.objects:
            if vm.get('name') == self.uuid:
                break

        # Check that m1.large above turned into the right thing.
        mem_kib = long(self.type_data['memory_mb']) << 10
        vcpus = self.type_data['vcpus']
        self.assertEqual(vm_info['max_mem'], mem_kib)
        self.assertEqual(vm_info['mem'], mem_kib)
        self.assertEqual(vm.get("summary.config.instanceUuid"), self.uuid)
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
        for c in vm.get("config.extraConfig").OptionValue:
            if (c.key == "nvp.vm-uuid" and c.value == self.instance['uuid']):
                found_vm_uuid = True
            if (c.key == "nvp.iface-id.0" and c.value == "vif-xxx-yyy-zzz"):
                found_iface_id = True

        self.assertTrue(found_vm_uuid)
        self.assertTrue(found_iface_id)

    def _check_vm_info(self, info, pwr_state=power_state.RUNNING):
        """Check if the get_info returned values correspond to the instance
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

    def _cached_files_exist(self, exists=True):
        cache = ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.vmdk' %
                 self.ds)
        if exists:
            self.assertTrue(vmwareapi_fake.get_file(cache))
        else:
            self.assertFalse(vmwareapi_fake.get_file(cache))

    def test_instance_dir_disk_created(self):
        """Test image file is cached when even when use_linked_clone
            is False
        """

        self._create_vm()
        inst_file_path = '[%s] %s/%s.vmdk' % (self.ds, self.uuid, self.uuid)
        cache = ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.vmdk' %
                 self.ds)
        self.assertTrue(vmwareapi_fake.get_file(inst_file_path))
        self._cached_files_exist()

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

    def _iso_disk_type_created(self, instance_type='m1.large'):
        self.image['disk_format'] = 'iso'
        self._create_vm(instance_type=instance_type)
        file = ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.iso' %
                self.ds)
        self.assertTrue(vmwareapi_fake.get_file(file))

    def test_iso_disk_type_created(self):
        self._iso_disk_type_created()
        vmdk_file_path = '[%s] %s/%s.vmdk' % (self.ds, self.uuid, self.uuid)
        self.assertTrue(vmwareapi_fake.get_file(vmdk_file_path))

    def test_iso_disk_type_created_with_root_gb_0(self):
        self._iso_disk_type_created(instance_type='m1.micro')
        vmdk_file_path = '[%s] %s/%s.vmdk' % (self.ds, self.uuid, self.uuid)
        self.assertFalse(vmwareapi_fake.get_file(vmdk_file_path))

    def test_iso_disk_cdrom_attach(self):
        self.iso_path = (
            '[%s] vmware_base/fake_image_uuid/fake_image_uuid.iso' % self.ds)

        def fake_attach_cdrom(vm_ref, instance, data_store_ref,
                              iso_uploaded_path):
            self.assertEqual(iso_uploaded_path, self.iso_path)

        self.stubs.Set(self.conn._vmops, "_attach_cdrom_to_vm",
                       fake_attach_cdrom)
        self.image['disk_format'] = 'iso'
        self._create_vm()

    def test_iso_disk_cdrom_attach_with_config_drive(self):
        self.flags(force_config_drive=True)
        self.iso_path = [
            ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.iso' %
             self.ds),
            '[%s] fake-config-drive' % self.ds]
        self.iso_unit_nos = [0, 1]
        self.iso_index = 0

        def fake_create_config_drive(instance, injected_files, password,
                                     data_store_name, folder, uuid, cookies):
            return 'fake-config-drive'

        def fake_attach_cdrom(vm_ref, instance, data_store_ref,
                              iso_uploaded_path):
            self.assertEqual(iso_uploaded_path, self.iso_path[self.iso_index])
            self.iso_index += 1

        self.stubs.Set(self.conn._vmops, "_attach_cdrom_to_vm",
                       fake_attach_cdrom)
        self.stubs.Set(self.conn._vmops, '_create_config_drive',
                       fake_create_config_drive)

        self.image['disk_format'] = 'iso'
        self._create_vm()
        self.assertEqual(self.iso_index, 2)

    def test_cdrom_attach_with_config_drive(self):
        self.flags(force_config_drive=True)
        self.iso_path = '[%s] fake-config-drive' % self.ds
        self.cd_attach_called = False

        def fake_create_config_drive(instance, injected_files, password,
                                     data_store_name, folder, uuid, cookies):
            return 'fake-config-drive'

        def fake_attach_cdrom(vm_ref, instance, data_store_ref,
                              iso_uploaded_path):
            self.assertEqual(iso_uploaded_path, self.iso_path)
            self.cd_attach_called = True

        self.stubs.Set(self.conn._vmops, "_attach_cdrom_to_vm",
                       fake_attach_cdrom)
        self.stubs.Set(self.conn._vmops, '_create_config_drive',
                       fake_create_config_drive)

        self._create_vm()
        self.assertTrue(self.cd_attach_called)

    def test_spawn(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_root_size_0(self):
        self._create_vm(instance_type='m1.micro')
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        cache = ('[%s] vmware_base/%s/%s.vmdk' %
                 (self.ds, 'fake_image_uuid', 'fake_image_uuid'))
        gb_cache = ('[%s] vmware_base/%s/%s.0.vmdk' %
                    (self.ds, 'fake_image_uuid', 'fake_image_uuid'))
        self.assertTrue(vmwareapi_fake.get_file(cache))
        self.assertFalse(vmwareapi_fake.get_file(gb_cache))

    def _spawn_with_delete_exception(self, fault=None):

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "DeleteDatastoreFile_Task":
                self.exception = True
                task_mdo = vmwareapi_fake.create_task(method, "error",
                        error_fault=fault)
                return task_mdo.obj
            return task_ref

        with (
            mock.patch.object(self.conn._session, '_call_method',
                              fake_call_method)
        ):
            if fault:
                self._create_vm()
                info = self.conn.get_info({'uuid': self.uuid,
                                           'node': self.instance_node})
                self._check_vm_info(info, power_state.RUNNING)
            else:
                self.assertRaises(error_util.VMwareDriverException,
                                  self._create_vm)
            self.assertTrue(self.exception)

    def test_spawn_with_delete_exception_not_found(self):
        self._spawn_with_delete_exception(vmwareapi_fake.FileNotFound())

    def test_spawn_with_delete_exception_file_fault(self):
        self._spawn_with_delete_exception(vmwareapi_fake.FileFault())

    def test_spawn_with_delete_exception_cannot_delete_file(self):
        self._spawn_with_delete_exception(vmwareapi_fake.CannotDeleteFile())

    def test_spawn_with_delete_exception_file_locked(self):
        self._spawn_with_delete_exception(vmwareapi_fake.FileLocked())

    def test_spawn_with_delete_exception_general(self):
        self._spawn_with_delete_exception()

    def test_spawn_disk_extend(self):
        self.mox.StubOutWithMock(self.conn._vmops, '_extend_virtual_disk')
        requested_size = 80 * units.Mi
        self.conn._vmops._extend_virtual_disk(mox.IgnoreArg(),
                requested_size, mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_disk_extend_exists(self):
        root = ('[%s] vmware_base/fake_image_uuid/fake_image_uuid.80.vmdk' %
                self.ds)
        self.root = root

        def _fake_extend(instance, requested_size, name, dc_ref):
            vmwareapi_fake._add_file(self.root)

        self.stubs.Set(self.conn._vmops, '_extend_virtual_disk',
                       _fake_extend)

        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        self.assertTrue(vmwareapi_fake.get_file(root))

    def test_spawn_disk_extend_sparse(self):
        self.mox.StubOutWithMock(vmware_images, 'get_vmdk_size_and_properties')
        result = [1024, {"vmware_ostype": "otherGuest",
                         "vmware_adaptertype": "lsiLogic",
                         "vmware_disktype": "sparse"}]
        vmware_images.get_vmdk_size_and_properties(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(result)
        self.mox.StubOutWithMock(self.conn._vmops, '_extend_virtual_disk')
        requested_size = 80 * units.Mi
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

        def fake_wait_for_task(task_ref):
            if task_ref == self.task_ref:
                self.task_ref = None
                self.assertTrue(vmwareapi_fake.get_file(cached_image))
                self.assertTrue(vmwareapi_fake.get_file(tmp_file))
                raise exception.NovaException('No space!')
            return self.wait_task(task_ref)

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

    def test_spawn_disk_extend_failed_copy(self):
        # Spawn instance
        # copy for extend fails without creating a file
        #
        # Expect the copy error to be raised
        self.flags(use_linked_clone=True, group='vmware')
        self.wait_task = self.conn._session._wait_for_task
        self.call_method = self.conn._session._call_method

        CopyError = error_util.FileFaultException

        def fake_wait_for_task(task_ref):
            if task_ref == 'fake-copy-task':
                raise CopyError('Copy failed!')
            return self.wait_task(task_ref)

        def fake_call_method(module, method, *args, **kwargs):
            if method == "CopyVirtualDisk_Task":
                return 'fake-copy-task'

            return self.call_method(module, method, *args, **kwargs)

        with contextlib.nested(
            mock.patch.object(self.conn._session, '_call_method',
                              new=fake_call_method),
            mock.patch.object(self.conn._session, '_wait_for_task',
                              new=fake_wait_for_task)):
            self.assertRaises(CopyError, self._create_vm)

    def test_spawn_disk_extend_failed_partial_copy(self):
        # Spawn instance
        # Copy for extend fails, leaving a file behind
        #
        # Expect the file to be cleaned up
        # Expect the copy error to be raised
        self.flags(use_linked_clone=True, group='vmware')
        self.wait_task = self.conn._session._wait_for_task
        self.call_method = self.conn._session._call_method
        self.task_ref = None
        uuid = 'fake_image_uuid'
        cached_image = '[%s] vmware_base/%s/%s.80.vmdk' % (self.ds,
                                                           uuid, uuid)

        CopyError = error_util.FileFaultException

        def fake_wait_for_task(task_ref):
            if task_ref == self.task_ref:
                self.task_ref = None
                self.assertTrue(vmwareapi_fake.get_file(cached_image))
                # N.B. We don't test for -flat here because real
                # CopyVirtualDisk_Task doesn't actually create it
                raise CopyError('Copy failed!')
            return self.wait_task(task_ref)

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "CopyVirtualDisk_Task":
                self.task_ref = task_ref
            return task_ref

        with contextlib.nested(
            mock.patch.object(self.conn._session, '_call_method',
                              new=fake_call_method),
            mock.patch.object(self.conn._session, '_wait_for_task',
                              new=fake_wait_for_task)):
            self.assertRaises(CopyError, self._create_vm)
        self.assertFalse(vmwareapi_fake.get_file(cached_image))

    def test_spawn_disk_extend_failed_partial_copy_failed_cleanup(self):
        # Spawn instance
        # Copy for extend fails, leaves file behind
        # File cleanup fails
        #
        # Expect file to be left behind
        # Expect file cleanup error to be raised
        self.flags(use_linked_clone=True, group='vmware')
        self.wait_task = self.conn._session._wait_for_task
        self.call_method = self.conn._session._call_method
        self.task_ref = None
        uuid = 'fake_image_uuid'
        cached_image = '[%s] vmware_base/%s/%s.80.vmdk' % (self.ds,
                                                           uuid, uuid)

        CopyError = error_util.FileFaultException
        DeleteError = error_util.CannotDeleteFileException

        def fake_wait_for_task(task_ref):
            if task_ref == self.task_ref:
                self.task_ref = None
                self.assertTrue(vmwareapi_fake.get_file(cached_image))
                # N.B. We don't test for -flat here because real
                # CopyVirtualDisk_Task doesn't actually create it
                raise CopyError('Copy failed!')
            elif task_ref == 'fake-delete-task':
                raise DeleteError('Delete failed!')
            return self.wait_task(task_ref)

        def fake_call_method(module, method, *args, **kwargs):
            if method == "DeleteDatastoreFile_Task":
                return 'fake-delete-task'

            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "CopyVirtualDisk_Task":
                self.task_ref = task_ref
            return task_ref

        with contextlib.nested(
            mock.patch.object(self.conn._session, '_wait_for_task',
                              new=fake_wait_for_task),
            mock.patch.object(self.conn._session, '_call_method',
                              new=fake_call_method)):
            self.assertRaises(DeleteError, self._create_vm)
        self.assertTrue(vmwareapi_fake.get_file(cached_image))

    def test_spawn_disk_invalid_disk_size(self):
        self.mox.StubOutWithMock(vmware_images, 'get_vmdk_size_and_properties')
        result = [82 * units.Gi,
                  {"vmware_ostype": "otherGuest",
                   "vmware_adaptertype": "lsiLogic",
                   "vmware_disktype": "sparse"}]
        vmware_images.get_vmdk_size_and_properties(
                mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(result)
        self.mox.ReplayAll()
        self.assertRaises(exception.InstanceUnacceptable,
                          self._create_vm)

    def test_spawn_invalid_disk_format(self):
        self._create_instance()
        self.image['disk_format'] = 'invalid'
        self.assertRaises(exception.InvalidDiskFormat,
                          self.conn.spawn, self.context,
                          self.instance, self.image,
                          injected_files=[], admin_password=None,
                          network_info=self.network_info,
                          block_device_info=None)

    def test_spawn_with_move_file_exists_exception(self):
        # The test will validate that the spawn completes
        # successfully. The "MoveDatastoreFile_Task" will
        # raise an file exists exception. The flag
        # self.exception will be checked to see that
        # the exception has indeed been raised.

        def fake_wait_for_task(task_ref):
            if task_ref == self.task_ref:
                self.task_ref = None
                self.exception = True
                raise error_util.FileAlreadyExistsException()
            return self.wait_task(task_ref)

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "MoveDatastoreFile_Task":
                self.task_ref = task_ref
            return task_ref

        with contextlib.nested(
            mock.patch.object(self.conn._session, '_wait_for_task',
                              fake_wait_for_task),
            mock.patch.object(self.conn._session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            self._create_vm()
            info = self.conn.get_info({'uuid': self.uuid,
                                       'node': self.instance_node})
            self._check_vm_info(info, power_state.RUNNING)
            self.assertTrue(self.exception)

    def test_spawn_with_move_general_exception(self):
        # The test will validate that the spawn completes
        # successfully. The "MoveDatastoreFile_Task" will
        # raise a general exception. The flag self.exception
        # will be checked to see that the exception has
        # indeed been raised.

        def fake_wait_for_task(task_ref):
            if task_ref == self.task_ref:
                self.task_ref = None
                self.exception = True
                raise error_util.VMwareDriverException('Exception!')
            return self.wait_task(task_ref)

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "MoveDatastoreFile_Task":
                self.task_ref = task_ref
            return task_ref

        with contextlib.nested(
            mock.patch.object(self.conn._session, '_wait_for_task',
                              fake_wait_for_task),
            mock.patch.object(self.conn._session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            self.assertRaises(error_util.VMwareDriverException,
                              self._create_vm)
            self.assertTrue(self.exception)

    def test_spawn_with_move_poll_exception(self):
        self.call_method = self.conn._session._call_method

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "MoveDatastoreFile_Task":
                task_mdo = vmwareapi_fake.create_task(method, "error")
                return task_mdo.obj
            return task_ref

        with (
            mock.patch.object(self.conn._session, '_call_method',
                              fake_call_method)
        ):
            self.assertRaises(error_util.VMwareDriverException,
                              self._create_vm)

    def test_spawn_with_move_file_exists_poll_exception(self):
        # The test will validate that the spawn completes
        # successfully. The "MoveDatastoreFile_Task" will
        # raise a file exists exception. The flag self.exception
        # will be checked to see that the exception has
        # indeed been raised.

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == "MoveDatastoreFile_Task":
                self.exception = True
                task_mdo = vmwareapi_fake.create_task(method, "error",
                        error_fault=vmwareapi_fake.FileAlreadyExists())
                return task_mdo.obj
            return task_ref

        with (
            mock.patch.object(self.conn._session, '_call_method',
                              fake_call_method)
        ):
            self._create_vm()
            info = self.conn.get_info({'uuid': self.uuid,
                                       'node': self.instance_node})
            self._check_vm_info(info, power_state.RUNNING)
            self.assertTrue(self.exception)

    def _spawn_attach_volume_vmdk(self, set_image_ref=True, vc_support=False):
        self._create_instance(set_image_ref=set_image_ref)
        self.mox.StubOutWithMock(block_device, 'volume_in_mapping')
        self.mox.StubOutWithMock(v_driver, 'block_device_info_get_mapping')
        connection_info = self._test_vmdk_connection_info('vmdk')
        root_disk = [{'connection_info': connection_info}]
        v_driver.block_device_info_get_mapping(
                mox.IgnoreArg()).AndReturn(root_disk)
        if vc_support:
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
        self._create_instance()
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

    def test_get_vm_ref_using_extra_config(self):
        self._create_vm()
        vm_ref = vm_util._get_vm_ref_from_extraconfig(self.conn._session,
                                                     self.instance['uuid'])
        self.assertIsNotNone(vm_ref, 'VM Reference cannot be none')
        # Disrupt the fake Virtual Machine object so that extraConfig
        # cannot be matched.
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0]
        fake_vm.get('config.extraConfig["nvp.vm-uuid"]').value = ""
        # We should not get a Virtual Machine through extraConfig.
        vm_ref = vm_util._get_vm_ref_from_extraconfig(self.conn._session,
                                                     self.instance['uuid'])
        self.assertIsNone(vm_ref, 'VM Reference should be none')
        # Check if we can find the Virtual Machine using the name.
        vm_ref = vm_util.get_vm_ref(self.conn._session, self.instance)
        self.assertIsNotNone(vm_ref, 'VM Reference cannot be none')

    def test_search_vm_ref_by_identifier(self):
        self._create_vm()
        vm_ref = vm_util.search_vm_ref_by_identifier(self.conn._session,
                                            self.instance['uuid'])
        self.assertIsNotNone(vm_ref, 'VM Reference cannot be none')
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0]
        fake_vm.set("summary.config.instanceUuid", "foo")
        fake_vm.set("name", "foo")
        fake_vm.get('config.extraConfig["nvp.vm-uuid"]').value = "foo"
        self.assertIsNone(vm_util.search_vm_ref_by_identifier(
                                    self.conn._session, self.instance['uuid']),
                          "VM Reference should be none")
        self.assertIsNotNone(
                vm_util.search_vm_ref_by_identifier(self.conn._session, "foo"),
                "VM Reference should not be none")

    def test_get_object_for_optionvalue(self):
        self._create_vm()
        vms = self.conn._session._call_method(vim_util, "get_objects",
                "VirtualMachine", ['config.extraConfig["nvp.vm-uuid"]'])
        vm_ref = vm_util._get_object_for_optionvalue(vms,
                                                     self.instance["uuid"])
        self.assertIsNotNone(vm_ref, 'VM Reference cannot be none')

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

    def test_snapshot_no_root_disk(self):
        self._iso_disk_type_created(instance_type='m1.micro')
        self.assertRaises(error_util.NoRootDiskDefined, self.conn.snapshot,
                          self.context, self.instance, "Test-Snapshot",
                          lambda *args, **kwargs: None)

    def test_snapshot_non_existent(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, self.conn.snapshot,
                          self.context, self.instance, "Test-Snapshot",
                          lambda *args, **kwargs: None)

    def test_snapshot_delete_vm_snapshot(self):
        self._create_vm()
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0].obj
        snapshot_ref = vmwareapi_fake.ManagedObjectReference(
                               value="Snapshot-123",
                               name="VirtualMachineSnapshot")

        self.mox.StubOutWithMock(vmops.VMwareVMOps,
                                 '_create_vm_snapshot')
        self.conn._vmops._create_vm_snapshot(
                self.instance, fake_vm).AndReturn(snapshot_ref)

        self.mox.StubOutWithMock(vmops.VMwareVMOps,
                                 '_delete_vm_snapshot')
        self.conn._vmops._delete_vm_snapshot(
                self.instance, fake_vm, snapshot_ref).AndReturn(None)
        self.mox.ReplayAll()

        self._test_snapshot()

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
        self._create_instance()
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
        self._create_instance()
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
        self._create_instance()
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
        self._create_instance()
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
        self._create_instance()
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

    def destroy_rescued(self, fake_method):
        self._rescue()
        with (
            mock.patch.object(self.conn._volumeops, "detach_disk_from_vm",
                              fake_method)
        ):
            self.instance['vm_state'] = vm_states.RESCUED
            self.conn.destroy(self.context, self.instance, self.network_info)
            inst_path = '[%s] %s/%s.vmdk' % (self.ds, self.uuid, self.uuid)
            self.assertFalse(vmwareapi_fake.get_file(inst_path))
            rescue_file_path = '[%s] %s-rescue/%s-rescue.vmdk' % (self.ds,
                                                                  self.uuid,
                                                                  self.uuid)
            self.assertFalse(vmwareapi_fake.get_file(rescue_file_path))

    def test_destroy_rescued(self):
        def fake_detach_disk_from_vm(*args, **kwargs):
            pass
        self.destroy_rescued(fake_detach_disk_from_vm)

    def test_destroy_rescued_with_exception(self):
        def fake_detach_disk_from_vm(*args, **kwargs):
            raise exception.NovaException('Here is my fake exception')
        self.destroy_rescued(fake_detach_disk_from_vm)

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
        self.assertIsNone(vm_util.vm_ref_cache_get(self.uuid))

    def test_destroy_no_datastore(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 1)
        # Overwrite the vmPathName
        vms = vmwareapi_fake._get_objects("VirtualMachine")
        vm = vms.objects[0]
        vm.set("config.files.vmPathName", None)
        self.conn.destroy(self.context, self.instance, self.network_info)
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 0)

    def test_destroy_non_existent(self):
        self.destroy_disks = True
        with mock.patch.object(self.conn._vmops,
                               "destroy") as mock_destroy:
            self._create_instance()
            self.conn.destroy(self.context, self.instance,
                              self.network_info,
                              None, self.destroy_disks)
            mock_destroy.assert_called_once_with(self.instance,
                                                 self.network_info,
                                                 self.destroy_disks)

    def test_destroy_instance_without_compute(self):
        self.destroy_disks = True
        with mock.patch.object(self.conn._vmops,
                               "destroy") as mock_destroy:
            self.conn.destroy(self.context, self.instance_without_compute,
                              self.network_info,
                              None, self.destroy_disks)
            self.assertFalse(mock_destroy.called)

    def _rescue(self, config_drive=False):
        def fake_attach_disk_to_vm(vm_ref, instance,
                                   adapter_type, disk_type, vmdk_path=None,
                                   disk_size=None, linked_clone=False,
                                   controller_key=None, unit_number=None,
                                   device_name=None):
            info = self.conn.get_info(instance)
            self._check_vm_info(info, power_state.SHUTDOWN)

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
        self._check_vm_info(info, power_state.RUNNING)
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
        self.assertIsNotNone(vm_util.vm_ref_cache_get('%s-rescue' % self.uuid))

    def test_rescue(self):
        self._rescue()
        inst_file_path = '[%s] %s/%s.vmdk' % (self.ds, self.uuid, self.uuid)
        self.assertTrue(vmwareapi_fake.get_file(inst_file_path))
        rescue_file_path = '[%s] %s-rescue/%s-rescue.vmdk' % (self.ds,
                                                              self.uuid,
                                                              self.uuid)
        self.assertTrue(vmwareapi_fake.get_file(rescue_file_path))

    def test_rescue_with_config_drive(self):
        self.flags(force_config_drive=True)
        self._rescue(config_drive=True)

    def test_unrescue(self):
        self._rescue()
        self.test_vm_ref = None
        self.test_device_name = None

        def fake_power_off_vm_ref(vm_ref):
            self.test_vm_ref = vm_ref
            self.assertIsNotNone(vm_ref)

        def fake_detach_disk_from_vm(vm_ref, instance,
                                     device_name, destroy_disk=False):
            self.test_device_name = device_name
            info = self.conn.get_info(instance)
            self._check_vm_info(info, power_state.SHUTDOWN)

        with contextlib.nested(
            mock.patch.object(self.conn._vmops, "_power_off_vm_ref",
                              side_effect=fake_power_off_vm_ref),
            mock.patch.object(self.conn._volumeops, "detach_disk_from_vm",
                              side_effect=fake_detach_disk_from_vm),
        ) as (poweroff, detach):
            self.conn.unrescue(self.instance, None)
            poweroff.assert_called_once_with(self.test_vm_ref)
            detach.assert_called_once_with(self.test_vm_ref, mock.ANY,
                                           self.test_device_name)
            self.test_vm_ref = None
            self.test_device_name = None
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
        """Tests the finish_migration method on vmops."""

        self.power_on_called = False
        self.wait_for_task = False
        self.wait_task = self.conn._session._wait_for_task

        def fake_power_on(instance):
            self.assertEqual(self.instance, instance)
            self.power_on_called = True

        def fake_vmops_update_instance_progress(context, instance, step,
                                                total_steps):
            self.assertEqual(self.context, context)
            self.assertEqual(self.instance, instance)
            self.assertEqual(4, step)
            self.assertEqual(vmops.RESIZE_TOTAL_STEPS, total_steps)

        if resize_instance:
            def fake_wait_for_task(task_ref):
                self.wait_for_task = True
                return self.wait_task(task_ref)

            self.stubs.Set(self.conn._session, "_wait_for_task",
                           fake_wait_for_task)

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
        if resize_instance:
            self.assertTrue(self.wait_for_task)
        else:
            self.assertFalse(self.wait_for_task)

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
        """Tests the finish_revert_migration method on vmops."""

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
        self.stubs.Set(vm_util, "_get_vm_ref_from_uuid",
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
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound,
                          self.conn.get_vnc_console,
                          self.context,
                          self.instance)

    def _test_get_vnc_console(self):
        self._create_vm()
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0]
        OptionValue = collections.namedtuple('OptionValue', ['key', 'value'])
        opt_val = OptionValue(key='', value=5906)
        fake_vm.set(vm_util.VNC_CONFIG_KEY, opt_val)
        vnc_dict = self.conn.get_vnc_console(self.context, self.instance)
        self.assertEqual(vnc_dict['host'], self.vnc_host)
        self.assertEqual(vnc_dict['port'], 5906)

    def test_get_vnc_console(self):
        self._test_get_vnc_console()

    def test_get_vnc_console_noport(self):
        self._create_vm()
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0]
        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self.conn.get_vnc_console,
                          self.context,
                          self.instance)

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
                vmdk_path='fake_path')
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
        connection_info['data']['target_portal'] = 'fake_target_host:port'
        connection_info['data']['target_iqn'] = 'fake_target_iqn'
        mount_point = '/dev/vdc'
        discover = ('fake_name', 'fake_uuid')
        self.mox.StubOutWithMock(volume_util, 'find_st')
        # simulate target not found
        volume_util.find_st(mox.IgnoreArg(), connection_info['data'],
                            mox.IgnoreArg()).AndReturn((None, None))
        self.mox.StubOutWithMock(volume_util, '_add_iscsi_send_target_host')
        # rescan gets called with target portal
        volume_util.rescan_iscsi_hba(
            self.conn._session,
            target_portal=connection_info['data']['target_portal'])
        # simulate target found
        volume_util.find_st(mox.IgnoreArg(), connection_info['data'],
                            mox.IgnoreArg()).AndReturn(discover)
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'attach_disk_to_vm')
        volumeops.VMwareVolumeOps.attach_disk_to_vm(mox.IgnoreArg(),
                self.instance, mox.IgnoreArg(), 'rdmp',
                device_name=mox.IgnoreArg())
        self.mox.ReplayAll()
        self.conn.attach_volume(None, connection_info, self.instance,
                                mount_point)

    def test_rescan_iscsi_hba(self):
        fake_target_portal = 'fake_target_host:port'
        host_storage_sys = vmwareapi_fake._get_objects(
            "HostStorageSystem").objects[0]
        iscsi_hba_array = host_storage_sys.get('storageDeviceInfo'
                                               '.hostBusAdapter')
        iscsi_hba = iscsi_hba_array.HostHostBusAdapter[0]
        # Check the host system does not have the send target
        self.assertRaises(AttributeError, getattr, iscsi_hba,
                          'configuredSendTarget')
        # Rescan HBA with the target portal
        volume_util.rescan_iscsi_hba(self.conn._session, None,
                                     fake_target_portal)
        # Check if HBA has the target portal configured
        self.assertEqual('fake_target_host',
                          iscsi_hba.configuredSendTarget[0].address)
        # Rescan HBA with same portal
        volume_util.rescan_iscsi_hba(self.conn._session, None,
                                     fake_target_portal)
        self.assertEqual(1, len(iscsi_hba.configuredSendTarget))

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

    def test_refresh_instance_security_rules(self):
        self.assertRaises(NotImplementedError,
                          self.conn.refresh_instance_security_rules,
                          instance=None)

    def test_image_aging_image_used(self):
        self._create_vm()
        all_instances = [self.instance]
        self.conn.manage_image_cache(self.context, all_instances)
        self._cached_files_exist()

    def _get_timestamp_filename(self):
        return '%s%s' % (imagecache.TIMESTAMP_PREFIX,
                         timeutils.strtime(at=self.old_time,
                                           fmt=imagecache.TIMESTAMP_FORMAT))

    def _override_time(self):
        self.old_time = datetime.datetime(2012, 11, 22, 12, 00, 00)

        def _fake_get_timestamp_filename(fake):
            return self._get_timestamp_filename()

        self.stubs.Set(imagecache.ImageCacheManager, '_get_timestamp_filename',
                       _fake_get_timestamp_filename)

    def _timestamp_file_exists(self, exists=True):
        timestamp = ('[%s] vmware_base/fake_image_uuid/%s/' %
                 (self.ds, self._get_timestamp_filename()))
        if exists:
            self.assertTrue(vmwareapi_fake.get_file(timestamp))
        else:
            self.assertFalse(vmwareapi_fake.get_file(timestamp))

    def _image_aging_image_marked_for_deletion(self):
        self._create_vm(uuid=uuidutils.generate_uuid())
        self._cached_files_exist()
        all_instances = []
        self.conn.manage_image_cache(self.context, all_instances)
        self._cached_files_exist()
        self._timestamp_file_exists()

    def test_image_aging_image_marked_for_deletion(self):
        self._override_time()
        self._image_aging_image_marked_for_deletion()

    def _timestamp_file_removed(self):
        self._override_time()
        self._image_aging_image_marked_for_deletion()
        self._create_vm(num_instances=2,
                        uuid=uuidutils.generate_uuid())
        self._timestamp_file_exists(exists=False)

    def test_timestamp_file_removed_spawn(self):
        self._timestamp_file_removed()

    def test_timestamp_file_removed_aging(self):
        self._timestamp_file_removed()
        ts = self._get_timestamp_filename()
        ts_path = ('[%s] vmware_base/fake_image_uuid/%s/' %
                   (self.ds, ts))
        vmwareapi_fake._add_file(ts_path)
        self._timestamp_file_exists()
        all_instances = [self.instance]
        self.conn.manage_image_cache(self.context, all_instances)
        self._timestamp_file_exists(exists=False)

    def test_image_aging_disabled(self):
        self._override_time()
        self.flags(remove_unused_base_images=False)
        self._create_vm()
        self._cached_files_exist()
        all_instances = []
        self.conn.manage_image_cache(self.context, all_instances)
        self._cached_files_exist(exists=True)
        self._timestamp_file_exists(exists=False)

    def _image_aging_aged(self, aging_time=100):
        self._override_time()
        cur_time = datetime.datetime(2012, 11, 22, 12, 00, 10)
        self.flags(remove_unused_original_minimum_age_seconds=aging_time)
        self._image_aging_image_marked_for_deletion()
        all_instances = []
        timeutils.set_time_override(cur_time)
        self.conn.manage_image_cache(self.context, all_instances)

    def test_image_aging_aged(self):
        self._image_aging_aged(aging_time=8)
        self._cached_files_exist(exists=False)

    def test_image_aging_not_aged(self):
        self._image_aging_aged()
        self._cached_files_exist()


class VMwareAPIHostTestCase(test.NoDBTestCase):
    """Unit tests for Vmware API host calls."""

    def setUp(self):
        super(VMwareAPIHostTestCase, self).setUp()
        self.flags(image_cache_subdirectory_name='vmware_base')
        vm_util.vm_refs_cache_reset()
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
                   api_retry_count=1,
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

    def test_list_instances(self):
        instances = self.conn.list_instances()
        self.assertEqual(0, len(instances))

    def test_list_instances_from_nodes(self):
        # Create instance on node1
        self._create_vm(self.node_name)
        # Create instances on the other node
        self._create_vm(self.node_name2, num_instances=2)
        self._create_vm(self.node_name2, num_instances=3)
        node1_vmops = self.conn._get_vmops_for_compute_node(self.node_name)
        node2_vmops = self.conn._get_vmops_for_compute_node(self.node_name2)
        self.assertEqual(1, len(node1_vmops.list_instances()))
        self.assertEqual(2, len(node2_vmops.list_instances()))
        self.assertEqual(3, len(self.conn.list_instances()))

    def _setup_mocks_for_session(self, mock_init):
        mock_init.return_value = None

        vcdriver = driver.VMwareVCDriver(None, False)
        vcdriver._session = mock.Mock()
        return vcdriver

    @mock.patch('nova.virt.vmwareapi.driver.VMwareVCDriver.__init__')
    def test_init_host_and_cleanup_host(self, mock_init):
        vcdriver = self._setup_mocks_for_session(mock_init)
        vcdriver.init_host("foo")
        vcdriver._session._create_session.assert_called_once()

        vcdriver.cleanup_host("foo")
        vcdriver._session.vim.client.service.Logout.assert_called_once()

    @mock.patch('nova.virt.vmwareapi.driver.LOG')
    @mock.patch('nova.virt.vmwareapi.driver.VMwareVCDriver.__init__')
    def test_cleanup_host_with_no_login(self, mock_init, mock_logger):
        vcdriver = self._setup_mocks_for_session(mock_init)
        vcdriver.init_host("foo")
        vcdriver._session._create_session.assert_called_once()

        # Not logged in...
        # observe that no exceptions were thrown
        mock_sc = mock.Mock()
        vcdriver._session.vim.retrieve_service_content.return_value = mock_sc
        web_fault = suds.WebFault(mock.Mock(), mock.Mock())
        vcdriver._session.vim.client.service.Logout.side_effect = web_fault
        vcdriver.cleanup_host("foo")

        # assert that the mock Logout method was never called
        vcdriver._session.vim.client.service.Logout.assert_called_once()
        mock_logger.debug.assert_called_once()

    def test_host_power_action(self):
        self.assertRaises(NotImplementedError,
                          self.conn.host_power_action, 'host', 'action')

    def test_host_maintenance_mode(self):
        self.assertRaises(NotImplementedError,
                          self.conn.host_maintenance_mode, 'host', 'mode')

    def test_set_host_enabled(self):
        self.assertRaises(NotImplementedError,
                          self.conn.set_host_enabled, 'host', 'state')

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

        self.mox.StubOutWithMock(ds_util, 'file_delete')
        # Check calls for delete vmdk and -flat.vmdk pair
        ds_util.file_delete(mox.IgnoreArg(),
                "[%s] vmware_temp/%s-flat.vmdk" % (self.ds, uuid_str),
                mox.IgnoreArg()).AndReturn(None)
        ds_util.file_delete(mox.IgnoreArg(),
                "[%s] vmware_temp/%s.vmdk" % (self.ds, uuid_str),
                mox.IgnoreArg()).AndReturn(None)

        self.mox.ReplayAll()
        self._test_snapshot()

    def test_spawn_invalid_node(self):
        self._create_instance(node='InvalidNodeName')
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
        self._create_instance()
        self.assertRaises(NotImplementedError,
                          self.conn.plug_vifs,
                          instance=self.instance, network_info=None)

    def test_unplug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self._create_instance()
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
        vm_ref_orig = vm_util.get_vm_ref(self.conn._session, self.instance)
        flavor = {'name': 'fake', 'flavorid': 'fake_id'}
        self.stubs.Set(self.conn._vmops, "_update_instance_progress",
                       fake_update_instance_progress)
        self.stubs.Set(self.conn._vmops, "_get_host_ref_from_name",
                       fake_get_host_ref_from_name)
        self.conn.migrate_disk_and_power_off(self.context, self.instance,
                                             'fake_dest', flavor,
                                             None)
        vm_ref = vm_util.get_vm_ref(self.conn._session, self.instance)
        self.assertNotEqual(vm_ref_orig.value, vm_ref.value,
                             "These should be different")

    def test_disassociate_vmref_from_instance(self):
        self._create_vm()
        vm_ref = vm_util.get_vm_ref(self.conn._session, self.instance)
        vm_util.disassociate_vmref_from_instance(self.conn._session,
                                        self.instance, vm_ref, "-backup")
        self.assertRaises(exception.InstanceNotFound,
                    vm_util.get_vm_ref, self.conn._session, self.instance)

    def test_clone_vmref_for_instance(self):
        self._create_vm()
        vm_ref = vm_util.get_vm_ref(self.conn._session, self.instance)
        vm_util.disassociate_vmref_from_instance(self.conn._session,
                                            self.instance, vm_ref, "-backup")
        host_ref = vmwareapi_fake._get_object_refs("HostSystem")[0]
        ds_ref = vmwareapi_fake._get_object_refs("Datastore")[0]
        dc_obj = vmwareapi_fake._get_objects("Datacenter").objects[0]
        vm_util.clone_vmref_for_instance(self.conn._session, self.instance,
                                         vm_ref, host_ref, ds_ref,
                                         dc_obj.get("vmFolder"))
        self.assertIsNotNone(
                        vm_util.get_vm_ref(self.conn._session, self.instance),
                        "No VM found")
        cloned_vm_ref = vm_util.get_vm_ref(self.conn._session, self.instance)
        self.assertNotEqual(vm_ref.value, cloned_vm_ref.value,
                            "Reference for the cloned VM should be different")
        vm_obj = vmwareapi_fake._get_vm_mdo(vm_ref)
        cloned_vm_obj = vmwareapi_fake._get_vm_mdo(cloned_vm_ref)
        self.assertEqual(vm_obj.name, self.instance['uuid'] + "-backup",
                       "Original VM name should be with suffix -backup")
        self.assertEqual(cloned_vm_obj.name, self.instance['uuid'],
                       "VM name does not match instance['uuid']")
        self.assertRaises(error_util.MissingParameter,
                          vm_util.clone_vmref_for_instance, self.conn._session,
                          self.instance, None, host_ref, ds_ref,
                          dc_obj.get("vmFolder"))

    def test_associate_vmref_for_instance(self):
        self._create_vm()
        vm_ref = vm_util.get_vm_ref(self.conn._session, self.instance)
        # First disassociate the VM from the instance so that we have a VM
        # to later associate using the associate_vmref_for_instance method
        vm_util.disassociate_vmref_from_instance(self.conn._session,
                                            self.instance, vm_ref, "-backup")
        # Ensure that the VM is indeed disassociated and that we cannot find
        # the VM using the get_vm_ref method
        self.assertRaises(exception.InstanceNotFound,
                    vm_util.get_vm_ref, self.conn._session, self.instance)
        # Associate the VM back to the instance
        vm_util.associate_vmref_for_instance(self.conn._session, self.instance,
                                             suffix="-backup")
        # Verify if we can get the VM reference
        self.assertIsNotNone(
                        vm_util.get_vm_ref(self.conn._session, self.instance),
                        "No VM found")

    def test_confirm_migration(self):
        self._create_vm()
        self.conn.confirm_migration(self.context, self.instance, None)

    def test_spawn_attach_volume_vmdk(self):
        self._spawn_attach_volume_vmdk(vc_support=True)

    def test_spawn_attach_volume_vmdk_no_image_ref(self):
        self._spawn_attach_volume_vmdk(set_image_ref=False, vc_support=True)

    def test_pause(self):
        # Tests that the VMwareVCDriver does not implement the pause method.
        self._create_instance()
        self.assertRaises(NotImplementedError, self.conn.pause, self.instance)

    def test_unpause(self):
        # Tests that the VMwareVCDriver does not implement the unpause method.
        self._create_instance()
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

    def test_get_instance_disk_info_is_implemented(self):
        # Ensure that the method has been implemented in the driver
        try:
            disk_info = self.conn.get_instance_disk_info('fake_instance_name')
            self.assertIsNone(disk_info)
        except NotImplementedError:
            self.fail("test_get_instance_disk_info() should not raise "
                      "NotImplementedError")

    def test_destroy(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEqual(1, len(instances))
        self.conn.destroy(self.context, self.instance, self.network_info)
        instances = self.conn.list_instances()
        self.assertEqual(0, len(instances))
        self.assertIsNone(vm_util.vm_ref_cache_get(self.uuid))

    def test_destroy_no_datastore(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': self.uuid,
                                   'node': self.instance_node})
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEqual(1, len(instances))
        # Overwrite the vmPathName
        vms = vmwareapi_fake._get_objects("VirtualMachine")
        vm = vms.objects[0]
        vm.set("config.files.vmPathName", None)
        self.conn.destroy(self.context, self.instance, self.network_info)
        instances = self.conn.list_instances()
        self.assertEqual(0, len(instances))

    def test_destroy_non_existent(self):
        self.destroy_disks = True
        with mock.patch.object(self.conn._vmops,
                               "destroy") as mock_destroy:
            self._create_instance()
            self.conn.destroy(self.context, self.instance,
                              self.network_info,
                              None, self.destroy_disks)
            mock_destroy.assert_called_once_with(self.instance,
                                                 self.network_info,
                                                 self.destroy_disks)

    def test_destroy_instance_without_compute(self):
        self.destroy_disks = True
        with mock.patch.object(self.conn._vmops,
                               "destroy") as mock_destroy:
            self.conn.destroy(self.context, self.instance_without_compute,
                              self.network_info,
                              None, self.destroy_disks)
            self.assertFalse(mock_destroy.called)
