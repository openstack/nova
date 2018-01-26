#    Copyright 2017 Red Hat, Inc.
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

import os.path
import threading
import time

import eventlet
import fixtures
import mock

from oslo_concurrency import processutils

from nova import exception
from nova import test
from nova.tests import uuidsentinel as uuids
from nova.virt.libvirt import config as libvirt_config
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host as libvirt_host
from nova.virt.libvirt.volume import mount


# We wait on events in a few cases. In normal execution the wait period should
# be in the order of fractions of a millisecond. However, if we've hit a bug we
# might deadlock and never return. To be nice to our test environment, we cut
# this short at MAX_WAIT seconds. This should be large enough that normal
# jitter won't trigger it, but not so long that it's annoying to wait for.
MAX_WAIT = 2


class ThreadController(object):
    """Helper class for executing a test thread incrementally by waiting at
    named waitpoints.

      def test(ctl):
        things()
        ctl.waitpoint('foo')
        more_things()
        ctl.waitpoint('bar')
        final_things()

      ctl = ThreadController(test)
      ctl.runto('foo')
      assert(things)
      ctl.runto('bar')
      assert(more_things)
      ctl.finish()
      assert(final_things)

    This gets more interesting when the waitpoints are mocked into non-test
    code.
    """

    # A map of threads to controllers
    all_threads = {}

    def __init__(self, fn):
        """Create a ThreadController.

        :param fn: A test function which takes a ThreadController as its
                   only argument
        """

        # All updates to wait_at and waiting are guarded by wait_lock
        self.wait_lock = threading.Condition()
        # The name of the next wait point
        self.wait_at = None
        # True when waiting at a waitpoint
        self.waiting = False
        # Incremented every time we continue from a waitpoint
        self.epoch = 1
        # The last epoch we waited at
        self.last_epoch = 0

        self.start_event = eventlet.event.Event()
        self.running = False
        self.complete = False

        # We must not execute fn() until the thread has been registered in
        # all_threads. eventlet doesn't give us an API to do this directly,
        # so we defer with an Event
        def deferred_start():
            self.start_event.wait()
            fn()

            with self.wait_lock:
                self.complete = True
                self.wait_lock.notify_all()

        self.thread = eventlet.greenthread.spawn(deferred_start)
        self.all_threads[self.thread] = self

    @classmethod
    def current(cls):
        return cls.all_threads.get(eventlet.greenthread.getcurrent())

    def _ensure_running(self):
        if not self.running:
            self.running = True
            self.start_event.send()

    def waitpoint(self, name):
        """Called by the test thread. Wait at a waitpoint called name"""
        with self.wait_lock:
            wait_since = time.time()
            while name == self.wait_at:
                self.waiting = True
                self.wait_lock.notify_all()
                self.wait_lock.wait(1)
                assert(time.time() - wait_since < MAX_WAIT)

            self.epoch += 1
            self.waiting = False
            self.wait_lock.notify_all()

    def runto(self, name):
        """Called by the control thread. Cause the test thread to run until
        reaching a waitpoint called name. When runto() exits, the test
        thread is guaranteed to have reached this waitpoint.
        """
        with self.wait_lock:
            # Set a new wait point
            self.wait_at = name
            self.wait_lock.notify_all()

            # We deliberately don't do this first to avoid a race the first
            # time we call runto()
            self._ensure_running()

            # Wait until the test thread is at the wait point
            wait_since = time.time()
            while self.epoch == self.last_epoch or not self.waiting:
                self.wait_lock.wait(1)
                assert(time.time() - wait_since < MAX_WAIT)

            self.last_epoch = self.epoch

    def start(self):
        """Called by the control thread. Cause the test thread to start
        running, but to not wait for it to complete.
        """
        self._ensure_running()

    def finish(self):
        """Called by the control thread. Cause the test thread to run to
        completion. When finish() exits, the test thread is guaranteed to
        have completed.
        """
        self._ensure_running()

        wait_since = time.time()
        with self.wait_lock:
            self.wait_at = None
            self.wait_lock.notify_all()
            while not self.complete:
                self.wait_lock.wait(1)
                assert(time.time() - wait_since < MAX_WAIT)

        self.thread.wait()


