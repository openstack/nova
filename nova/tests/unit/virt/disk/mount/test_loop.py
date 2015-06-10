# Copyright 2012 Michael Still
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


import fixtures

from nova import test
from nova.virt.disk.mount import loop
from nova.virt.image import model as imgmodel


def _fake_noop(*args, **kwargs):
    return


def _fake_trycmd_losetup_works(*args, **kwargs):
    return '/dev/loop0', ''


def _fake_trycmd_losetup_fails(*args, **kwards):
    return '', 'doh'


class LoopTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LoopTestCase, self).setUp()

        self.file = imgmodel.LocalFileImage("/some/file.qcow2",
                                            imgmodel.FORMAT_QCOW2)

    def test_get_dev(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        l = loop.LoopMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd',
                                             _fake_trycmd_losetup_works))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute',
                                             _fake_noop))

        # No error logged, device consumed
        self.assertTrue(l.get_dev())
        self.assertTrue(l.linked)
        self.assertEqual('', l.error)
        self.assertEqual('/dev/loop0', l.device)

        # Free
        l.unget_dev()
        self.assertFalse(l.linked)
        self.assertEqual('', l.error)
        self.assertIsNone(l.device)

    def test_inner_get_dev_fails(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        l = loop.LoopMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd',
                                             _fake_trycmd_losetup_fails))

        # No error logged, device consumed
        self.assertFalse(l._inner_get_dev())
        self.assertFalse(l.linked)
        self.assertNotEqual('', l.error)
        self.assertIsNone(l.device)

        # Free
        l.unget_dev()
        self.assertFalse(l.linked)
        self.assertIsNone(l.device)

    def test_get_dev_timeout(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        l = loop.LoopMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('time.sleep', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd',
                                             _fake_trycmd_losetup_fails))
        self.useFixture(fixtures.MonkeyPatch(('nova.virt.disk.mount.api.'
                                              'MAX_DEVICE_WAIT'), -10))

        # Always fail to get a device
        def fake_get_dev_fails():
            return False
        l._inner_get_dev = fake_get_dev_fails

        # Fail to get a device
        self.assertFalse(l.get_dev())

    def test_unget_dev(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        l = loop.LoopMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute',
                                             _fake_noop))

        # This just checks that a free of something we don't have doesn't
        # throw an exception
        l.unget_dev()
