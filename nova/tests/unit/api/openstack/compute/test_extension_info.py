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

import mock
import webob

from nova.api.openstack.compute import extension_info
from nova import exception
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes


class ExtensionInfoV21Test(test.NoDBTestCase):

    def setUp(self):
        super(ExtensionInfoV21Test, self).setUp()
        self.controller = extension_info.ExtensionInfoController()
        patcher = mock.patch.object(policy, 'authorize', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_extension_info_show_servers_not_present(self):
        req = fakes.HTTPRequest.blank('/extensions/servers')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 'servers')


class ExtensionInfoPolicyEnforcementV21(test.NoDBTestCase):
    def setUp(self):
        super(ExtensionInfoPolicyEnforcementV21, self).setUp()
        self.controller = extension_info.ExtensionInfoController()
        self.req = fakes.HTTPRequest.blank('')

    def _test_extension_policy_failed(self, action, *args):
        rule_name = "os_compute_api:extensions"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            getattr(self.controller, action), self.req, *args)

        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_extension_index_policy_failed(self):
        self._test_extension_policy_failed('index')

    def test_extension_show_policy_failed(self):
        self._test_extension_policy_failed('show', 1)
