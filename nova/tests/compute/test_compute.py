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

import base64
import copy
import datetime
import functools
import sys
import time

import mox

import nova
from nova import compute
from nova.compute import api as compute_api
from nova.compute import instance_types
from nova.compute import manager as compute_manager
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.network import api as network_api
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier_api
from nova.openstack.common.notifier import test_notifier
from nova.openstack.common import policy as common_policy
from nova.openstack.common import rpc
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils
import nova.policy
from nova import quota
from nova import test
from nova.tests.compute import fake_resource_tracker
from nova.tests.db.fakes import FakeModel
from nova.tests import fake_network
from nova.tests.image import fake as fake_image
from nova import utils
import nova.volume


QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
flags.DECLARE('live_migration_retry_count', 'nova.compute.manager')


FAKE_IMAGE_REF = 'fake-image-ref'


def nop_report_driver_status(self):
    pass


class FakeSchedulerAPI(object):

    def run_instance(self, ctxt, request_spec, admin_password,
            injected_files, requested_networks, is_first_time,
            filter_properties):
        pass

    def live_migration(self, ctxt, block_migration, disk_over_commit,
            instance, dest):
        pass


class BaseTestCase(test.TestCase):

    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   notification_driver=[test_notifier.__name__],
                   network_manager='nova.network.manager.FlatManager')
        self.compute = importutils.import_object(FLAGS.compute_manager)

        # override tracker with a version that doesn't need the database:
        self.compute.resource_tracker = \
            fake_resource_tracker.FakeResourceTracker(self.compute.host,
                    self.compute.driver)
        self.compute.update_available_resource(
                context.get_admin_context())

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)
        test_notifier.NOTIFICATIONS = []

        def fake_show(meh, context, id):
            return {'id': id, 'min_disk': None, 'min_ram': None,
                    'name': 'fake_name',
                    'properties': {'kernel_id': 'fake_kernel_id',
                                   'ramdisk_id': 'fake_ramdisk_id',
                                   'something_else': 'meow'}}

        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        fake_rpcapi = FakeSchedulerAPI()
        self.stubs.Set(self.compute, 'scheduler_rpcapi', fake_rpcapi)
        fake_network.set_stub_network_methods(self.stubs)

    def tearDown(self):
        fake_image.FakeImageService_reset()
        instances = db.instance_get_all(self.context.elevated())
        notifier_api._reset_drivers()
        for instance in instances:
            db.instance_destroy(self.context.elevated(), instance['uuid'])
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
        inst['architecture'] = 'x86_64'
        inst['os_type'] = 'Linux'
        inst.update(params)
        _create_service_entries(self.context.elevated(),
                {'fake_zone': [inst['host']]})
        return db.instance_create(self.context, inst)

    def _create_instance(self, params=None, type_name='m1.tiny'):
        """Create a test instance. Returns uuid"""
        return self._create_fake_instance(params, type_name=type_name)

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
        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                       fake_get_nw_info)
        self.stubs.Set(network_api.API, 'allocate_for_instance',
                       fake_get_nw_info)
        self.compute_api = compute.API()

    def tearDown(self):
        super(ComputeTestCase, self).tearDown()
        timeutils.clear_time_override()

    def test_wrap_instance_fault(self):
        inst = {"uuid": "fake_uuid"}

        called = {'fault_added': False}

        def did_it_add_fault(*args):
            called['fault_added'] = True

        self.stubs.Set(compute_utils, 'add_instance_fault_from_exc',
                       did_it_add_fault)

        @nova.compute.manager.wrap_instance_fault
        def failer(self2, context, instance):
            raise NotImplementedError()

        self.assertRaises(NotImplementedError, failer,
                          self.compute, self.context, instance=inst)

        self.assertTrue(called['fault_added'])

    def test_wrap_instance_fault_no_instance(self):
        inst_uuid = "fake_uuid"

        called = {'fault_added': False}

        def did_it_add_fault(*args):
            called['fault_added'] = True

        self.stubs.Set(compute_utils, 'add_instance_fault_from_exc',
                       did_it_add_fault)

        @nova.compute.manager.wrap_instance_fault
        def failer(self2, context, instance_uuid):
            raise exception.InstanceNotFound()

        self.assertRaises(exception.InstanceNotFound, failer,
                          self.compute, self.context, inst_uuid)

        self.assertFalse(called['fault_added'])

    def test_create_instance_with_img_ref_associates_config_drive(self):
        """Make sure create associates a config drive."""

        instance = jsonutils.to_primitive(self._create_fake_instance(
                        params={'config_drive': '1234', }))

        try:
            self.compute.run_instance(self.context, instance=instance)
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertTrue(instance.config_drive)
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_create_instance_associates_config_drive(self):
        """Make sure create associates a config drive."""

        instance = jsonutils.to_primitive(self._create_fake_instance(
                        params={'config_drive': '1234', }))

        try:
            self.compute.run_instance(self.context, instance=instance)
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertTrue(instance.config_drive)
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_create_instance_unlimited_memory(self):
        """Default of memory limit=None is unlimited"""
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())
        params = {"memory_mb": 999999999999}
        filter_properties = {'limits': {'memory_mb': None}}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)
        self.assertEqual(999999999999,
                self.compute.resource_tracker.compute_node['memory_mb_used'])

    def test_create_instance_unlimited_disk(self):
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())
        params = {"root_gb": 999999999999,
                  "ephemeral_gb": 99999999999}
        filter_properties = {'limits': {'disk_gb': None}}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_multiple_instances_then_starve(self):
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())
        filter_properties = {'limits': {'memory_mb': 4096, 'disk_gb': 1000}}
        params = {"memory_mb": 1024, "root_gb": 128, "ephemeral_gb": 128}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                                  filter_properties=filter_properties)
        self.assertEquals(1024,
                self.compute.resource_tracker.compute_node['memory_mb_used'])
        self.assertEquals(256,
                self.compute.resource_tracker.compute_node['local_gb_used'])

        params = {"memory_mb": 2048, "root_gb": 256, "ephemeral_gb": 256}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                                  filter_properties=filter_properties)
        self.assertEquals(3072,
                self.compute.resource_tracker.compute_node['memory_mb_used'])
        self.assertEquals(768,
                self.compute.resource_tracker.compute_node['local_gb_used'])

        params = {"memory_mb": 8192, "root_gb": 8192, "ephemeral_gb": 8192}
        instance = self._create_fake_instance(params)
        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_instance_with_oversubscribed_ram(self):
        """Test passing of oversubscribed ram policy from the scheduler."""

        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource()
        total_mem_mb = resources['memory_mb']

        oversub_limit_mb = total_mem_mb * 1.5
        instance_mb = int(total_mem_mb * 1.45)

        # build an instance, specifying an amount of memory that exceeds
        # total_mem_mb, but is less than the oversubscribed limit:
        params = {"memory_mb": instance_mb, "root_gb": 128,
                  "ephemeral_gb": 128}
        instance = self._create_fake_instance(params)

        limits = {'memory_mb': oversub_limit_mb}
        filter_properties = {'limits': limits}
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(instance_mb,
                self.compute.resource_tracker.compute_node['memory_mb_used'])

    def test_create_instance_with_oversubscribed_ram_fail(self):
        """Test passing of oversubscribed ram policy from the scheduler, but
        with insufficient memory.
        """
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource()
        total_mem_mb = resources['memory_mb']

        oversub_limit_mb = total_mem_mb * 1.5
        instance_mb = int(total_mem_mb * 1.55)

        # build an instance, specifying an amount of memory that exceeds
        # total_mem_mb, but is less than the oversubscribed limit:
        params = {"memory_mb": instance_mb, "root_gb": 128,
                  "ephemeral_gb": 128}
        instance = self._create_fake_instance(params)

        filter_properties = {'limits': {'memory_mb': oversub_limit_mb}}

        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_instance_with_oversubscribed_cpu(self):
        """Test passing of oversubscribed cpu policy from the scheduler."""

        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())
        limits = {'vcpu': 3}
        filter_properties = {'limits': limits}

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource()
        self.assertEqual(1, resources['vcpus'])

        # build an instance, specifying an amount of memory that exceeds
        # total_mem_mb, but is less than the oversubscribed limit:
        params = {"memory_mb": 10, "root_gb": 1,
                  "ephemeral_gb": 1, "vcpus": 2}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(2,
                self.compute.resource_tracker.compute_node['vcpus_used'])

        # create one more instance:
        params = {"memory_mb": 10, "root_gb": 1,
                  "ephemeral_gb": 1, "vcpus": 1}
        instance = self._create_fake_instance(params)
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(3,
                self.compute.resource_tracker.compute_node['vcpus_used'])

        # delete the instance:
        instance['vm_state'] = vm_states.DELETED
        self.compute.resource_tracker.update_usage(self.context,
                instance=instance)

        self.assertEqual(2,
                self.compute.resource_tracker.compute_node['vcpus_used'])

        # now oversubscribe vcpus and fail:
        params = {"memory_mb": 10, "root_gb": 1,
                  "ephemeral_gb": 1, "vcpus": 2}
        instance = self._create_fake_instance(params)

        limits = {'vcpu': 3}
        filter_properties = {'limits': limits}
        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_create_instance_with_oversubscribed_disk(self):
        """Test passing of oversubscribed disk policy from the scheduler."""

        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource()
        total_disk_gb = resources['local_gb']

        oversub_limit_gb = total_disk_gb * 1.5
        instance_gb = int(total_disk_gb * 1.45)

        # build an instance, specifying an amount of disk that exceeds
        # total_disk_gb, but is less than the oversubscribed limit:
        params = {"root_gb": instance_gb, "memory_mb": 10}
        instance = self._create_fake_instance(params)

        limits = {'disk_gb': oversub_limit_gb}
        filter_properties = {'limits': limits}
        self.compute.run_instance(self.context, instance=instance,
                filter_properties=filter_properties)

        self.assertEqual(instance_gb,
                self.compute.resource_tracker.compute_node['local_gb_used'])

    def test_create_instance_with_oversubscribed_disk_fail(self):
        """Test passing of oversubscribed disk policy from the scheduler, but
        with insufficient disk.
        """
        self.flags(reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.compute.resource_tracker.update_available_resource(
                self.context.elevated())

        # get total memory as reported by virt driver:
        resources = self.compute.driver.get_available_resource()
        total_disk_gb = resources['local_gb']

        oversub_limit_gb = total_disk_gb * 1.5
        instance_gb = int(total_disk_gb * 1.55)

        # build an instance, specifying an amount of disk that exceeds
        # total_disk_gb, but is less than the oversubscribed limit:
        params = {"root_gb": instance_gb, "memory_mb": 10}
        instance = self._create_fake_instance(params)

        limits = {'disk_gb': oversub_limit_gb}
        filter_properties = {'limits': limits}
        self.assertRaises(exception.ComputeResourcesUnavailable,
                self.compute.run_instance, self.context, instance=instance,
                filter_properties=filter_properties)

    def test_default_access_ip(self):
        self.flags(default_access_ip_network_name='test1')
        fake_network.unset_stub_network_methods(self.stubs)
        instance = jsonutils.to_primitive(self._create_fake_instance())

        try:
            self.compute.run_instance(self.context, instance=instance,
                    is_first_time=True)
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertEqual(instance.access_ip_v4, '192.168.1.100')
            self.assertEqual(instance.access_ip_v6, '2001:db8:0:1::1')
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_no_default_access_ip(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())

        try:
            self.compute.run_instance(self.context, instance=instance,
                    is_first_time=True)
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]

            self.assertFalse(instance.access_ip_v4)
            self.assertFalse(instance.access_ip_v6)
        finally:
            db.instance_destroy(self.context, instance['uuid'])

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
        instance = self._create_instance()
        self.assertRaises(test.TestingException, self.compute.run_instance,
                          self.context, instance=instance)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})
        self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})

    def test_run_instance_spawn_fail(self):
        """ spawn failure test.

        Make sure that when there is a spawning problem,
        the instance goes to ERROR state, keeping the task state"""
        def fake(*args, **kwargs):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver, 'spawn', fake)
        instance = self._create_instance()
        self.assertRaises(test.TestingException, self.compute.run_instance,
                          self.context, instance=instance)
        #check state is failed even after the periodic poll
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})
        self.compute.periodic_tasks(context.get_admin_context())
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': None})

    def test_run_instance_dealloc_network_instance_not_found(self):
        """ spawn network deallocate test.

        Make sure that when an instance is not found during spawn
        that the network is deallocated"""
        instance = self._create_instance()

        def fake(*args, **kwargs):
            raise exception.InstanceNotFound()

        self.stubs.Set(self.compute.driver, 'spawn', fake)
        self.mox.StubOutWithMock(self.compute, '_deallocate_network')
        self.compute._deallocate_network(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        self.assertRaises(exception.InstanceNotFound,
                          self.compute.run_instance,
                          self.context, instance=instance)

    def test_can_terminate_on_error_state(self):
        """Make sure that the instance can be terminated in ERROR state"""
        elevated = context.get_admin_context()
        #check failed to schedule --> terminate
        instance = self._create_instance(params={'vm_state': vm_states.ERROR})
        self.compute.terminate_instance(self.context, instance=instance)
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          elevated, instance['uuid'])

    def test_run_terminate(self):
        """Make sure it is possible to  run and terminate instance"""
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        self.compute.terminate_instance(self.context, instance=instance)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)

    def test_run_terminate_with_vol_attached(self):
        """Make sure it is possible to  run and terminate instance with volume
        attached
        """
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

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

        self.compute_api.attach_volume(self.context, instance, 1,
                                       '/dev/vdc')

        self.compute.terminate_instance(self.context, instance=instance)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)
        bdms = db.block_device_mapping_get_all_by_instance(self.context,
                                                           instance['uuid'])
        self.assertEqual(len(bdms), 0)

    def test_terminate_no_network(self):
        # This is as reported in LP bug 1008875
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        # Make it look like this is no instance
        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.compute._get_instance_nw_info(
                mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(exception.NetworkNotFound())
        self.mox.ReplayAll()

        self.compute.terminate_instance(self.context, instance=instance)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)

    def test_terminate_failure_leaves_task_state(self):
        """Ensure that a failure in terminate_instance does not result
        in the task state being reverted from DELETING (see LP 1046236).
        """
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        # Network teardown fails ungracefully
        self.mox.StubOutWithMock(self.compute, '_get_instance_nw_info')
        self.compute._get_instance_nw_info(
                mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(TypeError())
        self.mox.ReplayAll()

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.DELETING})
        try:
            self.compute.terminate_instance(self.context, instance=instance)
        except TypeError:
            pass

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]['task_state'], 'deleting')

    def test_run_terminate_timestamps(self):
        """Make sure timestamps are set for launched and destroyed"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.assertEqual(instance['launched_at'], None)
        self.assertEqual(instance['deleted_at'], None)
        launch = timeutils.utcnow()
        self.compute.run_instance(self.context, instance=instance)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assert_(instance['launched_at'] > launch)
        self.assertEqual(instance['deleted_at'], None)
        terminate = timeutils.utcnow()
        self.compute.terminate_instance(self.context, instance=instance)
        context = self.context.elevated(read_deleted="only")
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assert_(instance['launched_at'] < terminate)
        self.assert_(instance['deleted_at'] > terminate)

    def test_stop(self):
        """Ensure instance can be stopped"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.STOPPING})
        self.compute.stop_instance(self.context, instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_start(self):
        """Ensure instance can be started"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.STOPPING})
        self.compute.stop_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.STARTING})
        self.compute.start_instance(self.context, instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_rescue(self):
        """Ensure instance can be rescued and unrescued"""

        called = {'rescued': False,
                  'unrescued': False}

        def fake_rescue(self, context, instance_ref, network_info, image_meta,
                        rescue_password):
            called['rescued'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'rescue', fake_rescue)

        def fake_unrescue(self, instance_ref, network_info):
            called['unrescued'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'unrescue',
                       fake_unrescue)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.RESCUING})
        self.compute.rescue_instance(self.context, instance=instance)
        self.assertTrue(called['rescued'])
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.UNRESCUING})
        self.compute.unrescue_instance(self.context, instance=instance)
        self.assertTrue(called['unrescued'])

        self.compute.terminate_instance(self.context, instance=instance)

    def test_power_on(self):
        """Ensure instance can be powered on"""

        called = {'power_on': False}

        def fake_driver_power_on(self, instance):
            called['power_on'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'power_on',
                       fake_driver_power_on)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.POWERING_ON})
        self.compute.power_on_instance(self.context, instance=instance)
        self.assertTrue(called['power_on'])
        self.compute.terminate_instance(self.context, instance=instance)

    def test_power_off(self):
        """Ensure instance can be powered off"""

        called = {'power_off': False}

        def fake_driver_power_off(self, instance):
            called['power_off'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'power_off',
                       fake_driver_power_off)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.POWERING_OFF})
        self.compute.power_off_instance(self.context, instance=instance)
        self.assertTrue(called['power_off'])
        self.compute.terminate_instance(self.context, instance=instance)

    def test_pause(self):
        """Ensure instance can be paused and unpaused"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.PAUSING})
        self.compute.pause_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.UNPAUSING})
        self.compute.unpause_instance(self.context, instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_suspend(self):
        """ensure instance can be suspended and resumed"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.SUSPENDING})
        self.compute.suspend_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.RESUMING})
        self.compute.resume_instance(self.context, instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_suspend_error(self):
        """Ensure vm_state is ERROR when suspend error occurs"""
        def fake(*args, **kwargs):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver, 'suspend', fake)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)
        self.assertRaises(test.TestingException,
                          self.compute.suspend_instance,
                          self.context,
                          instance=instance)
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_rebuild(self):
        """Ensure instance can be rebuilt"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        image_ref = instance['image_ref']
        sys_metadata = db.instance_system_metadata_get(self.context,
                        instance['uuid'])
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context, instance,
                                      image_ref, image_ref,
                                      injected_files=[],
                                      new_pass="new_password",
                                      orig_sys_metadata=sys_metadata)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_rebuild_launch_time(self):
        """Ensure instance can be rebuilt"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        image_ref = instance['image_ref']

        self.compute.run_instance(self.context, instance=instance)
        timeutils.set_time_override(cur_time)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context, instance,
                                      image_ref, image_ref,
                                      injected_files=[],
                                      new_pass="new_password")
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEquals(cur_time, instance['launched_at'])
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_reboot_soft(self):
        """Ensure instance can be soft rebooted"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.REBOOTING})

        reboot_type = "SOFT"
        self.compute.reboot_instance(self.context,
                                     instance=instance,
                                     reboot_type=reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['power_state'], power_state.RUNNING)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_reboot_hard(self):
        """Ensure instance can be hard rebooted"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.REBOOTING_HARD})

        reboot_type = "HARD"
        self.compute.reboot_instance(self.context, instance=instance,
                                     reboot_type=reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['power_state'], power_state.RUNNING)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_set_admin_password(self):
        """Ensure instance can have its admin password set"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.UPDATING_PASSWORD})

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

        self.compute.set_admin_password(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], None)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_set_admin_password_bad_state(self):
        """Test setting password while instance is rebuilding."""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'], {
            "power_state": power_state.NOSTATE,
        })
        instance = jsonutils.to_primitive(db.instance_get_by_uuid(
                                          self.context, instance['uuid']))

        self.assertEqual(instance['power_state'], power_state.NOSTATE)

        def fake_driver_get_info(self2, _instance):
            return {'state': power_state.NOSTATE,
                    'max_mem': 0,
                    'mem': 0,
                    'num_cpu': 2,
                    'cpu_time': 0}

        self.stubs.Set(nova.virt.fake.FakeDriver, 'get_info',
                       fake_driver_get_info)

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.UPDATING_PASSWORD})
        self.assertRaises(exception.InstancePasswordSetFailed,
                          self.compute.set_admin_password,
                          self.context,
                          instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def _do_test_set_admin_password_driver_error(self, exc, expected_vm_state,
                                                 expected_task_state):
        """Ensure expected exception is raised if set_admin_password fails"""

        def fake_sleep(_time):
            pass

        self.stubs.Set(time, 'sleep', fake_sleep)

        def fake_driver_set_pass(self2, _instance, _pwd):
            raise exc

        self.stubs.Set(nova.virt.fake.FakeDriver, 'set_admin_password',
                       fake_driver_set_pass)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.UPDATING_PASSWORD})

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], task_states.UPDATING_PASSWORD)

        #error raised from the driver should not reveal internal information
        #so a new error is raised
        self.assertRaises(exception.InstancePasswordSetFailed,
                          self.compute.set_admin_password,
                          self.context,
                          instance=jsonutils.to_primitive(inst_ref))

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['vm_state'], expected_vm_state)
        self.assertEqual(inst_ref['task_state'], expected_task_state)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_set_admin_password_driver_not_authorized(self):
        """
        Ensure expected exception is raised if set_admin_password not
        authorized.
        """
        exc = exception.NotAuthorized(_('Internal error'))
        self._do_test_set_admin_password_driver_error(exc,
                                                vm_states.ERROR,
                                                None)

    def test_set_admin_password_driver_not_implemented(self):
        """
        Ensure expected exception is raised if set_admin_password not
        implemented by driver.
        """
        exc = NotImplementedError()
        self._do_test_set_admin_password_driver_error(exc,
                                                      vm_states.ACTIVE,
                                                      None)

    def test_inject_file(self):
        """Ensure we can write a file to an instance"""
        called = {'inject': False}

        def fake_driver_inject_file(self2, instance, path, contents):
            self.assertEqual(path, "/tmp/test")
            self.assertEqual(contents, "File Contents")
            called['inject'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'inject_file',
                       fake_driver_inject_file)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        self.compute.inject_file(self.context, "/tmp/test",
                "File Contents", instance=instance)
        self.assertTrue(called['inject'])
        self.compute.terminate_instance(self.context, instance=instance)

    def test_inject_network_info(self):
        """Ensure we can inject network info"""
        called = {'inject': False}

        def fake_driver_inject_network(self, instance, network_info):
            called['inject'] = True

        self.stubs.Set(nova.virt.fake.FakeDriver, 'inject_network_info',
                       fake_driver_inject_network)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        self.compute.inject_network_info(self.context, instance=instance)
        self.assertTrue(called['inject'])
        self.compute.terminate_instance(self.context, instance=instance)

    def test_reset_network(self):
        """Ensure we can reset networking on an instance"""
        called = {'count': 0}

        def fake_driver_reset_network(self, instance):
            called['count'] += 1

        self.stubs.Set(nova.virt.fake.FakeDriver, 'reset_network',
                       fake_driver_reset_network)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        self.compute.reset_network(self.context, instance=instance)

        self.assertEqual(called['count'], 1)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_snapshot(self):
        """Ensure instance can be snapshotted"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        name = "myfakesnapshot"
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.IMAGE_SNAPSHOT})
        self.compute.snapshot_instance(self.context, name, instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_snapshot_fails(self):
        """Ensure task_state is set to None if snapshot fails"""
        def fake_snapshot(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.compute.driver, 'snapshot', fake_snapshot)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.IMAGE_SNAPSHOT})
        self.assertRaises(test.TestingException,
                          self.compute.snapshot_instance,
                          self.context, "failing_snapshot", instance=instance)
        self._assert_state({'task_state': None})
        self.compute.terminate_instance(self.context, instance=instance)

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
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        output = self.compute.get_console_output(self.context,
                instance=instance)
        self.assertEqual(output, 'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE')
        self.compute.terminate_instance(self.context, instance=instance)

    def test_console_output_tail(self):
        """Make sure we can get console output from instance"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        output = self.compute.get_console_output(self.context,
                instance=instance, tail_length=2)
        self.assertEqual(output, 'ANOTHER\nLAST LINE')
        self.compute.terminate_instance(self.context, instance=instance)

    def test_novnc_vnc_console(self):
        """Make sure we can a vnc console for an instance."""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        # Try with the full instance
        console = self.compute.get_vnc_console(self.context, 'novnc',
                                               instance=instance)
        self.assert_(console)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_xvpvnc_vnc_console(self):
        """Make sure we can a vnc console for an instance."""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        console = self.compute.get_vnc_console(self.context, 'xvpvnc',
                                               instance=instance)
        self.assert_(console)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_invalid_vnc_console_type(self):
        """Raise useful error if console type is an unrecognised string"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(exception.ConsoleTypeInvalid,
                          self.compute.get_vnc_console,
                          self.context, 'invalid', instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_missing_vnc_console_type(self):
        """Raise useful error is console type is None"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(exception.ConsoleTypeInvalid,
                          self.compute.get_vnc_console,
                          self.context, None, instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_diagnostics(self):
        """Make sure we can get diagnostics for an instance."""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        diagnostics = self.compute.get_diagnostics(self.context,
                instance=instance)
        self.assertEqual(diagnostics, 'FAKE_DIAGNOSTICS')

        diagnostics = self.compute.get_diagnostics(self.context,
                instance=instance)
        self.assertEqual(diagnostics, 'FAKE_DIAGNOSTICS')
        self.compute.terminate_instance(self.context, instance=instance)

    def test_add_fixed_ip_usage_notification(self):
        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(network_api.API, 'add_fixed_ip_to_instance',
                       dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'inject_network_info', dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'reset_network', dummy)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 0)
        self.compute.add_fixed_ip_to_instance(self.context, network_id=1,
                instance=instance)

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_remove_fixed_ip_usage_notification(self):
        def dummy(*args, **kwargs):
            pass

        self.stubs.Set(network_api.API, 'remove_fixed_ip_from_instance',
                       dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'inject_network_info', dummy)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       'reset_network', dummy)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 0)
        self.compute.remove_fixed_ip_from_instance(self.context, 1,
                                                   instance=instance)

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_run_instance_usage_notification(self):
        """Ensure run instance generates appropriate usage notification"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['event_type'], 'compute.instance.create.start')
        self.assertEquals(msg['payload']['image_name'], 'fake_name')
        # The last event is the one with the sugar in it.
        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.create.end')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['image_name'], 'fake_name')
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
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_terminate_usage_notification(self):
        """Ensure terminate_instance generates correct usage notification"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        test_notifier.NOTIFICATIONS = []
        timeutils.set_time_override(cur_time)
        self.compute.terminate_instance(self.context, instance=instance)

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
        self.assertEquals(payload['instance_id'], instance['uuid'])
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
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        self.assertRaises(exception.Invalid,
                          self.compute.run_instance,
                          self.context,
                          instance=instance)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_instance_set_to_error_on_uncaught_exception(self):
        """Test that instance is set to error state when exception is raised"""
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.mox.StubOutWithMock(self.compute.network_api,
                                 "allocate_for_instance")
        self.compute.network_api.allocate_for_instance(
                mox.IgnoreArg(),
                mox.IgnoreArg(),
                requested_networks=None,
                vpn=False).AndRaise(rpc_common.RemoteError())

        fake_network.unset_stub_network_methods(self.stubs)

        self.mox.ReplayAll()

        self.assertRaises(rpc_common.RemoteError,
                          self.compute.run_instance,
                          self.context,
                          instance=instance)

        instance = db.instance_get_by_uuid(context.get_admin_context(),
                                           instance['uuid'])
        self.assertEqual(vm_states.ERROR, instance['vm_state'])

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_delete_instance_succedes_on_volume_fail(self):
        instance = self._create_fake_instance()

        def fake_cleanup_volumes(context, instance):
            raise test.TestingException()

        self.stubs.Set(self.compute, '_cleanup_volumes',
                       fake_cleanup_volumes)

        self.compute._delete_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_delete_instance_deletes_console_auth_tokens(self):
        instance = self._create_fake_instance()
        self.flags(vnc_enabled=True)

        self.tokens_deleted = False

        def fake_delete_tokens(*args, **kwargs):
            self.tokens_deleted = True

        cauth_rpcapi = self.compute.consoleauth_rpcapi
        self.stubs.Set(cauth_rpcapi, 'delete_tokens_for_instance',
                       fake_delete_tokens)

        self.compute._delete_instance(self.context,
                instance=jsonutils.to_primitive(instance))

        self.assertTrue(self.tokens_deleted)

    def test_instance_termination_exception_sets_error(self):
        """Test that we handle InstanceTerminationFailure
        which is propagated up from the underlying driver.
        """
        instance = self._create_fake_instance()

        def fake_delete_instance(context, instance):
            raise exception.InstanceTerminationFailure(reason='')

        self.stubs.Set(self.compute, '_delete_instance',
                       fake_delete_instance)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)

    def test_network_is_deallocated_on_spawn_failure(self):
        """When a spawn fails the network must be deallocated"""
        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.mox.StubOutWithMock(self.compute, "_setup_block_device_mapping")
        self.compute._setup_block_device_mapping(
                mox.IgnoreArg(),
                mox.IgnoreArg()).AndRaise(rpc.common.RemoteError('', '', ''))

        self.mox.ReplayAll()

        self.assertRaises(rpc.common.RemoteError,
                          self.compute.run_instance,
                          self.context, instance=instance)

        self.compute.terminate_instance(self.context, instance=instance)

    def test_lock(self):
        """ensure locked instance cannot be changed"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        non_admin_context = context.RequestContext(None,
                                                   None,
                                                   is_admin=False)

        def check_task_state(task_state):
            instance = db.instance_get_by_uuid(self.context, instance_uuid)
            self.assertEqual(instance['task_state'], task_state)

        # should fail with locked nonadmin context
        self.compute_api.lock(self.context, instance)
        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertRaises(exception.InstanceIsLocked,
                          self.compute_api.reboot,
                          non_admin_context, instance, 'SOFT')
        check_task_state(None)

        # should fail with invalid task state
        self.compute_api.unlock(self.context, instance)
        instance = db.instance_update(self.context, instance_uuid,
                                      {'task_state': task_states.REBOOTING})
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.reboot,
                          non_admin_context, instance, 'SOFT')
        check_task_state(task_states.REBOOTING)

        # should succeed with admin context
        instance = db.instance_update(self.context, instance_uuid,
                                      {'task_state': None})
        self.compute_api.reboot(self.context, instance, 'SOFT')
        check_task_state(task_states.REBOOTING)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def _test_state_revert(self, operation, pre_task_state,
                           post_task_state):
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context, instance=instance)

        # The API would have set task_state, so do that here to test
        # that the state gets reverted on failure
        db.instance_update(self.context, instance['uuid'],
                           {"task_state": pre_task_state})

        orig_elevated = self.context.elevated
        orig_notify = self.compute._notify_about_instance_usage

        def _get_an_exception(*args, **kwargs):
            raise Exception("This fails every single time!")

        self.stubs.Set(self.context, 'elevated', _get_an_exception)
        self.stubs.Set(self.compute,
                       '_notify_about_instance_usage', _get_an_exception)

        raised = False
        try:
            ret_val = getattr(self.compute, operation)(self.context,
                                                       instance=instance)
        except Exception:
            raised = True
        finally:
            # self.context.elevated() is called in tearDown()
            self.stubs.Set(self.context, 'elevated', orig_elevated)
            self.stubs.Set(self.compute,
                           '_notify_about_instance_usage', orig_notify)

        self.assertTrue(raised)

        # Fetch the instance's task_state and make sure it went to expected
        # post-state
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance["task_state"], post_task_state)

    def test_state_revert(self):
        """ensure that task_state is reverted after a failed operation"""
        actions = [
            ("reboot_instance", task_states.REBOOTING, None),
            ("stop_instance", task_states.STOPPING, None),
            ("start_instance", task_states.STARTING, None),
            ("terminate_instance", task_states.DELETING,
                                   task_states.DELETING),
            ("power_off_instance", task_states.POWERING_OFF, None),
            ("power_on_instance", task_states.POWERING_ON, None),
            ("rebuild_instance", task_states.REBUILDING, None),
            ("set_admin_password", task_states.UPDATING_PASSWORD, None),
            ("rescue_instance", task_states.RESCUING, None),
            ("unrescue_instance", task_states.UNRESCUING, None),
            ("revert_resize", task_states.RESIZE_REVERTING, None),
            ("prep_resize", task_states.RESIZE_PREP, None),
            ("resize_instance", task_states.RESIZE_PREP, None),
            ("pause_instance", task_states.PAUSING, None),
            ("unpause_instance", task_states.UNPAUSING, None),
            ("suspend_instance", task_states.SUSPENDING, None),
            ("resume_instance", task_states.RESUMING, None),
            ]

        for operation, pre_state, post_state in actions:
            self._test_state_revert(operation, pre_state, post_state)

    def _ensure_quota_reservations_committed(self):
        """Mock up commit of quota reservations"""
        reservations = list('fake_res')
        self.mox.StubOutWithMock(nova.quota.QUOTAS, 'commit')
        nova.quota.QUOTAS.commit(mox.IgnoreArg(), reservations)
        self.mox.ReplayAll()
        return reservations

    def _ensure_quota_reservations_rolledback(self):
        """Mock up rollback of quota reservations"""
        reservations = list('fake_res')
        self.mox.StubOutWithMock(nova.quota.QUOTAS, 'rollback')
        nova.quota.QUOTAS.rollback(mox.IgnoreArg(), reservations)
        self.mox.ReplayAll()
        return reservations

    def test_finish_resize(self):
        """Contrived test to ensure finish_resize doesn't raise anything"""

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)

        reservations = self._ensure_quota_reservations_committed()

        context = self.context.elevated()
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_type = instance_types.get_default_instance_type()
        db.instance_update(self.context, instance["uuid"],
                          {"task_state": task_states.RESIZE_PREP})
        self.compute.prep_resize(context, instance=instance,
                                 instance_type=instance_type,
                                 image={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'pre-migrating')
        db.instance_update(self.context, instance["uuid"],
                           {"task_state": task_states.RESIZE_MIGRATED})
        self.compute.finish_resize(context,
                migration_id=int(migration_ref['id']),
                disk_info={}, image={}, instance=instance,
                reservations=reservations)
        self.compute.terminate_instance(self.context, instance=instance)

    def test_finish_resize_handles_error(self):
        """Make sure we don't leave the instance in RESIZE on error"""

        def throw_up(*args, **kwargs):
            raise test.TestingException()

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', throw_up)

        reservations = self._ensure_quota_reservations_rolledback()

        context = self.context.elevated()
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_type = instance_types.get_default_instance_type()
        self.compute.prep_resize(context, instance=instance,
                                 instance_type=instance_type,
                                 image={}, reservations=reservations)
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance['uuid'], 'pre-migrating')

        db.instance_update(self.context, instance["uuid"],
                           {"task_state": task_states.RESIZE_MIGRATED})
        self.assertRaises(test.TestingException, self.compute.finish_resize,
                          context, migration_id=int(migration_ref['id']),
                          disk_info={}, image={}, instance=instance,
                          reservations=reservations)

        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_rebuild_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        inst_ref = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=inst_ref)
        timeutils.set_time_override(cur_time)

        test_notifier.NOTIFICATIONS = []
        instance = db.instance_get_by_uuid(self.context, inst_ref['uuid'])
        orig_sys_metadata = db.instance_system_metadata_get(self.context,
                inst_ref['uuid'])
        image_ref = instance["image_ref"]
        new_image_ref = image_ref + '-new_image_ref'
        db.instance_update(self.context, inst_ref['uuid'],
                           {'image_ref': new_image_ref})

        password = "new_password"

        instance = db.instance_get_by_uuid(self.context, inst_ref['uuid'])

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBUILDING})
        self.compute.rebuild_instance(self.context.elevated(),
                                      jsonutils.to_primitive(instance),
                                      image_ref, new_image_ref,
                                      injected_files=[],
                                      new_pass=password,
                                      orig_sys_metadata=orig_sys_metadata)

        instance = db.instance_get_by_uuid(self.context, inst_ref['uuid'])

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
        self.assertEquals(msg['payload']['image_name'], 'fake_name')
        msg = test_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg['event_type'],
                          'compute.instance.rebuild.end')
        self.assertEquals(msg['priority'], 'INFO')
        payload = msg['payload']
        self.assertEquals(payload['image_name'], 'fake_name')
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], inst_ref['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEqual(payload['launched_at'], str(cur_time))
        self.assertEquals(payload['image_ref_url'], new_image_ref_url)
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_finish_resize_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        instance = jsonutils.to_primitive(self._create_fake_instance())
        context = self.context.elevated()
        old_type_id = instance_types.get_instance_type_by_name(
                                                'm1.tiny')['id']
        new_type = instance_types.get_instance_type_by_name('m1.small')
        new_type = jsonutils.to_primitive(new_type)
        new_type_id = new_type['id']
        self.compute.run_instance(self.context, instance=instance)

        new_instance = db.instance_update(self.context, instance['uuid'],
                                      {'host': 'foo'})
        new_instance = jsonutils.to_primitive(new_instance)
        db.instance_update(self.context, new_instance["uuid"],
                           {"task_state": task_states.RESIZE_PREP})
        self.compute.prep_resize(context, instance=new_instance,
                instance_type=new_type, image={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                new_instance['uuid'], 'pre-migrating')
        self.compute.resize_instance(context, instance=new_instance,
                                     migration_id=migration_ref['id'],
                                     image={})
        timeutils.set_time_override(cur_time)
        test_notifier.NOTIFICATIONS = []

        self.compute.finish_resize(context,
                migration_id=int(migration_ref['id']), disk_info={}, image={},
                instance=new_instance)

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
        self.assertEquals(payload['instance_id'], new_instance['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.small')
        self.assertEquals(str(payload['instance_type_id']), str(new_type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEqual(payload['launched_at'], str(cur_time))
        image_ref_url = utils.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(context,
            instance=jsonutils.to_primitive(new_instance))

    def test_resize_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        old_time = datetime.datetime(2012, 4, 1)
        cur_time = datetime.datetime(2012, 12, 21, 12, 21)
        timeutils.set_time_override(old_time)
        instance = jsonutils.to_primitive(self._create_fake_instance())
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance=instance)
        timeutils.set_time_override(cur_time)
        test_notifier.NOTIFICATIONS = []

        new_instance = db.instance_update(self.context, instance['uuid'],
                                      {'host': 'foo'})
        new_instance = jsonutils.to_primitive(new_instance)
        instance_type = instance_types.get_default_instance_type()
        self.compute.prep_resize(context, instance=new_instance,
                instance_type=instance_type, image={})
        db.migration_get_by_instance_and_status(context,
                                                new_instance['uuid'],
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
        self.assertEquals(payload['instance_id'], new_instance['uuid'])
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        image_ref_url = utils.generate_image_url(FAKE_IMAGE_REF)
        self.assertEquals(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(context, instance=new_instance)

    def test_prep_resize_instance_migration_error_on_same_host(self):
        """Ensure prep_resize raise a migration error if destination is set on
        the same source host and allow_resize_to_same_host is false
        """
        self.flags(host="foo", allow_resize_to_same_host=False)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        context = self.context.elevated()

        reservations = self._ensure_quota_reservations_rolledback()

        self.compute.run_instance(self.context, instance=instance)
        new_instance = db.instance_update(self.context, instance['uuid'],
                                          {'host': self.compute.host})
        new_instance = jsonutils.to_primitive(new_instance)
        instance_type = instance_types.get_default_instance_type()

        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                          context, instance=new_instance,
                          instance_type=instance_type, image={},
                          reservations=reservations)
        self.compute.terminate_instance(context, instance=new_instance)

    def test_prep_resize_instance_migration_error_on_none_host(self):
        """Ensure prep_resize raise a migration error if destination host is
        not defined
        """
        instance = jsonutils.to_primitive(self._create_fake_instance())

        reservations = self._ensure_quota_reservations_rolledback()

        self.compute.run_instance(self.context, instance=instance)
        new_instance = db.instance_update(self.context, instance['uuid'],
                                          {'host': None})
        new_instance = jsonutils.to_primitive(new_instance)
        instance_type = instance_types.get_default_instance_type()

        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                          self.context, instance=new_instance,
                          instance_type=instance_type, image={},
                          reservations=reservations)
        self.compute.terminate_instance(self.context, instance=new_instance)

    def test_resize_instance_driver_error(self):
        """Ensure instance status set to Error on resize error"""

        def throw_up(*args, **kwargs):
            raise test.TestingException()

        self.stubs.Set(self.compute.driver, 'migrate_disk_and_power_off',
                       throw_up)

        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_type = instance_types.get_default_instance_type()
        context = self.context.elevated()

        reservations = self._ensure_quota_reservations_rolledback()

        self.compute.run_instance(self.context, instance=instance)
        new_instance = db.instance_update(self.context, instance['uuid'],
                                          {'host': 'foo'})
        new_instance = jsonutils.to_primitive(new_instance)
        self.compute.prep_resize(context, instance=new_instance,
                                 instance_type=instance_type, image={},
                                 reservations=reservations)
        migration_ref = db.migration_get_by_instance_and_status(context,
                new_instance['uuid'], 'pre-migrating')

        db.instance_update(self.context, new_instance['uuid'],
                           {"task_state": task_states.RESIZE_PREP})
        #verify
        self.assertRaises(test.TestingException, self.compute.resize_instance,
                          context, instance=new_instance,
                          migration_id=migration_ref['id'], image={},
                          reservations=reservations)
        instance = db.instance_get_by_uuid(context, new_instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ERROR)

        self.compute.terminate_instance(context,
            instance=jsonutils.to_primitive(instance))

    def test_resize_instance(self):
        """Ensure instance can be migrated/resized"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_type = instance_types.get_default_instance_type()
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance=instance)
        new_instance = db.instance_update(self.context, instance['uuid'],
                           {'host': 'foo'})
        new_instance = jsonutils.to_primitive(new_instance)
        self.compute.prep_resize(context, instance=new_instance,
                instance_type=instance_type, image={})
        migration_ref = db.migration_get_by_instance_and_status(context,
                new_instance['uuid'], 'pre-migrating')
        db.instance_update(self.context, new_instance['uuid'],
                           {"task_state": task_states.RESIZE_PREP})
        self.compute.resize_instance(context, instance=new_instance,
                                     migration_id=migration_ref['id'],
                                     image={})
        inst = db.instance_get_by_uuid(self.context, new_instance['uuid'])
        self.assertEqual(migration_ref['dest_compute'], inst['host'])

        self.compute.terminate_instance(self.context,
            instance=jsonutils.to_primitive(inst))

    def test_finish_revert_resize(self):
        """Ensure that the flavor is reverted to the original on revert"""
        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.driver, 'finish_revert_migration', fake)

        reservations = self._ensure_quota_reservations_committed()

        context = self.context.elevated()
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']

        self.compute.run_instance(self.context, instance=instance)

        # Confirm the instance size before the resize starts
        inst_ref = db.instance_get_by_uuid(context, instance['uuid'])
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '1')

        new_inst_ref = db.instance_update(self.context, instance['uuid'],
                                          {'host': 'foo'})

        new_instance_type_ref = db.instance_type_get_by_flavor_id(context, 3)
        self.compute.prep_resize(context,
                instance=jsonutils.to_primitive(new_inst_ref),
                instance_type=jsonutils.to_primitive(new_instance_type_ref),
                image={}, reservations=reservations)

        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')

        instance = jsonutils.to_primitive(inst_ref)
        db.instance_update(self.context, instance["uuid"],
                           {"task_state": task_states.RESIZE_PREP})
        self.compute.resize_instance(context, instance=instance,
                                     migration_id=migration_ref['id'],
                                     image={})
        self.compute.finish_resize(context,
                    migration_id=int(migration_ref['id']), disk_info={},
                    image={}, instance=instance)

        # Prove that the instance size is now the new size
        inst_ref = db.instance_get_by_uuid(context, instance['uuid'])
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '3')

        # Finally, revert and confirm the old flavor has been applied
        rpcinst = jsonutils.to_primitive(inst_ref)
        db.instance_update(self.context, instance["uuid"],
                           {"task_state": task_states.RESIZE_REVERTING})
        self.compute.revert_resize(context,
                migration_id=migration_ref['id'], instance=rpcinst,
                reservations=reservations)

        def fake_setup_networks_on_host(cls, ctxt, instance, host):
            self.assertEqual(host, migration_ref['source_compute'])
            inst = db.instance_get_by_uuid(ctxt, instance['uuid'])
            self.assertEqual(host, inst['host'])

        self.stubs.Set(network_api.API, 'setup_networks_on_host',
                       fake_setup_networks_on_host)

        self.compute.finish_revert_resize(context,
                migration_id=migration_ref['id'], instance=rpcinst,
                reservations=reservations)

        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.ACTIVE)
        self.assertEqual(instance['task_state'], None)

        inst_ref = db.instance_get_by_uuid(context, instance['uuid'])
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], '1')
        self.assertEqual(inst_ref['host'], migration_ref['source_compute'])

        self.compute.terminate_instance(context,
            instance=jsonutils.to_primitive(inst_ref))

    def test_get_by_flavor_id(self):
        type = instance_types.get_instance_type_by_flavor_id(1)
        self.assertEqual(type['name'], 'm1.tiny')

    def test_resize_same_source_fails(self):
        """Ensure instance fails to migrate when source and destination are
        the same host"""
        reservations = self._ensure_quota_reservations_rolledback()
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        instance_type = instance_types.get_default_instance_type()
        self.assertRaises(exception.MigrationError, self.compute.prep_resize,
                self.context, instance=instance,
                instance_type=instance_type, image={},
                reservations=reservations)
        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

    def test_resize_instance_handles_migration_error(self):
        """Ensure vm_state is ERROR when error occurs"""
        def raise_migration_failure(*args):
            raise test.TestingException()
        self.stubs.Set(self.compute.driver,
                'migrate_disk_and_power_off',
                raise_migration_failure)

        reservations = self._ensure_quota_reservations_rolledback()

        inst_ref = jsonutils.to_primitive(self._create_fake_instance())
        instance_type = instance_types.get_default_instance_type()
        context = self.context.elevated()

        self.compute.run_instance(self.context, instance=inst_ref)
        inst_ref = db.instance_update(self.context, inst_ref['uuid'],
                                      {'host': 'foo'})
        inst_ref = jsonutils.to_primitive(inst_ref)
        self.compute.prep_resize(context, instance=inst_ref,
                                 instance_type=instance_type,
                                 image={}, reservations=reservations)
        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')
        db.instance_update(self.context, inst_ref['uuid'],
                           {"task_state": task_states.RESIZE_PREP})
        self.assertRaises(test.TestingException, self.compute.resize_instance,
                          context, instance=inst_ref,
                          migration_id=migration_ref['id'], image={},
                          reservations=reservations)
        inst_ref = db.instance_get_by_uuid(context, inst_ref['uuid'])
        self.assertEqual(inst_ref['vm_state'], vm_states.ERROR)
        self.compute.terminate_instance(context,
            instance=jsonutils.to_primitive(inst_ref))

    def test_check_can_live_migrate_source_works_correctly(self):
        """Confirm check_can_live_migrate_source works on positive path"""
        context = self.context.elevated()
        inst_ref = jsonutils.to_primitive(self._create_fake_instance(
                                          {'host': 'fake_host_2'}))
        inst_id = inst_ref["id"]
        dest = "fake_host_1"

        self.mox.StubOutWithMock(db, 'instance_get')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_source')

        dest_check_data = {"test": "data"}
        self.compute.driver.check_can_live_migrate_source(context,
                                                          inst_ref,
                                                          dest_check_data)

        self.mox.ReplayAll()
        self.compute.check_can_live_migrate_source(context,
                dest_check_data=dest_check_data, instance=inst_ref)

    def test_check_can_live_migrate_destination_works_correctly(self):
        """Confirm check_can_live_migrate_destination works on positive path"""
        context = self.context.elevated()
        inst_ref = jsonutils.to_primitive(self._create_fake_instance(
                                          {'host': 'fake_host_2'}))
        inst_id = inst_ref["id"]
        dest = "fake_host_1"

        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_destination')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'check_can_live_migrate_source')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_destination_cleanup')

        dest_check_data = {"test": "data"}
        self.compute.driver.check_can_live_migrate_destination(context,
                inst_ref, True, False).AndReturn(dest_check_data)
        self.compute.compute_rpcapi.check_can_live_migrate_source(context,
                inst_ref, dest_check_data)
        self.compute.driver.check_can_live_migrate_destination_cleanup(
                context, dest_check_data)

        self.mox.ReplayAll()
        self.compute.check_can_live_migrate_destination(context,
                block_migration=True, disk_over_commit=False,
                instance=inst_ref)

    def test_check_can_live_migrate_destination_fails_dest_check(self):
        """Confirm check_can_live_migrate_destination works on positive path"""
        context = self.context.elevated()
        inst_ref = jsonutils.to_primitive(self._create_fake_instance(
                                          {'host': 'fake_host_2'}))
        inst_id = inst_ref["id"]
        dest = "fake_host_1"

        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_destination')

        self.compute.driver.check_can_live_migrate_destination(context,
                inst_ref, True, False).AndRaise(exception.Invalid())

        self.mox.ReplayAll()
        self.assertRaises(exception.Invalid,
                          self.compute.check_can_live_migrate_destination,
                          context, block_migration=True,
                          disk_over_commit=False, instance=inst_ref)

    def test_check_can_live_migrate_destination_fails_source(self):
        """Confirm check_can_live_migrate_destination works on positive path"""
        context = self.context.elevated()
        inst_ref = jsonutils.to_primitive(self._create_fake_instance(
                                          {'host': 'fake_host_2'}))
        inst_id = inst_ref["id"]
        dest = "fake_host_1"

        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_destination')
        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'check_can_live_migrate_source')
        self.mox.StubOutWithMock(self.compute.driver,
                                 'check_can_live_migrate_destination_cleanup')

        dest_check_data = {"test": "data"}
        self.compute.driver.check_can_live_migrate_destination(context,
                inst_ref, True, False).AndReturn(dest_check_data)
        self.compute.compute_rpcapi.check_can_live_migrate_source(context,
                inst_ref, dest_check_data).AndRaise(exception.Invalid())
        self.compute.driver.check_can_live_migrate_destination_cleanup(
                context, dest_check_data)

        self.mox.ReplayAll()
        self.assertRaises(exception.Invalid,
                          self.compute.check_can_live_migrate_destination,
                          context, block_migration=True,
                          disk_over_commit=False, instance=inst_ref)

    def test_pre_live_migration_instance_has_no_fixed_ip(self):
        """Confirm raising exception if instance doesn't have fixed_ip."""
        # creating instance testdata
        context = self.context.elevated()
        instance = jsonutils.to_primitive(self._create_fake_instance())
        inst_id = instance["id"]

        self.mox.ReplayAll()
        self.assertRaises(exception.FixedIpNotFoundForInstance,
                          self.compute.pre_live_migration, context,
                          instance=instance)

    def test_pre_live_migration_works_correctly(self):
        """Confirm setup_compute_volume is called when volume is mounted."""
        def stupid(*args, **kwargs):
            return fake_network.fake_get_instance_nw_info(self.stubs,
                                                          spectacular=True)
        self.stubs.Set(nova.compute.manager.ComputeManager,
                       '_get_instance_nw_info', stupid)

        # creating instance testdata
        instance = jsonutils.to_primitive(self._create_fake_instance(
                                          {'host': 'dummy'}))
        inst_id = instance['id']
        c = context.get_admin_context()
        nw_info = fake_network.fake_get_instance_nw_info(self.stubs)

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'pre_live_migration')
        self.compute.driver.pre_live_migration(mox.IsA(c), mox.IsA(instance),
                                               {'block_device_mapping': []},
                                               mox.IgnoreArg())
        self.mox.StubOutWithMock(self.compute.driver,
                                 'ensure_filtering_rules_for_instance')
        self.compute.driver.ensure_filtering_rules_for_instance(
            mox.IsA(instance), nw_info)

        # start test
        self.mox.ReplayAll()
        ret = self.compute.pre_live_migration(c, instance=instance)
        self.assertEqual(ret, None)

        # cleanup
        db.instance_destroy(c, instance['uuid'])

    def test_live_migration_dest_raises_exception(self):
        """Confirm exception when pre_live_migration fails."""
        # creating instance testdata
        instance_ref = self._create_fake_instance({'host': 'dummy'})
        instance = jsonutils.to_primitive(instance_ref)
        inst_uuid = instance['uuid']
        inst_id = instance['id']

        c = context.get_admin_context()
        topic = rpc.queue_get_for(c, FLAGS.compute_topic, instance['host'])

        # creating volume testdata
        volume_id = db.volume_create(c, {'size': 1})['id']
        values = {'instance_uuid': inst_uuid, 'device_name': '/dev/vdc',
                  'delete_on_termination': False, 'volume_id': volume_id}
        db.block_device_mapping_create(c, values)

        # creating mocks
        self.mox.StubOutWithMock(rpc, 'call')

        self.mox.StubOutWithMock(self.compute.driver,
                                 'get_instance_disk_info')
        self.compute.driver.get_instance_disk_info(instance['name'])

        self.mox.StubOutWithMock(self.compute.compute_rpcapi,
                                 'pre_live_migration')
        self.compute.compute_rpcapi.pre_live_migration(c,
                mox.IsA(instance), True, None, instance['host']).AndRaise(
                                        rpc.common.RemoteError('', '', ''))

        db.instance_update(self.context, instance['uuid'],
                           {'task_state': task_states.MIGRATING})
        # mocks for rollback
        rpc.call(c, 'network', {'method': 'setup_networks_on_host',
                                'args': {'instance_id': inst_id,
                                         'host': self.compute.host,
                                         'teardown': False}})
        rpcinst = jsonutils.to_primitive(
                db.instance_get_by_uuid(self.context, instance['uuid']))
        rpc.call(c, topic,
                {"method": "remove_volume_connection",
                 "args": {'instance': rpcinst,
                          'volume_id': volume_id},
                 "version": compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION},
                 None)
        rpc.cast(c, topic,
                {"method": "rollback_live_migration_at_destination",
                 "args": {'instance': rpcinst},
                 "version": compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})

        # start test
        self.mox.ReplayAll()
        self.assertRaises(rpc_common.RemoteError,
                          self.compute.live_migration,
                          c, dest=instance['host'], block_migration=True,
                          instance=rpcinst)

        # cleanup
        for bdms in db.block_device_mapping_get_all_by_instance(
            c, inst_uuid):
            db.block_device_mapping_destroy(c, bdms['id'])
        db.volume_destroy(c, volume_id)
        db.instance_destroy(c, inst_uuid)

    def test_live_migration_works_correctly(self):
        """Confirm live_migration() works as expected correctly."""
        # creating instance testdata
        c = context.get_admin_context()
        instance_ref = self._create_fake_instance({'host': 'dummy'})
        inst_uuid = instance_ref['uuid']
        inst_id = instance_ref['id']

        instance = jsonutils.to_primitive(db.instance_get(c, inst_id))

        # create
        self.mox.StubOutWithMock(rpc, 'call')
        topic = rpc.queue_get_for(c, FLAGS.compute_topic, instance['host'])
        rpc.call(c, topic,
                {"method": "pre_live_migration",
                 "args": {'instance': instance,
                          'block_migration': False,
                          'disk': None},
                 "version": compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION},
                None)

        # start test
        self.mox.ReplayAll()
        ret = self.compute.live_migration(c, dest=instance['host'],
                instance=instance)
        self.assertEqual(ret, None)

        # cleanup
        db.instance_destroy(c, inst_uuid)

    def test_post_live_migration_working_correctly(self):
        """Confirm post_live_migration() works as expected correctly."""
        dest = 'desthost'
        flo_addr = '1.2.1.2'

        # creating testdata
        c = context.get_admin_context()
        inst_ref = jsonutils.to_primitive(self._create_fake_instance({
                                'state_description': 'migrating',
                                'state': power_state.PAUSED}))
        inst_uuid = inst_ref['uuid']
        inst_id = inst_ref['id']

        db.instance_update(c, inst_uuid,
                           {'task_state': task_states.MIGRATING,
                            'power_state': power_state.PAUSED})
        v_ref = db.volume_create(c, {'size': 1, 'instance_id': inst_id})
        fix_addr = db.fixed_ip_create(c, {'address': '1.1.1.1',
                                          'instance_uuid': inst_ref['uuid']})
        fix_ref = db.fixed_ip_get_by_address(c, fix_addr)
        db.floating_ip_create(c, {'address': flo_addr,
                                  'fixed_ip_id': fix_ref['id']})

        # creating mocks
        self.mox.StubOutWithMock(self.compute.driver, 'unfilter_instance')
        self.compute.driver.unfilter_instance(inst_ref, [])
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, rpc.queue_get_for(c, FLAGS.compute_topic, dest),
            {"method": "post_live_migration_at_destination",
             "args": {'instance': inst_ref, 'block_migration': False},
             "version": compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION},
            None)
        self.mox.StubOutWithMock(self.compute.driver, 'unplug_vifs')
        self.compute.driver.unplug_vifs(inst_ref, [])
        rpc.call(c, 'network', {'method': 'setup_networks_on_host',
                                'args': {'instance_id': inst_id,
                                         'host': self.compute.host,
                                         'teardown': True}})

        # start test
        self.mox.ReplayAll()
        self.compute._post_live_migration(c, inst_ref, dest)

        # make sure floating ips are rewritten to destinatioin hostname.
        flo_refs = db.floating_ip_get_all_by_host(c, dest)
        self.assertTrue(flo_refs)
        self.assertEqual(flo_refs[0]['address'], flo_addr)

        # cleanup
        db.instance_destroy(c, inst_uuid)
        db.volume_destroy(c, v_ref['id'])
        db.floating_ip_destroy(c, flo_addr)

    def test_run_kill_vm(self):
        """Detect when a vm is terminated behind the scenes"""
        self.stubs.Set(compute_manager.ComputeManager,
                '_report_driver_status', nop_report_driver_status)

        instance = jsonutils.to_primitive(self._create_fake_instance())

        self.compute.run_instance(self.context, instance=instance)

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
        self.assertEqual(instances[0]['task_state'], None)

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
        compute_utils.add_instance_fault_from_exc(ctxt, instance_uuid,
                                                  NotImplementedError('test'),
                                                  exc_info)

    def test_add_instance_fault_with_remote_error(self):
        exc_info = None
        instance_uuid = str(utils.gen_uuid())

        def fake_db_fault_create(ctxt, values):
            self.assertTrue(values['details'].startswith('Remote error'))
            self.assertTrue('raise rpc_common.RemoteError'
                in values['details'])
            del values['details']

            expected = {
                'code': 500,
                'instance_uuid': instance_uuid,
                'message': 'My Test Message'
            }
            self.assertEquals(expected, values)

        try:
            raise rpc_common.RemoteError('test', 'My Test Message')
        except rpc_common.RemoteError as exc:
            exc_info = sys.exc_info()

        self.stubs.Set(nova.db, 'instance_fault_create', fake_db_fault_create)

        ctxt = context.get_admin_context()
        compute_utils.add_instance_fault_from_exc(ctxt, instance_uuid,
            exc,
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
        compute_utils.add_instance_fault_from_exc(ctxt, instance_uuid,
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
        compute_utils.add_instance_fault_from_exc(ctxt, instance_uuid,
                                                  NotImplementedError('test'))

    def test_cleanup_running_deleted_instances(self):
        admin_context = context.get_admin_context()
        deleted_at = (timeutils.utcnow() -
                      datetime.timedelta(hours=1, minutes=5))
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
        self.compute._shutdown_instance(admin_context,
                                        instance).AndReturn(None)

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

        self.mox.StubOutWithMock(timeutils, 'is_older_than')
        timeutils.is_older_than('sometimeago',
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
        instances = [{'uuid': 'fake_uuid1', 'vm_state': vm_states.RESIZED,
                      'task_state': None},
                     {'uuid': 'noexist'},
                     {'uuid': 'fake_uuid2', 'vm_state': vm_states.ERROR,
                      'task_state': None},
                     {'uuid': 'fake_uuid3', 'vm_state': vm_states.ACTIVE,
                      'task_state': task_states.REBOOTING},
                     {'uuid': 'fake_uuid4', 'vm_state': vm_states.RESIZED,
                      'task_state': None},
                     {'uuid': 'fake_uuid5', 'vm_state': vm_states.ACTIVE,
                      'task_state': None},
                     {'uuid': 'fake_uuid6', 'vm_state': vm_states.RESIZED,
                      'task_state': 'deleting'}]
        expected_migration_status = {'fake_uuid1': 'confirmed',
                                     'noexist': 'error',
                                     'fake_uuid2': 'error',
                                     'fake_uuid3': 'error',
                                     'fake_uuid4': None,
                                     'fake_uuid5': 'error',
                                     'fake_uuid6': 'error'}
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

        def fake_migration_get_unconfirmed_by_dest_compute(context,
                resize_confirm_window, dest_compute):
            self.assertEqual(dest_compute, FLAGS.host)
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
        self.stubs.Set(db, 'migration_get_unconfirmed_by_dest_compute',
                fake_migration_get_unconfirmed_by_dest_compute)
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
        created_at = timeutils.utcnow() + datetime.timedelta(seconds=-60)

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
        created_at = timeutils.utcnow() + datetime.timedelta(seconds=-60)

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
        created_at = timeutils.utcnow() + datetime.timedelta(seconds=-60)

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
        instance_map[uuid] = {
            'uuid': uuid,
            'host': FLAGS.host,
            'vm_state': vm_states.BUILDING,
            'created_at': timeutils.utcnow(),
        }
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
        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                       fake_get_nw_info)
        self.security_group_api = compute.api.SecurityGroupAPI()
        self.compute_api = compute.API(
                                   security_group_api=self.security_group_api)
        self.fake_image = {
            'id': 1,
            'name': 'fake_name',
            'properties': {'kernel_id': 'fake_kernel_id',
                           'ramdisk_id': 'fake_ramdisk_id'},
        }

    def _run_instance(self, params=None):
        instance = jsonutils.to_primitive(self._create_fake_instance(params))
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

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
        db.instance_destroy(self.context, refs[0]['uuid'])

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
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_create_just_enough_ram_and_disk(self):
        """Test an instance type with just enough ram and disk space"""

        inst_type = instance_types.get_default_instance_type()
        inst_type['root_gb'] = 2
        inst_type['memory_mb'] = 2

        def fake_show(*args):
            img = copy.copy(self.fake_image)
            img['min_ram'] = 2
            img['min_disk'] = 2
            img['name'] = 'fake_name'
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        (refs, resv_id) = self.compute_api.create(self.context,
                inst_type, None)
        db.instance_destroy(self.context, refs[0]['uuid'])

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
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_create_instance_defaults_display_name(self):
        """Verify that an instance cannot be created without a display_name."""
        cases = [dict(), dict(display_name=None)]
        for instance in cases:
            (ref, resv_id) = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None, **instance)
            try:
                self.assertNotEqual(ref[0]['display_name'], None)
            finally:
                db.instance_destroy(self.context, ref[0]['uuid'])

    def test_create_instance_sets_system_metadata(self):
        """Make sure image properties are copied into system metadata."""
        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None)
        try:
            sys_metadata = db.instance_system_metadata_get(self.context,
                    ref[0]['uuid'])

            image_props = {'image_kernel_id': 'fake_kernel_id',
                     'image_ramdisk_id': 'fake_ramdisk_id',
                     'image_something_else': 'meow', }
            for key, value in image_props.iteritems():
                self.assertTrue(key in sys_metadata)
                self.assertEqual(value, sys_metadata[key])

        finally:
            db.instance_destroy(self.context, ref[0]['uuid'])

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
            db.instance_destroy(self.context, ref[0]['uuid'])

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

    def test_create_with_large_user_data(self):
        """Test an instance type with too much user data."""

        inst_type = instance_types.get_default_instance_type()

        def fake_show(*args):
            img = copy.copy(self.fake_image)
            img['min_ram'] = 2
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        self.assertRaises(exception.InstanceUserDataTooLarge,
            self.compute_api.create, self.context, inst_type, None,
                          user_data=('1' * 65536))

    def test_create_with_malformed_user_data(self):
        """Test an instance type with malformed user data."""

        inst_type = instance_types.get_default_instance_type()

        def fake_show(*args):
            img = copy.copy(self.fake_image)
            img['min_ram'] = 2
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        self.assertRaises(exception.InstanceUserDataMalformed,
            self.compute_api.create, self.context, inst_type, None,
                          user_data='banana')

    def test_create_with_base64_user_data(self):
        """Test an instance type with ok much user data."""

        inst_type = instance_types.get_default_instance_type()

        def fake_show(*args):
            img = copy.copy(self.fake_image)
            img['min_ram'] = 2
            return img
        self.stubs.Set(fake_image._FakeImageService, 'show', fake_show)

        # NOTE(mikal): a string of length 48510 encodes to 65532 characters of
        # base64
        (refs, resv_id) = self.compute_api.create(
            self.context, inst_type, None,
            user_data=base64.encodestring('1' * 48510))
        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_default_hostname_generator(self):
        fake_uuids = [str(utils.gen_uuid()) for x in xrange(4)]

        orig_populate = self.compute_api._populate_instance_for_create

        def _fake_populate(base_options, *args, **kwargs):
            base_options['uuid'] = fake_uuids.pop(0)
            return orig_populate(base_options, *args, **kwargs)

        self.stubs.Set(self.compute_api,
                '_populate_instance_for_create',
                _fake_populate)

        cases = [(None, 'server-%s' % fake_uuids[0]),
                 ('Hello, Server!', 'hello-server'),
                 ('<}\x1fh\x10e\x08l\x02l\x05o\x12!{>', 'hello'),
                 ('hello_server', 'hello-server')]
        for display_name, hostname in cases:
            (ref, resv_id) = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None,
                display_name=display_name)
            try:
                self.assertEqual(ref[0]['hostname'], hostname)
            finally:
                db.instance_destroy(self.context, ref[0]['uuid'])

    def test_destroy_instance_disassociates_security_groups(self):
        """Make sure destroying disassociates security groups"""
        group = self._create_group()

        (ref, resv_id) = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None,
                security_group=['testgroup'])
        try:
            db.instance_destroy(self.context, ref[0]['uuid'])
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
            db.instance_destroy(self.context, ref[0]['uuid'])

    def test_start(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.STOPPING})
        self.compute.stop_instance(self.context, instance=instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.start(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.STARTING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_stop(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        self.compute_api.stop(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.STOPPING)

        db.instance_destroy(self.context, instance['uuid'])

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

        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        check_state(instance['uuid'], power_state.RUNNING, vm_states.ACTIVE,
                    None)

        # NOTE(yamahata): emulate compute.manager._sync_power_state() that
        # the instance is shutdown by itself
        db.instance_update(self.context, instance['uuid'],
                           {'power_state': power_state.NOSTATE,
                            'vm_state': vm_states.STOPPED})
        check_state(instance['uuid'], power_state.NOSTATE, vm_states.STOPPED,
                    None)

        start_check_state(instance['uuid'], power_state.NOSTATE,
                          vm_states.STOPPED, task_states.STARTING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_delete(self):
        instance, instance_uuid = self._run_instance(params={
                'host': FLAGS.host})

        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_delete_in_resized(self):
        instance, instance_uuid = self._run_instance(params={
                'host': FLAGS.host})

        instance['vm_state'] = vm_states.RESIZED

        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_delete_with_down_host(self):
        self.network_api_called = False

        def dummy(*args, **kwargs):
            self.network_api_called = True

        self.stubs.Set(self.compute_api.network_api, 'deallocate_for_instance',
                       dummy)

        #use old time to disable machine
        old_time = datetime.datetime(2012, 4, 1)

        instance, instance_uuid = self._run_instance(params={
                'host': FLAGS.host})
        timeutils.set_time_override(old_time)
        self.compute_api.delete(self.context, instance)
        timeutils.clear_time_override()

        self.assertEqual(instance['task_state'], None)
        self.assertTrue(self.network_api_called)

        # fetch the instance state from db and verify deletion.
        deleted_context = context.RequestContext('fake', 'fake',
                                                 read_deleted='yes')
        instance = db.instance_get_by_uuid(deleted_context, instance_uuid)
        self.assertEqual(instance['vm_state'], vm_states.DELETED)
        self.assertEqual(instance['task_state'], None)
        self.assertTrue(instance['deleted'])

    def test_repeated_delete_quota(self):
        in_use = {'instances': 1}

        def fake_reserve(context, **deltas):
            return dict(deltas.iteritems())

        self.stubs.Set(QUOTAS, 'reserve', fake_reserve)

        def fake_commit(context, deltas):
            for k, v in deltas.iteritems():
                in_use[k] = in_use.get(k, 0) + v

        self.stubs.Set(QUOTAS, 'commit', fake_commit)

        instance, instance_uuid = self._run_instance(params={
                'host': FLAGS.host})

        self.compute_api.delete(self.context, instance)
        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

        self.assertEquals(in_use['instances'], 0)

        db.instance_destroy(self.context, instance['uuid'])

    def test_delete_fast_if_host_not_set(self):
        instance = self._create_fake_instance({'host': None})
        self.compute_api.delete(self.context, instance)
        self.assertRaises(exception.InstanceNotFound, db.instance_get_by_uuid,
                          self.context, instance['uuid'])

    def test_delete_handles_host_setting_race_condition(self):
        instance, instance_uuid = self._run_instance(params={
                'host': FLAGS.host})
        instance['host'] = None  # make it think host was never set
        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_delete_fail(self):
        instance, instance_uuid = self._run_instance(params={
                'host': FLAGS.host})

        instance = db.instance_update(self.context, instance_uuid,
                                      {'disable_terminate': True})
        self.compute_api.delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        db.instance_destroy(self.context, instance['uuid'])

    def test_delete_soft(self):
        instance, instance_uuid = self._run_instance()

        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_OFF)

        db.instance_destroy(self.context, instance['uuid'])

    def test_delete_soft_fail(self):
        instance, instance_uuid = self._run_instance()

        instance = db.instance_update(self.context, instance_uuid,
                                      {'disable_terminate': True})
        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], None)

        db.instance_destroy(self.context, instance['uuid'])

    def test_force_delete(self):
        """Ensure instance can be deleted after a soft delete"""
        instance = jsonutils.to_primitive(self._create_fake_instance(params={
                'host': FLAGS.host}))
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_OFF)

        # set the state that the instance gets when soft_delete finishes
        instance = db.instance_update(self.context, instance['uuid'],
                                      {'vm_state': vm_states.SOFT_DELETED,
                                       'task_state': None})

        self.compute_api.force_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.DELETING)

    def test_suspend(self):
        """Ensure instance can be suspended"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        self.assertEqual(instance['task_state'], None)

        self.compute_api.suspend(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.SUSPENDING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_resume(self):
        """Ensure instance can be resumed (if suspended)"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)
        db.instance_update(self.context, instance['uuid'],
                           {'vm_state': vm_states.SUSPENDED})
        instance = db.instance_get(self.context, instance['id'])

        self.assertEqual(instance['task_state'], None)

        self.compute_api.resume(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['task_state'], task_states.RESUMING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_pause(self):
        """Ensure instance can be paused"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        self.assertEqual(instance['task_state'], None)

        self.compute_api.pause(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.PAUSING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_unpause(self):
        """Ensure instance can be unpaused"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        self.assertEqual(instance['task_state'], None)

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.PAUSING})
        self.compute.pause_instance(self.context, instance=instance)
        # set the state that the instance gets when pause finishes
        instance = db.instance_update(self.context, instance['uuid'],
                                      {'vm_state': vm_states.PAUSED})

        self.compute_api.unpause(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.UNPAUSING)

        db.instance_destroy(self.context, instance['uuid'])

    def test_restore(self):
        """Ensure instance can be restored from a soft delete"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.compute_api.soft_delete(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_OFF)

        # set the state that the instance gets when soft_delete finishes
        instance = db.instance_update(self.context, instance['uuid'],
                                      {'vm_state': vm_states.SOFT_DELETED,
                                       'task_state': None})

        self.compute_api.restore(self.context, instance)

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.POWERING_ON)

        db.instance_destroy(self.context, instance['uuid'])

    def test_rebuild(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

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
        self.assertEqual(instance['task_state'], task_states.REBUILDING)
        sys_metadata = db.instance_system_metadata_get(self.context,
                instance_uuid)
        self.assertEqual(sys_metadata,
                {'image_kernel_id': 'fake_kernel_id',
                'image_ramdisk_id': 'fake_ramdisk_id',
                'image_something_else': 'meow',
                'preserved': 'preserve this!'})
        db.instance_destroy(self.context, instance['uuid'])

    def test_reboot_soft(self):
        """Ensure instance can be soft rebooted"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['task_state'], None)

        reboot_type = "SOFT"
        self.compute_api.reboot(self.context, inst_ref, reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, inst_ref['uuid'])
        self.assertEqual(inst_ref['task_state'], task_states.REBOOTING)

        db.instance_destroy(self.context, inst_ref['uuid'])

    def test_reboot_hard(self):
        """Ensure instance can be hard rebooted"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(inst_ref['task_state'], None)

        reboot_type = "HARD"
        self.compute_api.reboot(self.context, inst_ref, reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, inst_ref['uuid'])
        self.assertEqual(inst_ref['task_state'], task_states.REBOOTING_HARD)

        db.instance_destroy(self.context, inst_ref['uuid'])

    def test_hard_reboot_of_soft_rebooting_instance(self):
        """Ensure instance can be hard rebooted while soft rebooting"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBOOTING})

        reboot_type = "HARD"
        self.compute_api.reboot(self.context, inst_ref, reboot_type)

        inst_ref = db.instance_get_by_uuid(self.context, inst_ref['uuid'])
        self.assertEqual(inst_ref['task_state'], task_states.REBOOTING_HARD)

        db.instance_destroy(self.context, inst_ref['uuid'])

    def test_soft_reboot_of_rebooting_instance(self):
        """Ensure instance can't be soft rebooted while rebooting"""
        instance = jsonutils.to_primitive(self._create_fake_instance())
        self.compute.run_instance(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance['uuid'])

        db.instance_update(self.context, instance['uuid'],
                           {"task_state": task_states.REBOOTING})

        inst_ref = db.instance_get_by_uuid(self.context, inst_ref['uuid'])
        reboot_type = "SOFT"
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.reboot,
                          self.context,
                          inst_ref,
                          reboot_type)

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
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'], None)

        def fake_rpc_method(context, topic, msg, do_cast=True):
            self.assertFalse(do_cast)

        self.stubs.Set(rpc, 'call', fake_rpc_method)

        self.compute_api.set_admin_password(self.context, inst_ref)

        inst_ref = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(inst_ref['vm_state'], vm_states.ACTIVE)
        self.assertEqual(inst_ref['task_state'],
                         task_states.UPDATING_PASSWORD)

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(inst_ref))

    def test_rescue_unrescue(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        instance_uuid = instance['uuid']
        self.compute.run_instance(self.context, instance=instance)

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

        self.compute.terminate_instance(self.context,
                instance=jsonutils.to_primitive(instance))

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

        db.instance_destroy(self.context, instance['uuid'])

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

        db.instance_destroy(self.context, instance['uuid'])

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

        db.instance_destroy(self.context, instance['uuid'])

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

        db.instance_destroy(self.context, instance['uuid'])

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

        db.instance_destroy(self.context, instance['uuid'])

    def test_snapshot_image_service_fails(self):
        # Ensure task_state remains at None if image service fails.
        def fake_create(*args, **kwargs):
            raise test.TestingException()

        restore = getattr(fake_image._FakeImageService, 'create')
        self.stubs.Set(fake_image._FakeImageService, 'create', fake_create)

        instance = self._create_fake_instance()
        self.assertRaises(test.TestingException,
                          self.compute_api.snapshot,
                          self.context,
                          instance,
                          'no_image_snapshot')

        self.stubs.Set(fake_image._FakeImageService, 'create', restore)
        db_instance = db.instance_get_all(context.get_admin_context())[0]
        self.assertTrue(db_instance['task_state'] is None)

    def test_backup_image_service_fails(self):
        # Ensure task_state remains at None if image service fails.
        def fake_create(*args, **kwargs):
            raise test.TestingException()

        restore = getattr(fake_image._FakeImageService, 'create')
        self.stubs.Set(fake_image._FakeImageService, 'create', fake_create)

        instance = self._create_fake_instance()
        self.assertRaises(test.TestingException,
                          self.compute_api.backup,
                          self.context,
                          instance,
                          'no_image_backup',
                          'DAILY',
                          0)

        self.stubs.Set(fake_image._FakeImageService, 'create', restore)
        db_instance = db.instance_get_all(context.get_admin_context())[0]
        self.assertTrue(db_instance['task_state'] is None)

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

        db.instance_destroy(self.context, instance['uuid'])

    def test_backup_conflict(self):
        """Can't backup an instance which is already being backed up."""
        instance = self._create_fake_instance()
        instance_values = {'task_state': task_states.IMAGE_BACKUP}
        db.instance_update(self.context, instance['uuid'], instance_values)
        instance = self.compute_api.get(self.context, instance['uuid'])

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.backup,
                          self.context,
                          instance,
                          None,
                          None,
                          None)

        db.instance_destroy(self.context, instance['uuid'])

    def test_snapshot_conflict(self):
        """Can't snapshot an instance which is already being snapshotted."""
        instance = self._create_fake_instance()
        instance_values = {'task_state': task_states.IMAGE_SNAPSHOT}
        db.instance_update(self.context, instance['uuid'], instance_values)
        instance = self.compute_api.get(self.context, instance['uuid'])

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.snapshot,
                          self.context,
                          instance,
                          None)

        db.instance_destroy(self.context, instance['uuid'])

    def test_resize_confirm_through_api(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        context = self.context.elevated()
        self.compute.run_instance(self.context, instance=instance)
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute_api.resize(context, instance, '4')

        # create a fake migration record (manager does this)
        db.migration_create(context,
                {'instance_uuid': instance['uuid'],
                 'status': 'finished'})
        # set the state that the instance gets when resize finishes
        instance = db.instance_update(self.context, instance['uuid'],
                                      {'task_state': None,
                                       'vm_state': vm_states.RESIZED})

        self.compute_api.confirm_resize(context, instance)
        self.compute.terminate_instance(context,
            instance=jsonutils.to_primitive(instance))

    def test_resize_revert_through_api(self):
        instance = jsonutils.to_primitive(self._create_fake_instance())
        context = self.context.elevated()
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.compute.run_instance(self.context, instance=instance)

        self.compute_api.resize(context, instance, '4')

        # create a fake migration record (manager does this)
        db.migration_create(context,
                {'instance_uuid': instance['uuid'],
                 'status': 'finished'})
        # set the state that the instance gets when resize finishes
        instance = db.instance_update(self.context, instance['uuid'],
                                      {'task_state': None,
                                       'vm_state': vm_states.RESIZED})

        self.compute_api.revert_resize(context, instance)

        instance = db.instance_get_by_uuid(context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.RESIZED)
        self.assertEqual(instance['task_state'], task_states.RESIZE_REVERTING)

        self.compute.terminate_instance(context,
            instance=jsonutils.to_primitive(instance))

    def test_resize_invalid_flavor_fails(self):
        """Ensure invalid flavors raise"""
        instance = self._create_fake_instance()
        context = self.context.elevated()
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        instance = jsonutils.to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(exception.NotFound, self.compute_api.resize,
                context, instance, 200)

        self.compute.terminate_instance(context, instance=instance)

    def test_resize_same_flavor_fails(self):
        """Ensure invalid flavors raise"""
        context = self.context.elevated()
        instance = self._create_fake_instance()
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        instance = jsonutils.to_primitive(instance)

        self.compute.run_instance(self.context, instance=instance)

        self.assertRaises(exception.CannotResizeToSameFlavor,
                          self.compute_api.resize, context, instance, 1)

        self.compute.terminate_instance(context, instance=instance)

    def test_migrate(self):
        context = self.context.elevated()
        instance = self._create_fake_instance()
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        instance = jsonutils.to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance)
        # Migrate simply calls resize() without a flavor_id.
        self.compute_api.resize(context, instance, None)
        self.compute.terminate_instance(context, instance=instance)

    def test_resize_request_spec(self):
        def _fake_cast(context, topic, msg):
            request_spec = msg['args']['request_spec']
            filter_properties = msg['args']['filter_properties']
            instance_properties = request_spec['instance_properties']
            # resize with flavor_id = None will still send instance_type
            self.assertEqual(request_spec['instance_type'],
                             orig_instance_type)
            self.assertEqual(request_spec['instance_uuids'],
                             [instance['uuid']])
            self.assertEqual(instance_properties['uuid'], instance['uuid'])
            self.assertEqual(instance_properties['host'], 'host2')
            # Ensure the instance passed to us has been updated with
            # progress set to 0 and task_state set to RESIZE_PREP.
            self.assertEqual(instance_properties['task_state'],
                    task_states.RESIZE_PREP)
            self.assertEqual(instance_properties['progress'], 0)
            self.assertIn('host2', filter_properties['ignore_hosts'])

        self.stubs.Set(rpc, 'cast', _fake_cast)

        context = self.context.elevated()
        instance = self._create_fake_instance(dict(host='host2'))
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        instance = jsonutils.to_primitive(instance)
        orig_instance_type = instance['instance_type']
        self.compute.run_instance(self.context, instance=instance)
        # We need to set the host to something 'known'.  Unfortunately,
        # the compute manager is using a cached copy of FLAGS.host,
        # so we can't just self.flags(host='host2') before calling
        # run_instance above.  Also, set progress to 10 so we ensure
        # it is reset to 0 in compute_api.resize().  (verified in
        # _fake_cast above).
        instance = db.instance_update(self.context, instance['uuid'],
                dict(host='host2', progress=10))
        # different host
        self.flags(host='host3')
        try:
            self.compute_api.resize(context, instance, None)
        finally:
            self.compute.terminate_instance(context, instance=instance)

    def test_resize_request_spec_noavoid(self):
        def _fake_cast(context, topic, msg):
            request_spec = msg['args']['request_spec']
            filter_properties = msg['args']['filter_properties']
            instance_properties = request_spec['instance_properties']
            self.assertEqual(instance_properties['host'], 'host2')
            # Ensure the instance passed to us has been updated with
            # progress set to 0 and task_state set to RESIZE_PREP.
            self.assertEqual(instance_properties['task_state'],
                    task_states.RESIZE_PREP)
            self.assertEqual(instance_properties['progress'], 0)
            self.assertNotIn('host2', filter_properties['ignore_hosts'])

        self.stubs.Set(rpc, 'cast', _fake_cast)
        self.flags(allow_resize_to_same_host=True)

        context = self.context.elevated()
        instance = self._create_fake_instance(dict(host='host2'))
        instance = db.instance_get_by_uuid(context, instance['uuid'])
        instance = jsonutils.to_primitive(instance)
        self.compute.run_instance(self.context, instance=instance)
        # We need to set the host to something 'known'.  Unfortunately,
        # the compute manager is using a cached copy of FLAGS.host,
        # so we can't just self.flags(host='host2') before calling
        # run_instance above.  Also, set progress to 10 so we ensure
        # it is reset to 0 in compute_api.resize().  (verified in
        # _fake_cast above).
        instance = db.instance_update(self.context, instance['uuid'],
                dict(host='host2', progress=10))
        # different host
        try:
            self.compute_api.resize(context, instance, None)
        finally:
            self.compute.terminate_instance(context, instance=instance)

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
                search_opts={'name': '^woo.*'})
        self.assertEqual(len(instances), 2)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance1['uuid'] in instance_uuids)
        self.assertTrue(instance2['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': '^woot.*'})
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
                search_opts={'name': '^n.*'})
        self.assertEqual(len(instances), 1)
        instance_uuids = [instance['uuid'] for instance in instances]
        self.assertTrue(instance3['uuid'] in instance_uuids)

        instances = self.compute_api.get_all(c,
                search_opts={'name': 'noth.*'})
        self.assertEqual(len(instances), 0)

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

    def test_get_all_by_multiple_options_at_once(self):
        """Test searching by multiple options at once"""
        c = context.get_admin_context()
        network_manager = fake_network.FakeNetworkManager()
        self.stubs.Set(self.compute_api.network_api,
                       'get_instance_uuids_by_ip_filter',
                       network_manager.get_instance_uuids_by_ip_filter)

        instance1 = self._create_fake_instance({
                'display_name': 'woot',
                'id': 0,
                'uuid': '00000000-0000-0000-0000-000000000010'})
        instance2 = self._create_fake_instance({
                'display_name': 'woo',
                'id': 20,
                'uuid': '00000000-0000-0000-0000-000000000020'})
        instance3 = self._create_fake_instance({
                'display_name': 'not-woot',
                'id': 30,
                'uuid': '00000000-0000-0000-0000-000000000030'})

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

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

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

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

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

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

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

        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])

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

        db.instance_destroy(c, instance0['uuid'])
        db.instance_destroy(c, instance1['uuid'])
        db.instance_destroy(c, instance2['uuid'])
        db.instance_destroy(c, instance3['uuid'])
        db.instance_destroy(c, instance4['uuid'])

    def test_instance_metadata(self):
        meta_changes = [None]
        self.flags(notify_on_any_change=True)

        def fake_change_instance_metadata(inst, ctxt, diff, instance=None,
                                          instance_uuid=None):
            meta_changes[0] = diff
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'change_instance_metadata',
                       fake_change_instance_metadata)

        _context = context.get_admin_context()
        instance = self._create_fake_instance({'metadata': {'key1': 'value1'}})
        instance = dict(instance)

        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key1': 'value1'})

        self.compute_api.update_instance_metadata(_context, instance,
                                                  {'key2': 'value2'})
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key1': 'value1', 'key2': 'value2'})
        self.assertEqual(meta_changes, [{'key2': ['+', 'value2']}])

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        payload = msg['payload']
        self.assertTrue('metadata' in payload)
        self.assertEquals(payload['metadata'], metadata)

        new_metadata = {'key2': 'bah', 'key3': 'value3'}
        self.compute_api.update_instance_metadata(_context, instance,
                                                  new_metadata, delete=True)
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, new_metadata)
        self.assertEqual(meta_changes, [{
                    'key1': ['-'],
                    'key2': ['+', 'bah'],
                    'key3': ['+', 'value3'],
                    }])

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        msg = test_notifier.NOTIFICATIONS[1]
        payload = msg['payload']
        self.assertTrue('metadata' in payload)
        self.assertEquals(payload['metadata'], metadata)

        self.compute_api.delete_instance_metadata(_context, instance, 'key2')
        metadata = self.compute_api.get_instance_metadata(_context, instance)
        self.assertEqual(metadata, {'key3': 'value3'})
        self.assertEqual(meta_changes, [{'key2': ['-']}])

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 3)
        msg = test_notifier.NOTIFICATIONS[2]
        payload = msg['payload']
        self.assertTrue('metadata' in payload)
        self.assertEquals(payload['metadata'], {})

        db.instance_destroy(_context, instance['uuid'])

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

        db.instance_destroy(_context, instance['uuid'])

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
        self.compute.terminate_instance(self.context, instance)

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
            db.instance_destroy(self.context, refs[0]['uuid'])

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

        db.instance_destroy(self.context, refs[0]['uuid'])

    def test_instance_architecture(self):
        """Test the instance architecture"""
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['architecture'], 'x86_64')
        db.instance_destroy(self.context, i_ref['uuid'])

    def test_instance_unknown_architecture(self):
        """Test if the architecture is unknown."""
        instance = jsonutils.to_primitive(self._create_fake_instance(
                        params={'architecture': ''}))
        try:
            self.compute.run_instance(self.context, instance=instance)
            instances = db.instance_get_all(context.get_admin_context())
            instance = instances[0]
            self.assertNotEqual(instance['architecture'], 'Unknown')
        finally:
            db.instance_destroy(self.context, instance['uuid'])

    def test_instance_name_template(self):
        """Test the instance_name template"""
        self.flags(instance_name_template='instance-%d')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], 'instance-%d' % i_ref['id'])
        db.instance_destroy(self.context, i_ref['uuid'])

        self.flags(instance_name_template='instance-%(uuid)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], 'instance-%s' % i_ref['uuid'])
        db.instance_destroy(self.context, i_ref['uuid'])

        self.flags(instance_name_template='%(id)d-%(uuid)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], '%d-%s' %
                (i_ref['id'], i_ref['uuid']))
        db.instance_destroy(self.context, i_ref['uuid'])

        # not allowed.. default is uuid
        self.flags(instance_name_template='%(name)s')
        i_ref = self._create_fake_instance()
        self.assertEqual(i_ref['name'], i_ref['uuid'])
        db.instance_destroy(self.context, i_ref['uuid'])

    def test_add_remove_fixed_ip(self):
        instance = self._create_fake_instance(params={'host': FLAGS.host})
        self.compute_api.add_fixed_ip(self.context, instance, '1')
        self.compute_api.remove_fixed_ip(self.context, instance, '192.168.1.1')
        self.compute_api.delete(self.context, instance)

    def test_attach_volume_invalid(self):
        self.assertRaises(exception.InvalidDevicePath,
                self.compute_api.attach_volume,
                self.context,
                {'locked': False},
                None,
                '/invalid')

    def test_vnc_console(self):
        """Make sure we can a vnc console for an instance."""

        fake_instance = {'uuid': 'fake_uuid',
                         'host': 'fake_compute_host'}
        fake_console_type = "novnc"
        fake_connect_info = {'token': 'fake_token',
                             'console_type': fake_console_type,
                             'host': 'fake_console_host',
                             'port': 'fake_console_port',
                             'internal_access_path': 'fake_access_path',
                             'instance_uuid': fake_instance["uuid"]}

        fake_connect_info2 = copy.deepcopy(fake_connect_info)
        fake_connect_info2['access_url'] = 'fake_console_url'

        self.mox.StubOutWithMock(rpc, 'call')

        rpc_msg1 = {'method': 'get_vnc_console',
                    'args': {'instance': fake_instance,
                             'console_type': fake_console_type},
                   'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION}
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

    def test_get_vnc_console_no_host(self):
        instance = self._create_fake_instance(params={'host': ''})

        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.get_vnc_console,
                          self.context, instance, 'novnc')

        db.instance_destroy(self.context, instance['uuid'])

    def test_validate_console_port(self):
        self.flags(vnc_enabled=True)
        instance = jsonutils.to_primitive(self._create_fake_instance())

        def fake_driver_get_console(*args, **kwargs):
            return {'host': "fake_host", 'port': "5900",
                    'internal_access_path': None}
        self.stubs.Set(self.compute.driver, "get_vnc_console",
                       fake_driver_get_console)

        self.assertTrue(self.compute.validate_console_port(self.context,
                                                            instance,
                                                            "5900",
                                                            "novnc"))

    def test_validate_console_port_wrong_port(self):
        self.flags(vnc_enabled=True)
        instance = jsonutils.to_primitive(self._create_fake_instance())

        def fake_driver_get_console(*args, **kwargs):
            return {'host': "fake_host", 'port': "5900",
                    'internal_access_path': None}
        self.stubs.Set(self.compute.driver, "get_vnc_console",
                       fake_driver_get_console)

        self.assertFalse(self.compute.validate_console_port(self.context,
                                                            instance,
                                                            "wrongport",
                                                            "novnc"))

    def test_console_output(self):
        fake_instance = {'uuid': 'fake_uuid',
                         'host': 'fake_compute_host'}
        fake_tail_length = 699
        fake_console_output = 'fake console output'

        self.mox.StubOutWithMock(rpc, 'call')

        rpc_msg = {'method': 'get_console_output',
                   'args': {'instance': fake_instance,
                            'tail_length': fake_tail_length},
                   'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION}
        rpc.call(self.context, 'compute.%s' % fake_instance['host'],
                rpc_msg, None).AndReturn(fake_console_output)

        self.mox.ReplayAll()

        output = self.compute_api.get_console_output(self.context,
                fake_instance, tail_length=fake_tail_length)
        self.assertEqual(output, fake_console_output)

    def test_attach_volume(self):
        """Ensure instance can be soft rebooted"""

        called = {}

        def fake_check_attach(*args, **kwargs):
            called['fake_check_attach'] = True

        def fake_reserve_volume(*args, **kwargs):
            called['fake_reserve_volume'] = True

        def fake_volume_get(self, context, volume_id):
            called['fake_volume_get'] = True
            return {'id': volume_id}

        def fake_rpc_attach_volume(self, context, **kwargs):
            called['fake_rpc_attach_volume'] = True

        self.stubs.Set(nova.volume.api.API, 'get', fake_volume_get)
        self.stubs.Set(nova.volume.api.API, 'check_attach', fake_check_attach)
        self.stubs.Set(nova.volume.api.API, 'reserve_volume',
                       fake_reserve_volume)
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'attach_volume',
                       fake_rpc_attach_volume)

        instance = self._create_fake_instance()
        self.compute_api.attach_volume(self.context, instance, 1, '/dev/vdb')
        self.assertTrue(called.get('fake_check_attach'))
        self.assertTrue(called.get('fake_reserve_volume'))
        self.assertTrue(called.get('fake_reserve_volume'))
        self.assertTrue(called.get('fake_rpc_attach_volume'))

    def test_attach_volume_no_device(self):

        called = {}

        def fake_check_attach(*args, **kwargs):
            called['fake_check_attach'] = True

        def fake_reserve_volume(*args, **kwargs):
            called['fake_reserve_volume'] = True

        def fake_volume_get(self, context, volume_id):
            called['fake_volume_get'] = True
            return {'id': volume_id}

        def fake_rpc_attach_volume(self, context, **kwargs):
            called['fake_rpc_attach_volume'] = True

        self.stubs.Set(nova.volume.api.API, 'get', fake_volume_get)
        self.stubs.Set(nova.volume.api.API, 'check_attach', fake_check_attach)
        self.stubs.Set(nova.volume.api.API, 'reserve_volume',
                       fake_reserve_volume)
        self.stubs.Set(compute_rpcapi.ComputeAPI, 'attach_volume',
                       fake_rpc_attach_volume)

        instance = self._create_fake_instance()
        self.compute_api.attach_volume(self.context, instance, 1, device=None)
        self.assertTrue(called.get('fake_check_attach'))
        self.assertTrue(called.get('fake_reserve_volume'))
        self.assertTrue(called.get('fake_reserve_volume'))
        self.assertTrue(called.get('fake_rpc_attach_volume'))

    def test_inject_network_info(self):
        instance = self._create_fake_instance(params={'host': FLAGS.host})
        self.compute.run_instance(self.context,
                instance=jsonutils.to_primitive(instance))
        instance = self.compute_api.get(self.context, instance['uuid'])
        self.compute_api.inject_network_info(self.context, instance)
        self.compute_api.delete(self.context, instance)

    def test_reset_network(self):
        instance = self._create_fake_instance()
        self.compute.run_instance(self.context,
                instance=jsonutils.to_primitive(instance))
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

        self.compute.run_instance(self.context,
                instance=jsonutils.to_primitive(instance))
        instance = self.compute_api.get(self.context, instance['uuid'])
        security_group_name = self._create_group()['name']

        self.security_group_api.add_to_instance(self.context,
                                                instance,
                                                security_group_name)
        self.security_group_api.remove_from_instance(self.context,
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
        db.instance_destroy(self.context, instance['uuid'])

    def test_secgroup_refresh(self):
        instance = self._create_fake_instance()

        def rule_get(*args, **kwargs):
            mock_rule = FakeModel({'parent_group_id': 1})
            return [mock_rule]

        def group_get(*args, **kwargs):
            mock_group = FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(
                   self.compute_api.db,
                   'security_group_rule_get_by_security_group_grantee',
                   rule_get)
        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, FLAGS.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                    compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_members_refresh(self.context, [1])

    def test_secgroup_refresh_once(self):
        instance = self._create_fake_instance()

        def rule_get(*args, **kwargs):
            mock_rule = FakeModel({'parent_group_id': 1})
            return [mock_rule]

        def group_get(*args, **kwargs):
            mock_group = FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(
                   self.compute_api.db,
                   'security_group_rule_get_by_security_group_grantee',
                   rule_get)
        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, FLAGS.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                   compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_members_refresh(self.context, [1, 2])

    def test_secgroup_refresh_none(self):
        def rule_get(*args, **kwargs):
            mock_rule = FakeModel({'parent_group_id': 1})
            return [mock_rule]

        def group_get(*args, **kwargs):
            mock_group = FakeModel({'instances': []})
            return mock_group

        self.stubs.Set(
                   self.compute_api.db,
                   'security_group_rule_get_by_security_group_grantee',
                   rule_get)
        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        self.mox.ReplayAll()

        self.security_group_api.trigger_members_refresh(self.context, [1])

    def test_secrule_refresh(self):
        instance = self._create_fake_instance()

        def group_get(*args, **kwargs):
            mock_group = FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, FLAGS.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                   compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_rules_refresh(self.context, [1])

    def test_secrule_refresh_once(self):
        instance = self._create_fake_instance()

        def group_get(*args, **kwargs):
            mock_group = FakeModel({'instances': [instance]})
            return mock_group

        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        topic = rpc.queue_get_for(self.context, FLAGS.compute_topic,
                                  instance['host'])
        rpc.cast(self.context, topic,
                {"method": "refresh_instance_security_rules",
                 "args": {'instance': jsonutils.to_primitive(instance)},
                 "version":
                   compute_rpcapi.SecurityGroupAPI.BASE_RPC_API_VERSION})
        self.mox.ReplayAll()

        self.security_group_api.trigger_rules_refresh(self.context, [1, 2])

    def test_secrule_refresh_none(self):
        def group_get(*args, **kwargs):
            mock_group = FakeModel({'instances': []})
            return mock_group

        self.stubs.Set(self.compute_api.db, 'security_group_get', group_get)

        self.mox.StubOutWithMock(rpc, 'cast')
        self.mox.ReplayAll()

        self.security_group_api.trigger_rules_refresh(self.context, [1, 2])

    def test_live_migrate(self):
        instance, instance_uuid = self._run_instance()

        self.compute_api.live_migrate(self.context, instance,
                                      block_migration=True,
                                      disk_over_commit=True,
                                      host='fake_dest_host')

        instance = db.instance_get_by_uuid(self.context, instance_uuid)
        self.assertEqual(instance['task_state'], task_states.MIGRATING)

        db.instance_destroy(self.context, instance['uuid'])


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


class ComputeAPIAggrTestCase(BaseTestCase):
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
        """Ensure metadata can be updated"""
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
        self.assertRaises(exception.AggregateNotFound,
                          self.api.delete_aggregate, self.context, aggr['id'])

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
        self.assertEqual(len(aggr['hosts']), 1)

    def test_add_host_to_aggregate_multiple(self):
        """Ensure we can add multiple hosts to an aggregate."""
        values = _create_service_entries(self.context)
        fake_zone = values.keys()[0]
        aggr = self.api.create_aggregate(self.context,
                                         'fake_aggregate', fake_zone)
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        self.assertEqual(len(aggr['hosts']), len(values[fake_zone]))

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
        for host in values[fake_zone]:
            aggr = self.api.add_host_to_aggregate(self.context,
                                                  aggr['id'], host)
        expected = self.api.remove_host_from_aggregate(self.context,
                                                       aggr['id'],
                                                       values[fake_zone][0])
        self.assertEqual(len(aggr['hosts']) - 1, len(expected['hosts']))

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
                  'availability_zone': 'test_zone'}
        self.aggr = db.aggregate_create(self.context, values)

    def test_add_aggregate_host(self):
        def fake_driver_add_to_aggregate(context, aggregate, host, **_ignore):
            fake_driver_add_to_aggregate.called = True
            return {"foo": "bar"}
        self.stubs.Set(self.compute.driver, "add_to_aggregate",
                       fake_driver_add_to_aggregate)

        self.compute.add_aggregate_host(self.context, self.aggr.id, "host")
        self.assertTrue(fake_driver_add_to_aggregate.called)

    def test_remove_aggregate_host(self):
        def fake_driver_remove_from_aggregate(context, aggregate, host,
                                              **_ignore):
            fake_driver_remove_from_aggregate.called = True
            self.assertEqual("host", host, "host")
            return {"foo": "bar"}
        self.stubs.Set(self.compute.driver, "remove_from_aggregate",
                       fake_driver_remove_from_aggregate)

        self.compute.remove_aggregate_host(self.context, self.aggr.id, "host")
        self.assertTrue(fake_driver_remove_from_aggregate.called)

    def test_add_aggregate_host_passes_slave_info_to_driver(self):
        def driver_add_to_aggregate(context, aggregate, host, **kwargs):
            self.assertEquals(self.context, context)
            self.assertEquals(aggregate.id, self.aggr.id)
            self.assertEquals(host, "the_host")
            self.assertEquals("SLAVE_INFO", kwargs.get("slave_info"))

        self.stubs.Set(self.compute.driver, "add_to_aggregate",
                       driver_add_to_aggregate)

        self.compute.add_aggregate_host(self.context, self.aggr.id,
            "the_host", slave_info="SLAVE_INFO")

    def test_remove_from_aggregate_passes_slave_info_to_driver(self):
        def driver_remove_from_aggregate(context, aggregate, host, **kwargs):
            self.assertEquals(self.context, context)
            self.assertEquals(aggregate.id, self.aggr.id)
            self.assertEquals(host, "the_host")
            self.assertEquals("SLAVE_INFO", kwargs.get("slave_info"))

        self.stubs.Set(self.compute.driver, "remove_from_aggregate",
                       driver_remove_from_aggregate)

        self.compute.remove_aggregate_host(self.context,
            self.aggr.id, "the_host", slave_info="SLAVE_INFO")


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
        common_policy.set_brain(common_policy.HttpBrain(rules))

    def test_actions_are_prefixed(self):
        self.mox.StubOutWithMock(nova.policy, 'enforce')
        nova.policy.enforce(self.context, 'compute:reboot', {})
        self.mox.ReplayAll()
        nova.compute.api.check_policy(self.context, 'reboot', {})

    def test_wrapped_method(self):
        instance = self._create_fake_instance(params={'host': None})

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
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})

    def test_get_host_uptime(self):
        ctxt = context.RequestContext('fake', 'fake')
        call_info = {}
        self._rpc_call_stub(call_info)

        self.host_api.get_host_uptime(ctxt, 'fake_host')
        self.assertEqual(call_info['context'], ctxt)
        self.assertEqual(call_info['topic'], 'compute.fake_host')
        self.assertEqual(call_info['msg'],
                {'method': 'get_host_uptime',
                 'args': {},
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})

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
                 'version':
                 compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})

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
                 'version': compute_rpcapi.ComputeAPI.BASE_RPC_API_VERSION})


