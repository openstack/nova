# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import os

from nova import test

from nova.openstack.common import cfg
from nova.virt.disk.mount import nbd

CONF = cfg.CONF
CONF.import_opt('max_nbd_devices', 'nova.virt.disk.mount.nbd')


class NbdTestCase(test.TestCase):
    def setUp(self):
        super(NbdTestCase, self).setUp()
        self.flags(max_nbd_devices=2)
        nbd.NbdMount._DEVICES_INITIALIZED = False
        nbd.NbdMount._DEVICES = []

    def test_nbd_initialize(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.assertTrue(n._DEVICES_INITIALIZED)
        self.assertEquals(['/dev/nbd0', '/dev/nbd1'], nbd.NbdMount._DEVICES)

    def test_nbd_not_loaded(self):
        orig_exists = os.path.exists
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                return False
            return orig_exists(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # This should fail, as we don't have the module "loaded"
        # TODO(mikal): work out how to force english as the gettext language
        # so that the error check always passes
        self.assertEquals(None, n._allocate_nbd())
        self.assertEquals('nbd unavailable: module not loaded', n.error)

        # And no device should be consumed
        self.assertEquals(['/dev/nbd0', '/dev/nbd1'], nbd.NbdMount._DEVICES)

    def test_nbd_allocation(self):
        orig_exists = os.path.exists
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                if path.endswith('pid'):
                    return False
                return True
            return orig_exists(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # Allocate a nbd device
        d = n._allocate_nbd()
        self.assertEquals('/dev/nbd1', d)
        self.assertEquals(1, len(nbd.NbdMount._DEVICES))

        # Allocate another
        d = n._allocate_nbd()
        self.assertEquals('/dev/nbd0', d)
        self.assertEquals([], nbd.NbdMount._DEVICES)
