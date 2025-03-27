# Copyright 2013 Cloudbase Solutions Srl
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
from nova.api.openstack.compute.schemas import console_auth_tokens as schema
from nova.api.openstack import wsgi
from nova.api import validation
import nova.conf
from nova import context as nova_context
from nova.i18n import _
from nova import objects
from nova.policies import console_auth_tokens as cat_policies

CONF = nova.conf.CONF


class ConsoleAuthTokensController(wsgi.Controller):

    @wsgi.expected_errors((400, 401, 404), '2.1', '2.30')
    @wsgi.expected_errors((400, 404), '2.31', '2.98')
    @wsgi.expected_errors((400, 404), '2.99')
    @validation.query_schema(schema.show_query, '2.1', '2.98')
    @validation.query_schema(schema.show_query_v299, '2.99')
    # NOTE(stephenfin): Technically this will never return a response now for
    # microversion <= 2.30, (as an exception will be raised instead) but we use
    # the same schema for documentation purposes
    @validation.response_body_schema(schema.show_response, '2.1', '2.98')
    @validation.response_body_schema(schema.show_response_v299, '2.99')
    def show(self, req, id):
        """Show console auth token.

        Until microversion 2.30, this API was available only for the rdp-html5
        console type which has been removed along with the HyperV driver in the
        Nova 29.0.0 (Caracal) release. As a result, we now return a HTTP 400
        error for microversion <= 2.30. Starting from 2.31 microversion, this
        API works for all the other supported console types.
        """
        if not api_version_request.is_supported(req, '2.31'):
            raise webob.exc.HTTPBadRequest()

        include_tls_port = False
        if api_version_request.is_supported(req, '2.99'):
            include_tls_port = True

        return self._show(req, id, include_tls_port=include_tls_port)

    def _show(self, req, id, include_tls_port=False):
        """Checks a console auth token and returns the related connect info."""
        context = req.environ['nova.context']
        context.can(cat_policies.BASE_POLICY_NAME)

        token = id
        if not token:
            msg = _("token not provided")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        connect_info = None

        results = nova_context.scatter_gather_skip_cell0(
            context, objects.ConsoleAuthToken.validate, token)
        # NOTE(melwitt): Console token auths are stored in cell databases,
        # but with only the token as a request param, we can't know which
        # cell database contains the token's corresponding connection info.
        # So, we must query all cells for the info and we can break the
        # loop as soon as we find a result because the token is associated
        # with one instance, which can only be in one cell.
        for result in results.values():
            if not nova_context.is_cell_failure_sentinel(result):
                connect_info = result
                break

        if not connect_info:
            raise webob.exc.HTTPNotFound(explanation=_("Token not found"))

        retval = {
            'console': {
                'instance_uuid': connect_info.instance_uuid,
                'host': connect_info.host,
                'port': connect_info.port,
                'internal_access_path': connect_info.internal_access_path,
            }
        }

        if connect_info.console_type == 'spice-direct' and include_tls_port:
            retval['console']['tls_port'] = connect_info.tls_port

        return retval
