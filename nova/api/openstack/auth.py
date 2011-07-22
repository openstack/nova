# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import hashlib
import time

import webob.exc
import webob.dec

from nova import auth
from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova import wsgi
from nova.api.openstack import faults

LOG = logging.getLogger('nova.api.openstack')
FLAGS = flags.FLAGS


class AuthMiddleware(wsgi.Middleware):
    """Authorize the openstack API request or return an HTTP Forbidden."""

    def __init__(self, application, db_driver=None):
        if not db_driver:
            db_driver = FLAGS.db_driver
        self.db = utils.import_object(db_driver)
        self.auth = auth.manager.AuthManager()
        super(AuthMiddleware, self).__init__(application)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if not self.has_authentication(req):
            return self.authenticate(req)
        user_id = self.get_user_by_authentication(req)
        if not user_id:
            token = req.headers["X-Auth-Token"]
            msg = _("%(user_id)s could not be found with token '%(token)s'")
            LOG.warn(msg % locals())
            return faults.Fault(webob.exc.HTTPUnauthorized())

        try:
            project_id = req.headers["X-Auth-Project-Id"]
        except KeyError:
            # FIXME(usrleon): It needed only for compatibility
            # while osapi clients don't use this header
            projects = self.auth.get_projects(user_id)
            if projects:
                project_id = projects[0].id
            else:
                return faults.Fault(webob.exc.HTTPUnauthorized())

        is_admin = self.auth.is_admin(user_id)
        req.environ['nova.context'] = context.RequestContext(user_id,
                                                             project_id,
                                                             is_admin)
        if not is_admin and not self.auth.is_project_member(user_id,
                                                            project_id):
            msg = _("%(user_id)s must be an admin or a "
                    "member of %(project_id)s")
            LOG.warn(msg % locals())
            return faults.Fault(webob.exc.HTTPUnauthorized())

        return self.application

    def has_authentication(self, req):
        return 'X-Auth-Token' in req.headers

    def get_user_by_authentication(self, req):
        return self.authorize_token(req.headers["X-Auth-Token"])

    def authenticate(self, req):
        # Unless the request is explicitly made against /<version>/ don't
        # honor it
        path_info = req.path_info
        if len(path_info) > 1:
            msg = _("Authentication requests must be made against a version "
                    "root (e.g. /v1.0 or /v1.1).")
            LOG.warn(msg)
            return faults.Fault(webob.exc.HTTPUnauthorized(explanation=msg))

        try:
            username = req.headers['X-Auth-User']
            key = req.headers['X-Auth-Key']
        except KeyError as ex:
            LOG.warn(_("Could not find %s in request.") % ex)
            return faults.Fault(webob.exc.HTTPUnauthorized())

        token, user = self._authorize_user(username, key, req)
        if user and token:
            res = webob.Response()
            res.headers['X-Auth-Token'] = token['token_hash']
            res.headers['X-Server-Management-Url'] = \
                token['server_management_url']
            res.headers['X-Storage-Url'] = token['storage_url']
            res.headers['X-CDN-Management-Url'] = token['cdn_management_url']
            res.content_type = 'text/plain'
            res.status = '204'
            LOG.debug(_("Successfully authenticated '%s'") % username)
            return res
        else:
            return faults.Fault(webob.exc.HTTPUnauthorized())

    def authorize_token(self, token_hash):
        """ retrieves user information from the datastore given a token

        If the token has expired, returns None
        If the token is not found, returns None
        Otherwise returns dict(id=(the authorized user's id))

        This method will also remove the token if the timestamp is older than
        2 days ago.
        """
        ctxt = context.get_admin_context()
        try:
            token = self.db.auth_token_get(ctxt, token_hash)
        except exception.NotFound:
            return None
        if token:
            delta = utils.utcnow() - token['created_at']
            if delta.days >= 2:
                self.db.auth_token_destroy(ctxt, token['token_hash'])
            else:
                return token['user_id']
        return None

    def _authorize_user(self, username, key, req):
        """Generates a new token and assigns it to a user.

        username - string
        key - string API key
        req - wsgi.Request object
        """
        ctxt = context.get_admin_context()

        try:
            user = self.auth.get_user_from_access_key(key)
        except exception.NotFound:
            LOG.warn(_("User not found with provided API key."))
            user = None

        if user and user.name == username:
            token_hash = hashlib.sha1('%s%s%f' % (username, key,
                time.time())).hexdigest()
            token_dict = {}
            token_dict['token_hash'] = token_hash
            token_dict['cdn_management_url'] = ''
            os_url = req.url
            token_dict['server_management_url'] = os_url
            token_dict['storage_url'] = ''
            token_dict['user_id'] = user.id
            token = self.db.auth_token_create(ctxt, token_dict)
            return token, user
        elif user and user.name != username:
            msg = _("Provided API key is valid, but not for user "
                    "'%(username)s'") % locals()
            LOG.warn(msg)

        return None, None
