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

import copy

from nova.notifications.objects import base
from nova.objects import base as nova_base
from nova.objects import fields


@nova_base.NovaObjectRegistry.register_notification
class ServerGroupPayload(base.NotificationPayloadBase):
    SCHEMA = {
        'uuid': ('group', 'uuid'),
        'name': ('group', 'name'),
        'user_id': ('group', 'user_id'),
        'project_id': ('group', 'project_id'),
        'policies': ('group', 'policies'),
        'members': ('group', 'members'),
        'hosts': ('group', 'hosts'),
        'policy': ('group', 'policy'),
        'rules': ('group', 'rules'),
    }
    # Version 1.0: Initial version
    # Version 1.1: Deprecate policies, add policy and add rules
    VERSION = '1.1'
    fields = {
        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),
        # NOTE(yikun): policies is deprecated and should
        # be removed on the next major version bump
        'policies': fields.ListOfStringsField(nullable=True),
        'members': fields.ListOfStringsField(nullable=True),
        'hosts': fields.ListOfStringsField(nullable=True),
        'policy': fields.StringField(nullable=True),
        'rules': fields.DictOfStringsField(),
    }

    def __init__(self, group):
        super(ServerGroupPayload, self).__init__()
        # Note: The group is orphaned here to avoid triggering lazy-loading of
        # the group.hosts field.
        cgroup = copy.deepcopy(group)
        cgroup._context = None
        self.populate_schema(group=cgroup)


@base.notification_sample('server_group-add_member.json')
@base.notification_sample('server_group-create.json')
@base.notification_sample('server_group-delete.json')
@nova_base.NovaObjectRegistry.register_notification
class ServerGroupNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('ServerGroupPayload')
    }
