# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack, LLC
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
Request Body limiting middleware.

"""

import webob.dec
import webob.exc

from nova import context
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova import wsgi


#default request size is 112k
max_request_body_size_opt = cfg.BoolOpt('osapi_max_request_body_size',
        default=114688,
        help='')

FLAGS = flags.FLAGS
FLAGS.register_opt(max_request_body_size_opt)
LOG = logging.getLogger(__name__)


class RequestBodySizeLimiter(wsgi.Middleware):
    """Add a 'nova.context' to WSGI environ."""

    def __init__(self, *args, **kwargs):
        super(RequestBodySizeLimiter, self).__init__(*args, **kwargs)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if (req.content_length > FLAGS.osapi_max_request_body_size
            or len(req.body) > FLAGS.osapi_max_request_body_size):
            msg = _("Request is too large.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        else:
            return self.application
