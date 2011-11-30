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
"""Support for mounting virtual image files"""

import os

from nova import log as logging
from nova import utils

LOG = logging.getLogger('nova.compute.disk')


class Mount(object):
    """Standard mounting operations, that can be overridden by subclasses.

    The basic device operations provided are get, map and mount,
    to be called in that order.
    """

    def __init__(self, image, mount_dir, partition=None,
                 disable_auto_fsck=False):

        # Input
        self.image = image
        self.partition = partition
        self.disable_auto_fsck = disable_auto_fsck
        self.mount_dir = mount_dir

        # Output
        self.error = ""

        # Internal
        self.linked = self.mapped = self.mounted = False
        self.device = self.mapped_device = None

    def get_dev(self):
        """Make the image available as a block device in the file system."""
        self.device = None
        self.linked = True
        return True

    def unget_dev(self):
        """Release the block device from the file system namespace."""
        self.linked = False

    def map_dev(self):
        """Map partitions of the device to the file system namespace."""
        assert(os.path.exists(self.device))

        if self.partition:
            map_path = '/dev/mapper/%sp%s' % (self.device.split('/')[-1],
                                              self.partition)
            assert(not os.path.exists(map_path))

            # Note kpartx can output warnings to stderr and succeed
            # Also it can output failures to stderr and "succeed"
            # So we just go on the existence of the mapped device
            _out, err = utils.trycmd('kpartx', '-a', self.device,
                                     run_as_root=True, discard_warnings=True)

            # Note kpartx does nothing when presented with a raw image,
            # so given we only use it when we expect a partitioned image, fail
            if not os.path.exists(map_path):
                if not err:
                    err = _('no partitions found')
                self.error = _('Failed to map partitions: %s') % err
            else:
                self.mapped_device = map_path
                self.mapped = True
        else:
            self.mapped_device = self.device
            self.mapped = True

        # This is an orthogonal operation
        # which only needs to be done once
        if self.disable_auto_fsck and self.mapped:
            self.disable_auto_fsck = False
            # attempt to set ext[234] so that it doesn't auto-fsck
            _out, err = utils.trycmd('tune2fs', '-c', 0, '-i', 0,
                                     self.mapped_device, run_as_root=True)
            if err:
                LOG.info(_('Failed to disable fs check: %s') % err)

        return self.mapped

    def unmap_dev(self):
        """Remove partitions of the device from the file system namespace."""
        if not self.mapped:
            return
        if self.partition:
            utils.execute('kpartx', '-d', self.device, run_as_root=True)
        self.mapped = False

    def mnt_dev(self):
        """Mount the device into the file system."""
        _out, err = utils.trycmd('mount', self.mapped_device, self.mount_dir,
                                 run_as_root=True)
        if err:
            self.error = _('Failed to mount filesystem: %s') % err
            return False

        self.mounted = True
        return True

    def unmnt_dev(self):
        """Unmount the device from the file system."""
        if not self.mounted:
            return
        utils.execute('umount', self.mapped_device, run_as_root=True)
        self.mounted = False

    def do_mount(self):
        """Call the get, map and mnt operations."""
        status = False
        try:
            status = self.get_dev() and self.map_dev() and self.mnt_dev()
        finally:
            if not status:
                self.do_umount()
        return status

    def do_umount(self):
        """Call the unmnt, unmap and unget operations."""
        if self.mounted:
            self.unmnt_dev()
        if self.mapped:
            self.unmap_dev()
        if self.linked:
            self.unget_dev()
