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
"""Tests for compute service"""

import copy
import datetime
import sys
import time

import mox

import nova
import nova.common.policy
from nova import compute
from nova.compute import aggregate_states
from nova.compute import api as compute_api
from nova.compute import instance_types
from nova.compute import manager as compute_manager
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.image import fake as fake_image
from nova import log as logging
from nova.notifier import test_notifier
from nova.openstack.common import importutils
import nova.policy
from nova import quota
from nova import rpc
from nova.rpc import common as rpc_common
from nova.scheduler import driver as scheduler_driver
from nova import test
from nova.tests import fake_network
from nova import utils
import nova.volume


QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
flags.DECLARE('stub_network', 'nova.compute.manager')
flags.DECLARE('live_migration_retry_count', 'nova.compute.manager')
flags.DECLARE('additional_compute_capabilities', 'nova.compute.manager')


FAKE_IMAGE_REF = 'fake-image-ref'
orig_rpc_call = rpc.call
orig_rpc_cast = rpc.cast


def rpc_call_wrapper(context, topic, msg, do_cast=True):
    """Stub out the scheduler creating the instance entry"""
    if (topic == FLAGS.scheduler_topic and
        msg['method'] == 'run_instance'):
        request_spec = msg['args']['request_spec']
        reservations = msg['args'].get('reservations')
        scheduler = scheduler_driver.Scheduler
        num_instances = request_spec.get('num_instances', 1)
        instances = []
        for num in xrange(num_instances):
            request_spec['instance_properties']['launch_index'] = num
            instance = scheduler().create_instance_db_entry(
                    context, request_spec, reservations)
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
        self.compute = importutils.import_object(FLAGS.compute_manager)

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)
        test_notifier.NOTIFICATIONS = []

        def fake_show(meh, context, id):
            return {'id': id, 'min_disk': None, 'min_ram': None,
                    'properties': {'kernel_id': 'fake_kernel_id',
                                   'ramdisk_id': 'fake_ramdisk_id',
                                   'something_else': 'meow'}}

        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)
        self.stubs.Set(rpc, 'call', rpc_call_wrapper)
        self.stubs.Set(rpc, 'cast', rpc_cast_wrapper)

    def tearDown(self):
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
        inst['image_ref'] = FAKE_IMAGE_REF
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['host'] = 'fake_host'
        type_id = instance_types.get_instance_type_by_name(type_name)['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['memory_mb'] = 0
        inst['vcpus'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
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
        inst['memory_mb'] = 1024
        inst['vcpus'] = 1
        inst['root_gb'] = 20
        inst['ephemeral_gb'] = 10
        inst['flavorid'] = '1'
        inst['swap'] = 2048
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
    def setUp(self):
        def fake_get_nw_info(cls, ctxt, instance, *args, **kwargs):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1,
                                                          spectacular=True)

        super(ComputeTestCase, self).setUp()
        self.stubs.Set(nova.network.API, 'get_instance_nw_info',
                       fake_get_nw_info)
        self.stubs.Set(nova.network.API, 'allocate_for_instance',
                       fake_get_nw_info)

    def tearDown(self):
        super(ComputeTestCase, self).tearDown()
        utils.clear_time_override()

    def test_wrap_instance_fault(self):
        inst_uuid = "fake_uuid"

        called = {'fault_added': False}

        def did_it_add_fault(*args):
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

        def did_it_add_fault(*args):
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

    def test_default_access_ip(self):
        self.flags(default_access_ip_network_name='test1', stub_network=False)
        instance = self._create_fake_instance()

        try:
            self.compute.run_instance(self.context, instance['uuid'],
                    is_first_time=True)
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertEqual(instance.access_ip_v4, '192.168.1.100')
            self.assertEqual(instance.access_ip_v6, '2001:db8:0:1::1')
        finally:
            db.instance_destroy(self.context, instance['id'])

    def test_no_default_access_ip(self):
        instance = self._create_fake_instance()

        try:
            self.compute.run_instance(self.context, instance['uuid'],
                    is_first_time=True)
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertFalse(instance.access_ip_v4)
            self.assertFalse(instance.access_ip_v6)
        finally:
            db.instance_destroy(self.context, instance['id'])

    def test_fail_to_schedule_persists(self):
        """check the persistence of the ERROR(scheduling) state"""
        self._create_instance(params={'vm_state': vm_states.ERROR,
                                      'task_state': task_states.SCHEDULING})
        #check state is failed even after the periodic poll
        self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.SCHEDULING})

    def test_run_instance_setup_block_device_mapping_fail(self):
        """ block device mapping failure test.

        Make sure that when there is a block device mapping problem,
        the instance goes to ERROR state, keeping the task state
        """
        def fake(*args, **kwargs):
            raise test.TestingException()
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       '_setup_block_device_mapping', fake)
        instance_uuid = self._create_instance()
        self.assertRaises(test.TestingException, self.compute.run_instance,
                          self.context, instance_uuid)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.BLOCK_DEVICE_MAPPING})
        self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.BLOCK_DEVICE_MAPPING})

    def test_run_instance_spawn_fail(self):
        """ spawn failure test.

        Make sure that when there is a spawning problem,
        the instance goes to ERROR state, keeping the task state"""
        def fake(*args, **kwargs):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver, 'spawn', fake)
        instance_uuid = self._create_instance()
        self.assertRaises(test.TestingException, self.compute.run_instance,
                          self.context, instance_uuid)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.SPAWNING})
        self.compute.periodic_tasks(context.get_admin_context())
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
        image_ref = instance['image_ref']

        self.compute.run_instance(self.context, instance_uuid)
        self.compute.rebuild_instance(self.context, instance_uuid,
                image_ref, image_ref)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_rebuild_launch_time(self):
        """Ensure instance can be rebuilt"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        utils.set_time_override(old_time)
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        image_ref = instance['image_ref']

        self.compute.run_instance(self.context, instance_uuid)
        utils.set_time_override(cur_time)
        self.compute.rebuild_instance(self.context, instance_uuid,
                image_ref, image_ref)
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(cur_time, instance['launched_at'])
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

    def test_set_admin_password_bad_state(self):
        """Test setting password while instance is rebuilding."""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        db.instance_update(self.context, instance['uuid'], {
            "power_state": power_state.NOSTATE,
        })
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])

        self.assertEqual(instance['power_state'], power_state.NOSTATE)

        def fake_driver_get_info(self2, _instance):
            return {'state': power_state.NOSTATE,
                    'max_mem': 0,
                    'mem': 0,
                    'num_cpu': 2,
                    'cpu_time': 0}

        self.stubs.Set(nova.virt.fake.FakeConnection, 'get_info',
                       fake_driver_get_info)

        self.assertRaises(exception.Invalid,
                          self.compute.set_admin_password,
                          self.context,
                          instance['uuid'])
        self.compute.terminate_instance(self.context, instance['uuid'])

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
        self.assertRaises(exception.NovaException,
                          self.compute.set_admin_password,
                          self.context, instance_uuid)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ERROR)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

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
            raise test.TestingException()

        self.stubs.Set(self.compute.driver, 'snapshot', fake_snapshot)

        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        self.assertRaises(test.TestingException,
                          self.compute.snapshot_instance,
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

    def test_novnc_vnc_console(self):
        """Make sure we can a vnc console for an instance."""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        console = self.compute.get_vnc_console(self.context,
                                               instance['uuid'],
                                               'novnc')
        self.assert_(console)
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_xvpvnc_vnc_console(self):
        """Make sure we can a vnc console for an instance."""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        console = self.compute.get_vnc_console(self.context,
                                               instance['uuid'],
                                               'xvpvnc')
        self.assert_(console)
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_invalid_vnc_console_type(self):
        """Make sure we can a vnc console for an instance."""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])

        self.assertRaises(exception.ConsoleTypeInvalid,
                          self.compute.get_vnc_console,
                          self.context,
                          instance['uuid'],
                          'invalid')
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

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
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

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_run_instance_usage_notification(self):
        """Ensure run instance generates apropriate usage notification"""
        inst_ref = self._create_fake_instance()
        instance_uuid = inst_ref['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['event_type'], 'compute.instance.create.start')
        # The last event is the one with the sugar in it.
        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.create.end')
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
        image_ref_url = utils.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_terminate_usage_notification(self):
        """Ensure terminate_instance generates apropriate usage notification"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        utils.set_time_override(old_time)

        inst_ref = self._create_fake_instance()
        self.compute.run_instance(self.context, inst_ref['uuid'])
        test_notifier.NOTIFICATIONS = []
        utils.set_time_override(cur_time)
        self.compute.terminate_instance(self.context, inst_ref['uuid'])

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 4)

        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.delete.start')
        msg1 = test_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg1['event_type'],
                                            'compute.instance.shutdown.start')
        msg1 = test_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg1['event_type'], 'compute.instance.shutdown.end')
        msg1 = test_notifier.NOTIFICATIONS[3]
        self.assertEquals(msg1['event_type'], 'compute.instance.delete.end')
        payload = msg1['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], inst_ref.uuid)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertTrue('deleted_at' in payload)
        self.assertEqual(payload['deleted_at'], str(cur_time))
        image_ref_url = utils.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)

    def test_run_instance_existing(self):
        """Ensure failure when running an instance that already exists"""
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance['uuid'])
        self.assertRaises(exception.Invalid,
                          self.compute.run_instance,
                          self.context,
                          instance['uuid'])
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_instance_set_to_error_on_uncaught_exception(self):
        """Test that instance is set to error state when exception is raised"""
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.mox.StubOutWithMock(self.compute.network_api,
                                 "allocate_for_instance")
        self.compute.network_api.allocate_for_instance(
                mox.IgnoreArg(),
                mox.IgnoreArg(),
                requested_networks=None,
                vpn=False).AndRaise(rpc_common.RemoteError())

        self.flags(stub_network=False)

        self.mox.ReplayAll()

        self.assertRaises(rpc_common.RemoteError,
                          self.compute.run_instance,
                          self.context,
                          instance_uuid)

        instance = db.instance_get_by_uuid(context.get_admin_context(),
                                           instance_uuid)
        self.assertEqual(vm_states.ERROR, instance['vm_state'])

        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_instance_termination_exception_sets_error(self):
        """Test that we handle InstanceTerminationFailure
        which is propagated up from the underlying driver.
        """
        instance = self._create_fake_instance()

        def fake_delete_instance(context, instance):
            raise exception.InstanceTerminationFailure(reason='')

        self.stubs.Set(self.compute, '_delete_instance',
                       fake_delete_instance)

        self.compute.terminate_instance(self.context, instance['uuid'])
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)

    def test_network_is_deallocated_on_spawn_failure(self):
        """When a spawn fails the network must be deallocated"""
        instance = self._create_fake_instance()

        self.mox.StubOutWithMock(self.compute, "_setup_block_device_mapping")
        self.compute._setup_block_device_mapping(
                mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(rpc.common.RemoteError('', '', ''))

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

        non_admin_context = context.RequestContext(None,
                                                   None,
                                                   is_admin=False)

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

        context = self.context.elevated()
        instance = self._create_fake_instance()
        self.compute.prep_resize(context, instance['uuid'], 1, {},
                                 filter_properties={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'pre-migrating')
        self.compute.finish_resize(context, instance['uuid'],
                                   int(migration_ref['id']), {}, {})
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_finish_resize_handles_error(self):
        """Make sure we don't leave the instance in RESIZE on error"""

        def throw_up(*args, **kwargs):
            raise test.TestingException()

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', throw_up)

        context = self.context.elevated()
        instance = self._create_fake_instance()
        self.compute.prep_resize(context, instance['uuid'], 1, {},
                                 filter_properties={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'pre-migrating')

        self.assertRaises(test.TestingException, self.compute.finish_resize,
                          context, instance['uuid'],
                          int(migration_ref['id']), {}, {})

        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_rebuild_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        utils.set_time_override(old_time)
        inst_ref = self._create_fake_instance()
        instance_uuid = inst_ref['uuid']
        self.compute.run_instance(self.context, instance_uuid)
        utils.set_time_override(cur_time)

        test_notifier.NOTIFICATIONS = []
        instance = db.instance_get_by_uuid(self.context, instance_uuid)

        image_ref = instance["image_ref"]
        new_image_ref = image_ref + '-new_image_ref'
        db.instance_update(self.context, instance_uuid,
                {'image_ref': new_image_ref})

        password = "new_password"

        self.compute._rebuild_instance(self.context, instance_uuid,
                image_ref, new_image_ref, dict(new_pass=password))

        instance = db.instance_get_by_uuid(self.context, instance_uuid)

        image_ref_url = utils.generate_image_url(image_ref)
        new_image_ref_url = utils.generate_image_url(new_image_ref)

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 3)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['event_type'],
                          'compute.instance.exists')
        self.assertEquals(msg['payload']['image_ref_url'], image_ref_url)
        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg['event_type'],
                          'compute.instance.rebuild.start')
        self.assertEquals(msg['payload']['image_ref_url'], new_image_ref_url)
        msg = test_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg['event_type'],
                          'compute.instance.rebuild.end')
        self.assertEquals(msg['priority'], 'INFO')
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
        self.assertEqual(payload['launched_at'], str(cur_time))
        self.assertEquals(payload['image_ref_url'], new_image_ref_url)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_finish_resize_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        utils.set_time_override(old_time)
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        context = self.context.elevated()
        old_type_id = instance_types.get_instance_type_by_name(
                                                'm1.tiny')['id']
        new_type_id = instance_types.get_instance_type_by_name(
                                                'm1.small')['id']
        self.compute.run_instance(self.context, instance_uuid)

        db.instance_update(self.context, instance_uuid, {'host': 'foo'})
        self.compute.prep_resize(context, instance_uuid, new_type_id, {},
                                 filter_properties={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                                                instance_uuid,
                                                'pre-migrating')
        self.compute.resize_instance(context, instance_uuid,
                                     migration_ref['id'], {})
        utils.set_time_override(cur_time)
        test_notifier.NOTIFICATIONS = []

        self.compute.finish_resize(context, instance['uuid'],
                                   int(migration_ref['id']), {}, {})

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['event_type'],
                          'compute.instance.finish_resize.start')
        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg['event_type'],
                          'compute.instance.finish_resize.end')
        self.assertEquals(msg['priority'], 'INFO')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance_uuid)
        self.assertEquals(payload['instance_type'], 'm1.small')
        self.assertEquals(str(payload['instance_type_id']), str(new_type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEqual(payload['launched_at'], str(cur_time))
        image_ref_url = utils.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(context, instance_uuid)

    def test_resize_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        utils.set_time_override(old_time)
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance_uuid)
        utils.set_time_override(cur_time)
        test_notifier.NOTIFICATIONS = []

        db.instance_update(self.context, instance_uuid, {'host': 'foo'})
        self.compute.prep_resize(context, instance_uuid, 1, {},
                                 filter_properties={})
        db.migration_get_by_instance_and_status(context,
                                                instance_uuid,
                                                'pre-migrating')

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 3)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['event_type'],
                          'compute.instance.exists')
        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg['event_type'],
                          'compute.instance.resize.prep.start')
        msg = test_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg['event_type'],
                          'compute.instance.resize.prep.end')
        self.assertEquals(msg['priority'], 'INFO')
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
        image_ref_url = utils.generate_image_url(FAKE_IMAGE_REF)
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
                          context, instance_uuid, 1, {})
        self.compute.terminate_instance(context, instance_uuid)

    def test_resize_instance_driver_error(self):
        """Ensure instance status set to Error on resize error"""

        def throw_up(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.compute.driver, 'migrate_disk_and_power_off',
                       throw_up)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance_uuid)
        db.instance_update(self.context, instance_uuid, {'host': 'foo'})
        self.compute.prep_resize(context, instance_uuid, 1, {},
                                 filter_properties={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance_uuid, 'pre-migrating')

        #verify
        self.assertRaises(test.TestingException, self.compute.resize_instance,
                          context, instance_uuid, migration_ref['id'], {})
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
        self.compute.prep_resize(context, instance_uuid, 1, {},
                                 filter_properties={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance_uuid, 'pre-migrating')
        self.compute.resize_instance(context, instance_uuid,
                migration_ref['id'], {})
        self.compute.terminate_instance(context, instance_uuid)

    def test_finish_revert_resize(self):
        """Ensure that the flavor is reverted to the original on revert"""
        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.driver, 'finish_revert_migration', fake)

        context = self.context.elevated()
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']

        self.compute.run_instance(self.context, instance_uuid)

        # Confirm the instance size before the resize starts
        inst_ref = db.instance_get_by_uuid(context, instance_uuid)
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '1')

        db.instance_update(self.context, instance_uuid, {'host': 'foo'})

        new_instance_type_ref = db.instance_type_get_by_flavor_id(context, 3)
        self.compute.prep_resize(context, inst_ref['uuid'],
                                 new_instance_type_ref['id'], {},
                                 filter_properties={})

        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')

        self.compute.resize_instance(context, inst_ref['uuid'],
                migration_ref['id'], {})
        self.compute.finish_resize(context, inst_ref['uuid'],
                    int(migration_ref['id']), {}, {})

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

        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ACTIVE)
        self.assertEqual(instance['task_state'], None)

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
                self.context, instance['uuid'], 1, {})
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_resize_instance_handles_migration_error(self):
        """Ensure vm_state is ERROR when error occurs"""
        def raise_migration_failure(*args):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver,
                'migrate_disk_and_power_off',
                raise_migration_failure)

        inst_ref = self._create_fake_instance()
        context = self.context.elevated()

        self.compute.run_instance(self.context, inst_ref['uuid'])
        db.instance_update(self.context, inst_ref['uuid'], {'host': 'foo'})
        self.compute.prep_resize(context, inst_ref['uuid'], 1, {},
                                 filter_properties={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')
        self.assertRaises(test.TestingException, self.compute.resize_instance,
                          context, inst_ref['uuid'], migration_ref['id'], {})
        inst_ref = db.instance_get_by_uuid(context, inst_ref['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(context, inst_ref['uuid'])

    def test_pre_live_migration_instance_has_no_fixed_ip(self):
        """Confirm raising exception if instance doesn't have fixed_ip."""
        # creating instance testdata
        inst_ref = self._create_fake_instance({'host': 'dummy'})
        c = context.get_admin_context()

        # start test
        self.stubs.Set(time, 'sleep', lambda t: None)
        self.assertRaises(exception.FixedIpNotFoundForInstance,
                          self.compute.pre_live_migration,
                          c, inst_ref['id'])
        # cleanup
        db.instance_destroy(c, inst_ref['id'])

    def test_pre_live_migration_works_correctly(self):
        """Confirm setup_compute_volume is called when volume is mounted."""
        def stupid(*args, **kwargs):
            return fake_network.fake_get_instance_nw_info(self.stubs,
                                                          spectacular=True)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       '_get_instance_nw_info', stupid)
        # creating instance testdata
        inst_ref = self._create_fake_instance({'host': 'dummy'})
        c = context.get_admin_context()

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'pre_live_migration')
        self.compute.driver.pre_live_migration({'block_device_mapping': []})
        nw_info = fake_network.fake_get_instance_nw_info(self.stubs)
        self.mox.StubOutWithMock(self.compute.driver, 'plug_vifs')
        self.compute.driver.plug_vifs(mox.IsA(inst_ref), nw_info)
        self.mox.StubOutWithMock(self.compute.driver,
                                 'ensure_filtering_rules_for_instance')
        self.compute.driver.ensure_filtering_rules_for_instance(
            mox.IsA(inst_ref), nw_info)

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

        c = context.get_admin_context()
        topic = rpc.queue_get_for(c, FLAGS.compute_topic, inst_ref['host'])

        # creating volume testdata
        volume_id = db.volume_create(c, {'size': 1})['id']
        values = {'instance_uuid': inst_ref['uuid'], 'device_name': '/dev/vdc',
                  'delete_on_termination': False, 'volume_id': volume_id}
        db.block_device_mapping_create(c, values)

        # creating mocks
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, FLAGS.volume_topic,
                 {"method": "check_for_export",
                  "args": {'instance_id': inst_ref['id']}})

        self.mox.StubOutWithMock(self.compute.driver, 'get_instance_disk_info')
        self.compute.driver.get_instance_disk_info(inst_ref.name)

        rpc.call(c, topic,
                 {"method": "pre_live_migration",
                  "args": {'instance_id': inst_ref['id'],
                           'block_migration': True,
                           'disk': None}
                 }).AndRaise(rpc.common.RemoteError('', '', ''))

        # mocks for rollback
        rpc.call(c, 'network', {'method': 'setup_networks_on_host',
                                'args': {'instance_id': inst_ref['id'],
                                         'host': self.compute.host,
                                         'teardown': False}})
        rpc.call(c, topic, {"method": "remove_volume_connection",
                            "args": {'instance_id': inst_ref['id'],
                                     'volume_id': volume_id}})
        rpc.cast(c, topic, {"method": "rollback_live_migration_at_destination",
                            "args": {'instance_id': inst_ref['id']}})

        # start test
        self.mox.ReplayAll()
        self.assertRaises(rpc_common.RemoteError,
                          self.compute.live_migration,
                          c, inst_ref['id'], inst_ref['host'], True)

        # cleanup
        for bdms in db.block_device_mapping_get_all_by_instance(
            c, inst_ref['uuid']):
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
        topic = rpc.queue_get_for(c, FLAGS.compute_topic, inst_ref['host'])

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
        db.floating_ip_create(c, {'address': flo_addr,
                                  'fixed_ip_id': fix_ref['id']})

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'unfilter_instance')
        self.compute.driver.unfilter_instance(i_ref, [])
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, rpc.queue_get_for(c, FLAGS.compute_topic, dest),
            {"method": "post_live_migration_at_destination",
             "args": {'instance_id': i_ref['id'], 'block_migration': False}})
        self.mox.StubOutWithMock(self.compute.driver, 'unplug_vifs')
        self.compute.driver.unplug_vifs(i_ref, [])
        rpc.call(c, 'network', {'method': 'setup_networks_on_host',
                                'args': {'instance_id': instance_id,
                                         'host': self.compute.host,
                                         'teardown': True}})

        # start test
        self.mox.ReplayAll()
        self.compute.post_live_migration(c, i_ref, dest)

        # make sure floating ips are rewritten to destinatioin hostname.
        flo_refs = db.floating_ip_get_all_by_host(c, dest)
        self.assertTrue(flo_refs)
        self.assertEqual(flo_refs[0]['address'], flo_addr)

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
        self.compute._sync_power_states(ctxt)

        instances = db.instance_get_all(ctxt)
        LOG.info(_("After force-killing instances: %s"), instances)
        self.assertEqual(len(instances), 1)
        self.assertEqual(power_state.NOSTATE, instances[0]['power_state'])

    def test_add_instance_fault(self):
        exc_info = None
        instance_uuid = str(utils.gen_uuid())

        def fake_db_fault_create(ctxt, values):
            self.assertTrue(values['details'].startswith('test'))
            self.assertTrue('raise NotImplementedError' in values['details'])
            del values['details']

            expected = {
                'code': 500,
                'message': 'NotImplementedError',
                'instance_uuid': instance_uuid,
            }
            self.assertEquals(expected, values)

        try:
            raise NotImplementedError('test')
        except Exception:
            exc_info = sys.exc_info()

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        self.compute.add_instance_fault_from_exc(ctxt, instance_uuid,
                                                 NotImplementedError('test'),
                                                 exc_info)

    def test_add_instance_fault_user_error(self):
        exc_info = None
        instance_uuid = str(utils.gen_uuid())

        def fake_db_fault_create(ctxt, values):

            expected = {
                'code': 400,
                'message': 'Invalid',
                'details': 'fake details',
                'instance_uuid': instance_uuid,
            }
            self.assertEquals(expected, values)

        user_exc = exception.Invalid('fake details', code=400)

        try:
            raise user_exc
        except Exception:
            exc_info = sys.exc_info()

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        self.compute.add_instance_fault_from_exc(ctxt, instance_uuid,
            user_exc, exc_info)

    def test_add_instance_fault_no_exc_info(self):
        instance_uuid = str(utils.gen_uuid())

        def fake_db_fault_create(ctxt, values):
            expected = {
                'code': 500,
                'message': 'NotImplementedError',
                'details': 'test',
                'instance_uuid': instance_uuid,
            }
            self.assertEquals(expected, values)

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        self.compute.add_instance_fault_from_exc(ctxt, instance_uuid,
                                                 NotImplementedError('test'))

    def test_get_additional_capabilities(self):
        self.flags(additional_compute_capabilities=['test3=xyzzy',
                                                    'test4',
                                                    'nothertest=blat'])
        caps = compute_manager._get_additional_capabilities()
        all_caps = dict(test3='xyzzy',
                        test4=True,
                        nothertest='blat')
        for c, val in all_caps.items():
            self.assertTrue(c in caps, c)
            self.assertEquals(val, caps[c])

    def test_report_driver_status(self):
        test_caps = dict(test1=1024, test2='foo', nothertest='bar')
        self.flags(additional_compute_capabilities=['test3=xyzzy',
                                                    'test4',
                                                    'nothertest=blat'])
        self.mox.StubOutWithMock(self.compute.driver, 'get_host_stats')
        self.compute.driver.get_host_stats(refresh=True).AndReturn(test_caps)
        self.compute._last_host_check = 0
        self.mox.ReplayAll()

        self.compute._report_driver_status(context.get_admin_context())
        caps = self.compute.last_capabilities
        all_caps = dict(test1=1024, test2='foo', test3='xyzzy',
                        test4=True, nothertest='bar')
        for c, val in all_caps.items():
            self.assertTrue(c in caps, c)
            self.assertEquals(val, caps[c])

    def test_cleanup_running_deleted_instances(self):
        admin_context = context.get_admin_context()
        deleted_at = utils.utcnow() - datetime.timedelta(hours=1, minutes=5)
        instance = self._create_fake_instance({"deleted_at": deleted_at,
                                          "deleted": True})

        self.compute.host = instance['host']

        self.mox.StubOutWithMock(self.compute.driver, 'list_instances')
        self.compute.driver.list_instances().AndReturn([instance['name']])
        FLAGS.running_deleted_instance_timeout = 3600
        FLAGS.running_deleted_instance_action = 'reap'

        self.mox.StubOutWithMock(self.compute.db, "instance_get_all_by_host")
        self.compute.db.instance_get_all_by_host(admin_context,
                                                 self.compute.host
                                                ).AndReturn([instance])

        self.mox.StubOutWithMock(self.compute, "_shutdown_instance")
        self.compute._shutdown_instance(admin_context, instance,
                                        'Terminating').AndReturn(None)

        self.mox.StubOutWithMock(self.compute, "_cleanup_volumes")
        self.compute._cleanup_volumes(admin_context,
                                      instance['uuid']).AndReturn(None)

        self.mox.ReplayAll()
        self.compute._cleanup_running_deleted_instances(admin_context)

    def test_running_deleted_instances(self):
        self.mox.StubOutWithMock(self.compute.driver, 'list_instances')
        self.compute.driver.list_instances().AndReturn(['herp', 'derp'])
        self.compute.host = 'host'

        instance1 = mox.MockAnything()
        instance1.name = 'herp'
        instance1.deleted = True
        instance1.deleted_at = "sometimeago"

        instance2 = mox.MockAnything()
        instance2.name = 'derp'
        instance2.deleted = False
        instance2.deleted_at = None

        self.mox.StubOutWithMock(utils, 'is_older_than')
        utils.is_older_than('sometimeago',
                    FLAGS.running_deleted_instance_timeout).AndReturn(True)

        self.mox.StubOutWithMock(self.compute.db, "instance_get_all_by_host")
        self.compute.db.instance_get_all_by_host('context',
                                                 'host').AndReturn(
                                                                [instance1,
                                                                 instance2])
        self.mox.ReplayAll()
        val = self.compute._running_deleted_instances('context')
        self.assertEqual(val, [instance1])

    def test_heal_instance_info_cache(self):
        # Update on every call for the test
        self.flags(heal_instance_info_cache_interval=-1)
        ctxt = context.get_admin_context()

        instance_map = {}
        instances = []
        for x in xrange(5):
            uuid = 'fake-uuid-%s' % x
            instance_map[uuid] = {'uuid': uuid, 'host': FLAGS.host}
            instances.append(instance_map[uuid])

        call_info = {'get_all_by_host': 0, 'get_by_uuid': 0,
                'get_nw_info': 0, 'expected_instance': None}

        def fake_instance_get_all_by_host(context, host):
            call_info['get_all_by_host'] += 1
            return instances[:]

        def fake_instance_get_by_uuid(context, instance_uuid):
            if instance_uuid not in instance_map:
                raise exception.InstanceNotFound
            call_info['get_by_uuid'] += 1
            return instance_map[instance_uuid]

        # NOTE(comstud): Override the stub in setUp()
        def fake_get_instance_nw_info(context, instance):
            # Note that this exception gets caught in compute/manager
            # and is ignored.  However, the below increment of
            # 'get_nw_info' won't happen, and you'll get an assert
            # failure checking it below.
            self.assertEqual(instance, call_info['expected_instance'])
            call_info['get_nw_info'] += 1

        self.stubs.Set(db, 'instance_get_all_by_host',
                fake_instance_get_all_by_host)
        self.stubs.Set(db, 'instance_get_by_uuid',
                fake_instance_get_by_uuid)
        self.stubs.Set(self.compute.network_api, 'get_instance_nw_info',
                fake_get_instance_nw_info)

        call_info['expected_instance'] = instances[0]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(call_info['get_all_by_host'], 1)
        self.assertEqual(call_info['get_by_uuid'], 0)
        self.assertEqual(call_info['get_nw_info'], 1)

        call_info['expected_instance'] = instances[1]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(call_info['get_all_by_host'], 1)
        self.assertEqual(call_info['get_by_uuid'], 1)
        self.assertEqual(call_info['get_nw_info'], 2)

        # Make an instance switch hosts
        instances[2]['host'] = 'not-me'
        # Make an instance disappear
        instance_map.pop(instances[3]['uuid'])
        # '2' and '3' should be skipped..
        call_info['expected_instance'] = instances[4]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(call_info['get_all_by_host'], 1)
        # Incremented for '2' and '4'.. '3' caused a raise above.
        self.assertEqual(call_info['get_by_uuid'], 3)
        self.assertEqual(call_info['get_nw_info'], 3)
        # Should be no more left.
        self.assertEqual(len(self.compute._instance_uuids_to_heal), 0)

        # This should cause a DB query now so we get first instance
        # back again
        call_info['expected_instance'] = instances[0]
        self.compute._heal_instance_info_cache(ctxt)
        self.assertEqual(call_info['get_all_by_host'], 2)
        # Stays the same, beacuse the instance came from the DB
        self.assertEqual(call_info['get_by_uuid'], 3)
        self.assertEqual(call_info['get_nw_info'], 4)

    def test_poll_unconfirmed_resizes(self):
        instances = [{'uuid': 'fake_uuid1', 'vm_state': vm_states.ACTIVE,
                      'task_state': task_states.RESIZE_VERIFY},
                     {'uuid': 'noexist'},
                     {'uuid': 'fake_uuid2', 'vm_state': vm_states.ERROR,
                      'task_state': task_states.RESIZE_VERIFY},
                     {'uuid': 'fake_uuid3', 'vm_state': vm_states.ACTIVE,
                      'task_state': task_states.REBOOTING},
                     {'uuid': 'fake_uuid4', 'vm_state': vm_states.ACTIVE,
                      'task_state': task_states.RESIZE_VERIFY},
                     {'uuid': 'fake_uuid5', 'vm_state': vm_states.ACTIVE,
                      'task_state': task_states.RESIZE_VERIFY}]
        expected_migration_status = {'fake_uuid1': 'confirmed',
                                     'noexist': 'error',
                                     'fake_uuid2': 'error',
                                     'fake_uuid3': 'error',
                                     'fake_uuid4': None,
                                     'fake_uuid5': 'confirmed'}
        migrations = []
        for i, instance in enumerate(instances, start=1):
            migrations.append({'id': i,
                               'instance_uuid': instance['uuid'],
                               'status': None})

        def fake_instance_get_by_uuid(context, instance_uuid):
            # raise InstanceNotFound exception for uuid 'noexist'
            if instance_uuid == 'noexist':
                raise exception.InstanceNotFound(instance_id=instance_uuid)
            for instance in instances:
                if instance['uuid'] == instance_uuid:
                    return instance

        def fake_migration_get_all_unconfirmed(context, resize_confirm_window):
            return migrations

        def fake_migration_update(context, migration_id, values):
            for migration in migrations:
                if migration['id'] == migration_id and 'status' in values:
                    migration['status'] = values['status']

        def fake_confirm_resize(context, instance):
            # raise exception for 'fake_uuid4' to check migration status
            # does not get set to 'error' on confirm_resize failure.
            if instance['uuid'] == 'fake_uuid4':
                raise test.TestingException
            for migration in migrations:
                if migration['instance_uuid'] == instance['uuid']:
                    migration['status'] = 'confirmed'

        self.stubs.Set(db, 'instance_get_by_uuid',
                fake_instance_get_by_uuid)
        self.stubs.Set(db, 'migration_get_all_unconfirmed',
                fake_migration_get_all_unconfirmed)
        self.stubs.Set(db, 'migration_update',
                fake_migration_update)
        self.stubs.Set(self.compute.compute_api, 'confirm_resize',
                fake_confirm_resize)

        def fetch_instance_migration_status(instance_uuid):
            for migration in migrations:
                if migration['instance_uuid'] == instance_uuid:
                    return migration['status']

        self.flags(resize_confirm_window=60)
        ctxt = context.get_admin_context()

        self.compute._poll_unconfirmed_resizes(ctxt)

        for uuid, status in expected_migration_status.iteritems():
            self.assertEqual(status, fetch_instance_migration_status(uuid))

    def test_instance_build_timeout_disabled(self):
        self.flags(instance_build_timeout=0)
        ctxt = context.get_admin_context()
        called = {'get_all': False, 'set_error_state': 0}
        created_at = utils.utcnow() + datetime.timedelta(seconds=-60)

        def fake_instance_get_all_by_filters(*args, **kwargs):
            called['get_all'] = True
            return instances[:]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                fake_instance_get_all_by_filters)

        def fake_set_instance_error_state(_ctxt, instance_uuid, **kwargs):
            called['set_error_state'] += 1

        self.stubs.Set(self.compute, '_set_instance_error_state',
                fake_set_instance_error_state)

        instance_map = {}
        instances = []
        for x in xrange(5):
            uuid = 'fake-uuid-%s' % x
            instance_map[uuid] = {'uuid': uuid, 'host': FLAGS.host,
                    'vm_state': vm_states.BUILDING,
                    'created_at': created_at}
            instances.append(instance_map[uuid])

        self.compute._check_instance_build_time(ctxt)
        self.assertFalse(called['get_all'])
        self.assertEqual(called['set_error_state'], 0)

    def test_instance_build_timeout(self):
        self.flags(instance_build_timeout=30)
        ctxt = context.get_admin_context()
        called = {'get_all': False, 'set_error_state': 0}
        created_at = utils.utcnow() + datetime.timedelta(seconds=-60)

        def fake_instance_get_all_by_filters(*args, **kwargs):
            called['get_all'] = True
            return instances[:]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                fake_instance_get_all_by_filters)

        def fake_set_instance_error_state(_ctxt, instance_uuid, **kwargs):
            called['set_error_state'] += 1

        self.stubs.Set(self.compute, '_set_instance_error_state',
                fake_set_instance_error_state)

        instance_map = {}
        instances = []
        for x in xrange(5):
            uuid = 'fake-uuid-%s' % x
            instance_map[uuid] = {'uuid': uuid, 'host': FLAGS.host,
                    'vm_state': vm_states.BUILDING,
                    'created_at': created_at}
            instances.append(instance_map[uuid])

        self.compute._check_instance_build_time(ctxt)
        self.assertTrue(called['get_all'])
        self.assertEqual(called['set_error_state'], 5)

    def test_instance_build_timeout_mixed_instances(self):
        self.flags(instance_build_timeout=30)
        ctxt = context.get_admin_context()
        called = {'get_all': False, 'set_error_state': 0}
        created_at = utils.utcnow() + datetime.timedelta(seconds=-60)

        def fake_instance_get_all_by_filters(*args, **kwargs):
            called['get_all'] = True
            return instances[:]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                fake_instance_get_all_by_filters)

        def fake_set_instance_error_state(_ctxt, instance_uuid, **kwargs):
            called['set_error_state'] += 1

        self.stubs.Set(self.compute, '_set_instance_error_state',
                fake_set_instance_error_state)

        instance_map = {}
        instances = []
        #expired instances
        for x in xrange(4):
            uuid = 'fake-uuid-%s' % x
            instance_map[uuid] = {'uuid': uuid, 'host': FLAGS.host,
                    'vm_state': vm_states.BUILDING,
                    'created_at': created_at}
            instances.append(instance_map[uuid])

        #not expired
        uuid = 'fake-uuid-5'
        instance_map[uuid] = {'uuid': uuid, 'host': FLAGS.host,
                'vm_state': vm_states.BUILDING,
                'created_at': utils.utcnow()}
        instances.append(instance_map[uuid])

        self.compute._check_instance_build_time(ctxt)
        self.assertTrue(called['get_all'])
        self.assertEqual(called['set_error_state'], 4)


