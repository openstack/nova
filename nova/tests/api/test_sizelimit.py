# Copyright (c) 2012 OpenStack, LLC
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

import webob

import nova.api.sizelimit
from nova import flags
from nova import test

FLAGS = flags.FLAGS
MAX_REQUEST_BODY_SIZE = FLAGS.osapi_max_request_body_size


class TestRequestBodySizeLimiter(test.TestCase):

    def setUp(self):
        super(TestRequestBodySizeLimiter, self).setUp()

        @webob.dec.wsgify()
        def fake_app(req):
            return webob.Response()

        self.middleware = nova.api.sizelimit.RequestBodySizeLimiter(fake_app)
        self.request = webob.Request.blank('/', method='POST')

    def test_content_length_acceptable(self):
        self.request.headers['Content-Length'] = MAX_REQUEST_BODY_SIZE
        self.request.body = "0" * MAX_REQUEST_BODY_SIZE
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status_int, 200)

    def test_content_length_to_large(self):
        self.request.headers['Content-Length'] = MAX_REQUEST_BODY_SIZE + 1
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status_int, 400)

    def test_request_to_large(self):
        self.request.body = "0" * (MAX_REQUEST_BODY_SIZE + 1)
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status_int, 400)
