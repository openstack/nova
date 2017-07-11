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
from nova.notifications.objects import request_spec as reqspec_payload
from nova.objects import base as nova_base
from nova.objects import fields


@nova_base.NovaObjectRegistry.register_notification
class ComputeTaskPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'instance_uuid': fields.UUIDField(),
        # There are some cases that request_spec is None.
        # e.g. Old instances can still have no RequestSpec object
        # attached to them.
        'request_spec': fields.ObjectField('RequestSpecPayload',
                                           nullable=True),
        'state': fields.InstanceStateField(nullable=True),
        'reason': fields.ObjectField('ExceptionPayload')
    }

    def __init__(self, instance_uuid, request_spec, state, reason):
        super(ComputeTaskPayload, self).__init__()
        self.instance_uuid = instance_uuid
        self.request_spec = reqspec_payload.RequestSpecPayload(
            request_spec) if request_spec is not None else None
        self.state = state
        self.reason = reason


@base.notification_sample('compute_task-build_instances-error.json')
@base.notification_sample('compute_task-migrate_server-error.json')
@base.notification_sample('compute_task-rebuild_server-error.json')
@nova_base.NovaObjectRegistry.register_notification
class ComputeTaskNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('ComputeTaskPayload')
    }
