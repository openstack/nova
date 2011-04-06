# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2010 Citrix Systems, Inc.
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

"""Test suite for XenAPI."""

import functools
import os
import re
import stubout
import ast

from nova import db
from nova import context
from nova import flags
from nova import log as logging
from nova import test
from nova import utils
from nova.auth import manager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import xenapi_conn
from nova.virt.xenapi import fake as xenapi_fake
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi.vmops import SimpleDH
from nova.virt.xenapi.vmops import VMOps
from nova.tests.db import fakes as db_fakes
from nova.tests.xenapi import stubs
from nova.tests.glance import stubs as glance_stubs
from nova.tests import fake_utils

LOG = logging.getLogger('nova.tests.test_xenapi')

FLAGS = flags.FLAGS


def stub_vm_utils_with_vdi_attached_here(function, should_return=True):
    """
    vm_utils.with_vdi_attached_here needs to be stubbed out because it
    calls down to the filesystem to attach a vdi. This provides a
    decorator to handle that.
    """
    @functools.wraps(function)
    def decorated_function(self, *args, **kwargs):
        orig_with_vdi_attached_here = vm_utils.with_vdi_attached_here
        vm_utils.with_vdi_attached_here = lambda *x: should_return
        function(self, *args, **kwargs)
        vm_utils.with_vdi_attached_here = orig_with_vdi_attached_here
    return decorated_function


class XenAPIVolumeTestCase(test.TestCase):
    """Unit tests for Volume operations."""
    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.context = context.RequestContext('fake', 'fake', False)
        FLAGS.target_host = '127.0.0.1'
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        db_fakes.stub_out_db_instance_api(self.stubs)
        stubs.stub_out_get_target(self.stubs)
        xenapi_fake.reset()
        self.values = {'id': 1,
                  'project_id': 'fake',
                  'user_id': 'fake',
                  'image_id': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'instance_type': 'm1.large',
                  'mac_address': 'aa:bb:cc:dd:ee:ff',
                  'os_type': 'linux'}

    def _create_volume(self, size='0'):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['host'] = 'localhost'
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        return db.volume_create(self.context, vol)

    def test_create_iscsi_storage(self):
        """This shows how to test helper classes' methods."""
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = volume_utils.VolumeHelper
        helper.XenAPI = session.get_imported_xenapi()
        vol = self._create_volume()
        info = helper.parse_volume_info(vol['id'], '/dev/sdc')
        label = 'SR-%s' % vol['id']
        description = 'Test-SR'
        sr_ref = helper.create_iscsi_storage(session, info, label, description)
        srs = xenapi_fake.get_all('SR')
        self.assertEqual(sr_ref, srs[0])
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_parse_volume_info_raise_exception(self):
        """This shows how to test helper classes' methods."""
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        session = xenapi_conn.XenAPISession('test_url', 'root', 'test_pass')
        helper = volume_utils.VolumeHelper
        helper.XenAPI = session.get_imported_xenapi()
        vol = self._create_volume()
        # oops, wrong mount point!
        self.assertRaises(volume_utils.StorageError,
                          helper.parse_volume_info,
                          vol['id'],
                          '/dev/sd')
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_attach_volume(self):
        """This shows how to test Ops classes' methods."""
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.context, self.values)
        vm = xenapi_fake.create_vm(instance.name, 'Running')
        result = conn.attach_volume(instance.name, volume['id'], '/dev/sdc')

        def check():
            # check that the VM has a VBD attached to it
            # Get XenAPI record for VBD
            vbds = xenapi_fake.get_all('VBD')
            vbd = xenapi_fake.get_record('VBD', vbds[0])
            vm_ref = vbd['VM']
            self.assertEqual(vm_ref, vm)

        check()

    def test_attach_volume_raise_exception(self):
        """This shows how to test when exceptions are raised."""
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForVolumeFailedTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.context, self.values)
        xenapi_fake.create_vm(instance.name, 'Running')
        self.assertRaises(Exception,
                          conn.attach_volume,
                          instance.name,
                          volume['id'],
                          '/dev/sdc')

    def tearDown(self):
        super(XenAPIVolumeTestCase, self).tearDown()
        self.stubs.UnsetAll()


