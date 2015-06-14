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

from mox3 import mox
import webob

from nova.api.ec2 import faults
from nova import test
from nova import wsgi


class TestFaults(test.NoDBTestCase):
    """Tests covering ec2 Fault class."""

    def test_fault_exception(self):
        # Ensure the status_int is set correctly on faults.
        fault = faults.Fault(webob.exc.HTTPBadRequest(
                             explanation='test'))
        self.assertIsInstance(fault.wrapped_exc, webob.exc.HTTPBadRequest)

    def test_fault_exception_status_int(self):
        # Ensure the status_int is set correctly on faults.
        fault = faults.Fault(webob.exc.HTTPNotFound(explanation='test'))
        self.assertEqual(fault.wrapped_exc.status_int, 404)

    def test_fault_call(self):
        # Ensure proper EC2 response on faults.
        message = 'test message'
        ex = webob.exc.HTTPNotFound(explanation=message)
        fault = faults.Fault(ex)
        req = wsgi.Request.blank('/test')
        req.GET['AWSAccessKeyId'] = "test_user_id:test_project_id"
        self.mox.StubOutWithMock(faults, 'ec2_error_response')
        faults.ec2_error_response(mox.IgnoreArg(), 'HTTPNotFound',
                                  message=message, status=ex.status_int)
        self.mox.ReplayAll()
        fault(req)
