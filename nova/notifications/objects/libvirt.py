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
class LibvirtErrorPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'ip': fields.StringField(),
        'reason': fields.ObjectField('ExceptionPayload'),
    }

    def __init__(self, ip, reason):
        super(LibvirtErrorPayload, self).__init__()
        self.ip = ip
        self.reason = reason


@base.notification_sample('libvirt-connect-error.json')
@nova_base.NovaObjectRegistry.register_notification
class LibvirtErrorNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'payload': fields.ObjectField('LibvirtErrorPayload')
    }
