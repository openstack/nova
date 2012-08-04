# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Support for mounting images with libguestfs"""

import os

from nova import exception
from nova import utils
from nova.virt.disk import mount


class Mount(mount.Mount):
    """libguestfs support for arbitrary images."""
    mode = 'guestfs'
    device_id_string = 'guest'

    def map_dev(self):
        self.mapped = True
        return True

    def unmap_dev(self):
        self.mapped = False

    def mnt_dev(self):
        try:
            partition = int(self.partition or 0)
        except ValueError:
            self.error = _('unsupported partition: %s') % self.partition
            return False

        args = ('guestmount', '--rw', '-a', self.image)
        if partition == -1:
            args += ('-i',)  # find the OS partition
        elif partition:
            args += ('-m', '/dev/sda%d' % partition)
        else:
            # We don't resort to -i for this case yet,
            # as some older versions of libguestfs
            # have problems identifying ttylinux images for example
            args += ('-m', '/dev/sda')
        args += (self.mount_dir,)
        # root access should not required for guestfs (if the user
        # has permissions to fusermount (by being part of the fuse
        # group for example)).  Also note the image and mount_dir
        # have appropriate creditials at this point for read/write
        # mounting by the nova user.  However currently there are
        # subsequent access issues by both the nova and root users
        # if the nova user mounts the image, as detailed here:
        # https://bugzilla.redhat.com/show_bug.cgi?id=765814
        _out, err = utils.trycmd(*args, discard_warnings=True,
                                 run_as_root=True)
        if err:
            self.error = _('Failed to mount filesystem: %s') % err
            # Be defensive and ensure this is unmounted,
            # as I'm not sure guestmount will never have
            # mounted when it returns EXIT_FAILURE.
            # This is required if discard_warnings=False above
            utils.trycmd('fusermount', '-u', self.mount_dir, run_as_root=True)
            return False

        # More defensiveness as there are edge cases where
        # guestmount can return success while not mounting
        try:
            if not os.listdir(self.mount_dir):
                # Assume we've just got the original empty temp dir
                err = _('unknown guestmount error')
                self.error = _('Failed to mount filesystem: %s') % err
                return False
        except OSError:
            # This is the usual path and means root has
            # probably mounted fine
            pass

        self.mounted = True
        return True

    def unmnt_dev(self):
        if not self.mounted:
            return
        umount_cmd = ['fusermount', '-u', self.mount_dir]
        try:
            # We make a few attempts to work around other
            # processes temporarily scanning the mount_dir etc.
            utils.execute(*umount_cmd, attempts=5, run_as_root=True)
        except exception.ProcessExecutionError:
            # If we still can't umount, then do a lazy umount
            # (in the background), so that mounts might eventually
            # be cleaned up. Note we'll wait 10s below for the umount to
            # complete, after which we'll raise an exception.
            umount_cmd.insert(1, '-z')
            utils.execute(*umount_cmd, run_as_root=True)

        # Unfortunately FUSE has an issue where it doesn't wait
        # for processes associated with the mount to terminate.
        # Therefore we do this manually here.  Note later versions
        # of guestmount have the --pid-file option to help with this.
        # Here we check every .2 seconds whether guestmount is finished
        # but do this for at most 10 seconds.
        wait_cmd = 'until ! ps -C guestmount -o args= | grep -qF "%s"; '
        wait_cmd += 'do sleep .2; done'
        wait_cmd %= self.mount_dir
        utils.execute('timeout', '10s', 'sh', '-c', wait_cmd)

        self.mounted = False