class HostMountStateTestCase(test.NoDBTestCase):
    def setUp(self):
        super(HostMountStateTestCase, self).setUp()

    @mock.patch('os.path.ismount',
                side_effect=[False, True, True, True, True])
    def test_init(self, mock_ismount):
        # Test that we initialise the state of MountManager correctly at
        # startup
        def fake_disk(disk):
            libvirt_disk = libvirt_config.LibvirtConfigGuestDisk()
            libvirt_disk.source_type = disk[0]
            libvirt_disk.source_path = os.path.join(*disk[1])
            return libvirt_disk

        def mock_guest(uuid, disks):
            guest = mock.create_autospec(libvirt_guest.Guest)
            guest.uuid = uuid
            guest.get_all_disks.return_value = map(fake_disk, disks)
            return guest

        local_dir = '/local'
        mountpoint_a = '/mnt/a'
        mountpoint_b = '/mnt/b'

        guests = map(mock_guest, [uuids.instance_a, uuids.instance_b], [
            # Local file root disk and a volume on each of mountpoints a and b
            [
                ('file', (local_dir, uuids.instance_a, 'disk')),
                ('file', (mountpoint_a, 'vola1')),
                ('file', (mountpoint_b, 'volb1')),
            ],

            # Local LVM root disk and a volume on each of mountpoints a and b
            [
                ('block', ('/dev', 'vg', uuids.instance_b + '_disk')),
                ('file', (mountpoint_a, 'vola2')),
                ('file', (mountpoint_b, 'volb2')),
            ]
        ])

        host = mock.create_autospec(libvirt_host.Host)
        host.list_guests.return_value = guests

        m = mount._HostMountState(host, 0)

        self.assertEqual([mountpoint_a, mountpoint_b],
                         sorted(m.mountpoints.keys()))

        self.assertSetEqual(set([('vola1', uuids.instance_a),
                                 ('vola2', uuids.instance_b)]),
                            m.mountpoints[mountpoint_a].attachments)
        self.assertSetEqual(set([('volb1', uuids.instance_a),
                                 ('volb2', uuids.instance_b)]),
                            m.mountpoints[mountpoint_b].attachments)

    @staticmethod
    def _get_clean_hostmountstate():
        # list_guests returns no guests: _HostMountState initial state is
        # clean.
        host = mock.create_autospec(libvirt_host.Host)
        host.list_guests.return_value = []
        return mount._HostMountState(host, 0)

    def _sentinel_mount(self, m, vol, mountpoint=mock.sentinel.mountpoint,
                        instance=None):
        if instance is None:
            instance = mock.sentinel.instance
            instance.uuid = uuids.instance

        m.mount(mock.sentinel.fstype, mock.sentinel.export,
                vol, mountpoint, instance,
                [mock.sentinel.option1, mock.sentinel.option2])

    def _sentinel_umount(self, m, vol, mountpoint=mock.sentinel.mountpoint,
                         instance=mock.sentinel.instance):
        m.umount(vol, mountpoint, instance)

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('nova.privsep.fs.umount')
    @mock.patch('os.path.ismount',
                side_effect=[False, True, True, True])
    def test_mount_umount(self, mock_ismount, mock_umount, mock_mount,
                          mock_ensure_tree):
        # Mount 2 different volumes from the same export. Test that we only
        # mount and umount once.
        m = self._get_clean_hostmountstate()

        # Mount vol_a from export
        self._sentinel_mount(m, mock.sentinel.vol_a)
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype,
                      mock.sentinel.export, mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])

        # Mount vol_b from export. We shouldn't have mounted again
        self._sentinel_mount(m, mock.sentinel.vol_b)
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype,
                      mock.sentinel.export, mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])

        # Unmount vol_a. We shouldn't have unmounted
        self._sentinel_umount(m, mock.sentinel.vol_a)
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype,
                      mock.sentinel.export, mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])

        # Unmount vol_b. We should have umounted.
        self._sentinel_umount(m, mock.sentinel.vol_b)
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype,
                      mock.sentinel.export, mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_umount.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('nova.privsep.fs.umount')
    @mock.patch('os.path.ismount',
                side_effect=[False, True, True, True])
    @mock.patch('nova.privsep.path.rmdir')
    def test_mount_umount_multi_attach(self, mock_rmdir, mock_ismount,
                                       mock_umount, mock_mount,
                                       mock_ensure_tree):
        # Mount a volume from a single export for 2 different instances. Test
        # that we only mount and umount once.
        m = self._get_clean_hostmountstate()

        instance_a = mock.sentinel.instance_a
        instance_a.uuid = uuids.instance_a
        instance_b = mock.sentinel.instance_b
        instance_b.uuid = uuids.instance_b

        # Mount vol_a for instance_a
        self._sentinel_mount(m, mock.sentinel.vol_a, instance=instance_a)
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_mount.reset_mock()

        # Mount vol_a for instance_b. We shouldn't have mounted again
        self._sentinel_mount(m, mock.sentinel.vol_a, instance=instance_b)
        mock_mount.assert_not_called()

        # Unmount vol_a for instance_a. We shouldn't have unmounted
        self._sentinel_umount(m, mock.sentinel.vol_a, instance=instance_a)
        mock_umount.assert_not_called()

        # Unmount vol_a for instance_b. We should have umounted.
        self._sentinel_umount(m, mock.sentinel.vol_a, instance=instance_b)
        mock_umount.assert_has_calls([mock.call(mock.sentinel.mountpoint)])

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('nova.privsep.fs.umount')
    @mock.patch('os.path.ismount',
                side_effect=[False, False, True, False, False, True])
    @mock.patch('nova.privsep.path.rmdir')
    def test_mount_concurrent(self, mock_rmdir, mock_ismount, mock_umount,
                              mock_mount, mock_ensure_tree):
        # This is 2 tests in 1, because the first test is the precondition
        # for the second.

        # The first test is that if 2 threads call mount simultaneously,
        # only one of them will call mount

        # The second test is that we correctly handle the case where we
        # delete a lock after umount. During the umount of the first test,
        # which will delete the lock when it completes, we start 2 more
        # threads which both call mount. These threads are holding a lock
        # which is about to be deleted. We test that they still don't race,
        # and only one of them calls mount.
        m = self._get_clean_hostmountstate()

        def mount_a():
            # Mount vol_a from export
            self._sentinel_mount(m, mock.sentinel.vol_a)
            ThreadController.current().waitpoint('mounted')
            self._sentinel_umount(m, mock.sentinel.vol_a)

        def mount_b():
            # Mount vol_b from export
            self._sentinel_mount(m, mock.sentinel.vol_b)
            self._sentinel_umount(m, mock.sentinel.vol_b)

        def mount_c():
            self._sentinel_mount(m, mock.sentinel.vol_c)

        def mount_d():
            self._sentinel_mount(m, mock.sentinel.vol_d)

        ctl_a = ThreadController(mount_a)
        ctl_b = ThreadController(mount_b)
        ctl_c = ThreadController(mount_c)
        ctl_d = ThreadController(mount_d)

        def trap_mount(*args, **kwargs):
            # Conditionally wait at a waitpoint named after the command
            # we're executing
            ThreadController.current().waitpoint('mount')

        def trap_umount(*args, **kwargs):
            # Conditionally wait at a waitpoint named after the command
            # we're executing
            ThreadController.current().waitpoint('umount')

        mock_mount.side_effect = trap_mount
        mock_umount.side_effect = trap_umount

        # Run the first thread until it's blocked while calling mount
        ctl_a.runto('mount')
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])

        # Start the second mount, and ensure it's got plenty of opportunity
        # to race.
        ctl_b.start()
        time.sleep(0.01)
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_umount.assert_not_called()

        # Allow ctl_a to complete its mount
        ctl_a.runto('mounted')
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_umount.assert_not_called()

        # Allow ctl_b to finish. We should not have done a umount
        ctl_b.finish()
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_umount.assert_not_called()

        # Allow ctl_a to start umounting. We haven't executed rmdir yet,
        # because we've blocked during umount
        ctl_a.runto('umount')
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_umount.assert_has_calls([mock.call(mock.sentinel.mountpoint)])
        mock_rmdir.assert_not_called()

        # While ctl_a is umounting, simultaneously start both ctl_c and
        # ctl_d, and ensure they have an opportunity to race
        ctl_c.start()
        ctl_d.start()
        time.sleep(0.01)

        # Allow a, c, and d to complete
        for ctl in (ctl_a, ctl_c, ctl_d):
            ctl.finish()

        # We should have completed the previous umount, then remounted
        # exactly once
        mock_ensure_tree.assert_has_calls([
            mock.call(mock.sentinel.mountpoint)])
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2]),
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_umount.assert_has_calls([mock.call(mock.sentinel.mountpoint)])

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('nova.privsep.fs.umount')
    @mock.patch('os.path.ismount',
                side_effect=[False, False, True, True, True, False])
    @mock.patch('nova.privsep.path.rmdir')
    def test_mount_concurrent_no_interfere(self, mock_rmdir, mock_ismount,
                                           mock_umount, mock_mount,
                                           mock_ensure_tree):
        # Test that concurrent calls to mount volumes in different exports
        # run concurrently
        m = self._get_clean_hostmountstate()

        def mount_a():
            # Mount vol on mountpoint a
            self._sentinel_mount(m, mock.sentinel.vol,
                                 mock.sentinel.mountpoint_a)
            ThreadController.current().waitpoint('mounted')
            self._sentinel_umount(m, mock.sentinel.vol,
                                  mock.sentinel.mountpoint_a)

        def mount_b():
            # Mount vol on mountpoint b
            self._sentinel_mount(m, mock.sentinel.vol,
                                 mock.sentinel.mountpoint_b)
            self._sentinel_umount(m, mock.sentinel.vol,
                                  mock.sentinel.mountpoint_b)

        ctl_a = ThreadController(mount_a)
        ctl_b = ThreadController(mount_b)

        ctl_a.runto('mounted')
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint_a,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_mount.reset_mock()

        ctl_b.finish()
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint_b,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_umount.assert_has_calls([mock.call(mock.sentinel.mountpoint_b)])
        mock_umount.reset_mock()

        ctl_a.finish()
        mock_umount.assert_has_calls([mock.call(mock.sentinel.mountpoint_a)])

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('nova.privsep.fs.umount',
                side_effect=processutils.ProcessExecutionError())
    @mock.patch('os.path.ismount',
                side_effect=[False, True, True, True, False])
    @mock.patch('nova.privsep.path.rmdir')
    def test_mount_after_failed_umount(self, mock_rmdir, mock_ismount,
                                       mock_umount, mock_mount,
                                       mock_ensure_tree):
        # Test that MountManager correctly tracks state when umount fails.
        # Test that when umount fails a subsequent mount doesn't try to
        # remount it.

        m = self._get_clean_hostmountstate()

        # Mount vol_a
        self._sentinel_mount(m, mock.sentinel.vol_a)
        mock_mount.assert_has_calls([
            mock.call(mock.sentinel.fstype, mock.sentinel.export,
                      mock.sentinel.mountpoint,
                      [mock.sentinel.option1, mock.sentinel.option2])])
        mock_mount.reset_mock()

        # Umount vol_a. The umount command will fail.
        self._sentinel_umount(m, mock.sentinel.vol_a)
        mock_umount.assert_has_calls([mock.call(mock.sentinel.mountpoint)])

        # We should not have called rmdir, because umount failed
        mock_rmdir.assert_not_called()

        # Mount vol_a again. We should not have called mount, because umount
        # failed.
        self._sentinel_mount(m, mock.sentinel.vol_a)
        mock_mount.assert_not_called()

        # Prevent future failure of umount
        mock_umount.side_effect = None

        # Umount vol_a successfully
        self._sentinel_umount(m, mock.sentinel.vol_a)
        mock_umount.assert_has_calls([mock.call(mock.sentinel.mountpoint)])

    @mock.patch.object(mount.LOG, 'error')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.privsep.fs.mount')
    @mock.patch('os.path.ismount')
    @mock.patch('nova.privsep.fs.umount')
    def test_umount_log_failure(self, mock_umount, mock_ismount, mock_mount,
                                mock_ensure_tree, mock_LOG_error):
        mock_umount.side_effect = mount.processutils.ProcessExecutionError(
            None, None, None, 'umount', 'umount: device is busy.')
        mock_ismount.side_effect = [False, True, True]

        m = self._get_clean_hostmountstate()

        self._sentinel_mount(m, mock.sentinel.vol_a)
        self._sentinel_umount(m, mock.sentinel.vol_a)

        mock_LOG_error.assert_called()


