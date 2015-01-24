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

from nova.api.openstack.compute.contrib import admin_actions as \
    admin_actions_v2
from nova.api.openstack.compute.plugins.v3 import admin_actions as \
    admin_actions_v21
import nova.context
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class AdminActionsTestV21(admin_only_action_common.CommonTests):
    admin_actions = admin_actions_v21
    fake_url = '/v2/fake'

    def setUp(self):
        super(AdminActionsTestV21, self).setUp()
        self.controller = self.admin_actions.AdminActionsController()
        self.compute_api = self.controller.compute_api
        self.context = nova.context.RequestContext('fake', 'fake')

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.admin_actions, 'AdminActionsController',
                       _fake_controller)

        self.app = self._get_app()
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def _get_app(self):
        return fakes.wsgi_app_v21(init_only=('servers',
                                             'os-admin-actions'),
                                  fake_auth_context=self.context)

    def test_actions(self):
        actions = ['resetNetwork', 'injectNetworkInfo']
        method_translations = {'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info'}

        self._test_actions(actions, method_translations)

    def test_actions_with_non_existed_instance(self):
        actions = ['resetNetwork', 'injectNetworkInfo']
        self._test_actions_with_non_existed_instance(actions)

    def test_actions_with_locked_instance(self):
        actions = ['resetNetwork', 'injectNetworkInfo']
        method_translations = {'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info'}

        self._test_actions_with_locked_instance(actions,
            method_translations=method_translations)


class AdminActionsTestV2(AdminActionsTestV21):
    admin_actions = admin_actions_v2

    def setUp(self):
        super(AdminActionsTestV2, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Admin_actions'])

    def _get_app(self):
        return fakes.wsgi_app(init_only=('servers',),
                              fake_auth_context=self.context)
