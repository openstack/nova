# Copyright (c) 2013 NEC Corporation
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

"""Middleware that ensures request ID.

It ensures to assign request ID for each API request and set it to
request environment. The request ID is also added to API response.
"""

from nova.openstack.common import context
from nova.openstack.common.middleware import base


ENV_REQUEST_ID = 'openstack.request_id'
HTTP_RESP_HEADER_REQUEST_ID = 'x-openstack-request-id'


class RequestIdMiddleware(base.Middleware):

    def process_request(self, req):
        self.req_id = context.generate_request_id()
        req.environ[ENV_REQUEST_ID] = self.req_id

    def process_response(self, response):
        response.headers.add(HTTP_RESP_HEADER_REQUEST_ID, self.req_id)
        return response
