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

"""
Test suite for XenAPI
"""

import os
import re
import stubout

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
from nova.virt.xenapi.vmops import SimpleDH
from nova.virt.xenapi.vmops import VMOps
from nova.tests.db import fakes as db_fakes
from nova.tests.xenapi import stubs
from nova.tests.glance import stubs as glance_stubs
from nova.tests import fake_utils

LOG = logging.getLogger('nova.tests.test_xenapi')

FLAGS = flags.FLAGS


class XenAPIVolumeTestCase(test.TestCase):
    """
    Unit tests for Volume operations
    """
    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        FLAGS.target_host = '127.0.0.1'
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        db_fakes.stub_out_db_instance_api(self.stubs)
        db_fakes.stub_out_db_network_api(self.stubs)
        stubs.stub_out_get_target(self.stubs)
        xenapi_fake.reset()
        self.values = {'name': 1, 'id': 1,
                  'project_id': 'fake',
                  'user_id': 'fake',
                  'image_id': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'instance_type': 'm1.large',
                  'mac_address': 'aa:bb:cc:dd:ee:ff',
                  }

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
        return db.volume_create(context.get_admin_context(), vol)

    def test_create_iscsi_storage(self):
        """ This shows how to test helper classes' methods """
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
        """ This shows how to test helper classes' methods """
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
        """ This shows how to test Ops classes' methods """
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.values)
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
        """ This shows how to test when exceptions are raised """
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForVolumeFailedTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.values)
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
    """
    Unit tests for VM operations
    """
    def setUp(self):
        super(XenAPIVMTestCase, self).setUp()
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake',
                                             admin=True)
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.network = utils.import_object(FLAGS.network_manager)
        self.stubs = stubout.StubOutForTesting()
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        xenapi_fake.reset()
        xenapi_fake.create_local_srs()
        db_fakes.stub_out_db_instance_api(self.stubs)
        db_fakes.stub_out_db_network_api(self.stubs)
        xenapi_fake.create_network('fake', FLAGS.flat_network_bridge)
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        stubs.stubout_get_this_vm_uuid(self.stubs)
        stubs.stubout_stream_disk(self.stubs)
        stubs.stubout_is_vdi_pv(self.stubs)
        self.stubs.Set(VMOps, 'reset_network', reset_network)
        glance_stubs.stubout_glance_client(self.stubs,
                                           glance_stubs.FakeGlance)
        fake_utils.stub_out_utils_execute(self.stubs)
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

            self.assertEquals(vm_labels, [1])

        def ensure_vbd_was_torn_down():
            vbd_labels = []
            for vbd_ref in xenapi_fake.get_all('VBD'):
                vbd_rec = xenapi_fake.get_record('VBD', vbd_ref)
                vbd_labels.append(vbd_rec["vm_name_label"])

            self.assertEquals(vbd_labels, [1])

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

    def check_vm_record(self, conn, check_injection=False):
        instances = conn.list_instances()
        self.assertEquals(instances, [1])

        # Get Nova record for VM
        vm_info = conn.get_info(1)

        # Get XenAPI record for VM
        vms = [(ref, rec) for ref, rec
               in xenapi_fake.get_all_records('VM').iteritems()
               if not rec['is_control_domain']]
        vm_ref, vm = vms[0]

        # Check that m1.large above turned into the right thing.
        instance_type = instance_types.INSTANCE_TYPES['m1.large']
        mem_kib = long(instance_type['memory_mb']) << 10
        mem_bytes = str(mem_kib << 10)
        vcpus = instance_type['vcpus']
        self.assertEquals(vm_info['max_mem'], mem_kib)
        self.assertEquals(vm_info['mem'], mem_kib)
        self.assertEquals(vm['memory_static_max'], mem_bytes)
        self.assertEquals(vm['memory_dynamic_max'], mem_bytes)
        self.assertEquals(vm['memory_dynamic_min'], mem_bytes)
        self.assertEquals(vm['VCPUs_max'], str(vcpus))
        self.assertEquals(vm['VCPUs_at_startup'], str(vcpus))

        # Check that the VM is running according to Nova
        self.assertEquals(vm_info['state'], power_state.RUNNING)

        # Check that the VM is running according to XenAPI.
        self.assertEquals(vm['power_state'], 'Running')

        if check_injection:
            xenstore_data = xenapi_fake.VM_get_xenstore_data(vm_ref)
            key = 'vm-data/networking/aabbccddeeff'
            LOG.debug("Xenstore data: %s",xenstore_data)
            xenstore_value=xenstore_data[key]
            #tcpip_data = dict([(k, v)
            #    for k, v in xenstore_value.iteritems()
            #    if k.startswith(key_prefix)])
            #LOG.debug("tcpip data: %s",tcpip_data)
            #self.assertEquals(tcpip_data['label'],'test_network')
            #self.assertEquals(tcpip_data, {
            #    'label': 'test_network',
            #    'broadcast': '10.0.0.255',
            #    'ips': [{'ip': '10.0.0.3', 'netmask':'255.255.255.0', 'enabled':'1'}],
            #    'mac': 'aa:bb:cc:dd:ee:ff',
            #    'dns': ['10.0.0.2'],
            #    'gateway': '10.0.0.1'})

    def _test_spawn(self, image_id, kernel_id, ramdisk_id,
        instance_type="m1.large", check_injection=False):

        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        values = {'name': 1,
                  'id': 1,
                  'project_id': self.project.id,
                  'user_id': self.user.id,
                  'image_id': image_id,
                  'kernel_id': kernel_id,
                  'ramdisk_id': ramdisk_id,
                  'instance_type': instance_type,
                  'mac_address': 'aa:bb:cc:dd:ee:ff',
                  }
        conn = xenapi_conn.get_connection(False)
        instance = db.instance_create(values)
        conn.spawn(instance)
        self.check_vm_record(conn, check_injection=check_injection)

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

    def test_spawn_raw_glance(self):
        FLAGS.xenapi_image_service = 'glance'
        self._test_spawn(1, None, None)

    def test_spawn_glance(self):
        FLAGS.xenapi_image_service = 'glance'
        self._test_spawn(1, 2, 3)

    def test_spawn_netinject_file(self):
        FLAGS.xenapi_image_service = 'glance'
        db_fakes.stub_out_db_network_api(self.stubs, injected=True)

        self._tee_executed = False

        def _tee_handler(cmd, input, *ignore_args):
            self.assertNotEqual(input, None)

            config = [line.strip() for line in input.split("\n")]

            # Find the start of eth0 configuration and check it
            index = config.index('auto eth0')
            LOG.debug("CONFIG")
            LOG.debug(config)
            
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
        self._test_spawn(1, 2, 3, check_injection=True)
        self.assertTrue(self._tee_executed)

    def test_spawn_netinject_xenstore(self):
        FLAGS.xenapi_image_service = 'glance'
        db_fakes.stub_out_db_network_api(self.stubs, injected=True)

        self._tee_executed = False

        def _mount_handler(cmd, *ignore_args):
            # When mounting, create real files under the mountpoint to simulate
            # files in the mounted filesystem

            # RegExp extracts the path of the mountpoint
            match = re.match(r'(sudo\s+)?mount[^"]*"[^"]*"\s+"([^"]*)"', cmd)
            self._tmpdir = match.group(2)
            LOG.debug(_('Creating files in %s to simulate guest agent' %
                self._tmpdir))
            os.makedirs(os.path.join(self._tmpdir, 'usr', 'sbin'))
            # Touch the file using open
            open(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'), 'w').close()
            return '', ''

        def _umount_handler(cmd, *ignore_args):
            # Umount would normall make files in the m,ounted filesystem
            # disappear, so do that here
            LOG.debug(_('Removing simulated guest agent files in %s' %
                self._tmpdir))
            os.remove(os.path.join(self._tmpdir, 'usr', 'sbin',
                'xe-update-networking'))
            os.rmdir(os.path.join(self._tmpdir, 'usr', 'sbin'))
            os.rmdir(os.path.join(self._tmpdir, 'usr'))
            return '', ''

        def _tee_handler(cmd, input, *ignore_args):
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

    def tearDown(self):
        super(XenAPIVMTestCase, self).tearDown()
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        self.stubs.UnsetAll()

    def _create_instance(self):
        """Creates and spawns a test instance"""
        values = {
            'name': 1,
            'id': 1,
            'project_id': self.project.id,
            'user_id': self.user.id,
            'image_id': 1,
            'kernel_id': 2,
            'ramdisk_id': 3,
            'instance_type': 'm1.large',
            'mac_address': 'aa:bb:cc:dd:ee:ff'}
        instance = db.instance_create(values)
        self.conn.spawn(instance)
        return instance


class XenAPIDiffieHellmanTestCase(test.TestCase):
    """
    Unit tests for Diffie-Hellman code
    """
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
