#  Copyright 2014 IBM Corp.
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

import os
import time

import mock
from six.moves import builtins

from nova import exception
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils


class PathUtilsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V PathUtils class."""

    def setUp(self):
        super(PathUtilsTestCase, self).setUp()
        self.fake_instance_dir = os.path.join('C:', 'fake_instance_dir')
        self.fake_instance_name = 'fake_instance_name'

        self._pathutils = pathutils.PathUtils()

    def _mock_lookup_configdrive_path(self, ext, rescue=False):
        self._pathutils.get_instance_dir = mock.MagicMock(
            return_value=self.fake_instance_dir)

        def mock_exists(*args, **kwargs):
            path = args[0]
            return True if path[(path.rfind('.') + 1):] == ext else False
        self._pathutils.exists = mock_exists
        configdrive_path = self._pathutils.lookup_configdrive_path(
            self.fake_instance_name, rescue)
        return configdrive_path

    def _test_lookup_configdrive_path(self, rescue=False):
        configdrive_name = 'configdrive'
        if rescue:
            configdrive_name += '-rescue'

        for format_ext in constants.DISK_FORMAT_MAP:
            configdrive_path = self._mock_lookup_configdrive_path(format_ext,
                                                                  rescue)
            expected_path = os.path.join(self.fake_instance_dir,
                                         configdrive_name + '.' + format_ext)
            self.assertEqual(expected_path, configdrive_path)

    def test_lookup_configdrive_path(self):
        self._test_lookup_configdrive_path()

    def test_lookup_rescue_configdrive_path(self):
        self._test_lookup_configdrive_path(rescue=True)

    def test_lookup_configdrive_path_non_exist(self):
        self._pathutils.get_instance_dir = mock.MagicMock(
            return_value=self.fake_instance_dir)
        self._pathutils.exists = mock.MagicMock(return_value=False)
        configdrive_path = self._pathutils.lookup_configdrive_path(
            self.fake_instance_name)
        self.assertIsNone(configdrive_path)

    def test_get_instances_dir_local(self):
        self.flags(instances_path=self.fake_instance_dir)
        instances_dir = self._pathutils.get_instances_dir()

        self.assertEqual(self.fake_instance_dir, instances_dir)

    def test_get_instances_dir_remote_instance_share(self):
        # The Hyper-V driver allows using a pre-configured share exporting
        # the instances dir. The same share name should be used across nodes.
        fake_instances_dir_share = 'fake_instances_dir_share'
        fake_remote = 'fake_remote'
        expected_instance_dir = r'\\%s\%s' % (fake_remote,
                                              fake_instances_dir_share)

        self.flags(instances_path_share=fake_instances_dir_share,
                   group='hyperv')
        instances_dir = self._pathutils.get_instances_dir(
            remote_server=fake_remote)
        self.assertEqual(expected_instance_dir, instances_dir)

    def test_get_instances_dir_administrative_share(self):
        self.flags(instances_path=r'C:\fake_instance_dir')
        fake_remote = 'fake_remote'
        expected_instance_dir = r'\\fake_remote\C$\fake_instance_dir'

        instances_dir = self._pathutils.get_instances_dir(
            remote_server=fake_remote)
        self.assertEqual(expected_instance_dir, instances_dir)

    def test_get_instances_dir_unc_path(self):
        fake_instance_dir = r'\\fake_addr\fake_share\fake_instance_dir'
        self.flags(instances_path=fake_instance_dir)
        fake_remote = 'fake_remote'

        instances_dir = self._pathutils.get_instances_dir(
            remote_server=fake_remote)
        self.assertEqual(fake_instance_dir, instances_dir)

    @mock.patch('os.path.join')
    def test_get_instances_sub_dir(self, fake_path_join):

        class WindowsError(Exception):
            def __init__(self, winerror=None):
                self.winerror = winerror

        fake_dir_name = "fake_dir_name"
        fake_windows_error = WindowsError
        self._pathutils.check_create_dir = mock.MagicMock(
            side_effect=WindowsError(pathutils.ERROR_INVALID_NAME))
        with mock.patch.object(builtins, 'WindowsError',
                               fake_windows_error, create=True):
            self.assertRaises(exception.AdminRequired,
                              self._pathutils._get_instances_sub_dir,
                              fake_dir_name)

    def test_copy_vm_console_logs(self):
        fake_local_logs = [mock.sentinel.log_path,
                           mock.sentinel.archived_log_path]
        fake_remote_logs = [mock.sentinel.remote_log_path,
                            mock.sentinel.remote_archived_log_path]

        self._pathutils.exists = mock.Mock(return_value=True)
        self._pathutils.copy = mock.Mock()
        self._pathutils.get_vm_console_log_paths = mock.Mock(
            side_effect=[fake_local_logs, fake_remote_logs])

        self._pathutils.copy_vm_console_logs(mock.sentinel.instance_name,
                                            mock.sentinel.dest_host)

        self._pathutils.get_vm_console_log_paths.assert_has_calls(
            [mock.call(mock.sentinel.instance_name),
             mock.call(mock.sentinel.instance_name,
                       remote_server=mock.sentinel.dest_host)])
        self._pathutils.copy.assert_has_calls([
            mock.call(mock.sentinel.log_path,
                      mock.sentinel.remote_log_path),
            mock.call(mock.sentinel.archived_log_path,
                      mock.sentinel.remote_archived_log_path)])

    @mock.patch.object(pathutils.PathUtils, 'get_base_vhd_dir')
    @mock.patch.object(pathutils.PathUtils, 'exists')
    def test_get_image_path(self, mock_exists,
                            mock_get_base_vhd_dir):
        fake_image_name = 'fake_image_name'
        mock_exists.side_effect = [True, False]
        mock_get_base_vhd_dir.return_value = 'fake_base_dir'

        res = self._pathutils.get_image_path(fake_image_name)

        mock_get_base_vhd_dir.assert_called_once_with()

        self.assertEqual(res,
            os.path.join('fake_base_dir', 'fake_image_name.vhd'))

    @mock.patch('os.path.getmtime')
    @mock.patch.object(pathutils, 'time')
    def test_get_age_of_file(self, mock_time, mock_getmtime):
        mock_time.time.return_value = time.time()
        mock_getmtime.return_value = mock_time.time.return_value - 42

        actual_age = self._pathutils.get_age_of_file(mock.sentinel.filename)
        self.assertEqual(42, actual_age)
        mock_time.time.assert_called_once_with()
        mock_getmtime.assert_called_once_with(mock.sentinel.filename)

    @mock.patch('os.path.exists')
    @mock.patch('tempfile.NamedTemporaryFile')
    def test_check_dirs_shared_storage(self, mock_named_tempfile,
                                       mock_exists):
        fake_src_dir = 'fake_src_dir'
        fake_dest_dir = 'fake_dest_dir'

        mock_exists.return_value = True
        mock_tmpfile = mock_named_tempfile.return_value.__enter__.return_value
        mock_tmpfile.name = 'fake_tmp_fname'
        expected_src_tmp_path = os.path.join(fake_src_dir,
                                             mock_tmpfile.name)

        self._pathutils.check_dirs_shared_storage(
            fake_src_dir, fake_dest_dir)

        mock_named_tempfile.assert_called_once_with(dir=fake_dest_dir)
        mock_exists.assert_called_once_with(expected_src_tmp_path)

    @mock.patch('os.path.exists')
    @mock.patch('tempfile.NamedTemporaryFile')
    def test_check_dirs_shared_storage_exception(self, mock_named_tempfile,
                                                 mock_exists):
        fake_src_dir = 'fake_src_dir'
        fake_dest_dir = 'fake_dest_dir'

        mock_exists.return_value = True
        mock_named_tempfile.side_effect = OSError('not exist')

        self.assertRaises(exception.FileNotFound,
            self._pathutils.check_dirs_shared_storage,
            fake_src_dir, fake_dest_dir)

    @mock.patch.object(pathutils.PathUtils, 'check_dirs_shared_storage')
    @mock.patch.object(pathutils.PathUtils, 'get_instances_dir')
    def test_check_remote_instances_shared(self, mock_get_instances_dir,
                                           mock_check_dirs_shared_storage):
        mock_get_instances_dir.side_effect = [mock.sentinel.local_inst_dir,
                                              mock.sentinel.remote_inst_dir]

        shared_storage = self._pathutils.check_remote_instances_dir_shared(
            mock.sentinel.dest)

        self.assertEqual(mock_check_dirs_shared_storage.return_value,
                         shared_storage)
        mock_get_instances_dir.assert_has_calls(
            [mock.call(), mock.call(mock.sentinel.dest)])
        mock_check_dirs_shared_storage.assert_called_once_with(
            mock.sentinel.local_inst_dir, mock.sentinel.remote_inst_dir)
