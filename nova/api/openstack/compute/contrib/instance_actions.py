# Copyright 2013 Rackspace Hosting
# All Rights Reserved.
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

from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute

authorize_actions = extensions.extension_authorizer('compute',
                                                    'instance_actions')
authorize_events = extensions.soft_extension_authorizer('compute',
                                                    'instance_actions:events')

ACTION_KEYS = ['action', 'instance_uuid', 'request_id', 'user_id',
               'project_id', 'start_time', 'message']
EVENT_KEYS = ['event', 'start_time', 'finish_time', 'result', 'traceback']


class InstanceActionsController(wsgi.Controller):

    def __init__(self):
        super(InstanceActionsController, self).__init__()
        self.compute_api = compute.API()
        self.action_api = compute.InstanceActionAPI()

    def _format_action(self, action_raw):
        action = {}
        for key in ACTION_KEYS:
            action[key] = action_raw.get(key)
        return action

    def _format_event(self, event_raw):
        event = {}
        for key in EVENT_KEYS:
            event[key] = event_raw.get(key)
        return event

    def index(self, req, server_id):
        """Returns the list of actions recorded for a given instance."""
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, server_id)
        authorize_actions(context, target=instance)
        actions_raw = self.action_api.actions_get(context, instance)
        actions = [self._format_action(action) for action in actions_raw]
        return {'instanceActions': actions}

    def show(self, req, server_id, id):
        """Return data about the given instance action."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        authorize_actions(context, target=instance)
        action = self.action_api.action_get_by_request_id(context, instance,
                                                          id)
        if action is None:
            raise exc.HTTPNotFound()

        action_id = action['id']
        action = self._format_action(action)
        if authorize_events(context):
            events_raw = self.action_api.action_events_get(context, instance,
                                                           action_id)
            action['events'] = [self._format_event(evt) for evt in events_raw]
        return {'instanceAction': action}


class Instance_actions(extensions.ExtensionDescriptor):
    """View a log of actions and events taken on an instance."""

    name = "InstanceActions"
    alias = "os-instance-actions"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "instance-actions/api/v1.1")
    updated = "2013-02-08T00:00:00Z"

    def get_resources(self):
        ext = extensions.ResourceExtension('os-instance-actions',
                                           InstanceActionsController(),
                                           parent=dict(
                                               member_name='server',
                                               collection_name='servers'))
        return [ext]
