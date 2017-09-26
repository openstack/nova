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


import mock
import os
import tempfile
import time

import eventlet
import fixtures
import six

from nova import test
from nova.virt.disk.mount import nbd
from nova.virt.image import model as imgmodel

ORIG_EXISTS = os.path.exists
ORIG_LISTDIR = os.listdir


def _fake_exists_no_users(path):
    if path.startswith('/sys/block/nbd'):
        if path.endswith('pid'):
            return False
        return True
    return ORIG_EXISTS(path)


def _fake_listdir_nbd_devices(path):
    if isinstance(path, six.string_types) and path.startswith('/sys/block'):
        return ['nbd0', 'nbd1']
    return ORIG_LISTDIR(path)


def _fake_exists_all_used(path):
    if path.startswith('/sys/block/nbd'):
        return True
    return ORIG_EXISTS(path)


def _fake_detect_nbd_devices_none(self):
    return []


def _fake_detect_nbd_devices(self):
    return ['nbd0', 'nbd1']


def _fake_noop(*args, **kwargs):
    return


class NbdTestCase(test.NoDBTestCase):
    def setUp(self):
        super(NbdTestCase, self).setUp()
        self.stub_out('nova.virt.disk.mount.nbd.NbdMount._detect_nbd_devices',
                      _fake_detect_nbd_devices)
        self.useFixture(fixtures.MonkeyPatch('os.listdir',
                                             _fake_listdir_nbd_devices))
        self.file = imgmodel.LocalFileImage("/some/file.qcow2",
                                            imgmodel.FORMAT_QCOW2)

    def test_nbd_no_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        self.stub_out('nova.virt.disk.mount.nbd.NbdMount._detect_nbd_devices',
                      _fake_detect_nbd_devices_none)
        n = nbd.NbdMount(self.file, tempdir)
        self.assertIsNone(n._allocate_nbd())

    def test_nbd_no_free_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_all_used))
        self.assertIsNone(n._allocate_nbd())

    def test_nbd_not_loaded(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                return False
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # This should fail, as we don't have the module "loaded"
        # TODO(mikal): work out how to force english as the gettext language
        # so that the error check always passes
        self.assertIsNone(n._allocate_nbd())
        self.assertEqual('nbd unavailable: module not loaded', n.error)

    def test_nbd_allocation(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))

        # Allocate a nbd device
        self.assertEqual('/dev/nbd0', n._allocate_nbd())

    def test_nbd_allocation_one_in_use(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                if path == '/sys/block/nbd0/pid':
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
        self.assertEqual('/dev/nbd1', n._allocate_nbd())

    def test_inner_get_dev_no_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        self.stub_out('nova.virt.disk.mount.nbd.NbdMount._detect_nbd_devices',
                      _fake_detect_nbd_devices_none)
        n = nbd.NbdMount(self.file, tempdir)
        self.assertFalse(n._inner_get_dev())

    @mock.patch('nova.privsep.fs.nbd_connect', return_value=('', 'broken'))
    def test_inner_get_dev_qemu_fails(self, mock_nbd_connect):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # Error logged, no device consumed
        self.assertFalse(n._inner_get_dev())
        self.assertTrue(n.error.startswith('qemu-nbd error'))

    @mock.patch('random.shuffle')
    @mock.patch('os.path.exists', side_effect=[True, False, False, False,
                                               False, False, False, False])
    @mock.patch('os.listdir', return_value=['nbd0', 'nbd1', 'loop0'])
    @mock.patch('nova.privsep.fs.nbd_connect', return_value=('', ''))
    @mock.patch('nova.privsep.fs.nbd_disconnect', return_value=('', ''))
    @mock.patch('time.sleep')
    def test_inner_get_dev_qemu_timeout(self, mock_sleep, mock_nbd_disconnct,
                                        mock_nbd_connect, mock_exists,
                                        mock_listdir, mock_shuffle):
        self.flags(timeout_nbd=3)
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)

        # Error logged, no device consumed
        self.assertFalse(n._inner_get_dev())
        self.assertTrue(n.error.endswith('did not show up'))

    @mock.patch('random.shuffle')
    @mock.patch('os.path.exists', side_effect=[True, False, False, False,
                                               False, True])
    @mock.patch('os.listdir', return_value=['nbd0', 'nbd1', 'loop0'])
    @mock.patch('nova.privsep.fs.nbd_connect', return_value=('', ''))
    @mock.patch('nova.privsep.fs.nbd_disconnect')
    def test_inner_get_dev_works(self, mock_nbd_disconnect, mock_nbd_connect,
                                 mock_exists, mock_listdir, mock_shuffle):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)

        # No error logged, device consumed
        self.assertTrue(n._inner_get_dev())
        self.assertTrue(n.linked)
        self.assertEqual('', n.error)
        self.assertEqual('/dev/nbd0', n.device)

        # Free
        n.unget_dev()
        self.assertFalse(n.linked)
        self.assertEqual('', n.error)
        self.assertIsNone(n.device)

    def test_unget_dev_simple(self):
        # This test is just checking we don't get an exception when we unget
        # something we don't have
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute', _fake_noop))
        n.unget_dev()

    @mock.patch('random.shuffle')
    @mock.patch('os.path.exists', side_effect=[True, False, False, False,
                                               False, True])
    @mock.patch('os.listdir', return_value=['nbd0', 'nbd1', 'loop0'])
    @mock.patch('nova.privsep.fs.nbd_connect', return_value=('', ''))
    @mock.patch('nova.privsep.fs.nbd_disconnect')
    def test_get_dev(self, mock_nbd_disconnect, mock_nbd_connect,
                     mock_exists, mock_listdir, mock_shuffle):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)

        # No error logged, device consumed
        self.assertTrue(n.get_dev())
        self.assertTrue(n.linked)
        self.assertEqual('', n.error)
        self.assertEqual('/dev/nbd0', n.device)

        # Free
        n.unget_dev()
        self.assertFalse(n.linked)
        self.assertEqual('', n.error)
        self.assertIsNone(n.device)

    @mock.patch('random.shuffle')
    @mock.patch('time.sleep')
    @mock.patch('nova.privsep.fs.nbd_connect')
    @mock.patch('nova.privsep.fs.nbd_disconnect')
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.virt.disk.mount.nbd.NbdMount._inner_get_dev',
                return_value=False)
    def test_get_dev_timeout(self, mock_get_dev, mock_exists,
                             mock_nbd_disconnect, mock_nbd_connect,
                             mock_sleep, mock_shuffle):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch(('nova.virt.disk.mount.api.'
                                              'MAX_DEVICE_WAIT'), -10))

        # No error logged, device consumed
        self.assertFalse(n.get_dev())

    @mock.patch('nova.privsep.fs.mount', return_value=('', 'broken'))
    def test_do_mount_need_to_specify_fs_type(self, mock_mount):
        # NOTE(mikal): Bug 1094373 saw a regression where we failed to
        # communicate a failed mount properly.
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        tempdir = self.useFixture(fixtures.TempDir()).path
        mount = nbd.NbdMount(imgfile.name, tempdir)

        def fake_returns_true(*args, **kwargs):
            return True
        mount.get_dev = fake_returns_true
        mount.map_dev = fake_returns_true

        self.assertFalse(mount.do_mount())

    @mock.patch('nova.privsep.fs.nbd_connect')
    @mock.patch('nova.privsep.fs.nbd_disconnect')
    @mock.patch('os.path.exists')
    def test_device_creation_race(self, mock_exists, mock_nbd_disconnect,
                                  mock_nbd_connect):
        # Make sure that even if two threads create instances at the same time
        # they cannot choose the same nbd number (see bug 1207422)

        tempdir = self.useFixture(fixtures.TempDir()).path
        free_devices = _fake_detect_nbd_devices(None)[:]
        chosen_devices = []

        def fake_find_unused(self):
            return os.path.join('/dev', free_devices[-1])

        def delay_and_remove_device(*args, **kwargs):
            # Ensure that context switch happens before the device is marked
            # as used. This will cause a failure without nbd-allocation-lock
            # in place.
            time.sleep(0.1)

            # We always choose the top device in find_unused - remove it now.
            free_devices.pop()

            return '', ''

        def pid_exists(pidfile):
            return pidfile not in [os.path.join('/sys/block', dev, 'pid')
                                   for dev in free_devices]

        self.stub_out('nova.virt.disk.mount.nbd.NbdMount._allocate_nbd',
                      fake_find_unused)
        mock_nbd_connect.side_effect = delay_and_remove_device
        mock_exists.side_effect = pid_exists

        def get_a_device():
            n = nbd.NbdMount(self.file, tempdir)
            n.get_dev()
            chosen_devices.append(n.device)

        thread1 = eventlet.spawn(get_a_device)
        thread2 = eventlet.spawn(get_a_device)
        thread1.wait()
        thread2.wait()

        self.assertEqual(2, len(chosen_devices))
        self.assertNotEqual(chosen_devices[0], chosen_devices[1])
