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


@base.NovaObjectRegistry.register
class MonitorMetric(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'name': fields.MonitorMetricTypeField(nullable=False),
        'value': fields.IntegerField(nullable=False),
        'timestamp': fields.DateTimeField(nullable=False),
        # This will be the stevedore extension full class name
        # for the plugin from which the metric originates.
        'source': fields.StringField(nullable=False),
    }

    # NOTE(jaypipes): This method exists to convert the object to the
    # format expected by the RPC notifier for metrics events.
    def to_dict(self):
        return {
            'name': self.name,
            'value': self.value,
            # NOTE(jaypipes): This is what jsonutils.dumps() does to
            # datetime.datetime objects, which is what timestamp is in
            # this object as well as the original simple dict metrics
            'timestamp': timeutils.strtime(self.timestamp),
            'source': self.source
        }


@base.NovaObjectRegistry.register
class MonitorMetricList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('MonitorMetric'),
    }
    child_versions = {
        '1.0': '1.0',
    }

    # NOTE(jaypipes): This method exists to convert the object to the
    # format expected by the RPC notifier for metrics events.
    def to_list(self):
        return [m.to_dict() for m in self.objects]
