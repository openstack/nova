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
APIRequestHandler, pulled unmodified out of nova.endpoint.api
"""

import logging

import tornado.web

from nova import exception
from nova import utils
from nova.auth import manager


_log = logging.getLogger("api")
_log.setLevel(logging.DEBUG)


class APIRequestHandler(tornado.web.RequestHandler):
    def get(self, controller_name):
        self.execute(controller_name)

    @tornado.web.asynchronous
    def execute(self, controller_name):
        # Obtain the appropriate controller for this request.
        try:
            controller = self.application.controllers[controller_name]
        except KeyError:
            self._error('unhandled', 'no controller named %s' % controller_name)
            return

        args = self.request.arguments

        # Read request signature.
        try:
            signature = args.pop('Signature')[0]
        except:
            raise tornado.web.HTTPError(400)

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
            raise tornado.web.HTTPError(400)

        # Authenticate the request.
        try:
            (user, project) = manager.AuthManager().authenticate(
                access,
                signature,
                auth_params,
                self.request.method,
                self.request.host,
                self.request.path
            )

        except exception.Error, ex:
            logging.debug("Authentication Failure: %s" % ex)
            raise tornado.web.HTTPError(403)

        _log.debug('action: %s' % action)

        for key, value in args.items():
            _log.debug('arg: %s\t\tval: %s' % (key, value))

        request = APIRequest(controller, action)
        context = APIRequestContext(self, user, project)
        d = request.send(context, **args)
        # d.addCallback(utils.debug)

        # TODO: Wrap response in AWS XML format
        d.addCallbacks(self._write_callback, self._error_callback)

    def _write_callback(self, data):
        self.set_header('Content-Type', 'text/xml')
        self.write(data)
        self.finish()

    def _error_callback(self, failure):
        try:
            failure.raiseException()
        except exception.ApiError as ex:
            self._error(type(ex).__name__ + "." + ex.code, ex.message)
        # TODO(vish): do something more useful with unknown exceptions
        except Exception as ex:
            self._error(type(ex).__name__, str(ex))
            raise

    def post(self, controller_name):
        self.execute(controller_name)

    def _error(self, code, message):
        self._status_code = 400
        self.set_header('Content-Type', 'text/xml')
        self.write('<?xml version="1.0"?>\n')
        self.write('<Response><Errors><Error><Code>%s</Code>'
                   '<Message>%s</Message></Error></Errors>'
                   '<RequestID>?</RequestID></Response>' % (code, message))
        self.finish()