def reset_network(*args):
    pass


class XenAPIVMTestCase(test.TestCase):
    """Unit tests for VM operations."""
    def setUp(self):
        super(XenAPIVMTestCase, self).setUp()
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.network = utils.import_object(FLAGS.network_manager)
        self.stubs = stubout.StubOutForTesting()
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass',
                   instance_name_template='%d')
        xenapi_fake.reset()
        xenapi_fake.create_local_srs()
        xenapi_fake.create_local_pifs()
        db_fakes.stub_out_db_instance_api(self.stubs)
        xenapi_fake.create_network('fake', FLAGS.flat_network_bridge)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        stubs.stubout_get_this_vm_uuid(self.stubs)
        stubs.stubout_stream_disk(self.stubs)
        stubs.stubout_is_vdi_pv(self.stubs)
        self.stubs.Set(VMOps, 'reset_network', reset_network)
        stubs.stub_out_vm_methods(self.stubs)
        glance_stubs.stubout_glance_client(self.stubs,
                                           glance_stubs.FakeGlance)
        fake_utils.stub_out_utils_execute(self.stubs)
        self.context = context.RequestContext('fake', 'fake', False)
        self.conn = xenapi_conn.get_connection(False)

    def test_list_instances_0(self):
        instances = self.conn.list_instances()
        self.assertEquals(instances, [])

    def test_get_diagnostics(self):
        instance = self._create_instance()
        self.conn.get_diagnostics(instance)

    def test_instance_snapshot(self):
        stubs.stubout_instance_snapshot(self.stubs)
        instance = self._create_instance()

        name = "MySnapshot"
        template_vm_ref = self.conn.snapshot(instance, name)

        def ensure_vm_was_torn_down():
            vm_labels = []
            for vm_ref in xenapi_fake.get_all('VM'):
                vm_rec = xenapi_fake.get_record('VM', vm_ref)
                if not vm_rec["is_control_domain"]:
                    vm_labels.append(vm_rec["name_label"])

            self.assertEquals(vm_labels, ['1'])

        def ensure_vbd_was_torn_down():
            vbd_labels = []
            for vbd_ref in xenapi_fake.get_all('VBD'):
                vbd_rec = xenapi_fake.get_record('VBD', vbd_ref)
                vbd_labels.append(vbd_rec["vm_name_label"])

            self.assertEquals(vbd_labels, ['1'])

        def ensure_vdi_was_torn_down():
            for vdi_ref in xenapi_fake.get_all('VDI'):
                vdi_rec = xenapi_fake.get_record('VDI', vdi_ref)
                name_label = vdi_rec["name_label"]
                self.assert_(not name_label.endswith('snapshot'))

        def check():
            ensure_vm_was_torn_down()
            ensure_vbd_was_torn_down()
            ensure_vdi_was_torn_down()

        check()

    def create_vm_record(self, conn, os_type, instance_id=1):
        instances = conn.list_instances()
        self.assertEquals(instances, [str(instance_id)])

        # Get Nova record for VM
        vm_info = conn.get_info(instance_id)
        # Get XenAPI record for VM
        vms = [rec for ref, rec
               in xenapi_fake.get_all_records('VM').iteritems()
               if not rec['is_control_domain']]
        vm = vms[0]
        self.vm_info = vm_info
        self.vm = vm

    def check_vm_record(self, conn, check_injection=False):
        # Check that m1.large above turned into the right thing.
        instance_type = db.instance_type_get_by_name(conn, 'm1.large')
        mem_kib = long(instance_type['memory_mb']) << 10
        mem_bytes = str(mem_kib << 10)
        vcpus = instance_type['vcpus']
        self.assertEquals(self.vm_info['max_mem'], mem_kib)
        self.assertEquals(self.vm_info['mem'], mem_kib)
        self.assertEquals(self.vm['memory_static_max'], mem_bytes)
        self.assertEquals(self.vm['memory_dynamic_max'], mem_bytes)
        self.assertEquals(self.vm['memory_dynamic_min'], mem_bytes)
        self.assertEquals(self.vm['VCPUs_max'], str(vcpus))
        self.assertEquals(self.vm['VCPUs_at_startup'], str(vcpus))

        # Check that the VM is running according to Nova
        self.assertEquals(self.vm_info['state'], power_state.RUNNING)

        # Check that the VM is running according to XenAPI.
        self.assertEquals(self.vm['power_state'], 'Running')

        if check_injection:
            xenstore_data = self.vm['xenstore_data']
            key = 'vm-data/networking/aabbccddeeff'
            xenstore_value = xenstore_data[key]
            tcpip_data = ast.literal_eval(xenstore_value)
            self.assertEquals(tcpip_data,
                              {'label': 'fake_flat_network',
                               'broadcast': '10.0.0.255',
                               'ips': [{'ip': '10.0.0.3',
                                        'netmask':'255.255.255.0',
                                        'enabled':'1'}],
                                'ip6s': [{'ip': 'fe80::a8bb:ccff:fedd:eeff',
                                          'netmask': '120',
                                          'enabled': '1'}],
                                'mac': 'aa:bb:cc:dd:ee:ff',
                                'dns': ['10.0.0.2'],
                                'gateway': '10.0.0.1',
                                'gateway6': 'fe80::a00:1'})

    def check_vm_params_for_windows(self):
        self.assertEquals(self.vm['platform']['nx'], 'true')
        self.assertEquals(self.vm['HVM_boot_params'], {'order': 'dc'})
        self.assertEquals(self.vm['HVM_boot_policy'], 'BIOS order')

        # check that these are not set
        self.assertEquals(self.vm['PV_args'], '')
        self.assertEquals(self.vm['PV_bootloader'], '')
        self.assertEquals(self.vm['PV_kernel'], '')
        self.assertEquals(self.vm['PV_ramdisk'], '')

    def check_vm_params_for_linux(self):
        self.assertEquals(self.vm['platform']['nx'], 'false')
        self.assertEquals(self.vm['PV_args'], 'clocksource=jiffies')
        self.assertEquals(self.vm['PV_bootloader'], 'pygrub')

        # check that these are not set
        self.assertEquals(self.vm['PV_kernel'], '')
        self.assertEquals(self.vm['PV_ramdisk'], '')
        self.assertEquals(self.vm['HVM_boot_params'], {})
        self.assertEquals(self.vm['HVM_boot_policy'], '')

    def check_vm_params_for_linux_with_external_kernel(self):
        self.assertEquals(self.vm['platform']['nx'], 'false')
        self.assertEquals(self.vm['PV_args'], 'root=/dev/xvda1')
        self.assertNotEquals(self.vm['PV_kernel'], '')
        self.assertNotEquals(self.vm['PV_ramdisk'], '')

        # check that these are not set
        self.assertEquals(self.vm['HVM_boot_params'], {})
        self.assertEquals(self.vm['HVM_boot_policy'], '')

    def _test_spawn(self, image_id, kernel_id, ramdisk_id,
                    instance_type="m1.large", os_type="linux",
                    instance_id=1, check_injection=False):
        stubs.stubout_loopingcall_start(self.stubs)
        values = {'id': instance_id,
                  'project_id': self.project.id,
                  'user_id': self.user.id,
                  'image_id': image_id,
                  'kernel_id': kernel_id,
                  'ramdisk_id': ramdisk_id,
                  'instance_type': instance_type,
                  'mac_address': 'aa:bb:cc:dd:ee:ff',
                  'os_type': os_type}
        instance = db.instance_create(self.context, values)
        self.conn.spawn(instance)
        self.create_vm_record(self.conn, os_type, instance_id)
        self.check_vm_record(self.conn, check_injection)

    def test_spawn_not_enough_memory(self):
        FLAGS.xenapi_image_service = 'glance'
        self.assertRaises(Exception,
                          self._test_spawn,
                          1, 2, 3, "m1.xlarge")

    def test_spawn_raw_objectstore(self):
        FLAGS.xenapi_image_service = 'objectstore'
        self._test_spawn(1, None, None)

    def test_spawn_objectstore(self):
        FLAGS.xenapi_image_service = 'objectstore'
        self._test_spawn(1, 2, 3)

    @stub_vm_utils_with_vdi_attached_here
    def test_spawn_raw_glance(self):
        FLAGS.xenapi_image_service = 'glance'
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_RAW, None, None)
        self.check_vm_params_for_linux()

    def test_spawn_vhd_glance_linux(self):
        FLAGS.xenapi_image_service = 'glance'
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_VHD, None, None,
                         os_type="linux")
        self.check_vm_params_for_linux()

    def test_spawn_vhd_glance_windows(self):
        FLAGS.xenapi_image_service = 'glance'
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_VHD, None, None,
                         os_type="windows")
        self.check_vm_params_for_windows()

    def test_spawn_glance(self):
        FLAGS.xenapi_image_service = 'glance'
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_MACHINE,
                         glance_stubs.FakeGlance.IMAGE_KERNEL,
                         glance_stubs.FakeGlance.IMAGE_RAMDISK)
        self.check_vm_params_for_linux_with_external_kernel()

    def test_spawn_netinject_file(self):
        FLAGS.xenapi_image_service = 'glance'
        db_fakes.stub_out_db_instance_api(self.stubs, injected=True)

        self._tee_executed = False

        def _tee_handler(cmd, **kwargs):
            input = kwargs.get('process_input', None)
            self.assertNotEqual(input, None)
            config = [line.strip() for line in input.split("\n")]
            # Find the start of eth0 configuration and check it
            index = config.index('auto eth0')
            self.assertEquals(config[index + 1:index + 8], [
                'iface eth0 inet static',
                'address 10.0.0.3',
                'netmask 255.255.255.0',
                'broadcast 10.0.0.255',
                'gateway 10.0.0.1',
                'dns-nameservers 10.0.0.2',
                ''])
            self._tee_executed = True
            return '', ''

        fake_utils.fake_execute_set_repliers([
            # Capture the sudo tee .../etc/network/interfaces command
            (r'(sudo\s+)?tee.*interfaces', _tee_handler),
        ])
        FLAGS.xenapi_image_service = 'glance'
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_MACHINE,
                         glance_stubs.FakeGlance.IMAGE_KERNEL,
                         glance_stubs.FakeGlance.IMAGE_RAMDISK,
                         check_injection=True)
        self.assertTrue(self._tee_executed)

    def test_spawn_netinject_xenstore(self):
        FLAGS.xenapi_image_service = 'glance'
        db_fakes.stub_out_db_instance_api(self.stubs, injected=True)

        self._tee_executed = False

        def _mount_handler(cmd, *ignore_args, **ignore_kwargs):
            # When mounting, create real files under the mountpoint to simulate
            # files in the mounted filesystem

            # mount point will be the last item of the command list
            self._tmpdir = cmd[len(cmd) - 1]
            LOG.debug(_('Creating files in %s to simulate guest agent' %
                self._tmpdir))
            os.makedirs(os.path.join(self._tmpdir, 'usr', 'sbin'))
            # Touch the file using open
            open(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'), 'w').close()
            return '', ''

        def _umount_handler(cmd, *ignore_args, **ignore_kwargs):
            # Umount would normall make files in the m,ounted filesystem
            # disappear, so do that here
            LOG.debug(_('Removing simulated guest agent files in %s' %
                self._tmpdir))
            os.remove(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'))
            os.rmdir(os.path.join(self._tmpdir, 'usr', 'sbin'))
            os.rmdir(os.path.join(self._tmpdir, 'usr'))
            return '', ''

        def _tee_handler(cmd, *ignore_args, **ignore_kwargs):
            self._tee_executed = True
            return '', ''

        fake_utils.fake_execute_set_repliers([
            (r'(sudo\s+)?mount', _mount_handler),
            (r'(sudo\s+)?umount', _umount_handler),
            (r'(sudo\s+)?tee.*interfaces', _tee_handler)])
        self._test_spawn(1, 2, 3, check_injection=True)

        # tee must not run in this case, where an injection-capable
        # guest agent is detected
        self.assertFalse(self._tee_executed)

    def test_spawn_vlanmanager(self):
        self.flags(xenapi_image_service='glance',
                   network_manager='nova.network.manager.VlanManager',
                   network_driver='nova.network.xenapi_net',
                   vlan_interface='fake0')
        # Reset network table
        xenapi_fake.reset_table('network')
        # Instance id = 2 will use vlan network (see db/fakes.py)
        fake_instance_id = 2
        network_bk = self.network
        # Ensure we use xenapi_net driver
        self.network = utils.import_object(FLAGS.network_manager)
        self.network.setup_compute_network(None, fake_instance_id)
        self._test_spawn(glance_stubs.FakeGlance.IMAGE_MACHINE,
                         glance_stubs.FakeGlance.IMAGE_KERNEL,
                         glance_stubs.FakeGlance.IMAGE_RAMDISK,
                         instance_id=fake_instance_id)
        # TODO(salvatore-orlando): a complete test here would require
        # a check for making sure the bridge for the VM's VIF is
        # consistent with bridge specified in nova db
        self.network = network_bk

    def test_spawn_with_network_qos(self):
        self._create_instance()
        for vif_ref in xenapi_fake.get_all('VIF'):
            vif_rec = xenapi_fake.get_record('VIF', vif_ref)
            self.assertEquals(vif_rec['qos_algorithm_type'], 'ratelimit')
            self.assertEquals(vif_rec['qos_algorithm_params']['kbps'],
                              str(4 * 1024))

    def test_rescue(self):
        self.flags(xenapi_inject_image=False)
        instance = self._create_instance()
        conn = xenapi_conn.get_connection(False)
        conn.rescue(instance, None)

    def test_unrescue(self):
        instance = self._create_instance()
        conn = xenapi_conn.get_connection(False)
        # Ensure that it will not unrescue a non-rescued instance.
        self.assertRaises(Exception, conn.unrescue, instance, None)

    def tearDown(self):
        super(XenAPIVMTestCase, self).tearDown()
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        self.vm_info = None
        self.vm = None
        self.stubs.UnsetAll()

    def _create_instance(self):
        """Creates and spawns a test instance."""
        stubs.stubout_loopingcall_start(self.stubs)
        values = {
            'id': 1,
            'project_id': self.project.id,
            'user_id': self.user.id,
            'image_id': 1,
            'kernel_id': 2,
            'ramdisk_id': 3,
            'instance_type': 'm1.large',
            'mac_address': 'aa:bb:cc:dd:ee:ff',
            'os_type': 'linux'}
        instance = db.instance_create(self.context, values)
        self.conn.spawn(instance)
        return instance


class XenAPIDiffieHellmanTestCase(test.TestCase):
    """Unit tests for Diffie-Hellman code."""
    def setUp(self):
        super(XenAPIDiffieHellmanTestCase, self).setUp()
        self.alice = SimpleDH()
        self.bob = SimpleDH()

    def test_shared(self):
        alice_pub = self.alice.get_public()
        bob_pub = self.bob.get_public()
        alice_shared = self.alice.compute_shared(bob_pub)
        bob_shared = self.bob.compute_shared(alice_pub)
        self.assertEquals(alice_shared, bob_shared)

    def test_encryption(self):
        msg = "This is a top-secret message"
        enc = self.alice.encrypt(msg)
        dec = self.bob.decrypt(enc)
        self.assertEquals(dec, msg)

    def tearDown(self):
        super(XenAPIDiffieHellmanTestCase, self).tearDown()


class XenAPIMigrateInstance(test.TestCase):
    """Unit test for verifying migration-related actions."""

    def setUp(self):
        super(XenAPIMigrateInstance, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        FLAGS.target_host = '127.0.0.1'
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        db_fakes.stub_out_db_instance_api(self.stubs)
        stubs.stub_out_get_target(self.stubs)
        xenapi_fake.reset()
        xenapi_fake.create_network('fake', FLAGS.flat_network_bridge)
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.context = context.RequestContext('fake', 'fake', False)
        self.values = {'id': 1,
                  'project_id': self.project.id,
                  'user_id': self.user.id,
                  'image_id': 1,
                  'kernel_id': None,
                  'ramdisk_id': None,
                  'local_gb': 5,
                  'instance_type': 'm1.large',
                  'mac_address': 'aa:bb:cc:dd:ee:ff',
                  'os_type': 'linux'}

        fake_utils.stub_out_utils_execute(self.stubs)
        stubs.stub_out_migration_methods(self.stubs)
        stubs.stubout_get_this_vm_uuid(self.stubs)
        glance_stubs.stubout_glance_client(self.stubs,
                                           glance_stubs.FakeGlance)

    def tearDown(self):
        super(XenAPIMigrateInstance, self).tearDown()
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        self.stubs.UnsetAll()

    def test_migrate_disk_and_power_off(self):
        instance = db.instance_create(self.context, self.values)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)
        conn = xenapi_conn.get_connection(False)
        conn.migrate_disk_and_power_off(instance, '127.0.0.1')

    def test_finish_resize(self):
        instance = db.instance_create(self.context, self.values)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForMigrationTests)
        stubs.stubout_loopingcall_start(self.stubs)
        conn = xenapi_conn.get_connection(False)
        conn.finish_resize(instance, dict(base_copy='hurr', cow='durr'))


class XenAPIDetermineDiskImageTestCase(test.TestCase):
    """Unit tests for code that detects the ImageType."""
    def setUp(self):
        super(XenAPIDetermineDiskImageTestCase, self).setUp()
        glance_stubs.stubout_glance_client(self.stubs,
                                           glance_stubs.FakeGlance)

        class FakeInstance(object):
            pass

        self.fake_instance = FakeInstance()
        self.fake_instance.id = 42
        self.fake_instance.os_type = 'linux'

    def assert_disk_type(self, disk_type):
        dt = vm_utils.VMHelper.determine_disk_image_type(
            self.fake_instance)
        self.assertEqual(disk_type, dt)

    def test_instance_disk(self):
        """If a kernel is specified, the image type is DISK (aka machine)."""
        FLAGS.xenapi_image_service = 'objectstore'
        self.fake_instance.image_id = glance_stubs.FakeGlance.IMAGE_MACHINE
        self.fake_instance.kernel_id = glance_stubs.FakeGlance.IMAGE_KERNEL
        self.assert_disk_type(vm_utils.ImageType.DISK)

    def test_instance_disk_raw(self):
        """
        If the kernel isn't specified, and we're not using Glance, then
        DISK_RAW is assumed.
        """
        FLAGS.xenapi_image_service = 'objectstore'
        self.fake_instance.image_id = glance_stubs.FakeGlance.IMAGE_RAW
        self.fake_instance.kernel_id = None
        self.assert_disk_type(vm_utils.ImageType.DISK_RAW)

    def test_glance_disk_raw(self):
        """
        If we're using Glance, then defer to the image_type field, which in
        this case will be 'raw'.
        """
        FLAGS.xenapi_image_service = 'glance'
        self.fake_instance.image_id = glance_stubs.FakeGlance.IMAGE_RAW
        self.fake_instance.kernel_id = None
        self.assert_disk_type(vm_utils.ImageType.DISK_RAW)

    def test_glance_disk_vhd(self):
        """
        If we're using Glance, then defer to the image_type field, which in
        this case will be 'vhd'.
        """
        FLAGS.xenapi_image_service = 'glance'
        self.fake_instance.image_id = glance_stubs.FakeGlance.IMAGE_VHD
        self.fake_instance.kernel_id = None
        self.assert_disk_type(vm_utils.ImageType.DISK_VHD)
