# coding=utf-8

# Copyright 2012,2014 Hewlett-Packard Development Company, L.P.
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

"""Tests for baremetal utils."""

import errno
import os
import tempfile

from nova import test
from nova.virt.baremetal import utils
from nova.virt.libvirt import utils as libvirt_utils


class BareMetalUtilsTestCase(test.NoDBTestCase):

    def test_random_alnum(self):
        s = utils.random_alnum(10)
        self.assertEqual(len(s), 10)
        s = utils.random_alnum(100)
        self.assertEqual(len(s), 100)

    def test_unlink(self):
        self.mox.StubOutWithMock(os, "unlink")
        os.unlink("/fake/path")

        self.mox.ReplayAll()
        utils.unlink_without_raise("/fake/path")
        self.mox.VerifyAll()

    def test_unlink_ENOENT(self):
        self.mox.StubOutWithMock(os, "unlink")
        os.unlink("/fake/path").AndRaise(OSError(errno.ENOENT))

        self.mox.ReplayAll()
        utils.unlink_without_raise("/fake/path")
        self.mox.VerifyAll()

    def test_create_link(self):
        self.mox.StubOutWithMock(os, "symlink")
        os.symlink("/fake/source", "/fake/link")

        self.mox.ReplayAll()
        utils.create_link_without_raise("/fake/source", "/fake/link")
        self.mox.VerifyAll()

    def test_create_link_EEXIST(self):
        self.mox.StubOutWithMock(os, "symlink")
        os.symlink("/fake/source", "/fake/link").AndRaise(
                OSError(errno.EEXIST))

        self.mox.ReplayAll()
        utils.create_link_without_raise("/fake/source", "/fake/link")
        self.mox.VerifyAll()

    def test_cache_image_with_clean(self):
        self.mox.StubOutWithMock(libvirt_utils, "fetch_image")
        temp_f, temp_file = tempfile.mkstemp()
        libvirt_utils.fetch_image(None, temp_file, None, None, None)
        self.mox.ReplayAll()
        utils.cache_image(None, temp_file, None, None, None, clean=True)
        self.mox.VerifyAll()
        self.assertFalse(os.path.exists(temp_file))