class ComputeAPITestCase(BaseTestCase):

    def setUp(self):
        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1,
                                                          spectacular=True)

        super(ComputeAPITestCase, self).setUp()
        self.stubs.Set(nova.network.API, 'get_instance_nw_info',
                       fake_get_nw_info)
        self.compute_api = compute.API()
        self.fake_image = {
            'id': 1,
            'properties': {'kernel_id': 'fake_kernel_id',
                           'ramdisk_id': 'fake_ramdisk_id'},
        }

    def _run_instance(self):
        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)
        return instance, instance_uuid

    def test_create_with_too_little_ram(self):
        """Test an instance type with too little memory"""

        inst_type = instance_types.get_default_instance_type()
        inst_type['memory_mb'] = 1

        def fake_show(*args):
            img = copy.copy(self.fake_image)
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
        inst_type['root_gb'] = 1

        def fake_show(*args):
            img = copy.copy(self.fake_image)
            img['min_disk'] = 2
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        self.assertRaises(exception.InstanceTypeDiskTooSmall,
            self.compute_api.create, self.context, inst_type, None)

        # Now increase the inst_type disk space and make sure all is fine.
        inst_type['root_gb'] = 2
        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, None)
        db.instance_destroy(self.context, refs[0]['id'])

    def test_create_just_enough_ram_and_disk(self):
        """Test an instance type with just enough ram and disk space"""

        inst_type = instance_types.get_default_instance_type()
        inst_type['root_gb'] = 2
        inst_type['memory_mb'] = 2

        def fake_show(*args):
            img = copy.copy(self.fake_image)
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
        inst_type['root_gb'] = 1
        inst_type['memory_mb'] = 1

        def fake_show(*args):
            return copy.copy(self.fake_image)
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

    def test_create_instance_sets_system_metadata(self):
        """Make sure image properties are copied into system metadata."""
        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None)
        try:
            sys_metadata = db.instance_system_metadata_get(self.context,
                    ref[0]['uuid'])
            self.assertEqual(sys_metadata,
                    {'image_kernel_id': 'fake_kernel_id',
                     'image_ramdisk_id': 'fake_ramdisk_id',
                     'image_something_else': 'meow'})
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

    def test_start_shutdown(self):
        def check_state(instance_uuid, power_state_, vm_state_, task_state_):
            instance = db.instance_get_by_uuid(self.context, instance_uuid)
            self.assertEqual(instance['power_state'], power_state_)
            self.assertEqual(instance['vm_state'], vm_state_)
            self.assertEqual(instance['task_state'], task_state_)

        def start_check_state(instance_uuid,
                              power_state_, vm_state_, task_state_):
            instance = db.instance_get_by_uuid(self.context, instance_uuid)
            self.compute_api.start(self.context, instance)
            check_state(instance_uuid, power_state_, vm_state_, task_state_)

        instance = self._create_fake_instance()
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance_uuid)

        check_state(instance_uuid, power_state.RUNNING, vm_states.ACTIVE, None)

        # NOTE(yamahata): emulate compute.manager._sync_power_state() that
        # the instance is shutdown by itself
        db.instance_update(self.context, instance_uuid,
                           {'power_state': power_state.NOSTATE,
                            'vm_state': vm_states.SHUTOFF})
        check_state(instance_uuid, power_state.NOSTATE, vm_states.SHUTOFF,
                    None)

        start_check_state(instance_uuid,
                          power_state.NOSTATE, vm_states.SHUTOFF, None)

        db.instance_update(self.context, instance_uuid,
                           {'shutdown_terminate': False})
        start_check_state(instance_uuid, power_state.NOSTATE,
                          vm_states.STOPPED, task_states.STARTING)

        db.instance_destroy(self.context, instance['id'])

    def test_delete(self):
        instance, instance_uuid = self._run_instance()

        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

        db.instance_destroy(self.context, instance['id'])

    def test_delete_fail(self):
        instance, instance_uuid = self._run_instance()

        instance = db.instance_update(self.context, instance_uuid,
                                      {'disable_terminate': True})
        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        db.instance_destroy(self.context, instance['id'])

    def test_delete_soft(self):
        instance, instance_uuid = self._run_instance()

        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_OFF)

        db.instance_destroy(self.context, instance['id'])

    def test_delete_soft_fail(self):
        instance, instance_uuid = self._run_instance()

        instance = db.instance_update(self.context, instance_uuid,
                                      {'disable_terminate': True})
        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

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
        self.compute.run_instance(self.context, instance_uuid)
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
        # Set some image metadata that should get wiped out and reset
        # as well as some other metadata that should be preserved.
        db.instance_system_metadata_update(self.context, instance_uuid,
                {'image_kernel_id': 'old-data',
                 'image_ramdisk_id': 'old_data',
                 'image_something_else': 'old-data',
                 'image_should_remove': 'bye-bye',
                 'preserved': 'preserve this!'},
                True)

        # Make sure Compute API updates the image_ref before casting to
        # compute manager.
        orig_update = self.compute_api.update
        info = {'image_ref': None}

        def update_wrapper(*args, **kwargs):
            if 'image_ref' in kwargs:
                info['image_ref'] = kwargs['image_ref']
            return orig_update(*args, **kwargs)

        self.stubs.Set(self.compute_api, 'update', update_wrapper)

        image_ref = instance["image_ref"] + '-new_image_ref'
        password = "new_password"
        self.compute_api.rebuild(self.context, instance, image_ref, password)
        self.assertEqual(info['image_ref'], image_ref)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.REBUILDING)
        sys_metadata = db.instance_system_metadata_get(self.context,
                instance_uuid)
        self.assertEqual(sys_metadata,
                {'image_kernel_id': 'fake_kernel_id',
                 'image_ramdisk_id': 'fake_ramdisk_id',
                 'image_something_else': 'meow',
                 'preserved': 'preserve this!'})
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
            img = copy.copy(self.fake_image)
            img['disk_format'] = 'vhd'
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        instance = self._create_fake_instance()
        inst_params = {'root_gb': 2, 'memory_mb': 256}
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
            img = copy.copy(self.fake_image)
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
            img = copy.copy(self.fake_image)
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
            raise exception.ImageNotFound

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
        db.migration_create(context,
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
        db.migration_create(context,
                {'instance_uuid': instance['uuid'],
                 'status': 'finished'})
        # set the state that the instance gets when resize finishes
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.RESIZE_VERIFY,
                            'vm_state': vm_states.ACTIVE})
        instance = db.instance_get_by_uuid(context, instance['uuid'])

        self.compute_api.revert_resize(context, instance)

        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.RESIZING)
        self.assertEqual(instance['task_state'], task_states.RESIZE_REVERTING)

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
        def _fake_cast(context, topic, msg):
            request_spec = msg['args']['request_spec']
            filter_properties = msg['args']['filter_properties']
            instance_properties = request_spec['instance_properties']
            self.assertEqual(instance_properties['host'], 'host2')
            self.assertIn('host2', filter_properties['ignore_hosts'])

        self.stubs.Set(rpc, 'cast', _fake_cast)

        context = self.context.elevated()
        instance = self._create_fake_instance(dict(host='host2'))
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute.run_instance(self.context, instance['uuid'])
        try:
            self.compute_api.resize(context, instance, None)
        finally:
            self.compute.terminate_instance(context, instance['uuid'])

    def test_resize_request_spec_noavoid(self):
        def _fake_cast(context, topic, msg):
            request_spec = msg['args']['request_spec']
            filter_properties = msg['args']['filter_properties']
            instance_properties = request_spec['instance_properties']
            self.assertEqual(instance_properties['host'], 'host2')
            self.assertNotIn('host2', filter_properties['ignore_hosts'])

        self.stubs.Set(rpc, 'cast', _fake_cast)
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

        self.stubs.Set(nova.network.API, 'associate_floating_ip',
                       fake_associate_ip_network_api)

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
        self.assertRaises(exception.FixedIpNotFoundForInstance,
                          self.compute_api.associate_floating_ip,
                          self.context,
                          instance,
                          address)
        self.compute.terminate_instance(self.context, instance_uuid)

    def test_get(self):
        """Test get instance"""
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

        # ensure unknown filter maps to an empty list, not an exception
        instances = self.compute_api.get_all(c, search_opts={'flavor': 99})
        self.assertEqual(instances, [])

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
                 'snapshot_id': '00000000-aaaa-bbbb-cccc-000000000000',
                 'delete_on_termination': False},


                # overwrite swap
                {'device_name': '/dev/sdb2',
                 'snapshot_id': '11111111-aaaa-bbbb-cccc-111111111111',
                 'delete_on_termination': False},
                {'device_name': '/dev/sdb3',
                 'snapshot_id': '22222222-aaaa-bbbb-cccc-222222222222'},
                {'device_name': '/dev/sdb4',
                 'no_device': True},

                # overwrite ephemeral
                {'device_name': '/dev/sdc2',
                 'snapshot_id': '33333333-aaaa-bbbb-cccc-333333333333',
                 'delete_on_termination': False},
                {'device_name': '/dev/sdc3',
                 'snapshot_id': '44444444-aaaa-bbbb-cccc-444444444444'},
                {'device_name': '/dev/sdc4',
                 'no_device': True},

                # volume
                {'device_name': '/dev/sdd1',
                 'snapshot_id': '55555555-aaaa-bbbb-cccc-555555555555',
                 'delete_on_termination': False},
                {'device_name': '/dev/sdd2',
                 'snapshot_id': '66666666-aaaa-bbbb-cccc-666666666666'},
                {'device_name': '/dev/sdd3',
                 'snapshot_id': '77777777-aaaa-bbbb-cccc-777777777777'},
                {'device_name': '/dev/sdd4',
                 'no_device': True}]

        self.compute_api._update_image_block_device_mapping(
            self.context, instance_type, instance['uuid'], mappings)

        bdms = [self._parse_db_block_device_mapping(bdm_ref)
                for bdm_ref in db.block_device_mapping_get_all_by_instance(
                    self.context, instance['uuid'])]
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
            instance['uuid'], block_device_mapping)
        bdms = [self._parse_db_block_device_mapping(bdm_ref)
                for bdm_ref in db.block_device_mapping_get_all_by_instance(
                    self.context, instance['uuid'])]
        expected_result = [
            {'snapshot_id': '00000000-aaaa-bbbb-cccc-000000000000',
               'device_name': '/dev/sda1'},

            {'virtual_name': 'swap', 'device_name': '/dev/sdb1',
             'volume_size': swap_size},
            {'snapshot_id': '11111111-aaaa-bbbb-cccc-111111111111',
               'device_name': '/dev/sdb2'},
            {'snapshot_id': '22222222-aaaa-bbbb-cccc-222222222222',
                'device_name': '/dev/sdb3'},
            {'no_device': True, 'device_name': '/dev/sdb4'},

            {'virtual_name': 'ephemeral0', 'device_name': '/dev/sdc1'},
            {'snapshot_id': '33333333-aaaa-bbbb-cccc-333333333333',
                'device_name': '/dev/sdc2'},
            {'snapshot_id': '44444444-aaaa-bbbb-cccc-444444444444',
                'device_name': '/dev/sdc3'},
            {'no_device': True, 'device_name': '/dev/sdc4'},

            {'snapshot_id': '55555555-aaaa-bbbb-cccc-555555555555',
                'device_name': '/dev/sdd1'},
            {'snapshot_id': '66666666-aaaa-bbbb-cccc-666666666666',
                'device_name': '/dev/sdd2'},
            {'snapshot_id': '77777777-aaaa-bbbb-cccc-777777777777',
                'device_name': '/dev/sdd3'},
            {'no_device': True, 'device_name': '/dev/sdd4'}]
        bdms.sort()
        expected_result.sort()
        self.assertDictListMatch(bdms, expected_result)

        for bdm in db.block_device_mapping_get_all_by_instance(
            self.context, instance['uuid']):
            db.block_device_mapping_destroy(self.context, bdm['id'])
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.compute.terminate_instance(self.context, instance['uuid'])

    def test_volume_size(self):
        ephemeral_size = 2
        swap_size = 3
        inst_type = {'ephemeral_gb': ephemeral_size, 'swap': swap_size}
        self.assertEqual(self.compute_api._volume_size(inst_type,
                                                       'ephemeral0'),
                         ephemeral_size)
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

    def test_instance_name_template(self):
        """Test the instance_name template"""
        self.flags(instance_name_template='instance-%d')
        i_ref = self._create_fake_instance()
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
        self.assertRaises(exception.InvalidDevicePath,
                self.compute_api.attach_volume,
                self.context,
                None,
                None,
                '/dev/invalid')

    def test_vnc_console(self):
        """Make sure we can a vnc console for an instance."""

        fake_instance = {'uuid': 'fake_uuid',
                         'host': 'fake_compute_host'}
        fake_console_type = "novnc"
        fake_connect_info = {'token': 'fake_token',
                             'console_type': fake_console_type,
                             'host': 'fake_console_host',
                             'port': 'fake_console_port',
                             'internal_access_path': 'fake_access_path'}
        fake_connect_info2 = copy.deepcopy(fake_connect_info)
        fake_connect_info2['access_url'] = 'fake_console_url'

        self.mox.StubOutWithMock(rpc, 'call')

        rpc_msg1 = {'method': 'get_vnc_console',
                    'args': {'instance_uuid': fake_instance['uuid'],
                             'console_type': fake_console_type},
                   'version': compute_rpcapi.ComputeAPI.RPC_API_VERSION}
        rpc_msg2 = {'method': 'authorize_console',
                    'args': fake_connect_info,
                    'version': '1.0'}

        rpc.call(self.context, 'compute.%s' % fake_instance['host'],
                rpc_msg1, None).AndReturn(fake_connect_info2)
        rpc.call(self.context, FLAGS.consoleauth_topic,
                rpc_msg2, None).AndReturn(None)

        self.mox.ReplayAll()

        console = self.compute_api.get_vnc_console(self.context,
                fake_instance, fake_console_type)
        self.assertEqual(console, {'url': 'fake_console_url'})

    def test_console_output(self):
        fake_instance = {'uuid': 'fake_uuid',
                         'host': 'fake_compute_host'}
        fake_tail_length = 699
        fake_console_output = 'fake console output'

        self.mox.StubOutWithMock(rpc, 'call')

        rpc_msg = {'method': 'get_console_output',
                   'args': {'instance_uuid': fake_instance['uuid'],
                            'tail_length': fake_tail_length},
                   'version': compute_rpcapi.ComputeAPI.RPC_API_VERSION}
        rpc.call(self.context, 'compute.%s' % fake_instance['host'],
                rpc_msg, None).AndReturn(fake_console_output)

        self.mox.ReplayAll()

        output = self.compute_api.get_console_output(self.context,
                fake_instance, tail_length=fake_tail_length)
        self.assertEqual(output, fake_console_output)

    def test_attach_volume(self):
        """Ensure instance can be soft rebooted"""

        def fake_check_attach(*args, **kwargs):
            pass

        def fake_reserve_volume(*args, **kwargs):
            pass

        def fake_volume_get(self, context, volume_id):
            return {'id': volume_id}

        self.stubs.Set(nova.volume.api.API, 'get', fake_volume_get)
        self.stubs.Set(nova.volume.api.API, 'check_attach', fake_check_attach)
        self.stubs.Set(nova.volume.api.API, 'reserve_volume',
                       fake_reserve_volume)
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

    def test_inject_file(self):
        """Ensure we can write a file to an instance"""
        instance = self._create_fake_instance()
        self.compute_api.inject_file(self.context, instance,
                                     "/tmp/test", "File Contents")
        db.instance_destroy(self.context, instance['id'])


