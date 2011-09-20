# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC
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
Common Auth Middleware.

"""

import webob.dec
import webob.exc

from nova import context
from nova import flags
from nova import wsgi


FLAGS = flags.FLAGS
flags.DEFINE_boolean('use_forwarded_for', False,
                     'Treat X-Forwarded-For as the canonical remote address. '
                     'Only enable this if you have a sanitizing proxy.')


class InjectContext(wsgi.Middleware):
    """Add a 'nova.context' to WSGI environ."""

    def __init__(self, context, *args, **kwargs):
        self.context = context
        super(InjectContext, self).__init__(*args, **kwargs)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        req.environ['nova.context'] = self.context
        return self.application
