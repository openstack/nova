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
from testtools.matchers import Equals
from testtools.matchers import MatchesListwise

from nova import test

from nova.openstack.common import cfg
from nova import utils
from nova.virt.disk.mount import nbd

CONF = cfg.CONF
CONF.import_opt('max_nbd_devices', 'nova.virt.disk.mount.nbd')

ORIG_EXISTS = os.path.exists


def _fake_exists_no_users(path):
    if path.startswith('/sys/block/nbd'):
        if path.endswith('pid'):
            return False
        return True
    return ORIG_EXISTS(path)


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
        self.assertThat(nbd.NbdMount._DEVICES,
                        MatchesListwise([Equals('/dev/nbd0'),
                                         Equals('/dev/nbd1')]))

    def test_nbd_no_free_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        nbd.NbdMount._DEVICES = []
        self.assertEquals(None, n._allocate_nbd())

    def test_nbd_not_loaded(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                return False
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # This should fail, as we don't have the module "loaded"
        # TODO(mikal): work out how to force english as the gettext language
        # so that the error check always passes
        self.assertEquals(None, n._allocate_nbd())
        self.assertEquals('nbd unavailable: module not loaded', n.error)

        # And no device should be consumed
        self.assertThat(nbd.NbdMount._DEVICES,
                        MatchesListwise([Equals('/dev/nbd0'),
                                         Equals('/dev/nbd1')]))

    def test_nbd_all_allocated(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        nbd.NbdMount._DEVICES = []
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # Allocate a nbd device, fails
        self.assertEquals(None, n._allocate_nbd())
        self.assertEquals('No free nbd devices', n.error)

    def test_nbd_allocation(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # Allocate a nbd device
        self.assertEquals('/dev/nbd1', n._allocate_nbd())
        self.assertEquals(['/dev/nbd0'], nbd.NbdMount._DEVICES)

        # Allocate another
        self.assertEquals('/dev/nbd0', n._allocate_nbd())
        self.assertEquals([], nbd.NbdMount._DEVICES)

    def test_nbd_allocation_one_in_use(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                if path == '/sys/block/nbd1/pid':
                    return True
                if path.endswith('pid'):
                    return False
                return True
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # Allocate a nbd device, should not be the in use one
        # TODO(mikal): Note that there is a leak here, as the in use nbd device
        # is removed from the list, but not returned so it will never be
        # re-added. I will fix this in a later patch.
        self.assertEquals('/dev/nbd0', n._allocate_nbd())
        self.assertEquals([], nbd.NbdMount._DEVICES)
        self.assertTrue('/dev/nbd0' not in nbd.NbdMount._DEVICES)

    def test_free(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        d = '/dev/nosuch'
        self.assertFalse(d in nbd.NbdMount._DEVICES)

        # Now free it
        n._free_nbd(d)
        self.assertThat(nbd.NbdMount._DEVICES,
                        MatchesListwise([Equals('/dev/nbd0'),
                                         Equals('/dev/nbd1'),
                                         Equals('/dev/nosuch')]))
        self.assertTrue(d in nbd.NbdMount._DEVICES)

        # Double free
        n._free_nbd(d)
        self.assertThat(nbd.NbdMount._DEVICES,
                        MatchesListwise([Equals('/dev/nbd0'),
                                         Equals('/dev/nbd1'),
                                         Equals('/dev/nosuch')]))
        self.assertTrue(d in nbd.NbdMount._DEVICES)

    def test_get_dev_no_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        nbd.NbdMount._DEVICES = []
        self.assertFalse(n.get_dev())

    def test_get_dev_qemu_fails(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # We have a trycmd that always fails
        def fake_trycmd(*args, **kwargs):
            return '', 'broken'
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        # Error logged, no device consumed
        self.assertFalse(n.get_dev())
        self.assertTrue(n.error.startswith('qemu-nbd error'))
        self.assertThat(nbd.NbdMount._DEVICES,
                        MatchesListwise([Equals('/dev/nbd0'),
                                         Equals('/dev/nbd1')]))

    def test_get_dev_qemu_timeout(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # We have a trycmd that always passed
        def fake_trycmd(*args, **kwargs):
            return '', ''
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        # We steal time.sleep() as well to speed up this test
        def fake_sleep(duration):
            return
        self.useFixture(fixtures.MonkeyPatch('time.sleep', fake_sleep))

        # Error logged, no device consumed
        self.assertFalse(n.get_dev())
        self.assertTrue(n.error.endswith('did not show up'))
        self.assertThat(nbd.NbdMount._DEVICES,
                        MatchesListwise([Equals('/dev/nbd0'),
                                         Equals('/dev/nbd1')]))

    def test_get_dev_works(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)

        # We need the pid file for the device which is allocated to exist, but
        # only once it is allocated to us
        def fake_exists_one(path):
            if path.startswith('/sys/block/nbd'):
                if path == '/sys/block/nbd1/pid':
                    return False
                if path.endswith('pid'):
                    return False
                return True
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             fake_exists_one))

        # We have a trycmd that always passed
        def fake_trycmd(*args, **kwargs):
            def fake_exists_two(path):
                if path.startswith('/sys/block/nbd'):
                    if path == '/sys/block/nbd1/pid':
                        return True
                    if path.endswith('pid'):
                        return False
                    return True
                return ORIG_EXISTS(path)
            self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                                 fake_exists_two))
            return '', ''
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        # Ditto execute
        def fake_exec(*args, **kwargs):
            return
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute', fake_exec))

        # No error logged, device consumed
        self.assertTrue(n.get_dev())
        self.assertTrue(n.linked)
        self.assertEquals('', n.error)
        self.assertEquals(['/dev/nbd0'], nbd.NbdMount._DEVICES)
        self.assertEquals('/dev/nbd1', n.device)

        # Free
        n.unget_dev()
        self.assertFalse(n.linked)
        self.assertEquals('', n.error)
        self.assertThat(nbd.NbdMount._DEVICES,
                        MatchesListwise([Equals('/dev/nbd0'),
                                         Equals('/dev/nbd1')]))
        self.assertEquals(None, n.device)

    def test_unget_dev_simple(self):
        # This test is just checking we don't get an exception when we unget
        # something we don't have
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        n.unget_dev()
