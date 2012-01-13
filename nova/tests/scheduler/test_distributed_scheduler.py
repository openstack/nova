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

import json

import nova.db

from nova import context
from nova import exception
from nova import test
from nova.scheduler import distributed_scheduler
from nova.scheduler import least_cost
from nova.scheduler import zone_manager
from nova.tests.scheduler import fake_zone_manager as ds_fakes


class FakeEmptyZoneManager(zone_manager.ZoneManager):
    def __init__(self):
        self.service_states = {}

    def get_host_list_from_db(self, context):
        return []

    def _compute_node_get_all(*args, **kwargs):
        return []

    def _instance_get_all(*args, **kwargs):
        return []


def fake_call_zone_method(context, method, specs, zones):
    return [
        (1, [
            dict(weight=2, blob='AAAAAAA'),
            dict(weight=4, blob='BBBBBBB'),
            dict(weight=6, blob='CCCCCCC'),
            dict(weight=8, blob='DDDDDDD'),
        ]),
        (2, [
            dict(weight=10, blob='EEEEEEE'),
            dict(weight=12, blob='FFFFFFF'),
            dict(weight=14, blob='GGGGGGG'),
            dict(weight=16, blob='HHHHHHH'),
        ]),
        (3, [
            dict(weight=18, blob='IIIIIII'),
            dict(weight=20, blob='JJJJJJJ'),
            dict(weight=22, blob='KKKKKKK'),
            dict(weight=24, blob='LLLLLLL'),
        ]),
    ]


def fake_zone_get_all(context):
    return [
        dict(id=1, api_url='zone1',
             username='admin', password='password',
             weight_offset=0.0, weight_scale=1.0),
        dict(id=2, api_url='zone2',
             username='admin', password='password',
             weight_offset=1000.0, weight_scale=1.0),
        dict(id=3, api_url='zone3',
             username='admin', password='password',
             weight_offset=0.0, weight_scale=1000.0),
    ]


def fake_filter_hosts(topic, request_info, unfiltered_hosts, options):
            return unfiltered_hosts


