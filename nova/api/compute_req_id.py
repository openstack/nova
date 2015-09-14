# Copyright (c) 2014 IBM Corp.
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

"""Middleware that ensures x-compute-request-id

Using this middleware provides a convenient way to attach the
x-compute-request-id to only v2 responses. Previously, this header was set in
api/openstack/wsgi.py

Responses for v2.1 API are taken care of by the request_id middleware provided
in oslo.
"""

from oslo_context import context
from oslo_middleware import base
import webob.dec


ENV_REQUEST_ID = 'openstack.request_id'
HTTP_RESP_HEADER_REQUEST_ID = 'x-compute-request-id'


class ComputeReqIdMiddleware(base.Middleware):

    @webob.dec.wsgify
    def __call__(self, req):
        req_id = context.generate_request_id()
        req.environ[ENV_REQUEST_ID] = req_id
        response = req.get_response(self.application)
        if HTTP_RESP_HEADER_REQUEST_ID not in response.headers:
            response.headers.add(HTTP_RESP_HEADER_REQUEST_ID, req_id)
        return response
