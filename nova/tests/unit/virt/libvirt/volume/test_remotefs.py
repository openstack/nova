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
from nova.virt.libvirt.volume import remotefs


class RemoteFSTestCase(test.NoDBTestCase):
    """Remote filesystem operations test case."""

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    def _test_mount_share(self, mock_mount, mock_ensure_tree,
                          already_mounted=False):
        if already_mounted:
            err_msg = 'Device or resource busy'
            mock_mount.side_effect = [
                None, processutils.ProcessExecutionError(err_msg)]

        remotefs.mount_share(
            mock.sentinel.mount_path, mock.sentinel.export_path,
            mock.sentinel.export_type,
            options=[mock.sentinel.mount_options])

        mock_ensure_tree.assert_any_call(mock.sentinel.mount_path)
        mock_mount.assert_has_calls(
            [mock.call(mock.sentinel.export_type,
                       mock.sentinel.export_path,
                       mock.sentinel.mount_path,
                       [mock.sentinel.mount_options])])

    def test_mount_new_share(self):
        self._test_mount_share()

    def test_mount_already_mounted_share(self):
        self._test_mount_share(already_mounted=True)

    @mock.patch('nova.privsep.fs.umount')
    def test_unmount_share(self, mock_umount):
        remotefs.unmount_share(
            mock.sentinel.mount_path, mock.sentinel.export_path)

        mock_umount.assert_has_calls(
            [mock.call(mock.sentinel.mount_path)])

    @mock.patch('nova.utils.execute')
    def test_remove_remote_file_rsync(self, mock_execute):
        remotefs.RsyncDriver().remove_file('host', 'dest', None, None)
        rsync_call_args = mock.call('rsync', '--archive',
                                    '--delete', '--include',
                                    'dest', '--exclude', '*',
                                    mock.ANY, 'host:',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch('nova.utils.ssh_execute')
    def test_remove_remote_file_ssh(self, mock_ssh_execute):
        remotefs.SshDriver().remove_file('host', 'dest', None, None)
        mock_ssh_execute.assert_called_once_with(
            'host', 'rm', 'dest',
            on_completion=None, on_execute=None)

    @mock.patch('nova.utils.execute')
    def test_remove_remote_dir_rsync(self, mock_execute):
        remotefs.RsyncDriver().remove_dir('host', 'dest', None, None)
        rsync_call_args = mock.call('rsync', '--archive',
                                    '--delete-excluded', mock.ANY,
                                    'host:dest',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)
        rsync_call_args = mock.call('rsync', '--archive',
                                    '--delete', '--include',
                                    'dest', '--exclude', '*',
                                    mock.ANY, 'host:',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)
        self.assertEqual(2, mock_execute.call_count)

    @mock.patch('nova.utils.ssh_execute')
    def test_remove_remote_dir_ssh(self, mock_ssh_execute):
        remotefs.SshDriver().remove_dir('host', 'dest', None, None)
        mock_ssh_execute.assert_called_once_with(
            'host', 'rm', '-rf', 'dest', on_completion=None,
            on_execute=None)

    @mock.patch('nova.utils.execute')
    def test_create_remote_file_rsync(self, mock_execute):
        remotefs.RsyncDriver().create_file('host', 'dest_dir', None, None)
        mkdir_call_args = mock.call('mkdir', '-p', mock.ANY,
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], mkdir_call_args)
        touch_call_args = mock.call('touch', mock.ANY,
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[1], touch_call_args)
        rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                    '--no-implied-dirs',
                                    mock.ANY, 'host:/',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[2], rsync_call_args)
        self.assertEqual(3, mock_execute.call_count)

    @mock.patch('nova.utils.ssh_execute')
    def test_create_remote_file_ssh(self, mock_ssh_execute):
        remotefs.SshDriver().create_file('host', 'dest_dir', None, None)
        mock_ssh_execute.assert_called_once_with('host', 'touch',
                                                 'dest_dir',
                                                 on_completion=None,
                                                 on_execute=None)

    @mock.patch('nova.utils.execute')
    def test_create_remote_dir_rsync(self, mock_execute):
        remotefs.RsyncDriver().create_dir('host', 'dest_dir', None, None)
        mkdir_call_args = mock.call('mkdir', '-p', mock.ANY,
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[0], mkdir_call_args)
        rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                    '--no-implied-dirs',
                                    mock.ANY, 'host:/',
                                    on_completion=None, on_execute=None)
        self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)
        self.assertEqual(2, mock_execute.call_count)

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

    def test_rsync_driver_ipv6(self):
        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().create_file('2600::', 'dest_dir', None,
                                               None)
            rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                        '--no-implied-dirs',
                                        mock.ANY, '[2600::]:/',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[2], rsync_call_args)

        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().create_dir('2600::', 'dest_dir', None, None)
            rsync_call_args = mock.call('rsync', '--archive', '--relative',
                                        '--no-implied-dirs',
                                        mock.ANY, '[2600::]:/',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)

        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().remove_file('2600::', 'dest', None, None)
            rsync_call_args = mock.call('rsync', '--archive',
                                        '--delete', '--include',
                                        'dest', '--exclude', '*',
                                        mock.ANY, '[2600::]:',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)

        with mock.patch('nova.utils.execute') as mock_execute:
            remotefs.RsyncDriver().remove_dir('2600::', 'dest', None, None)
            rsync_call_args = mock.call('rsync', '--archive',
                                        '--delete-excluded', mock.ANY,
                                        '[2600::]:dest',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[0], rsync_call_args)
            rsync_call_args = mock.call('rsync', '--archive',
                                        '--delete', '--include',
                                        'dest', '--exclude', '*',
                                        mock.ANY, '[2600::]:',
                                        on_completion=None, on_execute=None)
            self.assertEqual(mock_execute.mock_calls[1], rsync_call_args)
