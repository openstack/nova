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

from oslo_utils import timeutils

from nova.objects import base
from nova.objects import fields
from nova import utils


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
        target_version = utils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'numa_nodes_values' in primitive:
            del primitive['numa_membw_values']

    # NOTE(jaypipes): This method exists to convert the object to the
    # format expected by the RPC notifier for metrics events.
    def to_dict(self):
        dict_to_return = {
            'name': self.name,
            # NOTE(jaypipes): This is what jsonutils.dumps() does to
            # datetime.datetime objects, which is what timestamp is in
            # this object as well as the original simple dict metrics
            'timestamp': timeutils.strtime(self.timestamp),
            'source': self.source,
        }

        if self.obj_attr_is_set('value'):
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
    obj_relationships = {
        'objects': [('1.0', '1.0'), ('1.1', '1.1')],
    }

    # NOTE(jaypipes): This method exists to convert the object to the
    # format expected by the RPC notifier for metrics events.
    def to_list(self):
        return [m.to_dict() for m in self.objects]
