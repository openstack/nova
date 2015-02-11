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

from eventlet import greenthread
import mock
from mox3 import mox
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import units
from oslo_vmware import exceptions as vexc
from oslo_vmware import pbm
from oslo_vmware import vim
from oslo_vmware import vim_util as oslo_vim_util
import suds

from nova import block_device
from nova.compute import api as compute_api
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova.network import model as network_model
from nova import objects
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit import fake_instance
import nova.tests.unit.image.fake
from nova.tests.unit import matchers
from nova.tests.unit import test_flavors
from nova.tests.unit import utils
from nova.tests.unit.virt.vmwareapi import fake as vmwareapi_fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova import utils as nova_utils
from nova.virt import driver as v_driver
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import imagecache
from nova.virt.vmwareapi import images
from nova.virt.vmwareapi import vif
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops
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

    def _mock_getattr(self, attr_name):
        self.assertEqual("RetrieveServiceContent", attr_name)
        return lambda obj, **kwargs: fake_service_content()

    def _vim_create(self):
        with mock.patch.object(vim.Vim, '__getattr__', self._mock_getattr):
            return vim.Vim()

    def test_exception_with_deepcopy(self):
        self.assertIsNotNone(self.vim)
        self.assertRaises(vexc.VimException,
                          copy.deepcopy, self.vim)


def _fake_create_session(inst):
    session = vmwareapi_fake.DataObject()
    session.key = 'fake_key'
    session.userName = 'fake_username'
    session._pbm_wsdl_loc = None
    session._pbm = None
    inst._session = session


class VMwareDriverStartupTestCase(test.NoDBTestCase):
    def _start_driver_with_flags(self, expected_exception_type, startup_flags):
        self.flags(**startup_flags)
        with mock.patch(
                'nova.virt.vmwareapi.driver.VMwareAPISession.__init__'):
            e = self.assertRaises(
                    Exception, driver.VMwareVCDriver, None)  # noqa
            self.assertIs(type(e), expected_exception_type)

    def test_start_driver_no_user(self):
        self._start_driver_with_flags(
                Exception,
                dict(host_ip='ip', host_password='password',
                     group='vmware'))

    def test_start_driver_no_host(self):
        self._start_driver_with_flags(
                Exception,
                dict(host_username='username', host_password='password',
                     group='vmware'))

    def test_start_driver_no_password(self):
        self._start_driver_with_flags(
                Exception,
                dict(host_ip='ip', host_username='username',
                     group='vmware'))

    def test_start_driver_with_user_host_password(self):
        # Getting the InvalidInput exception signifies that no exception
        # is raised regarding missing user/password/host
        self._start_driver_with_flags(
                nova.exception.InvalidInput,
                dict(host_ip='ip', host_password='password',
                     host_username="user", datastore_regex="bad(regex",
                     group='vmware'))


