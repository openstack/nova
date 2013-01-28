# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import json

from nova import exception
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)


class Host(object):
    """
    Implements host related operations.
    """
    def __init__(self, session):
        self._session = session

    def host_power_action(self, host, action):
        """Reboots or shuts down the host."""
        host_mor = self._session._call_method(vim_util, "get_objects",
                                              "HostSystem")[0].obj
        LOG.debug(_("%(action)s %(host)s") % locals())
        if action == "reboot":
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "RebootHost_Task", host_mor,
                                    force=False)
        elif action == "shutdown":
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "ShutdownHost_Task", host_mor,
                                    force=False)
        elif action == "startup":
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "PowerUpHostFromStandBy_Task", host_mor,
                                    timeoutSec=60)
        self._session._wait_for_task(host, host_task)

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation."""
        host_mor = self._session._call_method(vim_util, "get_objects",
                                              "HostSystem")[0].obj
        LOG.debug(_("Set maintenance mod on %(host)s to %(mode)s") % locals())
        if mode:
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "EnterMaintenanceMode_Task",
                                    host_mor, timeout=0,
                                    evacuatePoweredOffVms=True)
        else:
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "ExitMaintenanceMode_Task",
                                    host_mor, timeout=0)
        self._session._wait_for_task(host, host_task)

    def set_host_enabled(self, _host, enabled):
        """Sets the specified host's ability to accept new instances."""
        pass


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
        if refresh:
            self.update_status()
        return self._stats

    def update_status(self):
        """Update the current state of the host.
        """
        host_mor = self._session._call_method(vim_util, "get_objects",
                                              "HostSystem")[0].obj
        summary = self._session._call_method(vim_util,
                                             "get_dynamic_property",
                                             host_mor,
                                             "HostSystem",
                                             "summary")

        if summary is None:
            return

        try:
            ds = vm_util.get_datastore_ref_and_name(self._session)
        except exception.DatastoreNotFound:
            ds = (None, None, 0, 0)

        data = {}
        data["vcpus"] = summary.hardware.numCpuThreads
        data["cpu_info"] = \
                {"vendor": summary.hardware.vendor,
                 "model": summary.hardware.cpuModel,
                 "topology": {"cores": summary.hardware.numCpuCores,
                              "sockets": summary.hardware.numCpuPkgs,
                              "threads": summary.hardware.numCpuThreads}
                }
        data["disk_total"] = ds[2] / (1024 * 1024)
        data["disk_available"] = ds[3] / (1024 * 1024)
        data["disk_used"] = data["disk_total"] - data["disk_available"]
        data["host_memory_total"] = summary.hardware.memorySize / (1024 * 1024)
        data["host_memory_free"] = data["host_memory_total"] - \
                                   summary.quickStats.overallMemoryUsage
        data["hypervisor_type"] = summary.config.product.name
        data["hypervisor_version"] = summary.config.product.version
        data["hypervisor_hostname"] = self._host_name

        self._stats = data
        return data
