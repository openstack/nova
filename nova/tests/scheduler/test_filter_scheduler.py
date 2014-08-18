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

import contextlib
import uuid

import mock
import mox

from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.scheduler import driver
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import utils as scheduler_utils
from nova.scheduler import weights
from nova.tests import fake_instance
from nova.tests.scheduler import fakes
from nova.tests.scheduler import test_scheduler


def fake_get_filtered_hosts(hosts, filter_properties, index):
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
        compute_utils.add_instance_fault_from_exc(fake_context, new_ref,
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
        compute_utils.add_instance_fault_from_exc(fake_context, new_ref,
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

        expected_filter_properties = {'retry': {'num_attempts': 1,
                                                'hosts': []}}
        self.driver._schedule(fake_context, request_spec,
                expected_filter_properties).AndReturn(['host1', 'host2'])
        # instance 1
        self.driver._provision_resource(
            fake_context, 'host1',
            mox.Func(_has_launch_index(0)), expected_filter_properties,
            None, None, None, None,
            instance_uuid='fake-uuid1',
            legacy_bdm_in_spec=False).AndReturn(instance1)
        # instance 2
        self.driver._provision_resource(
            fake_context, 'host2',
            mox.Func(_has_launch_index(1)), expected_filter_properties,
            None, None, None, None,
            instance_uuid='fake-uuid2',
            legacy_bdm_in_spec=False).AndReturn(instance2)
        self.mox.ReplayAll()

        self.driver.schedule_run_instance(fake_context, request_spec,
                None, None, None, None, {}, False)

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_schedule_happy_day(self, mock_get_extra):
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
                                                'os_type': 'Linux',
                                                'uuid': 'fake-uuid'}}
        self.mox.ReplayAll()
        weighed_hosts = sched._schedule(fake_context, request_spec, {})
        self.assertEqual(len(weighed_hosts), 10)
        for weighed_host in weighed_hosts:
            self.assertIsNotNone(weighed_host.obj)

    def test_max_attempts(self):
        self.flags(scheduler_max_attempts=4)
        self.assertEqual(4, scheduler_utils._max_attempts())

    def test_invalid_max_attempts(self):
        self.flags(scheduler_max_attempts=0)
        self.assertRaises(exception.NovaException,
                          scheduler_utils._max_attempts)

    def test_retry_disabled(self):
        # Retry info should not get populated when re-scheduling is off.
        self.flags(scheduler_max_attempts=1)
        sched = fakes.FakeFilterScheduler()
        request_spec = dict(instance_properties={},
                            instance_uuids=['fake-uuid1'])
        filter_properties = {}

        self.mox.StubOutWithMock(sched, '_schedule')
        self.mox.StubOutWithMock(sched, '_provision_resource')

        sched._schedule(self.context, request_spec,
                        filter_properties).AndReturn(['host1'])
        sched._provision_resource(
            self.context, 'host1',
            request_spec, filter_properties,
            None, None, None, None,
            instance_uuid='fake-uuid1',
            legacy_bdm_in_spec=False)

        self.mox.ReplayAll()

        sched.schedule_run_instance(self.context, request_spec, None, None,
                None, None, filter_properties, False)

    def test_retry_force_hosts(self):
        # Retry info should not get populated when re-scheduling is off.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()
        request_spec = dict(instance_properties={},
                            instance_uuids=['fake-uuid1'])
        filter_properties = {'force_hosts': ['force_host']}

        self.mox.StubOutWithMock(sched, '_schedule')
        self.mox.StubOutWithMock(sched, '_provision_resource')

        sched._schedule(self.context, request_spec,
                        filter_properties).AndReturn(['host1'])
        sched._provision_resource(
            self.context, 'host1',
            request_spec, filter_properties,
            None, None, None, None,
            instance_uuid='fake-uuid1',
            legacy_bdm_in_spec=False)

        self.mox.ReplayAll()

        sched.schedule_run_instance(self.context, request_spec, None, None,
                None, None, filter_properties, False)

    def test_retry_force_nodes(self):
        # Retry info should not get populated when re-scheduling is off.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()
        request_spec = dict(instance_properties={},
                            instance_uuids=['fake-uuid1'])
        filter_properties = {'force_nodes': ['force_node']}

        self.mox.StubOutWithMock(sched, '_schedule')
        self.mox.StubOutWithMock(sched, '_provision_resource')

        sched._schedule(self.context, request_spec,
                        filter_properties).AndReturn(['host1'])
        sched._provision_resource(
            self.context, 'host1',
            request_spec, filter_properties,
            None, None, None, None,
            instance_uuid='fake-uuid1',
            legacy_bdm_in_spec=False)

        self.mox.ReplayAll()

        sched.schedule_run_instance(self.context, request_spec, None, None,
                None, None, filter_properties, False)

    def test_retry_attempt_one(self):
        # Test retry logic on initial scheduling attempt.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()
        request_spec = dict(instance_properties={},
                            instance_uuids=['fake-uuid1'])
        filter_properties = {}
        expected_filter_properties = {'retry': {'num_attempts': 1,
                                                'hosts': []}}
        self.mox.StubOutWithMock(sched, '_schedule')
        self.mox.StubOutWithMock(sched, '_provision_resource')

        sched._schedule(self.context, request_spec,
                        expected_filter_properties).AndReturn(['host1'])
        sched._provision_resource(
            self.context, 'host1',
            request_spec, expected_filter_properties,
            None, None, None, None,
            instance_uuid='fake-uuid1',
            legacy_bdm_in_spec=False)

        self.mox.ReplayAll()

        sched.schedule_run_instance(self.context, request_spec, None, None,
                None, None, filter_properties, False)

    def test_retry_attempt_two(self):
        # Test retry logic when re-scheduling.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()
        request_spec = dict(instance_properties={},
                            instance_uuids=['fake-uuid1'])
        filter_properties = {'retry': {'num_attempts': 1}}
        expected_filter_properties = {'retry': {'num_attempts': 2}}
        self.mox.StubOutWithMock(sched, '_schedule')
        self.mox.StubOutWithMock(sched, '_provision_resource')

        sched._schedule(self.context, request_spec,
                        expected_filter_properties).AndReturn(['host1'])
        sched._provision_resource(
            self.context, 'host1',
            request_spec, expected_filter_properties,
            None, None, None, None,
            instance_uuid='fake-uuid1',
            legacy_bdm_in_spec=False)

        self.mox.ReplayAll()

        sched.schedule_run_instance(self.context, request_spec, None, None,
                None, None, filter_properties, False)

    def test_retry_exceeded_max_attempts(self):
        # Test for necessary explosion when max retries is exceeded and that
        # the information needed in request_spec is still present for error
        # handling
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()
        request_spec = dict(instance_properties={},
                            instance_uuids=['fake-uuid1'])
        filter_properties = {'retry': {'num_attempts': 2}}

        self.mox.ReplayAll()

        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          self.context, request_spec, None, None,
                          None, None, filter_properties, False)

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

    def _create_server_group(self, policy='anti-affinity'):
        instance = fake_instance.fake_instance_obj(self.context,
                params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.name = 'pele'
        group.uuid = str(uuid.uuid4())
        group.members = [instance.uuid]
        group.policies = [policy]
        return group

    def _group_details_in_filter_properties(self, group, func='get_by_uuid',
                                            hint=None, policy=None):
        sched = fakes.FakeFilterScheduler()

        filter_properties = {
            'scheduler_hints': {
                'group': hint,
            },
            'group_hosts': ['hostB'],
        }

        with contextlib.nested(
            mock.patch.object(objects.InstanceGroup, func, return_value=group),
            mock.patch.object(objects.InstanceGroup, 'get_hosts',
                              return_value=['hostA']),
        ) as (get_group, get_hosts):
            sched._supports_anti_affinity = True
            update_group_hosts = sched._setup_instance_group(self.context,
                    filter_properties)
            self.assertTrue(update_group_hosts)
            self.assertEqual(set(['hostA', 'hostB']),
                             filter_properties['group_hosts'])
            self.assertEqual([policy], filter_properties['group_policies'])

    def test_group_details_in_filter_properties(self):
        for policy in ['affinity', 'anti-affinity']:
            group = self._create_server_group(policy)
            self._group_details_in_filter_properties(group, func='get_by_uuid',
                                                     hint=group.uuid,
                                                     policy=policy)

    def _group_filter_with_filter_not_configured(self, policy):
        self.flags(scheduler_default_filters=['f1', 'f2'])
        sched = fakes.FakeFilterScheduler()

        instance = fake_instance.fake_instance_obj(self.context,
                params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.uuid = str(uuid.uuid4())
        group.members = [instance.uuid]
        group.policies = [policy]

        filter_properties = {
            'scheduler_hints': {
                'group': group.uuid,
            },
        }

        with contextlib.nested(
            mock.patch.object(objects.InstanceGroup, 'get_by_uuid',
                              return_value=group),
            mock.patch.object(objects.InstanceGroup, 'get_hosts',
                              return_value=['hostA']),
        ) as (get_group, get_hosts):
            self.assertRaises(exception.NoValidHost,
                              sched._setup_instance_group, self.context,
                              filter_properties)

    def test_group_filter_with_filter_not_configured(self):
        policies = ['anti-affinity', 'affinity']
        for policy in policies:
            self._group_filter_with_filter_not_configured(policy)

    def test_group_uuid_details_in_filter_properties(self):
        group = self._create_server_group()
        self._group_details_in_filter_properties(group, 'get_by_uuid',
                                                 group.uuid, 'anti-affinity')

    def test_group_name_details_in_filter_properties(self):
        group = self._create_server_group()
        self._group_details_in_filter_properties(group, 'get_by_name',
                                                 group.name, 'anti-affinity')

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_schedule_host_pool(self, mock_get_extra):
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
                               'os_type': 'Linux',
                               'uuid': 'fake-uuid'}

        request_spec = dict(instance_properties=instance_properties,
                            instance_type={})
        filter_properties = {}
        self.mox.ReplayAll()
        hosts = sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # one host should be chosen
        self.assertEqual(len(hosts), 1)

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_schedule_large_host_pool(self, mock_get_extra):
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
                               'os_type': 'Linux',
                               'uuid': 'fake-uuid'}
        request_spec = dict(instance_properties=instance_properties,
                            instance_type={})
        filter_properties = {}
        self.mox.ReplayAll()
        hosts = sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # one host should be chose
        self.assertEqual(len(hosts), 1)

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_schedule_chooses_best_host(self, mock_get_extra):
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
                                'os_type': 'Linux',
                                'uuid': 'fake-uuid'}

        request_spec = dict(instance_properties=instance_properties,
                            instance_type={})

        self.stubs.Set(weights.HostWeightHandler,
                        'get_weighed_objects', _fake_weigh_objects)

        filter_properties = {}
        self.mox.ReplayAll()
        hosts = sched._schedule(self.context, request_spec,
                filter_properties=filter_properties)

        # one host should be chosen
        self.assertEqual(1, len(hosts))

        self.assertEqual(50, hosts[0].weight)

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_select_destinations(self, mock_get_extra):
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
                                                'os_type': 'Linux',
                                                'uuid': 'fake-uuid'},
                        'num_instances': 1}
        self.mox.ReplayAll()
        dests = sched.select_destinations(fake_context, request_spec, {})
        (host, node) = (dests[0]['host'], dests[0]['nodename'])
        self.assertEqual(host, selected_hosts[0])
        self.assertEqual(node, selected_nodes[0])

    @mock.patch.object(filter_scheduler.FilterScheduler, '_schedule')
    def test_select_destinations_notifications(self, mock_schedule):
        mock_schedule.return_value = [mock.Mock()]

        with mock.patch.object(self.driver.notifier, 'info') as mock_info:
            request_spec = {'num_instances': 1}

            self.driver.select_destinations(self.context, request_spec, {})

            expected = [
                mock.call(self.context, 'scheduler.select_destinations.start',
                 dict(request_spec=request_spec)),
                mock.call(self.context, 'scheduler.select_destinations.end',
                 dict(request_spec=request_spec))]
            self.assertEqual(expected, mock_info.call_args_list)

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
