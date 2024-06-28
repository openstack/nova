# Copyright 2013 IBM Corp.
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

from unittest import mock

import ddt
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import suspend_server as \
    suspend_server_v21
from nova import exception
from nova.tests.unit.api.openstack.compute import admin_only_action_common


@ddt.ddt
class SuspendServerTestsV21(admin_only_action_common.CommonTests):
    suspend_server = suspend_server_v21
    controller_name = 'SuspendServerController'
    _api_version = '2.1'

    def setUp(self):
        super(SuspendServerTestsV21, self).setUp()
        self.controller = getattr(self.suspend_server, self.controller_name)()
        self.compute_api = self.controller.compute_api
        self.stub_out('nova.api.openstack.compute.suspend_server.'
                      'SuspendServerController',
                      lambda *a, **kw: self.controller)

    def test_suspend_resume(self):
        self._test_actions(
            ['_suspend', '_resume'],
            body_map={
                '_suspend': {'suspend': None}, '_resume': {'resume': None}
            }
        )

    @ddt.data(
        exception.OperationNotSupportedForVDPAInterface(
            instance_uuid=uuids.instance, operation='foo'),
        exception.OperationNotSupportedForSEV(
            instance_uuid=uuids.instance, operation='foo'),
        exception.ForbiddenWithAccelerators(),
    )
    @mock.patch('nova.compute.api.API.suspend')
    def test_suspend_raise_badrequest_for_not_supported_features(
        self, exc, mock_suspend):
        mock_suspend.side_effect = exc
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller._suspend,
            self.req, uuids.instance, body={'suspend': None})
        self.assertTrue(mock_suspend.called)

    def test_suspend_resume_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(
            ['_suspend', '_resume'],
            body_map={
                '_suspend': {'suspend': None}, '_resume': {'resume': None}
            }
        )

    def test_suspend_resume_raise_conflict_on_invalid_state(self):
        self._test_actions_raise_conflict_on_invalid_state(
            ['_suspend', '_resume'],
            body_map={
                '_suspend': {'suspend': None}, '_resume': {'resume': None}
            }
        )

    def test_actions_with_locked_instance(self):
        self._test_actions_with_locked_instance(
            ['_suspend', '_resume'],
            body_map={
                '_suspend': {'suspend': None}, '_resume': {'resume': None}
            }
        )
