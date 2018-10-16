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


@base.notification_sample('volume-usage.json')
@nova_base.NovaObjectRegistry.register_notification
class VolumeUsageNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('VolumeUsagePayload')
    }


@nova_base.NovaObjectRegistry.register_notification
class VolumeUsagePayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'volume_id': ('vol_usage', 'volume_id'),
        'project_id': ('vol_usage', 'project_id'),
        'user_id': ('vol_usage', 'user_id'),
        'availability_zone': ('vol_usage', 'availability_zone'),
        'instance_uuid': ('vol_usage', 'instance_uuid'),
        'last_refreshed': ('vol_usage', 'last_refreshed'),
        'reads': ('vol_usage', 'reads'),
        'read_bytes': ('vol_usage', 'read_bytes'),
        'writes': ('vol_usage', 'writes'),
        'write_bytes': ('vol_usage', 'write_bytes')
    }

    fields = {
        'volume_id': fields.UUIDField(),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'instance_uuid': fields.UUIDField(nullable=True),
        'last_refreshed': fields.DateTimeField(nullable=True),
        'reads': fields.IntegerField(),
        'read_bytes': fields.IntegerField(),
        'writes': fields.IntegerField(),
        'write_bytes': fields.IntegerField()
    }

    def __init__(self, vol_usage):
        super(VolumeUsagePayload, self).__init__()
        self.populate_schema(vol_usage=vol_usage)
