# Copyright 2013 IBM Corp.
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
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.policies import suspend_server as ss_policies


class SuspendServerController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(SuspendServerController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('suspend')
    def _suspend(self, req, id, body):
        """Permit admins to suspend the server."""
        context = req.environ['nova.context']
        server = common.get_instance(self.compute_api, context, id)
        try:
            context.can(ss_policies.POLICY_ROOT % 'suspend',
                        target={'user_id': server.user_id,
                                'project_id': server.project_id})
            self.compute_api.suspend(context, server)
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'suspend', id)

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('resume')
    def _resume(self, req, id, body):
        """Permit admins to resume the server from suspend."""
        context = req.environ['nova.context']
        context.can(ss_policies.POLICY_ROOT % 'resume')
        server = common.get_instance(self.compute_api, context, id)
        try:
            self.compute_api.resume(context, server)
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'resume', id)
