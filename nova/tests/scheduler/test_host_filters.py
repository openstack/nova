# Copyright 2011 OpenStack LLC.  # All Rights Reserved.
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

import httplib
import stubout

from nova import context
from nova import exception
from nova import flags
from nova.openstack.common import jsonutils
from nova.scheduler import filters
from nova.scheduler.filters.trusted_filter import AttestationService
from nova import test
from nova.tests.scheduler import fakes
from nova import utils


DATA = ''


def stub_out_https_backend(stubs):
    """
    Stubs out the httplib.HTTPRequest.getresponse to return
    faked-out data instead of grabbing actual contents of a resource

    The stubbed getresponse() returns an iterator over
    the data "I am a teapot, short and stout\n"

    :param stubs: Set of stubout stubs
    """

    class FakeHTTPResponse(object):

        def read(self):
            return DATA

    def fake_do_request(self, *args, **kwargs):
        return httplib.OK, FakeHTTPResponse()

    stubs.Set(AttestationService, '_do_request', fake_do_request)


class TestFilter(filters.BaseHostFilter):
    pass


class TestBogusFilter(object):
    """Class that doesn't inherit from BaseHostFilter"""
    pass


class HostFiltersTestCase(test.TestCase):
    """Test case for host filters."""

    def setUp(self):
        super(HostFiltersTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        stub_out_https_backend(self.stubs)
        self.context = context.RequestContext('fake', 'fake')
        self.json_query = jsonutils.dumps(
                ['and', ['>=', '$free_ram_mb', 1024],
                        ['>=', '$free_disk_mb', 200 * 1024]])
        # This has a side effect of testing 'get_filter_classes'
        # when specifying a method (in this case, our standard filters)
        classes = filters.get_filter_classes(
                ['nova.scheduler.filters.standard_filters'])
        self.class_map = {}
        for cls in classes:
            self.class_map[cls.__name__] = cls

    def test_get_filter_classes(self):
        classes = filters.get_filter_classes(
                ['nova.tests.scheduler.test_host_filters.TestFilter'])
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0].__name__, 'TestFilter')
        # Test a specific class along with our standard filters
        classes = filters.get_filter_classes(
                ['nova.tests.scheduler.test_host_filters.TestFilter',
                 'nova.scheduler.filters.standard_filters'])
        self.assertEqual(len(classes), 1 + len(self.class_map))

    def test_get_filter_classes_raises_on_invalid_classes(self):
        self.assertRaises(ImportError,
                filters.get_filter_classes,
                ['nova.tests.scheduler.test_host_filters.NoExist'])
        self.assertRaises(exception.ClassNotFound,
                filters.get_filter_classes,
                ['nova.tests.scheduler.test_host_filters.TestBogusFilter'])

    def test_all_host_filter(self):
        filt_cls = self.class_map['AllHostsFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, {}))

    def _stub_service_is_up(self, ret_value):
        def fake_service_is_up(service):
            return ret_value
        self.stubs.Set(utils, 'service_is_up', fake_service_is_up)

    def test_affinity_different_filter_passes(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'different_host': [instance_uuid], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_no_list_passes(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'different_host': instance_uuid}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_fails(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'different_host': [instance_uuid], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_handles_none(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_no_list_passes(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'same_host': instance_uuid}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_passes(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'same_host': [instance_uuid], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_fails(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'same_host': [instance_uuid], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_handles_none(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_passes(self):
        filt_cls = self.class_map['SimpleCIDRAffinityFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        host.capabilities = {'host_ip': '10.8.1.1'}

        affinity_ip = "10.8.1.100"

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'cidr': '/24',
                                 'build_near_host_ip': affinity_ip}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_fails(self):
        filt_cls = self.class_map['SimpleCIDRAffinityFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        host.capabilities = {'host_ip': '10.8.1.1'}

        affinity_ip = "10.8.1.100"

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'cidr': '/32',
                                 'build_near_host_ip': affinity_ip}}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_handles_none(self):
        filt_cls = self.class_map['SimpleCIDRAffinityFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})

        affinity_ip = flags.FLAGS.my_ip.split('.')[0:3]
        affinity_ip.append('100')
        affinity_ip = str.join('.', affinity_ip)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_passes(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        capabilities = {'enabled': True}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_type_filter(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TypeAffinityFilter']()

        filter_properties = {'context': self.context,
                             'instance_type': {'id': 1}}
        filter2_properties = {'context': self.context,
                             'instance_type': {'id': 2}}

        capabilities = {'enabled': True}
        service = {'disabled': False}
        host = fakes.FakeHostState('fake_host', 'compute',
                {'capabilities': capabilities,
                 'service': service})
        #True since empty
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        fakes.FakeInstance(context=self.context,
                           params={'host': 'fake_host', 'instance_type_id': 1})
        #True since same type
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        #False since different type
        self.assertFalse(filt_cls.host_passes(host, filter2_properties))
        #False since node not homogeneous
        fakes.FakeInstance(context=self.context,
                           params={'host': 'fake_host', 'instance_type_id': 2})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_ram_filter_fails_on_memory(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['RamFilter']()
        self.flags(ram_allocation_ratio=1.0)
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        capabilities = {'enabled': True}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1023, 'total_usable_ram_mb': 1024,
                 'capabilities': capabilities, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_ram_filter_oversubscribe(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['RamFilter']()
        self.flags(ram_allocation_ratio=2.0)
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        capabilities = {'enabled': True}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': -1024, 'total_usable_ram_mb': 2048,
                 'capabilities': capabilities, 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_fails_on_service_disabled(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        capabilities = {'enabled': True}
        service = {'disabled': True}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_fails_on_service_down(self):
        self._stub_service_is_up(False)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        capabilities = {'enabled': True}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_fails_on_capability_disabled(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        capabilities = {'enabled': False}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_passes_on_volume(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        capabilities = {'enabled': False}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'volume',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_passes_on_no_instance_type(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {}
        capabilities = {'enabled': False}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_passes_extra_specs(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeCapabilitiesFilter']()
        extra_specs = {'opt1': 1, 'opt2': 2}
        capabilities = {'enabled': True, 'opt1': 1, 'opt2': 2}
        service = {'disabled': False}
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_fails_extra_specs(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeCapabilitiesFilter']()
        extra_specs = {'opt1': 1, 'opt2': 3}
        capabilities = {'enabled': True, 'opt1': 1, 'opt2': 2}
        service = {'disabled': False}
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024, 'capabilities': capabilities,
                 'service': service})

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_isolated_hosts_fails_isolated_on_non_isolated(self):
        self.flags(isolated_images=['isolated'], isolated_hosts=['isolated'])
        filt_cls = self.class_map['IsolatedHostsFilter']()
        filter_properties = {
            'request_spec': {
                'instance_properties': {'image_ref': 'isolated'}
            }
        }
        host = fakes.FakeHostState('non-isolated', 'compute', {})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_isolated_hosts_fails_non_isolated_on_isolated(self):
        self.flags(isolated_images=['isolated'], isolated_hosts=['isolated'])
        filt_cls = self.class_map['IsolatedHostsFilter']()
        filter_properties = {
            'request_spec': {
                'instance_properties': {'image_ref': 'non-isolated'}
            }
        }
        host = fakes.FakeHostState('isolated', 'compute', {})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_isolated_hosts_passes_isolated_on_isolated(self):
        self.flags(isolated_images=['isolated'], isolated_hosts=['isolated'])
        filt_cls = self.class_map['IsolatedHostsFilter']()
        filter_properties = {
            'request_spec': {
                'instance_properties': {'image_ref': 'isolated'}
            }
        }
        host = fakes.FakeHostState('isolated', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_isolated_hosts_passes_non_isolated_on_non_isolated(self):
        self.flags(isolated_images=['isolated'], isolated_hosts=['isolated'])
        filt_cls = self.class_map['IsolatedHostsFilter']()
        filter_properties = {
            'request_spec': {
                'instance_properties': {'image_ref': 'non-isolated'}
            }
        }
        host = fakes.FakeHostState('non-isolated', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_passes(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                           'scheduler_hints': {'query': self.json_query}}
        capabilities = {'enabled': True}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024,
                 'free_disk_mb': 200 * 1024,
                 'capabilities': capabilities})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_passes_with_no_query(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0}}
        capabilities = {'enabled': True}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 0,
                 'free_disk_mb': 0,
                 'capabilities': capabilities})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_fails_on_memory(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                           'scheduler_hints': {'query': self.json_query}}
        capabilities = {'enabled': True}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1023,
                 'free_disk_mb': 200 * 1024,
                 'capabilities': capabilities})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_fails_on_disk(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                           'scheduler_hints': {'query': self.json_query}}
        capabilities = {'enabled': True}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024,
                 'free_disk_mb': (200 * 1024) - 1,
                 'capabilities': capabilities})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_fails_on_caps_disabled(self):
        filt_cls = self.class_map['JsonFilter']()
        json_query = jsonutils.dumps(
                ['and', ['>=', '$free_ram_mb', 1024],
                        ['>=', '$free_disk_mb', 200 * 1024],
                        '$capabilities.enabled'])
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                           'scheduler_hints': {'query': json_query}}
        capabilities = {'enabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024,
                 'free_disk_mb': 200 * 1024,
                 'capabilities': capabilities})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_fails_on_service_disabled(self):
        filt_cls = self.class_map['JsonFilter']()
        json_query = jsonutils.dumps(
                ['and', ['>=', '$free_ram_mb', 1024],
                        ['>=', '$free_disk_mb', 200 * 1024],
                        ['not', '$service.disabled']])
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'local_gb': 200},
                           'scheduler_hints': {'query': json_query}}
        capabilities = {'enabled': True}
        service = {'disabled': True}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 1024,
                 'free_disk_mb': 200 * 1024,
                 'capabilities': capabilities})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_happy_day(self):
        """Test json filter more thoroughly"""
        filt_cls = self.class_map['JsonFilter']()
        raw = ['and',
                  '$capabilities.enabled',
                  ['=', '$capabilities.opt1', 'match'],
                  ['or',
                      ['and',
                          ['<', '$free_ram_mb', 30],
                          ['<', '$free_disk_mb', 300]],
                      ['and',
                          ['>', '$free_ram_mb', 30],
                          ['>', '$free_disk_mb', 300]]]]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }

        # Passes
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 10,
                 'free_disk_mb': 200,
                 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

        # Passes
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 40,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

        # Fails due to capabilities being disabled
        capabilities = {'enabled': False, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'instance_type',
                {'free_ram_mb': 40,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        # Fails due to being exact memory/disk we don't want
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 30,
                 'free_disk_mb': 300,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        # Fails due to memory lower but disk higher
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 20,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        # Fails due to capabilities 'opt1' not equal
        capabilities = {'enabled': True, 'opt1': 'no-match'}
        service = {'enabled': True}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': 20,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_basic_operators(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeHostState('host1', 'compute',
                {'capabilities': {'enabled': True}})
        # (operator, arguments, expected_result)
        ops_to_test = [
                    ['=', [1, 1], True],
                    ['=', [1, 2], False],
                    ['<', [1, 2], True],
                    ['<', [1, 1], False],
                    ['<', [2, 1], False],
                    ['>', [2, 1], True],
                    ['>', [2, 2], False],
                    ['>', [2, 3], False],
                    ['<=', [1, 2], True],
                    ['<=', [1, 1], True],
                    ['<=', [2, 1], False],
                    ['>=', [2, 1], True],
                    ['>=', [2, 2], True],
                    ['>=', [2, 3], False],
                    ['in', [1, 1], True],
                    ['in', [1, 1, 2, 3], True],
                    ['in', [4, 1, 2, 3], False],
                    ['not', [True], False],
                    ['not', [False], True],
                    ['or', [True, False], True],
                    ['or', [False, False], False],
                    ['and', [True, True], True],
                    ['and', [False, False], False],
                    ['and', [True, False], False],
                    # Nested ((True or False) and (2 > 1)) == Passes
                    ['and', [['or', True, False], ['>', 2, 1]], True]]

        for (op, args, expected) in ops_to_test:
            raw = [op] + args
            filter_properties = {
                'scheduler_hints': {
                    'query': jsonutils.dumps(raw),
                },
            }
            self.assertEqual(expected,
                    filt_cls.host_passes(host, filter_properties))

        # This results in [False, True, False, True] and if any are True
        # then it passes...
        raw = ['not', True, False, True, False]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

        # This results in [False, False, False] and if any are True
        # then it passes...which this doesn't
        raw = ['not', True, True, True]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_unknown_operator_raises(self):
        filt_cls = self.class_map['JsonFilter']()
        raw = ['!=', 1, 2]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        host = fakes.FakeHostState('host1', 'compute',
                {'capabilities': {'enabled': True}})
        self.assertRaises(KeyError,
                filt_cls.host_passes, host, filter_properties)

    def test_json_filter_empty_filters_pass(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeHostState('host1', 'compute',
                {'capabilities': {'enabled': True}})

        raw = []
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        raw = {}
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_invalid_num_arguments_fails(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeHostState('host1', 'compute',
                {'capabilities': {'enabled': True}})

        raw = ['>', ['and', ['or', ['not', ['<', ['>=', ['<=', ['in', ]]]]]]]]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        raw = ['>', 1]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_unknown_variable_ignored(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeHostState('host1', 'compute',
                {'capabilities': {'enabled': True}})

        raw = ['=', '$........', 1, 1]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

        raw = ['=', '$foo', 2, 2]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_default_passes(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_trusted_and_trusted_passes(self):
        global DATA
        DATA = '{"hosts":[{"host_name":"host1","trust_lvl":"trusted"}]}'
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trusted_host': 'trusted'}
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_trusted_and_untrusted_fails(self):
        global DATA
        DATA = '{"hosts":[{"host_name":"host1","trust_lvl":"untrusted"}]}'
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trusted_host': 'trusted'}
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_untrusted_and_trusted_fails(self):
        global DATA
        DATA = '{"hosts":[{"host_name":"host1","trust_lvl":"trusted"}]}'
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trusted_host': 'untrusted'}
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_untrusted_and_untrusted_passes(self):
        global DATA
        DATA = '{"hosts":[{"host_name":"host1","trust_lvl":"untrusted"}]}'
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trusted_host': 'untrusted'}
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_core_filter_passes(self):
        filt_cls = self.class_map['CoreFilter']()
        filter_properties = {'instance_type': {'vcpus': 1}}
        self.flags(cpu_allocation_ratio=2)
        host = fakes.FakeHostState('host1', 'compute',
                {'vcpus_total': 4, 'vcpus_used': 7})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_core_filter_fails_safe(self):
        filt_cls = self.class_map['CoreFilter']()
        filter_properties = {'instance_type': {'vcpus': 1}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_core_filter_fails(self):
        filt_cls = self.class_map['CoreFilter']()
        filter_properties = {'instance_type': {'vcpus': 1}}
        self.flags(cpu_allocation_ratio=2)
        host = fakes.FakeHostState('host1', 'compute',
                {'vcpus_total': 4, 'vcpus_used': 8})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

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
        host = fakes.FakeHostState('host1', 'compute', {'service': service})
        self.assertTrue(filt_cls.host_passes(host, request))

    def test_availability_zone_filter_different(self):
        filt_cls = self.class_map['AvailabilityZoneFilter']()
        service = {'availability_zone': 'nova'}
        request = self._make_zone_request('bad')
        host = fakes.FakeHostState('host1', 'compute', {'service': service})
        self.assertFalse(filt_cls.host_passes(host, request))

    def test_arch_filter_same(self):
        permitted_instances = ['x86_64']
        filt_cls = self.class_map['ArchFilter']()
        filter_properties = {
            'request_spec': {
                'instance_properties': {'architecture': 'x86_64'}
            }
        }
        capabilities = {'enabled': True,
                            'cpu_info': {
                                'permitted_instance_types': permitted_instances
                            }
                        }
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
            {'capabilities': capabilities, 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_arch_filter_different(self):
        permitted_instances = ['arm']
        filt_cls = self.class_map['ArchFilter']()
        filter_properties = {
            'request_spec': {
                    'instance_properties': {'architecture': 'x86_64'}
                }
            }
        capabilities = {'enabled': True,
                            'cpu_info': {
                                'permitted_instance_types': permitted_instances
                            }
                        }
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
            {'capabilities': capabilities, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_arch_filter_without_permitted_instances(self):
        permitted_instances = []
        filt_cls = self.class_map['ArchFilter']()
        filter_properties = {
             'request_spec': {
                'instance_properties': {'architecture': 'x86_64'}
            }
        }
        capabilities = {'enabled': True,
                            'cpu_info': {
                                'permitted_instance_types': permitted_instances
                            }
                        }
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'compute',
            {'capabilities': capabilities, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_retry_filter_disabled(self):
        """Test case where retry/re-scheduling is disabled"""
        filt_cls = self.class_map['RetryFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        filter_properties = {}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_retry_filter_pass(self):
        """Host not previously tried"""
        filt_cls = self.class_map['RetryFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        retry = dict(num_attempts=1, hosts=['host2', 'host3'])
        filter_properties = dict(retry=retry)
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_retry_filter_fail(self):
        """Host was already tried"""
        filt_cls = self.class_map['RetryFilter']()
        host = fakes.FakeHostState('host1', 'compute', {})
        retry = dict(num_attempts=1, hosts=['host3', 'host1'])
        filter_properties = dict(retry=retry)
        self.assertFalse(filt_cls.host_passes(host, filter_properties))
