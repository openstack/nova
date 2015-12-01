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

from oslo_utils import units
from oslo_utils import versionutils

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import vm_mode
from nova import exception
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util


def _get_ds_capacity_and_freespace(session, cluster=None,
                                   datastore_regex=None):
    try:
        ds = ds_util.get_datastore(session, cluster,
                                   datastore_regex)
        return ds.capacity, ds.freespace
    except exception.DatastoreNotFound:
        return 0, 0


class VCState(object):
    """Manages information about the vCenter cluster"""
    def __init__(self, session, host_name, cluster, datastore_regex):
        super(VCState, self).__init__()
        self._session = session
        self._host_name = host_name
        self._cluster = cluster
        self._datastore_regex = datastore_regex
        self._stats = {}
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
        capacity, freespace = _get_ds_capacity_and_freespace(self._session,
            self._cluster, self._datastore_regex)

        # Get cpu, memory stats from the cluster
        stats = vm_util.get_stats_from_cluster(self._session, self._cluster)
        about_info = self._session._call_method(vim_util, "get_about_info")
        data = {}
        data["vcpus"] = stats['vcpus']
        data["disk_total"] = capacity / units.Gi
        data["disk_available"] = freespace / units.Gi
        data["disk_used"] = data["disk_total"] - data["disk_available"]
        data["host_memory_total"] = stats['mem']['total']
        data["host_memory_free"] = stats['mem']['free']
        data["hypervisor_type"] = about_info.name
        data["hypervisor_version"] = versionutils.convert_version_to_int(
                str(about_info.version))
        data["hypervisor_hostname"] = self._host_name
        data["supported_instances"] = [
            (arch.I686, hv_type.VMWARE, vm_mode.HVM),
            (arch.X86_64, hv_type.VMWARE, vm_mode.HVM)]

        self._stats = data
        return data
