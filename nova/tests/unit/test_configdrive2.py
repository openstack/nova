# Copyright 2012 Michael Still and Canonical Inc
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


import os
import tempfile

import mock
from oslo_config import cfg
from oslo_utils import fileutils

from nova import context
from nova import test
from nova.tests.unit import fake_instance
from nova import utils
from nova.virt import configdrive

CONF = cfg.CONF


class FakeInstanceMD(object):
    def metadata_for_config_drive(self):
        yield ('this/is/a/path/hello', 'This is some content')
        yield ('this/is/a/path/hi', b'This is some other content')


class ConfigDriveTestCase(test.NoDBTestCase):

    @mock.patch.object(utils, 'execute', return_value=None)
    def test_create_configdrive_iso(self, mock_execute):
        CONF.set_override('config_drive_format', 'iso9660')
        imagefile = None

        try:
            with configdrive.ConfigDriveBuilder(FakeInstanceMD()) as c:
                (fd, imagefile) = tempfile.mkstemp(prefix='cd_iso_')
                os.close(fd)
                c.make_drive(imagefile)

            mock_execute.assert_called_once_with('genisoimage', '-o',
                                                 mock.ANY,
                                                 '-ldots', '-allow-lowercase',
                                                 '-allow-multidot', '-l',
                                                 '-publisher',
                                                 mock.ANY,
                                                 '-quiet', '-J', '-r',
                                                 '-V', 'config-2',
                                                 mock.ANY,
                                                 attempts=1,
                                                 run_as_root=False)
        finally:
            if imagefile:
                fileutils.delete_if_exists(imagefile)

    @mock.patch.object(utils, 'mkfs', return_value=None)
    @mock.patch('nova.privsep.fs.mount', return_value=('', ''))
    @mock.patch('nova.privsep.fs.umount', return_value=None)
    @mock.patch.object(utils, 'trycmd', return_value=(None, None))
    def test_create_configdrive_vfat(self, mock_trycmd, mock_umount,
                                     mock_mount, mock_mkfs):
        CONF.set_override('config_drive_format', 'vfat')
        imagefile = None
        try:
            with configdrive.ConfigDriveBuilder(FakeInstanceMD()) as c:
                (fd, imagefile) = tempfile.mkstemp(prefix='cd_vfat_')
                os.close(fd)
                c.make_drive(imagefile)

            mock_mkfs.assert_called_once_with('vfat', mock.ANY,
                                              label='config-2')
            mock_mount.assert_called_once()
            mock_umount.assert_called_once()
            # NOTE(mikal): we can't check for a VFAT output here because the
            # filesystem creation stuff has been mocked out because it
            # requires root permissions

        finally:
            if imagefile:
                fileutils.delete_if_exists(imagefile)

    def test_config_drive_required_by_image_property(self):
        inst = fake_instance.fake_instance_obj(context.get_admin_context())
        inst.config_drive = ''
        inst.system_metadata = {
            utils.SM_IMAGE_PROP_PREFIX + 'img_config_drive': 'mandatory'}
        self.assertTrue(configdrive.required_by(inst))

        inst.system_metadata = {
            utils.SM_IMAGE_PROP_PREFIX + 'img_config_drive': 'optional'}
        self.assertFalse(configdrive.required_by(inst))

    @mock.patch.object(configdrive, 'required_by', return_value=False)
    def test_config_drive_update_instance_required_by_false(self,
                                                            mock_required):
        inst = fake_instance.fake_instance_obj(context.get_admin_context())
        inst.config_drive = ''
        configdrive.update_instance(inst)
        self.assertEqual('', inst.config_drive)

        inst.config_drive = True
        configdrive.update_instance(inst)
        self.assertTrue(inst.config_drive)

    @mock.patch.object(configdrive, 'required_by', return_value=True)
    def test_config_drive_update_instance(self, mock_required):
        inst = fake_instance.fake_instance_obj(context.get_admin_context())
        inst.config_drive = ''
        configdrive.update_instance(inst)
        self.assertTrue(inst.config_drive)

        inst.config_drive = True
        configdrive.update_instance(inst)
        self.assertTrue(inst.config_drive)
