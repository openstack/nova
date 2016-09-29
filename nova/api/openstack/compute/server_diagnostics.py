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

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.policies import server_diagnostics as sd_policies


ALIAS = "os-server-diagnostics"


class ServerDiagnosticsController(wsgi.Controller):
    def __init__(self):
        self.compute_api = compute.API()

    @extensions.expected_errors((404, 409, 501))
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        context.can(sd_policies.BASE_POLICY_NAME)

        instance = common.get_instance(self.compute_api, context, server_id)

        try:
            # NOTE(gmann): To make V21 same as V2 API, this method will call
            # 'get_diagnostics' instead of 'get_instance_diagnostics'.
            # In future, 'get_instance_diagnostics' needs to be called to
            # provide VM diagnostics in a defined format for all driver.
            # BP - https://blueprints.launchpad.net/nova/+spec/v3-diagnostics.
            return self.compute_api.get_diagnostics(context, instance)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'get_diagnostics', server_id)
        except exception.InstanceNotReady as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            common.raise_feature_not_supported()


class ServerDiagnostics(extensions.V21APIExtensionBase):
    """Allow Admins to view server diagnostics through server action."""

    name = "ServerDiagnostics"
    alias = ALIAS
    version = 1

    def get_resources(self):
        parent_def = {'member_name': 'server', 'collection_name': 'servers'}
        resources = [
            extensions.ResourceExtension('diagnostics',
                                         ServerDiagnosticsController(),
                                         parent=parent_def)]
        return resources

    def get_controller_extensions(self):
        return []
