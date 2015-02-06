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

"""Compatibility shim for Kilo, while operators migrate to oslo.middleware."""

from oslo_middleware import request_id

from nova.openstack.common import versionutils


ENV_REQUEST_ID = 'openstack.request_id'
HTTP_RESP_HEADER_REQUEST_ID = 'x-openstack-request-id'


@versionutils.deprecated(as_of=versionutils.deprecated.KILO,
                         in_favor_of='oslo.middleware.RequestId')
class RequestIdMiddleware(request_id.RequestId):
    pass
