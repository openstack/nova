# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova.compute import power_state
from nova.compute import task_states
from nova import context
from nova import db
from nova import exception
from nova import test
import nova.tests.image.fake
from nova.tests import matchers
from nova.tests import utils
from nova.tests.vmwareapi import db_fakes
from nova.tests.vmwareapi import stubs
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import fake as vmwareapi_fake


class VMwareAPIVMTestCase(test.TestCase):
    """Unit tests for Vmware API connection calls."""

    def setUp(self):
        super(VMwareAPIVMTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake', is_admin=False)
        self.flags(vmwareapi_host_ip='test_url',
                   vmwareapi_host_username='test_username',
                   vmwareapi_host_password='test_pass',
                   vnc_enabled=False,
                   use_linked_clone=False)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        vmwareapi_fake.reset()
        db_fakes.stub_out_db_instance_api(self.stubs)
        stubs.set_stubs(self.stubs)
        self.conn = driver.VMwareESXDriver(None, False)
        # NOTE(vish): none of the network plugging code is actually
        #             being tested
        self.network_info = utils.get_test_network_info(legacy_model=False)

        self.image = {
            'id': 'c1c8ce3d-c2e0-4247-890c-ccf5cc1c004c',
            'disk_format': 'vhd',
            'size': 512,
        }
        nova.tests.image.fake.stub_out_image_service(self.stubs)

    def tearDown(self):
        super(VMwareAPIVMTestCase, self).tearDown()
        vmwareapi_fake.cleanup()
        nova.tests.image.fake.FakeImageService_reset()

    def _create_instance_in_the_db(self):
        values = {'name': 1,
                  'id': 1,
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': "1",
                  'kernel_id': "1",
                  'ramdisk_id': "1",
                  'mac_address': "de:ad:be:ef:be:ef",
                  'instance_type': 'm1.large',
                  }
        self.instance = db.instance_create(None, values)

    def _create_vm(self):
        """Create and spawn the VM."""
        self._create_instance_in_the_db()
        self.type_data = db.instance_type_get_by_name(None, 'm1.large')
        self.conn.spawn(self.context, self.instance, self.image,
                        injected_files=[], admin_password=None,
                        network_info=self.network_info,
                        block_device_info=None)
        self._check_vm_record()

    def _check_vm_record(self):
        """
        Check if the spawned VM's properties correspond to the instance in
        the db.
        """
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 1)

        # Get Nova record for VM
        vm_info = self.conn.get_info({'name': 1})

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

    def test_list_instances(self):
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 0)

    def test_list_instances_1(self):
        self._create_vm()
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 1)

    def test_list_interfaces(self):
        self._create_vm()
        interfaces = self.conn.list_interfaces(1)
        self.assertEquals(len(interfaces), 1)
        self.assertEquals(interfaces[0], 4000)

    def test_spawn(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)

    def test_snapshot(self):
        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.snapshot(self.context, self.instance, "Test-Snapshot",
                           func_call_matcher.call)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.assertIsNone(func_call_matcher.match())

    def test_snapshot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.snapshot,
                          self.context, self.instance, "Test-Snapshot",
                          lambda *args, **kwargs: None)

    def test_reboot(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        reboot_type = "SOFT"
        self.conn.reboot(self.context, self.instance, self.network_info,
                         reboot_type)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)

    def test_reboot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.reboot,
                          self.context, self.instance, self.network_info,
                          'SOFT')

    def test_reboot_not_poweredon(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.assertRaises(exception.InstanceRebootFailure, self.conn.reboot,
                          self.context, self.instance, self.network_info,
                          'SOFT')

    def test_suspend(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.SUSPENDED)

    def test_suspend_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.suspend,
                          self.instance)

    def test_resume(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.conn.resume(self.instance, self.network_info)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)

    def test_resume_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.resume,
                          self.instance, self.network_info)

    def test_resume_not_suspended(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.assertRaises(exception.InstanceResumeFailure, self.conn.resume,
                          self.instance, self.network_info)

    def test_power_on(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.SHUTDOWN)
        self.conn.power_on(self.instance)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)

    def test_power_on_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_on,
                          self.instance)

    def test_power_off(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.SHUTDOWN)

    def test_power_off_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_off,
                          self.instance)

    def test_power_off_suspended(self):
        self._create_vm()
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.assertRaises(exception.InstancePowerOffFailure,
                          self.conn.power_off, self.instance)

    def test_get_info(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)

    def test_destroy(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1})
        self._check_vm_info(info, power_state.RUNNING)
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 1)
        self.conn.destroy(self.instance, self.network_info)
        instances = self.conn.list_instances()
        self.assertEquals(len(instances), 0)

    def test_destroy_non_existent(self):
        self._create_instance_in_the_db()
        self.assertEquals(self.conn.destroy(self.instance, self.network_info),
                          None)

    def test_pause(self):
        pass

    def test_unpause(self):
        pass

    def test_diagnostics(self):
        pass

    def test_get_console_output(self):
        pass


class VMwareAPIHostTestCase(test.TestCase):
    """Unit tests for Vmware API host calls."""

    def setUp(self):
        super(VMwareAPIHostTestCase, self).setUp()
        self.flags(vmwareapi_host_ip='test_url',
                   vmwareapi_host_username='test_username',
                   vmwareapi_host_password='test_pass')
        vmwareapi_fake.reset()
        stubs.set_stubs(self.stubs)
        self.conn = driver.VMwareESXDriver(False)

    def tearDown(self):
        super(VMwareAPIHostTestCase, self).tearDown()
        vmwareapi_fake.cleanup()

    def test_host_state(self):
        stats = self.conn.get_host_stats()
        self.assertEquals(stats['vcpus'], 16)
        self.assertEquals(stats['disk_total'], 1024)
        self.assertEquals(stats['disk_available'], 500)
        self.assertEquals(stats['disk_used'], 1024 - 500)
        self.assertEquals(stats['host_memory_total'], 1024)
        self.assertEquals(stats['host_memory_free'], 1024 - 500)

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
