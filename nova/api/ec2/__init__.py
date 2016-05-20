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

from oslo_log import log as logging

from nova.i18n import _LW
from nova import wsgi

LOG = logging.getLogger(__name__)

_DEPRECATED_MIDDLEWARE = (
    '%s has been deprecated and removed from Nova in Mitaka. '
    'You will need to remove lines referencing it in your paste.ini before '
    'upgrade to Newton or your cloud will break.')

_DEPRECATION_MESSAGE = ('The in tree EC2 API has been removed in Mitaka. '
                        'Please remove entries from api-paste.ini')

# NOTE(sdague): this whole file is safe to remove in Newton. We just
# needed a release cycle for it.


class DeprecatedMiddleware(wsgi.Middleware):
    def __init__(self, *args, **kwargs):
        super(DeprecatedMiddleware, self).__init__(args[0])
        LOG.warn(_LW(_DEPRECATED_MIDDLEWARE % type(self).__name__))  # noqa

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        # deprecated middleware needs to be a no op, not an exception
        return req.get_response(self.application)


class FaultWrapper(DeprecatedMiddleware):
    pass


class Lockout(DeprecatedMiddleware):
    pass


class EC2KeystoneAuth(DeprecatedMiddleware):
    pass


class NoAuth(DeprecatedMiddleware):
    pass


class Requestify(DeprecatedMiddleware):
    pass


class Authorizer(DeprecatedMiddleware):
    pass


class RequestLogging(DeprecatedMiddleware):
    pass


class Validator(DeprecatedMiddleware):
    pass


class Executor(wsgi.Application):
    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        return webob.exc.HTTPNotFound(explanation=_DEPRECATION_MESSAGE)