class KeypairAPITestCase(BaseTestCase):
    def setUp(self):
        super(KeypairAPITestCase, self).setUp()
        self.keypair_api = compute_api.KeypairAPI()
        self.ctxt = context.RequestContext('fake', 'fake')
        self._keypair_db_call_stubs()
        self.existing_key_name = 'fake existing key name'
        self.pub_key = ('ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDLnVkqJu9WVf'
                        '/5StU3JCrBR2r1s1j8K1tux+5XeSvdqaM8lMFNorzbY5iyoBbR'
                        'S56gy1jmm43QsMPJsrpfUZKcJpRENSe3OxIIwWXRoiapZe78u/'
                        'a9xKwj0avFYMcws9Rk9iAB7W4K1nEJbyCPl5lRBoyqeHBqrnnu'
                        'XWEgGxJCK0Ah6wcOzwlEiVjdf4kxzXrwPHyi7Ea1qvnNXTziF8'
                        'yYmUlH4C8UXfpTQckwSwpDyxZUc63P8q+vPbs3Q2kw+/7vvkCK'
                        'HJAXVI+oCiyMMfffoTq16M1xfV58JstgtTqAXG+ZFpicGajREU'
                        'E/E3hO5MGgcHmyzIrWHKpe1n3oEGuz')
        self.fingerprint = '4e:48:c6:a0:4a:f9:dd:b5:4c:85:54:5a:af:43:47:5a'

    def _keypair_db_call_stubs(self):

        def db_key_pair_get_all_by_user(self, user_id):
            return []

        def db_key_pair_create(self, keypair):
            pass

        def db_key_pair_destroy(context, user_id, name):
            pass

        def db_key_pair_get(context, user_id, name):
            if name == self.existing_key_name:
                return {'name': self.existing_key_name,
                        'public_key': self.pub_key,
                        'fingerprint': self.fingerprint}
            else:
                raise exception.KeypairNotFound(user_id=user_id, name=name)

        self.stubs.Set(db, "key_pair_get_all_by_user",
                       db_key_pair_get_all_by_user)
        self.stubs.Set(db, "key_pair_create",
                       db_key_pair_create)
        self.stubs.Set(db, "key_pair_destroy",
                       db_key_pair_destroy)
        self.stubs.Set(db, "key_pair_get",
                       db_key_pair_get)

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
        self.assertRaises(exception.KeyPairExists,
                          self.keypair_api.create_key_pair,
                          self.ctxt, self.ctxt.user_id,
                          self.existing_key_name)

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

    def test_get_keypair(self):
        keypair = self.keypair_api.get_key_pair(self.ctxt,
                                                self.ctxt.user_id,
                                                self.existing_key_name)
        self.assertEqual(self.existing_key_name, keypair['name'])


