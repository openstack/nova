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
import urllib2

import mox
from oslo.config import cfg

from nova.compute import power_state
from nova.compute import task_states
from nova import context
from nova import db
from nova import exception
from nova import test
import nova.tests.image.fake
from nova.tests import matchers
from nova.tests import utils
from nova.tests.virt.vmwareapi import db_fakes
from nova.tests.virt.vmwareapi import stubs
from nova.virt import fake
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi import vmops


class fake_vm_ref(object):
    def __init__(self):
        self.value = 4
        self._type = 'VirtualMachine'


class fake_http_resp(object):
    def __init__(self):
        self.code = 200

    def read(self):
        return "console log"


class VMwareAPIConfTestCase(test.TestCase):
    """Unit tests for VMWare API configurations."""
    def setUp(self):
        super(VMwareAPIConfTestCase, self).setUp()

    def tearDown(self):
        super(VMwareAPIConfTestCase, self).tearDown()

    def test_configure_without_wsdl_loc_override(self):
        # Test the default configuration behavior. By default,
        # use the WSDL sitting on the host we are talking to in
        # order to bind the SOAP client.
        wsdl_loc = cfg.CONF.vmwareapi_wsdl_loc
        self.assertIsNone(wsdl_loc)
        wsdl_url = vim.Vim.get_wsdl_url("https", "www.example.com")
        url = vim.Vim.get_soap_url("https", "www.example.com")
        self.assertEqual("https://www.example.com/sdk/vimService.wsdl",
                         wsdl_url)
        self.assertEqual("https://www.example.com/sdk", url)

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
        self.flags(vmwareapi_wsdl_loc=fake_wsdl)
        wsdl_loc = cfg.CONF.vmwareapi_wsdl_loc
        self.assertIsNotNone(wsdl_loc)
        self.assertEqual(fake_wsdl, wsdl_loc)
        wsdl_url = vim.Vim.get_wsdl_url("https", "www.example.com")
        url = vim.Vim.get_soap_url("https", "www.example.com")
        self.assertEqual(fake_wsdl, wsdl_url)
        self.assertEqual("https://www.example.com/sdk", url)


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
        self.node_name = 'test_url'
        self.context = context.RequestContext(self.user_id, self.project_id)
        vmwareapi_fake.reset()
        db_fakes.stub_out_db_instance_api(self.stubs)
        stubs.set_stubs(self.stubs)
        self.conn = driver.VMwareVCDriver(fake.FakeVirtAPI)
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
                  'uuid': "fake-uuid",
                  'project_id': self.project_id,
                  'user_id': self.user_id,
                  'image_ref': "1",
                  'kernel_id': "1",
                  'ramdisk_id': "1",
                  'mac_address': "de:ad:be:ef:be:ef",
                  'instance_type': 'm1.large',
                  'node': self.node_name,
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
        vm_info = self.conn.get_info({'uuid': 'fake-uuid',
                                      'name': 1})

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

        self.assertEqual(
            vm.get("config.hardware.device")[2].device.obj_name,
            "ns0:VirtualE1000")
        # Check that the VM is running according to Nova
        self.assertEquals(vm_info['state'], power_state.RUNNING)

        # Check that the VM is running according to vSphere API.
        self.assertEquals(vm.get("runtime.powerState"), 'poweredOn')

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

    def test_spawn(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
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
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.snapshot(self.context, self.instance, "Test-Snapshot",
                           func_call_matcher.call)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        self.assertIsNone(func_call_matcher.match())

    def test_snapshot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.snapshot,
                          self.context, self.instance, "Test-Snapshot",
                          lambda *args, **kwargs: None)

    def test_reboot(self):
        self._create_vm()
        info = self.conn.get_info({'name': 1, 'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        reboot_type = "SOFT"
        self.conn.reboot(self.context, self.instance, self.network_info,
                         reboot_type)
        info = self.conn.get_info({'name': 1, 'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)

    def test_reboot_with_uuid(self):
        """Test fall back to use name when can't find by uuid."""
        self._create_vm()
        info = self.conn.get_info({'name': 'fake-uuid', 'uuid': 'wrong-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        reboot_type = "SOFT"
        self.conn.reboot(self.context, self.instance, self.network_info,
                         reboot_type)
        info = self.conn.get_info({'name': 'fake-uuid', 'uuid': 'wrong-uuid'})
        self._check_vm_info(info, power_state.RUNNING)

    def test_reboot_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.reboot,
                          self.context, self.instance, self.network_info,
                          'SOFT')

    def test_reboot_not_poweredon(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.assertRaises(exception.InstanceRebootFailure, self.conn.reboot,
                          self.context, self.instance, self.network_info,
                          'SOFT')

    def test_suspend(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': "fake-uuid"})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.SUSPENDED)

    def test_suspend_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.suspend,
                          self.instance)

    def test_resume(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.conn.resume(self.instance, self.network_info)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)

    def test_resume_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.resume,
                          self.instance, self.network_info)

    def test_resume_not_suspended(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        self.assertRaises(exception.InstanceResumeFailure, self.conn.resume,
                          self.instance, self.network_info)

    def test_power_on(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.SHUTDOWN)
        self.conn.power_on(self.context, self.instance, self.network_info)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)

    def test_power_on_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_on,
                          self.context, self.instance, self.network_info)

    def test_power_off(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)
        self.conn.power_off(self.instance)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.SHUTDOWN)

    def test_power_off_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound, self.conn.power_off,
                          self.instance)

    def test_power_off_suspended(self):
        self._create_vm()
        self.conn.suspend(self.instance)
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.SUSPENDED)
        self.assertRaises(exception.InstancePowerOffFailure,
                          self.conn.power_off, self.instance)

    def test_get_info(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
        self._check_vm_info(info, power_state.RUNNING)

    def test_destroy(self):
        self._create_vm()
        info = self.conn.get_info({'uuid': 'fake-uuid'})
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
        vm_ref = fake_vm_ref()
        result = fake_http_resp()
        self._create_instance_in_the_db()
        self.mox.StubOutWithMock(vm_util, 'get_vm_ref_from_name')
        self.mox.StubOutWithMock(urllib2, 'urlopen')
        vm_util.get_vm_ref_from_name(mox.IgnoreArg(), self.instance['name']).\
        AndReturn(vm_ref)
        urllib2.urlopen(mox.IgnoreArg()).AndReturn(result)

        self.mox.ReplayAll()
        self.conn.get_console_output(self.instance)

    def _test_finish_migration(self, power_on):
        """
        Tests the finish_migration method on vmops via the
        VMwareVCDriver. Results are checked against whether or not
        the underlying instance should have been powered on.
        """

        self.power_on_called = False

        def fake_power_on(instance):
            self.assertEquals(self.instance, instance)
            self.power_on_called = True

        def fake_vmops_update_instance_progress(context, instance, step,
                                                total_steps):
            self.assertEquals(self.context, context)
            self.assertEquals(self.instance, instance)
            self.assertEquals(4, step)
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
                                   image_meta=None,
                                   power_on=power_on)
        # verify the results
        self.assertEquals(power_on, self.power_on_called)

    def test_finish_migration_power_on(self):
        self._test_finish_migration(power_on=True)

    def test_finish_migration_power_off(self):
        self._test_finish_migration(power_on=False)

    def _test_finish_revert_migration(self, power_on):
        """
        Tests the finish_revert_migration method on vmops via the
        VMwareVCDriver. Results are checked against whether or not
        the underlying instance should have been powered on.
        """

        # setup the test instance in the database
        self._create_vm()

        self.power_on_called = False
        self.vm_name = str(self.instance['name']) + '-orig'

        def fake_power_on(instance):
            self.assertEquals(self.instance, instance)
            self.power_on_called = True

        def fake_get_orig_vm_name_label(instance):
            self.assertEquals(self.instance, instance)
            return self.vm_name

        def fake_get_vm_ref_from_name(session, vm_name):
            self.assertEquals(self.vm_name, vm_name)
            return vmwareapi_fake._get_objects("VirtualMachine")[0]

        def fake_get_vm_ref_from_uuid(session, vm_uuid):
            return vmwareapi_fake._get_objects("VirtualMachine")[0]

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
        self.conn.finish_revert_migration(instance=self.instance,
                                          network_info=None,
                                          power_on=power_on)
        # verify the results
        self.assertEquals(power_on, self.power_on_called)

    def test_finish_revert_migration_power_on(self):
        self._test_finish_revert_migration(power_on=True)

    def test_finish_revert_migration_power_off(self):
        self._test_finish_revert_migration(power_on=False)

    def test_diagnostics_non_existent_vm(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound,
                          self.conn.get_diagnostics,
                          self.instance)

    def test_get_console_pool_info(self):
        info = self.conn.get_console_pool_info("console_type")
        self.assertEquals(info['address'], 'test_url')
        self.assertEquals(info['username'], 'test_username')
        self.assertEquals(info['password'], 'test_pass')

    def test_get_vnc_console_non_existent(self):
        self._create_instance_in_the_db()
        self.assertRaises(exception.InstanceNotFound,
                          self.conn.get_vnc_console,
                          self.instance)

    def test_get_vnc_console(self):
        self._create_instance_in_the_db()
        self._create_vm()
        vnc_dict = self.conn.get_vnc_console(self.instance)
        self.assertEquals(vnc_dict['host'], "ha-host")
        self.assertEquals(vnc_dict['port'], 5910)

    def test_host_ip_addr(self):
        self.assertEquals(self.conn.get_host_ip_addr(), "test_url")

    def test_get_volume_connector(self):
        self._create_instance_in_the_db()
        connector_dict = self.conn.get_volume_connector(self.instance)
        self.assertEquals(connector_dict['ip'], "test_url")
        self.assertEquals(connector_dict['initiator'], "iscsi-name")
        self.assertEquals(connector_dict['host'], "test_url")


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
        supported_instances = [('i686', 'vmware', 'hvm'),
                               ('x86_64', 'vmware', 'hvm')]
        self.assertEquals(stats['supported_instances'], supported_instances)

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


class VMwareAPIVCDriverTestCase(VMwareAPIVMTestCase):

    def setUp(self):
        super(VMwareAPIVCDriverTestCase, self).setUp()
        self.flags(
                   vmwareapi_cluster_name='test_cluster',
                   vmwareapi_task_poll_interval=10,
                   vnc_enabled=False
                   )
        self.conn = driver.VMwareVCDriver(None, False)

    def tearDown(self):
        super(VMwareAPIVCDriverTestCase, self).tearDown()
        vmwareapi_fake.cleanup()

    def test_get_available_resource(self):
        stats = self.conn.get_available_resource(self.node_name)
        self.assertEquals(stats['vcpus'], 16)
        self.assertEquals(stats['local_gb'], 1024)
        self.assertEquals(stats['local_gb_used'], 1024 - 500)
        self.assertEquals(stats['memory_mb'], 1024)
        self.assertEquals(stats['memory_mb_used'], 1024 - 524)
        self.assertEquals(stats['hypervisor_type'], 'VMware ESXi')
        self.assertEquals(stats['hypervisor_version'], '5.0.0')
        self.assertEquals(stats['hypervisor_hostname'], 'test_url')
