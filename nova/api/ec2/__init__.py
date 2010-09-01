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

"""
WSGI middleware for EC2 API controllers.
"""

import routes
import webob.dec

from nova import wsgi


class API(wsgi.Router):
    """Routes EC2 requests to the appropriate controller."""

    def __init__(self):
        mapper = routes.Mapper()
        mapper.connect(None, "{all:.*}", controller=self.dummy)
        super(API, self).__init__(mapper)

    @staticmethod
    @webob.dec.wsgify
    def dummy(req):
        """Temporary dummy controller."""
        msg = "dummy response -- please hook up __init__() to cloud.py instead"
        return repr({'dummy': msg,
                     'kwargs': repr(req.environ['wsgiorg.routing_args'][1])})
