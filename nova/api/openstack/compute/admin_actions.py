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
from nova.api.openstack.compute.schemas import reset_server_state
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova.compute import vm_states
from nova import exception
from nova.policies import admin_actions as aa_policies

# States usable in resetState action
# NOTE: It is necessary to update the schema of nova/api/openstack/compute/
# schemas/reset_server_state.py, when updating this state_map.
state_map = dict(active=vm_states.ACTIVE, error=vm_states.ERROR)


class AdminActionsController(wsgi.Controller):
    def __init__(self):
        super(AdminActionsController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('resetNetwork')
    def _reset_network(self, req, id, body):
        """Permit admins to reset networking on a server."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(aa_policies.POLICY_ROOT % 'reset_network',
                    target={'project_id': instance.project_id})
        try:
            self.compute_api.reset_network(context, instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('injectNetworkInfo')
    def _inject_network_info(self, req, id, body):
        """Permit admins to inject network info into a server."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(aa_policies.POLICY_ROOT % 'inject_network_info',
                    target={'project_id': instance.project_id})
        try:
            self.compute_api.inject_network_info(context, instance)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors(404)
    @wsgi.action('os-resetState')
    @validation.schema(reset_server_state.reset_state)
    def _reset_state(self, req, id, body):
        """Permit admins to reset the state of a server."""
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, id)
        context.can(aa_policies.POLICY_ROOT % 'reset_state',
                    target={'project_id': instance.project_id})

        # Identify the desired state from the body
        state = state_map[body["os-resetState"]["state"]]

        instance.vm_state = state
        instance.task_state = None
        instance.save(admin_state_reset=True)
