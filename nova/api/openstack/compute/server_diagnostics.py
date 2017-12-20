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
from nova import compute
from nova import exception
from nova.i18n import _
from nova.policies import server_diagnostics as sd_policies


class ServerDiagnosticsController(wsgi.Controller):
    _view_builder_class = server_diagnostics.ViewBuilder

    def __init__(self, *args, **kwargs):
        super(ServerDiagnosticsController, self).__init__(*args, **kwargs)
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
        except exception.InstanceDiagnosticsNotSupported:
            # NOTE(snikitin): During upgrade we may face situation when env
            # has new API and old compute. New compute returns a
            # Diagnostics object. Old compute returns a dictionary. So we
            # can't perform a request correctly if compute is too old.
            msg = _('Compute node is too old. You must complete the '
                    'upgrade process to be able to get standardized '
                    'diagnostics data which is available since v2.48. However '
                    'you are still able to get diagnostics data in '
                    'non-standardized format which is available until v2.47.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except NotImplementedError:
            common.raise_feature_not_supported()
