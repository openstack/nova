#   Copyright 2011 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas.v3 import reset_server_state
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova.compute import vm_states
from nova import exception

ALIAS = "os-admin-actions"

# States usable in resetState action
# NOTE: It is necessary to update the schema of nova/api/openstack/compute/
# schemas/v3/reset_server_state.py, when updating this state_map.
state_map = dict(active=vm_states.ACTIVE, error=vm_states.ERROR)


def authorize(context, action_name):
    action = 'v3:%s:%s' % (ALIAS, action_name)
    extensions.extension_authorizer('compute', action)(context)


class AdminActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(AdminActionsController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.response(202)
    @extensions.expected_errors((404, 409))
    @wsgi.action('resetNetwork')
    def _reset_network(self, req, id, body):
        """Permit admins to reset networking on a server."""
        context = req.environ['nova.context']
        authorize(context, 'reset_network')
        try:
            instance = common.get_instance(self.compute_api, context, id,
                                           want_objects=True)
            self.compute_api.reset_network(context, instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

    @wsgi.response(202)
    @extensions.expected_errors((404, 409))
    @wsgi.action('injectNetworkInfo')
    def _inject_network_info(self, req, id, body):
        """Permit admins to inject network info into a server."""
        context = req.environ['nova.context']
        authorize(context, 'inject_network_info')
        try:
            instance = common.get_instance(self.compute_api, context, id,
                                           want_objects=True)
            self.compute_api.inject_network_info(context, instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

    @wsgi.response(202)
    @extensions.expected_errors((400, 404))
    @wsgi.action('os-resetState')
    @validation.schema(reset_server_state.reset_state)
    def _reset_state(self, req, id, body):
        """Permit admins to reset the state of a server."""
        context = req.environ["nova.context"]
        authorize(context, 'reset_state')

        # Identify the desired state from the body
        state = state_map[body["os-resetState"]["state"]]

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        instance.vm_state = state
        instance.task_state = None
        instance.save(admin_state_reset=True)


class AdminActions(extensions.V3APIExtensionBase):
    """Enable admin-only server actions

    Actions include: pause, unpause, suspend, resume, migrate,
    reset_network, inject_network_info, lock, unlock, create_backup
    """

    name = "AdminActions"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = AdminActionsController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
