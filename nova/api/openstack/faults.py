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
import webob.exc

from nova.api.openstack import common
from nova.api.openstack import wsgi


class Fault(webob.exc.HTTPException):
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
        self.wrapped_exc = exception
        self.status_int = exception.status_int

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """Generate a WSGI response based on the exception passed to ctor."""
        # Replace the body with fault details.
        code = self.wrapped_exc.status_int
        fault_name = self._fault_names.get(code, "cloudServersFault")
        fault_data = {
            fault_name: {
                'code': code,
                'message': self.wrapped_exc.explanation}}
        if code == 413:
            retry = self.wrapped_exc.headers['Retry-After']
            fault_data[fault_name]['retryAfter'] = retry

        # 'code' is an attribute on the fault tag itself
        metadata = {'attributes': {fault_name: 'code'}}

        content_type = req.best_match_content_type()

        xml_serializer = {
            '1.0': wsgi.XMLDictSerializer(metadata, wsgi.XMLNS_V10),
            '1.1': wsgi.XMLDictSerializer(metadata, wsgi.XMLNS_V11),
        }[common.get_version_from_href(req.url)]

        serializer = {
            'application/xml': xml_serializer,
            'application/json': wsgi.JSONDictSerializer(),
        }[content_type]

        self.wrapped_exc.body = serializer.serialize(fault_data)
        self.wrapped_exc.content_type = content_type

        return self.wrapped_exc


class OverLimitFault(webob.exc.HTTPException):
    """
    Rate-limited request response.
    """

    def __init__(self, message, details, retry_time):
        """
        Initialize new `OverLimitFault` with relevant information.
        """
        self.wrapped_exc = webob.exc.HTTPForbidden()
        self.content = {
            "overLimitFault": {
                "code": self.wrapped_exc.status_int,
                "message": message,
                "details": details,
            },
        }

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, request):
        """
        Return the wrapped exception with a serialized body conforming to our
        error format.
        """
        content_type = request.best_match_content_type()
        metadata = {"attributes": {"overLimitFault": "code"}}

        xml_serializer = {
            '1.0': wsgi.XMLDictSerializer(metadata, wsgi.XMLNS_V10),
            '1.1': wsgi.XMLDictSerializer(metadata, wsgi.XMLNS_V11),
        }[common.get_version_from_href(request.url)]

        serializer = {
            'application/xml': xml_serializer,
            'application/json': wsgi.JSONDictSerializer(),
        }[content_type]

        content = serializer.serialize(self.content)
        self.wrapped_exc.body = content

        return self.wrapped_exc