def fake_rpc_method(context, topic, msg, do_cast=True):
    pass


def _create_service_entries(context, values={'avail_zone1': ['fake_host1',
                                                             'fake_host2'],
                                             'avail_zone2': ['fake_host3'], }):
    for avail_zone, hosts in values.iteritems():
        for host in hosts:
            db.service_create(context,
                              {'host': host,
                               'binary': 'nova-compute',
                               'topic': 'compute',
                               'report_count': 0,
                               'availability_zone': avail_zone})
    return values


class ComputeAPIAggrTestCase(test.TestCase):
    """This is for unit coverage of aggregate-related methods
    defined in nova.compute.api."""

    def setUp(self):
        super(ComputeAPIAggrTestCase, self).setUp()
        self.api = compute_api.AggregateAPI()
        self.context = context.get_admin_context()
        self.stubs.Set(rpc, 'call', fake_rpc_method)
        self.stubs.Set(rpc, 'cast', fake_rpc_method)

    def test_create_invalid_availability_zone(self):
        """Ensure InvalidAggregateAction is raised with wrong avail_zone."""
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.create_aggregate,
                          self.context, 'fake_aggr', 'fake_avail_zone')

    def test_update_aggregate_metadata(self):
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        metadata = {'foo_key1': 'foo_value1',
                    'foo_key2': 'foo_value2', }
        aggr = self.api.update_aggregate_metadata(self.context, aggr['id'],
                                                  metadata)
        metadata['foo_key1'] = None
        expected = self.api.update_aggregate_metadata(self.context,
                                             aggr['id'], metadata)
        self.assertDictMatch(expected['metadata'], {'foo_key2': 'foo_value2'})

    def test_delete_aggregate(self):
        """Ensure we can delete an aggregate."""
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        self.api.delete_aggregate(self.context, aggr['id'])
        expected = db.aggregate_get(self.context.elevated(read_deleted='yes'),
                                    aggr['id'])
        self.assertNotEqual(aggr['operational_state'],
                            expected['operational_state'])

    def test_delete_non_empty_aggregate(self):
        """Ensure InvalidAggregateAction is raised when non empty aggregate."""
        _create_service_entries(self.context,
                                {'fake_availability_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_availability_zone')
        self.api.add_host_to_aggregate(self.context, aggr['id'], 'fake_host')
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.delete_aggregate, self.context, aggr['id'])

    def test_add_host_to_aggregate(self):
        """Ensure we can add a host to an aggregate."""
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        fake_host = values[fake_zone][0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        aggr = self.api.add_host_to_aggregate(self.context,
                                              aggr['id'], fake_host)
        self.assertEqual(aggr['operational_state'], aggregate_states.CHANGING)

    def test_add_host_to_aggregate_multiple(self):
        """Ensure we can add multiple hosts to an aggregate."""
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        # let's mock the fact that the aggregate is active already!
        status = {'operational_state': aggregate_states.ACTIVE}
        db.aggregate_update(self.context, aggr['id'], status)
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        self.assertEqual(len(aggr['hosts']), len(values[fake_zone]))
        self.assertEqual(aggr['operational_state'],
                         aggregate_states.ACTIVE)

    def test_add_host_to_aggregate_invalid_changing_status(self):
        """Ensure InvalidAggregateAction is raised when adding host while
        aggregate is not ready."""
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        fake_host = values[fake_zone][0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        aggr = self.api.add_host_to_aggregate(self.context,
                                              aggr['id'], fake_host)
        self.assertEqual(aggr['operational_state'],
                             aggregate_states.CHANGING)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.add_host_to_aggregate, self.context,
                          aggr['id'], fake_host)

    def test_add_host_to_aggregate_invalid_dismissed_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        deleted."""
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', 'fake_zone')
        # let's mock the fact that the aggregate is dismissed!
        status = {'operational_state': aggregate_states.DISMISSED}
        db.aggregate_update(self.context, aggr['id'], status)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.add_host_to_aggregate, self.context,
                          aggr['id'], 'fake_host')

    def test_add_host_to_aggregate_invalid_error_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        in error."""
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', 'fake_zone')
        # let's mock the fact that the aggregate is in error!
        status = {'operational_state': aggregate_states.ERROR}
        db.aggregate_update(self.context, aggr['id'], status)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.add_host_to_aggregate, self.context,
                          aggr['id'], 'fake_host')

    def test_add_host_to_aggregate_zones_mismatch(self):
        """Ensure InvalidAggregateAction is raised when zones don't match."""
        _create_service_entries(self.context, {'fake_zoneX': ['fake_host1'],
                                               'fake_zoneY': ['fake_host2']})
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', 'fake_zoneY')
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.add_host_to_aggregate,
                          self.context, aggr['id'], 'fake_host1')

    def test_add_host_to_aggregate_raise_not_found(self):
        """Ensure ComputeHostNotFound is raised when adding invalid host."""
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        self.assertRaises(exception.ComputeHostNotFound,
                          self.api.add_host_to_aggregate,
                          self.context, aggr['id'], 'invalid_host')

    def test_remove_host_from_aggregate_active(self):
        """Ensure we can remove a host from an aggregate."""
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        # let's mock the fact that the aggregate is active already!
        status = {'operational_state': aggregate_states.ACTIVE}
        db.aggregate_update(self.context, aggr['id'], status)
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        expected = self.api.remove_host_from_aggregate(self.context,
                                                       aggr['id'],
                                                       values[fake_zone][0])
        self.assertEqual(len(aggr['hosts']) - 1, len(expected['hosts']))
        self.assertEqual(expected['operational_state'],
                         aggregate_states.ACTIVE)

    def test_remove_host_from_aggregate_error(self):
        """Ensure we can remove a host from an aggregate even if in error."""
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        # let's mock the fact that the aggregate is ready!
        status = {'operational_state': aggregate_states.ACTIVE}
        db.aggregate_update(self.context, aggr['id'], status)
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        # let's mock the fact that the aggregate is in error!
        status = {'operational_state': aggregate_states.ERROR}
        expected = self.api.remove_host_from_aggregate(self.context,
                                                       aggr['id'],
                                                       values[fake_zone][0])
        self.assertEqual(len(aggr['hosts']) - 1, len(expected['hosts']))
        self.assertEqual(expected['operational_state'],
                         aggregate_states.ACTIVE)

    def test_remove_host_from_aggregate_invalid_dismissed_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        deleted."""
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', 'fake_zone')
        # let's mock the fact that the aggregate is dismissed!
        status = {'operational_state': aggregate_states.DISMISSED}
        db.aggregate_update(self.context, aggr['id'], status)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.remove_host_from_aggregate, self.context,
                          aggr['id'], 'fake_host')

    def test_remove_host_from_aggregate_invalid_changing_status(self):
        """Ensure InvalidAggregateAction is raised when aggregate is
        changing."""
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', 'fake_zone')
        # let's mock the fact that the aggregate is changing!
        status = {'operational_state': aggregate_states.CHANGING}
        db.aggregate_update(self.context, aggr['id'], status)
        self.assertRaises(exception.InvalidAggregateAction,
                          self.api.remove_host_from_aggregate, self.context,
                          aggr['id'], 'fake_host')

    def test_remove_host_from_aggregate_raise_not_found(self):
        """Ensure ComputeHostNotFound is raised when removing invalid host."""
        _create_service_entries(self.context, {'fake_zone': ['fake_host']})
        aggr = self.api.create_aggregate(self.context, 'fake_aggregate',
                                         'fake_zone')
        self.assertRaises(exception.ComputeHostNotFound,
                          self.api.remove_host_from_aggregate,
                          self.context, aggr['id'], 'invalid_host')


class ComputeAggrTestCase(BaseTestCase):
    """This is for unit coverage of aggregate-related methods
    defined in nova.compute.manager."""

    def setUp(self):
        super(ComputeAggrTestCase, self).setUp()
        self.context = context.get_admin_context()
        values = {'name': 'test_aggr',
                  'availability_zone': 'test_zone', }
        self.aggr = db.aggregate_create(self.context, values)

    def test_add_aggregate_host(self):
        def fake_driver_add_to_aggregate(context, aggregate, host):
            fake_driver_add_to_aggregate.called = True
            return {"foo": "bar"}
        self.stubs.Set(self.compute.driver, "add_to_aggregate",
                       fake_driver_add_to_aggregate)

        self.compute.add_aggregate_host(self.context, self.aggr.id, "host")
        self.assertTrue(fake_driver_add_to_aggregate.called)

    def test_add_aggregate_host_raise_err(self):
        """Ensure the undo operation works correctly on add."""
        def fake_driver_add_to_aggregate(context, aggregate, host):
            raise exception.AggregateError
        self.stubs.Set(self.compute.driver, "add_to_aggregate",
                       fake_driver_add_to_aggregate)

        state = {'operational_state': aggregate_states.ACTIVE}
        db.aggregate_update(self.context, self.aggr.id, state)
        db.aggregate_host_add(self.context, self.aggr.id, 'fake_host')

        self.assertRaises(exception.AggregateError,
                          self.compute.add_aggregate_host,
                          self.context, self.aggr.id, "fake_host")
        excepted = db.aggregate_get(self.context, self.aggr.id)
        self.assertEqual(excepted.operational_state, aggregate_states.ERROR)
        self.assertEqual(excepted.hosts, [])

    def test_remove_aggregate_host(self):
        def fake_driver_remove_from_aggregate(context, aggregate, host):
            fake_driver_remove_from_aggregate.called = True
            self.assertEqual("host", host, "host")
            return {"foo": "bar"}
        self.stubs.Set(self.compute.driver, "remove_from_aggregate",
                       fake_driver_remove_from_aggregate)

        self.compute.remove_aggregate_host(self.context, self.aggr.id, "host")
        self.assertTrue(fake_driver_remove_from_aggregate.called)

    def test_remove_aggregate_host_raise_err(self):
        """Ensure the undo operation works correctly on remove."""
        def fake_driver_remove_from_aggregate(context, aggregate, host):
            raise exception.AggregateError
        self.stubs.Set(self.compute.driver, "remove_from_aggregate",
                       fake_driver_remove_from_aggregate)

        state = {'operational_state': aggregate_states.ACTIVE}
        db.aggregate_update(self.context, self.aggr.id, state)

        self.assertRaises(exception.AggregateError,
                          self.compute.remove_aggregate_host,
                          self.context, self.aggr.id, "fake_host")
        excepted = db.aggregate_get(self.context, self.aggr.id)
        self.assertEqual(excepted.operational_state, aggregate_states.ERROR)
        self.assertEqual(excepted.hosts, ['fake_host'])


class ComputePolicyTestCase(BaseTestCase):

    def setUp(self):
        super(ComputePolicyTestCase, self).setUp()
        nova.policy.reset()
        nova.policy.init()

        self.compute_api = compute.API()

    def tearDown(self):
        super(ComputePolicyTestCase, self).tearDown()
        nova.policy.reset()

    def _set_rules(self, rules):
        nova.common.policy.set_brain(nova.common.policy.HttpBrain(rules))

    def test_actions_are_prefixed(self):
        self.mox.StubOutWithMock(nova.policy, 'enforce')
        nova.policy.enforce(self.context, 'compute:reboot', {})
        self.mox.ReplayAll()
        nova.compute.api.check_policy(self.context, 'reboot', {})

    def test_wrapped_method(self):
        instance = self._create_fake_instance()
        # Reset this to None for this policy check. If it's set, it
        # tries to do a compute_api.update() and we're not testing for
        # that here.
        instance['host'] = None
        self.compute.run_instance(self.context, instance['uuid'])

        # force delete to fail
        rules = {"compute:delete": [["false:false"]]}
        self._set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.delete, self.context, instance)

        # reset rules to allow deletion
        rules = {"compute:delete": []}
        self._set_rules(rules)

        self.compute_api.delete(self.context, instance)

    def test_create_fail(self):
        rules = {"compute:create": [["false:false"]]}
        self._set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.create, self.context, '1', '1')

    def test_create_attach_volume_fail(self):
        rules = {
            "compute:create": [],
            "compute:create:attach_network": [["false:false"]],
            "compute:create:attach_volume": [],
        }
        self._set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.create, self.context, '1', '1',
                          requested_networks='blah',
                          block_device_mapping='blah')

    def test_create_attach_network_fail(self):
        rules = {
            "compute:create": [],
            "compute:create:attach_network": [],
            "compute:create:attach_volume": [["false:false"]],
        }
        self._set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.create, self.context, '1', '1',
                          requested_networks='blah',
                          block_device_mapping='blah')

    def test_get_fail(self):
        instance = self._create_fake_instance()

        rules = {
            "compute:get": [["false:false"]],
        }
        self._set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.get, self.context, instance['uuid'])

    def test_get_all_fail(self):
        rules = {
            "compute:get_all": [["false:false"]],
        }
        self._set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.get_all, self.context)

    def test_get_instance_faults(self):
        instance1 = self._create_fake_instance()
        instance2 = self._create_fake_instance()
        instances = [instance1, instance2]

        rules = {
            "compute:get_instance_faults": [["false:false"]],
        }
        self._set_rules(rules)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.compute_api.get_instance_faults,
                          self.context, instances)


class ComputeHostAPITestCase(BaseTestCase):
    def setUp(self):
        super(ComputeHostAPITestCase, self).setUp()
        self.host_api = compute_api.HostAPI()

    def _rpc_call_stub(self, call_info):
        def fake_rpc_call(context, topic, msg, timeout=None):
            call_info['context'] = context
            call_info['topic'] = topic
            call_info['msg'] = msg
        self.stubs.Set(rpc, 'call', fake_rpc_call)

    def test_set_host_enabled(self):
        ctxt = context.RequestContext('fake', 'fake')
        call_info = {}
        self._rpc_call_stub(call_info)

        self.host_api.set_host_enabled(ctxt, 'fake_host', 'fake_enabled')
        self.assertEqual(call_info['context'], ctxt)
        self.assertEqual(call_info['topic'], 'compute.fake_host')
        self.assertEqual(call_info['msg'],
                {'method': 'set_host_enabled',
                 'args': {'enabled': 'fake_enabled'},
                 'version': compute_rpcapi.ComputeAPI.RPC_API_VERSION})

    def test_host_power_action(self):
        ctxt = context.RequestContext('fake', 'fake')
        call_info = {}
        self._rpc_call_stub(call_info)
        self.host_api.host_power_action(ctxt, 'fake_host', 'fake_action')
        self.assertEqual(call_info['context'], ctxt)
        self.assertEqual(call_info['topic'], 'compute.fake_host')
        self.assertEqual(call_info['msg'],
                {'method': 'host_power_action',
                 'args': {'action': 'fake_action'},
                 'version': compute_rpcapi.ComputeAPI.RPC_API_VERSION})

    def test_set_host_maintenance(self):
        ctxt = context.RequestContext('fake', 'fake')
        call_info = {}
        self._rpc_call_stub(call_info)
        self.host_api.set_host_maintenance(ctxt, 'fake_host', 'fake_mode')
        self.assertEqual(call_info['context'], ctxt)
        self.assertEqual(call_info['topic'], 'compute.fake_host')
        self.assertEqual(call_info['msg'],
                {'method': 'host_maintenance_mode',
                 'args': {'host': 'fake_host', 'mode': 'fake_mode'},
                 'version': compute_rpcapi.ComputeAPI.RPC_API_VERSION})


class KeypairAPITestCase(BaseTestCase):
    def setUp(self):
        super(KeypairAPITestCase, self).setUp()
        self.keypair_api = compute_api.KeypairAPI()
        self.ctxt = context.RequestContext('fake', 'fake')
        self._keypair_db_call_stubs()
        self.pub_key = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDLnVkqJu9WVf' \
                  '/5StU3JCrBR2r1s1j8K1tux+5XeSvdqaM8lMFNorzbY5iyoBbRS56gy' \
                  '1jmm43QsMPJsrpfUZKcJpRENSe3OxIIwWXRoiapZe78u/a9xKwj0avF' \
                  'YMcws9Rk9iAB7W4K1nEJbyCPl5lRBoyqeHBqrnnuXWEgGxJCK0Ah6wc' \
                  'OzwlEiVjdf4kxzXrwPHyi7Ea1qvnNXTziF8yYmUlH4C8UXfpTQckwSw' \
                  'pDyxZUc63P8q+vPbs3Q2kw+/7vvkCKHJAXVI+oCiyMMfffoTq16M1xf' \
                  'V58JstgtTqAXG+ZFpicGajREUE/E3hO5MGgcHmyzIrWHKpe1n3oEGuz'
        self.fingerprint = '4e:48:c6:a0:4a:f9:dd:b5:4c:85:54:5a:af:43:47:5a'

    def _keypair_db_call_stubs(self):

        def db_key_pair_get_all_by_user(self, user_id):
            return []

        def db_key_pair_create(self, keypair):
            pass

        def db_key_pair_destroy(context, user_id, name):
            pass

        self.stubs.Set(db, "key_pair_get_all_by_user",
                       db_key_pair_get_all_by_user)
        self.stubs.Set(db, "key_pair_create",
                       db_key_pair_create)
        self.stubs.Set(db, "key_pair_destroy",
                       db_key_pair_destroy)

    def test_create_keypair(self):
        keypair = self.keypair_api.create_key_pair(self.ctxt,
                                                   self.ctxt.user_id, 'foo')
        self.assertEqual('foo', keypair['name'])

    def test_create_keypair_name_too_long(self):
        self.assertRaises(exception.InvalidKeypair,
                          self.keypair_api.create_key_pair,
                          self.ctxt, self.ctxt.user_id, 'x' * 256)

    def test_create_keypair_invalid_chars(self):
        self.assertRaises(exception.InvalidKeypair,
                          self.keypair_api.create_key_pair,
                          self.ctxt, self.ctxt.user_id, '* BAD CHARACTERS! *')

    def test_create_keypair_already_exists(self):
        def db_key_pair_get(context, user_id, name):
            pass
        self.stubs.Set(db, "key_pair_get",
                       db_key_pair_get)
        self.assertRaises(exception.KeyPairExists,
                          self.keypair_api.create_key_pair,
                          self.ctxt, self.ctxt.user_id, 'foo')

    def test_create_keypair_quota_limit(self):
        def fake_quotas_count(self, context, resource, *args, **kwargs):
            return FLAGS.quota_key_pairs
        self.stubs.Set(QUOTAS, "count", fake_quotas_count)
        self.assertRaises(exception.KeypairLimitExceeded,
                          self.keypair_api.create_key_pair,
                          self.ctxt, self.ctxt.user_id, 'foo')

    def test_import_keypair(self):
        keypair = self.keypair_api.import_key_pair(self.ctxt,
                                                   self.ctxt.user_id,
                                                   'foo',
                                                   self.pub_key)
        self.assertEqual('foo', keypair['name'])
        self.assertEqual(self.fingerprint, keypair['fingerprint'])
        self.assertEqual(self.pub_key, keypair['public_key'])

    def test_import_keypair_bad_public_key(self):
        self.assertRaises(exception.InvalidKeypair,
                          self.keypair_api.import_key_pair,
                          self.ctxt, self.ctxt.user_id, 'foo', 'bad key data')

    def test_import_keypair_name_too_long(self):
        self.assertRaises(exception.InvalidKeypair,
                          self.keypair_api.import_key_pair,
                          self.ctxt, self.ctxt.user_id, 'x' * 256,
                          self.pub_key)

    def test_import_keypair_invalid_chars(self):
        self.assertRaises(exception.InvalidKeypair,
                          self.keypair_api.import_key_pair,
                          self.ctxt, self.ctxt.user_id,
                          '* BAD CHARACTERS! *', self.pub_key)

    def test_import_keypair_quota_limit(self):
        def fake_quotas_count(self, context, resource, *args, **kwargs):
            return FLAGS.quota_key_pairs
        self.stubs.Set(QUOTAS, "count", fake_quotas_count)
        self.assertRaises(exception.KeypairLimitExceeded,
                          self.keypair_api.import_key_pair,
                          self.ctxt, self.ctxt.user_id, 'foo', self.pub_key)
