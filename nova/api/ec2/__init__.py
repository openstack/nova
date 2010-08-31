# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Starting point for routing EC2 requests
"""

import logging
import routes
import webob.exc
from webob.dec import wsgify

from nova.api.ec2 import admin
from nova.api.ec2 import cloud
from nova import exception
from nova import utils
from nova.auth import manager


_log = logging.getLogger("api")
_log.setLevel(logging.DEBUG)


class API(wsgi.Middleware):
    """Routing for all EC2 API requests."""

    def __init__(self):
        self.application = Authenticate(Router())

class Authenticate(wsgi.Middleware):
    """Authenticates an EC2 request."""

    @webob.dec.wsgify
    def __call__(self, req):
        #TODO(gundlach): where do arguments come from?
        args = self.request.arguments

        # Read request signature.
        try:
            signature = args.pop('Signature')[0]
        except:
            raise webob.exc.HTTPBadRequest()

        # Make a copy of args for authentication and signature verification.
        auth_params = {}
        for key, value in args.items():
            auth_params[key] = value[0]

        # Get requested action and remove authentication args for final request.
        try:
            action = args.pop('Action')[0]
            access = args.pop('AWSAccessKeyId')[0]
            args.pop('SignatureMethod')
            args.pop('SignatureVersion')
            args.pop('Version')
            args.pop('Timestamp')
        except:
            raise webob.exc.HTTPBadRequest()

        # Authenticate the request.
        try:
            (user, project) = manager.AuthManager().authenticate(
                access,
                signature,
                auth_params,
                req.method,
                req.host,
                req.path
            )

        except exception.Error, ex:
            logging.debug("Authentication Failure: %s" % ex)
            raise webob.exc.HTTPForbidden()

        _log.debug('action: %s' % action)

        for key, value in args.items():
            _log.debug('arg: %s\t\tval: %s' % (key, value))

        # Authenticated!
        req.environ['ec2.action'] = action
        req.environ['ec2.context'] = APIRequestContext(user, project)
        return self.application


class Router(wsgi.Application):
    """
    Finds controller for a request, executes environ['ec2.action'] upon it, and
    returns a response.
    """
    def __init__(self):
        self.map = routes.Mapper()
        self.map.connect("/{controller_name}/")
        self.controllers = dict(Cloud=cloud.CloudController(),
                                Admin=admin.AdminController())

    def __call__(self, req):
        # Obtain the appropriate controller for this request.
        match = self.map.match(req.path)
        if not match:
            raise webob.exc.HTTPNotFound()
        controller_name = match['controller_name']

        try:
            controller = self.controllers[controller_name]
        except KeyError:
            self._error('unhandled', 'no controller named %s' % controller_name)
            return

        api_request = APIRequest(controller, req.environ['ec2.action'])
        context = req.environ['ec2.context']
        try:
            return api_request.send(context, **args)
        except exception.ApiError as ex:
            self._error(req, type(ex).__name__ + "." + ex.code, ex.message)
        # TODO(vish): do something more useful with unknown exceptions
        except Exception as ex:
            self._error(type(ex).__name__, str(ex))

    def _error(self, req, code, message):
        req.status = 400
        req.headers['Content-Type'] = 'text/xml'
        req.response = ('<?xml version="1.0"?>\n'
                     '<Response><Errors><Error><Code>%s</Code>'
                     '<Message>%s</Message></Error></Errors>'
                     '<RequestID>?</RequestID></Response>') % (code, message))

