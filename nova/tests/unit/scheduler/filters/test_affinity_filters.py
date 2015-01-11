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

import mock
from oslo_config import cfg

from nova.scheduler.filters import affinity_filter
from nova import test
from nova.tests.unit.scheduler import fakes

CONF = cfg.CONF

CONF.import_opt('my_ip', 'nova.netconf')


@mock.patch('nova.compute.api.API.get_all')
class TestDifferentHostFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestDifferentHostFilter, self).setUp()
        self.filt_cls = affinity_filter.DifferentHostFilter()

    def test_affinity_different_filter_passes(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})
        get_all_mock.return_value = []

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                'different_host': ['fake'], }}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        get_all_mock.assert_called_once_with(mock.sentinel.ctx,
                                             {'host': 'host1',
                                              'uuid': ['fake'],
                                              'deleted': False})

    def test_affinity_different_filter_no_list_passes(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})
        get_all_mock.return_value = []

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                 'different_host': 'fake'}}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        get_all_mock.assert_called_once_with(mock.sentinel.ctx,
                                             {'host': 'host1',
                                              'uuid': ['fake'],
                                              'deleted': False})

    def test_affinity_different_filter_fails(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})
        get_all_mock.return_value = [mock.sentinel.instances]

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                'different_host': ['fake'], }}

        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))
        get_all_mock.assert_called_once_with(mock.sentinel.ctx,
                                             {'host': 'host1',
                                              'uuid': ['fake'],
                                              'deleted': False})

    def test_affinity_different_filter_handles_none(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': None}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        self.assertFalse(get_all_mock.called)


@mock.patch('nova.compute.api.API.get_all')
class TestSameHostFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestSameHostFilter, self).setUp()
        self.filt_cls = affinity_filter.SameHostFilter()

    def test_affinity_same_filter_passes(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})
        get_all_mock.return_value = [mock.sentinel.images]

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                'same_host': ['fake'], }}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        get_all_mock.assert_called_once_with(mock.sentinel.ctx,
                                             {'host': 'host1',
                                              'uuid': ['fake'],
                                              'deleted': False})

    def test_affinity_same_filter_no_list_passes(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})
        get_all_mock.return_value = [mock.sentinel.images]

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                 'same_host': 'fake'}}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        get_all_mock.assert_called_once_with(mock.sentinel.ctx,
                                             {'host': 'host1',
                                              'uuid': ['fake'],
                                              'deleted': False})

    def test_affinity_same_filter_fails(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})
        get_all_mock.return_value = []

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                'same_host': ['fake'], }}

        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))
        get_all_mock.assert_called_once_with(mock.sentinel.ctx,
                                             {'host': 'host1',
                                              'uuid': ['fake'],
                                              'deleted': False})

    def test_affinity_same_filter_handles_none(self, get_all_mock):
        host = fakes.FakeHostState('host1', 'node1', {})

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': None}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        self.assertFalse(get_all_mock.called)


class TestSimpleCIDRAffinityFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestSimpleCIDRAffinityFilter, self).setUp()
        self.filt_cls = affinity_filter.SimpleCIDRAffinityFilter()

    def test_affinity_simple_cidr_filter_passes(self):
        host = fakes.FakeHostState('host1', 'node1', {})
        host.host_ip = '10.8.1.1'

        affinity_ip = "10.8.1.100"

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                 'cidr': '/24',
                                 'build_near_host_ip': affinity_ip}}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_fails(self):
        host = fakes.FakeHostState('host1', 'node1', {})
        host.host_ip = '10.8.1.1'

        affinity_ip = "10.8.1.100"

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': {
                                 'cidr': '/32',
                                 'build_near_host_ip': affinity_ip}}

        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_handles_none(self):
        host = fakes.FakeHostState('host1', 'node1', {})

        affinity_ip = CONF.my_ip.split('.')[0:3]
        affinity_ip.append('100')
        affinity_ip = str.join('.', affinity_ip)

        filter_properties = {'context': mock.sentinel.ctx,
                             'scheduler_hints': None}

        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))


class TestGroupAffinityFilter(test.NoDBTestCase):

    def _test_group_anti_affinity_filter_passes(self, filt_cls, policy):
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
                affinity_filter.ServerGroupAntiAffinityFilter(),
                'anti-affinity')

    def _test_group_anti_affinity_filter_fails(self, filt_cls, policy):
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_policies': [policy],
                             'group_hosts': ['host1']}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_group_anti_affinity_filter_fails(self):
        self._test_group_anti_affinity_filter_fails(
                affinity_filter.ServerGroupAntiAffinityFilter(),
                'anti-affinity')

    def _test_group_affinity_filter_passes(self, filt_cls, policy):
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
                affinity_filter.ServerGroupAffinityFilter(), 'affinity')

    def _test_group_affinity_filter_fails(self, filt_cls, policy):
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_policies': [policy],
                             'group_hosts': ['host2']}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_group_affinity_filter_fails(self):
        self._test_group_affinity_filter_fails(
                affinity_filter.ServerGroupAffinityFilter(), 'affinity')