class DistributedSchedulerTestCase(test.TestCase):
    """Test case for Distributed Scheduler."""

    def test_adjust_child_weights(self):
        """Make sure the weights returned by child zones are
        properly adjusted based on the scale/offset in the zone
        db entries.
        """
        sched = ds_fakes.FakeDistributedScheduler()
        child_results = fake_call_zone_method(None, None, None, None)
        zones = fake_zone_get_all(None)
        weighted_hosts = sched._adjust_child_weights(child_results, zones)
        scaled = [130000, 131000, 132000, 3000]
        for weighted_host in weighted_hosts:
            w = weighted_host.weight
            if weighted_host.zone == 'zone1':  # No change
                self.assertTrue(w < 1000.0)
            if weighted_host.zone == 'zone2':  # Offset +1000
                self.assertTrue(w >= 1000.0 and w < 2000)
            if weighted_host.zone == 'zone3':  # Scale x1000
                self.assertEqual(scaled.pop(0), w)

    def test_run_instance_no_hosts(self):
        """
        Ensure empty hosts & child_zones result in NoValidHosts exception.
        """
        def _fake_empty_call_zone_method(*args, **kwargs):
            return []

        sched = ds_fakes.FakeDistributedScheduler()
        sched.zone_manager = FakeEmptyZoneManager()
        self.stubs.Set(sched, '_call_zone_method',
                       _fake_empty_call_zone_method)
        self.stubs.Set(nova.db, 'zone_get_all', fake_zone_get_all)

        fake_context = context.RequestContext('user', 'project')
        request_spec = dict(instance_type=dict(memory_mb=1, local_gb=1))
        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          fake_context, request_spec)

    def test_run_instance_with_blob_hint(self):
        """
        Check the local/child zone routing in the run_instance() call.
        If the zone_blob hint was passed in, don't re-schedule.
        """
        self.schedule_called = False
        self.from_blob_called = False
        self.locally_called = False
        self.child_zone_called = False

        def _fake_schedule(*args, **kwargs):
            self.schedule_called = True
            return least_cost.WeightedHost(1, host='x')

        def _fake_make_weighted_host_from_blob(*args, **kwargs):
            self.from_blob_called = True
            return least_cost.WeightedHost(1, zone='x', blob='y')

        def _fake_provision_resource_locally(*args, **kwargs):
            self.locally_called = True
            return 1

        def _fake_ask_child_zone_to_create_instance(*args, **kwargs):
            self.child_zone_called = True
            return 2

        sched = ds_fakes.FakeDistributedScheduler()
        self.stubs.Set(sched, '_schedule', _fake_schedule)
        self.stubs.Set(sched, '_make_weighted_host_from_blob',
                       _fake_make_weighted_host_from_blob)
        self.stubs.Set(sched, '_provision_resource_locally',
                       _fake_provision_resource_locally)
        self.stubs.Set(sched, '_ask_child_zone_to_create_instance',
                       _fake_ask_child_zone_to_create_instance)
        request_spec = {
                'instance_properties': {},
                'instance_type': {},
                'filter_driver': 'nova.scheduler.host_filter.AllHostsFilter',
                'blob': "Non-None blob data",
            }

        fake_context = context.RequestContext('user', 'project')
        instances = sched.schedule_run_instance(fake_context, request_spec)
        self.assertTrue(instances)
        self.assertFalse(self.schedule_called)
        self.assertTrue(self.from_blob_called)
        self.assertTrue(self.child_zone_called)
        self.assertFalse(self.locally_called)
        self.assertEquals(instances, [2])

    def test_run_instance_non_admin(self):
        """Test creating an instance locally using run_instance, passing
        a non-admin context.  DB actions should work."""
        self.was_admin = False

        def fake_schedule(context, *args, **kwargs):
            # make sure this is called with admin context, even though
            # we're using user context below
            self.was_admin = context.is_admin
            return []

        sched = ds_fakes.FakeDistributedScheduler()
        self.stubs.Set(sched, '_schedule', fake_schedule)

        fake_context = context.RequestContext('user', 'project')

        self.assertRaises(exception.NoValidHost, sched.schedule_run_instance,
                          fake_context, {})
        self.assertTrue(self.was_admin)

    def test_schedule_bad_topic(self):
        """Parameter checking."""
        sched = ds_fakes.FakeDistributedScheduler()
        self.assertRaises(NotImplementedError, sched._schedule, None, "foo",
                          {})

    def test_schedule_no_instance_type(self):
        """Parameter checking."""
        sched = ds_fakes.FakeDistributedScheduler()
        self.assertRaises(NotImplementedError, sched._schedule, None,
                          "compute", {})

    def test_schedule_happy_day(self):
        """Make sure there's nothing glaringly wrong with _schedule()
        by doing a happy day pass through."""

        self.next_weight = 1.0

        def _fake_weighted_sum(functions, hosts, options):
            self.next_weight += 2.0
            host, hostinfo = hosts[0]
            return least_cost.WeightedHost(self.next_weight, host=host,
                                           hostinfo=hostinfo)

        sched = ds_fakes.FakeDistributedScheduler()
        fake_context = context.RequestContext('user', 'project')
        sched.zone_manager = ds_fakes.FakeZoneManager()
        self.stubs.Set(sched, '_filter_hosts', fake_filter_hosts)
        self.stubs.Set(least_cost, 'weighted_sum', _fake_weighted_sum)
        self.stubs.Set(nova.db, 'zone_get_all', fake_zone_get_all)
        self.stubs.Set(sched, '_call_zone_method', fake_call_zone_method)

        instance_type = dict(memory_mb=512, local_gb=512)
        request_spec = dict(num_instances=10, instance_type=instance_type)
        weighted_hosts = sched._schedule(fake_context, 'compute',
                                         request_spec)
        self.assertEquals(len(weighted_hosts), 10)
        for weighted_host in weighted_hosts:
            # We set this up so remote hosts have even weights ...
            if int(weighted_host.weight) % 2 == 0:
                self.assertTrue(weighted_host.zone is not None)
                self.assertTrue(weighted_host.host is None)
            else:
                self.assertTrue(weighted_host.host is not None)
                self.assertTrue(weighted_host.zone is None)

    def test_schedule_local_zone(self):
        """Test to make sure _schedule makes no call out to zones if
        local_zone in the request spec is True."""

        self.next_weight = 1.0

        def _fake_weighted_sum(functions, hosts, options):
            self.next_weight += 2.0
            host, hostinfo = hosts[0]
            return least_cost.WeightedHost(self.next_weight, host=host,
                                           hostinfo=hostinfo)

        sched = ds_fakes.FakeDistributedScheduler()
        fake_context = context.RequestContext('user', 'project')
        sched.zone_manager = ds_fakes.FakeZoneManager()
        self.stubs.Set(sched, '_filter_hosts', fake_filter_hosts)
        self.stubs.Set(least_cost, 'weighted_sum', _fake_weighted_sum)
        self.stubs.Set(nova.db, 'zone_get_all', fake_zone_get_all)
        self.stubs.Set(sched, '_call_zone_method', fake_call_zone_method)

        instance_type = dict(memory_mb=512, local_gb=512)
        request_spec = dict(num_instances=10, instance_type=instance_type,
                            local_zone=True)
        weighted_hosts = sched._schedule(fake_context, 'compute',
                                         request_spec)
        self.assertEquals(len(weighted_hosts), 10)
        for weighted_host in weighted_hosts:
            # There should be no remote hosts
            self.assertTrue(weighted_host.host is not None)
            self.assertTrue(weighted_host.zone is None)

    def test_decrypt_blob(self):
        """Test that the decrypt method works."""

        fixture = ds_fakes.FakeDistributedScheduler()
        test_data = {'weight': 1, 'host': 'x', 'blob': 'y', 'zone': 'z'}

        class StubDecryptor(object):
            def decryptor(self, key):
                return lambda blob: blob

        self.stubs.Set(distributed_scheduler, 'crypto', StubDecryptor())

        weighted_host = fixture._make_weighted_host_from_blob(
                                                        json.dumps(test_data))
        self.assertTrue(isinstance(weighted_host, least_cost.WeightedHost))
        self.assertEqual(weighted_host.to_dict(), dict(weight=1, host='x',
                         blob='y', zone='z'))

    def test_get_cost_functions(self):
        fixture = ds_fakes.FakeDistributedScheduler()
        fns = fixture.get_cost_functions()
        self.assertEquals(len(fns), 1)
        weight, fn = fns[0]
        self.assertEquals(weight, 1.0)
        hostinfo = zone_manager.HostInfo('host', free_ram_mb=1000)
        self.assertEquals(1000, fn(hostinfo))

    def test_filter_hosts_avoid(self):
        """Test to make sure _filter_hosts() filters original hosts if
        avoid_original_host is True."""

        def _fake_choose_host_filters():
            return []

        sched = ds_fakes.FakeDistributedScheduler()
        fake_context = context.RequestContext('user', 'project')
        self.stubs.Set(sched, '_choose_host_filters',
                       _fake_choose_host_filters)

        hosts = [('host1', '1info'), ('host2', '2info'), ('host3', '3info')]
        request_spec = dict(instance_properties=dict(host='host2'),
                            avoid_original_host=True)

        filtered = sched._filter_hosts('compute', request_spec, hosts, {})
        self.assertEqual(filtered,
                         [('host1', '1info'), ('host3', '3info')])

    def test_filter_hosts_no_avoid(self):
        """Test to make sure _filter_hosts() does not filter original
        hosts if avoid_original_host is False."""

        def _fake_choose_host_filters():
            return []

        sched = ds_fakes.FakeDistributedScheduler()
        fake_context = context.RequestContext('user', 'project')
        self.stubs.Set(sched, '_choose_host_filters',
                       _fake_choose_host_filters)

        hosts = [('host1', '1info'), ('host2', '2info'), ('host3', '3info')]
        request_spec = dict(instance_properties=dict(host='host2'),
                            avoid_original_host=False)

        filtered = sched._filter_hosts('compute', request_spec, hosts, {})
        self.assertEqual(filtered, hosts)
