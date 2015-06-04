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

from nova import objects
from nova.scheduler import filters
from nova.virt import hardware

LOG = logging.getLogger(__name__)


class NUMATopologyFilter(filters.BaseHostFilter):
    """Filter on requested NUMA topology."""

    @filters.compat_legacy_props
    def host_passes(self, host_state, filter_properties):
        ram_ratio = host_state.ram_allocation_ratio
        cpu_ratio = host_state.cpu_allocation_ratio
        request_spec = filter_properties.get('request_spec', {})
        instance = request_spec.get('instance_properties', {})
        requested_topology = hardware.instance_topology_from_instance(instance)
        host_topology, _fmt = hardware.host_topology_and_format_from_host(
                host_state)
        pci_requests = instance.get('pci_requests')
        if pci_requests:
            pci_requests = pci_requests.requests
        if requested_topology and host_topology:
            limits = objects.NUMATopologyLimits(
                cpu_allocation_ratio=cpu_ratio,
                ram_allocation_ratio=ram_ratio)
            instance_topology = (hardware.numa_fit_instance_to_host(
                        host_topology, requested_topology,
                        limits=limits,
                        pci_requests=pci_requests,
                        pci_stats=host_state.pci_stats))
            if not instance_topology:
                LOG.debug("%(host)s, %(node)s fails NUMA topology "
                          "requirements. The instance does not fit on this "
                          "host.", {'host': host_state.host,
                                    'node': host_state.nodename},
                          instance_uuid=instance.get('instance_uuid'))
                return False
            host_state.limits['numa_topology'] = limits
            return True
        elif requested_topology:
            LOG.debug("%(host)s, %(node)s fails NUMA topology requirements. "
                      "No host NUMA topology while the instance specified "
                      "one.",
                      {'host': host_state.host, 'node': host_state.nodename},
                      instance_uuid=instance.get('instance_uuid'))
            return False
        else:
            return True