class DisabledInstanceTypesTestCase(BaseTestCase):
    """
    Some instance-types are marked 'disabled' which means that they will not
    show up in customer-facing listings. We do, however, want those
    instance-types to be availble for emergency migrations and for rebuilding
    of existing instances.

    One legitimate use of the 'disabled' field would be when phasing out a
    particular instance-type. We still want customers to be able to use an
    instance that of the old type, and we want Ops to be able perform
    migrations against it, but we *don't* want customers building new slices
    with ths phased-out instance-type.
    """
    def setUp(self):
        super(DisabledInstanceTypesTestCase, self).setUp()
        self.compute_api = compute.API()
        self.inst_type = instance_types.get_default_instance_type()

    def test_can_build_instance_from_visible_instance_type(self):
        self.inst_type['disabled'] = False

        self.assertNotRaises(exception.InstanceTypeNotFound,
            self.compute_api.create, self.context, self.inst_type, None,
            exc_msg="Visible instance-types can be built from")

    def test_cannot_build_instance_from_disabled_instance_type(self):
        self.inst_type['disabled'] = True
        self.assertRaises(exception.InstanceTypeNotFound,
            self.compute_api.create, self.context, self.inst_type, None)

    def test_can_rebuild_instance_from_visible_instance_type(self):
        instance = self._create_fake_instance()
        image_href = None
        admin_password = 'blah'

        instance['instance_type']['disabled'] = True

        # Assert no errors were raised
        self.assertNotRaises(None,
            self.compute_api.rebuild, self.context, instance, image_href,
            admin_password,
            exc_msg="Visible instance-types can be rebuilt from")

    def test_can_rebuild_instance_from_disabled_instance_type(self):
        """
        A rebuild or a restore should only change the 'image',
        not the 'instance_type'. Therefore, should be allowed even
        when the slice is on disabled type already.
        """
        instance = self._create_fake_instance()
        image_href = None
        admin_password = 'blah'

        instance['instance_type']['disabled'] = True

        # Assert no errors were raised
        self.assertNotRaises(None,
            self.compute_api.rebuild, self.context, instance, image_href,
            admin_password,
            exc_msg="Disabled instance-types can be rebuilt from")

    def test_can_resize_to_visible_instance_type(self):
        instance = self._create_fake_instance()
        orig_get_instance_type_by_flavor_id =\
                instance_types.get_instance_type_by_flavor_id

        def fake_get_instance_type_by_flavor_id(flavor_id):
            instance_type = orig_get_instance_type_by_flavor_id(flavor_id)
            instance_type['disabled'] = False
            return instance_type

        self.stubs.Set(instance_types, 'get_instance_type_by_flavor_id',
                       fake_get_instance_type_by_flavor_id)

        # FIXME(sirp): for legacy this raises FlavorNotFound instead of
        # InstanceTypeNot; we should eventually make it raise
        # InstanceTypeNotFound for consistency.
        self.assertNotRaises(exception.FlavorNotFound,
            self.compute_api.resize, self.context, instance, '4',
            exc_msg="Visible flavors can be resized to")

    def test_cannot_resize_to_disabled_instance_type(self):
        instance = self._create_fake_instance()
        orig_get_instance_type_by_flavor_id = \
                instance_types.get_instance_type_by_flavor_id

        def fake_get_instance_type_by_flavor_id(flavor_id):
            instance_type = orig_get_instance_type_by_flavor_id(flavor_id)
            instance_type['disabled'] = True
            return instance_type

        self.stubs.Set(instance_types, 'get_instance_type_by_flavor_id',
                       fake_get_instance_type_by_flavor_id)

        # FIXME(sirp): for legacy this raises FlavorNotFound instead of
        # InstanceTypeNot; we should eventually make it raise
        # InstanceTypeNotFound for consistency.
        self.assertRaises(exception.FlavorNotFound,
            self.compute_api.resize, self.context, instance, '4')

    def test_can_migrate_to_visible_instance_type(self):
        instance = self._create_fake_instance()
        instance['instance_type']['disabled'] = False

        # FIXME(sirp): for legacy this raises FlavorNotFound instead of
        # InstanceTypeNot; we should eventually make it raise
        # InstanceTypeNotFound for consistency.
        self.assertNotRaises(exception.FlavorNotFound,
            self.compute_api.resize, self.context, instance, None,
            exc_msg="Visible flavors can be migrated to")

    def test_can_migrate_to_disabled_instance_type(self):
        """
        We don't want to require a customers instance-type to change when ops
        is migrating a failed server.
        """
        instance = self._create_fake_instance()
        instance['instance_type']['disabled'] = True

        # FIXME(sirp): for legacy this raises FlavorNotFound instead of
        # InstanceTypeNot; we should eventually make it raise
        # InstanceTypeNotFound for consistency.
        self.assertNotRaises(exception.FlavorNotFound,
            self.compute_api.resize, self.context, instance, None,
            exc_msg="Disabled flavors can be migrated to")


