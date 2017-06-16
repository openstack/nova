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
class KeypairPayload(base.NotificationPayloadBase):
    SCHEMA = {
        'user_id': ('keypair', 'user_id'),
        'name': ('keypair', 'name'),
        'public_key': ('keypair', 'public_key'),
        'fingerprint': ('keypair', 'fingerprint'),
        'type': ('keypair', 'type')
    }
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'user_id': fields.StringField(nullable=True),
        'name': fields.StringField(nullable=False),
        'fingerprint': fields.StringField(nullable=True),
        'public_key': fields.StringField(nullable=True),
        'type': fields.StringField(nullable=False),
    }

    def __init__(self, keypair, **kwargs):
        super(KeypairPayload, self).__init__(**kwargs)
        self.populate_schema(keypair=keypair)


@base.notification_sample('keypair-create-start.json')
@base.notification_sample('keypair-create-end.json')
@nova_base.NovaObjectRegistry.register_notification
class KeypairNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('KeypairPayload')
    }
