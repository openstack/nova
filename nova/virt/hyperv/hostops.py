# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Cloudbase Solutions Srl
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
Management class for host operations.
"""
import multiprocessing
import platform

from nova.openstack.common import log as logging
from nova.virt.hyperv import baseops

LOG = logging.getLogger(__name__)


class HostOps(baseops.BaseOps):
    def __init__(self):
        super(HostOps, self).__init__()
        self._stats = None

    def _get_vcpu_total(self):
        """Get vcpu number of physical computer.
        :returns: the number of cpu core.
        """
        # On certain platforms, this will raise a NotImplementedError.
        try:
            return multiprocessing.cpu_count()
        except NotImplementedError:
            LOG.warn(_("Cannot get the number of cpu, because this "
                       "function is not implemented for this platform. "
                       "This error can be safely ignored for now."))
            return 0

    def _get_memory_mb_total(self):
        """Get the total memory size(MB) of physical computer.
        :returns: the total amount of memory(MB).
        """
        total_kb = self._conn_cimv2.query(
            "SELECT TotalVisibleMemorySize FROM win32_operatingsystem")[0]\
            .TotalVisibleMemorySize
        total_mb = long(total_kb) / 1024
        return total_mb

    def _get_local_gb_total(self):
        """Get the total hdd size(GB) of physical computer.
        :returns:
            The total amount of HDD(GB).
            Note that this value shows a partition where
            NOVA-INST-DIR/instances mounts.
        """
        #TODO(jordanrinke): This binds to C only right now,
        #need to bind to instance dir
        total_kb = self._conn_cimv2.query(
            "SELECT Size FROM win32_logicaldisk WHERE DriveType=3")[0].Size
        total_gb = long(total_kb) / (1024 ** 3)
        return total_gb

    def _get_vcpu_used(self):
        """ Get vcpu usage number of physical computer.
        :returns: The total number of vcpu that currently used.
        """
        #TODO(jordanrinke) figure out a way to count assigned VCPUs
        total_vcpu = 0
        return total_vcpu

    def _get_memory_mb_used(self):
        """Get the free memory size(MB) of physical computer.
        :returns: the total usage of memory(MB).
        """
        total_kb = self._conn_cimv2.query(
            "SELECT FreePhysicalMemory FROM win32_operatingsystem")[0]\
                .FreePhysicalMemory
        total_mb = long(total_kb) / 1024

        return total_mb

    def _get_local_gb_used(self):
        """Get the free hdd size(GB) of physical computer.
        :returns:
           The total usage of HDD(GB).
           Note that this value shows a partition where
           NOVA-INST-DIR/instances mounts.
        """
        #TODO(jordanrinke): This binds to C only right now,
        #need to bind to instance dir
        total_kb = self._conn_cimv2.query(
            "SELECT FreeSpace FROM win32_logicaldisk WHERE DriveType=3")[0]\
                .FreeSpace
        total_gb = long(total_kb) / (1024 ** 3)
        return total_gb

    def _get_hypervisor_version(self):
        """Get hypervisor version.
        :returns: hypervisor version (ex. 12003)
        """
        version = self._conn_cimv2.Win32_OperatingSystem()[0]\
            .Version.replace('.', '')
        LOG.info(_('Windows version: %s ') % version)
        return version

    def get_available_resource(self):
        """Retrieve resource info.

        This method is called when nova-compute launches, and
        as part of a periodic task.

        :returns: dictionary describing resources

        """
        LOG.info(_('get_available_resource called'))

        # TODO(alexpilotti) implemented cpu_info
        dic = {'vcpus': self._get_vcpu_total(),
               'memory_mb': self._get_memory_mb_total(),
               'local_gb': self._get_local_gb_total(),
               'vcpus_used': self._get_vcpu_used(),
               'memory_mb_used': self._get_memory_mb_used(),
               'local_gb_used': self._get_local_gb_used(),
               'hypervisor_type': "hyperv",
               'hypervisor_version': self._get_hypervisor_version(),
               'hypervisor_hostname': platform.node(),
               'cpu_info': 'unknown'}

        return dic

    def _update_stats(self):
        LOG.debug(_("Updating host stats"))

        data = {}
        data["disk_total"] = self._get_local_gb_total()
        data["disk_used"] = self._get_local_gb_used()
        data["disk_available"] = data["disk_total"] - data["disk_used"]
        data["host_memory_total"] = self._get_memory_mb_total()
        data["host_memory_overhead"] = self._get_memory_mb_used()
        data["host_memory_free"] = \
            data["host_memory_total"] - data["host_memory_overhead"]
        data["host_memory_free_computed"] = data["host_memory_free"]
        data["supported_instances"] = \
            [('i686', 'hyperv', 'hvm'),
             ('x86_64', 'hyperv', 'hvm')]

        self._stats = data

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
           True, run the update first."""
        LOG.info(_("get_host_stats called"))

        if refresh or not self._stats:
            self._update_stats()
        return self._stats

    def host_power_action(self, host, action):
        """Reboots, shuts down or powers up the host."""
        pass