class ComputeReschedulingTestCase(BaseTestCase):
    """Tests related to re-scheduling build requests"""

    def setUp(self):
        super(ComputeReschedulingTestCase, self).setUp()

        self._reschedule = self._reschedule_partial()

        def fake_update(*args, **kwargs):
            self.updated_task_state = kwargs.get('task_state')
        self.stubs.Set(self.compute, '_instance_update', fake_update)

    def _reschedule_partial(self):
        uuid = "12-34-56-78-90"

        requested_networks = None
        admin_password = None
        injected_files = None
        is_first_time = False

        return functools.partial(self.compute._reschedule, self.context, uuid,
                requested_networks, admin_password, injected_files,
                is_first_time, request_spec=None, filter_properties={})

    def test_reschedule_no_filter_properties(self):
        """no filter_properties will disable re-scheduling"""
        self.assertFalse(self._reschedule())

    def test_reschedule_no_retry_info(self):
        """no retry info will also disable re-scheduling"""
        filter_properties = {}
        self.assertFalse(self._reschedule(filter_properties=filter_properties))

    def test_reschedule_no_request_spec(self):
        """no request spec will also disable re-scheduling"""
        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)
        self.assertFalse(self._reschedule(filter_properties=filter_properties))

    def test_reschedule_success(self):
        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)
        request_spec = {'instance_uuids': ['foo', 'bar']}
        self.assertTrue(self._reschedule(filter_properties=filter_properties,
            request_spec=request_spec))
        self.assertEqual(1, len(request_spec['instance_uuids']))
        self.assertEqual(self.updated_task_state, task_states.SCHEDULING)


