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
from nova.i18n import _
from nova import utils

ALIAS = "os-instance-actions"
authorize = extensions.os_compute_authorizer(ALIAS)
soft_authorize = extensions.os_compute_soft_authorizer(ALIAS)

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

    @wsgi.Controller.api_version("2.1", "2.20")
    def _get_instance(self, req, context, server_id):
        return common.get_instance(self.compute_api, context, server_id)

    @wsgi.Controller.api_version("2.21")  # noqa
    def _get_instance(self, req, context, server_id):
        with utils.temporary_mutation(context, read_deleted='yes'):
            return common.get_instance(self.compute_api, context, server_id)

    @extensions.expected_errors(404)
    def index(self, req, server_id):
        """Returns the list of actions recorded for a given instance."""
        context = req.environ["nova.context"]
        instance = self._get_instance(req, context, server_id)
        authorize(context, target=instance)
        actions_raw = self.action_api.actions_get(context, instance)
        actions = [self._format_action(action) for action in actions_raw]
        return {'instanceActions': actions}

    @extensions.expected_errors(404)
    def show(self, req, server_id, id):
        """Return data about the given instance action."""
        context = req.environ['nova.context']
        instance = self._get_instance(req, context, server_id)
        authorize(context, target=instance)
        action = self.action_api.action_get_by_request_id(context, instance,
                                                          id)
        if action is None:
            msg = _("Action %s not found") % id
            raise exc.HTTPNotFound(explanation=msg)

        action_id = action['id']
        action = self._format_action(action)
        if soft_authorize(context, action='events'):
            events_raw = self.action_api.action_events_get(context, instance,
                                                           action_id)
            action['events'] = [self._format_event(evt) for evt in events_raw]
        return {'instanceAction': action}


class InstanceActions(extensions.V21APIExtensionBase):
    """View a log of actions and events taken on an instance."""

    name = "InstanceActions"
    alias = ALIAS
    version = 1

    def get_resources(self):
        ext = extensions.ResourceExtension(ALIAS,
                                           InstanceActionsController(),
                                           parent=dict(
                                               member_name='server',
                                               collection_name='servers'))
        return [ext]

    def get_controller_extensions(self):
        """It's an abstract function V21APIExtensionBase and the extension
        will not be loaded without it.
        """
        return []
