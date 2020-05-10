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

import abc

from nova.objects import fields


class MonitorBase(metaclass=abc.ABCMeta):
    """Base class for all resource monitor plugins.

    A monitor is responsible for adding a set of related metrics to
    a `nova.objects.MonitorMetricList` object after the monitor has
    performed some sampling or monitoring action.
    """

    def __init__(self, compute_manager):
        self.compute_manager = compute_manager
        self.source = None

    @abc.abstractmethod
    def get_metric_names(self):
        """Get available metric names.

        Get available metric names, which are represented by a set of keys
        that can be used to check conflicts and duplications

        :returns: set containing one or more values from
            :py:attr: nova.objects.fields.MonitorMetricType.ALL
        """
        raise NotImplementedError('get_metric_names')

    @abc.abstractmethod
    def populate_metrics(self, metric_list):
        """Monitors are responsible for populating this metric_list object
        with nova.objects.MonitorMetric objects with values collected via
        the respective compute drivers.

        Note that if the monitor class is responsible for tracking a *related*
        set of metrics -- e.g. a set of percentages of CPU time allocated to
        user, kernel, and idle -- it is the responsibility of the monitor
        implementation to do a single sampling call to the underlying monitor
        to ensure that related metric values make logical sense.

        :param metric_list: A mutable reference of the metric list object
        """
        raise NotImplementedError('populate_metrics')


class CPUMonitorBase(MonitorBase):
    """Base class for all monitors that return CPU-related metrics."""

    def get_metric_names(self):
        return set([
            fields.MonitorMetricType.CPU_FREQUENCY,
            fields.MonitorMetricType.CPU_USER_TIME,
            fields.MonitorMetricType.CPU_KERNEL_TIME,
            fields.MonitorMetricType.CPU_IDLE_TIME,
            fields.MonitorMetricType.CPU_IOWAIT_TIME,
            fields.MonitorMetricType.CPU_USER_PERCENT,
            fields.MonitorMetricType.CPU_KERNEL_PERCENT,
            fields.MonitorMetricType.CPU_IDLE_PERCENT,
            fields.MonitorMetricType.CPU_IOWAIT_PERCENT,
            fields.MonitorMetricType.CPU_PERCENT,
        ])
