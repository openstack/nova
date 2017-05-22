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
CPU monitor based on virt driver to retrieve CPU information
"""

from oslo_log import log as logging
from oslo_utils import timeutils

from nova.compute.monitors import base
import nova.conf
from nova import exception
from nova import objects

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class Monitor(base.CPUMonitorBase):
    """CPU monitor that uses the virt driver's get_host_cpu_stats() call."""

    def __init__(self, resource_tracker):
        super(Monitor, self).__init__(resource_tracker)
        self.source = CONF.compute_driver
        self.driver = resource_tracker.driver
        self._data = {}
        self._cpu_stats = {}

    def populate_metrics(self, metric_list):
        self._update_data()
        for name in self.get_metric_names():
            metric_object = objects.MonitorMetric()
            metric_object.name = name
            metric_object.value = self._data[name]
            metric_object.timestamp = self._data["timestamp"]
            metric_object.source = self.source
            metric_list.objects.append(metric_object)

    def _update_data(self):
        self._data = {}
        self._data["timestamp"] = timeutils.utcnow()

        # Extract node's CPU statistics.
        try:
            stats = self.driver.get_host_cpu_stats()
            self._data["cpu.user.time"] = stats["user"]
            self._data["cpu.kernel.time"] = stats["kernel"]
            self._data["cpu.idle.time"] = stats["idle"]
            self._data["cpu.iowait.time"] = stats["iowait"]
            self._data["cpu.frequency"] = stats["frequency"]
        except (TypeError, KeyError):
            LOG.exception("Not all properties needed are implemented "
                          "in the compute driver")
            raise exception.ResourceMonitorError(
                monitor=self.__class__.__name__)

        # The compute driver API returns the absolute values for CPU times.
        # We compute the utilization percentages for each specific CPU time
        # after calculating the delta between the current reading and the
        # previous reading.
        stats["total"] = (stats["user"] + stats["kernel"]
                          + stats["idle"] + stats["iowait"])
        cputime = float(stats["total"] - self._cpu_stats.get("total", 0))

        # NOTE(jwcroppe): Convert all the `perc` values to their integer forms
        # since pre-conversion their values are within the range [0, 1] and the
        # objects.MonitorMetric.value field requires an integer.
        perc = (stats["user"] - self._cpu_stats.get("user", 0)) / cputime
        self._data["cpu.user.percent"] = int(perc * 100)

        perc = (stats["kernel"] - self._cpu_stats.get("kernel", 0)) / cputime
        self._data["cpu.kernel.percent"] = int(perc * 100)

        perc = (stats["idle"] - self._cpu_stats.get("idle", 0)) / cputime
        self._data["cpu.idle.percent"] = int(perc * 100)

        perc = (stats["iowait"] - self._cpu_stats.get("iowait", 0)) / cputime
        self._data["cpu.iowait.percent"] = int(perc * 100)

        # Compute the current system-wide CPU utilization as a percentage.
        used = stats["user"] + stats["kernel"] + stats["iowait"]
        prev_used = (self._cpu_stats.get("user", 0)
                     + self._cpu_stats.get("kernel", 0)
                     + self._cpu_stats.get("iowait", 0))
        perc = (used - prev_used) / cputime
        self._data["cpu.percent"] = int(perc * 100)

        self._cpu_stats = stats.copy()
