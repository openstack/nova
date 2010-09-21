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
Root WSGI middleware for all API controllers.
"""

import routes
import webob.dec

from nova import wsgi
from nova.api import ec2
from nova.api import rackspace


class API(wsgi.Router):
    """Routes top-level requests to the appropriate controller."""

    def __init__(self):
        mapper = routes.Mapper()
        mapper.connect("/", controller=self.versions)
        mapper.connect("/v1.0/{path_info:.*}", controller=rackspace.API())
        mapper.connect("/ec2/{path_info:.*}", controller=ec2.API())
        super(API, self).__init__(mapper)

    @webob.dec.wsgify
    def versions(self, req):
        """Respond to a request for all OpenStack API versions."""
        response = {
                "versions": [
                    dict(status="CURRENT", id="v1.0")]}
        metadata = {
            "application/xml": {
                "attributes": dict(version=["status", "id"])}}
        return wsgi.Serializer(req.environ, metadata).to_content_type(response)
