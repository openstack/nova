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

from mox3 import mox
from oslo_config import cfg

from nova import context
from nova.openstack.common import fileutils
from nova import test
from nova.tests.unit import fake_instance
from nova import utils
from nova.virt import configdrive

CONF = cfg.CONF


class FakeInstanceMD(object):
    def metadata_for_config_drive(self):
        yield ('this/is/a/path/hello', 'This is some content')


class ConfigDriveTestCase(test.NoDBTestCase):

    def test_create_configdrive_iso(self):
        CONF.set_override('config_drive_format', 'iso9660')
        imagefile = None

        try:
            self.mox.StubOutWithMock(utils, 'execute')

            utils.execute('genisoimage', '-o', mox.IgnoreArg(), '-ldots',
                          '-allow-lowercase', '-allow-multidot', '-l',
                          '-publisher', mox.IgnoreArg(), '-quiet', '-J', '-r',
                          '-V', 'config-2', mox.IgnoreArg(), attempts=1,
                          run_as_root=False).AndReturn(None)

            self.mox.ReplayAll()

            with configdrive.ConfigDriveBuilder(FakeInstanceMD()) as c:
                (fd, imagefile) = tempfile.mkstemp(prefix='cd_iso_')
                os.close(fd)
                c.make_drive(imagefile)

        finally:
            if imagefile:
                fileutils.delete_if_exists(imagefile)

    def test_create_configdrive_vfat(self):
        CONF.set_override('config_drive_format', 'vfat')
        imagefile = None
        try:
            self.mox.StubOutWithMock(utils, 'mkfs')
            self.mox.StubOutWithMock(utils, 'execute')
            self.mox.StubOutWithMock(utils, 'trycmd')

            utils.mkfs('vfat', mox.IgnoreArg(),
                       label='config-2').AndReturn(None)
            utils.trycmd('mount', '-o', mox.IgnoreArg(), mox.IgnoreArg(),
                         mox.IgnoreArg(),
                         run_as_root=True).AndReturn((None, None))
            utils.execute('umount', mox.IgnoreArg(),
                          run_as_root=True).AndReturn(None)

            self.mox.ReplayAll()

            with configdrive.ConfigDriveBuilder(FakeInstanceMD()) as c:
                (fd, imagefile) = tempfile.mkstemp(prefix='cd_vfat_')
                os.close(fd)
                c.make_drive(imagefile)

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
