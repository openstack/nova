# Copyright (c) 2011 OpenStack Foundation
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
"""
Common Auth Middleware.

"""

from oslo_log import log as logging
from oslo_log import versionutils
from oslo_serialization import jsonutils
import webob.dec
import webob.exc

import nova.conf
from nova import context
from nova.i18n import _
from nova import wsgi


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def _load_pipeline(loader, pipeline):
    filters = [loader.get_filter(n) for n in pipeline[:-1]]
    app = loader.get_app(pipeline[-1])
    filters.reverse()
    for filter in filters:
        app = filter(app)
    return app


def pipeline_factory(loader, global_conf, **local_conf):
    """A paste pipeline replica that keys off of auth_strategy."""
    versionutils.report_deprecated_feature(
        LOG,
        "The legacy V2 API code tree has been removed in Newton. "
        "Please remove legacy v2 API entry from api-paste.ini, and use "
        "V2.1 API or V2.1 API compat mode instead"
    )


def pipeline_factory_v21(loader, global_conf, **local_conf):
    """A paste pipeline replica that keys off of auth_strategy."""
    return _load_pipeline(loader, local_conf[CONF.api.auth_strategy].split())


class InjectContext(wsgi.Middleware):
    """Add a 'nova.context' to WSGI environ."""

    def __init__(self, context, *args, **kwargs):
        self.context = context
        super(InjectContext, self).__init__(*args, **kwargs)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        req.environ['nova.context'] = self.context
        return self.application


class NovaKeystoneContext(wsgi.Middleware):
    """Make a request context from keystone headers."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        # Build a context, including the auth_token...
        remote_address = req.remote_addr
        if CONF.api.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)

        service_catalog = None
        if req.headers.get('X_SERVICE_CATALOG') is not None:
            try:
                catalog_header = req.headers.get('X_SERVICE_CATALOG')
                service_catalog = jsonutils.loads(catalog_header)
            except ValueError:
                raise webob.exc.HTTPInternalServerError(
                          _('Invalid service catalog json.'))

        # NOTE(jamielennox): This is a full auth plugin set by auth_token
        # middleware in newer versions.
        user_auth_plugin = req.environ.get('keystone.token_auth')

        ctx = context.RequestContext.from_environ(
            req.environ,
            user_auth_plugin=user_auth_plugin,
            remote_address=remote_address,
            service_catalog=service_catalog)

        if ctx.user_id is None:
            LOG.debug("Neither X_USER_ID nor X_USER found in request")
            return webob.exc.HTTPUnauthorized()

        req.environ['nova.context'] = ctx
        return self.application
