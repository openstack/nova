# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
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
Tests For Compute
"""
from copy import copy
import datetime
import time
from webob import exc

import mox
import webob.exc

import nova
from nova import compute
from nova.compute import instance_types
from nova.compute import manager as compute_manager
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.image import fake as fake_image
from nova import log as logging
from nova.network.quantum import client as quantum_client
from nova.notifier import test_notifier
from nova.scheduler import driver as scheduler_driver
from nova import rpc
from nova import test
from nova.tests import fake_network
from nova import utils
import nova.volume


LOG = logging.getLogger('nova.tests.compute')
FLAGS = flags.FLAGS
flags.DECLARE('stub_network', 'nova.compute.manager')
flags.DECLARE('live_migration_retry_count', 'nova.compute.manager')


class FakeTime(object):
    def __init__(self):
        self.counter = 0

    def sleep(self, t):
        self.counter += t


orig_rpc_call = rpc.call
orig_rpc_cast = rpc.cast


def rpc_call_wrapper(context, topic, msg, do_cast=True):
    """Stub out the scheduler creating the instance entry"""
    if topic == FLAGS.scheduler_topic and \
            msg['method'] == 'run_instance':
        request_spec = msg['args']['request_spec']
        scheduler = scheduler_driver.Scheduler
        num_instances = request_spec.get('num_instances', 1)
        instances = []
        for x in xrange(num_instances):
            instance = scheduler().create_instance_db_entry(
                    context, request_spec)
            encoded = scheduler_driver.encode_instance(instance)
            instances.append(encoded)
        return instances
    else:
        if do_cast:
            orig_rpc_cast(context, topic, msg)
        else:
            return orig_rpc_call(context, topic, msg)


def rpc_cast_wrapper(context, topic, msg):
    """Stub out the scheduler creating the instance entry in
    the reservation_id case.
    """
    rpc_call_wrapper(context, topic, msg, do_cast=True)


def nop_report_driver_status(self):
    pass


class BaseTestCase(test.TestCase):

    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.flags(connection_type='fake',
                   stub_network=True,
                   notification_driver='nova.notifier.test_notifier',
                   network_manager='nova.network.manager.FlatManager')
        self.compute = utils.import_object(FLAGS.compute_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []
        self.mox = mox.Mox()
        self.total_waits = 0

        def fake_show(meh, context, id):
            return {'id': 1, 'min_disk': None, 'min_ram': None,
                    'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)
        self.stubs.Set(rpc, 'call', rpc_call_wrapper)
        self.stubs.Set(rpc, 'cast', rpc_cast_wrapper)

    def tearDown(self):
        self.mox.UnsetStubs()
        instances = db.instance_get_all(self.context.elevated())
        for instance in instances:
            db.instance_destroy(self.context.elevated(), instance['id'])
        super(BaseTestCase, self).tearDown()

    def _create_fake_instance(self, params=None, type_name='m1.tiny'):
        """Create a test instance"""
        if not params:
            params = {}

        inst = {}
        inst['vm_state'] = vm_states.ACTIVE
        inst['image_ref'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        type_id = instance_types.get_instance_type_by_name(type_name)['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst.update(params)
        return db.instance_create(self.context, inst)

    def _create_instance(self, params=None, type_name='m1.tiny'):
        """Create a test instance. Returns uuid"""
        return self._create_fake_instance(params, type_name=type_name)['uuid']

    def _create_instance_type(self, params=None):
        """Create a test instance type"""
        if not params:
            params = {}

        context = self.context.elevated()
        inst = {}
        inst['name'] = 'm1.small'
        inst['memory_mb'] = '1024'
        inst['vcpus'] = '1'
        inst['local_gb'] = '20'
        inst['flavorid'] = '1'
        inst['swap'] = '2048'
        inst['rxtx_factor'] = 1
        inst.update(params)
        return db.instance_type_create(context, inst)['id']

    def _create_group(self):
        values = {'name': 'testgroup',
                  'description': 'testgroup',
                  'user_id': self.user_id,
                  'project_id': self.project_id}
        return db.security_group_create(self.context, values)


class ComputeTestCase(BaseTestCase):

    def test_wrap_instance_fault(self):
        inst_uuid = "fake_uuid"

        called = {'fault_added': False}

        def did_it_add_fault(_ctxt, _inst_uuid, _e):
            called['fault_added'] = True

        self.stubs.Set(self.compute, 'add_instance_fault_from_exc',
                       did_it_add_fault)

        @nova.compute.manager.wrap_instance_fault
        def failer(self2, context, instance_uuid):
            raise NotImplementedError()

        self.assertRaises(NotImplementedError, failer,
                          self.compute, self.context, inst_uuid)

        self.assertTrue(called['fault_added'])

    def test_wrap_instance_fault_no_instance(self):
        inst_uuid = "fake_uuid"

        called = {'fault_added': False}

        def did_it_add_fault(_ctxt, _inst_uuid, _e):
            called['fault_added'] = True

        self.stubs.Set(self.compute, 'add_instance_fault_from_exc',
                       did_it_add_fault)

        @nova.compute.manager.wrap_instance_fault
        def failer(self2, context, instance_uuid):
            raise exception.InstanceNotFound()

        self.assertRaises(exception.InstanceNotFound, failer,
                          self.compute, self.context, inst_uuid)

        self.assertFalse(called['fault_added'])

    def test_create_instance_with_img_ref_associates_config_drive(self):
        """Make sure create associates a config drive."""

        instance = self._create_fake_instance(
                        params={'config_drive': '1234', })

        try:
            self.compute.run_instance(self.context, instance['uuid'])
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertTrue(instance.config_drive)
        finally:
            db.instance_destroy(self.context, instance['id'])

    def test_create_instance_associates_config_drive(self):
        """Make sure create associates a config drive."""

        instance = self._create_fake_instance(
                        params={'config_drive': '1234', })

        try:
            self.compute.run_instance(self.context, instance['uuid'])
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertTrue(instance.config_drive)
        finally:
            db.instance_destroy(self.context, instance['id'])

    def _assert_state(self, state_dict):
        """assert the instance is in the state defined by state_dict"""
        instances = db.instance_get_all(context.get_admin_context())
        self.assertEqual(len(instances), 1)

        if 'vm_state' in state_dict:
            self.assertEqual(state_dict['vm_state'], instances[0]['vm_state'])
        if 'task_state' in state_dict:
            self.assertEqual(state_dict['task_state'],
                             instances[0]['task_state'])
        if 'power_state' in state_dict:
            self.assertEqual(state_dict['power_state'],
                             instances[0]['power_state'])

    def test_fail_to_schedule_persists(self):
        """check the persistence of the ERROR(scheduling) state"""
        self._create_instance(params={'vm_state': vm_states.ERROR,
                                      'task_state': task_states.SCHEDULING})
        #check state is failed even after the periodic poll
        error_list = self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.SCHEDULING})

    def test_run_instance_setup_block_device_mapping_fail(self):
        """ block device mapping failure test.

        Make sure that when there is a block device mapping problem,
        the instance goes to ERROR state, keeping the task state
        """
        def fake(*args, **kwargs):
            raise Exception("Failed to block device mapping")
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       '_setup_block_device_mapping', fake)
        instance_uuid = self._create_instance()
        self.assertRaises(Exception, self.compute.run_instance,
                          self.context, instance_uuid)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.BLOCK_DEVICE_MAPPING})
        error_list = self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.BLOCK_DEVICE_MAPPING})

    def test_run_instance_spawn_fail(self):
        """ spawn failure test.

        Make sure that when there is a spawning problem,
        the instance goes to ERROR state, keeping the task state"""
        def fake(*args, **kwargs):
            raise Exception("Failed to spawn")
        self.stubs.Set(self.compute.driver, 'spawn', fake)
        instance_uuid = self._create_instance()
        self.assertRaises(Exception, self.compute.run_instance,
                          self.context, instance_uuid)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.SPAWNING})
        error_list = self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.SPAWNING})

    def test_can_terminate_on_error_state(self):
        """Make sure that the instance can be terminated in ERROR state"""
        elevated = context.get_admin_context()
        #check failed to schedule --> terminate
        instance_uuid = self._create_instance(params={'vm_state':
                                                vm_states.ERROR})
        self.compute.terminate_instance(self.context, instance_uuid)
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          elevated, instance_uuid)

    def test_run_terminate(self):
        """Make sure it is possible to  run and terminate instance"""
        instance = self._create_fake_instance()

        self.compute.run_instance(self.context, instance['uuid'])

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        self.compute.terminate_instance(self.context, instance['uuid'])

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)

    def test_run_terminate_timestamps(self):
        """Make sure timestamps are set for launched and destroyed"""
        instance = self._create_fake_instance()
        self.assertEqual(instance['launched_at'], None)
        self.assertEqual(instance['deleted_at'], None)
        launch = utils.utcnow()
        self.compute.run_instance(self.context, instance['uuid'])
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assert_(instance['launched_at'] > launch)
        self.assertEqual(instance['deleted_at'], None)
        terminate = utils.utcnow()
        self.compute.terminate_instance(self.context, instance['uuid'])
        context = self.context.elevated(read_deleted="only")
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assert_(instance['launched_at'] < terminate)
        self.assert_(instance['deleted_at'] > terminate)

    def test_stop(self):
        """Ensure instance can be stopped"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.stop_instance(self.context, instance_uuid)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_start(self):
        """Ensure instance can be started"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.stop_instance(self.context, instance_uuid)
        self.compute.start_instance(self.context, instance_uuid)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_rescue(self):
        """Ensure instance can be rescued and unrescued"""

        called = {'rescued': False,
                  'unrescued': False}

        def fake_rescue(self, context, instance_ref, network_info, image_meta):
            called['rescued'] = True

        self.stubs.Set(nova.virt.fake.FakeConnection, 'rescue', fake_rescue)

        def fake_unrescue(self, instance_ref, network_info):
            called['unrescued'] = True

        self.stubs.Set(nova.virt.fake.FakeConnection, 'unrescue',
                       fake_unrescue)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.rescue_instance(self.context, instance_uuid)
        self.assertTrue(called['rescued'])
        self.compute.unrescue_instance(self.context, instance_uuid)
        self.assertTrue(called['unrescued'])
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_power_on(self):
        """Ensure instance can be powered on"""

        called = {'power_on': False}

        def fake_driver_power_on(self, instance):
            called['power_on'] = True

        self.stubs.Set(nova.virt.driver.ComputeDriver, 'power_on',
                       fake_driver_power_on)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.power_on_instance(self.context, instance_uuid)
        self.assertTrue(called['power_on'])
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_power_off(self):
        """Ensure instance can be powered off"""

        called = {'power_off': False}

        def fake_driver_power_off(self, instance):
            called['power_off'] = True

        self.stubs.Set(nova.virt.driver.ComputeDriver, 'power_off',
                       fake_driver_power_off)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.power_off_instance(self.context, instance_uuid)
        self.assertTrue(called['power_off'])
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_pause(self):
        """Ensure instance can be paused and unpaused"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.pause_instance(self.context, instance_uuid)
        self.compute.unpause_instance(self.context, instance_uuid)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_suspend(self):
        """ensure instance can be suspended and resumed"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.suspend_instance(self.context, instance_uuid)
        self.compute.resume_instance(self.context, instance_uuid)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_rebuild(self):
        """Ensure instance can be rebuilt"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.compute.run_instance(self.context, instance_uuid)
        self.compute.rebuild_instance(self.context, instance_uuid)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_reboot_soft(self):
        """Ensure instance can be soft rebooted"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid,
                           {'task_state': task_states.REBOOTING})

        reboot_type = "SOFT"
        self.compute.reboot_instance(self.context, instance_uuid, reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['power_state'], power_state.RUNNING)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context, inst_ref['uuid'])

    def test_reboot_hard(self):
        """Ensure instance can be hard rebooted"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid,
                           {'task_state': task_states.REBOOTING_HARD})

        reboot_type = "HARD"
        self.compute.reboot_instance(self.context, instance_uuid, reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['power_state'], power_state.RUNNING)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context, inst_ref['uuid'])

    def test_set_admin_password(self):
        """Ensure instance can have its admin password set"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid,
                           {'task_state': task_states.UPDATING_PASSWORD})

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

        self.compute.set_admin_password(self.context, instance_uuid)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context, inst_ref['uuid'])

    def test_set_admin_password_driver_error(self):
        """Ensure error is raised admin password set"""

        def fake_sleep(_time):
            pass

        self.stubs.Set(time, 'sleep', fake_sleep)

        def fake_driver_set_pass(self2, _instance, _pwd):
            raise exception.NotAuthorized(_('Internal error'))

        self.stubs.Set(nova.virt.fake.FakeConnection, 'set_admin_password',
                       fake_driver_set_pass)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid,
                           {'task_state': task_states.UPDATING_PASSWORD})

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

        #error raised from the driver should not reveal internal information
        #so a new error is raised
        self.assertRaises(exception.Error,
                          self.compute.set_admin_password,
                          self.context, instance_uuid)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ERROR)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context, inst_ref['uuid'])

    def test_inject_file(self):
        """Ensure we can write a file to an instance"""
        called = {'inject': False}

        def fake_driver_inject_file(self2, instance, path, contents):
            self.assertEqual(path, "/tmp/test")
            self.assertEqual(contents, "File Contents")
            called['inject'] = True

        self.stubs.Set(nova.virt.fake.FakeConnection, 'inject_file',
                       fake_driver_inject_file)

        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        self.compute.inject_file(self.context, instance['uuid'], "/tmp/test",
                "File Contents")
        self.assertTrue(called['inject'])
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_inject_network_info(self):
        """Ensure we can inject network info"""
        called = {'inject': False}

        def fake_driver_inject_network(self, instance, network_info):
            called['inject'] = True

        self.stubs.Set(nova.virt.fake.FakeConnection, 'inject_network_info',
                       fake_driver_inject_network)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.inject_network_info(self.context, instance_uuid)
        self.assertTrue(called['inject'])
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_reset_network(self):
        """Ensure we can reset networking on an instance"""
        called = {'reset': False}

        def fake_driver_reset_network(self, instance):
            called['reset'] = True

        self.stubs.Set(nova.virt.fake.FakeConnection, 'reset_network',
                       fake_driver_reset_network)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.reset_network(self.context, instance_uuid)
        self.assertTrue(called['reset'])
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_agent_update(self):
        """Ensure instance can have its agent updated"""
        called = {'agent_update': False}

        def fake_driver_agent_update(self2, instance, url, md5hash):
            called['agent_update'] = True
            self.assertEqual(url, 'http://fake/url/')
            self.assertEqual(md5hash, 'fakehash')

        self.stubs.Set(nova.virt.fake.FakeConnection, 'agent_update',
                       fake_driver_agent_update)

        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        self.compute.agent_update(self.context, instance['uuid'],
                                  'http://fake/url/', 'fakehash')
        self.assertTrue(called['agent_update'])
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_snapshot(self):
        """Ensure instance can be snapshotted"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        name = "myfakesnapshot"
        self.compute.run_instance(self.context, instance_uuid)
        self.compute.snapshot_instance(self.context, instance_uuid, name)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_snapshot_fails(self):
        """Ensure task_state is set to None if snapshot fails"""
        def fake_snapshot(*args, **kwargs):
            raise Exception("I don't want to create a snapshot")

        self.stubs.Set(self.compute.driver, 'snapshot', fake_snapshot)

        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        self.assertRaises(Exception, self.compute.snapshot_instance,
                          self.context, instance['uuid'], "failing_snapshot")
        self._assert_state({'task_state': None})
        self.compute.terminate_instance(self.context, instance['uuid'])

    def _assert_state(self, state_dict):
        """Assert state of VM is equal to state passed as parameter"""
        instances = db.instance_get_all(context.get_admin_context())
        self.assertEqual(len(instances), 1)

        if 'vm_state' in state_dict:
            self.assertEqual(state_dict['vm_state'], instances[0]['vm_state'])
        if 'task_state' in state_dict:
            self.assertEqual(state_dict['task_state'],
                             instances[0]['task_state'])
        if 'power_state' in state_dict:
            self.assertEqual(state_dict['power_state'],
                             instances[0]['power_state'])

    def test_console_output(self):
        """Make sure we can get console output from instance"""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        output = self.compute.get_console_output(self.context,
                                                  instance['uuid'])
        self.assertEqual(output, 'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE')
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_console_output_tail(self):
        """Make sure we can get console output from instance"""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        output = self.compute.get_console_output(self.context,
                                                instance['uuid'],
                                                tail_length=2)
        self.assertEqual(output, 'ANOTHER\nLAST LINE')
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_ajax_console(self):
        """Make sure we can get console output from instance"""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        console = self.compute.get_ajax_console(self.context,
                                                instance['uuid'])
        self.assert_(set(['token', 'host', 'port']).issubset(console.keys()))
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_vnc_console(self):
        """Make sure we can a vnc console for an instance."""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        console = self.compute.get_vnc_console(self.context, instance['uuid'])
        self.assert_(console)
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_diagnostics(self):
        """Make sure we can get diagnostics for an instance."""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        diagnostics = self.compute.get_diagnostics(self.context,
                                                   instance['uuid'])
        self.assertEqual(diagnostics, 'FAKE_DIAGNOSTICS')
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_add_fixed_ip_usage_notification(self):
        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(nova.network.API, 'add_fixed_ip_to_instance',
                       dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'inject_network_info', dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'reset_network', dummy)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 0)
        self.compute.add_fixed_ip_to_instance(self.context, instance_uuid, 1)

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_remove_fixed_ip_usage_notification(self):
        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(nova.network.API, 'remove_fixed_ip_from_instance',
                       dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'inject_network_info', dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'reset_network', dummy)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 0)
        self.compute.remove_fixed_ip_from_instance(self.context,
                                                   instance_uuid,
                                                   1)

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_run_instance_usage_notification(self):
        """Ensure run instance generates apropriate usage notification"""
        inst_ref = self._create_fake_instance()
        instance_uuid = inst_ref['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.create')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], inst_ref.uuid)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertEquals(payload['state'], 'active')
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertTrue(payload['launched_at'])
        image_ref_url = "%s/images/1" % utils.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_terminate_usage_notification(self):
        """Ensure terminate_instance generates apropriate usage notification"""
        inst_ref = self._create_fake_instance()
        self.compute.run_instance(self.context, inst_ref['uuid'])
        test_notifier.NOTIFICATIONS = []
        self.compute.terminate_instance(self.context, inst_ref['uuid'])

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.exists')

        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.delete')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], inst_ref.uuid)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        image_ref_url = "%s/images/1" % utils.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)

    def test_run_instance_existing(self):
        """Ensure failure when running an instance that already exists"""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        self.assertRaises(exception.Error,
                          self.compute.run_instance,
                          self.context,
                          instance['uuid'])
        self.compute.terminate_instance(self.context, instance['uuid'])

    @test.skip_test('test fails: lp892005')
    def test_instance_set_to_error_on_uncaught_exception(self):
        """Test that instance is set to error state when exception is raised"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.mox.StubOutWithMock(self.compute.network_api,
                                 "allocate_for_instance")
        self.compute.network_api.allocate_for_instance(mox.IgnoreArg(),
                                                       mox.IgnoreArg(),
                                                       requested_networks=None,
                                                       vpn=False).\
            AndRaise(quantum_client.QuantumServerException())

        FLAGS.stub_network = False

        self.mox.ReplayAll()

        self.assertRaises(quantum_client.QuantumServerException,
                          self.compute.run_instance,
                          self.context,
                          instance_uuid)

        instance = db.instance_get_by_uuid(context.get_admin_context(),
                                           instance_uuid)
        self.assertEqual(vm_states.ERROR, instance['vm_state'])

        self.compute.terminate_instance(self.context, instance['uuid'])

    @test.skip_test('test fails: lp892005')
    def test_network_is_deallocated_on_spawn_failure(self):
        """When a spawn fails the network must be deallocated"""
        instance = self._create_fake_instance()

        self.mox.StubOutWithMock(self.compute, "_setup_block_device_mapping")
        self.compute._setup_block_device_mapping(mox.IgnoreArg(),
                                                 mox.IgnoreArg()).\
            AndRaise(rpc.common.RemoteError('', '', ''))

        self.mox.ReplayAll()

        self.assertRaises(rpc.common.RemoteError,
                          self.compute.run_instance,
                          self.context,
                          instance['uuid'])

        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_get_lock(self):
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.assertFalse(self.compute.get_lock(self.context, instance_uuid))
        db.instance_update(self.context, instance_uuid, {'locked': True})
        self.assertTrue(self.compute.get_lock(self.context, instance_uuid))

    def test_lock(self):
        """ensure locked instance cannot be changed"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        non_admin_context = context.RequestContext(None, None, is_admin=False)

        # decorator should return False (fail) with locked nonadmin context
        self.compute.lock_instance(self.context, instance_uuid)
        ret_val = self.compute.reboot_instance(non_admin_context,
                                               instance_uuid)
        self.assertEqual(ret_val, False)

        # decorator should return None (success) with unlocked nonadmin context
        self.compute.unlock_instance(self.context, instance_uuid)
        ret_val = self.compute.reboot_instance(non_admin_context,
                                               instance_uuid)
        self.assertEqual(ret_val, None)

        self.compute.terminate_instance(self.context, instance_uuid)

    def test_finish_resize(self):
        """Contrived test to ensure finish_resize doesn't raise anything"""

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.network_api, 'get_instance_nw_info', fake)
        context = self.context.elevated()
        instance = self._create_fake_instance()
        self.compute.prep_resize(context, instance['uuid'], 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'pre-migrating')
        try:
            self.compute.finish_resize(context, instance['uuid'],
                    int(migration_ref['id']), {})
        except KeyError, e:
            # Only catch key errors. We want other reasons for the test to
            # fail to actually error out so we don't obscure anything
            self.fail()

        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_finish_resize_handles_error(self):
        """Make sure we don't leave the instance in RESIZE on error"""

        def throw_up(*args, **kwargs):
            raise Exception()

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', throw_up)
        self.stubs.Set(self.compute.network_api, 'get_instance_nw_info', fake)
        context = self.context.elevated()
        instance = self._create_fake_instance()
        self.compute.prep_resize(context, instance['uuid'], 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'pre-migrating')

        self.assertRaises(Exception, self.compute.finish_resize,
                          context, instance['uuid'],
                          int(migration_ref['id']), {})

        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_resize_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance_uuid)
        test_notifier.NOTIFICATIONS = []

        db.instance_update(self.context, instance_uuid, {'host': 'foo'})
        self.compute.prep_resize(context, instance_uuid, 1)
        db.migration_get_by_instance_and_status(context,
                                                instance_uuid,
                                                'pre-migrating')

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.resize.prep')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance_uuid)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        image_ref_url = "%s/images/1" % utils.generate_glance_url()
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(context, instance_uuid)

    def test_prep_resize_instance_migration_error(self):
        """Ensure prep_resize raise a migration error"""
        self.flags(host="foo", allow_resize_to_same_host=False)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid, {'host': 'foo'})

        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                          context, instance_uuid, 1)
        self.compute.terminate_instance(context, instance_uuid)

    def test_resize_instance_driver_error(self):
        """Ensure instance status set to Error on resize error"""

        def throw_up(*args, **kwargs):
            raise Exception()

        self.stubs.Set(self.compute.driver, 'migrate_disk_and_power_off',
                       throw_up)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid, {'host': 'foo'})
        self.compute.prep_resize(context, instance_uuid, 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance_uuid, 'pre-migrating')

        #verify
        self.assertRaises(Exception, self.compute.resize_instance, context,
                          instance_uuid, migration_ref['id'])
        instance = db.instance_get_by_uuid(context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.ERROR)

        self.compute.terminate_instance(context, instance_uuid)

    def test_resize_instance(self):
        """Ensure instance can be migrated/resized"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid,
                           {'host': 'foo'})
        self.compute.prep_resize(context, instance_uuid, 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance_uuid, 'pre-migrating')
        self.compute.resize_instance(context, instance_uuid,
                migration_ref['id'])
        self.compute.terminate_instance(context, instance_uuid)

    def test_finish_revert_resize(self):
        """Ensure that the flavor is reverted to the original on revert"""
        context = self.context.elevated()
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.driver, 'finish_revert_migration', fake)
        self.stubs.Set(self.compute.network_api, 'get_instance_nw_info', fake)

        self.compute.run_instance(self.context, instance_uuid)

        # Confirm the instance size before the resize starts
        inst_ref = db.instance_get_by_uuid(context, instance_uuid)
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '1')

        db.instance_update(self.context, instance_uuid, {'host': 'foo'})

        new_instance_type_ref = db.instance_type_get_by_flavor_id(context, 3)
        self.compute.prep_resize(context, inst_ref['uuid'],
                                 new_instance_type_ref['id'])

        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')

        self.compute.resize_instance(context, inst_ref['uuid'],
                migration_ref['id'])
        self.compute.finish_resize(context, inst_ref['uuid'],
                    int(migration_ref['id']), {})

        # Prove that the instance size is now the new size
        inst_ref = db.instance_get_by_uuid(context, instance_uuid)
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '3')

        # Finally, revert and confirm the old flavor has been applied
        self.compute.revert_resize(context, inst_ref['uuid'],
                migration_ref['id'])
        self.compute.finish_revert_resize(context, inst_ref['uuid'],
                migration_ref['id'])

        inst_ref = db.instance_get_by_uuid(context, instance_uuid)
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '1')
        self.assertEqual(inst_ref['host'], migration_ref['source_compute'])

        self.compute.terminate_instance(context, inst_ref['uuid'])

    def test_get_by_flavor_id(self):
        type = instance_types.get_instance_type_by_flavor_id(1)
        self.assertEqual(type['name'], 'm1.tiny')

    def test_resize_same_source_fails(self):
        """Ensure instance fails to migrate when source and destination are
        the same host"""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                self.context, instance['uuid'], 1)
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_resize_instance_handles_migration_error(self):
        """Ensure vm_state is ERROR when error occurs"""
        def raise_migration_failure(*args):
            raise Exception(reason='test failure')
        self.stubs.Set(self.compute.driver,
                'migrate_disk_and_power_off',
                raise_migration_failure)

        inst_ref = self._create_fake_instance()
        context = self.context.elevated()

        self.compute.run_instance(self.context, inst_ref['uuid'])
        db.instance_update(self.context, inst_ref['uuid'], {'host': 'foo'})
        self.compute.prep_resize(context, inst_ref['uuid'], 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')
        self.assertRaises(Exception, self.compute.resize_instance,
                          context, inst_ref['uuid'], migration_ref['id'])
        inst_ref = db.instance_get_by_uuid(context, inst_ref['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(context, inst_ref['uuid'])

    def _setup_other_managers(self):
        self.volume_manager = utils.import_object(FLAGS.volume_manager)
        self.network_manager = utils.import_object(FLAGS.network_manager)
        self.compute_driver = utils.import_object(FLAGS.compute_driver)

    def test_pre_live_migration_instance_has_no_fixed_ip(self):
        """Confirm raising exception if instance doesn't have fixed_ip."""
        # creating instance testdata
        inst_ref = self._create_fake_instance({'host': 'dummy'})
        c = context.get_admin_context()
        topic = db.queue_get_for(c, FLAGS.compute_topic, inst_ref['host'])

        # start test
        self.assertRaises(exception.FixedIpNotFoundForInstance,
                          self.compute.pre_live_migration,
                          c, inst_ref['id'], time=FakeTime())
        # cleanup
        db.instance_destroy(c, inst_ref['id'])

    def test_pre_live_migration_works_correctly(self):
        """Confirm setup_compute_volume is called when volume is mounted."""
        # creating instance testdata
        inst_ref = self._create_fake_instance({'host': 'dummy'})
        c = context.get_admin_context()
        topic = db.queue_get_for(c, FLAGS.compute_topic, inst_ref['host'])

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'pre_live_migration')
        self.compute.driver.pre_live_migration({'block_device_mapping': []})
        dummy_nw_info = [[None, {'ips':'1.1.1.1'}]]
        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.compute._get_instance_nw_info(c, mox.IsA(inst_ref)
            ).AndReturn(dummy_nw_info)
        self.mox.StubOutWithMock(self.compute.driver, 'plug_vifs')
        self.compute.driver.plug_vifs(mox.IsA(inst_ref), dummy_nw_info)
        self.mox.StubOutWithMock(self.compute.driver,
                                 'ensure_filtering_rules_for_instance')
        self.compute.driver.ensure_filtering_rules_for_instance(
            mox.IsA(inst_ref), dummy_nw_info)

        # start test
        self.mox.ReplayAll()
        ret = self.compute.pre_live_migration(c, inst_ref['id'])
        self.assertEqual(ret, None)

        # cleanup
        db.instance_destroy(c, inst_ref['id'])

    def test_live_migration_dest_raises_exception(self):
        """Confirm exception when pre_live_migration fails."""
        # creating instance testdata
        inst_ref = self._create_fake_instance({'host': 'dummy'})
        instance_id = inst_ref['id']
        c = context.get_admin_context()
        topic = db.queue_get_for(c, FLAGS.compute_topic, inst_ref['host'])
        # creating volume testdata
        volume_id = 1
        db.volume_create(c, {'id': volume_id})
        values = {'instance_id': instance_id, 'device_name': '/dev/vdc',
            'delete_on_termination': False, 'volume_id': volume_id}
        db.block_device_mapping_create(c, values)

        # creating mocks
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, FLAGS.volume_topic, {"method": "check_for_export",
                                         "args": {'instance_id': instance_id}})
        rpc.call(c, topic, {"method": "pre_live_migration",
                            "args": {'instance_id': instance_id,
                                     'block_migration': True,
                                     'disk': None}}).\
                            AndRaise(rpc.common.RemoteError('', '', ''))
        # mocks for rollback
        rpc.call(c, topic, {"method": "remove_volume_connection",
                            "args": {'instance_id': instance_id,
                                     'volume_id': volume_id}})
        rpc.cast(c, topic, {"method": "rollback_live_migration_at_destination",
                            "args": {'instance_id': inst_ref['id']}})

        # start test
        self.mox.ReplayAll()
        self.assertRaises(rpc.RemoteError,
                          self.compute.live_migration,
                          c, instance_id, inst_ref['host'], True)

        # cleanup
        for bdms in db.block_device_mapping_get_all_by_instance(c,
                                                                instance_id):
            db.block_device_mapping_destroy(c, bdms['id'])
        db.volume_destroy(c, volume_id)
        db.instance_destroy(c, inst_ref['id'])

    def test_live_migration_works_correctly(self):
        """Confirm live_migration() works as expected correctly."""
        # creating instance testdata
        instance = self._create_fake_instance({'host': 'dummy'})
        instance_id = instance['id']
        c = context.get_admin_context()
        inst_ref = db.instance_get(c, instance_id)
        topic = db.queue_get_for(c, FLAGS.compute_topic, inst_ref['host'])

        # create
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, topic, {"method": "pre_live_migration",
                            "args": {'instance_id': instance_id,
                                     'block_migration': False,
                                     'disk': None}})

        # start test
        self.mox.ReplayAll()
        ret = self.compute.live_migration(c, inst_ref['id'], inst_ref['host'])
        self.assertEqual(ret, None)

        # cleanup
        db.instance_destroy(c, instance_id)

    def test_post_live_migration_working_correctly(self):
        """Confirm post_live_migration() works as expected correctly."""
        dest = 'desthost'
        flo_addr = '1.2.1.2'

        # creating testdata
        c = context.get_admin_context()
        instance = self._create_fake_instance({
                        'state_description': 'migrating',
                        'state': power_state.PAUSED})
        instance_id = instance['id']
        i_ref = db.instance_get(c, instance_id)
        db.instance_update(c, i_ref['id'], {'vm_state': vm_states.MIGRATING,
                                            'power_state': power_state.PAUSED})
        v_ref = db.volume_create(c, {'size': 1, 'instance_id': instance_id})
        fix_addr = db.fixed_ip_create(c, {'address': '1.1.1.1',
                                          'instance_id': instance_id})
        fix_ref = db.fixed_ip_get_by_address(c, fix_addr)
        flo_ref = db.floating_ip_create(c, {'address': flo_addr,
                                        'fixed_ip_id': fix_ref['id']})

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'unfilter_instance')
        self.compute.driver.unfilter_instance(i_ref, [])
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, db.queue_get_for(c, FLAGS.compute_topic, dest),
            {"method": "post_live_migration_at_destination",
             "args": {'instance_id': i_ref['id'], 'block_migration': False}})
        self.mox.StubOutWithMock(self.compute.driver, 'unplug_vifs')
        self.compute.driver.unplug_vifs(i_ref, [])

        # start test
        self.mox.ReplayAll()
        ret = self.compute.post_live_migration(c, i_ref, dest)

        # make sure every data is rewritten to destinatioin hostname.
        i_ref = db.instance_get(c, i_ref['id'])
        c1 = (i_ref['host'] == dest)
        flo_refs = db.floating_ip_get_all_by_host(c, dest)
        c2 = (len(flo_refs) != 0 and flo_refs[0]['address'] == flo_addr)
        self.assertTrue(c1 and c2)

        # cleanup
        db.instance_destroy(c, instance_id)
        db.volume_destroy(c, v_ref['id'])
        db.floating_ip_destroy(c, flo_addr)

    def test_run_kill_vm(self):
        """Detect when a vm is terminated behind the scenes"""
        self.stubs.Set(compute_manager.ComputeManager,
                '_report_driver_status', nop_report_driver_status)

        instance = self._create_fake_instance()

        self.compute.run_instance(self.context, instance['uuid'])

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        instance_name = instances[0].name
        self.compute.driver.test_remove_vm(instance_name)

        # Force the compute manager to do its periodic poll
        ctxt = context.get_admin_context()
        self.compute.periodic_tasks(ctxt, raise_on_error=True)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After force-killing instances: %s"), instances)
        self.assertEqual(len(instances), 1)
        self.assertEqual(power_state.NOSTATE, instances[0]['power_state'])

    def test_add_instance_fault(self):
        instance_uuid = str(utils.gen_uuid())

        def fake_db_fault_create(ctxt, values):
            expected = {
                'code': 500,
                'message': 'NotImplementedError',
                'details': '',
                'instance_uuid': instance_uuid,
            }
            self.assertEquals(expected, values)

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        self.compute.add_instance_fault_from_exc(ctxt, instance_uuid,
                                                 NotImplementedError())

    def test_add_instance_fault_http_exception(self):
        instance_uuid = str(utils.gen_uuid())

        def fake_db_fault_create(ctxt, values):
            expected = {
                'code': 404,
                'message': 'HTTPNotFound',
                'details': 'Error Details',
                'instance_uuid': instance_uuid,
            }
            self.assertEquals(expected, values)

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        self.compute.add_instance_fault_from_exc(ctxt, instance_uuid,
                                        exc.HTTPNotFound("Error Details"))


