# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright (c) 2011-2014 OpenStack Foundation
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

"""
Ironic host manager.

This host manager will consume all cpu's, disk space, and
ram from a host / node as it is supporting Baremetal hosts, which can not be
subdivided into multiple instances.
"""
from oslo_log import log as logging

import nova.conf
from nova import context as context_module
from nova import objects
from nova.objects import fields as obj_fields
from nova.scheduler import host_manager

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class IronicNodeState(host_manager.HostState):
    """Mutable and immutable information tracked for a host.
    This is an attempt to remove the ad-hoc data structures
    previously used and lock down access.
    """

    def _update_from_compute_node(self, compute):
        """Update information about a host from a ComputeNode object."""

        # NOTE(jichenjc): if the compute record is just created but not updated
        # some field such as free_disk_gb can be None
        if 'free_disk_gb' not in compute or compute.free_disk_gb is None:
            LOG.debug('Ignoring compute node %s as its usage has not been '
                      'updated yet.', compute.uuid)
            return

        self.vcpus_total = compute.vcpus
        self.vcpus_used = compute.vcpus_used

        self.free_ram_mb = compute.free_ram_mb
        self.total_usable_ram_mb = compute.memory_mb
        self.free_disk_mb = compute.free_disk_gb * 1024

        self.stats = compute.stats or {}
        self.uuid = compute.uuid

        self.total_usable_disk_gb = compute.local_gb
        self.hypervisor_type = compute.hypervisor_type
        self.hypervisor_version = compute.hypervisor_version
        self.hypervisor_hostname = compute.hypervisor_hostname
        self.cpu_info = compute.cpu_info
        if compute.supported_hv_specs:
            self.supported_instances = [spec.to_list() for spec
                                        in compute.supported_hv_specs]
        else:
            self.supported_instances = []

        # update allocation ratios given by the ComputeNode object
        self.cpu_allocation_ratio = compute.cpu_allocation_ratio
        self.ram_allocation_ratio = compute.ram_allocation_ratio
        self.disk_allocation_ratio = compute.disk_allocation_ratio

        # update failed_builds counter reported by the compute
        self.failed_builds = int(self.stats.get('failed_builds', 0))

        self.updated = compute.updated_at

    def _locked_consume_from_request(self, spec_obj):
        """Consume nodes entire resources regardless of instance request."""
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_used = self.vcpus_total


class IronicHostManager(host_manager.HostManager):
    """Ironic HostManager class."""

    @staticmethod
    def _is_ironic_compute(compute):
        ht = compute.hypervisor_type if 'hypervisor_type' in compute else None
        return ht == obj_fields.HVType.IRONIC

    def _load_filters(self):
        if CONF.filter_scheduler.use_baremetal_filters:
            return CONF.filter_scheduler.baremetal_enabled_filters
        return super(IronicHostManager, self)._load_filters()

    def host_state_cls(self, host, node, cell, **kwargs):
        """Factory function/property to create a new HostState."""
        compute = kwargs.get('compute')
        if compute and self._is_ironic_compute(compute):
            return IronicNodeState(host, node, cell)
        else:
            return host_manager.HostState(host, node, cell)

    def _init_instance_info(self, computes_by_cell=None):
        """Ironic hosts should not pass instance info."""
        context = context_module.RequestContext()
        self._load_cells(context)
        if not computes_by_cell:
            computes_by_cell = {}
            for cell in self.cells:
                with context_module.target_cell(context, cell) as cctxt:
                    computes_by_cell[cell] = (
                        objects.ComputeNodeList.get_all(cctxt).objects)

        non_ironic_computes = {cell: [c for c in compute_nodes
                                      if not self._is_ironic_compute(c)]
                               for cell, compute_nodes in
                               computes_by_cell.items()}
        super(IronicHostManager, self)._init_instance_info(non_ironic_computes)

    def _get_instance_info(self, context, compute):
        """Ironic hosts should not pass instance info."""

        if compute and self._is_ironic_compute(compute):
            return {}
        else:
            return super(IronicHostManager, self)._get_instance_info(context,
                                                                     compute)
