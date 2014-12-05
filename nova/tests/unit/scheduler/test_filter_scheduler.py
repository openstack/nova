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

import mock

from nova import context
from nova import exception
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import utils as scheduler_utils
from nova.scheduler import weights
from nova.tests.unit.scheduler import fakes
from nova.tests.unit.scheduler import test_scheduler


def fake_get_filtered_hosts(hosts, filter_properties, index):
    return list(hosts)


class FilterSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Filter Scheduler."""

    driver_cls = filter_scheduler.FilterScheduler

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

    def test_select_destinations_no_valid_host_not_enough(self):
        # Tests that we have fewer hosts available than number of instances
        # requested to build.
        with mock.patch.object(self.driver, '_schedule',
                               return_value=[mock.sentinel.host1]):
            try:
                self.driver.select_destinations(
                    self.context, {'num_instances': 2}, {})
                self.fail('Expected NoValidHost to be raised.')
            except exception.NoValidHost as e:
                # Make sure that we provided a reason why NoValidHost.
                self.assertIn('reason', e.kwargs)
                self.assertTrue(len(e.kwargs['reason']) > 0)