class ComputeAPITestCase(BaseTestCase):

    def setUp(self):
        super(ComputeAPITestCase, self).setUp()
        self.compute_api = compute.API()
        self.fake_image = {
            'id': 1,
            'properties': {'kernel_id': 1, 'ramdisk_id': 1},
        }

    def test_create_with_too_little_ram(self):
        """Test an instance type with too little memory"""

        inst_type = instance_types.get_default_instance_type()
        inst_type['memory_mb'] = 1

        def fake_show(*args):
            img = copy(self.fake_image)
            img['min_ram'] = 2
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        self.assertRaises(exception.InstanceTypeMemoryTooSmall,
            self.compute_api.create, self.context, inst_type, None)

        # Now increase the inst_type memory and make sure all is fine.
        inst_type['memory_mb'] = 2
        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, None)
        db.instance_destroy(self.context, refs[0]['id'])

    def test_create_with_too_little_disk(self):
        """Test an instance type with too little disk space"""

        inst_type = instance_types.get_default_instance_type()
        inst_type['local_gb'] = 1

        def fake_show(*args):
            img = copy(self.fake_image)
            img['min_disk'] = 2
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
            self.compute_api.create, self.context, inst_type, None)

        # Now increase the inst_type disk space and make sure all is fine.
        inst_type['local_gb'] = 2
        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, None)
        db.instance_destroy(self.context, refs[0]['id'])

    def test_create_just_enough_ram_and_disk(self):
        """Test an instance type with just enough ram and disk space"""

        inst_type = instance_types.get_default_instance_type()
        inst_type['local_gb'] = 2
        inst_type['memory_mb'] = 2

        def fake_show(*args):
            img = copy(self.fake_image)
            img['min_ram'] = 2
            img['min_disk'] = 2
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, None)
        db.instance_destroy(self.context, refs[0]['id'])

    def test_create_with_no_ram_and_disk_reqs(self):
        """Test an instance type with no min_ram or min_disk"""

        inst_type = instance_types.get_default_instance_type()
        inst_type['local_gb'] = 1
        inst_type['memory_mb'] = 1

        def fake_show(*args):
            return copy(self.fake_image)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, None)
        db.instance_destroy(self.context, refs[0]['id'])

    def test_create_instance_defaults_display_name(self):
        """Verify that an instance cannot be created without a display_name."""
        cases = [dict(), dict(display_name=None)]
        for instance in cases:
            (ref, resv_id) = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None, **instance)
            try:
                self.assertNotEqual(ref[0]['display_name'], None)
            finally:
                db.instance_destroy(self.context, ref[0]['id'])

    def test_create_instance_associates_security_groups(self):
        """Make sure create associates security groups"""
        group = self._create_group()
        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None,
                security_group=['testgroup'])
        try:
            self.assertEqual(len(db.security_group_get_by_instance(
                             self.context, ref[0]['id'])), 1)
            group = db.security_group_get(self.context, group['id'])
            self.assert_(len(group.instances) == 1)
        finally:
            db.security_group_destroy(self.context, group['id'])
            db.instance_destroy(self.context, ref[0]['id'])

    def test_create_instance_with_invalid_security_group_raises(self):
        instance_type = instance_types.get_default_instance_type()

        pre_build_len = len(db.instance_get_all(context.get_admin_context()))
        self.assertRaises(exception.SecurityGroupNotFoundForProject,
                          self.compute_api.create,
                          self.context,
                          instance_type=instance_type,
                          image_href=None,
                          security_group=['this_is_a_fake_sec_group'])
        self.assertEqual(pre_build_len,
                         len(db.instance_get_all(context.get_admin_context())))

    def test_default_hostname_generator(self):
        cases = [(None, 'server-1'), ('Hello, Server!', 'hello-server'),
                 ('<}\x1fh\x10e\x08l\x02l\x05o\x12!{>', 'hello'),
                 ('hello_server', 'hello-server')]
        for display_name, hostname in cases:
            (ref, resv_id) = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None,
                display_name=display_name)
            try:
                self.assertEqual(ref[0]['hostname'], hostname)
            finally:
                db.instance_destroy(self.context, ref[0]['id'])

    def test_destroy_instance_disassociates_security_groups(self):
        """Make sure destroying disassociates security groups"""
        group = self._create_group()

        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None,
                security_group=['testgroup'])
        try:
            db.instance_destroy(self.context, ref[0]['id'])
            group = db.security_group_get(self.context, group['id'])
            self.assert_(len(group.instances) == 0)
        finally:
            db.security_group_destroy(self.context, group['id'])

    def test_destroy_security_group_disassociates_instances(self):
        """Make sure destroying security groups disassociates instances"""
        group = self._create_group()

        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None,
                security_group=['testgroup'])

        try:
            db.security_group_destroy(self.context, group['id'])
            admin_deleted_context = context.get_admin_context(
                    read_deleted="only")
            group = db.security_group_get(admin_deleted_context, group['id'])
            self.assert_(len(group.instances) == 0)
        finally:
            db.instance_destroy(self.context, ref[0]['id'])

    def test_start(self):
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        self.compute.stop_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.start(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.STARTING)

        db.instance_destroy(self.context, instance['id'])

    def test_stop(self):
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.stop(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.STOPPING)

        db.instance_destroy(self.context, instance['id'])

    def test_delete(self):
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

        db.instance_destroy(self.context, instance['id'])

    def test_delete_soft(self):
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance['uuid'])

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_OFF)

        db.instance_destroy(self.context, instance['id'])

    def test_force_delete(self):
        """Ensure instance can be deleted after a soft delete"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_OFF)

        self.compute_api.force_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

    def test_suspend(self):
        """Ensure instance can be suspended"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        self.assertEqual(instance['task_state'], None)

        self.compute_api.suspend(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.SUSPENDING)

        db.instance_destroy(self.context, instance['id'])

    def test_resume(self):
        """Ensure instance can be resumed (if suspended)"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        instance_id = instance['id']
        self.compute.run_instance(self.context, instance_uuid )
        db.instance_update(self.context, instance_id,
                           {'vm_state': vm_states.SUSPENDED})
        instance = db.instance_get(self.context, instance_id)

        self.assertEqual(instance['task_state'], None)

        self.compute_api.resume(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.RESUMING)

        db.instance_destroy(self.context, instance['id'])

    def test_pause(self):
        """Ensure instance can be paused"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        self.assertEqual(instance['task_state'], None)

        self.compute_api.pause(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.PAUSING)

        db.instance_destroy(self.context, instance['id'])

    def test_unpause(self):
        """Ensure instance can be unpaused"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        self.assertEqual(instance['task_state'], None)

        self.compute.pause_instance(self.context, instance_uuid)
        # set the state that the instance gets when pause finishes
        db.instance_update(self.context, instance['uuid'],
                           {'vm_state': vm_states.PAUSED})
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])

        self.compute_api.unpause(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.UNPAUSING)

        db.instance_destroy(self.context, instance['id'])

    def test_restore(self):
        """Ensure instance can be restored from a soft delete"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_OFF)

        self.compute_api.restore(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_ON)

        db.instance_destroy(self.context, instance['id'])

    def test_rebuild(self):
        inst_ref = self._create_fake_instance()
        instance_uuid = inst_ref['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        image_ref = instance["image_ref"]
        password = "new_password"
        self.compute_api.rebuild(self.context, instance, image_ref, password)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.REBUILDING)

        db.instance_destroy(self.context, instance['id'])

    def test_reboot_soft(self):
        """Ensure instance can be soft rebooted"""
        inst_ref = self._create_fake_instance()
        instance_uuid = inst_ref['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['task_state'], None)

        reboot_type = "SOFT"
        self.compute_api.reboot(self.context, inst_ref, reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['task_state'], task_states.REBOOTING)

        db.instance_destroy(self.context, inst_ref['id'])

    def test_reboot_hard(self):
        """Ensure instance can be hard rebooted"""
        inst_ref = self._create_fake_instance()
        instance_uuid = inst_ref['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['task_state'], None)

        reboot_type = "HARD"
        self.compute_api.reboot(self.context, inst_ref, reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['task_state'], task_states.REBOOTING_HARD)

        db.instance_destroy(self.context, inst_ref['id'])

    def test_hostname_create(self):
        """Ensure instance hostname is set during creation."""
        inst_type = instance_types.get_instance_type_by_name('m1.tiny')
        (instances, _) = self.compute_api.create(self.context,
                                                 inst_type,
                                                 None,
                                                 display_name='test host')

        self.assertEqual('test-host', instances[0]['hostname'])

    def test_set_admin_password(self):
        """Ensure instance can have its admin password set"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute_api.set_admin_password(self.context, inst_ref)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

        self.compute.terminate_instance(self.context, instance_uuid)

    def test_rescue_unrescue(self):
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.ACTIVE)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.rescue(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.ACTIVE)
        self.assertEqual(instance['task_state'], task_states.RESCUING)

        params = {'vm_state': vm_states.RESCUED, 'task_state': None}
        db.instance_update(self.context, instance_uuid, params)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.compute_api.unrescue(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.RESCUED)
        self.assertEqual(instance['task_state'], task_states.UNRESCUING)

        self.compute.terminate_instance(self.context, instance_uuid)

    def test_snapshot(self):
        """Ensure a snapshot of an instance can be created"""
        instance = self._create_fake_instance()
        image = self.compute_api.snapshot(self.context, instance, 'snap1',
                                        {'extra_param': 'value1'})

        self.assertEqual(image['name'], 'snap1')
        properties = image['properties']
        self.assertTrue('backup_type' not in properties)
        self.assertEqual(properties['image_type'], 'snapshot')
        self.assertEqual(properties['instance_uuid'], instance['uuid'])
        self.assertEqual(properties['extra_param'], 'value1')

        db.instance_destroy(self.context, instance['id'])

    def test_snapshot_minram_mindisk_VHD(self):
        """Ensure a snapshots min_ram and min_disk are correct.

        A snapshot of a non-shrinkable VHD should have min_ram
        and min_disk set to that of the original instances flavor.
        """

        def fake_show(*args):
            img = copy(self.fake_image)
            img['disk_format'] = 'vhd'
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        instance = self._create_fake_instance()
        inst_params = {'local_gb': 2, 'memory_mb': 256}
        instance['instance_type'].update(inst_params)

        image = self.compute_api.snapshot(self.context, instance, 'snap1',
                                        {'extra_param': 'value1'})

        self.assertEqual(image['name'], 'snap1')
        self.assertEqual(image['min_ram'], 256)
        self.assertEqual(image['min_disk'], 2)
        properties = image['properties']
        self.assertTrue('backup_type' not in properties)
        self.assertEqual(properties['image_type'], 'snapshot')
        self.assertEqual(properties['instance_uuid'], instance['uuid'])
        self.assertEqual(properties['extra_param'], 'value1')

        db.instance_destroy(self.context, instance['id'])

    def test_snapshot_minram_mindisk(self):
        """Ensure a snapshots min_ram and min_disk are correct.

        A snapshot of an instance should have min_ram and min_disk
        set to that of the instances original image unless that
        image had a disk format of vhd.
        """

        def fake_show(*args):
            img = copy(self.fake_image)
            img['disk_format'] = 'raw'
            img['min_ram'] = 512
            img['min_disk'] = 1
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        instance = self._create_fake_instance()

        image = self.compute_api.snapshot(self.context, instance, 'snap1',
                                        {'extra_param': 'value1'})

        self.assertEqual(image['name'], 'snap1')
        self.assertEqual(image['min_ram'], 512)
        self.assertEqual(image['min_disk'], 1)
        properties = image['properties']
        self.assertTrue('backup_type' not in properties)
        self.assertEqual(properties['image_type'], 'snapshot')
        self.assertEqual(properties['instance_uuid'], instance['uuid'])
        self.assertEqual(properties['extra_param'], 'value1')

        db.instance_destroy(self.context, instance['id'])

    def test_snapshot_minram_mindisk_img_missing_minram(self):
        """Ensure a snapshots min_ram and min_disk are correct.

        Do not show an attribute that the orig img did not have.
        """

        def fake_show(*args):
            img = copy(self.fake_image)
            img['disk_format'] = 'raw'
            img['min_disk'] = 1
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        instance = self._create_fake_instance()

        image = self.compute_api.snapshot(self.context, instance, 'snap1',
                                        {'extra_param': 'value1'})

        self.assertEqual(image['name'], 'snap1')
        self.assertFalse('min_ram' in image)
        self.assertEqual(image['min_disk'], 1)
        properties = image['properties']
        self.assertTrue('backup_type' not in properties)
        self.assertEqual(properties['image_type'], 'snapshot')
        self.assertEqual(properties['instance_uuid'], instance['uuid'])
        self.assertEqual(properties['extra_param'], 'value1')

        db.instance_destroy(self.context, instance['id'])

    def test_snapshot_minram_mindisk_no_image(self):
        """Ensure a snapshots min_ram and min_disk are correct.

        A snapshots min_ram and min_disk should be set to default if
        an instances original image cannot be found.
        """

        def fake_show(*args):
            raise webob.exc.HTTPNotFound()

        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        instance = self._create_fake_instance()

        image = self.compute_api.snapshot(self.context, instance, 'snap1',
                                        {'extra_param': 'value1'})

        self.assertEqual(image['name'], 'snap1')

        # min_ram and min_disk are not returned when set to default
        self.assertFalse('min_ram' in image)
        self.assertFalse('min_disk' in image)

        properties = image['properties']
        self.assertTrue('backup_type' not in properties)
        self.assertEqual(properties['image_type'], 'snapshot')
        self.assertEqual(properties['instance_uuid'], instance['uuid'])
        self.assertEqual(properties['extra_param'], 'value1')

        db.instance_destroy(self.context, instance['id'])

    def test_backup(self):
        """Can't backup an instance which is already being backed up."""
        instance = self._create_fake_instance()
        image = self.compute_api.backup(self.context, instance,
                                        'backup1', 'DAILY', None,
                                        {'extra_param': 'value1'})

        self.assertEqual(image['name'], 'backup1')
        properties = image['properties']
        self.assertEqual(properties['backup_type'], 'DAILY')
        self.assertEqual(properties['image_type'], 'backup')
        self.assertEqual(properties['instance_uuid'], instance['uuid'])
        self.assertEqual(properties['extra_param'], 'value1')

        db.instance_destroy(self.context, instance['id'])

    def test_backup_conflict(self):
        """Can't backup an instance which is already being backed up."""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        instance_values = {'task_state': task_states.IMAGE_BACKUP}
        db.instance_update(self.context, instance_uuid, instance_values)
        instance = self.compute_api.get(self.context, instance_uuid)

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.backup,
                          self.context,
                          instance,
                          None,
                          None,
                          None)

        db.instance_destroy(self.context, instance['id'])

    def test_snapshot_conflict(self):
        """Can't snapshot an instance which is already being snapshotted."""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        instance_values = {'task_state': task_states.IMAGE_SNAPSHOT}
        db.instance_update(self.context, instance_uuid, instance_values)
        instance = self.compute_api.get(self.context, instance_uuid)

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.snapshot,
                          self.context,
                          instance,
                          None)

        db.instance_destroy(self.context, instance['id'])

    def test_resize_confirm_through_api(self):
        instance = self._create_fake_instance()
        context = self.context.elevated()
        self.compute.run_instance(self.context, instance['uuid'])
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute_api.resize(context, instance, '4')

        # create a fake migration record (manager does this)
        migration_ref = db.migration_create(context,
                {'instance_uuid': instance['uuid'],
                 'status': 'finished'})
        # set the state that the instance gets when resize finishes
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.RESIZE_VERIFY,
                            'vm_state': vm_states.ACTIVE})
        instance = db.instance_get_by_uuid(context, instance['uuid'])

        self.compute_api.confirm_resize(context, instance)
        self.compute.terminate_instance(context, instance['uuid'])

    def test_resize_revert_through_api(self):
        instance = self._create_fake_instance()
        context = self.context.elevated()
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute.run_instance(self.context, instance['uuid'])

        self.compute_api.resize(context, instance, '4')

        # create a fake migration record (manager does this)
        migration_ref = db.migration_create(context,
                {'instance_uuid': instance['uuid'],
                 'status': 'finished'})
        # set the state that the instance gets when resize finishes
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.RESIZE_VERIFY,
                            'vm_state': vm_states.ACTIVE})
        instance = db.instance_get_by_uuid(context, instance['uuid'])

        self.compute_api.revert_resize(context, instance)
        self.compute.terminate_instance(context, instance['uuid'])

    def test_resize_invalid_flavor_fails(self):
        """Ensure invalid flavors raise"""
        instance = self._create_fake_instance()
        context = self.context.elevated()
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute.run_instance(self.context, instance['uuid'])

        self.assertRaises(exception.NotFound, self.compute_api.resize,
                context, instance, 200)

        self.compute.terminate_instance(context, instance['uuid'])

    def test_resize_same_size_fails(self):
        """Ensure invalid flavors raise"""
        context = self.context.elevated()
        instance = self._create_fake_instance()
        instance = db.instance_get_by_uuid(context, instance['uuid'])

        self.compute.run_instance(self.context, instance['uuid'])

        self.assertRaises(exception.CannotResizeToSameSize,
                          self.compute_api.resize, context, instance, 1)

        self.compute.terminate_instance(context, instance['uuid'])

    def test_migrate(self):
        context = self.context.elevated()
        instance = self._create_fake_instance()
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute.run_instance(self.context, instance['uuid'])
        # Migrate simply calls resize() without a flavor_id.
        self.compute_api.resize(context, instance, None)
        self.compute.terminate_instance(context, instance['uuid'])

    def test_resize_request_spec(self):
        def _fake_cast(context, args):
            request_spec = args['args']['request_spec']
            instance_properties = request_spec['instance_properties']
            self.assertEqual(instance_properties['host'], 'host2')
            self.assertEqual(request_spec['avoid_original_host'], True)

        self.stubs.Set(self.compute_api, '_cast_scheduler_message',
                       _fake_cast)

        context = self.context.elevated()
        instance = self._create_fake_instance(dict(host='host2'))
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute.run_instance(self.context, instance['uuid'])
        try:
            self.compute_api.resize(context, instance, None)
        finally:
            self.compute.terminate_instance(context, instance['uuid'])

    def test_resize_request_spec_noavoid(self):
        def _fake_cast(context, args):
            request_spec = args['args']['request_spec']
            instance_properties = request_spec['instance_properties']
            self.assertEqual(instance_properties['host'], 'host2')
            self.assertEqual(request_spec['avoid_original_host'], False)

        self.stubs.Set(self.compute_api, '_cast_scheduler_message',
                       _fake_cast)
        self.flags(allow_resize_to_same_host=True)

        context = self.context.elevated()
        instance = self._create_fake_instance(dict(host='host2'))
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute.run_instance(self.context, instance['uuid'])
        try:
            self.compute_api.resize(context, instance, None)
        finally:
            self.compute.terminate_instance(context, instance['uuid'])

    def test_associate_floating_ip(self):
        """Ensure we can associate a floating ip with an instance"""
        called = {'associate': False}

        def fake_associate_ip_network_api(self, ctxt, floating_address,
                                          fixed_address):
            called['associate'] = True

        nw_info = fake_network.fake_get_instance_nw_info(self.stubs, 1)

        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return nw_info

        self.stubs.Set(nova.network.API, 'associate_floating_ip',
                       fake_associate_ip_network_api)

        self.stubs.Set(nova.network.API, 'get_instance_nw_info',
                       fake_get_nw_info)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        address = '0.1.2.3'

        self.compute.run_instance(self.context, instance_uuid)
        self.compute_api.associate_floating_ip(self.context,
                                               instance,
                                               address)
        self.assertTrue(called['associate'])
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_associate_floating_ip_no_fixed_ip(self):
        """Should fail if instance has no fixed ip."""

        def fake_get_nw_info(self, ctxt, instance):
            return []

        self.stubs.Set(nova.network.API, 'get_instance_nw_info',
                       fake_get_nw_info)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        address = '0.1.2.3'

        self.compute.run_instance(self.context, instance_uuid)
        self.assertRaises(exception.ApiError,
                          self.compute_api.associate_floating_ip,
                          self.context,
                          instance,
                          address)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_get(self):
        """Test get instance"""
        self.maxDiff = None
        c = context.get_admin_context()
        exp_instance = self._create_fake_instance()
        expected = dict(exp_instance.iteritems())
        expected['name'] = exp_instance['name']

        def fake_db_get(context, instance_uuid):
            return exp_instance

        self.stubs.Set(db, 'instance_get_by_uuid', fake_db_get)

        instance = self.compute_api.get(c, exp_instance['uuid'])
        self.assertEquals(expected, instance)

    def test_get_with_integer_id(self):
        """Test get instance with an integer id"""
        self.maxDiff = None
        c = context.get_admin_context()
        exp_instance = self._create_fake_instance()
        expected = dict(exp_instance.iteritems())
        expected['name'] = exp_instance['name']

        def fake_db_get(context, instance_id):
            return exp_instance

        self.stubs.Set(db, 'instance_get', fake_db_get)

        instance = self.compute_api.get(c, exp_instance['id'])
        self.assertEquals(expected, instance)

    def test_get_all_by_name_regexp(self):
        """Test searching instances by name (display_name)"""
        c = context.get_admin_context()
        instance1 = self._create_fake_instance({'display_name': 'woot'})
        instance2 = self._create_fake_instance({
                'display_name': 'woo'})
        instance3 = self._create_fake_instance({
                'display_name': 'not-woot'})

        instances = self.compute_api.get_all(c,
                search_opts={'name': 'woo.*'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance1['uuid'] in instance_uuids)
        self.assertTrue(instance2['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': 'woot.*'})
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertEqual(len(instances), 1)
        self.assertTrue(instance1['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': '.*oot.*'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance1['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': 'n.*'})
        self.assertEqual(len(instances), 1)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance3['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': 'noth.*'})
        self.assertEqual(len(instances), 0)

        db.instance_destroy(c, instance1['id'])
        db.instance_destroy(c, instance2['id'])
        db.instance_destroy(c, instance3['id'])

    def test_get_all_by_instance_name_regexp(self):
        """Test searching instances by name"""
        self.flags(instance_name_template='instance-%d')

        c = context.get_admin_context()
        instance1 = self._create_fake_instance()
        instance2 = self._create_fake_instance({'id': 2})
        instance3 = self._create_fake_instance({'id': 10})

        instances = self.compute_api.get_all(c,
                search_opts={'instance_name': 'instance.*'})
        self.assertEqual(len(instances), 3)

        instances = self.compute_api.get_all(c,
                search_opts={'instance_name': '.*\-\d$'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance1['uuid'] in instance_uuids)
        self.assertTrue(instance2['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'instance_name': 'i.*2'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance2['uuid'])

        db.instance_destroy(c, instance1['id'])
        db.instance_destroy(c, instance2['id'])
        db.instance_destroy(c, instance3['id'])

    def test_get_all_by_multiple_options_at_once(self):
        """Test searching by multiple options at once"""
        c = context.get_admin_context()
        network_manager = fake_network.FakeNetworkManager()
        self.stubs.Set(self.compute_api.network_api,
                       'get_instance_uuids_by_ip_filter',
                       network_manager.get_instance_uuids_by_ip_filter)
        self.stubs.Set(network_manager.db,
                       'instance_get_id_to_uuid_mapping',
                       db.instance_get_id_to_uuid_mapping)

        instance1 = self._create_fake_instance({'display_name': 'woot',
                                                'id': 0})
        instance2 = self._create_fake_instance({
                'display_name': 'woo',
                'id': 20})
        instance3 = self._create_fake_instance({
                'display_name': 'not-woot',
                'id': 30})

        # ip ends up matching 2nd octet here.. so all 3 match ip
        # but 'name' only matches one
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.1', 'name': 'not.*'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance3['uuid'])

        # ip ends up matching any ip with a '1' in the last octet..
        # so instance 1 and 3.. but name should only match #1
        # but 'name' only matches one
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.1$', 'name': '^woo.*'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance1['uuid'])

        # same as above but no match on name (name matches instance1
        # but the ip query doesn't
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.2$', 'name': '^woot.*'})
        self.assertEqual(len(instances), 0)

        # ip matches all 3... ipv6 matches #2+#3...name matches #3
        instances = self.compute_api.get_all(c,
                search_opts={'ip': '.*\.1',
                             'name': 'not.*',
                             'ip6': '^.*12.*34.*'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance3['uuid'])

        db.instance_destroy(c, instance1['id'])
        db.instance_destroy(c, instance2['id'])
        db.instance_destroy(c, instance3['id'])

    def test_get_all_by_image(self):
        """Test searching instances by image"""

        c = context.get_admin_context()
        instance1 = self._create_fake_instance({'image_ref': '1234'})
        instance2 = self._create_fake_instance({'image_ref': '4567'})
        instance3 = self._create_fake_instance({'image_ref': '4567'})

        instances = self.compute_api.get_all(c, search_opts={'image': '123'})
        self.assertEqual(len(instances), 0)

        instances = self.compute_api.get_all(c, search_opts={'image': '1234'})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance1['uuid'])

        instances = self.compute_api.get_all(c, search_opts={'image': '4567'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance2['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        # Test passing a list as search arg
        instances = self.compute_api.get_all(c,
                                    search_opts={'image': ['1234', '4567']})
        self.assertEqual(len(instances), 3)

        db.instance_destroy(c, instance1['id'])
        db.instance_destroy(c, instance2['id'])
        db.instance_destroy(c, instance3['id'])

    def test_get_all_by_flavor(self):
        """Test searching instances by image"""

        c = context.get_admin_context()
        instance1 = self._create_fake_instance({'instance_type_id': 1})
        instance2 = self._create_fake_instance({'instance_type_id': 2})
        instance3 = self._create_fake_instance({'instance_type_id': 2})

        # NOTE(comstud): Migrations set up the instance_types table
        # for us.  Therefore, we assume the following is true for
        # these tests:
        # instance_type_id 1 == flavor 3
        # instance_type_id 2 == flavor 1
        # instance_type_id 3 == flavor 4
        # instance_type_id 4 == flavor 5
        # instance_type_id 5 == flavor 2

        instances = self.compute_api.get_all(c,
                search_opts={'flavor': 5})
        self.assertEqual(len(instances), 0)

        self.assertRaises(exception.FlavorNotFound,
                self.compute_api.get_all,
                c, search_opts={'flavor': 99})

        instances = self.compute_api.get_all(c, search_opts={'flavor': 3})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['id'], instance1['id'])

        instances = self.compute_api.get_all(c, search_opts={'flavor': 1})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance2['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        db.instance_destroy(c, instance1['id'])
        db.instance_destroy(c, instance2['id'])
        db.instance_destroy(c, instance3['id'])

    def test_get_all_by_state(self):
        """Test searching instances by state"""

        c = context.get_admin_context()
        instance1 = self._create_fake_instance({
            'power_state': power_state.SHUTDOWN,
        })
        instance2 = self._create_fake_instance({
            'power_state': power_state.RUNNING,
        })
        instance3 = self._create_fake_instance({
            'power_state': power_state.RUNNING,
        })

        instances = self.compute_api.get_all(c,
                search_opts={'power_state': power_state.SUSPENDED})
        self.assertEqual(len(instances), 0)

        instances = self.compute_api.get_all(c,
                search_opts={'power_state': power_state.SHUTDOWN})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance1['uuid'])

        instances = self.compute_api.get_all(c,
                search_opts={'power_state': power_state.RUNNING})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance2['uuid'] in instance_uuids)
        self.assertTrue(instance3['uuid'] in instance_uuids)

        # Test passing a list as search arg
        instances = self.compute_api.get_all(c,
                search_opts={'power_state': [power_state.SHUTDOWN,
                        power_state.RUNNING]})
        self.assertEqual(len(instances), 3)

        db.instance_destroy(c, instance1['id'])
        db.instance_destroy(c, instance2['id'])
        db.instance_destroy(c, instance3['id'])

    def test_get_all_by_metadata(self):
        """Test searching instances by metadata"""

        c = context.get_admin_context()
        instance0 = self._create_fake_instance()
        instance1 = self._create_fake_instance({
                'metadata': {'key1': 'value1'}})
        instance2 = self._create_fake_instance({
                'metadata': {'key2': 'value2'}})
        instance3 = self._create_fake_instance({
                'metadata': {'key3': 'value3'}})
        instance4 = self._create_fake_instance({
                'metadata': {'key3': 'value3',
                             'key4': 'value4'}})

        # get all instances
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {}})
        self.assertEqual(len(instances), 5)

        # wrong key/value combination
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key1': 'value3'}})
        self.assertEqual(len(instances), 0)

        # non-existing keys
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key5': 'value1'}})
        self.assertEqual(len(instances), 0)

        # find existing instance
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key2': 'value2'}})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance2['uuid'])

        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key3': 'value3'}})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance3['uuid'] in instance_uuids)
        self.assertTrue(instance4['uuid'] in instance_uuids)

        # multiple criterias as a dict
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': {'key3': 'value3',
                                          'key4': 'value4'}})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance4['uuid'])

        # multiple criterias as a list
        instances = self.compute_api.get_all(c,
                search_opts={'metadata': [{'key4': 'value4'},
                                          {'key3': 'value3'}]})
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['uuid'], instance4['uuid'])

        db.instance_destroy(c, instance0['id'])
        db.instance_destroy(c, instance1['id'])
        db.instance_destroy(c, instance2['id'])
        db.instance_destroy(c, instance3['id'])
        db.instance_destroy(c, instance4['id'])

    def test_instance_metadata(self):
        """Test searching instances by state"""
        _context = context.get_admin_context()
        instance = self._create_fake_instance({'metadata': {'key1': 'value1'}})

        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key1': 'value1'})

        self.compute_api.update_instance_metadata(_context, instance,
                                                  {'key2': 'value2'})
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key1': 'value1', 'key2': 'value2'})

        new_metadata = {'key2': 'bah', 'key3': 'value3'}
        self.compute_api.update_instance_metadata(_context, instance,
                                                  new_metadata, delete=True)
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, new_metadata)

        self.compute_api.delete_instance_metadata(_context, instance, 'key2')
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key3': 'value3'})

        db.instance_destroy(_context, instance['id'])

    def test_get_instance_faults(self):
        """Get an instances latest fault"""
        instance = self._create_fake_instance()

        fault_fixture = {
                'code': 404,
                'instance_uuid': instance['uuid'],
                'message': "HTTPNotFound",
                'details': "Stock details for test",
                'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
            }

        def return_fault(_ctxt, instance_uuids):
            return dict.fromkeys(instance_uuids, [fault_fixture])

        self.stubs.Set(nova.db,
                       'instance_fault_get_by_instance_uuids',
                       return_fault)

        _context = context.get_admin_context()
        output = self.compute_api.get_instance_faults(_context, [instance])
        expected = {instance['uuid']: [fault_fixture]}
        self.assertEqual(output, expected)

        db.instance_destroy(_context, instance['id'])

    @staticmethod
    def _parse_db_block_device_mapping(bdm_ref):
        attr_list = ('delete_on_termination', 'device_name', 'no_device',
                     'virtual_name', 'volume_id', 'volume_size', 'snapshot_id')
        bdm = {}
        for attr in attr_list:
            val = bdm_ref.get(attr, None)
            if val:
                bdm[attr] = val

        return bdm

    def test_update_block_device_mapping(self):
        swap_size = 1
        instance_type = {'swap': swap_size}
        instance = self._create_fake_instance()
        mappings = [
                {'virtual': 'ami', 'device': 'sda1'},
                {'virtual': 'root', 'device': '/dev/sda1'},

                {'virtual': 'swap', 'device': 'sdb4'},
                {'virtual': 'swap', 'device': 'sdb3'},
                {'virtual': 'swap', 'device': 'sdb2'},
                {'virtual': 'swap', 'device': 'sdb1'},

                {'virtual': 'ephemeral0', 'device': 'sdc1'},
                {'virtual': 'ephemeral1', 'device': 'sdc2'},
                {'virtual': 'ephemeral2', 'device': 'sdc3'}]
        block_device_mapping = [
                # root
                {'device_name': '/dev/sda1',
                 'snapshot_id': 0x12345678,
                 'delete_on_termination': False},


                # overwrite swap
                {'device_name': '/dev/sdb2',
                 'snapshot_id': 0x23456789,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdb3',
                 'snapshot_id': 0x3456789A},
                {'device_name': '/dev/sdb4',
                 'no_device': True},

                # overwrite ephemeral
                {'device_name': '/dev/sdc2',
                 'snapshot_id': 0x456789AB,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdc3',
                 'snapshot_id': 0x56789ABC},
                {'device_name': '/dev/sdc4',
                 'no_device': True},

                # volume
                {'device_name': '/dev/sdd1',
                 'snapshot_id': 0x87654321,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdd2',
                 'snapshot_id': 0x98765432},
                {'device_name': '/dev/sdd3',
                 'snapshot_id': 0xA9875463},
                {'device_name': '/dev/sdd4',
                 'no_device': True}]

        self.compute_api._update_image_block_device_mapping(
            self.context, instance_type, instance['id'], mappings)

        bdms = [self._parse_db_block_device_mapping(bdm_ref)
                for bdm_ref in db.block_device_mapping_get_all_by_instance(
                    self.context, instance['id'])]
        expected_result = [
            {'virtual_name': 'swap', 'device_name': '/dev/sdb1',
             'volume_size': swap_size},
            {'virtual_name': 'ephemeral0', 'device_name': '/dev/sdc1'},

            # NOTE(yamahata): ATM only ephemeral0 is supported.
            #                 they're ignored for now
            #{'virtual_name': 'ephemeral1', 'device_name': '/dev/sdc2'},
            #{'virtual_name': 'ephemeral2', 'device_name': '/dev/sdc3'}
            ]
        bdms.sort()
        expected_result.sort()
        self.assertDictListMatch(bdms, expected_result)

        self.compute_api._update_block_device_mapping(
            self.context, instance_types.get_default_instance_type(),
            instance['id'], block_device_mapping)
        bdms = [self._parse_db_block_device_mapping(bdm_ref)
                for bdm_ref in db.block_device_mapping_get_all_by_instance(
                    self.context, instance['id'])]
        expected_result = [
            {'snapshot_id': 0x12345678, 'device_name': '/dev/sda1'},

            {'virtual_name': 'swap', 'device_name': '/dev/sdb1',
             'volume_size': swap_size},
            {'snapshot_id': 0x23456789, 'device_name': '/dev/sdb2'},
            {'snapshot_id': 0x3456789A, 'device_name': '/dev/sdb3'},
            {'no_device': True, 'device_name': '/dev/sdb4'},

            {'virtual_name': 'ephemeral0', 'device_name': '/dev/sdc1'},
            {'snapshot_id': 0x456789AB, 'device_name': '/dev/sdc2'},
            {'snapshot_id': 0x56789ABC, 'device_name': '/dev/sdc3'},
            {'no_device': True, 'device_name': '/dev/sdc4'},

            {'snapshot_id': 0x87654321, 'device_name': '/dev/sdd1'},
            {'snapshot_id': 0x98765432, 'device_name': '/dev/sdd2'},
            {'snapshot_id': 0xA9875463, 'device_name': '/dev/sdd3'},
            {'no_device': True, 'device_name': '/dev/sdd4'}]
        bdms.sort()
        expected_result.sort()
        self.assertDictListMatch(bdms, expected_result)

        for bdm in db.block_device_mapping_get_all_by_instance(
            self.context, instance['id']):
            db.block_device_mapping_destroy(self.context, bdm['id'])
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_volume_size(self):
        local_size = 2
        swap_size = 3
        inst_type = {'local_gb': local_size, 'swap': swap_size}
        self.assertEqual(self.compute_api._volume_size(inst_type,
                                                          'ephemeral0'),
                         local_size)
        self.assertEqual(self.compute_api._volume_size(inst_type,
                                                       'ephemeral1'),
                         0)
        self.assertEqual(self.compute_api._volume_size(inst_type,
                                                       'swap'),
                         swap_size)

    def test_reservation_id_one_instance(self):
        """Verify building an instance has a reservation_id that
        matches return value from create"""
        (refs, resv_id) = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None)
        try:
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]['reservation_id'], resv_id)
        finally:
            db.instance_destroy(self.context, refs[0]['id'])

    def test_reservation_ids_two_instances(self):
        """Verify building 2 instances at once results in a
        reservation_id being returned equal to reservation id set
        in both instances
        """
        (refs, resv_id) = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None,
                min_count=2, max_count=2)
        try:
            self.assertEqual(len(refs), 2)
            self.assertNotEqual(resv_id, None)
        finally:
            for instance in refs:
                self.assertEqual(instance['reservation_id'], resv_id)

        db.instance_destroy(self.context, refs[0]['id'])

    def test_create_with_specified_reservation_id(self):
        """Verify building instances with a specified
        reservation_id results in the correct reservation_id
        being set
        """

        # We need admin context to be able to specify our own
        # reservation_ids.
        context = self.context.elevated()
        # 1 instance
        (refs, resv_id) = self.compute_api.create(context,
                instance_types.get_default_instance_type(), None,
                min_count=1, max_count=1, reservation_id='meow')
        try:
            self.assertEqual(len(refs), 1)
            self.assertEqual(resv_id, 'meow')
        finally:
            self.assertEqual(refs[0]['reservation_id'], resv_id)

        # 2 instances
        (refs, resv_id) = self.compute_api.create(context,
                instance_types.get_default_instance_type(), None,
                min_count=2, max_count=2, reservation_id='woof')
        try:
            self.assertEqual(len(refs), 2)
            self.assertEqual(resv_id, 'woof')
        finally:
            for instance in refs:
                self.assertEqual(instance['reservation_id'], resv_id)
            db.instance_destroy(self.context, refs[0]['id'])

    def test_instance_name_template(self):
        """Test the instance_name template"""
        self.flags(instance_name_template='instance-%d')
        i_ref = self._create_fake_instance()
        instance_id = i_ref['id']
        self.assertEqual(i_ref['name'], 'instance-%d' % i_ref['id'])
        db.instance_destroy(self.context, i_ref['id'])

        self.flags(instance_name_template='instance-%(uuid)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], 'instance-%s' % i_ref['uuid'])
        db.instance_destroy(self.context, i_ref['id'])

        self.flags(instance_name_template='%(id)d-%(uuid)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], '%d-%s' %
                (i_ref['id'], i_ref['uuid']))
        db.instance_destroy(self.context, i_ref['id'])

        # not allowed.. default is uuid
        self.flags(instance_name_template='%(name)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], i_ref['uuid'])
        db.instance_destroy(self.context, i_ref['id'])

    def test_add_remove_fixed_ip(self):
        instance = self._create_fake_instance()
        self.compute_api.add_fixed_ip(self.context, instance, '1')
        self.compute_api.remove_fixed_ip(self.context, instance, '192.168.1.1')
        self.compute_api.delete(self.context, instance)

    def test_attach_volume_invalid(self):
        self.assertRaises(exception.ApiError,
                self.compute_api.attach_volume,
                None,
                None,
                None,
                '/dev/invalid')

    def test_attach_volume(self):
        instance_id = 1
        instance_uuid = utils.gen_uuid()
        volume_id = 1

        for device in ('/dev/sda', '/dev/xvda'):
            # creating mocks
            self.mox.StubOutWithMock(self.compute_api.volume_api,
                    'check_attach')
            self.mox.StubOutWithMock(self.compute_api, 'get')
            self.mox.StubOutWithMock(rpc, 'cast')

            rpc.cast(
                    mox.IgnoreArg(),
                    mox.IgnoreArg(), {"method": "attach_volume",
                        "args": {'volume_id': volume_id,
                                 'instance_uuid': instance_uuid,
                                 'mountpoint': device}})

            self.compute_api.volume_api.check_attach(
                    mox.IgnoreArg(),
                    volume_id=volume_id).AndReturn(
                            {'id': volume_id, 'status': 'available',
                                'attach_status': 'detached'})

            self.compute_api.get(
                    mox.IgnoreArg(),
                    mox.IgnoreArg()).AndReturn({
                        'id': instance_id,
                        'uuid': instance_uuid,
                        'host': 'fake'})

            self.mox.ReplayAll()
            self.compute_api.attach_volume(None, None, volume_id, device)
            self.mox.UnsetStubs()

    def test_vnc_console(self):
        """Make sure we can a vnc console for an instance."""
        def vnc_rpc_call_wrapper(*args, **kwargs):
            return {'token': 'asdf', 'host': '0.0.0.0', 'port': 8080}

        self.stubs.Set(rpc, 'call', vnc_rpc_call_wrapper)

        instance = self._create_fake_instance()
        console = self.compute_api.get_vnc_console(self.context, instance)
        self.compute_api.delete(self.context, instance)

    def test_ajax_console(self):
        """Make sure we can a vnc console for an instance."""
        def ajax_rpc_call_wrapper(*args, **kwargs):
            return {'token': 'asdf', 'host': '0.0.0.0', 'port': 8080}

        self.stubs.Set(rpc, 'call', ajax_rpc_call_wrapper)

        instance = self._create_fake_instance()
        console = self.compute_api.get_ajax_console(self.context, instance)
        self.compute_api.delete(self.context, instance)

    def test_console_output(self):
        instance = self._create_fake_instance()
        console = self.compute_api.get_console_output(self.context, instance)

    def test_attach_volume(self):
        """Ensure instance can be soft rebooted"""

        def fake_check_attach(*args, **kwargs):
            pass

        self.stubs.Set(nova.volume.api.API, 'check_attach', fake_check_attach)

        instance = self._create_fake_instance()
        self.compute_api.attach_volume(self.context, instance, 1, '/dev/vdb')

    def test_inject_network_info(self):
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        instance = self.compute_api.get(self.context, instance['uuid'])
        self.compute_api.inject_network_info(self.context, instance)
        self.compute_api.delete(self.context, instance)

    def test_reset_network(self):
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        instance = self.compute_api.get(self.context, instance['uuid'])
        self.compute_api.reset_network(self.context, instance)

    def test_lock(self):
        instance = self._create_fake_instance()
        self.compute_api.lock(self.context, instance)
        self.compute_api.delete(self.context, instance)

    def test_unlock(self):
        instance = self._create_fake_instance()
        self.compute_api.unlock(self.context, instance)
        self.compute_api.delete(self.context, instance)

    def test_get_lock(self):
        instance = self._create_fake_instance()
        self.assertFalse(self.compute_api.get_lock(self.context, instance))
        db.instance_update(self.context, instance['uuid'], {'locked': True})
        self.assertTrue(self.compute_api.get_lock(self.context, instance))

    def test_add_remove_security_group(self):
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        instance = self.compute_api.get(self.context, instance['uuid'])
        security_group_name = self._create_group()['name']
        self.compute_api.add_security_group(self.context,
                                            instance,
                                            security_group_name)
        self.compute_api.remove_security_group(self.context,
                                               instance,
                                               security_group_name)

    def test_get_diagnostics(self):
        instance = self._create_fake_instance()
        self.compute_api.get_diagnostics(self.context, instance)
        self.compute_api.delete(self.context, instance)

    def test_get_actions(self):

        expected = [{'id': 1,
                    'instance_id': 5,
                    'action': 'rebuild',
                    'error': '',
                    }]

        def fake_get_actions(context, instance):
            return expected

        self.stubs.Set(nova.db, 'instance_get_actions',
                       fake_get_actions)

        instance = self._create_fake_instance()
        context = self.context.elevated()
        actual = self.compute_api.get_actions(context, instance)
        self.assertEqual(expected, actual)

        self.compute_api.delete(self.context, instance)

    def test_inject_file(self):
        """Ensure we can write a file to an instance"""
        instance = self._create_fake_instance()
        self.compute_api.inject_file(self.context, instance,
                                     "/tmp/test", "File Contents")
        db.instance_destroy(self.context, instance['id'])
