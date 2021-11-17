# Copyright (c) 2021 SAP SE
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

from oslo_serialization import jsonutils

from nova import exception
from nova import objects
from nova.objects.compute_node import ComputeNode
from nova.scheduler.filters import cpu_info_migration_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestCpuFlagsMigrationFilter(test.NoDBTestCase):
    SOURCE_NODE = fakes.COMPUTE_NODES[0]

    def setUp(self):
        super(TestCpuFlagsMigrationFilter, self).setUp()
        self.filter = cpu_info_migration_filter.CpuInfoMigrationFilter()
        self._default_scheduler_hints = dict(
            source_host=[self.SOURCE_NODE.host],
            source_node=[self.SOURCE_NODE.hypervisor_hostname],
        )

    @mock.patch('nova.context.get_admin_context')
    @mock.patch('nova.context.target_cell')
    @mock.patch.object(cpu_info_migration_filter, 'request_is_live_migrate')
    @mock.patch.object(ComputeNode, 'get_by_host_and_nodename')
    @mock.patch.object(cpu_info_migration_filter, 'HostMapping')
    def _test_filter_all(self,
            mock_host_mapping,
            mock_get_cn,
            mock_is_live_migrate,
            mock_target_cell,
            mock_get_admin_context,
            compute_node=None,
            is_live_migrate=True,
            hosts=None,
            filtered_hosts=None,
            **scheduler_hints):
        if not scheduler_hints:
            scheduler_hints = self._default_scheduler_hints
        hosts = [mock.sentinel.host] if hosts is None else hosts
        if filtered_hosts is None:
            filtered_hosts = hosts
        admin_ctx = mock.sentinel.admin_ctxt
        mock_get_admin_context.return_value = admin_ctx
        mock_is_live_migrate.return_value = is_live_migrate
        mock_get_cn.side_effect = compute_node
        spec_obj = objects.RequestSpec(
                        context=mock.sentinel.ctx,
                        scheduler_hints=scheduler_hints)

        cell_mapping = mock.sentinel.cell_mapping
        mock_host_mapping.get_by_host.return_value.cell_mapping = cell_mapping

        cell_ctxt = mock.sentinel.cell_ctxt
        mock_target_cell.return_value.__enter__.return_value = cell_ctxt

        result = self.filter.filter_all(hosts, spec_obj)

        try:
            # In case the filter returns an iterable
            result = list(result)
        except TypeError:
            pass

        self.assertEqual(result, filtered_hosts)
        mock_is_live_migrate.assert_called_with(spec_obj)

        if compute_node is None:
            mock_get_admin_context.assert_not_called()
            mock_get_cn.assert_not_called()
        else:
            mock_get_admin_context.assert_called()
            source_host = spec_obj.get_scheduler_hint('source_host')
            source_node = spec_obj.get_scheduler_hint('source_node')
            mock_get_cn.assert_called_with(cell_ctxt, source_host, source_node)
        return spec_obj

    def _test_filter_all_no_host_passes(self, **kwargs):
        with mock.patch.object(
                self.filter, '_are_cpu_flags_supported') as mock_host_passes:
            spec_obj = self._test_filter_all(**kwargs)
            mock_host_passes.assert_not_called()
            return spec_obj

    def test_no_source_host_pass_through(self):
        self._test_filter_all_no_host_passes(source_host=['host1'])

    def test_no_source_node_pass_through(self):
        self._test_filter_all_no_host_passes(source_node=['node1'])

    def test_non_live_migrate_pass_through(self):
        self._test_filter_all_no_host_passes(is_live_migrate=False)

    def test_missing_compute_host_filters_all(self):
        def raise_exception(_, host, node):
            raise exception.ComputeHostNotFound(host=host)
        self._test_filter_all_no_host_passes(
            compute_node=raise_exception, hosts=[])

    def test_missing_host_mapping_filters_all(self):
        def raise_exception(_, host, node):
            raise exception.HostMappingNotFound(name=host)
        self._test_filter_all_no_host_passes(
            compute_node=raise_exception, hosts=[])

    def test_invalid_source_cpu_info_filters_all(self):
        self._test_filter_all_no_host_passes(
            compute_node=[mock.NonCallableMock(cpu_info="Random String")],
            hosts=[])

    def _test_valid_source_cpu_info_filters_all(self, cpu_info):
        hosts = [mock.sentinel.host0, mock.sentinel.host1]
        compute_node = [mock.NonCallableMock(cpu_info=cpu_info)]
        parsed_cpu_info = \
            cpu_info_migration_filter.CpuInfoMigrationFilter._parse_cpu_info(
                cpu_info)

        with mock.patch.object(
                self.filter, '_are_cpu_flags_supported',
                return_value=True) as mock_host_passes:
            self._test_filter_all(
                    compute_node=compute_node,
                    hosts=hosts)
            mock_host_passes.assert_has_calls([
                mock.call(host, parsed_cpu_info) for host in hosts
            ], any_order=True)  # We do not care about the order

    def test_valid_source_cpu_info_string(self):
        self._test_valid_source_cpu_info_filters_all(
            '{"features": ["a", "b", "c"]}')

    def test_valid_source_cpu_info_dict(self):
        self._test_valid_source_cpu_info_filters_all(
            dict(features=["a", "b", "c"]))

    def _test_target_cpu_info(self, target_cpu_info, filters=True):
        compute_node = [mock.NonCallableMock(
            cpu_info=dict(features=["a", "b"]))]
        hosts = [mock.NonCallableMock(cpu_info=target_cpu_info)]
        if filters:
            filtered_hosts = []
        else:
            filtered_hosts = hosts
        self._test_filter_all(compute_node=compute_node,
                              hosts=hosts, filtered_hosts=filtered_hosts)

        if not isinstance(target_cpu_info, str):
            target_cpu_info_str = jsonutils.dumps(target_cpu_info)
            self._test_target_cpu_info(target_cpu_info_str, filters)

    def test_invalid_target_cpu_info(self):
        self._test_target_cpu_info('Random String', filters=True)

    def test_target_cpu_info_subset(self):
        self._test_target_cpu_info(dict(features=["b", "c"]), filters=True)

    def test_target_cpu_info_equal(self):
        self._test_target_cpu_info(dict(features=["b", "a"]), filters=False)

    def test_target_cpu_info_superset(self):
        self._test_target_cpu_info(
            dict(features=["b", "a", "c"]), filters=False)
