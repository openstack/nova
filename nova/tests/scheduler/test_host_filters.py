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

from nova import context
from nova.scheduler import filters
from nova import test
from nova.tests.scheduler import fakes


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
