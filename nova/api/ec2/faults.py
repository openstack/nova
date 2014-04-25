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

from oslo.config import cfg
import webob.dec
import webob.exc

import nova.api.ec2
from nova import context
from nova.openstack.common import log as logging
from nova import utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def ec2_error_response(request_id, code, message, status=500):
    """Helper to construct an EC2 compatible error response."""
    LOG.debug('EC2 error response: %(code)s: %(message)s',
              {'code': code, 'message': message})
    resp = webob.Response()
    resp.status = status
    resp.headers['Content-Type'] = 'text/xml'
    resp.body = str('<?xml version="1.0"?>\n'
                    '<Response><Errors><Error><Code>%s</Code>'
                    '<Message>%s</Message></Error></Errors>'
                    '<RequestID>%s</RequestID></Response>' %
                    (utils.xhtml_escape(utils.utf8(code)),
                     utils.xhtml_escape(utils.utf8(message)),
                     utils.xhtml_escape(utils.utf8(request_id))))
    return resp


class Fault(webob.exc.HTTPException):
    """Captures exception and return REST Response."""

    def __init__(self, exception):
        """Create a response for the given webob.exc.exception."""
        self.wrapped_exc = exception

    @webob.dec.wsgify
    def __call__(self, req):
        """Generate a WSGI response based on the exception passed to ctor."""
        code = nova.api.ec2.exception_to_ec2code(self.wrapped_exc)
        status = self.wrapped_exc.status_int
        message = self.wrapped_exc.explanation

        if status == 501:
            message = "The requested function is not supported"

        if 'AWSAccessKeyId' not in req.params:
            raise webob.exc.HTTPBadRequest()
        user_id, _sep, project_id = req.params['AWSAccessKeyId'].partition(':')
        project_id = project_id or user_id
        remote_address = getattr(req, 'remote_address', '127.0.0.1')
        if CONF.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)

        ctxt = context.RequestContext(user_id,
                                      project_id,
                                      remote_address=remote_address)
        resp = ec2_error_response(ctxt.request_id, code,
                                  message=message, status=status)
        return resp
