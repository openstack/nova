#    Copyright 2018 NTT Corporation
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

from nova.notifications.objects import base
from nova.objects import base as nova_base
from nova.objects import fields


@base.notification_sample('metrics-update.json')
@nova_base.NovaObjectRegistry.register_notification
class MetricsNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('MetricsPayload')
    }


@nova_base.NovaObjectRegistry.register_notification
class MetricPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'name': ('monitor_metric', 'name'),
        'value': ('monitor_metric', 'value'),
        'numa_membw_values': ('monitor_metric', 'numa_membw_values'),
        'timestamp': ('monitor_metric', 'timestamp'),
        'source': ('monitor_metric', 'source'),
    }

    fields = {
        'name': fields.MonitorMetricTypeField(),
        'value': fields.IntegerField(),
        'numa_membw_values': fields.DictOfIntegersField(nullable=True),
        'timestamp': fields.DateTimeField(),
        'source': fields.StringField(),
    }

    def __init__(self, monitor_metric):
        super(MetricPayload, self).__init__()
        self.populate_schema(monitor_metric=monitor_metric)

    @classmethod
    def from_monitor_metric_list_obj(cls, monitor_metric_list):
        """Returns a list of MetricPayload objects based on the passed
        MonitorMetricList object.
        """
        payloads = []
        for monitor_metric in monitor_metric_list:
            payloads.append(cls(monitor_metric))
        return payloads


@nova_base.NovaObjectRegistry.register_notification
class MetricsPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'host': fields.StringField(),
        'host_ip': fields.StringField(),
        'nodename': fields.StringField(),
        'metrics': fields.ListOfObjectsField('MetricPayload'),
    }

    def __init__(self, host, host_ip, nodename, monitor_metric_list):
        super(MetricsPayload, self).__init__()
        self.host = host
        self.host_ip = host_ip
        self.nodename = nodename
        self.metrics = MetricPayload.from_monitor_metric_list_obj(
            monitor_metric_list)
