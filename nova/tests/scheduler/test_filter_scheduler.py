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

from nova import context
from nova import exception
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import least_cost
from nova.tests.scheduler import fakes
from nova.tests.scheduler import test_scheduler


def fake_filter_hosts(hosts, filter_properties):
    return list(hosts)


class FilterSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Filter Scheduler."""

    driver_cls = filter_scheduler.FilterScheduler

    def test_run_instance_no_hosts(self):
        """
        Ensure empty hosts & child_zones result in NoValidHosts exception.
        """
        def _fake_empty_call_zone_method(*args, **kwargs):
            return []

        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')
        request_spec = {'instance_type': {'memory_mb': 1, 'root_gb': 1,
                                          'ephemeral_gb': 0},
                        'instance_properties': {'project_id': 1}}
        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          fake_context, '', request_spec, None, None, None,
                          None, {}, None)

    def test_run_instance_non_admin(self):
        """Test creating an instance locally using run_instance, passing
        a non-admin context.  DB actions should work."""
        self.was_admin = False

        def fake_get(context, *args, **kwargs):
            # make sure this is called with admin context, even though
            # we're using user context below
            self.was_admin = context.is_admin
            return {}

        sched = fakes.FakeFilterScheduler()
        self.stubs.Set(sched.host_manager, 'get_all_host_states', fake_get)

        fake_context = context.RequestContext('user', 'project')

        request_spec = {'instance_type': {'memory_mb': 1, 'local_gb': 1},
                        'instance_properties': {'project_id': 1}}
        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          fake_context, '', request_spec, None, None, None,
                          None, {}, None)
        self.assertTrue(self.was_admin)

    def test_schedule_bad_topic(self):
        """Parameter checking."""
        sched = fakes.FakeFilterScheduler()
        fake_context = context.RequestContext('user', 'project')
        self.assertRaises(NotImplementedError, sched._schedule, fake_context,
                          "foo", {}, {})

    def test_scheduler_includes_launch_index(self):
        ctxt = "fake-context"
        fake_kwargs = {'fake_kwarg1': 'fake_value1',
                       'fake_kwarg2': 'fake_value2'}
        instance_opts = {'fake_opt1': 'meow'}
        request_spec = {'num_instances': 2,
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

        class ContextFake(object):
            def elevated(self):
                return ctxt
        context_fake = ContextFake()

        self.mox.StubOutWithMock(self.driver, '_schedule')
        self.mox.StubOutWithMock(self.driver, '_provision_resource')

        self.driver._schedule(context_fake, 'compute',
                              request_spec, {}
                              ).AndReturn(['host1', 'host2'])
        # instance 1
        self.driver._provision_resource(
            ctxt, 'host1',
            mox.Func(_has_launch_index(0)), None,
            {}, None, None, None, None).AndReturn(instance1)
        # instance 2
        self.driver._provision_resource(
            ctxt, 'host2',
            mox.Func(_has_launch_index(1)), None,
            {}, None, None, None, None).AndReturn(instance2)
        self.mox.ReplayAll()

        self.driver.schedule_run_instance(context_fake, '', request_spec,
                None, None, None, None, {}, None)

    def test_schedule_happy_day(self):
        """Make sure there's nothing glaringly wrong with _schedule()
        by doing a happy day pass through."""

        self.next_weight = 1.0

        def _fake_weighted_sum(functions, hosts, options):
            self.next_weight += 2.0
            host_state = hosts[0]
            return least_cost.WeightedHost(self.next_weight,
                    host_state=host_state)

        sched = fakes.FakeFilterScheduler()
        fake_context = context.RequestContext('user', 'project',
                is_admin=True)

        self.stubs.Set(sched.host_manager, 'filter_hosts',
                fake_filter_hosts)
        self.stubs.Set(least_cost, 'weighted_sum', _fake_weighted_sum)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        request_spec = {'num_instances': 10,
                        'instance_type': {'memory_mb': 512, 'root_gb': 512,
                                          'ephemeral_gb': 0,
                                          'vcpus': 1},
                        'instance_properties': {'project_id': 1,
                                                'root_gb': 512,
                                                'memory_mb': 512,
                                                'ephemeral_gb': 0,
                                                'vcpus': 1}}
        self.mox.ReplayAll()
        weighted_hosts = sched._schedule(fake_context, 'compute',
                request_spec, {})
        self.assertEquals(len(weighted_hosts), 10)
        for weighted_host in weighted_hosts:
            self.assertTrue(weighted_host.host_state is not None)

    def test_get_cost_functions(self):
        self.flags(reserved_host_memory_mb=128)
        fixture = fakes.FakeFilterScheduler()
        fns = fixture.get_cost_functions()
        self.assertEquals(len(fns), 1)
        weight, fn = fns[0]
        self.assertEquals(weight, -1.0)
        hostinfo = host_manager.HostState('host', 'compute')
        hostinfo.update_from_compute_node(dict(memory_mb=1000,
                local_gb=0, vcpus=1))
        self.assertEquals(1000 - 128, fn(hostinfo, {}))

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

        instance_properties = {}
        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}

        sched._schedule(self.context, 'compute', request_spec,
                filter_properties=filter_properties)

        # should not have retry info in the populated filter properties:
        self.assertFalse("retry" in filter_properties)

    def test_retry_attempt_one(self):
        """Test retry logic on initial scheduling attempt"""
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {}
        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}

        sched._schedule(self.context, 'compute', request_spec,
                filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(1, num_attempts)

    def test_retry_attempt_two(self):
        """Test retry logic when re-scheduling"""
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {}
        request_spec = dict(instance_properties=instance_properties)

        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)

        sched._schedule(self.context, 'compute', request_spec,
                filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(2, num_attempts)

    def test_retry_exceeded_max_attempts(self):
        """Test for necessary explosion when max retries is exceeded"""
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {}
        request_spec = dict(instance_properties=instance_properties)

        retry = dict(num_attempts=2)
        filter_properties = dict(retry=retry)

        self.assertRaises(exception.NoValidHost, sched._schedule, self.context,
                'compute', request_spec, filter_properties=filter_properties)

    def test_add_retry_host(self):
        retry = dict(num_attempts=1, hosts=[])
        filter_properties = dict(retry=retry)
        host = "fakehost"

        sched = fakes.FakeFilterScheduler()
        sched._add_retry_host(filter_properties, host)

        hosts = filter_properties['retry']['hosts']
        self.assertEqual(1, len(hosts))
        self.assertEqual(host, hosts[0])