class VMwareSessionTestCase(test.NoDBTestCase):

    @mock.patch.object(driver.VMwareAPISession, '_is_vim_object',
                       return_value=False)
    def test_call_method(self, mock_is_vim):
        with contextlib.nested(
                mock.patch.object(driver.VMwareAPISession, '_create_session',
                                  _fake_create_session),
                mock.patch.object(driver.VMwareAPISession, 'invoke_api'),
        ) as (fake_create, fake_invoke):
            session = driver.VMwareAPISession()
            session._vim = mock.Mock()
            module = mock.Mock()
            session._call_method(module, 'fira')
            fake_invoke.assert_called_once_with(module, 'fira', session._vim)

    @mock.patch.object(driver.VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_vim(self, mock_is_vim):
        with contextlib.nested(
                mock.patch.object(driver.VMwareAPISession, '_create_session',
                                  _fake_create_session),
                mock.patch.object(driver.VMwareAPISession, 'invoke_api'),
        ) as (fake_create, fake_invoke):
            session = driver.VMwareAPISession()
            module = mock.Mock()
            session._call_method(module, 'fira')
            fake_invoke.assert_called_once_with(module, 'fira')


class VMwareAPIVMTestCase(test.NoDBTestCase):
    """Unit tests for Vmware API connection calls."""

    REQUIRES_LOCKING = True

    @mock.patch.object(driver.VMwareVCDriver, '_register_openstack_extension')
    def setUp(self, mock_register):
        super(VMwareAPIVMTestCase, self).setUp()
        vm_util.vm_refs_cache_reset()
        self.context = context.RequestContext('fake', 'fake', is_admin=False)
        cluster_name = 'test_cluster'
        cluster_name2 = 'test_cluster2'
        self.flags(cluster_name=[cluster_name, cluster_name2],
                   host_ip='test_url',
                   host_username='test_username',
                   host_password='test_pass',
                   api_retry_count=1,
                   use_linked_clone=False, group='vmware')
        self.flags(vnc_enabled=False,
                   image_cache_subdirectory_name='vmware_base',
                   my_ip='')
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        stubs.set_stubs(self.stubs)
        vmwareapi_fake.reset()
        nova.tests.unit.image.fake.stub_out_image_service(self.stubs)
        self.conn = driver.VMwareVCDriver(None, False)
        self._set_exception_vars()
        self.node_name = self.conn._resources.keys()[0]
        self.node_name2 = self.conn._resources.keys()[1]
        if cluster_name2 in self.node_name2:
            self.ds = 'ds1'
        else:
            self.ds = 'ds2'

        self.vim = vmwareapi_fake.FakeVim()

        # NOTE(vish): none of the network plugging code is actually
        #             being tested
        self.network_info = utils.get_test_network_info()
        image_ref = nova.tests.unit.image.fake.get_valid_image_id()
        (image_service, image_id) = glance.get_remote_image_service(
            self.context, image_ref)
        metadata = image_service.show(self.context, image_id)
        self.image = {
            'id': image_ref,
            'disk_format': 'vmdk',
            'size': int(metadata['size']),
        }
        self.fake_image_uuid = self.image['id']
        nova.tests.unit.image.fake.stub_out_image_service(self.stubs)
        self.vnc_host = 'ha-host'
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
                                         'image_ref': self.image['id'],
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
        nova.tests.unit.image.fake.FakeImageService_reset()

    def test_legacy_block_device_info(self):
        self.assertFalse(self.conn.need_legacy_block_device_info)

    def test_get_host_ip_addr(self):
        self.assertEqual('test_url', self.conn.get_host_ip_addr())

    def test_init_host_with_no_session(self):
        self.conn._session = mock.Mock()
        self.conn._session.vim = None
        self.conn.init_host('fake_host')
        self.conn._session._create_session.assert_called_once_with()

    def test_init_host(self):
        try:
            self.conn.init_host("fake_host")
        except Exception as ex:
            self.fail("init_host raised: %s" % ex)

    def _set_exception_vars(self):
        self.wait_task = self.conn._session._wait_for_task
        self.call_method = self.conn._session._call_method
        self.task_ref = None
        self.exception = False

    def test_cleanup_host(self):
        self.conn.init_host("fake_host")
        try:
            self.conn.cleanup_host("fake_host")
        except Exception as ex:
            self.fail("cleanup_host raised: %s" % ex)

    def test_driver_capabilities(self):
        self.assertTrue(self.conn.capabilities['has_imagecache'])
        self.assertFalse(self.conn.capabilities['supports_recreate'])

    def test_configuration_linked_clone(self):
        self.flags(use_linked_clone=None, group='vmware')
        self.assertRaises(vexc.UseLinkedCloneConfigurationFault,
                          self.conn._validate_configuration)

    @mock.patch.object(pbm, 'get_profile_id_by_name')
    def test_configuration_pbm(self, get_profile_mock):
        get_profile_mock.return_value = 'fake-profile'
        self.flags(pbm_enabled=True,
                   pbm_default_policy='fake-policy',
                   pbm_wsdl_location='fake-location', group='vmware')
        self.conn._validate_configuration()

    @mock.patch.object(pbm, 'get_profile_id_by_name')
    def test_configuration_pbm_bad_default(self, get_profile_mock):
        get_profile_mock.return_value = None
        self.flags(pbm_enabled=True,
                   pbm_wsdl_location='fake-location',
                   pbm_default_policy='fake-policy', group='vmware')
        self.assertRaises(error_util.PbmDefaultPolicyDoesNotExist,
                          self.conn._validate_configuration)

    def test_login_retries(self):
        self.attempts = 0
        self.login_session = vmwareapi_fake.FakeVim()._login()

        def _fake_login(_self):
            self.attempts += 1
            if self.attempts == 1:
                raise vexc.VimConnectionException('Here is my fake exception')
            return self.login_session

        def _fake_check_session(_self):
            return True

        self.stubs.Set(vmwareapi_fake.FakeVim, '_login', _fake_login)
        self.stubs.Set(vmwareapi_fake.FakeVim, '_check_session',
                       _fake_check_session)

        with mock.patch.object(greenthread, 'sleep'):
            self.conn = driver.VMwareAPISession()
        self.assertEqual(self.attempts, 2)

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
                         uuid=None, instance_type='m1.large',
                         ephemeral=None):
        if not node:
            node = self.node_name
        if not uuid:
            uuid = uuidutils.generate_uuid()
        self.type_data = self._get_instance_type_by_name(instance_type)
        if ephemeral is not None:
            self.type_data['ephemeral_gb'] = ephemeral
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
                  'expected_attrs': ['system_metadata'],
        }
        if set_image_ref:
            values['image_ref'] = self.fake_image_uuid
        self.instance_node = node
        self.uuid = uuid
        self.instance = fake_instance.fake_instance_obj(
                self.context, **values)

    def _create_vm(self, node=None, num_instances=1, uuid=None,
                   instance_type='m1.large', powered_on=True,
                   ephemeral=None, bdi=None):
        """Create and spawn the VM."""
        if not node:
            node = self.node_name
        self._create_instance(node=node, uuid=uuid,
                              instance_type=instance_type,
                              ephemeral=ephemeral)
        self.assertIsNone(vm_util.vm_ref_cache_get(self.uuid))
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=bdi)
        self._check_vm_record(num_instances=num_instances,
                              powered_on=powered_on,
                              uuid=uuid)
        self.assertIsNotNone(vm_util.vm_ref_cache_get(self.uuid))

    def _get_vm_record(self):
        # Get record for VM
        vms = vmwareapi_fake._get_objects("VirtualMachine")
        for vm in vms.objects:
            if vm.get('name') == self.uuid:
                return vm
        self.fail('Unable to find VM backing!')

    def _get_info(self, uuid=None, node=None, name=None):
        uuid = uuid if uuid else self.uuid
        node = node if node else self.instance_node
        name = name if node else '1'
        return self.conn.get_info({'uuid': uuid,
                                   'name': name,
                                   'node': node})

    def _check_vm_record(self, num_instances=1, powered_on=True, uuid=None):
        """Check if the spawned VM's properties correspond to the instance in
        the db.
        """
        instances = self.conn.list_instances()
        if uuidutils.is_uuid_like(uuid):
            self.assertEqual(len(instances), num_instances)

        # Get Nova record for VM
        vm_info = self._get_info()
        vm = self._get_vm_record()

        # Check that m1.large above turned into the right thing.
        mem_kib = long(self.type_data['memory_mb']) << 10
        vcpus = self.type_data['vcpus']
        self.assertEqual(vm_info.max_mem_kb, mem_kib)
        self.assertEqual(vm_info.mem_kb, mem_kib)
        self.assertEqual(vm.get("summary.config.instanceUuid"), self.uuid)
        self.assertEqual(vm.get("summary.config.numCpu"), vcpus)
        self.assertEqual(vm.get("summary.config.memorySizeMB"),
                         self.type_data['memory_mb'])

        self.assertEqual(
            vm.get("config.hardware.device").VirtualDevice[2].obj_name,
            "ns0:VirtualE1000")
        if powered_on:
            # Check that the VM is running according to Nova
            self.assertEqual(power_state.RUNNING, vm_info.state)

            # Check that the VM is running according to vSphere API.
            self.assertEqual('poweredOn', vm.get("runtime.powerState"))
        else:
            # Check that the VM is not running according to Nova
            self.assertEqual(power_state.SHUTDOWN, vm_info.state)

            # Check that the VM is not running according to vSphere API.
            self.assertEqual('poweredOff', vm.get("runtime.powerState"))

        found_vm_uuid = False
        found_iface_id = False
        extras = vm.get("config.extraConfig")
        for c in extras.OptionValue:
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
        self.assertEqual(info.state, pwr_state)
        self.assertEqual(info.max_mem_kb, mem_kib)
        self.assertEqual(info.mem_kb, mem_kib)
        self.assertEqual(info.num_cpu, self.type_data['vcpus'])

    def test_instance_exists(self):
        self._create_vm()
        self.assertTrue(self.conn.instance_exists(self.instance))
        invalid_instance = dict(uuid='foo', name='bar', node=self.node_name)
        self.assertFalse(self.conn.instance_exists(invalid_instance))

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
        cache = ds_util.DatastorePath(self.ds, 'vmware_base',
                                      self.fake_image_uuid,
                                      '%s.vmdk' % self.fake_image_uuid)
        if exists:
            self.assertTrue(vmwareapi_fake.get_file(str(cache)))
        else:
            self.assertFalse(vmwareapi_fake.get_file(str(cache)))

    @mock.patch.object(nova.virt.vmwareapi.images.VMwareImage,
                       'from_image')
    def test_instance_dir_disk_created(self, mock_from_image):
        """Test image file is cached when even when use_linked_clone
            is False
        """
        img_props = images.VMwareImage(
            image_id=self.fake_image_uuid,
            linked_clone=False)

        mock_from_image.return_value = img_props
        self._create_vm()
        path = ds_util.DatastorePath(self.ds, self.uuid, '%s.vmdk' % self.uuid)
        self.assertTrue(vmwareapi_fake.get_file(str(path)))
        self._cached_files_exist()

    @mock.patch.object(nova.virt.vmwareapi.images.VMwareImage,
                       'from_image')
    def test_cache_dir_disk_created(self, mock_from_image):
        """Test image disk is cached when use_linked_clone is True."""
        self.flags(use_linked_clone=True, group='vmware')

        img_props = images.VMwareImage(
            image_id=self.fake_image_uuid,
            file_size=1 * units.Ki,
            disk_type=constants.DISK_TYPE_SPARSE)

        mock_from_image.return_value = img_props

        self._create_vm()
        path = ds_util.DatastorePath(self.ds, 'vmware_base',
                                     self.fake_image_uuid,
                                     '%s.vmdk' % self.fake_image_uuid)
        root = ds_util.DatastorePath(self.ds, 'vmware_base',
                                     self.fake_image_uuid,
                                     '%s.80.vmdk' % self.fake_image_uuid)
        self.assertTrue(vmwareapi_fake.get_file(str(path)))
        self.assertTrue(vmwareapi_fake.get_file(str(root)))

    def _iso_disk_type_created(self, instance_type='m1.large'):
        self.image['disk_format'] = 'iso'
        self._create_vm(instance_type=instance_type)
        path = ds_util.DatastorePath(self.ds, 'vmware_base',
                                     self.fake_image_uuid,
                                     '%s.iso' % self.fake_image_uuid)
        self.assertTrue(vmwareapi_fake.get_file(str(path)))

    def test_iso_disk_type_created(self):
        self._iso_disk_type_created()
        path = ds_util.DatastorePath(self.ds, self.uuid, '%s.vmdk' % self.uuid)
        self.assertTrue(vmwareapi_fake.get_file(str(path)))

    def test_iso_disk_type_created_with_root_gb_0(self):
        self._iso_disk_type_created(instance_type='m1.micro')
        path = ds_util.DatastorePath(self.ds, self.uuid, '%s.vmdk' % self.uuid)
        self.assertFalse(vmwareapi_fake.get_file(str(path)))

    def test_iso_disk_cdrom_attach(self):
        iso_path = ds_util.DatastorePath(self.ds, 'vmware_base',
                                         self.fake_image_uuid,
                                         '%s.iso' % self.fake_image_uuid)

        def fake_attach_cdrom(vm_ref, instance, data_store_ref,
                              iso_uploaded_path):
            self.assertEqual(iso_uploaded_path, str(iso_path))

        self.stubs.Set(self.conn._vmops, "_attach_cdrom_to_vm",
                       fake_attach_cdrom)
        self.image['disk_format'] = 'iso'
        self._create_vm()

    @mock.patch.object(nova.virt.vmwareapi.images.VMwareImage,
                       'from_image')
    def test_iso_disk_cdrom_attach_with_config_drive(self,
                                                     mock_from_image):
        img_props = images.VMwareImage(
            image_id=self.fake_image_uuid,
            file_size=80 * units.Gi,
            file_type='iso',
            linked_clone=False)

        mock_from_image.return_value = img_props

        self.flags(force_config_drive=True)
        iso_path = [
            ds_util.DatastorePath(self.ds, 'vmware_base',
                                  self.fake_image_uuid,
                                  '%s.iso' % self.fake_image_uuid),
            ds_util.DatastorePath(self.ds, 'fake-config-drive')]
        self.iso_index = 0

        def fake_create_config_drive(instance, injected_files, password,
                                     data_store_name, folder, uuid, cookies):
            return 'fake-config-drive'

        def fake_attach_cdrom(vm_ref, instance, data_store_ref,
                              iso_uploaded_path):
            self.assertEqual(iso_uploaded_path, str(iso_path[self.iso_index]))
            self.iso_index += 1

        self.stubs.Set(self.conn._vmops, "_attach_cdrom_to_vm",
                       fake_attach_cdrom)
        self.stubs.Set(self.conn._vmops, '_create_config_drive',
                       fake_create_config_drive)

        self.image['disk_format'] = 'iso'
        self._create_vm()
        self.assertEqual(self.iso_index, 2)

    def test_ephemeral_disk_attach(self):
        self._create_vm(ephemeral=50)
        path = ds_util.DatastorePath(self.ds, self.uuid,
                                     'ephemeral_0.vmdk')
        self.assertTrue(vmwareapi_fake.get_file(str(path)))

    def test_ephemeral_disk_attach_from_bdi(self):
        ephemerals = [{'device_type': 'disk',
                       'disk_bus': 'lsiLogic',
                       'size': 25},
                      {'device_type': 'disk',
                       'disk_bus': 'lsiLogic',
                       'size': 25}]
        bdi = {'ephemerals': ephemerals}
        self._create_vm(bdi=bdi, ephemeral=50)
        path = ds_util.DatastorePath(self.ds, self.uuid,
                                     'ephemeral_0.vmdk')
        self.assertTrue(vmwareapi_fake.get_file(str(path)))
        path = ds_util.DatastorePath(self.ds, self.uuid,
                                     'ephemeral_1.vmdk')
        self.assertTrue(vmwareapi_fake.get_file(str(path)))

    def test_ephemeral_disk_attach_from_bdii_with_no_ephs(self):
        bdi = {'ephemerals': []}
        self._create_vm(bdi=bdi, ephemeral=50)
        path = ds_util.DatastorePath(self.ds, self.uuid,
                                     'ephemeral_0.vmdk')
        self.assertTrue(vmwareapi_fake.get_file(str(path)))

    def test_cdrom_attach_with_config_drive(self):
        self.flags(force_config_drive=True)

        iso_path = ds_util.DatastorePath(self.ds, 'fake-config-drive')
        self.cd_attach_called = False

        def fake_create_config_drive(instance, injected_files, password,
                                     data_store_name, folder, uuid, cookies):
            return 'fake-config-drive'

        def fake_attach_cdrom(vm_ref, instance, data_store_ref,
                              iso_uploaded_path):
            self.assertEqual(iso_uploaded_path, str(iso_path))
            self.cd_attach_called = True

        self.stubs.Set(self.conn._vmops, "_attach_cdrom_to_vm",
                       fake_attach_cdrom)
        self.stubs.Set(self.conn._vmops, '_create_config_drive',
                       fake_create_config_drive)

        self._create_vm()
        self.assertTrue(self.cd_attach_called)

    def test_spawn(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_vm_ref_cached(self):
        uuid = uuidutils.generate_uuid()
        self.assertIsNone(vm_util.vm_ref_cache_get(uuid))
        self._create_vm(uuid=uuid)
        self.assertIsNotNone(vm_util.vm_ref_cache_get(uuid))

    def _spawn_power_state(self, power_on):
        self._spawn = self.conn._vmops.spawn
        self._power_on = power_on

        def _fake_spawn(context, instance, image_meta, injected_files,
            admin_password, network_info, block_device_info=None,
            instance_name=None, power_on=True, flavor=None):
            return self._spawn(context, instance, image_meta,
                               injected_files, admin_password, network_info,
                               block_device_info=block_device_info,
                               instance_name=instance_name,
                               power_on=self._power_on,
                               flavor=flavor)

        with (
            mock.patch.object(self.conn._vmops, 'spawn', _fake_spawn)
        ):
            self._create_vm(powered_on=power_on)
            info = self._get_info()
            if power_on:
                self._check_vm_info(info, power_state.RUNNING)
            else:
                self._check_vm_info(info, power_state.SHUTDOWN)

    def test_spawn_no_power_on(self):
        self._spawn_power_state(False)

    def test_spawn_power_on(self):
        self._spawn_power_state(True)

    def test_spawn_root_size_0(self):
        self._create_vm(instance_type='m1.micro')
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        cache = ('[%s] vmware_base/%s/%s.vmdk' %
                 (self.ds, self.fake_image_uuid, self.fake_image_uuid))
        gb_cache = ('[%s] vmware_base/%s/%s.0.vmdk' %
                    (self.ds, self.fake_image_uuid, self.fake_image_uuid))
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
                info = self._get_info()
                self._check_vm_info(info, power_state.RUNNING)
            else:
                self.assertRaises(vexc.VMwareDriverException, self._create_vm)
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
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_disk_extend_exists(self):
        root = ds_util.DatastorePath(self.ds, 'vmware_base',
                                     self.fake_image_uuid,
                                     '%s.80.vmdk' % self.fake_image_uuid)

        def _fake_extend(instance, requested_size, name, dc_ref):
            vmwareapi_fake._add_file(str(root))

        self.stubs.Set(self.conn._vmops, '_extend_virtual_disk',
                       _fake_extend)

        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.assertTrue(vmwareapi_fake.get_file(str(root)))

    @mock.patch.object(nova.virt.vmwareapi.images.VMwareImage,
                       'from_image')
    def test_spawn_disk_extend_sparse(self, mock_from_image):
        img_props = images.VMwareImage(
            image_id=self.fake_image_uuid,
            file_size=units.Ki,
            disk_type=constants.DISK_TYPE_SPARSE,
            linked_clone=True)

        mock_from_image.return_value = img_props

        with contextlib.nested(
            mock.patch.object(self.conn._vmops, '_extend_virtual_disk'),
            mock.patch.object(self.conn._vmops, 'get_datacenter_ref_and_name'),
        ) as (mock_extend, mock_get_dc):
            dc_val = mock.Mock()
            dc_val.ref = "fake_dc_ref"
            dc_val.name = "dc1"
            mock_get_dc.return_value = dc_val
            self._create_vm()
            iid = img_props.image_id
            cached_image = ds_util.DatastorePath(self.ds, 'vmware_base',
                                                 iid, '%s.80.vmdk' % iid)
            mock_extend.assert_called_once_with(
                    self.instance, self.instance.root_gb * units.Mi,
                    str(cached_image), "fake_dc_ref")

    def test_spawn_disk_extend_failed_copy(self):
        # Spawn instance
        # copy for extend fails without creating a file
        #
        # Expect the copy error to be raised
        self.flags(use_linked_clone=True, group='vmware')

        CopyError = vexc.FileFaultException

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
        self.task_ref = None
        uuid = self.fake_image_uuid
        cached_image = '[%s] vmware_base/%s/%s.80.vmdk' % (self.ds,
                                                           uuid, uuid)

        CopyError = vexc.FileFaultException

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
        self.task_ref = None
        uuid = self.fake_image_uuid
        cached_image = '[%s] vmware_base/%s/%s.80.vmdk' % (self.ds,
                                                           uuid, uuid)

        CopyError = vexc.FileFaultException
        DeleteError = vexc.CannotDeleteFileException

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

    @mock.patch.object(nova.virt.vmwareapi.images.VMwareImage,
                       'from_image')
    def test_spawn_disk_invalid_disk_size(self, mock_from_image):
        img_props = images.VMwareImage(
            image_id=self.fake_image_uuid,
            file_size=82 * units.Gi,
            disk_type=constants.DISK_TYPE_SPARSE,
            linked_clone=True)

        mock_from_image.return_value = img_props

        self.assertRaises(exception.InstanceUnacceptable,
                          self._create_vm)

    @mock.patch.object(nova.virt.vmwareapi.images.VMwareImage,
                       'from_image')
    def test_spawn_disk_extend_insufficient_disk_space(self, mock_from_image):
        img_props = images.VMwareImage(
            image_id=self.fake_image_uuid,
            file_size=1024,
            disk_type=constants.DISK_TYPE_SPARSE,
            linked_clone=True)

        mock_from_image.return_value = img_props

        cached_image = ds_util.DatastorePath(self.ds, 'vmware_base',
                                             self.fake_image_uuid,
                                             '%s.80.vmdk' %
                                              self.fake_image_uuid)
        tmp_file = ds_util.DatastorePath(self.ds, 'vmware_base',
                                         self.fake_image_uuid,
                                         '%s.80-flat.vmdk' %
                                          self.fake_image_uuid)

        NoDiskSpace = vexc.get_fault_class('NoDiskSpace')

        def fake_wait_for_task(task_ref):
            if task_ref == self.task_ref:
                self.task_ref = None
                raise NoDiskSpace()
            return self.wait_task(task_ref)

        def fake_call_method(module, method, *args, **kwargs):
            task_ref = self.call_method(module, method, *args, **kwargs)
            if method == 'ExtendVirtualDisk_Task':
                self.task_ref = task_ref
            return task_ref

        with contextlib.nested(
            mock.patch.object(self.conn._session, '_wait_for_task',
                              fake_wait_for_task),
            mock.patch.object(self.conn._session, '_call_method',
                              fake_call_method)
        ) as (mock_wait_for_task, mock_call_method):
            self.assertRaises(NoDiskSpace, self._create_vm)
            self.assertFalse(vmwareapi_fake.get_file(str(cached_image)))
            self.assertFalse(vmwareapi_fake.get_file(str(tmp_file)))

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
                raise vexc.FileAlreadyExistsException()
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
            info = self._get_info()
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
                raise vexc.VMwareDriverException('Exception!')
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
            self.assertRaises(vexc.VMwareDriverException,
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
            self.assertRaises(vexc.VMwareDriverException,
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
            info = self._get_info()
            self._check_vm_info(info, power_state.RUNNING)
            self.assertTrue(self.exception)

    def _spawn_attach_volume_vmdk(self, set_image_ref=True):
        self._create_instance(set_image_ref=set_image_ref)
        self.mox.StubOutWithMock(block_device, 'volume_in_mapping')
        self.mox.StubOutWithMock(v_driver, 'block_device_info_get_mapping')
        connection_info = self._test_vmdk_connection_info('vmdk')
        root_disk = [{'connection_info': connection_info}]
        v_driver.block_device_info_get_mapping(
                mox.IgnoreArg()).AndReturn(root_disk)
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
                self.instance)
        self.mox.ReplayAll()
        block_device_info = {'mount_device': 'vda'}
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=block_device_info)

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
                self.instance)
        self.mox.ReplayAll()
        block_device_info = {'mount_device': 'vda'}
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=block_device_info)

    def test_spawn_hw_versions(self):
        def _fake_flavor_get(context, id):
            flavor = stubs._fake_flavor_get(context, id)
            flavor['extra_specs'] = {'vmware:hw_version': 'vmx-08'}
            return flavor

        with mock.patch.object(db, 'flavor_get', _fake_flavor_get):
            self._create_vm()
        vm = self._get_vm_record()
        version = vm.get("version")
        self.assertEqual('vmx-08', version)

    def mock_upload_image(self, context, image, instance, session, **kwargs):
        self.assertEqual(image, 'Test-Snapshot')
        self.assertEqual(instance, self.instance)
        self.assertEqual(1024, kwargs['vmdk_size'])

    def test_get_vm_ref_using_extra_config(self):
        self._create_vm()
        vm_ref = vm_util._get_vm_ref_from_extraconfig(self.conn._session,
                                                     self.instance['uuid'])
        self.assertIsNotNone(vm_ref, 'VM Reference cannot be none')
        # Disrupt the fake Virtual Machine object so that extraConfig
        # cannot be matched.
        fake_vm = self._get_vm_record()
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
        fake_vm = self._get_vm_record()
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
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        with mock.patch.object(images, 'upload_image_stream_optimized',
                               self.mock_upload_image):
            self.conn.snapshot(self.context, self.instance, "Test-Snapshot",
                               func_call_matcher.call)
        info = self._get_info()
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
        fake_vm = self._get_vm_record()
        snapshot_ref = vmwareapi_fake.ManagedObjectReference(
                               value="Snapshot-123",
                               name="VirtualMachineSnapshot")

        self.mox.StubOutWithMock(vmops.VMwareVMOps,
                                 '_create_vm_snapshot')
        self.conn._vmops._create_vm_snapshot(
                self.instance, fake_vm.obj).AndReturn(snapshot_ref)

        self.mox.StubOutWithMock(vmops.VMwareVMOps,
                                 '_delete_vm_snapshot')
        self.conn._vmops._delete_vm_snapshot(
                self.instance, fake_vm.obj, snapshot_ref).AndReturn(None)
        self.mox.ReplayAll()

        self._test_snapshot()

    def _snapshot_delete_vm_snapshot_exception(self, exception, call_count=1):
        self._create_vm()
        fake_vm = vmwareapi_fake._get_objects("VirtualMachine").objects[0].obj
        snapshot_ref = vmwareapi_fake.ManagedObjectReference(
                               value="Snapshot-123",
                               name="VirtualMachineSnapshot")

        with contextlib.nested(
            mock.patch.object(self.conn._session, '_wait_for_task',
                              side_effect=exception),
            mock.patch.object(vmops, '_time_sleep_wrapper')
        ) as (_fake_wait, _fake_sleep):
            if exception != vexc.TaskInProgress:
                self.assertRaises(exception,
                                  self.conn._vmops._delete_vm_snapshot,
                                  self.instance, fake_vm, snapshot_ref)
                self.assertEqual(0, _fake_sleep.call_count)
            else:
                self.conn._vmops._delete_vm_snapshot(self.instance, fake_vm,
                                                     snapshot_ref)
                self.assertEqual(call_count - 1, _fake_sleep.call_count)
            self.assertEqual(call_count, _fake_wait.call_count)

    def test_snapshot_delete_vm_snapshot_exception(self):
        self._snapshot_delete_vm_snapshot_exception(exception.NovaException)

    def test_snapshot_delete_vm_snapshot_exception_retry(self):
        self.flags(api_retry_count=5, group='vmware')
        self._snapshot_delete_vm_snapshot_exception(vexc.TaskInProgress,
                                                    5)

    def test_reboot(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        reboot_type = "SOFT"
        self.conn.reboot(self.context, self.instance, self.network_info,
                         reboot_type)
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)

    def test_reboot_with_uuid(self):
        """Test fall back to use name when can't find by uuid."""
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        reboot_type = "SOFT"
        self.conn.reboot(self.context, self.instance, self.network_info,
                         reboot_type)
        info = self._get_info()
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
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self._get_info()
        self._check_vm_info(info, power_state.SUSPENDED)
        self.assertRaises(exception.InstanceRebootFailure, self.conn.reboot,
                          self.context, self.instance, self.network_info,
                          'SOFT')

    def test_suspend(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self._get_info()
        self._check_vm_info(info, power_state.SUSPENDED)

    def test_suspend_non_existent(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, self.conn.suspend,
                          self.instance)

    def test_resume(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self._get_info()
        self._check_vm_info(info, power_state.SUSPENDED)
        self.conn.resume(self.context, self.instance, self.network_info)
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)

    def test_resume_non_existent(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, self.conn.resume,
                          self.context, self.instance, self.network_info)

    def test_resume_not_suspended(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.assertRaises(exception.InstanceResumeFailure, self.conn.resume,
                          self.context, self.instance, self.network_info)

    def test_power_on(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self._get_info()
        self._check_vm_info(info, power_state.SHUTDOWN)
        self.conn.power_on(self.context, self.instance, self.network_info)
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)

    def test_power_on_non_existent(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_on,
                          self.context, self.instance, self.network_info)

    def test_power_off(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self._get_info()
        self._check_vm_info(info, power_state.SHUTDOWN)

    def test_power_off_non_existent(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_off,
                          self.instance)

    @mock.patch.object(driver.VMwareVCDriver, 'reboot')
    @mock.patch.object(vm_util, 'get_vm_state',
                       return_value='poweredOff')
    def test_resume_state_on_host_boot(self, mock_get_vm_state,
                                       mock_reboot):
        self._create_instance()
        self.conn.resume_state_on_host_boot(self.context, self.instance,
                'network_info')
        mock_get_vm_state.assert_called_once_with(self.conn._session,
                                                  self.instance)
        mock_reboot.assert_called_once_with(self.context, self.instance,
                                            'network_info', 'hard', None)

    def test_resume_state_on_host_boot_no_reboot(self):
        self._create_instance()
        for state in ['poweredOn', 'suspended']:
            with contextlib.nested(
                mock.patch.object(driver.VMwareVCDriver, 'reboot'),
                mock.patch.object(vm_util, 'get_vm_state',
                                  return_value=state)
            ) as (mock_reboot, mock_get_vm_state):
                self.conn.resume_state_on_host_boot(self.context,
                                                    self.instance,
                                                    'network_info')
                mock_get_vm_state.assert_called_once_with(self.conn._session,
                                                          self.instance)
                self.assertFalse(mock_reboot.called)

    def destroy_rescued(self, fake_method):
        self._rescue()
        with contextlib.nested(
            mock.patch.object(self.conn._volumeops, "detach_disk_from_vm",
                              fake_method),
            mock.patch.object(vm_util, "power_on_instance"),
        ) as (fake_detach, fake_power_on):
            self.instance['vm_state'] = vm_states.RESCUED
            self.conn.destroy(self.context, self.instance, self.network_info)
            inst_path = ds_util.DatastorePath(self.ds, self.uuid,
                                              '%s.vmdk' % self.uuid)
            self.assertFalse(vmwareapi_fake.get_file(str(inst_path)))
            rescue_file_path = ds_util.DatastorePath(
                self.ds, '%s-rescue' % self.uuid, '%s-rescue.vmdk' % self.uuid)
            self.assertFalse(vmwareapi_fake.get_file(str(rescue_file_path)))
            # Unrescue does not power on with destroy
            self.assertFalse(fake_power_on.called)

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
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 1)
        self.conn.destroy(self.context, self.instance, self.network_info)
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 0)
        self.assertIsNone(vm_util.vm_ref_cache_get(self.uuid))

    def test_destroy_no_datastore(self):
        self._create_vm()
        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEqual(len(instances), 1)
        # Delete the vmPathName
        vm = self._get_vm_record()
        vm.delete('config.files.vmPathName')
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
                                                 self.destroy_disks)

    def test_destroy_instance_without_compute(self):
        self.destroy_disks = True
        with mock.patch.object(self.conn._vmops,
                               "destroy") as mock_destroy:
            self.conn.destroy(self.context, self.instance_without_compute,
                              self.network_info,
                              None, self.destroy_disks)
            self.assertFalse(mock_destroy.called)

    def _destroy_instance_without_vm_ref(self, resize_exists=False,
                                         task_state=None):

        def fake_vm_ref_from_name(session, vm_name):
            if resize_exists:
                return 'fake-ref'

        self._create_instance()
        with contextlib.nested(
             mock.patch.object(vm_util, 'get_vm_ref_from_name',
                               fake_vm_ref_from_name),
             mock.patch.object(self.conn._session,
                               '_call_method'),
             mock.patch.object(self.conn._vmops,
                               '_destroy_instance')
        ) as (mock_get, mock_call, mock_destroy):
            self.instance.task_state = task_state
            self.conn.destroy(self.context, self.instance,
                              self.network_info,
                              None, True)
            if resize_exists:
                if task_state == task_states.RESIZE_REVERTING:
                    expected = 1
                else:
                    expected = 2
            else:
                expected = 1
            self.assertEqual(expected, mock_destroy.call_count)
            self.assertFalse(mock_call.called)

    def test_destroy_instance_without_vm_ref(self):
        self._destroy_instance_without_vm_ref()

    def test_destroy_instance_without_vm_ref_with_resize(self):
        self._destroy_instance_without_vm_ref(resize_exists=True)

    def test_destroy_instance_without_vm_ref_with_resize_revert(self):
        self._destroy_instance_without_vm_ref(resize_exists=True,
            task_state=task_states.RESIZE_REVERTING)

    def _rescue(self, config_drive=False):
        # validate that the power on is only called once
        self._power_on = vm_util.power_on_instance
        self._power_on_called = 0

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
                return str(ds_util.DatastorePath(data_store_name,
                                                 instance_uuid, 'fake.iso'))

            self.stubs.Set(self.conn._vmops, '_create_config_drive',
                           fake_create_config_drive)

        self._create_vm()

        def fake_power_on_instance(session, instance, vm_ref=None):
            self._power_on_called += 1
            return self._power_on(session, instance, vm_ref=vm_ref)

        info = self._get_info()
        self._check_vm_info(info, power_state.RUNNING)
        self.stubs.Set(vm_util, "power_on_instance",
                       fake_power_on_instance)
        self.stubs.Set(self.conn._volumeops, "attach_disk_to_vm",
                       fake_attach_disk_to_vm)

        self.conn.rescue(self.context, self.instance, self.network_info,
                         self.image, 'fake-password')
        info = self._get_info(name='1-rescue',
                              uuid='%s-rescue' % self.uuid)
        self._check_vm_info(info, power_state.RUNNING)
        info = self._get_info()
        self._check_vm_info(info, power_state.SHUTDOWN)
        self.assertIsNotNone(vm_util.vm_ref_cache_get('%s-rescue' % self.uuid))
        self.assertEqual(1, self._power_on_called)

    def test_rescue(self):
        self._rescue()
        inst_file_path = ds_util.DatastorePath(self.ds, self.uuid,
                                               '%s.vmdk' % self.uuid)
        self.assertTrue(vmwareapi_fake.get_file(str(inst_file_path)))
        rescue_file_path = ds_util.DatastorePath(self.ds,
                                                 '%s-rescue' % self.uuid,
                                                 '%s-rescue.vmdk' % self.uuid)
        self.assertTrue(vmwareapi_fake.get_file(str(rescue_file_path)))

    def test_rescue_with_config_drive(self):
        self.flags(force_config_drive=True)
        self._rescue(config_drive=True)

    def test_unrescue(self):
        # NOTE(dims): driver unrescue ends up eventually in vmops.unrescue
        # with power_on=True, the test_destroy_rescued tests the
        # vmops.unrescue with power_on=False
        self._rescue()
        vm_ref = vm_util.get_vm_ref(self.conn._session,
                                    self.instance)
        vm_rescue_ref = vm_util.get_vm_ref_from_name(self.conn._session,
                                                     '%s-rescue' % self.uuid)

        self.poweroff_instance = vm_util.power_off_instance

        def fake_power_off_instance(session, instance, vm_ref):
            # This is called so that we actually poweroff the simulated vm.
            # The reason for this is that there is a validation in destroy
            # that the instance is not powered on.
            self.poweroff_instance(session, instance, vm_ref)

        def fake_detach_disk_from_vm(vm_ref, instance,
                                     device_name, destroy_disk=False):
            self.test_device_name = device_name
            info = self.conn.get_info(instance)
            self._check_vm_info(info, power_state.SHUTDOWN)

        with contextlib.nested(
            mock.patch.object(vm_util, "power_off_instance",
                              side_effect=fake_power_off_instance),
            mock.patch.object(self.conn._volumeops, "detach_disk_from_vm",
                              side_effect=fake_detach_disk_from_vm),
            mock.patch.object(vm_util, "power_on_instance"),
        ) as (poweroff, detach, fake_power_on):
            self.conn.unrescue(self.instance, None)
            poweroff.assert_called_once_with(self.conn._session, mock.ANY,
                                             vm_rescue_ref)
            detach.assert_called_once_with(vm_rescue_ref, mock.ANY,
                                           self.test_device_name)
            fake_power_on.assert_called_once_with(self.conn._session,
                                                  self.instance,
                                                  vm_ref=vm_ref)
            self.test_vm_ref = None
            self.test_device_name = None

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
        expected = {'vmware:' + k: v for k, v in expected.items()}
        self.assertThat(
                self.conn.get_diagnostics({'name': 1, 'uuid': self.uuid,
                                           'node': self.instance_node}),
                matchers.DictMatches(expected))

    def test_get_instance_diagnostics(self):
        self._create_vm()
        expected = {'uptime': 0,
                    'memory_details': {'used': 0, 'maximum': 512},
                    'nic_details': [],
                    'driver': 'vmwareapi',
                    'state': 'running',
                    'version': '1.0',
                    'cpu_details': [],
                    'disk_details': [],
                    'hypervisor_os': 'esxi',
                    'config_drive': False}
        actual = self.conn.get_instance_diagnostics(
                {'name': 1, 'uuid': self.uuid, 'node': self.instance_node})
        self.assertThat(actual.serialize(), matchers.DictMatches(expected))

    def test_get_console_output(self):
        self.assertRaises(NotImplementedError, self.conn.get_console_output,
            None, None)

    def test_get_vnc_console_non_existent(self):
        self._create_instance()
        self.assertRaises(exception.InstanceNotFound,
                          self.conn.get_vnc_console,
                          self.context,
                          self.instance)

    def _test_get_vnc_console(self):
        self._create_vm()
        fake_vm = self._get_vm_record()
        OptionValue = collections.namedtuple('OptionValue', ['key', 'value'])
        opt_val = OptionValue(key='', value=5906)
        fake_vm.set(vm_util.VNC_CONFIG_KEY, opt_val)
        vnc_console = self.conn.get_vnc_console(self.context, self.instance)
        self.assertEqual(self.vnc_host, vnc_console.host)
        self.assertEqual(5906, vnc_console.port)

    def test_get_vnc_console(self):
        self._test_get_vnc_console()

    def test_get_vnc_console_noport(self):
        self._create_vm()
        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self.conn.get_vnc_console,
                          self.context,
                          self.instance)

    def test_get_volume_connector(self):
        self._create_vm()
        connector_dict = self.conn.get_volume_connector(self.instance)
        fake_vm = self._get_vm_record()
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
                self.instance)
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
                self.instance)
        self.mox.ReplayAll()
        self.conn.detach_volume(connection_info, self.instance, mount_point,
                                encryption=None)

    def test_attach_vmdk_disk_to_vm(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('vmdk')

        adapter_type = constants.DEFAULT_ADAPTER_TYPE
        disk_type = constants.DEFAULT_DISK_TYPE
        vmdk_info = vm_util.VmdkInfo('fake-path', adapter_type, disk_type, 64,
                                     'fake-device')
        with contextlib.nested(
            mock.patch.object(vm_util, 'get_vm_ref',
                              return_value=mock.sentinel.vm_ref),
            mock.patch.object(volumeops.VMwareVolumeOps, '_get_volume_ref'),
            mock.patch.object(vm_util, 'get_vmdk_info',
                              return_value=vmdk_info),
            mock.patch.object(volumeops.VMwareVolumeOps, 'attach_disk_to_vm'),
            mock.patch.object(volumeops.VMwareVolumeOps,
                              '_update_volume_details')
        ) as (get_vm_ref, get_volume_ref, get_vmdk_info,
              attach_disk_to_vm, update_volume_details):
            self.conn.attach_volume(None, connection_info, self.instance,
                                    '/dev/vdc')

            get_vm_ref.assert_called_once_with(self.conn._session,
                                               self.instance)
            get_volume_ref.assert_called_once_with(
                connection_info['data']['volume'])
            self.assertTrue(get_vmdk_info.called)
            attach_disk_to_vm.assert_called_once_with(mock.sentinel.vm_ref,
                self.instance, adapter_type, disk_type, vmdk_path='fake-path')
            update_volume_details.assert_called_once_with(
                mock.sentinel.vm_ref, self.instance,
                connection_info['data']['volume_id'])

    def test_detach_vmdk_disk_from_vm(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('vmdk')

        adapter_type = constants.DEFAULT_ADAPTER_TYPE
        disk_type = constants.DEFAULT_DISK_TYPE
        vmdk_info = vm_util.VmdkInfo('fake-path', adapter_type, disk_type, 64,
                                     'fake-device')
        with contextlib.nested(
            mock.patch.object(vm_util, 'get_vm_ref',
                              return_value=mock.sentinel.vm_ref),
            mock.patch.object(volumeops.VMwareVolumeOps, '_get_volume_ref',
                              return_value=mock.sentinel.volume_ref),
            mock.patch.object(volumeops.VMwareVolumeOps,
                              '_get_vmdk_backed_disk_device',
                              return_value=mock.sentinel.disk_device),
            mock.patch.object(vm_util, 'get_vmdk_info',
                              return_value=vmdk_info),
            mock.patch.object(volumeops.VMwareVolumeOps,
                              '_consolidate_vmdk_volume'),
            mock.patch.object(volumeops.VMwareVolumeOps,
                              'detach_disk_from_vm')
        ) as (get_vm_ref, get_volume_ref, get_vmdk_backed_disk_device,
              get_vmdk_info, consolidate_vmdk_volume, detach_disk_from_vm):
            self.conn.detach_volume(connection_info, self.instance,
                                    '/dev/vdc', encryption=None)

            get_vm_ref.assert_called_once_with(self.conn._session,
                                               self.instance)
            get_volume_ref.assert_called_once_with(
                connection_info['data']['volume'])
            get_vmdk_backed_disk_device.assert_called_once_with(
                mock.sentinel.vm_ref, connection_info['data'])
            self.assertTrue(get_vmdk_info.called)
            consolidate_vmdk_volume.assert_called_once_with(self.instance,
                mock.sentinel.vm_ref, mock.sentinel.disk_device,
                mock.sentinel.volume_ref, adapter_type=adapter_type,
                disk_type=disk_type)
            detach_disk_from_vm.assert_called_once_with(mock.sentinel.vm_ref,
                self.instance, mock.sentinel.disk_device)

    def test_volume_attach_iscsi(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('iscsi')
        mount_point = '/dev/vdc'
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_attach_volume_iscsi')
        volumeops.VMwareVolumeOps._attach_volume_iscsi(connection_info,
                self.instance)
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
                self.instance)
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
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_iscsi_get_target')
        # simulate target not found
        volumeops.VMwareVolumeOps._iscsi_get_target(
            connection_info['data']).AndReturn((None, None))
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_iscsi_add_send_target_host')
        # rescan gets called with target portal
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_iscsi_rescan_hba')
        volumeops.VMwareVolumeOps._iscsi_rescan_hba(
            connection_info['data']['target_portal'])
        # simulate target found
        volumeops.VMwareVolumeOps._iscsi_get_target(
            connection_info['data']).AndReturn(discover)
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 'attach_disk_to_vm')
        volumeops.VMwareVolumeOps.attach_disk_to_vm(mox.IgnoreArg(),
                self.instance, mox.IgnoreArg(), 'rdmp',
                device_name=mox.IgnoreArg())
        self.mox.ReplayAll()
        self.conn.attach_volume(None, connection_info, self.instance,
                                mount_point)

    def test_iscsi_rescan_hba(self):
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
        vops = volumeops.VMwareVolumeOps(self.conn._session)
        vops._iscsi_rescan_hba(fake_target_portal)
        # Check if HBA has the target portal configured
        self.assertEqual('fake_target_host',
                          iscsi_hba.configuredSendTarget[0].address)
        # Rescan HBA with same portal
        vops._iscsi_rescan_hba(fake_target_portal)
        self.assertEqual(1, len(iscsi_hba.configuredSendTarget))

    def test_iscsi_get_target(self):
        data = {'target_portal': 'fake_target_host:port',
                'target_iqn': 'fake_target_iqn'}
        host = vmwareapi_fake._get_objects('HostSystem').objects[0]
        host._add_iscsi_target(data)
        vops = volumeops.VMwareVolumeOps(self.conn._session)
        result = vops._iscsi_get_target(data)
        self.assertEqual(('fake-device', 'fake-uuid'), result)

    def test_detach_iscsi_disk_from_vm(self):
        self._create_vm()
        connection_info = self._test_vmdk_connection_info('iscsi')
        connection_info['data']['target_portal'] = 'fake_target_portal'
        connection_info['data']['target_iqn'] = 'fake_target_iqn'
        mount_point = '/dev/vdc'
        find = ('fake_name', 'fake_uuid')
        self.mox.StubOutWithMock(volumeops.VMwareVolumeOps,
                                 '_iscsi_get_target')
        volumeops.VMwareVolumeOps._iscsi_get_target(
            connection_info['data']).AndReturn(find)
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

    @mock.patch.object(objects.block_device.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_image_aging_image_used(self, mock_get_by_inst):
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
        timestamp = ds_util.DatastorePath(self.ds, 'vmware_base',
                                          self.fake_image_uuid,
                                          self._get_timestamp_filename() + '/')
        if exists:
            self.assertTrue(vmwareapi_fake.get_file(str(timestamp)))
        else:
            self.assertFalse(vmwareapi_fake.get_file(str(timestamp)))

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

    @mock.patch.object(objects.block_device.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_timestamp_file_removed_aging(self, mock_get_by_inst):
        self._timestamp_file_removed()
        ts = self._get_timestamp_filename()
        ts_path = ds_util.DatastorePath(self.ds, 'vmware_base',
                                        self.fake_image_uuid, ts + '/')
        vmwareapi_fake._add_file(str(ts_path))
        self._timestamp_file_exists()
        all_instances = [self.instance]
        self.conn.manage_image_cache(self.context, all_instances)
        self._timestamp_file_exists(exists=False)

    @mock.patch.object(objects.block_device.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_image_aging_disabled(self, mock_get_by_inst):
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

    def test_public_api_signatures(self):
        self.assertPublicAPISignatures(v_driver.ComputeDriver(None), self.conn)

    def test_register_extension(self):
        with mock.patch.object(self.conn._session, '_call_method',
                               return_value=None) as mock_call_method:
            self.conn._register_openstack_extension()
            mock_call_method.assert_has_calls(
                [mock.call(oslo_vim_util, 'find_extension',
                           constants.EXTENSION_KEY),
                 mock.call(oslo_vim_util, 'register_extension',
                           constants.EXTENSION_KEY,
                           constants.EXTENSION_TYPE_INSTANCE)])

    def test_register_extension_already_exists(self):
        with mock.patch.object(self.conn._session, '_call_method',
                               return_value='fake-extension') as mock_find_ext:
            self.conn._register_openstack_extension()
            mock_find_ext.assert_called_once_with(oslo_vim_util,
                                                  'find_extension',
                                                  constants.EXTENSION_KEY)

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
        vcdriver._session.vim = None

        def side_effect():
            vcdriver._session.vim = mock.Mock()
        vcdriver._session._create_session.side_effect = side_effect
        return vcdriver

    def test_host_power_action(self):
        self.assertRaises(NotImplementedError,
                          self.conn.host_power_action, 'action')

    def test_host_maintenance_mode(self):
        self.assertRaises(NotImplementedError,
                          self.conn.host_maintenance_mode, 'host', 'mode')

    def test_set_host_enabled(self):
        self.assertRaises(NotImplementedError,
                          self.conn.set_host_enabled, 'state')

    def test_datastore_regex_configured(self):
        for node in self.conn._resources.keys():
            self.assertEqual(self.conn._datastore_regex,
                    self.conn._resources[node]['vmops']._datastore_regex)
            self.assertEqual(self.conn._datastore_regex,
                    self.conn._resources[node]['vcstate']._datastore_regex)

    @mock.patch('nova.virt.vmwareapi.ds_util.get_datastore')
    def test_datastore_regex_configured_vcstate(self, mock_get_ds_ref):
        self.assertEqual(2, len(self.conn._resources.keys()))
        for node in self.conn._resources.keys():
            vcstate = self.conn._resources[node]['vcstate']
            self.conn.get_available_resource(node)
            mock_get_ds_ref.assert_called_with(
                vcstate._session, vcstate._cluster, vcstate._datastore_regex)

    def test_get_available_resource(self):
        stats = self.conn.get_available_resource(self.node_name)
        self.assertEqual(stats['vcpus'], 32)
        self.assertEqual(stats['local_gb'], 1024)
        self.assertEqual(stats['local_gb_used'], 1024 - 500)
        self.assertEqual(stats['memory_mb'], 1000)
        self.assertEqual(stats['memory_mb_used'], 500)
        self.assertEqual(stats['hypervisor_type'], 'VMware vCenter Server')
        self.assertEqual(stats['hypervisor_version'], 5001000)
        self.assertEqual(stats['hypervisor_hostname'], self.node_name)
        self.assertIsNone(stats['cpu_info'])
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
        info = self._get_info(uuid=uuid1)
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.destroy(self.context, self.instance, self.network_info)
        self._create_vm(node=self.node_name2, num_instances=1,
                        uuid=uuid2)
        info = self._get_info(uuid=uuid2)
        self._check_vm_info(info, power_state.RUNNING)

    def test_spawn_invalid_node(self):
        self._create_instance(node='InvalidNodeName')
        self.assertRaises(exception.NotFound, self.conn.spawn,
                          self.context, self.instance, self.image,
                          injected_files=[], admin_password=None,
                          network_info=self.network_info,
                          block_device_info=None)

    @mock.patch.object(nova.virt.vmwareapi.images.VMwareImage,
                       'from_image')
    def test_spawn_with_sparse_image(self, mock_from_image):
        img_info = images.VMwareImage(
            image_id=self.fake_image_uuid,
            file_size=1024,
            disk_type=constants.DISK_TYPE_SPARSE,
            linked_clone=False)

        mock_from_image.return_value = img_info

        self._create_vm()
        info = self._get_info()
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

    def _create_vif(self):
        gw_4 = network_model.IP(address='101.168.1.1', type='gateway')
        dns_4 = network_model.IP(address='8.8.8.8', type=None)
        subnet_4 = network_model.Subnet(cidr='101.168.1.0/24',
                                        dns=[dns_4],
                                        gateway=gw_4,
                                        routes=None,
                                        dhcp_server='191.168.1.1')

        gw_6 = network_model.IP(address='101:1db9::1', type='gateway')
        subnet_6 = network_model.Subnet(cidr='101:1db9::/64',
                                        dns=None,
                                        gateway=gw_6,
                                        ips=None,
                                        routes=None)

        network_neutron = network_model.Network(id='network-id-xxx-yyy-zzz',
                                                bridge=None,
                                                label=None,
                                                subnets=[subnet_4,
                                                         subnet_6],
                                                bridge_interface='eth0',
                                                vlan=99)

        vif_bridge_neutron = network_model.VIF(id='new-vif-xxx-yyy-zzz',
                                               address='ca:fe:de:ad:be:ef',
                                               network=network_neutron,
                                               type=None,
                                               devname='tap-xxx-yyy-zzz',
                                               ovs_interfaceid='aaa-bbb-ccc')
        return vif_bridge_neutron

    def _validate_interfaces(self, id, index, num_iface_ids):
        vm = self._get_vm_record()
        found_iface_id = False
        extras = vm.get("config.extraConfig")
        key = "nvp.iface-id.%s" % index
        num_found = 0
        for c in extras.OptionValue:
            if c.key.startswith("nvp.iface-id."):
                num_found += 1
                if c.key == key and c.value == id:
                    found_iface_id = True
        self.assertTrue(found_iface_id)
        self.assertEqual(num_found, num_iface_ids)

    def _attach_interface(self, vif):
        self.conn.attach_interface(self.instance, self.image, vif)
        self._validate_interfaces(vif['id'], 1, 2)

    def test_attach_interface(self):
        self._create_vm()
        vif = self._create_vif()
        self._attach_interface(vif)

    def test_attach_interface_with_exception(self):
        self._create_vm()
        vif = self._create_vif()

        with mock.patch.object(self.conn._session, '_wait_for_task',
                               side_effect=Exception):
            self.assertRaises(exception.InterfaceAttachFailed,
                              self.conn.attach_interface,
                              self.instance, self.image, vif)

    @mock.patch.object(vif, 'get_network_device',
                       return_value='fake_device')
    def _detach_interface(self, vif, mock_get_device):
        self._create_vm()
        self._attach_interface(vif)
        self.conn.detach_interface(self.instance, vif)
        self._validate_interfaces('free', 1, 2)

    def test_detach_interface(self):
        vif = self._create_vif()
        self._detach_interface(vif)

    def test_detach_interface_and_attach(self):
        vif = self._create_vif()
        self._detach_interface(vif)
        self.conn.attach_interface(self.instance, self.image, vif)
        self._validate_interfaces(vif['id'], 1, 2)

    def test_detach_interface_no_device(self):
        self._create_vm()
        vif = self._create_vif()
        self._attach_interface(vif)
        self.assertRaises(exception.NotFound, self.conn.detach_interface,
                          self.instance, vif)

    def test_detach_interface_no_vif_match(self):
        self._create_vm()
        vif = self._create_vif()
        self._attach_interface(vif)
        vif['id'] = 'bad-id'
        self.assertRaises(exception.NotFound, self.conn.detach_interface,
                          self.instance, vif)

    @mock.patch.object(vif, 'get_network_device',
                       return_value='fake_device')
    def test_detach_interface_with_exception(self, mock_get_device):
        self._create_vm()
        vif = self._create_vif()
        self._attach_interface(vif)

        with mock.patch.object(self.conn._session, '_wait_for_task',
                               side_effect=Exception):
            self.assertRaises(exception.InterfaceDetachFailed,
                              self.conn.detach_interface,
                              self.instance, vif)

    def test_migrate_disk_and_power_off(self):
        def fake_update_instance_progress(context, instance, step,
                                          total_steps):
            pass

        def fake_get_host_ref_from_name(dest):
            return None

        self._create_vm(instance_type='m1.large')
        vm_ref_orig = vm_util.get_vm_ref(self.conn._session, self.instance)
        flavor = self._get_instance_type_by_name('m1.large')
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
        self.assertRaises(vexc.MissingParameter,
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

    def test_resize_to_smaller_disk(self):
        self._create_vm(instance_type='m1.large')
        flavor = self._get_instance_type_by_name('m1.small')
        self.assertRaises(exception.InstanceFaultRollback,
                          self.conn.migrate_disk_and_power_off, self.context,
                          self.instance, 'fake_dest', flavor, None)

    def test_spawn_attach_volume_vmdk(self):
        self._spawn_attach_volume_vmdk()

    def test_spawn_attach_volume_vmdk_no_image_ref(self):
        self._spawn_attach_volume_vmdk(set_image_ref=False)

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
        instance = objects.Instance()
        try:
            disk_info = self.conn.get_instance_disk_info(instance)
            self.assertIsNone(disk_info)
        except NotImplementedError:
            self.fail("test_get_instance_disk_info() should not raise "
                      "NotImplementedError")

    def test_get_host_uptime(self):
        self.assertRaises(NotImplementedError,
                          self.conn.get_host_uptime)

    def _test_finish_migration(self, power_on, resize_instance=False):
        """Tests the finish_migration method on VC Driver."""
        # setup the test instance in the database
        self._create_vm()
        if resize_instance:
            self.instance.system_metadata = {'old_instance_type_root_gb': '0'}
        vm_ref = vm_util.get_vm_ref(self.conn._session, self.instance)
        datastore = ds_util.Datastore(ref='fake-ref', name='fake')
        dc_info = vmops.DcInfo(ref='fake_ref', name='fake',
                               vmFolder='fake_folder')
        with contextlib.nested(
                mock.patch.object(self.conn._session, "_call_method",
                                  return_value='fake-task'),
                mock.patch.object(self.conn._vmops,
                                  "_update_instance_progress"),
                mock.patch.object(self.conn._session, "_wait_for_task"),
                mock.patch.object(vm_util, "get_vm_resize_spec",
                                  return_value='fake-spec'),
                mock.patch.object(ds_util, "get_datastore",
                                  return_value=datastore),
                mock.patch.object(self.conn._vmops,
                                  'get_datacenter_ref_and_name',
                                  return_value=dc_info),
                mock.patch.object(self.conn._vmops, '_extend_virtual_disk'),
                mock.patch.object(vm_util, "power_on_instance")
        ) as (fake_call_method, fake_update_instance_progress,
              fake_wait_for_task, fake_vm_resize_spec,
              fake_get_datastore, fake_get_datacenter_ref_and_name,
              fake_extend_virtual_disk, fake_power_on):
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
                fake_vm_resize_spec.assert_called_once_with(
                    self.conn._session.vim.client.factory,
                    self.instance.vcpus,
                    self.instance.memory_mb)
                fake_call_method.assert_any_call(
                    self.conn._session.vim,
                    "ReconfigVM_Task",
                    vm_ref,
                    spec='fake-spec')
                fake_wait_for_task.assert_called_once_with('fake-task')
                fake_extend_virtual_disk.assert_called_once_with(
                    self.instance, self.instance['root_gb'] * units.Mi,
                    None, dc_info.ref)
            else:
                self.assertFalse(fake_vm_resize_spec.called)
                self.assertFalse(fake_call_method.called)
                self.assertFalse(fake_wait_for_task.called)
                self.assertFalse(fake_extend_virtual_disk.called)

            if power_on:
                fake_power_on.assert_called_once_with(self.conn._session,
                                                      self.instance,
                                                      vm_ref=vm_ref)
            else:
                self.assertFalse(fake_power_on.called)
            fake_update_instance_progress.called_once_with(
                self.context, self.instance, 4, vmops.RESIZE_TOTAL_STEPS)

    def test_finish_migration_power_on(self):
        self._test_finish_migration(power_on=True)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(power_on=False)

    def test_finish_migration_power_on_resize(self):
        self._test_finish_migration(power_on=True,
                                    resize_instance=True)

    @mock.patch.object(vm_util, 'associate_vmref_for_instance')
    @mock.patch.object(vm_util, 'power_on_instance')
    def _test_finish_revert_migration(self, fake_power_on,
                                      fake_associate_vmref, power_on):
        """Tests the finish_revert_migration method on VC Driver."""

        # setup the test instance in the database
        self._create_instance()
        self.conn.finish_revert_migration(self.context,
                                          instance=self.instance,
                                          network_info=None,
                                          block_device_info=None,
                                          power_on=power_on)
        fake_associate_vmref.assert_called_once_with(self.conn._session,
                                                     self.instance,
                                                     suffix='-orig')
        if power_on:
            fake_power_on.assert_called_once_with(self.conn._session,
                                                  self.instance)
        else:
            self.assertFalse(fake_power_on.called)

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(power_on=True)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(power_on=False)

    def test_pbm_wsdl_location(self):
        self.flags(pbm_enabled=True,
                   pbm_wsdl_location='fira',
                   group='vmware')
        self.conn._update_pbm_location()
        self.assertEqual('fira', self.conn._session._pbm_wsdl_loc)
        self.assertIsNone(self.conn._session._pbm)
