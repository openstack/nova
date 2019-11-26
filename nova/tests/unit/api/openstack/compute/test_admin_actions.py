#   Copyright 2011 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from nova.api.openstack.compute import admin_actions as admin_actions_v21
from nova.tests.unit.api.openstack.compute import admin_only_action_common


class AdminActionsTestV21(admin_only_action_common.CommonTests):
    admin_actions = admin_actions_v21
    _api_version = '2.1'

    def setUp(self):
        super(AdminActionsTestV21, self).setUp()
        self.controller = self.admin_actions.AdminActionsController()
        self.compute_api = self.controller.compute_api
        self.stub_out('nova.api.openstack.compute.admin_actions.'
                      'AdminActionsController',
                      lambda *a, **k: self.controller)

    def test_actions(self):
        actions = ['_reset_network', '_inject_network_info']
        method_translations = {'_reset_network': 'reset_network',
                               '_inject_network_info': 'inject_network_info'}

        self._test_actions(actions, method_translations)

    def test_actions_with_non_existed_instance(self):
        actions = ['_reset_network', '_inject_network_info']
        self._test_actions_with_non_existed_instance(actions)

    def test_actions_with_locked_instance(self):
        actions = ['_reset_network', '_inject_network_info']
        method_translations = {'_reset_network': 'reset_network',
                               '_inject_network_info': 'inject_network_info'}

        self._test_actions_with_locked_instance(actions,
            method_translations=method_translations)
