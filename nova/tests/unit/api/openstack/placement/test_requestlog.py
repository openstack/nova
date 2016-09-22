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
"""Tests for the placement request log middleware."""

import mock
import webob

from nova.api.openstack.placement import requestlog
from nova import test


class TestRequestLog(test.NoDBTestCase):

    @staticmethod
    @webob.dec.wsgify
    def application(req):
        req.response.status = 200
        return req.response

    def setUp(self):
        super(TestRequestLog, self).setUp()
        self.req = webob.Request.blank('/resource_providers?name=myrp')
        self.environ = self.req.environ
        # The blank does not include remote address, so add it.
        self.environ['REMOTE_ADDR'] = '127.0.0.1'
        # nor a microversion
        self.environ['placement.microversion'] = '2.1'

    def test_get_uri(self):
        req_uri = requestlog.RequestLog._get_uri(self.environ)
        self.assertEqual('/resource_providers?name=myrp', req_uri)

    def test_get_uri_knows_prefix(self):
        self.environ['SCRIPT_NAME'] = '/placement'
        req_uri = requestlog.RequestLog._get_uri(self.environ)
        self.assertEqual('/placement/resource_providers?name=myrp', req_uri)

    @mock.patch("nova.api.openstack.placement.requestlog.RequestLog.write_log")
    def test_middleware_writes_logs(self, write_log):
        start_response_mock = mock.MagicMock()
        app = requestlog.RequestLog(self.application)
        app(self.environ, start_response_mock)
        write_log.assert_called_once_with(
            self.environ, '/resource_providers?name=myrp', '200 OK', '0')

    @mock.patch("nova.api.openstack.placement.requestlog.LOG")
    def test_middleware_sends_message(self, mocked_log):
        start_response_mock = mock.MagicMock()
        app = requestlog.RequestLog(self.application)
        app(self.environ, start_response_mock)
        mocked_log.debug.assert_called_once_with(
            'Starting request: %s "%s %s"', '127.0.0.1', 'GET',
            '/resource_providers?name=myrp')
        mocked_log.info.assert_called_once_with(
            '%(REMOTE_ADDR)s "%(REQUEST_METHOD)s %(REQUEST_URI)s" '
            'status: %(status)s len: %(bytes)s microversion: %(microversion)s',
            {'microversion': '2.1',
             'status': '200',
             'REQUEST_URI': '/resource_providers?name=myrp',
             'REQUEST_METHOD': 'GET',
             'REMOTE_ADDR': '127.0.0.1',
             'bytes': '0'})
