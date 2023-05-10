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


from oslo_log import log as logging
from oslo_utils import timeutils

from nova.compute.monitors import base
import nova.conf
from nova import exception
from nova import objects

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class Monitor(base.VmwareMonitorBase):
    def __init__(self, resource_tracker):
        super(Monitor, self).__init__(resource_tracker)
        self.source = CONF.compute_driver
        self.driver = resource_tracker.driver
        self._data = {}

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
        try:
            metric_stats = self.driver.get_cluster_metrics()
            self._data['storage.percent.usage'] = (
                metric_stats['datastore_percent'])
            self._data['storage.total'] = metric_stats['datastore_total']
            self._data['storage.used'] = metric_stats['datastore_used']
            self._data['storage.free'] = metric_stats['datastore_free']
            self._data['cpu.total'] = metric_stats['cpu_total']
            self._data['cpu.used'] = metric_stats['cpu_used']
            self._data['cpu.free'] = metric_stats['cpu_free']
            self._data['cpu.percent.used'] = metric_stats['cpu_percent']
            self._data['memory.total'] = metric_stats['memory_total']
            self._data['memory.used'] = metric_stats['memory_used']
            self._data['memory.free'] = metric_stats['memory_free']
            self._data['memory.percent'] = metric_stats['memory_percent']

            LOG.info("Cluster metrics: %s", self._data)

        except (NotImplementedError, TypeError, KeyError):
            LOG.exception("Not all properties needed are implemented "
                          "in the compute driver")
            raise exception.ResourceMonitorError(
                monitor=self.__class__.__name__)
