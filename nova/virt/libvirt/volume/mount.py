# Copyright 2016,2017 Red Hat, Inc.
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

import collections
import contextlib
import os.path
import threading

from oslo_concurrency import processutils
from oslo_log import log
from oslo_utils import fileutils
import six

import nova.conf
from nova import exception
import nova.privsep.fs
import nova.privsep.path

CONF = nova.conf.CONF
LOG = log.getLogger(__name__)


class _HostMountStateManager(object):
    """A global manager of filesystem mounts.

    _HostMountStateManager manages a _HostMountState object for the current
    compute node. Primarily it creates one on host_up(), destroys it on
    host_down(), and returns it via get_state().

    _HostMountStateManager manages concurrency itself. Independent callers do
    not need to consider interactions between multiple _HostMountStateManager
    calls when designing their own locking.

    _HostMountStateManager is a singleton, and must only be accessed via:

      mount.get_manager()
    """

    def __init__(self):
        self._reset_state()

    def _reset_state(self):
        """Reset state of global _HostMountStateManager.

        Should only be called by __init__ and tests.
        """

        self.state = None
        self.use_count = 0

        # Guards both state and use_count
        self.cond = threading.Condition()

        # Incremented each time we initialise a new mount state. Aids
        # debugging.
        self.generation = 0

    @contextlib.contextmanager
    def get_state(self):
        """Return the current mount state.

        _HostMountStateManager will not permit a new state object to be
        created while any previous state object is still in use.

        get_state will raise HypervisorUnavailable if the libvirt connection is
        currently down.

        :rtype: _HostMountState
        """

        # We hold the instance lock here so that if a _HostMountState is
        # currently initialising we'll wait for it to complete rather than
        # fail.
        with self.cond:
            state = self.state
            if state is None:
                raise exception.HypervisorUnavailable()
            self.use_count += 1

        try:
            LOG.debug('Got _HostMountState generation %(gen)i',
                      {'gen': state.generation})

            yield state
        finally:
            with self.cond:
                self.use_count -= 1
                self.cond.notify_all()

    def host_up(self, host):
        """Inialise a new _HostMountState when the libvirt connection comes
        up.

        host_up will destroy and re-initialise the current state if one
        already exists, but this is considered an error.

        host_up will block before creating a new state until all operations
        using a previous state have completed.

        :param host: A connected libvirt Host object
        """
        with self.cond:
            if self.state is not None:
                LOG.warning("host_up called, but we think host is already up")
                self._host_down()

            # Wait until all operations using a previous state generation are
            # complete before initialising a new one. Note that self.state is
            # already None, set either by initialisation or by host_down. This
            # means the current state will not be returned to any new callers,
            # and use_count will eventually reach zero.
            # We do this to avoid a race between _HostMountState initialisation
            # and an on-going mount/unmount operation
            while self.use_count != 0:
                self.cond.wait()

            # Another thread might have initialised state while we were
            # wait()ing
            if self.state is None:
                LOG.debug('Initialising _HostMountState generation %(gen)i',
                          {'gen': self.generation})
                self.state = _HostMountState(host, self.generation)
                self.generation += 1

    def host_down(self):
        """Destroy the current _HostMountState when the libvirt connection
        goes down.
        """
        with self.cond:
            if self.state is None:
                LOG.warning("host_down called, but we don't think host is up")
                return

            self._host_down()

    def _host_down(self):
        LOG.debug('Destroying MountManager generation %(gen)i',
                  {'gen': self.state.generation})
        self.state = None


