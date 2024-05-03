# Copyright (c) 2024 SAP SE
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
from unittest import mock

import ddt

from oslo_utils.fixture import uuidsentinel as uuids

from nova import objects
from nova.scheduler.filters import resize_vcpu_max_unit_filter
from nova import test
from nova.tests.unit.scheduler import fakes


@ddt.ddt
class TestResizeVcpuMaxUnitFilter(test.NoDBTestCase):
    def setUp(self):
        super(TestResizeVcpuMaxUnitFilter, self).setUp()
        self.filt_cls = (
            resize_vcpu_max_unit_filter.ResizeVcpuMaxUnitFilter())
        self._default_hints = dict(
            source_host=[fakes.COMPUTE_NODES[0].host]
        )

    @mock.patch('nova.scheduler.utils.is_non_vmware_spec', return_value=True)
    def test_passes_non_vmware(self, non_vmware_spec):
        hosts = [fakes.FakeHostState('host1', 'compute', {})]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx)

        self.assertEqual(hosts, self.filt_cls.filter_all(hosts, spec_obj))
        non_vmware_spec.assert_called_once_with(spec_obj)

    @mock.patch('nova.scheduler.utils.is_non_vmware_spec', return_value=False)
    @mock.patch('nova.scheduler.utils.request_is_resize', return_value=False)
    def test_passes_non_resize(self, is_resize, non_vmware_spec):
        hosts = [fakes.FakeHostState('host1', 'compute', {})]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx)

        self.assertEqual(hosts, self.filt_cls.filter_all(hosts, spec_obj))
        is_resize.assert_called_once_with(spec_obj)
        non_vmware_spec.assert_called_once_with(spec_obj)

    @ddt.data(4, 6)
    def test_passes_bigger_flavor(self, vcpus):
        hosts = [fakes.FakeHostState('host1', 'compute', {})]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            instance_uuid=uuids.instance,
            scheduler_hints=self._default_hints,
            flavor=objects.Flavor(vcpus=vcpus))

        flavor = objects.Flavor(vcpus=4)
        instance = objects.Instance(uuid=uuids.instance,
                                    flavor=flavor)

        admin_ctx = mock.sentinel.admin_context
        with test.nested(
                mock.patch('nova.objects.Instance.get_by_uuid',
                           return_value=instance),
                mock.patch('nova.scheduler.utils.is_non_vmware_spec',
                           return_value=False),
                mock.patch('nova.scheduler.utils.request_is_resize',
                           return_value=True),
                mock.patch(
                    'nova.objects.InstanceMapping.get_by_instance_uuid'),
                mock.patch('nova.context.target_cell'),
                mock.patch('nova.context.get_admin_context',
                           return_value=admin_ctx),
        ) as (get_by_uuid, non_vmware_spec, is_resize, inst_mapping,
              target_cell, get_context):
            inst_mapping.get_by_host.return_value.cell_mapping = \
                mock.sentinel.cell_mapping

            cell_ctxt = mock.sentinel.cell_ctxt
            target_cell.return_value.__enter__.return_value = cell_ctxt

            self.assertEqual(hosts, self.filt_cls.filter_all(hosts, spec_obj))
            get_by_uuid.assert_called_once_with(cell_ctxt, uuids.instance,
                                                expected_attrs=['flavor'])
            is_resize.assert_called_once_with(spec_obj)
            non_vmware_spec.assert_called_once_with(spec_obj)

    def test_filters_hosts(self):
        hosts = [
            fakes.FakeHostState('host1', 'compute',
                                {'stats': {'vcpus_max_unit': '2'}}),
            fakes.FakeHostState('host2', 'compute',
                                {'stats': {'vcpus_max_unit': '4'}}),
            fakes.FakeHostState('host3', 'compute',
                                {'stats': {'vcpus_max_unit': '6'}}),
            fakes.FakeHostState('host4', 'compute',
                                {'stats': {}})
        ]
        spec_obj = objects.RequestSpec(
            context=mock.sentinel.ctx,
            instance_uuid=uuids.instance,
            flavor=objects.Flavor(vcpus=2))

        flavor = objects.Flavor(vcpus=4)
        instance = objects.Instance(uuid=uuids.instance,
                                    flavor=flavor)

        admin_ctx = mock.sentinel.admin_context
        with test.nested(
                mock.patch('nova.objects.Instance.get_by_uuid',
                           return_value=instance),
                mock.patch('nova.scheduler.utils.is_non_vmware_spec',
                           return_value=False),
                mock.patch('nova.scheduler.utils.request_is_resize',
                           return_value=True),
                mock.patch(
                    'nova.objects.InstanceMapping.get_by_instance_uuid'),
                mock.patch('nova.context.target_cell'),
                mock.patch('nova.context.get_admin_context',
                           return_value=admin_ctx),
        ) as (get_by_uuid, non_vmware_spec, is_resize, inst_mapping,
              target_cell, get_context):
            inst_mapping.get_by_instance_uuid.return_value.cell_mapping = \
                mock.sentinel.cell_mapping

            cell_ctxt = mock.sentinel.cell_ctxt
            target_cell.return_value.__enter__.return_value = cell_ctxt

            results = [h.host for h in
                       self.filt_cls.filter_all(hosts, spec_obj)]
            self.assertEqual(['host2', 'host3'], results)

            get_by_uuid.assert_called_once_with(cell_ctxt, uuids.instance,
                                                expected_attrs=['flavor'])
            is_resize.assert_called_once_with(spec_obj)
            non_vmware_spec.assert_called_once_with(spec_obj)
