# Copyright 2011 OpenStack Foundation
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
from nova.policies import pause_server as ps_policies


class PauseServerController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(PauseServerController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409, 501))
    @wsgi.action('pause')
    def _pause(self, req, id, body):
        """Permit Admins to pause the server."""
        ctxt = req.environ['nova.context']
        server = common.get_instance(self.compute_api, ctxt, id)
        ctxt.can(ps_policies.POLICY_ROOT % 'pause',
                 target={'user_id': server.user_id,
                         'project_id': server.project_id})
        try:
            self.compute_api.pause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'pause', id)
        except (exception.InstanceUnknownCell,
                     exception.InstanceNotFound) as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except NotImplementedError:
            common.raise_feature_not_supported()

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409, 501))
    @wsgi.action('unpause')
    def _unpause(self, req, id, body):
        """Permit Admins to unpause the server."""
        ctxt = req.environ['nova.context']
        ctxt.can(ps_policies.POLICY_ROOT % 'unpause')
        server = common.get_instance(self.compute_api, ctxt, id)
        try:
            self.compute_api.unpause(ctxt, server)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'unpause', id)
        except (exception.InstanceUnknownCell,
                     exception.InstanceNotFound) as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except NotImplementedError:
            common.raise_feature_not_supported()
