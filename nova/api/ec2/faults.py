# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import context
from nova import flags
from nova import utils

FLAGS = flags.FLAGS


class Fault(webob.exc.HTTPException):
    """Captures exception and return REST Response."""

    def __init__(self, exception):
        """Create a response for the given webob.exc.exception."""
        self.wrapped_exc = exception

    @webob.dec.wsgify
    def __call__(self, req):
        """Generate a WSGI response based on the exception passed to ctor."""
        code = self.wrapped_exc.status_int
        message = self.wrapped_exc.explanation

        if code == 501:
            message = "The requested function is not supported"
        code = str(code)

        if 'AWSAccessKeyId' not in req.params:
            raise webob.exc.HTTPBadRequest()
        user_id, _sep, project_id = req.params['AWSAccessKeyId'].partition(':')
        project_id = project_id or user_id
        remote_address = getattr(req, 'remote_address', '127.0.0.1')
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)

        ctxt = context.RequestContext(user_id,
                                      project_id,
                                      remote_address=remote_address)

        resp = webob.Response()
        resp.status = self.wrapped_exc.status_int
        resp.headers['Content-Type'] = 'text/xml'
        resp.body = str('<?xml version="1.0"?>\n'
                         '<Response><Errors><Error><Code>%s</Code>'
                         '<Message>%s</Message></Error></Errors>'
                         '<RequestID>%s</RequestID></Response>' %
                         (utils.utf8(code), utils.utf8(message),
                         utils.utf8(ctxt.request_id)))

        return resp
