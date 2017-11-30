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


from keystonemiddleware import auth_token
from oslo_log import log as logging
from oslo_middleware import request_id
import webob.dec
import webob.exc

from nova.api.openstack.placement import context

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
        if req.environ['PATH_INFO'] == '/':
            return self.application

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


class PlacementKeystoneContext(Middleware):
    """Make a request context from keystone headers."""

    @webob.dec.wsgify
    def __call__(self, req):
        req_id = req.environ.get(request_id.ENV_REQUEST_ID)

        ctx = context.RequestContext.from_environ(
            req.environ, request_id=req_id)

        if ctx.user_id is None and req.environ['PATH_INFO'] != '/':
            LOG.debug("Neither X_USER_ID nor X_USER found in request")
            return webob.exc.HTTPUnauthorized()

        req.environ['placement.context'] = ctx
        return self.application


class PlacementAuthProtocol(auth_token.AuthProtocol):
    """A wrapper on Keystone auth_token middleware.

    Does not perform verification of authentication tokens
    for root in the API.

    """
    def __init__(self, app, conf):
        self._placement_app = app
        super(PlacementAuthProtocol, self).__init__(app, conf)

    def __call__(self, environ, start_response):
        if environ['PATH_INFO'] == '/':
            return self._placement_app(environ, start_response)

        return super(PlacementAuthProtocol, self).__call__(
            environ, start_response)


def filter_factory(global_conf, **local_conf):
    conf = global_conf.copy()
    conf.update(local_conf)

    def auth_filter(app):
        return PlacementAuthProtocol(app, conf)
    return auth_filter
