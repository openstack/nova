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


@nova_base.NovaObjectRegistry.register_notification
class FlavorPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'flavorid': ('flavor', 'flavorid'),
        'memory_mb': ('flavor', 'memory_mb'),
        'vcpus': ('flavor', 'vcpus'),
        'root_gb': ('flavor', 'root_gb'),
        'ephemeral_gb': ('flavor', 'ephemeral_gb'),
    }

    fields = {
        'flavorid': fields.StringField(nullable=True),
        'memory_mb': fields.IntegerField(nullable=True),
        'vcpus': fields.IntegerField(nullable=True),
        'root_gb': fields.IntegerField(nullable=True),
        'ephemeral_gb': fields.IntegerField(nullable=True),
    }

    def __init__(self, instance, **kwargs):
        super(FlavorPayload, self).__init__(**kwargs)
        self.populate_schema(instance=instance, flavor=instance.flavor)
