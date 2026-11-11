# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

from nova import exception
from nova.tests.functional.libvirt import base


class TestInitHost(base.ServersTestBase):

    @mock.patch('os_brick.initiator.linuxscsi.LinuxSCSI.is_multipath_running')
    def test_check_multipath(self, mock_multipath):
        # enable and require multipath
        self.flags(volume_use_multipath=True, group='libvirt')
        self.flags(volume_enforce_multipath=True, group='libvirt')

        # multipath is running, so compute should start without error
        mock_multipath.return_value = True
        hostname = self.start_compute()
        mock_multipath.assert_called_once()
        mock_multipath.reset_mock()

        # multipath is stopped, so compute should fail to start
        mock_multipath.return_value = False
        self.assertRaises(exception.InvalidConfiguration,
                          self.restart_compute_service, hostname)
        mock_multipath.assert_called_once()
