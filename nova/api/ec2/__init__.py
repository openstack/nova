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

import webob.dec
import webob.exc

from nova import wsgi

_DEPRECATION_MESSAGE = ('The in tree EC2 API has been removed in Mitaka. '
                        'Please remove entries from api-paste.ini')


class DeprecatedMiddleware(wsgi.Middleware):
    def __init__(self, *args, **kwargs):
        super(DeprecatedMiddleware, self).__init__(args[0])

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        return webob.exc.HTTPException(message=_DEPRECATION_MESSAGE)


class DeprecatedApplication(wsgi.Application):
    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        return webob.exc.HTTPException(message=_DEPRECATION_MESSAGE)


FaultWrapper = DeprecatedMiddleware
RequestLogging = DeprecatedMiddleware
Lockout = DeprecatedMiddleware
EC2KeystoneAuth = DeprecatedMiddleware
NoAuth = DeprecatedMiddleware
Requestify = DeprecatedMiddleware
Authorizer = DeprecatedMiddleware
Validator = DeprecatedMiddleware
Executor = DeprecatedApplication
