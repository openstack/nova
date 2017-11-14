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


@base.notification_sample('flavor-create.json')
@base.notification_sample('flavor-update.json')
@base.notification_sample('flavor-delete.json')
@nova_base.NovaObjectRegistry.register_notification
class FlavorNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('FlavorPayload')
    }


@nova_base.NovaObjectRegistry.register_notification
class FlavorPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    # Version 1.1: Add other fields for Flavor
    # Version 1.2: Add extra_specs and projects fields
    # Version 1.3: Make projects and extra_specs field nullable as they are
    # not always available when a notification is emitted.
    # Version 1.4: Added description field.
    VERSION = '1.4'

    # NOTE: if we'd want to rename some fields(memory_mb->ram, root_gb->disk,
    # ephemeral_gb: ephemeral), bumping to payload version 2.0 will be needed.
    SCHEMA = {
        'flavorid': ('flavor', 'flavorid'),
        'memory_mb': ('flavor', 'memory_mb'),
        'vcpus': ('flavor', 'vcpus'),
        'root_gb': ('flavor', 'root_gb'),
        'ephemeral_gb': ('flavor', 'ephemeral_gb'),
        'name': ('flavor', 'name'),
        'swap': ('flavor', 'swap'),
        'rxtx_factor': ('flavor', 'rxtx_factor'),
        'vcpu_weight': ('flavor', 'vcpu_weight'),
        'disabled': ('flavor', 'disabled'),
        'is_public': ('flavor', 'is_public'),
        'extra_specs': ('flavor', 'extra_specs'),
        'projects': ('flavor', 'projects'),
        'description': ('flavor', 'description')
    }

    fields = {
        'flavorid': fields.StringField(nullable=True),
        'memory_mb': fields.IntegerField(nullable=True),
        'vcpus': fields.IntegerField(nullable=True),
        'root_gb': fields.IntegerField(nullable=True),
        'ephemeral_gb': fields.IntegerField(nullable=True),
        'name': fields.StringField(),
        'swap': fields.IntegerField(),
        'rxtx_factor': fields.FloatField(nullable=True),
        'vcpu_weight': fields.IntegerField(nullable=True),
        'disabled': fields.BooleanField(),
        'is_public': fields.BooleanField(),
        'extra_specs': fields.DictOfStringsField(nullable=True),
        'projects': fields.ListOfStringsField(nullable=True),
        'description': fields.StringField(nullable=True)
    }

    def __init__(self, flavor):
        super(FlavorPayload, self).__init__()
        if 'projects' not in flavor:
            # NOTE(danms): If projects is not loaded in the flavor,
            # don't attempt to load it. If we're in a child cell then
            # we can't load the real flavor, and if we're a flavor on
            # an instance then we don't want to anyway.
            flavor = flavor.obj_clone()
            flavor._context = None
        self.populate_schema(flavor=flavor)
