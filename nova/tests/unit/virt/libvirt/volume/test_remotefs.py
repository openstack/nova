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
from oslo_concurrency import processutils

from nova import test
from nova import utils
from nova.virt.libvirt.volume import remotefs


class RemoteFSTestCase(test.NoDBTestCase):
    """Remote filesystem operations test case."""

    @mock.patch.object(utils, 'execute')
    def _test_mount_share(self, mock_execute, already_mounted=False):
        if already_mounted:
            err_msg = 'Device or resource busy'
            mock_execute.side_effect = [
                None, processutils.ProcessExecutionError(err_msg)]

        remotefs.mount_share(
            mock.sentinel.mount_path, mock.sentinel.export_path,
            mock.sentinel.export_type,
            options=[mock.sentinel.mount_options])

        mock_execute.assert_any_call('mkdir', '-p',
                                     mock.sentinel.mount_path)
        mock_execute.assert_any_call('mount', '-t', mock.sentinel.export_type,
                                     mock.sentinel.mount_options,
                                     mock.sentinel.export_path,
                                     mock.sentinel.mount_path,
                                     run_as_root=True)

    def test_mount_new_share(self):
        self._test_mount_share()

    def test_mount_already_mounted_share(self):
        self._test_mount_share(already_mounted=True)

    @mock.patch.object(utils, 'execute')
    def test_unmount_share(self, mock_execute):
        remotefs.unmount_share(
            mock.sentinel.mount_path, mock.sentinel.export_path)

        mock_execute.assert_any_call('umount', mock.sentinel.mount_path,
                                     run_as_root=True, attempts=3,
                                     delay_on_retry=True)

    @mock.patch('tempfile.mkdtemp', return_value='/tmp/Mercury')
    @mock.patch('nova.utils.execute')
    def test_remove_remote_file_rsync(self, mock_execute, mock_mkdtemp):
        remotefs.RsyncDriver().remove_file('host', 'dest', None, None)
        rsync_call_args = mock.call('rsync', '--archive',
                                    '--delete', '--include',
                                    'dest', '--exclude', '*',
                                    '/tmp/Mercury/', 'host:',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)
        rm_call_args = mock.call('rm', '-rf', '/tmp/Mercury')
        self.assertEqual(mock_execute.mock_calls[1], rm_call_args)
        self.assertEqual(2, mock_execute.call_count)
        self.assertEqual(1, mock_mkdtemp.call_count)

    @mock.patch('nova.utils.ssh_execute')
    def test_remove_remote_file_ssh(self, mock_ssh_execute):
        remotefs.SshDriver().remove_file('host', 'dest', None, None)
        mock_ssh_execute.assert_called_once_with(
            'host', 'rm', 'dest',
            on_completion=None, on_execute=None)

    @mock.patch('tempfile.mkdtemp', return_value='/tmp/Venus')
    @mock.patch('nova.utils.execute')
    def test_remove_remote_dir_rsync(self, mock_execute, mock_mkdtemp):
        remotefs.RsyncDriver().remove_dir('host', 'dest', None, None)
        rsync_call_args = mock.call('rsync', '--archive',
                                    '--delete-excluded', '/tmp/Venus/',
                                    'host:dest',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)
        rsync_call_args = mock.call('rsync', '--archive',
                                    '--delete', '--include',
                                    'dest', '--exclude', '*',
                                    '/tmp/Venus/', 'host:',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)
        rm_call_args = mock.call('rm', '-rf', '/tmp/Venus')
        self.assertEqual(mock_execute.mock_calls[2], rm_call_args)
        self.assertEqual(3, mock_execute.call_count)
        self.assertEqual(1, mock_mkdtemp.call_count)

    @mock.patch('nova.utils.ssh_execute')
    def test_remove_remote_dir_ssh(self, mock_ssh_execute):
        remotefs.SshDriver().remove_dir('host', 'dest', None, None)
        mock_ssh_execute.assert_called_once_with(
            'host', 'rm', '-rf', 'dest', on_completion=None,
            on_execute=None)

    @mock.patch('tempfile.mkdtemp', return_value='/tmp/Mars')
    @mock.patch('nova.utils.execute')
    def test_create_remote_file_rsync(self, mock_execute, mock_mkdtemp):
        remotefs.RsyncDriver().create_file('host', 'dest_dir', None, None)
        mkdir_call_args = mock.call('mkdir', '-p', '/tmp/Mars/',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], mkdir_call_args)
        touch_call_args = mock.call('touch', '/tmp/Mars/dest_dir',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[1], touch_call_args)
        rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                    '--no-implied-dirs',
                                    '/tmp/Mars/./dest_dir', 'host:/',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[2], rsync_call_args)
        rm_call_args = mock.call('rm', '-rf', '/tmp/Mars')
        self.assertEqual(mock_execute.mock_calls[3], rm_call_args)
        self.assertEqual(4, mock_execute.call_count)
        self.assertEqual(1, mock_mkdtemp.call_count)

    @mock.patch('nova.utils.ssh_execute')
    def test_create_remote_file_ssh(self, mock_ssh_execute):
        remotefs.SshDriver().create_file('host', 'dest_dir', None, None)
        mock_ssh_execute.assert_called_once_with('host', 'touch',
                                                 'dest_dir',
                                                 on_completion=None,
                                                 on_execute=None)

    @mock.patch('tempfile.mkdtemp', return_value='/tmp/Jupiter')
    @mock.patch('nova.utils.execute')
    def test_create_remote_dir_rsync(self, mock_execute, mock_mkdtemp):
        remotefs.RsyncDriver().create_dir('host', 'dest_dir', None, None)
        mkdir_call_args = mock.call('mkdir', '-p', '/tmp/Jupiter/dest_dir',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], mkdir_call_args)
        rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                    '--no-implied-dirs',
                                    '/tmp/Jupiter/./dest_dir', 'host:/',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)
        rm_call_args = mock.call('rm', '-rf', '/tmp/Jupiter')
        self.assertEqual(mock_execute.mock_calls[2], rm_call_args)
        self.assertEqual(3, mock_execute.call_count)
        self.assertEqual(1, mock_mkdtemp.call_count)

    @mock.patch('nova.utils.ssh_execute')
    def test_create_remote_dir_ssh(self, mock_ssh_execute):
        remotefs.SshDriver().create_dir('host', 'dest_dir', None, None)
        mock_ssh_execute.assert_called_once_with('host', 'mkdir',
                                                 '-p', 'dest_dir',
                                                 on_completion=None,
                                                 on_execute=None)

    @mock.patch('nova.utils.execute')
    def test_remote_copy_file_rsync(self, mock_execute):
        remotefs.RsyncDriver().copy_file('1.2.3.4:/home/star_wars',
                                         '/home/favourite', None, None,
                                         compression=True)
        mock_execute.assert_called_once_with('rsync', '-r', '--sparse',
                                             '1.2.3.4:/home/star_wars',
                                             '/home/favourite',
                                             '--compress',
                                             on_completion=None,
                                             on_execute=None)

    @mock.patch('nova.utils.execute')
    def test_remote_copy_file_rsync_without_compression(self, mock_execute):
        remotefs.RsyncDriver().copy_file('1.2.3.4:/home/star_wars',
                                         '/home/favourite', None, None,
                                         compression=False)
        mock_execute.assert_called_once_with('rsync', '-r', '--sparse',
                                             '1.2.3.4:/home/star_wars',
                                             '/home/favourite',
                                             on_completion=None,
                                             on_execute=None)

    @mock.patch('nova.utils.execute')
    def test_remote_copy_file_ssh(self, mock_execute):
        remotefs.SshDriver().copy_file('1.2.3.4:/home/SpaceOdyssey',
                                       '/home/favourite', None, None, True)
        mock_execute.assert_called_once_with('scp', '-r',
                                             '1.2.3.4:/home/SpaceOdyssey',
                                             '/home/favourite',
                                             on_completion=None,
                                             on_execute=None)

    @mock.patch('tempfile.mkdtemp', return_value='/tmp/Saturn')
    def test_rsync_driver_ipv6(self, mock_mkdtemp):
        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().create_file('2600::', 'dest_dir', None,
                                               None)
            rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                        '--no-implied-dirs',
                                        '/tmp/Saturn/./dest_dir', '[2600::]:/',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[2], rsync_call_args)

        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().create_dir('2600::', 'dest_dir', None, None)
            rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                        '--no-implied-dirs',
                                        '/tmp/Saturn/./dest_dir', '[2600::]:/',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)

        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().remove_file('2600::', 'dest', None, None)
            rsync_call_args = mock.call('rsync', '--archive',
                                        '--delete', '--include',
                                        'dest', '--exclude', '*',
                                        '/tmp/Saturn/', '[2600::]:',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)

        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().remove_dir('2600::', 'dest', None, None)
            rsync_call_args = mock.call('rsync', '--archive',
                                        '--delete-excluded', '/tmp/Saturn/',
                                        '[2600::]:dest',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)
            rsync_call_args = mock.call('rsync', '--archive',
                                        '--delete', '--include',
                                        'dest', '--exclude', '*',
                                        '/tmp/Saturn/', '[2600::]:',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)
