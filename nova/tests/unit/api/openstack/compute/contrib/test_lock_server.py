# Copyright 2011 OpenStack Foundation
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

from nova.api.openstack.compute.contrib import admin_actions as \
    lock_server_v2
from nova.api.openstack.compute.plugins.v3 import lock_server as \
    lock_server_v21
from nova import exception
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class LockServerTestsV21(admin_only_action_common.CommonTests):
    lock_server = lock_server_v21
    controller_name = 'LockServerController'

    def setUp(self):
        super(LockServerTestsV21, self).setUp()
        self.controller = getattr(self.lock_server, self.controller_name)()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.lock_server, self.controller_name,
                       _fake_controller)
        self.app = self._get_app()
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def _get_app(self):
        return fakes.wsgi_app_v21(init_only=('servers',
                                             'os-lock-server'),
                                  fake_auth_context=self.context)

    def test_lock_unlock(self):
        self._test_actions(['lock', 'unlock'])

    def test_lock_unlock_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(['lock', 'unlock'])

    def test_unlock_not_authorized(self):
        self.mox.StubOutWithMock(self.compute_api, 'unlock')

        instance = self._stub_instance_get()

        self.compute_api.unlock(self.context, instance).AndRaise(
                exception.PolicyNotAuthorized(action='unlock'))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {'unlock': None})
        self.assertEqual(403, res.status_int)


class LockServerTestsV2(LockServerTestsV21):
    lock_server = lock_server_v2
    controller_name = 'AdminActionsController'

    def setUp(self):
        super(LockServerTestsV2, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Admin_actions'])

    def _get_app(self):
        return fakes.wsgi_app(init_only=('servers',),
                                 fake_auth_context=self.context)
