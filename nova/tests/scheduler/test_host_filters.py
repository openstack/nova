# Copyright 2011 OpenStack Foundation  # All Rights Reserved.
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
Tests For Scheduler Host Filters.
"""

from oslo.config import cfg

from nova import context
from nova import db
from nova.scheduler import filters
from nova import servicegroup
from nova import test
from nova.tests.scheduler import fakes

CONF = cfg.CONF


class TestFilter(filters.BaseHostFilter):
    pass


class TestBogusFilter(object):
    """Class that doesn't inherit from BaseHostFilter."""
    pass


class HostFiltersTestCase(test.NoDBTestCase):
    """Test case for host filters."""
    # FIXME(sirp): These tests still require DB access until we can separate
    # the testing of the DB API code from the host-filter code.
    USES_DB = True

    def setUp(self):
        super(HostFiltersTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        filter_handler = filters.HostFilterHandler()
        classes = filter_handler.get_matching_classes(
                ['nova.scheduler.filters.all_filters'])
        self.class_map = {}
        for cls in classes:
            self.class_map[cls.__name__] = cls

    def test_all_filters(self):
        # Double check at least a couple of known filters exist
        self.assertIn('AllHostsFilter', self.class_map)
        self.assertIn('ComputeFilter', self.class_map)

    def test_all_host_filter(self):
        filt_cls = self.class_map['AllHostsFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertTrue(filt_cls.host_passes(host, {}))

    def _stub_service_is_up(self, ret_value):
        def fake_service_is_up(self, service):
                return ret_value
        self.stubs.Set(servicegroup.API, 'service_is_up', fake_service_is_up)

    def test_compute_filter_passes(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_type_filter(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TypeAffinityFilter']()

        filter_properties = {'context': self.context,
                             'instance_type': {'id': 1}}
        filter2_properties = {'context': self.context,
                             'instance_type': {'id': 2}}

        service = {'disabled': False}
        host = fakes.FakeHostState('fake_host', 'fake_node',
                {'service': service})
        # True since empty
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        fakes.FakeInstance(context=self.context,
                           params={'host': 'fake_host', 'instance_type_id': 1})
        # True since same type
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        # False since different type
        self.assertFalse(filt_cls.host_passes(host, filter2_properties))
        # False since node not homogeneous
        fakes.FakeInstance(context=self.context,
                           params={'host': 'fake_host', 'instance_type_id': 2})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_type_filter(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateTypeAffinityFilter']()

        filter_properties = {'context': self.context,
                             'instance_type': {'name': 'fake1'}}
        filter2_properties = {'context': self.context,
                             'instance_type': {'name': 'fake2'}}
        service = {'disabled': False}
        host = fakes.FakeHostState('fake_host', 'fake_node',
                {'service': service})
        # True since no aggregates
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        # True since type matches aggregate, metadata
        self._create_aggregate_with_host(name='fake_aggregate',
                hosts=['fake_host'], metadata={'instance_type': 'fake1'})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        # False since type matches aggregate, metadata
        self.assertFalse(filt_cls.host_passes(host, filter2_properties))

    def _test_compute_filter_fails_on_service_disabled(self,
                                                       reason=None):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': True}
        if reason:
            service['disabled_reason'] = reason
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_fails_on_service_disabled_no_reason(self):
        self._test_compute_filter_fails_on_service_disabled()

    def test_compute_filter_fails_on_service_disabled(self):
        self._test_compute_filter_fails_on_service_disabled(reason='Test')

    def test_compute_filter_fails_on_service_down(self):
        self._stub_service_is_up(False)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def _create_aggregate_with_host(self, name='fake_aggregate',
                          metadata=None,
                          hosts=['host1']):
        values = {'name': name}
        if metadata:
            metadata['availability_zone'] = 'fake_avail_zone'
        else:
            metadata = {'availability_zone': 'fake_avail_zone'}
        result = db.aggregate_create(self.context.elevated(), values, metadata)
        for host in hosts:
            db.aggregate_host_add(self.context.elevated(), result['id'], host)
        return result

    def test_core_filter_passes(self):
        filt_cls = self.class_map['CoreFilter']()
        filter_properties = {'instance_type': {'vcpus': 1}}
        self.flags(cpu_allocation_ratio=2)
        host = fakes.FakeHostState('host1', 'node1',
                {'vcpus_total': 4, 'vcpus_used': 7})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_core_filter_fails_safe(self):
        filt_cls = self.class_map['CoreFilter']()
        filter_properties = {'instance_type': {'vcpus': 1}}
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_core_filter_fails(self):
        filt_cls = self.class_map['CoreFilter']()
        filter_properties = {'instance_type': {'vcpus': 1}}
        self.flags(cpu_allocation_ratio=2)
        host = fakes.FakeHostState('host1', 'node1',
                {'vcpus_total': 4, 'vcpus_used': 8})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_core_filter_value_error(self):
        filt_cls = self.class_map['AggregateCoreFilter']()
        filter_properties = {'context': self.context,
                             'instance_type': {'vcpus': 1}}
        self.flags(cpu_allocation_ratio=2)
        host = fakes.FakeHostState('host1', 'node1',
                {'vcpus_total': 4, 'vcpus_used': 7})
        self._create_aggregate_with_host(name='fake_aggregate',
                hosts=['host1'],
                metadata={'cpu_allocation_ratio': 'XXX'})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(4 * 2, host.limits['vcpu'])

    def test_aggregate_core_filter_default_value(self):
        filt_cls = self.class_map['AggregateCoreFilter']()
        filter_properties = {'context': self.context,
                             'instance_type': {'vcpus': 1}}
        self.flags(cpu_allocation_ratio=2)
        host = fakes.FakeHostState('host1', 'node1',
                {'vcpus_total': 4, 'vcpus_used': 8})
        # False: fallback to default flag w/o aggregates
        self.assertFalse(filt_cls.host_passes(host, filter_properties))
        self._create_aggregate_with_host(name='fake_aggregate',
                hosts=['host1'],
                metadata={'cpu_allocation_ratio': '3'})
        # True: use ratio from aggregates
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(4 * 3, host.limits['vcpu'])

    def test_aggregate_core_filter_conflict_values(self):
        filt_cls = self.class_map['AggregateCoreFilter']()
        filter_properties = {'context': self.context,
                             'instance_type': {'vcpus': 1}}
        self.flags(cpu_allocation_ratio=1)
        host = fakes.FakeHostState('host1', 'node1',
                {'vcpus_total': 4, 'vcpus_used': 8})
        self._create_aggregate_with_host(name='fake_aggregate1',
                hosts=['host1'],
                metadata={'cpu_allocation_ratio': '2'})
        self._create_aggregate_with_host(name='fake_aggregate2',
                hosts=['host1'],
                metadata={'cpu_allocation_ratio': '3'})
        # use the minimum ratio from aggregates
        self.assertFalse(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(4 * 2, host.limits['vcpu'])

    @staticmethod
    def _make_zone_request(zone, is_admin=False):
        ctxt = context.RequestContext('fake', 'fake', is_admin=is_admin)
        return {
            'context': ctxt,
            'request_spec': {
                'instance_properties': {
                    'availability_zone': zone
                }
            }
        }

    def test_availability_zone_filter_same(self):
        filt_cls = self.class_map['AvailabilityZoneFilter']()
        service = {'availability_zone': 'nova'}
        request = self._make_zone_request('nova')
        host = fakes.FakeHostState('host1', 'node1',
                                   {'service': service})
        self.assertTrue(filt_cls.host_passes(host, request))

    def test_availability_zone_filter_different(self):
        filt_cls = self.class_map['AvailabilityZoneFilter']()
        service = {'availability_zone': 'nova'}
        request = self._make_zone_request('bad')
        host = fakes.FakeHostState('host1', 'node1',
                                   {'service': service})
        self.assertFalse(filt_cls.host_passes(host, request))

    def test_retry_filter_disabled(self):
        # Test case where retry/re-scheduling is disabled.
        filt_cls = self.class_map['RetryFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_retry_filter_pass(self):
        # Node not previously tried.
        filt_cls = self.class_map['RetryFilter']()
        host = fakes.FakeHostState('host1', 'nodeX', {})
        retry = dict(num_attempts=2,
                     hosts=[['host1', 'node1'],  # same host, different node
                            ['host2', 'node2'],  # different host and node
                            ])
        filter_properties = dict(retry=retry)
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_retry_filter_fail(self):
        # Node was already tried.
        filt_cls = self.class_map['RetryFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        retry = dict(num_attempts=1,
                     hosts=[['host1', 'node1']])
        filter_properties = dict(retry=retry)
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_filter_num_iops_passes(self):
        self.flags(max_io_ops_per_host=8)
        filt_cls = self.class_map['IoOpsFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 7})
        filter_properties = {}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_filter_num_iops_fails(self):
        self.flags(max_io_ops_per_host=8)
        filt_cls = self.class_map['IoOpsFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 8})
        filter_properties = {}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_filter_num_instances_passes(self):
        self.flags(max_instances_per_host=5)
        filt_cls = self.class_map['NumInstancesFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_instances': 4})
        filter_properties = {}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_filter_num_instances_fails(self):
        self.flags(max_instances_per_host=5)
        filt_cls = self.class_map['NumInstancesFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_instances': 5})
        filter_properties = {}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def _test_group_anti_affinity_filter_passes(self, cls, policy):
        filt_cls = self.class_map[cls]()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        filter_properties = {'group_policies': ['affinity']}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        filter_properties = {'group_policies': [policy]}
        filter_properties['group_hosts'] = []
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        filter_properties['group_hosts'] = ['host2']
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_group_anti_affinity_filter_passes(self):
        self._test_group_anti_affinity_filter_passes(
                'ServerGroupAntiAffinityFilter', 'anti-affinity')

    def test_group_anti_affinity_filter_passes_legacy(self):
        self._test_group_anti_affinity_filter_passes(
                'GroupAntiAffinityFilter', 'legacy')

    def _test_group_anti_affinity_filter_fails(self, cls, policy):
        filt_cls = self.class_map[cls]()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_policies': [policy],
                             'group_hosts': ['host1']}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_group_anti_affinity_filter_fails(self):
        self._test_group_anti_affinity_filter_fails(
                'ServerGroupAntiAffinityFilter', 'anti-affinity')

    def test_group_anti_affinity_filter_fails_legacy(self):
        self._test_group_anti_affinity_filter_fails(
                'GroupAntiAffinityFilter', 'legacy')

    def _test_group_affinity_filter_passes(self, cls, policy):
        filt_cls = self.class_map['ServerGroupAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        filter_properties = {'group_policies': ['anti-affinity']}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        filter_properties = {'group_policies': ['affinity'],
                             'group_hosts': ['host1']}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_group_affinity_filter_passes(self):
        self._test_group_affinity_filter_passes(
                'ServerGroupAffinityFilter', 'affinity')

    def test_group_affinity_filter_passes_legacy(self):
        self._test_group_affinity_filter_passes(
                'GroupAffinityFilter', 'legacy')

    def _test_group_affinity_filter_fails(self, cls, policy):
        filt_cls = self.class_map[cls]()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_policies': [policy],
                             'group_hosts': ['host2']}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_group_affinity_filter_fails(self):
        self._test_group_affinity_filter_fails(
                'ServerGroupAffinityFilter', 'affinity')

    def test_group_affinity_filter_fails_legacy(self):
        self._test_group_affinity_filter_fails(
                'GroupAffinityFilter', 'legacy')

    def test_metrics_filter_pass(self):
        self.flags(weight_setting=['foo=1', 'bar=2'], group='metrics')
        metrics = dict(foo=1, bar=2)
        host = fakes.FakeHostState('host1', 'node1',
                                   attribute_dict={'metrics': metrics})
        filt_cls = self.class_map['MetricsFilter']()
        self.assertTrue(filt_cls.host_passes(host, None))

    def test_metrics_filter_missing_metrics(self):
        self.flags(weight_setting=['foo=1', 'bar=2'], group='metrics')
        metrics = dict(foo=1)
        host = fakes.FakeHostState('host1', 'node1',
                                   attribute_dict={'metrics': metrics})
        filt_cls = self.class_map['MetricsFilter']()
        self.assertFalse(filt_cls.host_passes(host, None))

    def test_aggregate_filter_num_iops_value(self):
        self.flags(max_io_ops_per_host=7)
        filt_cls = self.class_map['AggregateIoOpsFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 7})
        filter_properties = {'context': self.context}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))
        self._create_aggregate_with_host(
            name='fake_aggregate',
            hosts=['host1'],
            metadata={'max_io_ops_per_host': 8})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_filter_num_iops_value_error(self):
        self.flags(max_io_ops_per_host=8)
        filt_cls = self.class_map['AggregateIoOpsFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_io_ops': 7})
        self._create_aggregate_with_host(
            name='fake_aggregate',
            hosts=['host1'],
            metadata={'max_io_ops_per_host': 'XXX'})
        filter_properties = {'context': self.context}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_disk_filter_value_error(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateDiskFilter']()
        self.flags(disk_allocation_ratio=1.0)
        filter_properties = {
            'context': self.context,
            'instance_type': {'root_gb': 1,
                              'ephemeral_gb': 1,
                              'swap': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'free_disk_mb': 3 * 1024,
                                    'total_usable_disk_gb': 1,
                                   'service': service})
        self._create_aggregate_with_host(name='fake_aggregate',
                hosts=['host1'],
                metadata={'disk_allocation_ratio': 'XXX'})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_disk_filter_default_value(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateDiskFilter']()
        self.flags(disk_allocation_ratio=1.0)
        filter_properties = {
            'context': self.context,
            'instance_type': {'root_gb': 2,
                              'ephemeral_gb': 1,
                              'swap': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'free_disk_mb': 3 * 1024,
                                    'total_usable_disk_gb': 1,
                                   'service': service})
        # Uses global conf.
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        # Uses an aggregate with ratio
        self._create_aggregate_with_host(
            name='fake_aggregate',
            hosts=['host1'],
            metadata={'disk_allocation_ratio': '2'})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_filter_aggregate_num_instances_value(self):
        self.flags(max_instances_per_host=4)
        filt_cls = self.class_map['AggregateNumInstancesFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_instances': 5})
        filter_properties = {'context': self.context}
        # No aggregate defined for that host.
        self.assertFalse(filt_cls.host_passes(host, filter_properties))
        self._create_aggregate_with_host(
            name='fake_aggregate',
            hosts=['host1'],
            metadata={'max_instances_per_host': 6})
        # Aggregate defined for that host.
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_filter_aggregate_num_instances_value_error(self):
        self.flags(max_instances_per_host=6)
        filt_cls = self.class_map['AggregateNumInstancesFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                                   {'num_instances': 5})
        filter_properties = {'context': self.context}
        self._create_aggregate_with_host(
            name='fake_aggregate',
            hosts=['host1'],
            metadata={'max_instances_per_host': 'XXX'})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
