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

from oslo.config import cfg

from nova.scheduler import filters
from nova.virt import hardware

CONF = cfg.CONF
CONF.import_opt('cpu_allocation_ratio', 'nova.scheduler.filters.core_filter')
CONF.import_opt('ram_allocation_ratio', 'nova.scheduler.filters.ram_filter')


class NUMATopologyFilter(filters.BaseHostFilter):
    """Filter on requested NUMA topology."""

    def host_passes(self, host_state, filter_properties):
        ram_ratio = CONF.ram_allocation_ratio
        cpu_ratio = CONF.cpu_allocation_ratio
        instance = filter_properties.get('instance_properties', {})
        instance_topology = hardware.instance_topology_from_instance(instance)
        if instance_topology:
            if host_state.numa_topology:
                limit_cells = []
                usage_after_instance = (
                        hardware.get_host_numa_usage_from_instance(
                            host_state, instance, never_serialize_result=True))
                for cell in usage_after_instance.cells:
                    max_cell_memory = int(cell.memory * ram_ratio)
                    max_cell_cpu = len(cell.cpuset) * cpu_ratio
                    if (cell.memory_usage > max_cell_memory or
                            cell.cpu_usage > max_cell_cpu):
                        return False
                    limit_cells.append(
                        hardware.VirtNUMATopologyCellLimit(
                            cell.id, cell.cpuset, cell.memory,
                            max_cell_cpu, max_cell_memory))
                host_state.limits['numa_topology'] = (
                        hardware.VirtNUMALimitTopology(
                            cells=limit_cells).to_json())
                return True
            else:
                return False
        else:
            return True
