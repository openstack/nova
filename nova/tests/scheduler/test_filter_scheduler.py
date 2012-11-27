# Copyright 2011 OpenStack LLC.
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
Tests For Filter Scheduler.
"""

import mox

from nova.compute import instance_types
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.scheduler import driver
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import weights
from nova.tests.scheduler import fakes
from nova.tests.scheduler import test_scheduler


def fake_get_filtered_hosts(hosts, filter_properties):
    return list(hosts)


class FilterSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Filter Scheduler."""

    driver_cls = filter_scheduler.FilterScheduler

    def test_run_instance_no_hosts(self):

        def _fake_empty_call_zone_method(*args, **kwargs):
            return []

        sched = fakes.FakeFilterScheduler()

        uuid = 'fake-uuid1'
        fake_context = context.RequestContext('user', 'project')
        instance_properties = {'project_id': 1, 'os_type': 'Linux'}
        request_spec = {'instance_type': {'memory_mb': 1, 'root_gb': 1,
                                          'ephemeral_gb': 0},
                        'instance_properties': instance_properties,
                        'instance_uuids': [uuid]}

        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        compute_utils.add_instance_fault_from_exc(fake_context,
                uuid, mox.IsA(exception.NoValidHost), mox.IgnoreArg())
        db.instance_update_and_get_original(fake_context, uuid,
                {'vm_state': vm_states.ERROR,
                 'task_state': None}).AndReturn(({}, {}))
        self.mox.ReplayAll()
        sched.schedule_run_instance(
                fake_context, request_spec, None, None, None, None, {})

    def test_run_instance_non_admin(self):
        self.was_admin = False

        def fake_get(context, *args, **kwargs):
            # make sure this is called with admin context, even though
            # we're using user context below
            self.was_admin = context.is_admin
            return {}

        sched = fakes.FakeFilterScheduler()
        self.stubs.Set(sched.host_manager, 'get_all_host_states', fake_get)

        fake_context = context.RequestContext('user', 'project')

        uuid = 'fake-uuid1'
        instance_properties = {'project_id': 1, 'os_type': 'Linux'}
        request_spec = {'instance_type': {'memory_mb': 1, 'local_gb': 1},
                        'instance_properties': instance_properties,
                        'instance_uuids': [uuid]}
        self.mox.StubOutWithMock(compute_utils, 'add_instance_fault_from_exc')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        compute_utils.add_instance_fault_from_exc(fake_context,
                uuid, mox.IsA(exception.NoValidHost), mox.IgnoreArg())
        db.instance_update_and_get_original(fake_context, uuid,
                {'vm_state': vm_states.ERROR,
                 'task_state': None}).AndReturn(({}, {}))
        self.mox.ReplayAll()
        sched.schedule_run_instance(
                fake_context, request_spec, None, None, None, None, {})
        self.assertTrue(self.was_admin)

    def test_scheduler_includes_launch_index(self):
        fake_context = context.RequestContext('user', 'project')
        instance_opts = {'fake_opt1': 'meow'}
        request_spec = {'instance_uuids': ['fake-uuid1', 'fake-uuid2'],
                        'instance_properties': instance_opts}
        instance1 = {'uuid': 'fake-uuid1'}
        instance2 = {'uuid': 'fake-uuid2'}

        def _has_launch_index(expected_index):
            """Return a function that verifies the expected index."""
            def _check_launch_index(value):
                if 'instance_properties' in value:
                    if 'launch_index' in value['instance_properties']:
                        index = value['instance_properties']['launch_index']
                        if index == expected_index:
                            return True
                return False
            return _check_launch_index

        self.mox.StubOutWithMock(self.driver, '_schedule')
        self.mox.StubOutWithMock(self.driver, '_provision_resource')

        self.driver._schedule(fake_context, request_spec, {},
                ['fake-uuid1', 'fake-uuid2']).AndReturn(['host1', 'host2'])
        # instance 1
        self.driver._provision_resource(
            fake_context, 'host1',
            mox.Func(_has_launch_index(0)), {},
            None, None, None, None,
            instance_uuid='fake-uuid1').AndReturn(instance1)
        # instance 2
        self.driver._provision_resource(
            fake_context, 'host2',
            mox.Func(_has_launch_index(1)), {},
            None, None, None, None,
            instance_uuid='fake-uuid2').AndReturn(instance2)
        self.mox.ReplayAll()

        self.driver.schedule_run_instance(fake_context, request_spec,
                None, None, None, None, {})

    def test_schedule_happy_day(self):
        """Make sure there's nothing glaringly wrong with _schedule()
        by doing a happy day pass through."""

        self.next_weight = 1.0

        def _fake_weigh_objects(_self, functions, hosts, options):
            self.next_weight += 2.0
            host_state = hosts[0]
            return [weights.WeighedHost(host_state, self.next_weight)]

        sched = fakes.FakeFilterScheduler()
        fake_context = context.RequestContext('user', 'project',
                is_admin=True)

        self.stubs.Set(sched.host_manager, 'get_filtered_hosts',
                fake_get_filtered_hosts)
        self.stubs.Set(weights.HostWeightHandler,
                'get_weighed_objects', _fake_weigh_objects)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        request_spec = {'num_instances': 10,
                        'instance_type': {'memory_mb': 512, 'root_gb': 512,
                                          'ephemeral_gb': 0,
                                          'vcpus': 1},
                        'instance_properties': {'project_id': 1,
                                                'root_gb': 512,
                                                'memory_mb': 512,
                                                'ephemeral_gb': 0,
                                                'vcpus': 1,
                                                'os_type': 'Linux'}}
        self.mox.ReplayAll()
        weighed_hosts = sched._schedule(fake_context, request_spec, {})
        self.assertEquals(len(weighed_hosts), 10)
        for weighed_host in weighed_hosts:
            self.assertTrue(weighed_host.obj is not None)

    def test_schedule_prep_resize_doesnt_update_host(self):
        fake_context = context.RequestContext('user', 'project',
                is_admin=True)

        sched = fakes.FakeFilterScheduler()

        def _return_hosts(*args, **kwargs):
            host_state = host_manager.HostState('host2', 'node2')
            return [weights.WeighedHost(host_state, 1.0)]

        self.stubs.Set(sched, '_schedule', _return_hosts)

        info = {'called': 0}

        def _fake_instance_update_db(*args, **kwargs):
            # This should not be called
            info['called'] = 1

        self.stubs.Set(driver, 'instance_update_db',
                _fake_instance_update_db)

        instance = {'uuid': 'fake-uuid', 'host': 'host1'}

        sched.schedule_prep_resize(fake_context, {}, {}, {},
                                   instance, {}, None)
        self.assertEqual(info['called'], 0)

    def test_max_attempts(self):
        self.flags(scheduler_max_attempts=4)

        sched = fakes.FakeFilterScheduler()
        self.assertEqual(4, sched._max_attempts())

    def test_invalid_max_attempts(self):
        self.flags(scheduler_max_attempts=0)

        sched = fakes.FakeFilterScheduler()
        self.assertRaises(exception.NovaException, sched._max_attempts)

    def test_retry_disabled(self):
        """Retry info should not get populated when re-scheduling is off"""
        self.flags(scheduler_max_attempts=1)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}

        sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # should not have retry info in the populated filter properties:
        self.assertFalse("retry" in filter_properties)

    def test_retry_attempt_one(self):
        """Test retry logic on initial scheduling attempt"""
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}

        sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(1, num_attempts)

    def test_retry_attempt_two(self):
        """Test retry logic when re-scheduling"""
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)

        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)

        sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(2, num_attempts)

    def test_retry_exceeded_max_attempts(self):
        """Test for necessary explosion when max retries is exceeded"""
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)

        retry = dict(num_attempts=2)
        filter_properties = dict(retry=retry)

        self.assertRaises(exception.NoValidHost, sched._schedule, self.context,
                request_spec, filter_properties=filter_properties)

    def test_add_retry_host(self):
        retry = dict(num_attempts=1, hosts=[])
        filter_properties = dict(retry=retry)
        host = "fakehost"

        sched = fakes.FakeFilterScheduler()
        sched._add_retry_host(filter_properties, host)

        hosts = filter_properties['retry']['hosts']
        self.assertEqual(1, len(hosts))
        self.assertEqual(host, hosts[0])

    def test_post_select_populate(self):
        """Test addition of certain filter props after a host is selected"""
        retry = {'hosts': [], 'num_attempts': 1}
        filter_properties = {'retry': retry}
        sched = fakes.FakeFilterScheduler()

        host_state = host_manager.HostState('host', 'node')
        host_state.limits['vcpus'] = 5
        sched._post_select_populate_filter_properties(filter_properties,
                host_state)

        self.assertEqual('host', filter_properties['retry']['hosts'][0])

        self.assertEqual({'vcpus': 5}, host_state.limits)

    def test_prep_resize_post_populates_retry(self):
        """Prep resize should add a 'host' entry to the retry dict"""
        sched = fakes.FakeFilterScheduler()

        image = 'image'
        instance = db.instance_create(self.context, {})

        instance_properties = {'project_id': 'fake', 'os_type': 'Linux'}
        instance_type = instance_types.get_instance_type_by_name("m1.tiny")
        request_spec = {'instance_properties': instance_properties,
                        'instance_type': instance_type}
        retry = {'hosts': [], 'num_attempts': 1}
        filter_properties = {'retry': retry}
        reservations = None

        host = fakes.FakeHostState('host', 'node', {})
        weighed_host = weights.WeighedHost(host, 1)
        weighed_hosts = [weighed_host]

        self.mox.StubOutWithMock(sched, '_schedule')
        self.mox.StubOutWithMock(sched.compute_rpcapi, 'prep_resize')

        sched._schedule(self.context, request_spec, filter_properties,
                [instance['uuid']]).AndReturn(weighed_hosts)
        sched.compute_rpcapi.prep_resize(self.context, image, instance,
                instance_type, 'host', reservations, request_spec=request_spec,
                filter_properties=filter_properties, node='node')

        self.mox.ReplayAll()
        sched.schedule_prep_resize(self.context, image, request_spec,
                filter_properties, instance, instance_type, reservations)

        self.assertEqual(['host'], filter_properties['retry']['hosts'])