class MountManagerTestCase(test.NoDBTestCase):
    class FakeHostMountState(object):
        def __init__(self, host, generation):
            self.host = host
            self.generation = generation

            ctl = ThreadController.current()
            if ctl is not None:
                ctl.waitpoint('init')

    def setUp(self):
        super(MountManagerTestCase, self).setUp()

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.volume.mount._HostMountState',
            self.FakeHostMountState))

        self.m = mount.get_manager()
        self.m._reset_state()

    def _get_state(self):
        with self.m.get_state() as state:
            return state

    def test_host_up_down(self):
        self.m.host_up(mock.sentinel.host)
        state = self._get_state()
        self.assertEqual(state.host, mock.sentinel.host)
        self.assertEqual(state.generation, 0)

        self.m.host_down()
        self.assertRaises(exception.HypervisorUnavailable, self._get_state)

    def test_host_up_waits_for_completion(self):
        self.m.host_up(mock.sentinel.host)

        def txn():
            with self.m.get_state():
                ThreadController.current().waitpoint('running')

        # Start a thread which blocks holding a state object
        ctl = ThreadController(txn)
        ctl.runto('running')

        # Host goes down
        self.m.host_down()

        # Call host_up in a separate thread because it will block, and give
        # it plenty of time to race
        host_up = eventlet.greenthread.spawn(self.m.host_up,
                                             mock.sentinel.host)
        time.sleep(0.01)

        # Assert that we haven't instantiated a new state while there's an
        # ongoing operation from the previous state
        self.assertRaises(exception.HypervisorUnavailable, self._get_state)

        # Allow the previous ongoing operation and host_up to complete
        ctl.finish()
        host_up.wait()

        # Assert that we've got a new state generation
        state = self._get_state()
        self.assertEqual(1, state.generation)
