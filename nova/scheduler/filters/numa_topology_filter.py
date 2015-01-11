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

from oslo_config import cfg

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
        request_spec = filter_properties.get('request_spec', {})
        instance = request_spec.get('instance_properties', {})
        requested_topology = hardware.instance_topology_from_instance(instance)
        host_topology, _fmt = hardware.host_topology_and_format_from_host(
                host_state)
        pci_requests = filter_properties.get('pci_requests')
        if pci_requests:
            pci_requests = pci_requests.requests
        if requested_topology and host_topology:
            limit_cells = []
            for cell in host_topology.cells:
                max_cell_memory = int(cell.memory * ram_ratio)
                max_cell_cpu = len(cell.cpuset) * cpu_ratio
                limit_cells.append(hardware.VirtNUMATopologyCellLimit(
                    cell.id, cell.cpuset, cell.memory,
                    max_cell_cpu, max_cell_memory))
            limits = hardware.VirtNUMALimitTopology(cells=limit_cells)
            instance_topology = (hardware.numa_fit_instance_to_host(
                        host_topology, requested_topology,
                        limits_topology=limits,
                        pci_requests=pci_requests,
                        pci_stats=host_state.pci_stats))
            if not instance_topology:
                return False
            host_state.limits['numa_topology'] = limits.to_json()
            instance['numa_topology'] = instance_topology
            return True
        elif requested_topology:
            return False
        else:
            return True
