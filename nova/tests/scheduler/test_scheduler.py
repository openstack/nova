# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""
Tests For Scheduler
"""

import mox

from nova.compute import api as compute_api
from nova.compute import instance_types
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import api as conductor_api
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova.openstack.common import jsonutils
from nova.openstack.common.notifier import api as notifier
from nova.openstack.common import rpc
from nova.scheduler import driver
from nova.scheduler import manager
from nova import servicegroup
from nova import test
from nova.tests import fake_instance_actions
from nova.tests.image import fake as fake_image
from nova.tests import matchers
from nova.tests.scheduler import fakes
from nova import utils


class SchedulerManagerTestCase(test.TestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager
    driver_cls = driver.Scheduler
    driver_cls_name = 'nova.scheduler.driver.Scheduler'

    def setUp(self):
        super(SchedulerManagerTestCase, self).setUp()
        self.flags(scheduler_driver=self.driver_cls_name)
        self.stubs.Set(compute_api, 'API', fakes.FakeComputeAPI)
        self.manager = self.manager_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.fake_args = (1, 2, 3)
        self.fake_kwargs = {'cat': 'meow', 'dog': 'woof'}
        fake_instance_actions.stub_out_action_events(self.stubs)

    def test_1_correct_init(self):
        # Correct scheduler driver
        manager = self.manager
        self.assertTrue(isinstance(manager.driver, self.driver_cls))

    def test_update_service_capabilities(self):
        service_name = 'fake_service'
        host = 'fake_host'

        self.mox.StubOutWithMock(self.manager.driver,
                'update_service_capabilities')

        # Test no capabilities passes empty dictionary
        self.manager.driver.update_service_capabilities(service_name,
                host, {})
        self.mox.ReplayAll()
        result = self.manager.update_service_capabilities(self.context,
                service_name=service_name, host=host, capabilities={})
        self.mox.VerifyAll()

        self.mox.ResetAll()
        # Test capabilities passes correctly
        capabilities = {'fake_capability': 'fake_value'}
        self.manager.driver.update_service_capabilities(
                service_name, host, capabilities)
        self.mox.ReplayAll()
        result = self.manager.update_service_capabilities(self.context,
                service_name=service_name, host=host,
                capabilities=capabilities)

    def test_update_service_multiple_capabilities(self):
        service_name = 'fake_service'
        host = 'fake_host'

        self.mox.StubOutWithMock(self.manager.driver,
                                 'update_service_capabilities')

        capab1 = {'fake_capability': 'fake_value1'},
        capab2 = {'fake_capability': 'fake_value2'},
        capab3 = None
        self.manager.driver.update_service_capabilities(
                service_name, host, capab1)
        self.manager.driver.update_service_capabilities(
                service_name, host, capab2)
        # None is converted to {}
        self.manager.driver.update_service_capabilities(
                service_name, host, {})
        self.mox.ReplayAll()
        self.manager.update_service_capabilities(self.context,
                service_name=service_name, host=host,
                capabilities=[capab1, capab2, capab3])

    def test_show_host_resources(self):
        host = 'fake_host'

        compute_node = {'host': host,
                        'compute_node': [{'vcpus': 4,
                                          'vcpus_used': 2,
                                          'memory_mb': 1024,
                                          'memory_mb_used': 512,
                                          'local_gb': 1024,
                                          'local_gb_used': 512}]}
        instances = [{'project_id': 'project1',
                      'vcpus': 1,
                      'memory_mb': 128,
                      'root_gb': 128,
                      'ephemeral_gb': 0},
                     {'project_id': 'project1',
                      'vcpus': 2,
                      'memory_mb': 256,
                      'root_gb': 384,
                      'ephemeral_gb': 0},
                     {'project_id': 'project2',
                      'vcpus': 2,
                      'memory_mb': 256,
                      'root_gb': 256,
                      'ephemeral_gb': 0}]

        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')

        db.service_get_by_compute_host(self.context, host).AndReturn(
                compute_node)
        db.instance_get_all_by_host(self.context, host).AndReturn(instances)

        self.mox.ReplayAll()
        result = self.manager.show_host_resources(self.context, host)
        expected = {'usage': {'project1': {'memory_mb': 384,
                                           'vcpus': 3,
                                           'root_gb': 512,
                                           'ephemeral_gb': 0},
                              'project2': {'memory_mb': 256,
                                           'vcpus': 2,
                                           'root_gb': 256,
                                           'ephemeral_gb': 0}},
                    'resource': {'vcpus': 4,
                                 'vcpus_used': 2,
                                 'local_gb': 1024,
                                 'local_gb_used': 512,
                                 'memory_mb': 1024,
                                 'memory_mb_used': 512}}
        self.assertThat(result, matchers.DictMatches(expected))

    def _mox_schedule_method_helper(self, method_name):
        # Make sure the method exists that we're going to test call
        def stub_method(*args, **kwargs):
            pass

        setattr(self.manager.driver, method_name, stub_method)

        self.mox.StubOutWithMock(self.manager.driver,
                method_name)

    def test_run_instance_exception_puts_instance_in_error_state(self):
        fake_instance_uuid = 'fake-instance-id'
        inst = {"vm_state": "", "task_state": ""}

        self._mox_schedule_method_helper('schedule_run_instance')
        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        request_spec = {'instance_properties': inst,
                        'instance_uuids': [fake_instance_uuid]}

        self.manager.driver.schedule_run_instance(self.context,
                request_spec, None, None, None, None, {}).AndRaise(
                        exception.NoValidHost(reason=""))
        old, new_ref = db.instance_update_and_get_original(self.context,
                fake_instance_uuid,
                {"vm_state": vm_states.ERROR,
                 "task_state": None}).AndReturn((inst, inst))
        compute_utils.add_instance_fault_from_exc(self.context,
                mox.IsA(conductor_api.LocalAPI), new_ref,
                mox.IsA(exception.NoValidHost), mox.IgnoreArg())

        self.mox.ReplayAll()
        self.manager.run_instance(self.context, request_spec,
                None, None, None, None, {})

    def test_live_migration_schedule_novalidhost(self):
        inst = {"uuid": "fake-instance-id",
                "vm_state": vm_states.ACTIVE,
                "task_state": task_states.MIGRATING, }

        dest = None
        block_migration = False
        disk_over_commit = False

        self._mox_schedule_method_helper('schedule_live_migration')
        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.manager.driver.schedule_live_migration(self.context,
                    inst, dest, block_migration, disk_over_commit).AndRaise(
                    exception.NoValidHost(reason=""))
        db.instance_update_and_get_original(self.context, inst["uuid"],
                                {"vm_state": inst['vm_state'],
                                 "task_state": None,
                                 "expected_task_state": task_states.MIGRATING,
                                }).AndReturn((inst, inst))
        compute_utils.add_instance_fault_from_exc(self.context,
                                mox.IsA(conductor_api.LocalAPI), inst,
                                mox.IsA(exception.NoValidHost),
                                mox.IgnoreArg())

        self.mox.ReplayAll()
        self.assertRaises(exception.NoValidHost,
                          self.manager.live_migration,
                          self.context, inst, dest, block_migration,
                          disk_over_commit)

    def test_live_migration_compute_service_notavailable(self):
        inst = {"uuid": "fake-instance-id",
                "vm_state": vm_states.ACTIVE,
                "task_state": task_states.MIGRATING, }

        dest = 'fake_host'
        block_migration = False
        disk_over_commit = False

        self._mox_schedule_method_helper('schedule_live_migration')
        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        self.manager.driver.schedule_live_migration(self.context,
                    inst, dest, block_migration, disk_over_commit).AndRaise(
                    exception.ComputeServiceUnavailable(host="src"))
        db.instance_update_and_get_original(self.context, inst["uuid"],
                                {"vm_state": inst['vm_state'],
                                 "task_state": None,
                                 "expected_task_state": task_states.MIGRATING,
                                }).AndReturn((inst, inst))
        compute_utils.add_instance_fault_from_exc(self.context,
                                mox.IsA(conductor_api.LocalAPI), inst,
                                mox.IsA(exception.ComputeServiceUnavailable),
                                mox.IgnoreArg())

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
                          self.manager.live_migration,
                          self.context, inst, dest, block_migration,
                          disk_over_commit)

    def test_prep_resize_no_valid_host_back_in_active_state(self):
        fake_instance_uuid = 'fake-instance-id'
        fake_instance = {'uuid': fake_instance_uuid}
        inst = {"vm_state": "", "task_state": ""}

        self._mox_schedule_method_helper('schedule_prep_resize')

        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        request_spec = {'instance_type': 'fake_type',
                        'instance_uuids': [fake_instance_uuid],
                        'instance_properties': {'uuid': fake_instance_uuid}}
        kwargs = {
                'context': self.context,
                'image': 'fake_image',
                'request_spec': request_spec,
                'filter_properties': 'fake_props',
                'instance': fake_instance,
                'instance_type': 'fake_type',
                'reservations': list('fake_res'),
        }
        self.manager.driver.schedule_prep_resize(**kwargs).AndRaise(
                exception.NoValidHost(reason=""))
        old_ref, new_ref = db.instance_update_and_get_original(self.context,
                fake_instance_uuid,
                {"vm_state": vm_states.ACTIVE, "task_state": None}).AndReturn(
                        (inst, inst))
        compute_utils.add_instance_fault_from_exc(self.context,
                mox.IsA(conductor_api.LocalAPI), new_ref,
                mox.IsA(exception.NoValidHost), mox.IgnoreArg())

        self.mox.ReplayAll()
        self.manager.prep_resize(**kwargs)

    def test_prep_resize_exception_host_in_error_state_and_raise(self):
        fake_instance_uuid = 'fake-instance-id'
        fake_instance = {'uuid': fake_instance_uuid}

        self._mox_schedule_method_helper('schedule_prep_resize')

        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')

        request_spec = {'instance_properties':
                {'uuid': fake_instance_uuid}}
        kwargs = {
                'context': self.context,
                'image': 'fake_image',
                'request_spec': request_spec,
                'filter_properties': 'fake_props',
                'instance': fake_instance,
                'instance_type': 'fake_type',
                'reservations': list('fake_res'),
        }

        self.manager.driver.schedule_prep_resize(**kwargs).AndRaise(
                test.TestingException('something happened'))

        inst = {
            "vm_state": "",
            "task_state": "",
        }
        old_ref, new_ref = db.instance_update_and_get_original(self.context,
                fake_instance_uuid,
                {"vm_state": vm_states.ERROR,
                 "task_state": None}).AndReturn((inst, inst))
        compute_utils.add_instance_fault_from_exc(self.context,
                mox.IsA(conductor_api.LocalAPI), new_ref,
                mox.IsA(test.TestingException), mox.IgnoreArg())

        self.mox.ReplayAll()

        self.assertRaises(test.TestingException, self.manager.prep_resize,
                          **kwargs)

    def test_set_vm_state_and_notify_adds_instance_fault(self):
        request = {'instance_properties': {'uuid': 'fake-uuid'}}
        updates = {'vm_state': 'foo'}
        fake_inst = {'uuid': 'fake-uuid'}

        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'instance_fault_create')
        self.mox.StubOutWithMock(notifier, 'notify')
        db.instance_update_and_get_original(self.context, 'fake-uuid',
                                            updates).AndReturn((None,
                                                                fake_inst))
        db.instance_fault_create(self.context, mox.IgnoreArg())
        notifier.notify(self.context, mox.IgnoreArg(), 'scheduler.foo',
                        notifier.ERROR, mox.IgnoreArg())
        self.mox.ReplayAll()

        self.manager._set_vm_state_and_notify('foo', {'vm_state': 'foo'},
                                              self.context, None, request)


class SchedulerTestCase(test.TestCase):
    """Test case for base scheduler driver class."""

    # So we can subclass this test and re-use tests if we need.
    driver_cls = driver.Scheduler

    def setUp(self):
        super(SchedulerTestCase, self).setUp()
        self.stubs.Set(compute_api, 'API', fakes.FakeComputeAPI)

        def fake_show(meh, context, id):
            if id:
                return {'id': id, 'min_disk': None, 'min_ram': None,
                        'name': 'fake_name',
                        'status': 'active',
                        'properties': {'kernel_id': 'fake_kernel_id',
                                       'ramdisk_id': 'fake_ramdisk_id',
                                       'something_else': 'meow'}}
            else:
                raise exception.ImageNotFound(image_id=id)

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)
        self.image_service = glance.get_default_image_service()

        self.driver = self.driver_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.servicegroup_api = servicegroup.API()

    def test_update_service_capabilities(self):
        service_name = 'fake_service'
        host = 'fake_host'

        self.mox.StubOutWithMock(self.driver.host_manager,
                'update_service_capabilities')

        capabilities = {'fake_capability': 'fake_value'}
        self.driver.host_manager.update_service_capabilities(
                service_name, host, capabilities)
        self.mox.ReplayAll()
        result = self.driver.update_service_capabilities(service_name,
                host, capabilities)

    def test_hosts_up(self):
        service1 = {'host': 'host1'}
        service2 = {'host': 'host2'}
        services = [service1, service2]

        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')

        db.service_get_all_by_topic(self.context,
                self.topic).AndReturn(services)
        self.servicegroup_api.service_is_up(service1).AndReturn(False)
        self.servicegroup_api.service_is_up(service2).AndReturn(True)

        self.mox.ReplayAll()
        result = self.driver.hosts_up(self.context, self.topic)
        self.assertEqual(result, ['host2'])

    def _live_migration_instance(self):
        inst_type = instance_types.get_instance_type(1)
        # NOTE(danms): we have _got_ to stop doing this!
        inst_type['memory_mb'] = 1024
        sys_meta = utils.dict_to_metadata(
            instance_types.save_instance_type_info({}, inst_type))
        return {'id': 31337,
                'uuid': 'fake_uuid',
                'name': 'fake-instance',
                'host': 'fake_host1',
                'power_state': power_state.RUNNING,
                'memory_mb': 1024,
                'root_gb': 1024,
                'ephemeral_gb': 0,
                'vm_state': '',
                'task_state': '',
                'instance_type_id': inst_type['id'],
                'image_ref': 'fake-image-ref',
                'system_metadata': sys_meta}

    def test_live_migration_basic(self):
        # Test basic schedule_live_migration functionality.
        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        self.mox.StubOutWithMock(self.driver, '_live_migration_dest_check')
        self.mox.StubOutWithMock(self.driver, '_live_migration_common_check')
        self.mox.StubOutWithMock(self.driver.compute_rpcapi,
                                 'check_can_live_migrate_destination')
        self.mox.StubOutWithMock(self.driver.compute_rpcapi,
                                 'live_migration')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = jsonutils.to_primitive(self._live_migration_instance())

        self.driver._live_migration_src_check(self.context, instance)
        self.driver._live_migration_dest_check(self.context, instance,
                                               dest).AndReturn(dest)
        self.driver._live_migration_common_check(self.context, instance,
                                                 dest)
        self.driver.compute_rpcapi.check_can_live_migrate_destination(
               self.context, instance, dest, block_migration,
               disk_over_commit).AndReturn({})
        self.driver.compute_rpcapi.live_migration(self.context,
                host=instance['host'], instance=instance, dest=dest,
                block_migration=block_migration, migrate_data={})

        self.mox.ReplayAll()
        self.driver.schedule_live_migration(self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_all_checks_pass(self):
        # Test live migration when all checks pass.

        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(rpc, 'call')
        self.mox.StubOutWithMock(self.driver.compute_rpcapi,
                                 'live_migration')

        dest = 'fake_host2'
        block_migration = True
        disk_over_commit = True
        instance = jsonutils.to_primitive(self._live_migration_instance())

        # Source checks
        db.service_get_by_compute_host(self.context,
                instance['host']).AndReturn('fake_service2')
        self.servicegroup_api.service_is_up('fake_service2').AndReturn(True)

        # Destination checks (compute is up, enough memory, disk)
        db.service_get_by_compute_host(self.context,
                dest).AndReturn('fake_service3')
        self.servicegroup_api.service_is_up('fake_service3').AndReturn(True)
        # assert_compute_node_has_enough_memory()
        db.service_get_by_compute_host(self.context, dest).AndReturn(
                {'compute_node': [{'memory_mb': 2048,
                                   'free_disk_gb': 512,
                                   'local_gb_used': 512,
                                   'free_ram_mb': 1280,
                                   'local_gb': 1024,
                                   'vcpus': 4,
                                   'vcpus_used': 2,
                                   'updated_at': None,
                                   'hypervisor_version': 1}]})

        # Common checks (same hypervisor, etc)
        db.service_get_by_compute_host(self.context, dest).AndReturn(
                {'compute_node': [{'hypervisor_type': 'xen',
                                   'hypervisor_version': 1}]})
        db.service_get_by_compute_host(self.context,
            instance['host']).AndReturn(
                    {'compute_node': [{'hypervisor_type': 'xen',
                                       'hypervisor_version': 1,
                                       'cpu_info': 'fake_cpu_info'}]})

        rpc.call(self.context, "compute.fake_host2",
                   {"method": 'check_can_live_migrate_destination',
                    "args": {'instance': instance,
                             'block_migration': block_migration,
                             'disk_over_commit': disk_over_commit},
                    "version": compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION},
                 None).AndReturn({})

        self.driver.compute_rpcapi.live_migration(self.context,
                host=instance['host'], instance=instance, dest=dest,
                block_migration=block_migration, migrate_data={})

        self.mox.ReplayAll()
        result = self.driver.schedule_live_migration(self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)
        self.assertEqual(result, None)

    def test_live_migration_instance_not_running(self):
        # The instance given by instance_id is not running.

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()
        instance['power_state'] = power_state.NOSTATE

        self.assertRaises(exception.InstanceNotRunning,
            self.driver.schedule_live_migration, self.context,
                    instance=instance, dest=dest,
                    block_migration=block_migration,
                    disk_over_commit=disk_over_commit)

    def test_live_migration_compute_src_not_exist(self):
        # Raise exception when src compute node is does not exist.

        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()

        # Compute down
        db.service_get_by_compute_host(self.context,
                instance['host']).AndRaise(
                        exception.ComputeHostNotFound(host='fake'))

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_compute_src_not_alive(self):
        # Raise exception when src compute node is not alive.

        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()

        # Compute down
        db.service_get_by_compute_host(self.context,
                instance['host']).AndReturn('fake_service2')
        self.servicegroup_api.service_is_up('fake_service2').AndReturn(False)

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_compute_dest_not_exist(self):
        # Raise exception when dest compute node does not exist.

        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()

        self.driver._live_migration_src_check(self.context, instance)
        # Compute down
        db.service_get_by_compute_host(self.context,
                            dest).AndRaise(exception.NotFound())

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_compute_dest_not_alive(self):
        # Raise exception when dest compute node is not alive.

        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()

        self.driver._live_migration_src_check(self.context, instance)
        db.service_get_by_compute_host(self.context,
                dest).AndReturn('fake_service3')
        # Compute is down
        self.servicegroup_api.service_is_up('fake_service3').AndReturn(False)

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_dest_check_service_same_host(self):
        # Confirms exception raises in case dest and src is same host.

        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        block_migration = False
        instance = self._live_migration_instance()
        # make dest same as src
        dest = instance['host']

        self.driver._live_migration_src_check(self.context, instance)

        self.mox.ReplayAll()
        self.assertRaises(exception.UnableToMigrateToSelf,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=False)

    def test_live_migration_dest_check_service_lack_memory(self):
        # Confirms exception raises when dest doesn't have enough memory.

        # Flag needed to make FilterScheduler test hit memory limit since the
        # default for it is to allow memory overcommit by a factor of 1.5.
        self.flags(ram_allocation_ratio=1.0)

        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(servicegroup.API, 'service_is_up')
        self.mox.StubOutWithMock(self.driver, '_get_compute_info')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()

        self.driver._live_migration_src_check(self.context, instance)
        db.service_get_by_compute_host(self.context,
                dest).AndReturn('fake_service3')
        self.servicegroup_api.service_is_up('fake_service3').AndReturn(True)

        self.driver._get_compute_info(self.context, dest).AndReturn(
                                                       {'memory_mb': 2048,
                                                        'free_disk_gb': 512,
                                                        'local_gb_used': 512,
                                                        'free_ram_mb': 512,
                                                        'local_gb': 1024,
                                                        'vcpus': 4,
                                                        'vcpus_used': 2,
                                                        'updated_at': None})

        self.mox.ReplayAll()
        self.assertRaises(exception.MigrationError,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_different_hypervisor_type_raises(self):
        # Confirm live_migration to hypervisor of different type raises.
        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        self.mox.StubOutWithMock(self.driver, '_live_migration_dest_check')
        self.mox.StubOutWithMock(rpc, 'queue_get_for')
        self.mox.StubOutWithMock(rpc, 'call')
        self.mox.StubOutWithMock(rpc, 'cast')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()

        self.driver._live_migration_src_check(self.context, instance)
        self.driver._live_migration_dest_check(self.context, instance,
                                               dest).AndReturn(dest)

        db.service_get_by_compute_host(self.context, dest).AndReturn(
                {'compute_node': [{'hypervisor_type': 'xen',
                                   'hypervisor_version': 1}]})
        db.service_get_by_compute_host(self.context,
            instance['host']).AndReturn(
                    {'compute_node': [{'hypervisor_type': 'not-xen',
                                       'hypervisor_version': 1}]})

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidHypervisorType,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_dest_hypervisor_version_older_raises(self):
        # Confirm live migration to older hypervisor raises.
        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        self.mox.StubOutWithMock(self.driver, '_live_migration_dest_check')
        self.mox.StubOutWithMock(rpc, 'queue_get_for')
        self.mox.StubOutWithMock(rpc, 'call')
        self.mox.StubOutWithMock(rpc, 'cast')
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')

        dest = 'fake_host2'
        block_migration = False
        disk_over_commit = False
        instance = self._live_migration_instance()

        self.driver._live_migration_src_check(self.context, instance)
        self.driver._live_migration_dest_check(self.context, instance,
                                               dest).AndReturn(dest)

        db.service_get_by_compute_host(self.context, dest).AndReturn(
                {'compute_node': [{'hypervisor_type': 'xen',
                                    'hypervisor_version': 1}]})
        db.service_get_by_compute_host(self.context,
            instance['host']).AndReturn(
                    {'compute_node': [{'hypervisor_type': 'xen',
                                       'hypervisor_version': 2}]})
        self.mox.ReplayAll()
        self.assertRaises(exception.DestinationHypervisorTooOld,
                self.driver.schedule_live_migration, self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)

    def test_live_migration_dest_check_auto_set_host(self):
        instance = self._live_migration_instance()

        # Confirm dest is picked by scheduler if not set.
        self.mox.StubOutWithMock(self.driver, 'select_hosts')
        self.mox.StubOutWithMock(instance_types, 'extract_instance_type')

        request_spec = {'instance_properties': instance,
                        'instance_type': {},
                        'instance_uuids': [instance['uuid']],
                        'image': self.image_service.show(self.context,
                                                         instance['image_ref'])
                        }
        ignore_hosts = [instance['host']]
        filter_properties = {'ignore_hosts': ignore_hosts}

        instance_types.extract_instance_type(instance).AndReturn({})
        self.driver.select_hosts(self.context, request_spec,
                                 filter_properties).AndReturn(['fake_host2'])

        self.mox.ReplayAll()
        result = self.driver._live_migration_dest_check(self.context, instance,
                                                        None, ignore_hosts)
        self.assertEqual('fake_host2', result)

    def test_live_migration_auto_set_dest(self):
        instance = self._live_migration_instance()

        # Confirm scheduler picks target host if none given.
        self.mox.StubOutWithMock(instance_types, 'extract_instance_type')
        self.mox.StubOutWithMock(self.driver, '_live_migration_src_check')
        self.mox.StubOutWithMock(self.driver, 'select_hosts')
        self.mox.StubOutWithMock(self.driver, '_live_migration_common_check')
        self.mox.StubOutWithMock(rpc, 'call')
        self.mox.StubOutWithMock(self.driver.compute_rpcapi, 'live_migration')

        dest = None
        block_migration = False
        disk_over_commit = False
        request_spec = {'instance_properties': instance,
                        'instance_type': {},
                        'instance_uuids': [instance['uuid']],
                        'image': self.image_service.show(self.context,
                                                         instance['image_ref'])
                        }

        self.driver._live_migration_src_check(self.context, instance)

        instance_types.extract_instance_type(
                instance).MultipleTimes().AndReturn({})

        # First selected host raises exception.InvalidHypervisorType
        self.driver.select_hosts(self.context, request_spec,
                {'ignore_hosts': [instance['host']]}).AndReturn(['fake_host2'])
        self.driver._live_migration_common_check(self.context, instance,
                'fake_host2').AndRaise(exception.InvalidHypervisorType())

        # Second selected host raises exception.InvalidCPUInfo
        self.driver.select_hosts(self.context, request_spec,
                {'ignore_hosts': [instance['host'],
                                  'fake_host2']}).AndReturn(['fake_host3'])
        self.driver._live_migration_common_check(self.context, instance,
                                                 'fake_host3')
        rpc.call(self.context, "compute.fake_host3",
                   {"method": 'check_can_live_migrate_destination',
                    "args": {'instance': instance,
                             'block_migration': block_migration,
                             'disk_over_commit': disk_over_commit},
                    "version": compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION},
                 None).AndRaise(exception.InvalidCPUInfo(reason=""))

        # Third selected host pass all checks
        self.driver.select_hosts(self.context, request_spec,
                {'ignore_hosts': [instance['host'],
                                  'fake_host2',
                                  'fake_host3']}).AndReturn(['fake_host4'])
        self.driver._live_migration_common_check(self.context, instance,
                                                 'fake_host4')
        rpc.call(self.context, "compute.fake_host4",
                   {"method": 'check_can_live_migrate_destination',
                    "args": {'instance': instance,
                             'block_migration': block_migration,
                             'disk_over_commit': disk_over_commit},
                    "version": compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION},
                 None).AndReturn({})
        self.driver.compute_rpcapi.live_migration(self.context,
                host=instance['host'], instance=instance, dest='fake_host4',
                block_migration=block_migration, migrate_data={})

        self.mox.ReplayAll()
        result = self.driver.schedule_live_migration(self.context,
                instance=instance, dest=dest,
                block_migration=block_migration,
                disk_over_commit=disk_over_commit)
        self.assertEqual(result, None)

    def test_handle_schedule_error_adds_instance_fault(self):
        instance = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'instance_fault_create')
        self.mox.StubOutWithMock(notifier, 'notify')
        db.instance_update_and_get_original(self.context, instance['uuid'],
                                            mox.IgnoreArg()).AndReturn(
                                                (None, instance))
        db.instance_fault_create(self.context, mox.IgnoreArg())
        notifier.notify(self.context, mox.IgnoreArg(),
                        'scheduler.run_instance',
                        notifier.ERROR, mox.IgnoreArg())
        self.mox.ReplayAll()

        driver.handle_schedule_error(self.context,
                                     exception.NoValidHost('test'),
                                     instance['uuid'], {})


class SchedulerDriverBaseTestCase(SchedulerTestCase):
    """Test cases for base scheduler driver class methods
       that can't will fail if the driver is changed"""

    def test_unimplemented_schedule_run_instance(self):
        fake_args = (1, 2, 3)
        fake_kwargs = {'cat': 'meow'}
        fake_request_spec = {'instance_properties':
                {'uuid': 'uuid'}}

        self.assertRaises(NotImplementedError,
                         self.driver.schedule_run_instance,
                         self.context, fake_request_spec, None, None, None,
                         None, None)

    def test_unimplemented_schedule_prep_resize(self):
        fake_args = (1, 2, 3)
        fake_kwargs = {'cat': 'meow'}
        fake_request_spec = {'instance_properties':
                {'uuid': 'uuid'}}

        self.assertRaises(NotImplementedError,
                         self.driver.schedule_prep_resize,
                         self.context, {},
                         fake_request_spec, {}, {}, {}, None)


class SchedulerDriverModuleTestCase(test.TestCase):
    """Test case for scheduler driver module methods."""

    def setUp(self):
        super(SchedulerDriverModuleTestCase, self).setUp()
        self.context = context.RequestContext('fake_user', 'fake_project')

    def test_encode_instance(self):
        instance = {'id': 31337,
                    'test_arg': 'meow'}

        result = driver.encode_instance(instance, True)
        expected = {'id': instance['id'], '_is_precooked': False}
        self.assertThat(result, matchers.DictMatches(expected))
        # Orig dict not changed
        self.assertNotEqual(result, instance)

        result = driver.encode_instance(instance, False)
        expected = {}
        expected.update(instance)
        expected['_is_precooked'] = True
        self.assertThat(result, matchers.DictMatches(expected))
        # Orig dict not changed
        self.assertNotEqual(result, instance)
