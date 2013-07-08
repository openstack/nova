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
# @author: Shane Wang, Intel Corporation.

"""
CPU monitor based on compute driver to retrieve CPU information
"""

from oslo.config import cfg

from nova.compute.monitors import cpu_monitor as monitor
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils

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
        self._data = {}

    def add_timestamp(f):
        """Decorator to indicate that a method needs to add a timestamp.

        The decorator (w/o any argument) is used in this way in this class
        only. When a function returning a value is decorated by the decorator,
        which means a timestamp should be added into the returned value.
        That is, a tuple (value, timestamp) is returned.

        The timestamp is not the time when the function is called but probably
        when the value the function returns was retrieved.
        Actually the value is retrieved by the internal method
        _update_cpustat(). Because we don't allow _update_cpustat() is called
        so frequently. So, the value is read from the cache which was got in
        the last call sometimes. And the timestamp is saved for utilization
        aware scheduling in the future.

        The decorator is mainly used in this class. If users hope to define
        how the timestamp is got by themselves, they should not use this
        decorator in their own classes.
        """
        def wrapper(self, **kwargs):
            self._update_cpustat()
            return f(self, **kwargs), self._data.get("timestamp")
        return wrapper

    @add_timestamp
    def _get_cpu_frequency(self, **kwargs):
        return self._data.get("cpu.frequency")

    @add_timestamp
    def _get_cpu_user_time(self, **kwargs):
        return self._data.get("cpu.user.time")

    @add_timestamp
    def _get_cpu_kernel_time(self, **kwargs):
        return self._data.get("cpu.kernel.time")

    @add_timestamp
    def _get_cpu_idle_time(self, **kwargs):
        return self._data.get("cpu.idle.time")

    @add_timestamp
    def _get_cpu_iowait_time(self, **kwargs):
        return self._data.get("cpu.iowait.time")

    @add_timestamp
    def _get_cpu_user_percent(self, **kwargs):
        return self._data.get("cpu.user.percent")

    @add_timestamp
    def _get_cpu_kernel_percent(self, **kwargs):
        return self._data.get("cpu.kernel.percent")

    @add_timestamp
    def _get_cpu_idle_percent(self, **kwargs):
        return self._data.get("cpu.idle.percent")

    @add_timestamp
    def _get_cpu_iowait_percent(self, **kwargs):
        return self._data.get("cpu.iowait.percent")

    @add_timestamp
    def _get_cpu_percent(self, **kwargs):
        return self._data.get("cpu.percent")

    def _update_cpustat(self, **kwargs):
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
            LOG.exception(_("Not all properties needed are implemented "
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
