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

import httplib

from oslo.config import cfg
import stubout

from nova import context
from nova import db
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova.pci import pci_stats
from nova.scheduler import filters
from nova.scheduler.filters import extra_specs_ops
from nova.scheduler.filters import trusted_filter
from nova import servicegroup
from nova import test
from nova.tests.scheduler import fakes
from nova import utils

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')


class TestFilter(filters.BaseHostFilter):
    pass


class TestBogusFilter(object):
    """Class that doesn't inherit from BaseHostFilter."""
    pass


class ExtraSpecsOpsTestCase(test.NoDBTestCase):
    def _do_extra_specs_ops_test(self, value, req, matches):
        assertion = self.assertTrue if matches else self.assertFalse
        assertion(extra_specs_ops.match(value, req))

    def test_extra_specs_matches_simple(self):
        self._do_extra_specs_ops_test(
            value='1',
            req='1',
            matches=True)

    def test_extra_specs_fails_simple(self):
        self._do_extra_specs_ops_test(
            value='',
            req='1',
            matches=False)

    def test_extra_specs_fails_simple2(self):
        self._do_extra_specs_ops_test(
            value='3',
            req='1',
            matches=False)

    def test_extra_specs_fails_simple3(self):
        self._do_extra_specs_ops_test(
            value='222',
            req='2',
            matches=False)

    def test_extra_specs_fails_with_bogus_ops(self):
        self._do_extra_specs_ops_test(
            value='4',
            req='> 2',
            matches=False)

    def test_extra_specs_matches_with_op_eq(self):
        self._do_extra_specs_ops_test(
            value='123',
            req='= 123',
            matches=True)

    def test_extra_specs_matches_with_op_eq2(self):
        self._do_extra_specs_ops_test(
            value='124',
            req='= 123',
            matches=True)

    def test_extra_specs_fails_with_op_eq(self):
        self._do_extra_specs_ops_test(
            value='34',
            req='= 234',
            matches=False)

    def test_extra_specs_fails_with_op_eq3(self):
        self._do_extra_specs_ops_test(
            value='34',
            req='=',
            matches=False)

    def test_extra_specs_matches_with_op_seq(self):
        self._do_extra_specs_ops_test(
            value='123',
            req='s== 123',
            matches=True)

    def test_extra_specs_fails_with_op_seq(self):
        self._do_extra_specs_ops_test(
            value='1234',
            req='s== 123',
            matches=False)

    def test_extra_specs_matches_with_op_sneq(self):
        self._do_extra_specs_ops_test(
            value='1234',
            req='s!= 123',
            matches=True)

    def test_extra_specs_fails_with_op_sneq(self):
        self._do_extra_specs_ops_test(
            value='123',
            req='s!= 123',
            matches=False)

    def test_extra_specs_fails_with_op_sge(self):
        self._do_extra_specs_ops_test(
            value='1000',
            req='s>= 234',
            matches=False)

    def test_extra_specs_fails_with_op_sle(self):
        self._do_extra_specs_ops_test(
            value='1234',
            req='s<= 1000',
            matches=False)

    def test_extra_specs_fails_with_op_sl(self):
        self._do_extra_specs_ops_test(
            value='2',
            req='s< 12',
            matches=False)

    def test_extra_specs_fails_with_op_sg(self):
        self._do_extra_specs_ops_test(
            value='12',
            req='s> 2',
            matches=False)

    def test_extra_specs_matches_with_op_in(self):
        self._do_extra_specs_ops_test(
            value='12311321',
            req='<in> 11',
            matches=True)

    def test_extra_specs_matches_with_op_in2(self):
        self._do_extra_specs_ops_test(
            value='12311321',
            req='<in> 12311321',
            matches=True)

    def test_extra_specs_matches_with_op_in3(self):
        self._do_extra_specs_ops_test(
            value='12311321',
            req='<in> 12311321 <in>',
            matches=True)

    def test_extra_specs_fails_with_op_in(self):
        self._do_extra_specs_ops_test(
            value='12310321',
            req='<in> 11',
            matches=False)

    def test_extra_specs_fails_with_op_in2(self):
        self._do_extra_specs_ops_test(
            value='12310321',
            req='<in> 11 <in>',
            matches=False)

    def test_extra_specs_matches_with_op_or(self):
        self._do_extra_specs_ops_test(
            value='12',
            req='<or> 11 <or> 12',
            matches=True)

    def test_extra_specs_matches_with_op_or2(self):
        self._do_extra_specs_ops_test(
            value='12',
            req='<or> 11 <or> 12 <or>',
            matches=True)

    def test_extra_specs_fails_with_op_or(self):
        self._do_extra_specs_ops_test(
            value='13',
            req='<or> 11 <or> 12',
            matches=False)

    def test_extra_specs_fails_with_op_or2(self):
        self._do_extra_specs_ops_test(
            value='13',
            req='<or> 11 <or> 12 <or>',
            matches=False)

    def test_extra_specs_matches_with_op_le(self):
        self._do_extra_specs_ops_test(
            value='2',
            req='<= 10',
            matches=True)

    def test_extra_specs_fails_with_op_le(self):
        self._do_extra_specs_ops_test(
            value='3',
            req='<= 2',
            matches=False)

    def test_extra_specs_matches_with_op_ge(self):
        self._do_extra_specs_ops_test(
            value='3',
            req='>= 1',
            matches=True)

    def test_extra_specs_fails_with_op_ge(self):
        self._do_extra_specs_ops_test(
            value='2',
            req='>= 3',
            matches=False)