class ThatsNoOrdinaryRabbitException(Exception):
    pass


class ComputeReschedulingExceptionTestCase(BaseTestCase):
    """Tests for re-scheduling exception handling logic"""

    def setUp(self):
        super(ComputeReschedulingExceptionTestCase, self).setUp()

        # cause _spawn to raise an exception to test the exception logic:
        def exploding_spawn(*args, **kwargs):
            raise ThatsNoOrdinaryRabbitException()
        self.stubs.Set(self.compute, '_spawn',
                exploding_spawn)

        self.fake_instance = jsonutils.to_primitive(
                self._create_fake_instance())
        self.instance_uuid = self.fake_instance['uuid']

    def test_exception_with_rescheduling_disabled(self):
        """Spawn fails and re-scheduling is disabled."""
        # this won't be re-scheduled:
        self.assertRaises(ThatsNoOrdinaryRabbitException,
                self.compute._run_instance, self.context,
                None, {}, None, None, None, None, self.fake_instance)

    def test_exception_with_rescheduling_enabled(self):
        """Spawn fails and re-scheduling is enabled.  Original exception
        should *not* be re-raised.
        """
        # provide the expected status so that this one will be re-scheduled:
        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)
        request_spec = dict(num_attempts=1)
        self.assertNotRaises(ThatsNoOrdinaryRabbitException,
                self.compute._run_instance, self.context,
                filter_properties=filter_properties, request_spec=request_spec,
                instance=self.fake_instance)

    def test_exception_context_cleared(self):
        """Test with no rescheduling and an additional exception occurs
        clearing the original build error's exception context.
        """
        # clears the original exception context:
        class FleshWoundException(Exception):
            pass

        def reschedule_explode(*args, **kwargs):
            raise FleshWoundException()
        self.stubs.Set(self.compute, '_reschedule', reschedule_explode)

        # the original exception should now be raised:
        self.assertRaises(ThatsNoOrdinaryRabbitException,
                self.compute._run_instance, self.context,
                None, {}, None, None, None, None, self.fake_instance)
