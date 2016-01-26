# Copyright 2013 IBM Corp.
# Copyright 2010 OpenStack Foundation
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

from oslo_config import cfg
import webob.dec
import webob.exc

from nova.api.openstack import wsgi
from nova import context
from nova import wsgi as base_wsgi

CONF = cfg.CONF
CONF.import_opt('use_forwarded_for', 'nova.api.auth')


class NoAuthMiddlewareBase(base_wsgi.Middleware):
    """Return a fake token if one isn't specified."""

    def base_call(self, req, project_id_in_path, always_admin=True):
        if 'X-Auth-Token' not in req.headers:
            user_id = req.headers.get('X-Auth-User', 'admin')
            project_id = req.headers.get('X-Auth-Project-Id', 'admin')
            if project_id_in_path:
                os_url = '/'.join([req.url.rstrip('/'), project_id])
            else:
                os_url = req.url.rstrip('/')
            res = webob.Response()
            # NOTE(vish): This is expecting and returning Auth(1.1), whereas
            #             keystone uses 2.0 auth.  We should probably allow
            #             2.0 auth here as well.
            res.headers['X-Auth-Token'] = '%s:%s' % (user_id, project_id)
            res.headers['X-Server-Management-Url'] = os_url
            res.content_type = 'text/plain'
            res.status = '204'
            return res

        token = req.headers['X-Auth-Token']
        user_id, _sep, project_id = token.partition(':')
        project_id = project_id or user_id
        remote_address = getattr(req, 'remote_address', '127.0.0.1')
        if CONF.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)
        is_admin = always_admin or (user_id == 'admin')
        ctx = context.RequestContext(user_id,
                                     project_id,
                                     is_admin=is_admin,
                                     remote_address=remote_address)

        req.environ['nova.context'] = ctx
        return self.application


class NoAuthMiddleware(NoAuthMiddlewareBase):
    """Return a fake token if one isn't specified.

    noauth2 provides admin privs if 'admin' is provided as the user id.

    """
    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        return self.base_call(req, True, always_admin=False)


class NoAuthMiddlewareV2_18(NoAuthMiddlewareBase):
    """Return a fake token if one isn't specified.

    This provides a version of the middleware which does not add
    project_id into server management urls.

    """

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        return self.base_call(req, False, always_admin=False)
