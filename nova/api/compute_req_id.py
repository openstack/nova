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

Nova's notion of request-id tracking predates any common idea, so the
original version of this header in OpenStack was
x-compute-request-id. Eventually we got oslo, and all other projects
implemented this with x-openstack-request-id.

However, x-compute-request-id was always part of our contract. The
following migrates us to use x-openstack-request-id as well, by using
the common middleware.

"""

from oslo_middleware import request_id


HTTP_RESP_HEADER_REQUEST_ID = 'x-compute-request-id'


class ComputeReqIdMiddleware(request_id.RequestId):
    compat_headers = [HTTP_RESP_HEADER_REQUEST_ID]
