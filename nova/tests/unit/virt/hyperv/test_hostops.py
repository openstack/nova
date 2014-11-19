# Copyright 2014 Cloudbase Solutions Srl
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

import mock

from nova import test
from nova.virt.hyperv import constants
from nova.virt.hyperv import hostops


class HostOpsTestCase(test.NoDBTestCase):

        def setUp(self):
            self._hostops = hostops.HostOps()
            super(HostOpsTestCase, self).setUp()

        def _test_host_power_action(self, action):
            self._hostops._hostutils.host_power_action = mock.Mock()

            self._hostops.host_power_action(action)
            self._hostops._hostutils.host_power_action.assert_called_with(
                action)

        def test_host_power_action_shutdown(self):
            self._test_host_power_action(constants.HOST_POWER_ACTION_SHUTDOWN)

        def test_host_power_action_reboot(self):
            self._test_host_power_action(constants.HOST_POWER_ACTION_REBOOT)

        def test_host_power_action_exception(self):
            self.assertRaises(NotImplementedError,
                              self._hostops.host_power_action,
                              constants.HOST_POWER_ACTION_STARTUP)
