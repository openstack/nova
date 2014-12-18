# Copyright (c) 2015 Quobyte Inc.
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
"""Unit tests for the Quobyte volume driver module."""

import mock
import os

from oslo_concurrency import processutils

from nova import exception
from nova.openstack.common import fileutils
from nova import test
from nova import utils
from nova.virt.libvirt import quobyte


class QuobyteTestCase(test.NoDBTestCase):

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch.object(utils, "execute")
    def test_quobyte_mount_volume(self, mock_execute, mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.mount_volume(quobyte_volume, export_mnt_base)

        mock_ensure_tree.assert_called_once_with(export_mnt_base)
        expected_commands = [mock.call('mount.quobyte',
                                       quobyte_volume,
                                       export_mnt_base,
                                       check_exit_code=[0, 4])
                             ]
        mock_execute.assert_has_calls(expected_commands)

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch.object(utils, "execute")
    def test_quobyte_mount_volume_with_config(self,
                                              mock_execute,
                                              mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))
        config_file_dummy = "/etc/quobyte/dummy.conf"

        quobyte.mount_volume(quobyte_volume,
                             export_mnt_base,
                             config_file_dummy)

        mock_ensure_tree.assert_called_once_with(export_mnt_base)
        expected_commands = [mock.call('mount.quobyte',
                                       quobyte_volume,
                                       export_mnt_base,
                                       '-c',
                                       config_file_dummy,
                                       check_exit_code=[0, 4])
                             ]
        mock_execute.assert_has_calls(expected_commands)

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.
                                    ProcessExecutionError))
    def test_quobyte_mount_volume_fails(self, mock_execute, mock_ensure_tree):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        self.assertRaises(processutils.ProcessExecutionError,
                          quobyte.mount_volume,
                          quobyte_volume,
                          export_mnt_base)

    @mock.patch.object(utils, "execute")
    def test_quobyte_umount_volume(self, mock_execute):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.umount_volume(export_mnt_base)

        mock_execute.assert_called_once_with('umount.quobyte',
                                             export_mnt_base)

    @mock.patch.object(quobyte.LOG, "error")
    @mock.patch.object(utils, "execute")
    def test_quobyte_umount_volume_warns(self,
                                         mock_execute,
                                         mock_debug):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        def exec_side_effect(*cmd, **kwargs):
            exerror = processutils.ProcessExecutionError()
            exerror.message = "Device or resource busy"
            raise exerror
        mock_execute.side_effect = exec_side_effect

        quobyte.umount_volume(export_mnt_base)

        (mock_debug.
         assert_called_once_with("The Quobyte volume at %s is still in use.",
                                 export_mnt_base))

    @mock.patch.object(quobyte.LOG, "exception")
    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.ProcessExecutionError))
    def test_quobyte_umount_volume_fails(self,
                                         mock_execute,
                                         mock_exception):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.umount_volume(export_mnt_base)

        (mock_exception.
         assert_called_once_with("Couldn't unmount "
                                 "the Quobyte Volume at %s",
                                 export_mnt_base))

    @mock.patch.object(os, "access", return_value=True)
    @mock.patch.object(utils, "execute")
    def test_quobyte_is_valid_volume(self, mock_execute, mock_access):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        quobyte.validate_volume(export_mnt_base)

        mock_execute.assert_called_once_with('getfattr',
                                             '-n',
                                             'quobyte.info',
                                             export_mnt_base)

    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.
                                    ProcessExecutionError))
    def test_quobyte_is_valid_volume_vol_not_valid_volume(self, mock_execute):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        self.assertRaises(exception.NovaException,
                          quobyte.validate_volume,
                          export_mnt_base)

    @mock.patch.object(os, "access", return_value=False)
    @mock.patch.object(utils, "execute",
                       side_effect=(processutils.
                                    ProcessExecutionError))
    def test_quobyte_is_valid_volume_vol_no_valid_access(self,
                                                         mock_execute,
                                                         mock_access):
        mnt_base = '/mnt'
        quobyte_volume = '192.168.1.1/volume-00001'
        export_mnt_base = os.path.join(mnt_base,
                                       utils.get_hash_str(quobyte_volume))

        self.assertRaises(exception.NovaException,
                          quobyte.validate_volume,
                          export_mnt_base)
