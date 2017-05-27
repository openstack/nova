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


from oslo_context import context
from testtools import matchers
import webob
import webob.dec

from nova.api import compute_req_id
from nova import test


ENV_REQUEST_ID = 'openstack.request_id'


class RequestIdTest(test.NoDBTestCase):
    def test_generate_request_id(self):
        @webob.dec.wsgify
        def application(req):
            return req.environ[ENV_REQUEST_ID]

        app = compute_req_id.ComputeReqIdMiddleware(application)
        req = webob.Request.blank('/test')
        req_id = context.generate_request_id()
        req.environ[ENV_REQUEST_ID] = req_id
        res = req.get_response(app)

        res_id = res.headers.get(compute_req_id.HTTP_RESP_HEADER_REQUEST_ID)
        self.assertThat(res_id, matchers.StartsWith('req-'))
        self.assertEqual(res_id.encode('utf-8'), res.body)