class _HostMountState(object):
    """A data structure recording all managed mountpoints and the
    attachments in use for each one. _HostMountState ensures that the compute
    node only attempts to mount a single mountpoint in use by multiple
    attachments once, and that it is not unmounted until it is no longer in use
    by any attachments.

    Callers should not create a _HostMountState directly, but should obtain
    it via:

      with mount.get_manager().get_state() as state:
        state.mount(...)

    On creation _HostMountState inspects the compute host directly to discover
    all current mountpoints and the attachments on them. After creation it
    expects to have exclusive control of these mountpoints until it is
    destroyed.

    _HostMountState manages concurrency itself. Independent callers do not need
    to consider interactions between multiple _HostMountState calls when
    designing their own locking.
    """

    class _MountPoint(object):
        """A single mountpoint, and the set of attachments in use on it."""
        def __init__(self):
            # A guard for operations on this mountpoint
            # N.B. Care is required using this lock, as it will be deleted
            # if the containing _MountPoint is deleted.
            self.lock = threading.Lock()

            # The set of attachments on this mountpoint.
            self.attachments = set()

        def add_attachment(self, vol_name, instance_uuid):
            self.attachments.add((vol_name, instance_uuid))

        def remove_attachment(self, vol_name, instance_uuid):
            self.attachments.remove((vol_name, instance_uuid))

        def in_use(self):
            return len(self.attachments) > 0

    def __init__(self, host, generation):
        """Initialise a _HostMountState by inspecting the current compute
        host for mountpoints and the attachments in use on them.

        :param host: A connected libvirt Host object
        :param generation: An integer indicating the generation of this
                           _HostMountState object. This is 0 for the first
                           _HostMountState created, and incremented for each
                           created subsequently. It is used in log messages to
                           aid debugging.
        """
        self.generation = generation
        self.mountpoints = collections.defaultdict(self._MountPoint)

        # Iterate over all guests on the connected libvirt
        for guest in host.list_guests(only_running=False):
            for disk in guest.get_all_disks():

                # All remote filesystem volumes are files
                if disk.source_type != 'file':
                    continue

                # NOTE(mdbooth): We're assuming that the mountpoint is our
                # immediate parent, which is currently true for all
                # volume drivers. We deliberately don't do anything clever
                # here, because we don't want to, e.g.:
                # * Add mountpoints for non-volume disks
                # * Get it wrong when a non-running domain references a
                #   volume which isn't mounted because the host just rebooted.
                # and this is good enough. We could probably do better here
                # with more thought.

                mountpoint = os.path.dirname(disk.source_path)
                if not os.path.ismount(mountpoint):
                    continue

                name = os.path.basename(disk.source_path)
                mount = self.mountpoints[mountpoint]
                mount.add_attachment(name, guest.uuid)

                LOG.debug('Discovered volume %(vol)s in use for existing '
                          'mountpoint %(mountpoint)s',
                          {'vol': name, 'mountpoint': mountpoint})

    @contextlib.contextmanager
    def _get_locked(self, mountpoint):
        """Get a locked mountpoint object

        :param mountpoint: The path of the mountpoint whose object we should
                           return.
        :rtype: _HostMountState._MountPoint
        """
        # This dance is because we delete locks. We need to be sure that the
        # lock we hold does not belong to an object which has been deleted.
        # We do this by checking that mountpoint still refers to this object
        # when we hold the lock. This is safe because:
        # * we only delete an object from mountpounts whilst holding its lock
        # * mountpoints is a defaultdict which will atomically create a new
        #   object on access
        while True:
            mount = self.mountpoints[mountpoint]
            with mount.lock:
                if self.mountpoints[mountpoint] is mount:
                    yield mount
                    break

    def mount(self, fstype, export, vol_name, mountpoint, instance, options):
        """Ensure a mountpoint is available for an attachment, mounting it
        if necessary.

        If this is the first attachment on this mountpoint, we will mount it
        with:

          mount -t <fstype> <options> <export> <mountpoint>

        :param fstype: The filesystem type to be passed to mount command.
        :param export: The type-specific identifier of the filesystem to be
                       mounted. e.g. for nfs 'host.example.com:/mountpoint'.
        :param vol_name: The name of the volume on the remote filesystem.
        :param mountpoint: The directory where the filesystem will be
                           mounted on the local compute host.
        :param instance: The instance the volume will be attached to.
        :param options: An arbitrary list of additional arguments to be
                        passed to the mount command immediate before export
                        and mountpoint.
        """

        # NOTE(mdbooth): mount() may currently be called multiple times for a
        # single attachment. Any operation which calls
        # LibvirtDriver._hard_reboot will re-attach volumes which are probably
        # already attached, resulting in multiple mount calls.

        LOG.debug('_HostMountState.mount(fstype=%(fstype)s, '
                  'export=%(export)s, vol_name=%(vol_name)s, %(mountpoint)s, '
                  'options=%(options)s) generation %(gen)s',
                  {'fstype': fstype, 'export': export, 'vol_name': vol_name,
                   'mountpoint': mountpoint, 'options': options,
                   'gen': self.generation})
        with self._get_locked(mountpoint) as mount:
            if os.path.ismount(mountpoint):
                LOG.debug(('Mounting %(mountpoint)s generation %(gen)s, '
                           'mountpoint already mounted'),
                          {'mountpoint': mountpoint, 'gen': self.generation})
            else:
                LOG.debug('Mounting %(mountpoint)s generation %(gen)s',
                          {'mountpoint': mountpoint, 'gen': self.generation})

                fileutils.ensure_tree(mountpoint)

                try:
                    nova.privsep.fs.mount(fstype, export, mountpoint, options)
                except processutils.ProcessExecutionError():
                    # Check to see if mountpoint is mounted despite the error
                    # eg it was already mounted
                    if os.path.ismount(mountpoint):
                        # We're not going to raise the exception because we're
                        # in the desired state anyway. However, this is still
                        # unusual so we'll log it.
                        LOG.exception(
                            'Error mounting %(fstypes export %(export)s on '
                            '%(mountpoint)s. Continuing because mountpount is '
                            'mounted despite this.',
                            {'fstype': fstype, 'export': export,
                             'mountpoint': mountpoint})
                    else:
                        # If the mount failed there's no reason for us to keep
                        # a record of it. It will be created again if the
                        # caller retries.

                        # Delete while holding lock
                        del self.mountpoints[mountpoint]

                        raise

            mount.add_attachment(vol_name, instance.uuid)

        LOG.debug('_HostMountState.mount() for %(mountpoint)s '
                  'generation %(gen)s completed successfully',
                  {'mountpoint': mountpoint, 'gen': self.generation})

    def umount(self, vol_name, mountpoint, instance):
        """Mark an attachment as no longer in use, and unmount its mountpoint
        if necessary.

        :param vol_name: The name of the volume on the remote filesystem.
        :param mountpoint: The directory where the filesystem is be
                           mounted on the local compute host.
        :param instance: The instance the volume was attached to.
        """
        LOG.debug('_HostMountState.umount(vol_name=%(vol_name)s, '
                  'mountpoint=%(mountpoint)s) generation %(gen)s',
                  {'vol_name': vol_name, 'mountpoint': mountpoint,
                   'gen': self.generation})
        with self._get_locked(mountpoint) as mount:
            try:
                mount.remove_attachment(vol_name, instance.uuid)
            except KeyError:
                LOG.warning("Request to remove attachment "
                            "(%(vol_name)s, %(instance)s) from "
                            "%(mountpoint)s, but we don't think it's in use.",
                            {'vol_name': vol_name, 'instance': instance.uuid,
                             'mountpoint': mountpoint})

            if not mount.in_use():
                mounted = os.path.ismount(mountpoint)

                if mounted:
                    mounted = self._real_umount(mountpoint)

                # Delete our record entirely if it's unmounted
                if not mounted:
                    del self.mountpoints[mountpoint]

            LOG.debug('_HostMountState.umount() for %(mountpoint)s '
                      'generation %(gen)s completed successfully',
                      {'mountpoint': mountpoint, 'gen': self.generation})

    def _real_umount(self, mountpoint):
        # Unmount and delete a mountpoint.
        # Return mount state after umount (i.e. True means still mounted)
        LOG.debug('Unmounting %(mountpoint)s generation %(gen)s',
                  {'mountpoint': mountpoint, 'gen': self.generation})

        try:
            nova.privsep.fs.umount(mountpoint)
        except processutils.ProcessExecutionError as ex:
            LOG.error("Couldn't unmount %(mountpoint)s: %(reason)s",
                      {'mountpoint': mountpoint, 'reason': six.text_type(ex)})

        if not os.path.ismount(mountpoint):
            nova.privsep.path.rmdir(mountpoint)
            return False

        return True


__manager__ = _HostMountStateManager()


def get_manager():
    """Return the _HostMountStateManager singleton.

    :rtype: _HostMountStateManager
    """
    return __manager__


def mount(fstype, export, vol_name, mountpoint, instance, options=None):
    """A convenience wrapper around _HostMountState.mount(), called via the
    _HostMountStateManager singleton.
    """
    with __manager__.get_state() as mount_state:
        mount_state.mount(fstype, export, vol_name, mountpoint, instance,
                          options)


def umount(vol_name, mountpoint, instance):
    """A convenience wrapper around _HostMountState.umount(), called via the
    _HostMountStateManager singleton.
    """
    with __manager__.get_state() as mount_state:
        mount_state.umount(vol_name, mountpoint, instance)
