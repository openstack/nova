# Copyright (c) 2012 OpenStack Foundation
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

from oslo.config import cfg
import StringIO
import webob

import nova.api.sizelimit
from nova import test

CONF = cfg.CONF
MAX_REQUEST_BODY_SIZE = CONF.osapi_max_request_body_size


class TestLimitingReader(test.NoDBTestCase):

    def test_limiting_reader(self):
        BYTES = 1024
        bytes_read = 0
        data = StringIO.StringIO("*" * BYTES)
        for chunk in nova.api.sizelimit.LimitingReader(data, BYTES):
            bytes_read += len(chunk)

        self.assertEquals(bytes_read, BYTES)

        bytes_read = 0
        data = StringIO.StringIO("*" * BYTES)
        reader = nova.api.sizelimit.LimitingReader(data, BYTES)
        byte = reader.read(1)
        while len(byte) != 0:
            bytes_read += 1
            byte = reader.read(1)

        self.assertEquals(bytes_read, BYTES)

    def test_limiting_reader_fails(self):
        BYTES = 1024

        def _consume_all_iter():
            bytes_read = 0
            data = StringIO.StringIO("*" * BYTES)
            for chunk in nova.api.sizelimit.LimitingReader(data, BYTES - 1):
                bytes_read += len(chunk)

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          _consume_all_iter)

        def _consume_all_read():
            bytes_read = 0
            data = StringIO.StringIO("*" * BYTES)
            reader = nova.api.sizelimit.LimitingReader(data, BYTES - 1)
            byte = reader.read(1)
            while len(byte) != 0:
                bytes_read += 1
                byte = reader.read(1)

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          _consume_all_read)


class TestRequestBodySizeLimiter(test.NoDBTestCase):

    def setUp(self):
        super(TestRequestBodySizeLimiter, self).setUp()

        @webob.dec.wsgify()
        def fake_app(req):
            return webob.Response(req.body)

        self.middleware = nova.api.sizelimit.RequestBodySizeLimiter(fake_app)
        self.request = webob.Request.blank('/', method='POST')

    def test_content_length_acceptable(self):
        self.request.headers['Content-Length'] = MAX_REQUEST_BODY_SIZE
        self.request.body = "0" * MAX_REQUEST_BODY_SIZE
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status_int, 200)

    def test_content_length_too_large(self):
        self.request.headers['Content-Length'] = MAX_REQUEST_BODY_SIZE + 1
        self.request.body = "0" * (MAX_REQUEST_BODY_SIZE + 1)
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status_int, 413)

    def test_request_too_large_no_content_length(self):
        self.request.body = "0" * (MAX_REQUEST_BODY_SIZE + 1)
        self.request.headers['Content-Length'] = None
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status_int, 413)
