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
Tests For Distributed Scheduler.
"""

from nova import context
from nova import exception
from nova.scheduler import least_cost
from nova.scheduler import host_manager
from nova import test
from nova.tests.scheduler import fakes


def fake_filter_hosts(hosts, filter_properties):
    return list(hosts)


class DistributedSchedulerTestCase(test.TestCase):
    """Test case for Distributed Scheduler."""

    def test_run_instance_no_hosts(self):
        """
        Ensure empty hosts & child_zones result in NoValidHosts exception.
        """
        def _fake_empty_call_zone_method(*args, **kwargs):
            return []

        sched = fakes.FakeDistributedScheduler()

        fake_context = context.RequestContext('user', 'project')
        request_spec = {'instance_type': {'memory_mb': 1, 'root_gb': 1,
                                          'ephemeral_gb': 0},
                        'instance_properties': {'project_id': 1}}
        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          fake_context, request_spec)

    def test_run_instance_non_admin(self):
        """Test creating an instance locally using run_instance, passing
        a non-admin context.  DB actions should work."""
        self.was_admin = False

        def fake_get(context, *args, **kwargs):
            # make sure this is called with admin context, even though
            # we're using user context below
            self.was_admin = context.is_admin
            return {}

        sched = fakes.FakeDistributedScheduler()
        self.stubs.Set(sched.host_manager, 'get_all_host_states', fake_get)

        fake_context = context.RequestContext('user', 'project')

        request_spec = {'instance_type': {'memory_mb': 1, 'local_gb': 1},
                        'instance_properties': {'project_id': 1}}
        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          fake_context, request_spec)
        self.assertTrue(self.was_admin)

    def test_schedule_bad_topic(self):
        """Parameter checking."""
        sched = fakes.FakeDistributedScheduler()
        fake_context = context.RequestContext('user', 'project')
        self.assertRaises(NotImplementedError, sched._schedule, fake_context,
                          "foo", {})

    def test_schedule_happy_day(self):
        """Make sure there's nothing glaringly wrong with _schedule()
        by doing a happy day pass through."""

        self.next_weight = 1.0

        def _fake_weighted_sum(functions, hosts, options):
            self.next_weight += 2.0
            host_state = hosts[0]
            return least_cost.WeightedHost(self.next_weight,
                    host_state=host_state)

        sched = fakes.FakeDistributedScheduler()
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
                request_spec)
        self.mox.VerifyAll()
        self.assertEquals(len(weighted_hosts), 10)
        for weighted_host in weighted_hosts:
            self.assertTrue(weighted_host.host_state is not None)

    def test_get_cost_functions(self):
        self.flags(reserved_host_memory_mb=128)
        fixture = fakes.FakeDistributedScheduler()
        fns = fixture.get_cost_functions()
        self.assertEquals(len(fns), 1)
        weight, fn = fns[0]
        self.assertEquals(weight, 1.0)
        hostinfo = host_manager.HostState('host', 'compute')
        hostinfo.update_from_compute_node(dict(memory_mb=1000,
                local_gb=0, vcpus=1))
        self.assertEquals(1000 - 128, fn(hostinfo, {}))
