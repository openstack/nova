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

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import networks_associate
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.i18n import _
from nova import network
from nova.policies import networks_associate as na_policies


class NetworkAssociateActionController(wsgi.Controller):
    """Network Association API Controller."""

    def __init__(self, network_api=None):
        self.network_api = network_api or network.API()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.action("disassociate_host")
    @wsgi.response(202)
    @wsgi.expected_errors((404, 501))
    def _disassociate_host_only(self, req, id, body):
        context = req.environ['nova.context']
        context.can(na_policies.BASE_POLICY_NAME)
        try:
            self.network_api.associate(context, id, host=None)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        except NotImplementedError:
            common.raise_feature_not_supported()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.action("disassociate_project")
    @wsgi.response(202)
    @wsgi.expected_errors((404, 501))
    def _disassociate_project_only(self, req, id, body):
        context = req.environ['nova.context']
        context.can(na_policies.BASE_POLICY_NAME)
        try:
            self.network_api.associate(context, id, project=None)
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        except NotImplementedError:
            common.raise_feature_not_supported()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.action("associate_host")
    @wsgi.response(202)
    @wsgi.expected_errors((404, 501))
    @validation.schema(networks_associate.associate_host)
    def _associate_host(self, req, id, body):
        context = req.environ['nova.context']
        context.can(na_policies.BASE_POLICY_NAME)

        try:
            self.network_api.associate(context, id,
                                       host=body['associate_host'])
        except exception.NetworkNotFound:
            msg = _("Network not found")
            raise exc.HTTPNotFound(explanation=msg)
        except NotImplementedError:
            common.raise_feature_not_supported()
