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


import webob.dec

from nova import wsgi


class Fault(wsgi.Application):

    """An RS API fault response."""

    _fault_names = {
            400: "badRequest",
            401: "unauthorized",
            403: "resizeNotAllowed",
            404: "itemNotFound",
            405: "badMethod",
            409: "inProgress",
            413: "overLimit",
            415: "badMediaType",
            501: "notImplemented",
            503: "serviceUnavailable"}

    def __init__(self, exception):
        """Create a Fault for the given webob.exc.exception."""
        self.exception = exception

    @webob.dec.wsgify
    def __call__(self, req):
        """Generate a WSGI response based on self.exception."""
        # Replace the body with fault details.
        code = self.exception.status_int
        fault_name = self._fault_names.get(code, "cloudServersFault")
        fault_data = {
            fault_name: {
                'code': code,
                'message': self.exception.explanation}}
        if code == 413:
            retry = self.exception.headers['Retry-After']
            fault_data[fault_name]['retryAfter'] = retry
        # 'code' is an attribute on the fault tag itself 
        metadata = {'application/xml': {'attributes': {fault_name: 'code'}}}
        serializer = wsgi.Serializer(req.environ, metadata)
        self.exception.body = serializer.to_content_type(fault_data)
        return self.exception
