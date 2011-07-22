# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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
Test suite for VMWareAPI.
"""

import stubout

from nova import context
from nova import db
from nova import flags
from nova import test
from nova import utils
from nova.compute import power_state
from nova.tests.glance import stubs as glance_stubs
from nova.tests.vmwareapi import db_fakes
from nova.tests.vmwareapi import stubs
from nova.virt import vmwareapi_conn
from nova.virt.vmwareapi import fake as vmwareapi_fake


FLAGS = flags.FLAGS


class VMWareAPIVMTestCase(test.TestCase):
    """Unit tests for Vmware API connection calls."""

    # NOTE(jkoelker): This is leaking stubs into the db module.
    #                 Commenting out until updated for multi-nic.
    #def setUp(self):
    #    super(VMWareAPIVMTestCase, self).setUp()
    #    self.flags(vmwareapi_host_ip='test_url',
    #               vmwareapi_host_username='test_username',
    #               vmwareapi_host_password='test_pass')
    #    self.network = utils.import_object(FLAGS.network_manager)
    #    self.user_id = 'fake'
    #    self.project_id = 'fake'
    #    self.context = context.RequestContext(self.user_id, self.project_id)
    #    vmwareapi_fake.reset()
    #    db_fakes.stub_out_db_instance_api(self.stubs)
    #    stubs.set_stubs(self.stubs)
    #    glance_stubs.stubout_glance_client(self.stubs,
    #                                       glance_stubs.FakeGlance)
    #    self.conn = vmwareapi_conn.get_connection(False)

    #def tearDown(self):
    #    super(VMWareAPIVMTestCase, self).tearDown()
    #    vmwareapi_fake.cleanup()
    #    self.stubs.UnsetAll()

    def _create_instance_in_the_db(self):
        values = {'name': 1,
                  'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_id': "1",
                  'kernel_id': "1",
                  'ramdisk_id': "1",
                  'instance_type': 'm1.large',
                  'mac_address': 'aa:bb:cc:dd:ee:ff',
                  }
        self.instance = db.instance_create(values)

    def _create_vm(self):
        """Create and spawn the VM."""
        self._create_instance_in_the_db()
        self.type_data = db.instance_type_get_by_name(None, 'm1.large')
        self.conn.spawn(self.instance)
        self._check_vm_record()

    def _check_vm_record(self):
        """
        Check if the spawned VM's properties correspond to the instance in
        the db.
        """
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 1)

        # Get Nova record for VM
        vm_info = self.conn.get_info(1)

        # Get record for VM
        vms = vmwareapi_fake._get_objects("VirtualMachine")
        vm = vms[0]

        # Check that m1.large above turned into the right thing.
        mem_kib = long(self.type_data['memory_mb']) << 10
        vcpus = self.type_data['vcpus']
        self.assertEquals(vm_info['max_mem'], mem_kib)
        self.assertEquals(vm_info['mem'], mem_kib)
        self.assertEquals(vm.get("summary.config.numCpu"), vcpus)
        self.assertEquals(vm.get("summary.config.memorySizeMB"),
                          self.type_data['memory_mb'])

        # Check that the VM is running according to Nova
        self.assertEquals(vm_info['state'], power_state.RUNNING)

        # Check that the VM is running according to vSphere API.
        self.assertEquals(vm.get("runtime.powerState"), 'poweredOn')

    def _check_vm_info(self, info, pwr_state=power_state.RUNNING):
        """
        Check if the get_info returned values correspond to the instance
        object in the db.
        """
        mem_kib = long(self.type_data['memory_mb']) << 10
        self.assertEquals(info["state"], pwr_state)
        self.assertEquals(info["max_mem"], mem_kib)
        self.assertEquals(info["mem"], mem_kib)
        self.assertEquals(info["num_cpu"], self.type_data['vcpus'])

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_list_instances(self):
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 0)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_list_instances_1(self):
        self._create_vm()
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 1)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_spawn(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_snapshot(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.snapshot(self.instance, "Test-Snapshot")
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_snapshot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(Exception, self.conn.snapshot, self.instance,
                          "Test-Snapshot")

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_reboot(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.reboot(self.instance)
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_reboot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(Exception, self.conn.reboot, self.instance)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_reboot_not_poweredon(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance, self.dummy_callback_handler)
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.PAUSED)
        self.assertRaises(Exception, self.conn.reboot, self.instance)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_suspend(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance, self.dummy_callback_handler)
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.PAUSED)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_suspend_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(Exception, self.conn.suspend, self.instance,
                          self.dummy_callback_handler)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_resume(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance, self.dummy_callback_handler)
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.PAUSED)
        self.conn.resume(self.instance, self.dummy_callback_handler)
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_resume_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(Exception, self.conn.resume, self.instance,
                          self.dummy_callback_handler)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_resume_not_suspended(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)
        self.assertRaises(Exception, self.conn.resume, self.instance,
                          self.dummy_callback_handler)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_get_info(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_destroy(self):
        self._create_vm()
        info = self.conn.get_info(1)
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 1)
        self.conn.destroy(self.instance)
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 0)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_destroy_non_existent(self):
        self._create_instance_in_the_db()
        self.assertEquals(self.conn.destroy(self.instance), None)

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_pause(self):
        pass

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_unpause(self):
        pass

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_diagnostics(self):
        pass

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_get_console_output(self):
        pass

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def test_get_ajax_console(self):
        pass

    @test.skip_test("DB stubbing not removed, needs updating for multi-nic")
    def dummy_callback_handler(self, ret):
        """
        Dummy callback function to be passed to suspend, resume, etc., calls.
        """
        pass
