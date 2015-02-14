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
import iso8601
from oslo_config import cfg
from oslo_utils import timeutils

from nova.openstack.common import log as logging
from nova.scheduler import host_manager

host_manager_opts = [
    cfg.ListOpt('baremetal_scheduler_default_filters',
                default=[
                    'RetryFilter',
                    'AvailabilityZoneFilter',
                    'ComputeFilter',
                    'ComputeCapabilitiesFilter',
                    'ImagePropertiesFilter',
                    'ExactRamFilter',
                    'ExactDiskFilter',
                    'ExactCoreFilter',
                ],
                help='Which filter class names to use for filtering '
                     'baremetal hosts when not specified in the request.'),
    cfg.BoolOpt('scheduler_use_baremetal_filters',
                default=False,
                help='Flag to decide whether to use '
                     'baremetal_scheduler_default_filters or not.'),

    ]

CONF = cfg.CONF
CONF.register_opts(host_manager_opts)

LOG = logging.getLogger(__name__)


class IronicNodeState(host_manager.HostState):
    """Mutable and immutable information tracked for a host.
    This is an attempt to remove the ad-hoc data structures
    previously used and lock down access.
    """

    def update_from_compute_node(self, compute):
        """Update information about a host from a ComputeNode object."""
        self.vcpus_total = compute.vcpus
        self.vcpus_used = compute.vcpus_used

        self.free_ram_mb = compute.free_ram_mb
        self.total_usable_ram_mb = compute.memory_mb
        self.free_disk_mb = compute.free_disk_gb * 1024

        self.stats = compute.stats or {}

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
        self.updated = compute.updated_at

    def consume_from_instance(self, instance):
        """Consume nodes entire resources regardless of instance request."""
        self.free_ram_mb = 0
        self.free_disk_mb = 0
        self.vcpus_used = self.vcpus_total

        now = timeutils.utcnow()
        # NOTE(sbauza): Objects are UTC tz-aware by default
        self.updated = now.replace(tzinfo=iso8601.iso8601.Utc())


class IronicHostManager(host_manager.HostManager):
    """Ironic HostManager class."""

    def __init__(self):
        super(IronicHostManager, self).__init__()
        if CONF.scheduler_use_baremetal_filters:
            baremetal_default = CONF.baremetal_scheduler_default_filters
            CONF.scheduler_default_filters = baremetal_default

    def host_state_cls(self, host, node, **kwargs):
        """Factory function/property to create a new HostState."""
        compute = kwargs.get('compute')
        if compute and compute.get('hypervisor_type') == 'ironic':
            return IronicNodeState(host, node, **kwargs)
        else:
            return host_manager.HostState(host, node, **kwargs)
