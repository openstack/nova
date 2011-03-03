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
#    under the License.import datetime

import datetime
import hashlib
import json
import time

import webob.exc
import webob.dec

from nova import auth
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
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

    @webob.dec.wsgify
    def __call__(self, req):
        if not self.has_authentication(req):
            return self.authenticate(req)
        user = self.get_user_by_authentication(req)
        account_name = req.path_info_peek()

        if not user:
            return faults.Fault(webob.exc.HTTPUnauthorized())

        if not account_name:
            if self.auth.is_admin(user):
                account_name = FLAGS.default_project
            else:
                return faults.Fault(webob.exc.HTTPUnauthorized())
        try:
            account = self.auth.get_project(account_name)
        except exception.NotFound:
            return faults.Fault(webob.exc.HTTPUnauthorized())

        if not self.auth.is_admin(user) and \
           not self.auth.is_project_member(user, account):
            return faults.Fault(webob.exc.HTTPUnauthorized())

        req.environ['nova.context'] = context.RequestContext(user, account)
        return self.application

    def has_authentication(self, req):
        return 'X-Auth-Token' in req.headers

    def get_user_by_authentication(self, req):
        return self.authorize_token(req.headers["X-Auth-Token"])

    def authenticate(self, req):
        # Unless the request is explicitly made against /<version>/ don't
        # honor it
        path_info = req.path_info
        account_name = None
        if len(path_info) > 1:
            return faults.Fault(webob.exc.HTTPUnauthorized())

        try:
            username = req.headers['X-Auth-User']
            key = req.headers['X-Auth-Key']
        except KeyError:
            return faults.Fault(webob.exc.HTTPUnauthorized())

        if ':' in username:
            account_name, username = username.rsplit(':', 1)

        token, user = self._authorize_user(username, account_name, key, req)
        if user and token:
            res = webob.Response()
            res.headers['X-Auth-Token'] = token.token_hash
            res.headers['X-Server-Management-Url'] = \
                token.server_management_url
            res.headers['X-Storage-Url'] = token.storage_url
            res.headers['X-CDN-Management-Url'] = token.cdn_management_url
            res.content_type = 'text/plain'
            res.status = '204'
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
            delta = datetime.datetime.now() - token.created_at
            if delta.days >= 2:
                self.db.auth_token_destroy(ctxt, token.token_hash)
            else:
                return self.auth.get_user(token.user_id)
        return None

    def _authorize_user(self, username, account_name, key, req):
        """Generates a new token and assigns it to a user.

        username - string
        account_name - string
        key - string API key
        req - webob.Request object
        """
        ctxt = context.get_admin_context()
        user = self.auth.get_user_from_access_key(key)
        if account_name:
            try:
                account = self.auth.get_project(account_name)
            except exception.NotFound:
                return None, None
        else:
            # (dragondm) punt and try to determine account.
            # this is something of a hack, but a user on 1 account is a
            # common case, and is the way the current RS code works.
            accounts = self.auth.get_projects(user=user)
            if len(accounts) == 1:
                account = accounts[0]
            else:
                #we can't tell what account they are logging in for.
                return None, None

        if user and user.name == username:
            token_hash = hashlib.sha1('%s%s%f' % (username, key,
                time.time())).hexdigest()
            token_dict = {}
            token_dict['token_hash'] = token_hash
            token_dict['cdn_management_url'] = ''
            # auth url + project (account) id, e.g.
            # http://foo.org:8774/baz/v1.0/myacct/
            os_url = '%s%s%s/' % (req.url,
                                  '' if req.url.endswith('/') else '/',
                                  account.id)
            token_dict['server_management_url'] = os_url
            token_dict['storage_url'] = ''
            token_dict['user_id'] = user.id
            token = self.db.auth_token_create(ctxt, token_dict)
            return token, user
        return None, None
