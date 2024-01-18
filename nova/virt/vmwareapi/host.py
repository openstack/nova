# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
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
Management class for host-related functions (start, reboot, etc).
"""
from copy import deepcopy

from oslo_log import log as logging
from oslo_utils import units
from oslo_utils import versionutils
from oslo_vmware import exceptions as vexc

import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova.objects import fields as obj_fields
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

SERVICE_DISABLED_REASON = 'set by vmwareapi host_state'


def _get_ds_capacity_and_freespace(session, cluster=None,
                                   datastore_regex=None):
    capacity = 0
    freespace = 0
    max_freespace = 0
    try:
        for ds in ds_util.get_available_datastores(session, cluster,
                                                   datastore_regex):
            capacity += ds.capacity
            freespace += ds.freespace
            max_freespace = max(max_freespace, ds.freespace)
    except exception.DatastoreNotFound:
        pass

    # Avoid ValueError("Capacity is smaller than free space")
    return capacity, min(freespace, capacity), min(max_freespace, capacity)


class VCState(object):
    """Manages information about the vCenter cluster"""

    def __init__(self, session, cluster_node_name, cluster, datastore_regex):
        super(VCState, self).__init__()
        self._session = session
        self._cluster_node_name = cluster_node_name
        self._cluster = cluster
        self._datastore_regex = datastore_regex
        self._stats = {}
        ctx = context.get_admin_context()
        try:
            service = objects.Service.get_by_compute_host(ctx, CONF.host)
            self._auto_service_disabled = service.disabled \
                        and service.disabled_reason == SERVICE_DISABLED_REASON
        except exception.ComputeHostNotFound:
            # this can happend on newly-added hosts
            self._auto_service_disabled = False
        about_info = self._session._call_method(vim_util, "get_about_info")
        self._hypervisor_type = about_info.name
        self._hypervisor_version = versionutils.convert_version_to_int(
                str(about_info.version))
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the cluster. If 'refresh' is
        True, run the update first.
        """
        if refresh or not self._stats:
            self.update_status()
        return self._stats

    def update_status(self):
        """Update the current state of the cluster."""
        data = {}
        try:
            capacity, free, max_free = _get_ds_capacity_and_freespace(
                self._session, self._cluster, self._datastore_regex)

            # Get cpu, memory stats from the cluster
            per_host_stats = vm_util.get_stats_from_cluster_per_host(
                self._session, self._cluster)
        except (vexc.VimConnectionException, vexc.VimAttributeException) as ex:
            # VimAttributeException is thrown when vpxd service is down
            LOG.warning("Failed to connect with %(node)s. "
                        "Error: %(error)s",
                        {'node': self._cluster_node_name, 'error': ex})
            self._set_host_enabled(False)
            return data

        local_gb = capacity // units.Gi
        local_gb_used = (capacity - free) // units.Gi
        local_gb_max_free = max_free // units.Gi

        defaults = {
            "local_gb": local_gb,
            "local_gb_used": local_gb_used,
            "local_gb_max_free": local_gb_max_free,
            "supported_instances": [
                (obj_fields.Architecture.I686,
                 obj_fields.HVType.VMWARE,
                 obj_fields.VMMode.HVM),
                (obj_fields.Architecture.X86_64,
                 obj_fields.HVType.VMWARE,
                 obj_fields.VMMode.HVM)],
            "numa_topology": None,
        }

        for host_ref_value, info in per_host_stats.items():
            data[info["name"]] = self._merge_stats(info["name"], info,
                                                   defaults)
        cluster_stats = vm_util.aggregate_stats_from_cluster(per_host_stats)
        cluster_stats["hypervisor_type"] = self._hypervisor_type
        cluster_stats["hypervisor_version"] = self._hypervisor_version
        data[self._cluster_node_name] = self._merge_stats(
            self._cluster_node_name, cluster_stats, defaults)

        self._stats = data
        if self._auto_service_disabled:
            self._set_host_enabled(True)
        return data

    def _merge_stats(self, host, stats, defaults):
        result = deepcopy(defaults)
        result["hypervisor_hostname"] = host
        result.update(stats)
        return result

    def _set_host_enabled(self, enabled):
        """Sets the compute host's ability to accept new instances."""
        ctx = context.get_admin_context()
        service = objects.Service.get_by_compute_host(ctx, CONF.host)
        service.disabled = not enabled
        service.disabled_reason = SERVICE_DISABLED_REASON
        service.save()
        self._auto_service_disabled = service.disabled
