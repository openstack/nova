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

from nova.api.openstack.compute.plugins.v3 import lock_server
from nova import exception
from nova.tests.api.openstack.compute.plugins.v3 import \
     admin_only_action_common
from nova.tests.api.openstack import fakes


class LockServerTests(admin_only_action_common.CommonTests):
    def setUp(self):
        super(LockServerTests, self).setUp()
        self.controller = lock_server.LockServerController()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(lock_server, 'LockServerController',
                       _fake_controller)
        self.app = fakes.wsgi_app_v3(init_only=('servers',
                                                'os-lock-server'),
                                     fake_auth_context=self.context)
        self.mox.StubOutWithMock(self.compute_api, 'get')

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
