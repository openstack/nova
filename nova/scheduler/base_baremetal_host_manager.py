# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright (c) 2011 OpenStack Foundation
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
Manage hosts in the current zone.
"""

from nova.openstack.common import jsonutils
from nova.scheduler import host_manager


class BaseBaremetalNodeState(host_manager.HostState):
    """Mutable and immutable information tracked for a host.
    This is an attempt to remove the ad-hoc data structures
    previously used and lock down access.
    """

    def update_from_compute_node(self, compute):
        """Update information about a host from its compute_node info."""
        self.vcpus_total = compute['vcpus']
        self.vcpus_used = compute['vcpus_used']

        self.free_ram_mb = compute['free_ram_mb']
        self.total_usable_ram_mb = compute['memory_mb']
        self.free_disk_mb = compute['free_disk_gb'] * 1024

        stats = compute.get('stats', '{}')
        self.stats = jsonutils.loads(stats)

    def consume_from_instance(self, instance):
        """Consume nodes entire resources regardless of instance request."""
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_used = self.vcpus_total


class BaseBaremetalHostManager(host_manager.HostManager):
    """Base class for Baremetal and Ironic HostManager classes."""

    def host_state_cls(self, host, node, **kwargs):
        """Factory function to create a new HostState.  May be overridden
        in subclasses to extend functionality.
        """
        return BaseBaremetalNodeState(host, node, **kwargs)
