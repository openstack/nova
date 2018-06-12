# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the placement fault wrap middleware."""

import mock

from oslo_serialization import jsonutils
import testtools
import webob

from nova.api.openstack.placement import fault_wrap


ERROR_MESSAGE = 'that was not supposed to happen'


class Fault(Exception):
    pass


class TestFaultWrapper(testtools.TestCase):

    @staticmethod
    @webob.dec.wsgify
    def failing_application(req):
        raise Fault(ERROR_MESSAGE)

    def setUp(self):
        super(TestFaultWrapper, self).setUp()
        self.req = webob.Request.blank('/')
        self.environ = self.req.environ
        self.environ['HTTP_ACCEPT'] = 'application/json'
        self.start_response_mock = mock.MagicMock()
        self.fail_app = fault_wrap.FaultWrapper(self.failing_application)

    def test_fault_is_wrapped(self):
        response = self.fail_app(self.environ, self.start_response_mock)
        # response is a single member list
        error_struct = jsonutils.loads(response[0])
        first_error = error_struct['errors'][0]

        self.assertIn(ERROR_MESSAGE, first_error['detail'])
        self.assertEqual(500, first_error['status'])
        self.assertEqual('Internal Server Error', first_error['title'])

    def test_fault_response_headers(self):
        self.fail_app(self.environ, self.start_response_mock)
        call_args = self.start_response_mock.call_args
        self.assertEqual('500 Internal Server Error', call_args[0][0])

    @mock.patch("nova.api.openstack.placement.fault_wrap.LOG")
    def test_fault_log(self, mocked_log):
        self.fail_app(self.environ, self.start_response_mock)
        mocked_log.exception.assert_called_once_with(
                'Placement API unexpected error: %s',
                mock.ANY)
