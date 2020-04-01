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

from nova.api.openstack.compute import pause_server as \
    pause_server_v21
from nova.tests.unit.api.openstack.compute import admin_only_action_common


class PauseServerTestsV21(admin_only_action_common.CommonTests):
    pause_server = pause_server_v21
    controller_name = 'PauseServerController'
    _api_version = '2.1'

    def setUp(self):
        super(PauseServerTestsV21, self).setUp()
        self.controller = getattr(self.pause_server, self.controller_name)()
        self.compute_api = self.controller.compute_api
        self.stub_out('nova.api.openstack.compute.pause_server.'
                      'PauseServerController',
                      lambda *a, **kw: self.controller)

    def test_pause_unpause(self):
        self._test_actions(['_pause', '_unpause'])

    def test_actions_raise_on_not_implemented(self):
        for action in ['_pause', '_unpause']:
            self._test_not_implemented_state(action)

    def test_pause_unpause_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(['_pause', '_unpause'])

    def test_pause_unpause_with_non_existed_instance_in_compute_api(self):
        self._test_actions_instance_not_found_in_compute_api(['_pause',
                                                              '_unpause'])

    def test_pause_unpause_raise_conflict_on_invalid_state(self):
        self._test_actions_raise_conflict_on_invalid_state(['_pause',
                                                            '_unpause'])

    def test_actions_with_locked_instance(self):
        self._test_actions_with_locked_instance(['_pause', '_unpause'])
