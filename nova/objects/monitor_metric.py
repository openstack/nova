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

from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova.objects import base
from nova.objects import fields
from nova import utils


# NOTE(jwcroppe): Used to determine which fields whose value we need to adjust
# (read: divide by 100.0) before sending information to the RPC notifier since
# these values were expected to be within the range [0, 1].
FIELDS_REQUIRING_CONVERSION = [fields.MonitorMetricType.CPU_USER_PERCENT,
                               fields.MonitorMetricType.CPU_KERNEL_PERCENT,
                               fields.MonitorMetricType.CPU_IDLE_PERCENT,
                               fields.MonitorMetricType.CPU_IOWAIT_PERCENT,
                               fields.MonitorMetricType.CPU_PERCENT]


@base.NovaObjectRegistry.register
class MonitorMetric(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added NUMA support

    VERSION = '1.1'

    fields = {
        'name': fields.MonitorMetricTypeField(nullable=False),
        'value': fields.IntegerField(nullable=False),
        'numa_membw_values': fields.DictOfIntegersField(nullable=True),
        'timestamp': fields.DateTimeField(nullable=False),
        # This will be the stevedore extension full class name
        # for the plugin from which the metric originates.
        'source': fields.StringField(nullable=False),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(MonitorMetric, self).obj_make_compatible(primitive,
                                                       target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'numa_membw_values' in primitive:
            del primitive['numa_membw_values']

    # NOTE(jaypipes): This method exists to convert the object to the
    # format expected by the RPC notifier for metrics events.
    def to_dict(self):
        dict_to_return = {
            'name': self.name,
            # NOTE(jaypipes): This is what jsonutils.dumps() does to
            # datetime.datetime objects, which is what timestamp is in
            # this object as well as the original simple dict metrics
            'timestamp': utils.strtime(self.timestamp),
            'source': self.source,
        }

        if self.obj_attr_is_set('value'):
            if self.name in FIELDS_REQUIRING_CONVERSION:
                dict_to_return['value'] = self.value / 100.0
            else:
                dict_to_return['value'] = self.value
        elif self.obj_attr_is_set('numa_membw_values'):
            dict_to_return['numa_membw_values'] = self.numa_membw_values

        return dict_to_return


@base.NovaObjectRegistry.register
class MonitorMetricList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: MonitorMetric version 1.1
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('MonitorMetric'),
    }

    @classmethod
    def from_json(cls, metrics):
        """Converts a legacy json object into a list of MonitorMetric objs
        and finally returns of MonitorMetricList

        :param metrics: a string of json serialized objects
        :returns: a MonitorMetricList Object.
        """
        metrics = jsonutils.loads(metrics) if metrics else []

        # NOTE(suro-patz): While instantiating the MonitorMetric() from
        #                  JSON-ified string, we need to re-convert the
        #                  normalized metrics to avoid truncation to 0 by
        #                  typecasting into an integer.
        metric_list = []
        for metric in metrics:
            if ('value' in metric and metric['name'] in
                                      FIELDS_REQUIRING_CONVERSION):
                metric['value'] = metric['value'] * 100
            metric_list.append(MonitorMetric(**metric))

        return MonitorMetricList(objects=metric_list)

    # NOTE(jaypipes): This method exists to convert the object to the
    # format expected by the RPC notifier for metrics events.
    def to_list(self):
        return [m.to_dict() for m in self.objects]
