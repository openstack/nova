# Copyright 2013 Cloudbase Solutions Srl
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

from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import context
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


_FAKE_CONNECT_INFO = {'instance_uuid': 'fake_instance_uuid',
                      'host': 'fake_host',
                      'port': 'fake_port',
                      'internal_access_path': 'fake_access_path',
                      'console_type': 'rdp-html5'}


def _fake_check_token(self, context, token):
    return _FAKE_CONNECT_INFO


def _fake_check_token_not_found(self, context, token):
    return None


def _fake_check_token_unauthorized(self, context, token):
    connect_info = _FAKE_CONNECT_INFO
    connect_info['console_type'] = 'unauthorized_console_type'
    return connect_info


class ConsoleAuthTokensExtensionTest(test.TestCase):

    _FAKE_URL = '/v3/os-console-auth-tokens/1'

    _EXPECTED_OUTPUT = {'console': {'instance_uuid': 'fake_instance_uuid',
                                    'host': 'fake_host',
                                    'port': 'fake_port',
                                    'internal_access_path':
                                    'fake_access_path'}}

    def setUp(self):
        super(ConsoleAuthTokensExtensionTest, self).setUp()
        self.stubs.Set(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       _fake_check_token)

        ctxt = self._get_admin_context()
        self.app = fakes.wsgi_app_v3(init_only=('os-console-auth-tokens'),
                                     fake_auth_context=ctxt)

    def _get_admin_context(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        return ctxt

    def _create_request(self):
        req = fakes.HTTPRequestV3.blank(self._FAKE_URL)
        req.method = "GET"
        req.headers["content-type"] = "application/json"
        return req

    def test_get_console_connect_info(self):
        req = self._create_request()
        res = req.get_response(self.app)
        self.assertEqual(200, res.status_int)
        output = jsonutils.loads(res.body)
        self.assertEqual(self._EXPECTED_OUTPUT, output)

    def test_get_console_connect_info_token_not_found(self):
        self.stubs.Set(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       _fake_check_token_not_found)
        req = self._create_request()
        res = req.get_response(self.app)
        self.assertEqual(404, res.status_int)

    def test_get_console_connect_info_unauthorized_console_type(self):
        self.stubs.Set(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       _fake_check_token_unauthorized)
        req = self._create_request()
        res = req.get_response(self.app)
        self.assertEqual(401, res.status_int)
