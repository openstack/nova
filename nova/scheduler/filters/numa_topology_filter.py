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
from nova.objects import fields
from nova.scheduler import filters
from nova.virt import hardware

LOG = logging.getLogger(__name__)


class NUMATopologyFilter(filters.BaseHostFilter):
    """Filter on requested NUMA topology."""

    RUN_ON_REBUILD = True

    def _satisfies_cpu_policy(self, host_state, extra_specs, image_props):
        """Check that the host_state provided satisfies any available
        CPU policy requirements.
        """
        host_topology, _ = hardware.host_topology_and_format_from_host(
            host_state)
        # NOTE(stephenfin): There can be conflicts between the policy
        # specified by the image and that specified by the instance, but this
        # is not the place to resolve these. We do this during scheduling.
        cpu_policy = [extra_specs.get('hw:cpu_policy'),
                      image_props.get('hw_cpu_policy')]
        cpu_thread_policy = [extra_specs.get('hw:cpu_thread_policy'),
                             image_props.get('hw_cpu_thread_policy')]

        if not host_topology:
            return True

        if fields.CPUAllocationPolicy.DEDICATED not in cpu_policy:
            return True

        if fields.CPUThreadAllocationPolicy.REQUIRE not in cpu_thread_policy:
            return True

        if not host_topology.has_threads:
            LOG.debug("%(host_state)s fails CPU policy requirements. "
                      "Host does not have hyperthreading or "
                      "hyperthreading is disabled, but 'require' threads "
                      "policy was requested.", {'host_state': host_state})
            return False

        return True

    def host_passes(self, host_state, spec_obj):
        # TODO(stephenfin): The 'numa_fit_instance_to_host' function has the
        # unfortunate side effect of modifying 'spec_obj.numa_topology' - an
        # InstanceNUMATopology object - by populating the 'cpu_pinning' field.
        # This is rather rude and said function should be reworked to avoid
        # doing this. That's a large, non-backportable cleanup however, so for
        # now we just duplicate spec_obj to prevent changes propagating to
        # future filter calls.
        spec_obj = spec_obj.obj_clone()

        ram_ratio = host_state.ram_allocation_ratio
        cpu_ratio = host_state.cpu_allocation_ratio
        extra_specs = spec_obj.flavor.extra_specs
        image_props = spec_obj.image.properties
        requested_topology = spec_obj.numa_topology
        host_topology, _fmt = hardware.host_topology_and_format_from_host(
                host_state)
        pci_requests = spec_obj.pci_requests

        network_metadata = None
        if 'network_metadata' in spec_obj:
            network_metadata = spec_obj.network_metadata

        if pci_requests:
            pci_requests = pci_requests.requests

        if not self._satisfies_cpu_policy(host_state, extra_specs,
                                          image_props):
            return False

        if requested_topology and host_topology:
            limits = objects.NUMATopologyLimits(
                cpu_allocation_ratio=cpu_ratio,
                ram_allocation_ratio=ram_ratio)

            if network_metadata:
                limits.network_metadata = network_metadata

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
                          instance_uuid=spec_obj.instance_uuid)
                return False
            host_state.limits['numa_topology'] = limits
            return True
        elif requested_topology:
            LOG.debug("%(host)s, %(node)s fails NUMA topology requirements. "
                      "No host NUMA topology while the instance specified "
                      "one.",
                      {'host': host_state.host, 'node': host_state.nodename},
                      instance_uuid=spec_obj.instance_uuid)
            return False
        else:
            return True
