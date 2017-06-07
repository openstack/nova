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


from oslo_context import context
from oslo_db.sqlalchemy import enginefacade
from oslo_log import log as logging
from oslo_middleware import request_id
import webob.dec
import webob.exc


LOG = logging.getLogger(__name__)


class Middleware(object):

    def __init__(self, application, **kwargs):
        self.application = application


# NOTE(cdent): Only to be used in tests where auth is being faked.
class NoAuthMiddleware(Middleware):
    """Require a token if one isn't present."""

    def __init__(self, application):
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req):
        if 'X-Auth-Token' not in req.headers:
            return webob.exc.HTTPUnauthorized()

        token = req.headers['X-Auth-Token']
        user_id, _sep, project_id = token.partition(':')
        project_id = project_id or user_id
        if user_id == 'admin':
            roles = ['admin']
        else:
            roles = []
        req.headers['X_USER_ID'] = user_id
        req.headers['X_TENANT_ID'] = project_id
        req.headers['X_ROLES'] = ','.join(roles)
        return self.application


@enginefacade.transaction_context_provider
class RequestContext(context.RequestContext):
    pass


class PlacementKeystoneContext(Middleware):
    """Make a request context from keystone headers."""

    @webob.dec.wsgify
    def __call__(self, req):
        req_id = req.environ.get(request_id.ENV_REQUEST_ID)

        ctx = RequestContext.from_environ(
            req.environ, request_id=req_id)

        if ctx.user_id is None:
            LOG.debug("Neither X_USER_ID nor X_USER found in request")
            return webob.exc.HTTPUnauthorized()

        req.environ['placement.context'] = ctx
        return self.application
