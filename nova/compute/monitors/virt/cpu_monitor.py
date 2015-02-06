# Copyright 2013 Intel Corporation.
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
CPU monitor based on compute driver to retrieve CPU information
"""

from oslo_config import cfg
from oslo_utils import timeutils

from nova.compute import monitors
from nova.compute.monitors import cpu_monitor as monitor
from nova import exception
from nova.i18n import _LE
from nova.openstack.common import log as logging

CONF = cfg.CONF
CONF.import_opt('compute_driver', 'nova.virt.driver')
LOG = logging.getLogger(__name__)


class ComputeDriverCPUMonitor(monitor._CPUMonitorBase):
    """CPU monitor based on compute driver

    The class inherits from the base class for resource monitors,
    and implements the essential methods to get metric names and their real
    values for CPU utilization.

    The compute manager could load the monitors to retrieve the metrics
    of the devices on compute nodes and know their resource information
    periodically.
    """

    def __init__(self, parent):
        super(ComputeDriverCPUMonitor, self).__init__(parent)
        self.source = CONF.compute_driver
        self.driver = self.compute_manager.driver
        self._cpu_stats = {}

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_frequency(self, **kwargs):
        return self._data.get("cpu.frequency")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_user_time(self, **kwargs):
        return self._data.get("cpu.user.time")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_kernel_time(self, **kwargs):
        return self._data.get("cpu.kernel.time")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_idle_time(self, **kwargs):
        return self._data.get("cpu.idle.time")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_iowait_time(self, **kwargs):
        return self._data.get("cpu.iowait.time")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_user_percent(self, **kwargs):
        return self._data.get("cpu.user.percent")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_kernel_percent(self, **kwargs):
        return self._data.get("cpu.kernel.percent")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_idle_percent(self, **kwargs):
        return self._data.get("cpu.idle.percent")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_iowait_percent(self, **kwargs):
        return self._data.get("cpu.iowait.percent")

    @monitors.ResourceMonitorBase.add_timestamp
    def _get_cpu_percent(self, **kwargs):
        return self._data.get("cpu.percent")

    def _update_data(self, **kwargs):
        # Don't allow to call this function so frequently (<= 1 sec)
        now = timeutils.utcnow()
        if self._data.get("timestamp") is not None:
            delta = now - self._data.get("timestamp")
            if delta.seconds <= 1:
                return

        self._data = {}
        self._data["timestamp"] = now

        # Extract node's CPU statistics.
        try:
            stats = self.driver.get_host_cpu_stats()
            self._data["cpu.user.time"] = stats["user"]
            self._data["cpu.kernel.time"] = stats["kernel"]
            self._data["cpu.idle.time"] = stats["idle"]
            self._data["cpu.iowait.time"] = stats["iowait"]
            self._data["cpu.frequency"] = stats["frequency"]
        except (NotImplementedError, TypeError, KeyError) as ex:
            LOG.exception(_LE("Not all properties needed are implemented "
                              "in the compute driver: %s"), ex)
            raise exception.ResourceMonitorError(
                monitor=self.__class__.__name__)

        # The compute driver API returns the absolute values for CPU times.
        # We compute the utilization percentages for each specific CPU time
        # after calculating the delta between the current reading and the
        # previous reading.
        stats["total"] = (stats["user"] + stats["kernel"]
                          + stats["idle"] + stats["iowait"])
        cputime = float(stats["total"] - self._cpu_stats.get("total", 0))

        perc = (stats["user"] - self._cpu_stats.get("user", 0)) / cputime
        self._data["cpu.user.percent"] = perc

        perc = (stats["kernel"] - self._cpu_stats.get("kernel", 0)) / cputime
        self._data["cpu.kernel.percent"] = perc

        perc = (stats["idle"] - self._cpu_stats.get("idle", 0)) / cputime
        self._data["cpu.idle.percent"] = perc

        perc = (stats["iowait"] - self._cpu_stats.get("iowait", 0)) / cputime
        self._data["cpu.iowait.percent"] = perc

        # Compute the current system-wide CPU utilization as a percentage.
        used = stats["user"] + stats["kernel"] + stats["iowait"]
        prev_used = (self._cpu_stats.get("user", 0)
                     + self._cpu_stats.get("kernel", 0)
                     + self._cpu_stats.get("iowait", 0))
        perc = (used - prev_used) / cputime
        self._data["cpu.percent"] = perc

        self._cpu_stats = stats.copy()
