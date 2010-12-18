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

import stubout

from nova import db
from nova import context
from nova import flags
from nova import test
from nova import utils
from nova.auth import manager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import volume_utils
from nova.tests.db import fakes
from nova.tests.xenapi import stubs

FLAGS = flags.FLAGS


class XenAPIVolumeTestCase(test.TrialTestCase):
    """
    Unit tests for Volume operations
    """
    def setUp(self):
        super(XenAPIVolumeTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        FLAGS.target_host = '127.0.0.1'
        FLAGS.xenapi_connection_url = 'test_url'
        FLAGS.xenapi_connection_password = 'test_pass'
        fakes.stub_out_db_instance_api(self.stubs)
        fake.reset()
        self.values = {'name': 1,
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
        info = helper.parse_volume_info(vol['ec2_id'], '/dev/sdc')
        label = 'SR-%s' % vol['ec2_id']
        description = 'Test-SR'
        sr_ref = helper.create_iscsi_storage(session, info, label, description)
        srs = fake.get_all('SR')
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
                          vol['ec2_id'],
                          '/dev/sd')
        db.volume_destroy(context.get_admin_context(), vol['id'])

    def test_attach_volume(self):
        """ This shows how to test Ops classes' methods """
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVolumeTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.values)
        fake.create_vm(instance.name, 'Running')
        result = conn.attach_volume(instance.name, volume['ec2_id'],
                                    '/dev/sdc')

        def check():
            # check that the VM has a VBD attached to it
            # Get XenAPI reference for the VM
            vms = fake.get_all('VM')
            # Get XenAPI record for VBD
            vbds = fake.get_all('VBD')
            vbd = fake.get_record('VBD', vbds[0])
            vm_ref = vbd['VM']
            self.assertEqual(vm_ref, vms[0])

        check()

    def test_attach_volume_raise_exception(self):
        """ This shows how to test when exceptions are raised """
        stubs.stubout_session(self.stubs,
                              stubs.FakeSessionForVolumeFailedTests)
        conn = xenapi_conn.get_connection(False)
        volume = self._create_volume()
        instance = db.instance_create(self.values)
        fake.create_vm(instance.name, 'Running')
        self.assertRaises(Exception,
                          conn.attach_volume,
                          instance.name,
                          volume['ec2_id'],
                          '/dev/sdc')

    def tearDown(self):
        super(XenAPIVolumeTestCase, self).tearDown()
        self.stubs.UnsetAll()


class XenAPIVMTestCase(test.TrialTestCase):
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
        fake.reset()
        fakes.stub_out_db_instance_api(self.stubs)
        fake.create_network('fake', FLAGS.flat_network_bridge)

    def test_list_instances_0(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        conn = xenapi_conn.get_connection(False)
        instances = conn.list_instances()
        self.assertEquals(instances, [])

    def test_spawn(self):
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        values = {'name': 1,
                  'project_id': self.project.id,
                  'user_id': self.user.id,
                  'image_id': 1,
                  'kernel_id': 2,
                  'ramdisk_id': 3,
                  'instance_type': 'm1.large',
                  'mac_address': 'aa:bb:cc:dd:ee:ff',
                  }
        conn = xenapi_conn.get_connection(False)
        instance = db.instance_create(values)
        conn.spawn(instance)

        def check():
            instances = conn.list_instances()
            self.assertEquals(instances, [1])

            # Get Nova record for VM
            vm_info = conn.get_info(1)

            # Get XenAPI record for VM
            vms = fake.get_all('VM')
            vm = fake.get_record('VM', vms[0])

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

        check()

    def tearDown(self):
        super(XenAPIVMTestCase, self).tearDown()
        self.manager.delete_project(self.project)
        self.manager.delete_user(self.user)
        self.stubs.UnsetAll()
