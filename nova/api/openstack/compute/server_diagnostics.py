# Copyright 2011 OpenStack Foundation
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

import webob

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.views import server_diagnostics
from nova.api.openstack import wsgi
from nova.compute import api as compute
from nova import exception
from nova.policies import server_diagnostics as sd_policies


class ServerDiagnosticsController(wsgi.Controller):
    _view_builder_class = server_diagnostics.ViewBuilder

    def __init__(self):
        super(ServerDiagnosticsController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.expected_errors((400, 404, 409, 501))
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        context.can(sd_policies.BASE_POLICY_NAME)

        instance = common.get_instance(self.compute_api, context, server_id)

        try:
            if api_version_request.is_supported(req, min_version='2.48'):
                diagnostics = self.compute_api.get_instance_diagnostics(
                    context, instance)
                return self._view_builder.instance_diagnostics(diagnostics)

            return self.compute_api.get_diagnostics(context, instance)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'get_diagnostics', server_id)
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            common.raise_feature_not_supported()
