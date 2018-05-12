# Copyright 2011 NTT
# All Rights Reserved.
#
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


import mock

from oslo_concurrency import processutils

from nova.network import linux_utils as net_utils
from nova import test


class NetUtilsTestCase(test.NoDBTestCase):
    def test_set_device_mtu_default(self):
        calls = []
        with mock.patch('nova.utils.execute', return_value=('', '')) as ex:
            net_utils.set_device_mtu('fake-dev')
            ex.assert_has_calls(calls)

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev(self, mock_execute):
        net_utils.create_tap_dev('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_create_tap_skipped_when_exists(self, mock_execute, mock_exists):
        net_utils.create_tap_dev('tap42')

        mock_exists.assert_called_once_with('/sys/class/net/tap42')
        mock_execute.assert_not_called()

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_mac(self, mock_execute):
        net_utils.create_tap_dev('tap42', '00:11:22:33:44:55')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42',
                      'address', '00:11:22:33:44:55',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_fallback_to_tunctl(self, mock_execute):
        # ip failed, fall back to tunctl
        mock_execute.side_effect = [processutils.ProcessExecutionError, 0, 0]

        net_utils.create_tap_dev('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('tunctl', '-b', '-t', 'tap42',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_multiqueue(self, mock_execute):
        net_utils.create_tap_dev('tap42', multiqueue=True)

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      'multi_queue',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_multiqueue_tunctl_raises(self, mock_execute):
        # if creation of a tap by the means of ip command fails,
        # create_tap_dev() will try to do that by the means of tunctl
        mock_execute.side_effect = processutils.ProcessExecutionError
        # but tunctl can't create multiqueue taps, so the failure is expected
        self.assertRaises(processutils.ProcessExecutionError,
                          net_utils.create_tap_dev,
                          'tap42', multiqueue=True)
