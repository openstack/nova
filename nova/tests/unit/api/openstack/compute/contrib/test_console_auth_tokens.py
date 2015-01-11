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

import copy

from oslo_config import cfg
import webob

from nova.api.openstack.compute.contrib import console_auth_tokens \
    as console_auth_tokens_v2
from nova.api.openstack.compute.plugins.v3 import console_auth_tokens \
    as console_auth_tokens_v21
from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF

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
    connect_info = copy.deepcopy(_FAKE_CONNECT_INFO)
    connect_info['console_type'] = 'unauthorized_console_type'
    return connect_info


class ConsoleAuthTokensExtensionTestV21(test.TestCase):
    controller_class = console_auth_tokens_v21

    _EXPECTED_OUTPUT = {'console': {'instance_uuid': 'fake_instance_uuid',
                                    'host': 'fake_host',
                                    'port': 'fake_port',
                                    'internal_access_path':
                                    'fake_access_path'}}

    def setUp(self):
        super(ConsoleAuthTokensExtensionTestV21, self).setUp()
        self.stubs.Set(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       _fake_check_token)

        self.controller = self.controller_class.ConsoleAuthTokensController()
        self.req = fakes.HTTPRequest.blank('', use_admin_context=True)

    def test_get_console_connect_info(self):
        output = self.controller.show(self.req, fakes.FAKE_UUID)
        self.assertEqual(self._EXPECTED_OUTPUT, output)

    def test_get_console_connect_info_token_not_found(self):
        self.stubs.Set(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       _fake_check_token_not_found)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, fakes.FAKE_UUID)

    def test_get_console_connect_info_unauthorized_console_type(self):
        self.stubs.Set(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       _fake_check_token_unauthorized)
        self.assertRaises(webob.exc.HTTPUnauthorized,
                          self.controller.show, self.req, fakes.FAKE_UUID)


class ConsoleAuthTokensExtensionTestV2(ConsoleAuthTokensExtensionTestV21):
    controller_class = console_auth_tokens_v2
