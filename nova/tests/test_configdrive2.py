# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import mox
import os
import tempfile

from nova import test

from nova import flags
from nova.openstack.common import log
from nova import utils
from nova.virt import configdrive
from nova.virt.libvirt import utils as virtutils


FLAGS = flags.FLAGS

LOG = log.getLogger(__name__)


class ConfigDriveTestCase(test.TestCase):

    def test_create_configdrive_iso(self):
        imagefile = None

        try:
            self.mox.StubOutWithMock(utils, 'execute')

            utils.execute('genisoimage', '-o', mox.IgnoreArg(), '-ldots',
                          '-allow-lowercase', '-allow-multidot', '-l',
                          '-publisher', mox.IgnoreArg(), '-quiet', '-J', '-r',
                          '-V', 'config-2', mox.IgnoreArg(), attempts=1,
                          run_as_root=False).AndReturn(None)

            self.mox.ReplayAll()

            c = configdrive.ConfigDriveBuilder()
            c._add_file('this/is/a/path/hello', 'This is some content')
            (fd, imagefile) = tempfile.mkstemp(prefix='cd_iso_')
            os.close(fd)
            c._make_iso9660(imagefile)
            c.cleanup()

            # Check cleanup
            self.assertFalse(os.path.exists(c.tempdir))

        finally:
            if imagefile:
                utils.delete_if_exists(imagefile)

    def test_create_configdrive_vfat(self):
        imagefile = None
        try:
            self.mox.StubOutWithMock(virtutils, 'mkfs')
            self.mox.StubOutWithMock(utils, 'execute')
            self.mox.StubOutWithMock(utils, 'trycmd')

            virtutils.mkfs('vfat', mox.IgnoreArg(),
                           label='config-2').AndReturn(None)
            utils.trycmd('mount', '-o', 'loop', mox.IgnoreArg(),
                         mox.IgnoreArg(),
                         run_as_root=True).AndReturn((None, None))
            utils.trycmd('chown', mox.IgnoreArg(), mox.IgnoreArg(),
                         run_as_root=True).AndReturn((None, None))
            utils.execute('umount', mox.IgnoreArg(),
                          run_as_root=True).AndReturn(None)

            self.mox.ReplayAll()

            c = configdrive.ConfigDriveBuilder()
            c._add_file('this/is/a/path/hello', 'This is some content')
            (fd, imagefile) = tempfile.mkstemp(prefix='cd_vfat_')
            os.close(fd)
            c._make_vfat(imagefile)
            c.cleanup()

            # Check cleanup
            self.assertFalse(os.path.exists(c.tempdir))

            # NOTE(mikal): we can't check for a VFAT output here because the
            # filesystem creation stuff has been mocked out because it
            # requires root permissions

        finally:
            if imagefile:
                utils.delete_if_exists(imagefile)
