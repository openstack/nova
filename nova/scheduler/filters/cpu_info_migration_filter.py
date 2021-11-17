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

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import context as nova_context
from nova import exception
from nova.objects.compute_node import ComputeNode
from nova.objects.host_mapping import HostMapping
from nova.scheduler import filters
from nova.scheduler.utils import request_is_live_migrate

LOG = logging.getLogger(__name__)


class CpuInfoMigrationFilter(filters.BaseHostFilter):
    """Limit for live-migrations the target hosts by having all the
    sources cpu flags.

    We cannot move a VM from a host with more cpu features to one with less
    while running. It does not apply when the VM is stopped
    (E.g. resize/rebuild)

    Implements `filter_all` directly instead of `host_passes`
    """
    # Instance type and host capabilities do not change within a request
    run_filter_once_per_request = True

    def filter_all(self, filter_obj_list, spec_obj):
        source_host = spec_obj.get_scheduler_hint('source_host')
        source_node = spec_obj.get_scheduler_hint('source_node')

        if (not request_is_live_migrate(spec_obj) or
                not source_host or
                not source_node):
            return filter_obj_list

        try:
            context = nova_context.get_admin_context()
            host_mapping = HostMapping.get_by_host(context, source_host)
            cell_mapping = host_mapping.cell_mapping
            with nova_context.target_cell(context, cell_mapping) as cctxt:
                compute_node = ComputeNode.get_by_host_and_nodename(
                    cctxt, source_host, source_node)
        except exception.ComputeHostNotFound:
            LOG.warning("Cannot find source host/node %s/%s",
                        source_host, source_node)
            return []
        except exception.HostMappingNotFound:
            LOG.warning("Cannot find host mapping for host %s", source_host)
            return []

        try:
            source_cpu_flags = self._parse_cpu_info(compute_node.cpu_info)
        except (ValueError, KeyError):
            LOG.warning("Cannot parse cpu_info for source host/node %s/%s: %s",
                        source_host, source_node, compute_node.cpu_info)
            return []

        return [host_state
            for host_state in filter_obj_list
            if self._are_cpu_flags_supported(host_state, source_cpu_flags)]

    @staticmethod
    def _parse_cpu_info(cpu_info):
        if isinstance(cpu_info, str):
            cpu_info = jsonutils.loads(cpu_info)

        return set(cpu_info["features"])

    @staticmethod
    def _are_cpu_flags_supported(host_state, source_cpu_flags):
        """Return if a host supports the given cpu flags."""
        try:
            cpu_flags = CpuInfoMigrationFilter._parse_cpu_info(
                host_state.cpu_info)
        except (ValueError, KeyError):
            LOG.warning(
                "Cannot parse cpu_info for target host/node (%s/%s) '%s'",
                host_state.host, host_state.nodename, host_state.cpu_info)
            return False

        return source_cpu_flags.issubset(cpu_flags)
