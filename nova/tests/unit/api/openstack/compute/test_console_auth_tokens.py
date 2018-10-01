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

import ddt
import mock
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import console_auth_tokens \
        as console_auth_tokens_v21
from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes


@ddt.ddt
class ConsoleAuthTokensExtensionTestV21(test.NoDBTestCase):
    controller_class = console_auth_tokens_v21

    _EXPECTED_OUTPUT = {'console': {'instance_uuid': fakes.FAKE_UUID,
                                    'host': 'fake_host',
                                    'port': '1234',
                                    'internal_access_path':
                                    'fake_access_path'}}

    # The database backend returns a ConsoleAuthToken.to_dict() and o.vo
    # StringField are unicode. And the port is an IntegerField.
    _EXPECTED_OUTPUT_DB = copy.deepcopy(_EXPECTED_OUTPUT)
    _EXPECTED_OUTPUT_DB['console'].update(
        {'host': u'fake_host', 'port': 1234,
         'internal_access_path': u'fake_access_path'})

    def setUp(self):
        super(ConsoleAuthTokensExtensionTestV21, self).setUp()
        self.controller = self.controller_class.ConsoleAuthTokensController()
        self.req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.context = self.req.environ['nova.context']

    @ddt.data(True, False)
    @mock.patch('nova.objects.ConsoleAuthToken.validate',
                return_value=objects.ConsoleAuthToken(
                    instance_uuid=fakes.FAKE_UUID, host='fake_host',
                    port='1234', internal_access_path='fake_access_path',
                    console_type='rdp-html5', token=fakes.FAKE_UUID))
    @mock.patch.object(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       return_value={
                           'instance_uuid': fakes.FAKE_UUID,
                           'host': 'fake_host',
                           'port': '1234',
                           'internal_access_path': 'fake_access_path',
                           'console_type': 'rdp-html5'})
    def test_get_console_connect_info(self, enable_consoleauth,
                                      mock_check_token, mock_validate):
        self.flags(enable_consoleauth=enable_consoleauth, group='workarounds')
        output = self.controller.show(self.req, fakes.FAKE_UUID)
        if enable_consoleauth:
            self.assertEqual(self._EXPECTED_OUTPUT, output)
            mock_check_token.assert_called_once_with(self.context,
                                                     fakes.FAKE_UUID)
            mock_validate.assert_not_called()
        else:
            self.assertEqual(self._EXPECTED_OUTPUT_DB, output)
            mock_validate.assert_called_once_with(self.context,
                                                  fakes.FAKE_UUID)
            mock_check_token.assert_not_called()

    @ddt.data(True, False)
    @mock.patch('nova.objects.ConsoleAuthToken.validate',
                side_effect=exception.InvalidToken(token='***'))
    @mock.patch.object(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       return_value=None)
    def test_get_console_connect_info_token_not_found(self, enable_consoleauth,
                                                      mock_check_token,
                                                      mock_validate):
        self.flags(enable_consoleauth=enable_consoleauth, group='workarounds')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, fakes.FAKE_UUID)
        if enable_consoleauth:
            mock_check_token.assert_called_once_with(self.context,
                                                     fakes.FAKE_UUID)
            mock_validate.assert_not_called()
        else:
            mock_validate.assert_called_once_with(self.context,
                                                  fakes.FAKE_UUID)
            mock_check_token.assert_not_called()

    @ddt.data(True, False)
    @mock.patch('nova.objects.ConsoleAuthToken.validate',
                return_value=objects.ConsoleAuthToken(
                    instance_uuid=fakes.FAKE_UUID, host='fake_host',
                    port='1234', internal_access_path='fake_access_path',
                    console_type='unauthorized_console_type',
                    token=fakes.FAKE_UUID))
    @mock.patch.object(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token',
                       return_value={
                           'instance_uuid': fakes.FAKE_UUID,
                           'host': 'fake_host',
                           'port': '1234',
                           'internal_access_path': 'fake_access_path',
                           'console_type': 'unauthorized_console_type'})
    def test_get_console_connect_info_nonrdp_console_type(self,
                                                          enable_consoleauth,
                                                          mock_check_token,
                                                          mock_validate):
        self.flags(enable_consoleauth=enable_consoleauth, group='workarounds')
        self.assertRaises(webob.exc.HTTPUnauthorized,
                          self.controller.show, self.req, fakes.FAKE_UUID)
        if enable_consoleauth:
            mock_check_token.assert_called_once_with(self.context,
                                                     fakes.FAKE_UUID)
            mock_validate.assert_not_called()
        else:
            mock_validate.assert_called_once_with(self.context,
                                                  fakes.FAKE_UUID)
            mock_check_token.assert_not_called()


@ddt.ddt
class ConsoleAuthTokensExtensionTestV231(ConsoleAuthTokensExtensionTestV21):

    def setUp(self):
        super(ConsoleAuthTokensExtensionTestV231, self).setUp()
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.31')

    @ddt.data(True, False)
    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    @mock.patch.object(consoleauth_rpcapi.ConsoleAuthAPI, 'check_token')
    def test_get_console_connect_info_nonrdp_console_type(self,
                                                          enable_consoleauth,
                                                          mock_check,
                                                          mock_validate):
        self.flags(enable_consoleauth=enable_consoleauth, group='workarounds')
        mock_validate.return_value = objects.ConsoleAuthToken(
            instance_uuid=fakes.FAKE_UUID, host='fake_host', port='1234',
            internal_access_path='fake_access_path', console_type='webmks',
            token=fakes.FAKE_UUID)
        mock_check.return_value = {'instance_uuid': fakes.FAKE_UUID,
                                   'host': 'fake_host',
                                   'port': '1234',
                                   'internal_access_path': 'fake_access_path',
                                   'console_type': 'webmks'}
        output = self.controller.show(self.req, fakes.FAKE_UUID)
        if enable_consoleauth:
            self.assertEqual(self._EXPECTED_OUTPUT, output)
            mock_check.assert_called_once_with(self.context, fakes.FAKE_UUID)
            mock_validate.assert_not_called()
        else:
            self.assertEqual(self._EXPECTED_OUTPUT_DB, output)
            mock_validate.assert_called_once_with(self.context,
                                                  fakes.FAKE_UUID)
            mock_check.assert_not_called()
