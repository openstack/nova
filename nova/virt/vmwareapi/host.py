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

from nova.compute import arch
from nova.compute import hvtype
from nova.compute import vm_mode
from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common import units
from nova import utils
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)


def _get_ds_capacity_and_freespace(session, cluster=None):
    try:
        ds = ds_util.get_datastore(session, cluster)
        return ds.capacity, ds.freespace
    except exception.DatastoreNotFound:
        return 0, 0


class HostState(object):
    """Manages information about the ESX host this compute
    node is running on.
    """
    def __init__(self, session, host_name):
        super(HostState, self).__init__()
        self._session = session
        self._host_name = host_name
        self._stats = {}
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh or not self._stats:
            self.update_status()
        return self._stats

    def update_status(self):
        """Update the current state of the host.
        """
        host_mor = vm_util.get_host_ref(self._session)
        summary = self._session._call_method(vim_util,
                                             "get_dynamic_property",
                                             host_mor,
                                             "HostSystem",
                                             "summary")

        if summary is None:
            return

        capacity, freespace = _get_ds_capacity_and_freespace(self._session)

        data = {}
        data["vcpus"] = summary.hardware.numCpuThreads
        data["cpu_info"] = \
                {"vendor": summary.hardware.vendor,
                 "model": summary.hardware.cpuModel,
                 "topology": {"cores": summary.hardware.numCpuCores,
                              "sockets": summary.hardware.numCpuPkgs,
                              "threads": summary.hardware.numCpuThreads}
                }
        data["disk_total"] = capacity / units.Gi
        data["disk_available"] = freespace / units.Gi
        data["disk_used"] = data["disk_total"] - data["disk_available"]
        data["host_memory_total"] = summary.hardware.memorySize / units.Mi
        data["host_memory_free"] = data["host_memory_total"] - \
                                   summary.quickStats.overallMemoryUsage
        data["hypervisor_type"] = summary.config.product.name
        data["hypervisor_version"] = utils.convert_version_to_int(
                str(summary.config.product.version))
        data["hypervisor_hostname"] = self._host_name
        data["supported_instances"] = [
            (arch.I686, hvtype.VMWARE, vm_mode.HVM),
            (arch.X86_64, hvtype.VMWARE, vm_mode.HVM)]

        self._stats = data
        return data


class VCState(object):
    """Manages information about the VC host this compute
    node is running on.
    """
    def __init__(self, session, host_name, cluster):
        super(VCState, self).__init__()
        self._session = session
        self._host_name = host_name
        self._cluster = cluster
        self._stats = {}
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh or not self._stats:
            self.update_status()
        return self._stats

    def update_status(self):
        """Update the current state of the cluster."""
        capacity, freespace = _get_ds_capacity_and_freespace(self._session,
                                                             self._cluster)

        # Get cpu, memory stats from the cluster
        stats = vm_util.get_stats_from_cluster(self._session, self._cluster)
        about_info = self._session._call_method(vim_util, "get_about_info")
        data = {}
        data["vcpus"] = stats['cpu']['vcpus']
        data["cpu_info"] = {"vendor": stats['cpu']['vendor'],
                            "model": stats['cpu']['model'],
                            "topology": {"cores": stats['cpu']['cores'],
                                         "threads": stats['cpu']['vcpus']}}
        data["disk_total"] = capacity / units.Gi
        data["disk_available"] = freespace / units.Gi
        data["disk_used"] = data["disk_total"] - data["disk_available"]
        data["host_memory_total"] = stats['mem']['total']
        data["host_memory_free"] = stats['mem']['free']
        data["hypervisor_type"] = about_info.name
        data["hypervisor_version"] = utils.convert_version_to_int(
                str(about_info.version))
        data["hypervisor_hostname"] = self._host_name
        data["supported_instances"] = [
            (arch.I686, hvtype.VMWARE, vm_mode.HVM),
            (arch.X86_64, hvtype.VMWARE, vm_mode.HVM)]

        self._stats = data
        return data
