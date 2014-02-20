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

from nova.api.openstack.compute.plugins.v3 import pause_server
from nova.tests.api.openstack.compute.plugins.v3 import \
     admin_only_action_common
from nova.tests.api.openstack import fakes


class PauseServerTests(admin_only_action_common.CommonTests):
    def setUp(self):
        super(PauseServerTests, self).setUp()
        self.controller = pause_server.PauseServerController()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(pause_server, 'PauseServerController',
                       _fake_controller)
        self.app = fakes.wsgi_app_v3(init_only=('servers',
                                                'os-pause-server'),
                                     fake_auth_context=self.context)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_pause_unpause(self):
        self._test_actions(['pause', 'unpause'])

    def test_pause_unpause_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(['pause', 'unpause'])

    def test_pause_unpause_raise_conflict_on_invalid_state(self):
        self._test_actions_raise_conflict_on_invalid_state(['pause',
                                                            'unpause'])

    def test_actions_with_locked_instance(self):
        self._test_actions_with_locked_instance(['pause', 'unpause'])
