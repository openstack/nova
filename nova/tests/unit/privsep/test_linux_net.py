# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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

from oslo_concurrency import processutils

import nova.privsep.linux_net
from nova import test


class LinuxNetTestCase(test.NoDBTestCase):
    """Test networking helpers."""

    @mock.patch('oslo_concurrency.processutils.execute',
                return_value=('', ''))
    def test_set_device_mtu_default(self, mock_exec):
        calls = []
        nova.privsep.linux_net._set_device_mtu_inner('fake-dev', None)
        mock_exec.assert_has_calls(calls)

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    def test_create_tap_dev(self, mock_enabled, mock_execute):
        nova.privsep.linux_net._create_tap_dev_inner('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      check_exit_code=[0, 2, 254])
        ])
        mock_enabled.assert_called_once_with('tap42')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_create_tap_skipped_when_exists(self, mock_execute, mock_exists):
        nova.privsep.linux_net._create_tap_dev_inner('tap42')

        mock_exists.assert_called_once_with('/sys/class/net/tap42')
        mock_execute.assert_not_called()

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    @mock.patch('nova.privsep.linux_net._set_device_macaddr_inner')
    def test_create_tap_dev_mac(self, mock_set_macaddr, mock_enabled,
                                mock_execute):
        nova.privsep.linux_net._create_tap_dev_inner(
            'tap42', '00:11:22:33:44:55')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      check_exit_code=[0, 2, 254])
        ])
        mock_enabled.assert_called_once_with('tap42')
        mock_set_macaddr.assert_has_calls([
            mock.call('tap42', '00:11:22:33:44:55')])

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    def test_create_tap_dev_fallback_to_tunctl(self, mock_enabled,
                                               mock_execute):
        # ip failed, fall back to tunctl
        mock_execute.side_effect = [processutils.ProcessExecutionError, 0, 0]

        nova.privsep.linux_net._create_tap_dev_inner('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      check_exit_code=[0, 2, 254]),
            mock.call('tunctl', '-b', '-t', 'tap42')
        ])
        mock_enabled.assert_called_once_with('tap42')

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    def test_create_tap_dev_multiqueue(self, mock_enabled, mock_execute):
        nova.privsep.linux_net._create_tap_dev_inner(
            'tap42', multiqueue=True)

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      'multi_queue', check_exit_code=[0, 2, 254])
        ])
        mock_enabled.assert_called_once_with('tap42')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_create_tap_dev_multiqueue_tunctl_raises(self, mock_execute):
        # if creation of a tap by the means of ip command fails,
        # create_tap_dev() will try to do that by the means of tunctl
        mock_execute.side_effect = processutils.ProcessExecutionError
        # but tunctl can't create multiqueue taps, so the failure is expected
        self.assertRaises(processutils.ProcessExecutionError,
                          nova.privsep.linux_net._create_tap_dev_inner,
                          'tap42', multiqueue=True)
