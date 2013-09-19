# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

import tempfile

import fixtures

from nova import test
from nova.virt.disk import api


class APITestCase(test.NoDBTestCase):

    def test_can_resize_need_fs_type_specified(self):
        # NOTE(mikal): Bug 1094373 saw a regression where we failed to
        # treat a failure to mount as a failure to be able to resize the
        # filesystem
        def _fake_get_disk_size(path):
            return 10
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.api.get_disk_size', _fake_get_disk_size))

        def fake_trycmd(*args, **kwargs):
            return '', 'broken'
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        def fake_returns_true(*args, **kwargs):
            return True
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.mount.nbd.NbdMount.get_dev',
                fake_returns_true))
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.mount.nbd.NbdMount.map_dev',
                fake_returns_true))

        # Force the use of localfs, which is what was used during the failure
        # reported in the bug
        def fake_import_fails(*args, **kwargs):
            raise Exception('Failed')
        self.useFixture(fixtures.MonkeyPatch(
                'nova.openstack.common.importutils.import_module',
                fake_import_fails))

        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        self.assertFalse(api.is_image_partitionless(imgfile, use_cow=True))
