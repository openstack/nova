# Copyright 2011 OpenStack Foundation
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

from nova.compute import rpcapi as compute_rpcapi
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import api as conductor_api
from nova import context
from nova import db
from nova import exception
from nova.scheduler import driver
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import utils as scheduler_utils
from nova.scheduler import weights
from nova.tests.scheduler import fakes
from nova.tests.scheduler import test_scheduler


def fake_get_filtered_hosts(hosts, filter_properties, index):
    return list(hosts)


def fake_get_group_filtered_hosts(hosts, filter_properties, index):
    group_hosts = filter_properties.get('group_hosts') or []
    if group_hosts:
        hosts = list(hosts)
        hosts.pop(0)
        return hosts
    else:
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
        old_ref, new_ref = db.instance_update_and_get_original(fake_context,
                uuid, {'vm_state': vm_states.ERROR, 'task_state':
                    None}).AndReturn(({}, {}))
        compute_utils.add_instance_fault_from_exc(fake_context,
                mox.IsA(conductor_api.LocalAPI), new_ref,
                mox.IsA(exception.NoValidHost), mox.IgnoreArg())

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        db.compute_node_get_all(mox.IgnoreArg()).AndReturn([])

        self.mox.ReplayAll()
        sched.schedule_run_instance(
                fake_context, request_spec, None, None,
                None, None, {}, False)

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
        old_ref, new_ref = db.instance_update_and_get_original(fake_context,
                uuid, {'vm_state': vm_states.ERROR, 'task_state':
                    None}).AndReturn(({}, {}))
        compute_utils.add_instance_fault_from_exc(fake_context,
                mox.IsA(conductor_api.LocalAPI), new_ref,
                mox.IsA(exception.NoValidHost), mox.IgnoreArg())
        self.mox.ReplayAll()
        sched.schedule_run_instance(
                fake_context, request_spec, None, None, None, None, {}, False)
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
            instance_uuid='fake-uuid1',
            legacy_bdm_in_spec=False).AndReturn(instance1)
        # instance 2
        self.driver._provision_resource(
            fake_context, 'host2',
            mox.Func(_has_launch_index(1)), {},
            None, None, None, None,
            instance_uuid='fake-uuid2',
            legacy_bdm_in_spec=False).AndReturn(instance2)
        self.mox.ReplayAll()

        self.driver.schedule_run_instance(fake_context, request_spec,
                None, None, None, None, {}, False)

    def test_schedule_happy_day(self):
        """Make sure there's nothing glaringly wrong with _schedule()
        by doing a happy day pass through.
        """

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

    def test_max_attempts(self):
        self.flags(scheduler_max_attempts=4)

        sched = fakes.FakeFilterScheduler()
        self.assertEqual(4, sched._max_attempts())

    def test_invalid_max_attempts(self):
        self.flags(scheduler_max_attempts=0)

        sched = fakes.FakeFilterScheduler()
        self.assertRaises(exception.NovaException, sched._max_attempts)

    def test_retry_disabled(self):
        # Retry info should not get populated when re-scheduling is off.
        self.flags(scheduler_max_attempts=1)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        db.compute_node_get_all(mox.IgnoreArg()).AndReturn([])
        self.mox.ReplayAll()

        sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # should not have retry info in the populated filter properties:
        self.assertFalse("retry" in filter_properties)

    def test_retry_attempt_one(self):
        # Test retry logic on initial scheduling attempt.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        db.compute_node_get_all(mox.IgnoreArg()).AndReturn([])
        self.mox.ReplayAll()

        sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(1, num_attempts)

    def test_retry_attempt_two(self):
        # Test retry logic when re-scheduling.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)

        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        db.compute_node_get_all(mox.IgnoreArg()).AndReturn([])
        self.mox.ReplayAll()

        sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(2, num_attempts)

    def test_retry_exceeded_max_attempts(self):
        # Test for necessary explosion when max retries is exceeded and that
        # the information needed in request_spec is still present for error
        # handling
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        instance_properties = {'project_id': '12345', 'os_type': 'Linux'}
        instance_uuids = ['fake-id']
        request_spec = dict(instance_properties=instance_properties,
                            instance_uuids=instance_uuids)

        retry = dict(num_attempts=2)
        filter_properties = dict(retry=retry)

        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          self.context, request_spec, admin_password=None,
                          injected_files=None, requested_networks=None,
                          is_first_time=False,
                          filter_properties=filter_properties,
                          legacy_bdm_in_spec=False)
        uuids = request_spec.get('instance_uuids')
        self.assertEqual(uuids, instance_uuids)

    def test_add_retry_host(self):
        retry = dict(num_attempts=1, hosts=[])
        filter_properties = dict(retry=retry)
        host = "fakehost"
        node = "fakenode"

        scheduler_utils._add_retry_host(filter_properties, host, node)

        hosts = filter_properties['retry']['hosts']
        self.assertEqual(1, len(hosts))
        self.assertEqual([host, node], hosts[0])

    def test_post_select_populate(self):
        # Test addition of certain filter props after a node is selected.
        retry = {'hosts': [], 'num_attempts': 1}
        filter_properties = {'retry': retry}

        host_state = host_manager.HostState('host', 'node')
        host_state.limits['vcpus'] = 5
        scheduler_utils.populate_filter_properties(filter_properties,
                host_state)

        self.assertEqual(['host', 'node'],
                         filter_properties['retry']['hosts'][0])

        self.assertEqual({'vcpus': 5}, host_state.limits)

    def test_basic_schedule_run_instances_anti_affinity(self):
        filter_properties = {'scheduler_hints':
                             {'group': 'cats'}}
        # Request spec 1
        instance_opts1 = {'project_id': 1, 'os_type': 'Linux',
                          'memory_mb': 512, 'root_gb': 512,
                          'ephemeral_gb': 0, 'vcpus': 1,
                          'system_metadata': {'system': 'metadata'}}
        request_spec1 = {'instance_uuids': ['fake-uuid1-1', 'fake-uuid1-2'],
                         'instance_properties': instance_opts1,
                         'instance_type': {'memory_mb': 512, 'root_gb': 512,
                                           'ephemeral_gb': 0, 'vcpus': 1}}
        self.next_weight = 1.0

        def _fake_weigh_objects(_self, functions, hosts, options):
            self.next_weight += 2.0
            host_state = hosts[0]
            return [weights.WeighedHost(host_state, self.next_weight)]

        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project',
                is_admin=True)

        self.stubs.Set(sched.host_manager, 'get_filtered_hosts',
                fake_get_group_filtered_hosts)
        self.stubs.Set(weights.HostWeightHandler,
                'get_weighed_objects', _fake_weigh_objects)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        self.mox.StubOutWithMock(driver, 'instance_update_db')
        self.mox.StubOutWithMock(compute_rpcapi.ComputeAPI, 'run_instance')
        self.mox.StubOutWithMock(sched, 'group_hosts')

        instance1_1 = {'uuid': 'fake-uuid1-1'}
        instance1_2 = {'uuid': 'fake-uuid1-2'}

        sched.group_hosts(mox.IgnoreArg(), 'cats').AndReturn([])

        def inc_launch_index1(*args, **kwargs):
            request_spec1['instance_properties']['launch_index'] = (
                request_spec1['instance_properties']['launch_index'] + 1)

        expected_metadata = {'system_metadata':
                             {'system': 'metadata', 'group': 'cats'}}
        driver.instance_update_db(fake_context, instance1_1['uuid'],
                extra_values=expected_metadata).WithSideEffects(
                inc_launch_index1).AndReturn(instance1_1)
        compute_rpcapi.ComputeAPI.run_instance(fake_context, host='host3',
                instance=instance1_1, requested_networks=None,
                injected_files=None, admin_password=None, is_first_time=None,
                request_spec=request_spec1, filter_properties=mox.IgnoreArg(),
                node='node3', legacy_bdm_in_spec=False)

        driver.instance_update_db(fake_context, instance1_2['uuid'],
                extra_values=expected_metadata).WithSideEffects(
                inc_launch_index1).AndReturn(instance1_2)
        compute_rpcapi.ComputeAPI.run_instance(fake_context, host='host4',
                instance=instance1_2, requested_networks=None,
                injected_files=None, admin_password=None, is_first_time=None,
                request_spec=request_spec1, filter_properties=mox.IgnoreArg(),
                node='node4', legacy_bdm_in_spec=False)
        self.mox.ReplayAll()
        sched.schedule_run_instance(fake_context, request_spec1,
                None, None, None, None, filter_properties, False)

    def test_schedule_host_pool(self):
        """Make sure the scheduler_host_subset_size property works properly."""

        self.flags(scheduler_host_subset_size=2)
        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project',
                is_admin=True)
        self.stubs.Set(sched.host_manager, 'get_filtered_hosts',
                fake_get_filtered_hosts)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        instance_properties = {'project_id': 1,
                                    'root_gb': 512,
                                    'memory_mb': 512,
                                    'ephemeral_gb': 0,
                                    'vcpus': 1,
                                    'os_type': 'Linux'}

        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}
        self.mox.ReplayAll()
        hosts = sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # one host should be chosen
        self.assertEqual(len(hosts), 1)

    def test_schedule_large_host_pool(self):
        """Hosts should still be chosen if pool size
        is larger than number of filtered hosts.
        """

        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project',
                is_admin=True)
        self.flags(scheduler_host_subset_size=20)
        self.stubs.Set(sched.host_manager, 'get_filtered_hosts',
                fake_get_filtered_hosts)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        instance_properties = {'project_id': 1,
                                    'root_gb': 512,
                                    'memory_mb': 512,
                                    'ephemeral_gb': 0,
                                    'vcpus': 1,
                                    'os_type': 'Linux'}
        request_spec = dict(instance_properties=instance_properties)
        filter_properties = {}
        self.mox.ReplayAll()
        hosts = sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # one host should be chose
        self.assertEqual(len(hosts), 1)

    def test_schedule_chooses_best_host(self):
        """If scheduler_host_subset_size is 1, the largest host with greatest
        weight should be returned.
        """

        self.flags(scheduler_host_subset_size=1)

        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project',
                is_admin=True)
        self.stubs.Set(sched.host_manager, 'get_filtered_hosts',
                fake_get_filtered_hosts)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        self.next_weight = 50

        def _fake_weigh_objects(_self, functions, hosts, options):
            this_weight = self.next_weight
            self.next_weight = 0
            host_state = hosts[0]
            return [weights.WeighedHost(host_state, this_weight)]

        instance_properties = {'project_id': 1,
                                'root_gb': 512,
                                'memory_mb': 512,
                                'ephemeral_gb': 0,
                                'vcpus': 1,
                                'os_type': 'Linux'}

        request_spec = dict(instance_properties=instance_properties)

        self.stubs.Set(weights.HostWeightHandler,
                        'get_weighed_objects', _fake_weigh_objects)

        filter_properties = {}
        self.mox.ReplayAll()
        hosts = sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # one host should be chosen
        self.assertEquals(1, len(hosts))

        self.assertEquals(50, hosts[0].weight)

    def test_select_hosts_happy_day(self):
        """select_hosts is basically a wrapper around the _select() method.

        Similar to the _select tests, this just does a happy path test to
        ensure there is nothing glaringly wrong.
        """

        self.next_weight = 1.0

        selected_hosts = []

        def _fake_weigh_objects(_self, functions, hosts, options):
            self.next_weight += 2.0
            host_state = hosts[0]
            selected_hosts.append(host_state.host)
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
        hosts = sched.select_hosts(fake_context, request_spec, {})
        self.assertEquals(len(hosts), 10)
        self.assertEquals(hosts, selected_hosts)

    def test_select_hosts_no_valid_host(self):

        def _return_no_host(*args, **kwargs):
            return []

        self.stubs.Set(self.driver, '_schedule', _return_no_host)
        self.assertRaises(exception.NoValidHost,
                          self.driver.select_hosts, self.context, {}, {})

    def test_select_destinations(self):
        """select_destinations is basically a wrapper around _schedule().

        Similar to the _schedule tests, this just does a happy path test to
        ensure there is nothing glaringly wrong.
        """

        self.next_weight = 1.0

        selected_hosts = []
        selected_nodes = []

        def _fake_weigh_objects(_self, functions, hosts, options):
            self.next_weight += 2.0
            host_state = hosts[0]
            selected_hosts.append(host_state.host)
            selected_nodes.append(host_state.nodename)
            return [weights.WeighedHost(host_state, self.next_weight)]

        sched = fakes.FakeFilterScheduler()
        fake_context = context.RequestContext('user', 'project',
            is_admin=True)

        self.stubs.Set(sched.host_manager, 'get_filtered_hosts',
            fake_get_filtered_hosts)
        self.stubs.Set(weights.HostWeightHandler,
            'get_weighed_objects', _fake_weigh_objects)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        request_spec = {'instance_type': {'memory_mb': 512, 'root_gb': 512,
                                          'ephemeral_gb': 0,
                                          'vcpus': 1},
                        'instance_properties': {'project_id': 1,
                                                'root_gb': 512,
                                                'memory_mb': 512,
                                                'ephemeral_gb': 0,
                                                'vcpus': 1,
                                                'os_type': 'Linux'},
                        'num_instances': 1}
        self.mox.ReplayAll()
        dests = sched.select_destinations(fake_context, request_spec, {})
        (host, node) = (dests[0]['host'], dests[0]['nodename'])
        self.assertEquals(host, selected_hosts[0])
        self.assertEquals(node, selected_nodes[0])

    def test_select_destinations_no_valid_host(self):

        def _return_no_host(*args, **kwargs):
            return []

        self.stubs.Set(self.driver, '_schedule', _return_no_host)
        self.assertRaises(exception.NoValidHost,
                self.driver.select_destinations, self.context,
                {'num_instances': 1}, {})

    def test_handles_deleted_instance(self):
        """Test instance deletion while being scheduled."""

        def _raise_instance_not_found(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='123')

        self.stubs.Set(driver, 'instance_update_db',
                       _raise_instance_not_found)

        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')
        host_state = host_manager.HostState('host2', 'node2')
        weighted_host = weights.WeighedHost(host_state, 1.42)
        filter_properties = {}

        uuid = 'fake-uuid1'
        instance_properties = {'project_id': 1, 'os_type': 'Linux'}
        request_spec = {'instance_type': {'memory_mb': 1, 'local_gb': 1},
                        'instance_properties': instance_properties,
                        'instance_uuids': [uuid]}
        sched._provision_resource(fake_context, weighted_host,
                                  request_spec, filter_properties,
                                  None, None, None, None)