class HostFiltersTestCase(test.NoDBTestCase):
    """Test case for host filters."""
    # FIXME(sirp): These tests still require DB access until we can separate
    # the testing of the DB API code from the host-filter code.
    USES_DB = True

    def fake_oat_request(self, *args, **kwargs):
        """Stubs out the response from OAT service."""
        self.oat_attested = True
        return httplib.OK, self.oat_data

    def setUp(self):
        super(HostFiltersTestCase, self).setUp()
        self.oat_data = ''
        self.oat_attested = False
        self.stubs = stubout.StubOutForTesting()
        self.stubs.Set(trusted_filter.AttestationService, '_request',
                self.fake_oat_request)
        self.context = context.RequestContext('fake', 'fake')
        self.json_query = jsonutils.dumps(
                ['and', ['>=', '$free_ram_mb', 1024],
                        ['>=', '$free_disk_mb', 200 * 1024]])
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

    def test_affinity_different_filter_passes(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'different_host': [instance_uuid], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_no_list_passes(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'different_host': instance_uuid}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_fails(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'different_host': [instance_uuid], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_handles_none(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['DifferentHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid
        db.instance_destroy(self.context, instance_uuid)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'different_host': [instance_uuid], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_no_list_passes(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'same_host': instance_uuid}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_passes(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'same_host': [instance_uuid], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_fails(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host2'})
        instance_uuid = instance.uuid

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'same_host': [instance_uuid], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_handles_none(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['SameHostFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        instance = fakes.FakeInstance(context=self.context,
                                         params={'host': 'host1'})
        instance_uuid = instance.uuid
        db.instance_destroy(self.context, instance_uuid)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                'same_host': [instance_uuid], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_passes(self):
        filt_cls = self.class_map['SimpleCIDRAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        host.host_ip = '10.8.1.1'

        affinity_ip = "10.8.1.100"

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'cidr': '/24',
                                 'build_near_host_ip': affinity_ip}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_fails(self):
        filt_cls = self.class_map['SimpleCIDRAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        host.host_ip = '10.8.1.1'

        affinity_ip = "10.8.1.100"

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
                                 'cidr': '/32',
                                 'build_near_host_ip': affinity_ip}}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_simple_cidr_filter_handles_none(self):
        filt_cls = self.class_map['SimpleCIDRAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})

        affinity_ip = CONF.my_ip.split('.')[0:3]
        affinity_ip.append('100')
        affinity_ip = str.join('.', affinity_ip)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

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
        #True since no aggregates
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        #True since type matches aggregate, metadata
        self._create_aggregate_with_host(name='fake_aggregate',
                hosts=['fake_host'], metadata={'instance_type': 'fake1'})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        #False since type matches aggregate, metadata
        self.assertFalse(filt_cls.host_passes(host, filter2_properties))

    def test_ram_filter_fails_on_memory(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['RamFilter']()
        self.flags(ram_allocation_ratio=1.0)
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1023, 'total_usable_ram_mb': 1024,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_ram_filter_passes(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['RamFilter']()
        self.flags(ram_allocation_ratio=1.0)
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'total_usable_ram_mb': 1024,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_ram_filter_oversubscribe(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['RamFilter']()
        self.flags(ram_allocation_ratio=2.0)
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': -1024, 'total_usable_ram_mb': 2048,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(2048 * 2.0, host.limits['memory_mb'])

    def test_aggregate_ram_filter_value_error(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateRamFilter']()
        self.flags(ram_allocation_ratio=1.0)
        filter_properties = {'context': self.context,
                             'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'total_usable_ram_mb': 1024,
                 'service': service})
        self._create_aggregate_with_host(name='fake_aggregate',
                hosts=['host1'],
                metadata={'ram_allocation_ratio': 'XXX'})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(1024 * 1.0, host.limits['memory_mb'])

    def test_aggregate_ram_filter_default_value(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateRamFilter']()
        self.flags(ram_allocation_ratio=1.0)
        filter_properties = {'context': self.context,
                             'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1023, 'total_usable_ram_mb': 1024,
                 'service': service})
        # False: fallback to default flag w/o aggregates
        self.assertFalse(filt_cls.host_passes(host, filter_properties))
        self._create_aggregate_with_host(name='fake_aggregate',
                hosts=['host1'],
                metadata={'ram_allocation_ratio': '2.0'})
        # True: use ratio from aggregates
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(1024 * 2.0, host.limits['memory_mb'])

    def test_aggregate_ram_filter_conflict_values(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateRamFilter']()
        self.flags(ram_allocation_ratio=1.0)
        filter_properties = {'context': self.context,
                             'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1023, 'total_usable_ram_mb': 1024,
                 'service': service})
        self._create_aggregate_with_host(name='fake_aggregate1',
                hosts=['host1'],
                metadata={'ram_allocation_ratio': '1.5'})
        self._create_aggregate_with_host(name='fake_aggregate2',
                hosts=['host1'],
                metadata={'ram_allocation_ratio': '2.0'})
        # use the minimum ratio from aggregates
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(1024 * 1.5, host.limits['memory_mb'])

    def test_disk_filter_passes(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['DiskFilter']()
        self.flags(disk_allocation_ratio=1.0)
        filter_properties = {'instance_type': {'root_gb': 1,
            'ephemeral_gb': 1, 'swap': 512}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 13,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_disk_filter_fails(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['DiskFilter']()
        self.flags(disk_allocation_ratio=1.0)
        filter_properties = {'instance_type': {'root_gb': 10,
            'ephemeral_gb': 1, 'swap': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 13,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_disk_filter_oversubscribe(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['DiskFilter']()
        self.flags(disk_allocation_ratio=10.0)
        filter_properties = {'instance_type': {'root_gb': 100,
            'ephemeral_gb': 18, 'swap': 1024}}
        service = {'disabled': False}
        # 1GB used... so 119GB allowed...
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 12,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(12 * 10.0, host.limits['disk_gb'])

    def test_disk_filter_oversubscribe_fail(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['DiskFilter']()
        self.flags(disk_allocation_ratio=10.0)
        filter_properties = {'instance_type': {'root_gb': 100,
            'ephemeral_gb': 19, 'swap': 1024}}
        service = {'disabled': False}
        # 1GB used... so 119GB allowed...
        host = fakes.FakeHostState('host1', 'node1',
                {'free_disk_mb': 11 * 1024, 'total_usable_disk_gb': 12,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_fails_on_service_disabled(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': True}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_fails_on_service_down(self):
        self._stub_service_is_up(False)
        filt_cls = self.class_map['ComputeFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024}}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024, 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_passes_same_inst_props_and_version(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'_architecture': 'x86_64',
                                    'hypervisor_type': 'kvm',
                                    'vm_mode': 'hvm',
                                    'hypervisor_version_requires': '>=6.0,<6.2'
        }}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances': [('x86_64', 'kvm', 'hvm')],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_different_inst_props(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'architecture': 'arm',
                                    'hypervisor_type': 'qemu',
                                    'vm_mode': 'hvm'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances': [('x86_64', 'kvm', 'hvm')],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_different_hyper_version(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'architecture': 'x86_64',
                                    'hypervisor_type': 'kvm',
                                    'vm_mode': 'hvm',
                                    'hypervisor_version_requires': '>=6.2'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'enabled': True,
                        'supported_instances': [('x86_64', 'kvm', 'hvm')],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_passes_partial_inst_props(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'architecture': 'x86_64',
                                    'vm_mode': 'hvm'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances': [('x86_64', 'kvm', 'hvm')],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_partial_inst_props(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'architecture': 'x86_64',
                                    'vm_mode': 'hvm'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances': [('x86_64', 'xen', 'xen')],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_passes_without_inst_props(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        filter_properties = {'request_spec': {}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'supported_instances': [('x86_64', 'kvm', 'hvm')],
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_without_host_props(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'architecture': 'x86_64',
                                    'hypervisor_type': 'kvm',
                                    'vm_mode': 'hvm'}}
        filter_properties = {'request_spec': {'image': img_props}}
        hypervisor_version = utils.convert_version_to_int('6.0.0')
        capabilities = {'enabled': True,
                        'hypervisor_version': hypervisor_version}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_passes_without_hyper_version(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'architecture': 'x86_64',
                                    'hypervisor_type': 'kvm',
                                    'vm_mode': 'hvm',
                                    'hypervisor_version_requires': '>=6.0'}}
        filter_properties = {'request_spec': {'image': img_props}}
        capabilities = {'enabled': True,
                        'supported_instances': [('x86_64', 'kvm', 'hvm')]}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_image_properties_filter_fails_with_unsupported_hyper_ver(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ImagePropertiesFilter']()
        img_props = {'properties': {'architecture': 'x86_64',
                                    'hypervisor_type': 'kvm',
                                    'vm_mode': 'hvm',
                                    'hypervisor_version_requires': '>=6.0'}}
        filter_properties = {'request_spec': {'image': img_props}}
        capabilities = {'enabled': True,
                        'supported_instances': [('x86_64', 'kvm', 'hvm')],
                        'hypervisor_version': 5000}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def _do_test_compute_filter_extra_specs(self, ecaps, especs, passes):
        """In real Openstack runtime environment,compute capabilities
        value may be number, so we should use number to do unit test.
        """
        self._stub_service_is_up(True)
        filt_cls = self.class_map['ComputeCapabilitiesFilter']()
        capabilities = {}
        capabilities.update(ecaps)
        service = {'disabled': False}
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'extra_specs': especs}}
        host_state = {'free_ram_mb': 1024, 'service': service}
        host_state.update(capabilities)
        host = fakes.FakeHostState('host1', 'node1', host_state)
        assertion = self.assertTrue if passes else self.assertFalse
        assertion(filt_cls.host_passes(host, filter_properties))

    def test_compute_filter_passes_extra_specs_simple(self):
        self._do_test_compute_filter_extra_specs(
                ecaps={'stats': {'opt1': 1, 'opt2': 2}},
            especs={'opt1': '1', 'opt2': '2', 'trust:trusted_host': 'true'},
            passes=True)

    def test_compute_filter_fails_extra_specs_simple(self):
        self._do_test_compute_filter_extra_specs(
                ecaps={'stats': {'opt1': 1, 'opt2': 2}},
            especs={'opt1': '1', 'opt2': '222', 'trust:trusted_host': 'true'},
            passes=False)

    def test_compute_filter_pass_extra_specs_simple_with_scope(self):
        self._do_test_compute_filter_extra_specs(
                ecaps={'stats': {'opt1': 1, 'opt2': 2}},
            especs={'capabilities:opt1': '1',
                    'trust:trusted_host': 'true'},
            passes=True)

    def test_compute_filter_pass_extra_specs_same_as_scope(self):
        # Make sure this still works even if the key is the same as the scope
        self._do_test_compute_filter_extra_specs(
            ecaps={'capabilities': 1},
            especs={'capabilities': '1'},
            passes=True)

    def test_compute_filter_extra_specs_simple_with_wrong_scope(self):
        self._do_test_compute_filter_extra_specs(
            ecaps={'opt1': 1, 'opt2': 2},
            especs={'wrong_scope:opt1': '1',
                    'trust:trusted_host': 'true'},
            passes=True)

    def test_compute_filter_extra_specs_pass_multi_level_with_scope(self):
        self._do_test_compute_filter_extra_specs(
                ecaps={'stats': {'opt1': {'a': 1, 'b': {'aa': 2}}, 'opt2': 2}},
            especs={'opt1:a': '1', 'capabilities:opt1:b:aa': '2',
                    'trust:trusted_host': 'true'},
            passes=True)

    def test_aggregate_filter_passes_no_extra_specs(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateInstanceExtraSpecsFilter']()
        capabilities = {'opt1': 1, 'opt2': 2}

        filter_properties = {'context': self.context, 'instance_type':
                {'memory_mb': 1024}}
        host = fakes.FakeHostState('host1', 'node1', capabilities)
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

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

    def _do_test_aggregate_filter_extra_specs(self, emeta, especs, passes):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateInstanceExtraSpecsFilter']()
        self._create_aggregate_with_host(name='fake2', metadata=emeta)
        filter_properties = {'context': self.context,
            'instance_type': {'memory_mb': 1024, 'extra_specs': especs}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'free_ram_mb': 1024})
        assertion = self.assertTrue if passes else self.assertFalse
        assertion(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_filter_fails_extra_specs_deleted_host(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateInstanceExtraSpecsFilter']()
        extra_specs = {'opt1': 's== 1', 'opt2': 's== 2',
                       'trust:trusted_host': 'true'}
        self._create_aggregate_with_host(metadata={'opt1': '1'})
        agg2 = self._create_aggregate_with_host(name='fake2',
                metadata={'opt2': '2'})
        filter_properties = {'context': self.context, 'instance_type':
                {'memory_mb': 1024, 'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'node1',
                                   {'free_ram_mb': 1024})
        db.aggregate_host_delete(self.context.elevated(), agg2['id'], 'host1')
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_filter_passes_extra_specs_simple(self):
        especs = {
            # Un-scoped extra spec
            'opt1': '1',
            # Scoped extra spec that applies to this filter
            'aggregate_instance_extra_specs:opt2': '2',
            # Scoped extra spec that does not apply to this filter
            'trust:trusted_host': 'true',
        }
        self._do_test_aggregate_filter_extra_specs(
                emeta={'opt1': '1', 'opt2': '2'}, especs=especs, passes=True)

    def test_aggregate_filter_passes_with_key_same_as_scope(self):
        especs = {
                # Un-scoped extra spec, make sure we don't blow up if it
                # happens to match our scope.
                'aggregate_instance_extra_specs': '1',
        }
        self._do_test_aggregate_filter_extra_specs(
                emeta={'aggregate_instance_extra_specs': '1'},
                especs=especs, passes=True)

    def test_aggregate_filter_fails_extra_specs_simple(self):
        self._do_test_aggregate_filter_extra_specs(
            emeta={'opt1': '1', 'opt2': '2'},
            especs={'opt1': '1', 'opt2': '222',
                    'trust:trusted_host': 'true'},
            passes=False)

    def _do_test_isolated_hosts(self, host_in_list, image_in_list,
                            set_flags=True,
                            restrict_isolated_hosts_to_isolated_images=True):
        if set_flags:
            self.flags(isolated_images=['isolated_image'],
                       isolated_hosts=['isolated_host'],
                       restrict_isolated_hosts_to_isolated_images=
                       restrict_isolated_hosts_to_isolated_images)
        host_name = 'isolated_host' if host_in_list else 'free_host'
        image_ref = 'isolated_image' if image_in_list else 'free_image'
        filter_properties = {
            'request_spec': {
                'instance_properties': {'image_ref': image_ref}
            }
        }
        filt_cls = self.class_map['IsolatedHostsFilter']()
        host = fakes.FakeHostState(host_name, 'node', {})
        return filt_cls.host_passes(host, filter_properties)

    def test_isolated_hosts_fails_isolated_on_non_isolated(self):
        self.assertFalse(self._do_test_isolated_hosts(False, True))

    def test_isolated_hosts_fails_non_isolated_on_isolated(self):
        self.assertFalse(self._do_test_isolated_hosts(True, False))

    def test_isolated_hosts_passes_isolated_on_isolated(self):
        self.assertTrue(self._do_test_isolated_hosts(True, True))

    def test_isolated_hosts_passes_non_isolated_on_non_isolated(self):
        self.assertTrue(self._do_test_isolated_hosts(False, False))

    def test_isolated_hosts_no_config(self):
        # If there are no hosts nor isolated images in the config, it should
        # not filter at all. This is the default config.
        self.assertTrue(self._do_test_isolated_hosts(False, True, False))
        self.assertTrue(self._do_test_isolated_hosts(True, False, False))
        self.assertTrue(self._do_test_isolated_hosts(True, True, False))
        self.assertTrue(self._do_test_isolated_hosts(False, False, False))

    def test_isolated_hosts_no_hosts_config(self):
        self.flags(isolated_images=['isolated_image'])
        # If there are no hosts in the config, it should only filter out
        # images that are listed
        self.assertFalse(self._do_test_isolated_hosts(False, True, False))
        self.assertTrue(self._do_test_isolated_hosts(True, False, False))
        self.assertFalse(self._do_test_isolated_hosts(True, True, False))
        self.assertTrue(self._do_test_isolated_hosts(False, False, False))

    def test_isolated_hosts_no_images_config(self):
        self.flags(isolated_hosts=['isolated_host'])
        # If there are no images in the config, it should only filter out
        # isolated_hosts
        self.assertTrue(self._do_test_isolated_hosts(False, True, False))
        self.assertFalse(self._do_test_isolated_hosts(True, False, False))
        self.assertFalse(self._do_test_isolated_hosts(True, True, False))
        self.assertTrue(self._do_test_isolated_hosts(False, False, False))

    def test_isolated_hosts_less_restrictive(self):
        # If there are isolated hosts and non isolated images
        self.assertTrue(self._do_test_isolated_hosts(True, False, True, False))
        # If there are isolated hosts and isolated images
        self.assertTrue(self._do_test_isolated_hosts(True, True, True, False))
        # If there are non isolated hosts and non isolated images
        self.assertTrue(self._do_test_isolated_hosts(False, False, True,
                                                     False))
        # If there are non isolated hosts and isolated images
        self.assertFalse(self._do_test_isolated_hosts(False, True, True,
                                                      False))

    def test_json_filter_passes(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                           'scheduler_hints': {'query': self.json_query}}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024,
                 'free_disk_mb': 200 * 1024})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_passes_with_no_query(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0}}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 0,
                 'free_disk_mb': 0})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_fails_on_memory(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                           'scheduler_hints': {'query': self.json_query}}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1023,
                 'free_disk_mb': 200 * 1024})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_fails_on_disk(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'instance_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                           'scheduler_hints': {'query': self.json_query}}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024,
                 'free_disk_mb': (200 * 1024) - 1})
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
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 1024,
                 'free_disk_mb': 200 * 1024})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_happy_day(self):
        # Test json filter more thoroughly.
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
        capabilities = {'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 10,
                 'free_disk_mb': 200,
                 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

        # Passes
        capabilities = {'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 40,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

        # Fails due to capabilities being disabled
        capabilities = {'enabled': False, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 40,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        # Fails due to being exact memory/disk we don't want
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 30,
                 'free_disk_mb': 300,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        # Fails due to memory lower but disk higher
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 20,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

        # Fails due to capabilities 'opt1' not equal
        capabilities = {'enabled': True, 'opt1': 'no-match'}
        service = {'enabled': True}
        host = fakes.FakeHostState('host1', 'node1',
                {'free_ram_mb': 20,
                 'free_disk_mb': 400,
                 'capabilities': capabilities,
                 'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_json_filter_basic_operators(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                {})
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
        host = fakes.FakeHostState('host1', 'node1',
                {})
        self.assertRaises(KeyError,
                filt_cls.host_passes, host, filter_properties)

    def test_json_filter_empty_filters_pass(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeHostState('host1', 'node1',
                {})

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
        host = fakes.FakeHostState('host1', 'node1',
                {})

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
        host = fakes.FakeHostState('host1', 'node1',
                {})

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
        filter_properties = {'context': self.context.elevated(),
                             'instance_type': {'memory_mb': 1024}}
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_trusted_and_trusted_passes(self):
        self.oat_data = {"hosts": [{"host_name": "host1",
                                   "trust_lvl": "trusted",
                                   "vtime": timeutils.isotime()}]}
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trust:trusted_host': 'trusted'}
        filter_properties = {'context': self.context.elevated(),
                             'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_trusted_and_untrusted_fails(self):
        self.oat_data = {"hosts": [{"host_name": "host1",
                                    "trust_lvl": "untrusted",
                                    "vtime": timeutils.isotime()}]}
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trust:trusted_host': 'trusted'}
        filter_properties = {'context': self.context.elevated(),
                             'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_untrusted_and_trusted_fails(self):
        self.oat_data = {"hosts": [{"host_name": "host1",
                                    "trust_lvl": "trusted",
                                    "vtime": timeutils.isotime()}]}
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trust:trusted_host': 'untrusted'}
        filter_properties = {'context': self.context.elevated(),
                             'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_untrusted_and_untrusted_passes(self):
        self.oat_data = {"hosts": [{"host_name": "host1",
                                    "trust_lvl": "untrusted",
                                    "vtime": timeutils.isotime()}]}
        self._stub_service_is_up(True)
        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trust:trusted_host': 'untrusted'}
        filter_properties = {'context': self.context.elevated(),
                             'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'node1', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_trusted_filter_update_cache(self):
        self.oat_data = {"hosts": [{"host_name":
                                    "host1", "trust_lvl": "untrusted",
                                    "vtime": timeutils.isotime()}]}

        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trust:trusted_host': 'untrusted'}
        filter_properties = {'context': self.context.elevated(),
                             'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'node1', {})

        filt_cls.host_passes(host, filter_properties)     # Fill the caches

        self.oat_attested = False
        filt_cls.host_passes(host, filter_properties)
        self.assertFalse(self.oat_attested)

        self.oat_attested = False

        timeutils.set_time_override(timeutils.utcnow())
        timeutils.advance_time_seconds(
            CONF.trusted_computing.attestation_auth_timeout + 80)
        filt_cls.host_passes(host, filter_properties)
        self.assertTrue(self.oat_attested)

        timeutils.clear_time_override()

    def test_trusted_filter_update_cache_timezone(self):
        self.oat_data = {"hosts": [{"host_name": "host1",
                                    "trust_lvl": "untrusted",
                                    "vtime": "2012-09-09T05:10:40-04:00"}]}

        filt_cls = self.class_map['TrustedFilter']()
        extra_specs = {'trust:trusted_host': 'untrusted'}
        filter_properties = {'context': self.context.elevated(),
                             'instance_type': {'memory_mb': 1024,
                                               'extra_specs': extra_specs}}
        host = fakes.FakeHostState('host1', 'node1', {})

        timeutils.set_time_override(
            timeutils.normalize_time(
                timeutils.parse_isotime("2012-09-09T09:10:40Z")))

        filt_cls.host_passes(host, filter_properties)     # Fill the caches

        self.oat_attested = False
        filt_cls.host_passes(host, filter_properties)
        self.assertFalse(self.oat_attested)

        self.oat_attested = False
        timeutils.advance_time_seconds(
            CONF.trusted_computing.attestation_auth_timeout - 10)
        filt_cls.host_passes(host, filter_properties)
        self.assertFalse(self.oat_attested)

        timeutils.clear_time_override()

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

    def test_group_anti_affinity_filter_passes(self):
        filt_cls = self.class_map['GroupAntiAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_hosts': []}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        filter_properties = {'group_hosts': ['host2']}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_group_anti_affinity_filter_fails(self):
        filt_cls = self.class_map['GroupAntiAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_hosts': ['host1']}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_group_affinity_filter_passes(self):
        filt_cls = self.class_map['GroupAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_hosts': ['host1']}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_group_affinity_filter_fails(self):
        filt_cls = self.class_map['GroupAffinityFilter']()
        host = fakes.FakeHostState('host1', 'node1', {})
        filter_properties = {'group_hosts': ['host2']}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_multi_tenancy_isolation_with_meta_passes(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateMultiTenancyIsolation']()
        aggr_meta = {'filter_tenant_id': 'my_tenantid'}
        self._create_aggregate_with_host(name='fake1', metadata=aggr_meta,
                                         hosts=['host1'])
        filter_properties = {'context': self.context,
                             'request_spec': {
                                 'instance_properties': {
                                     'project_id': 'my_tenantid'}}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_multi_tenancy_isolation_fails(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateMultiTenancyIsolation']()
        aggr_meta = {'filter_tenant_id': 'other_tenantid'}
        self._create_aggregate_with_host(name='fake1', metadata=aggr_meta,
                                         hosts=['host1'])
        filter_properties = {'context': self.context,
                             'request_spec': {
                                 'instance_properties': {
                                     'project_id': 'my_tenantid'}}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_aggregate_multi_tenancy_isolation_no_meta_passes(self):
        self._stub_service_is_up(True)
        filt_cls = self.class_map['AggregateMultiTenancyIsolation']()
        aggr_meta = {}
        self._create_aggregate_with_host(name='fake1', metadata=aggr_meta,
                                         hosts=['host1'])
        filter_properties = {'context': self.context,
                             'request_spec': {
                                 'instance_properties': {
                                     'project_id': 'my_tenantid'}}}
        host = fakes.FakeHostState('host1', 'compute', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def _fake_pci_support_requests(self, pci_requests):
        self.pci_requests = pci_requests
        return self.pci_request_result

    def test_pci_passthrough_pass(self):
        filt_cls = self.class_map['PciPassthroughFilter']()
        requests = [{'count': 1, 'spec': [{'vendor_id': '8086'}]}]
        filter_properties = {'pci_requests': requests}
        self.stubs.Set(pci_stats.PciDeviceStats, 'support_requests',
                       self._fake_pci_support_requests)
        host = fakes.FakeHostState(
            'host1', 'node1',
            attribute_dict={'pci_stats': pci_stats.PciDeviceStats()})
        self.pci_request_result = True
        self.assertTrue(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(self.pci_requests, requests)

    def test_pci_passthrough_fail(self):
        filt_cls = self.class_map['PciPassthroughFilter']()
        requests = [{'count': 1, 'spec': [{'vendor_id': '8086'}]}]
        filter_properties = {'pci_requests': requests}
        self.stubs.Set(pci_stats.PciDeviceStats, 'support_requests',
                       self._fake_pci_support_requests)
        host = fakes.FakeHostState(
            'host1', 'node1',
            attribute_dict={'pci_stats': pci_stats.PciDeviceStats()})
        self.pci_request_result = False
        self.assertFalse(filt_cls.host_passes(host, filter_properties))
        self.assertEqual(self.pci_requests, requests)

    def test_pci_passthrough_no_pci_request(self):
        filt_cls = self.class_map['PciPassthroughFilter']()
        filter_properties = {}
        host = fakes.FakeHostState('h1', 'n1', {})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_pci_passthrough_comopute_stats(self):
        filt_cls = self.class_map['PciPassthroughFilter']()
        requests = [{'count': 1, 'spec': [{'vendor_id': '8086'}]}]
        filter_properties = {'pci_requests': requests}
        self.stubs.Set(pci_stats.PciDeviceStats, 'support_requests',
                       self._fake_pci_support_requests)
        host = fakes.FakeHostState(
            'host1', 'node1',
            attribute_dict={})
        self.pci_request_result = True
        self.assertRaises(AttributeError, filt_cls.host_passes,
                          host, filter_properties)
