# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
#
# Copyright 2011, Piston Cloud Computing, Inc.
#
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
"""
Utility methods to resize, repartition, and modify disk images.

Includes injection of SSH PGP keys into authorized_keys file.

"""

import json
import os
import tempfile

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.virt.disk import guestfs
from nova.virt.disk import loop
from nova.virt.disk import nbd

LOG = logging.getLogger('nova.compute.disk')
FLAGS = flags.FLAGS
flags.DEFINE_integer('minimum_root_size', 1024 * 1024 * 1024 * 10,
                     'minimum size in bytes of root partition')
flags.DEFINE_string('injected_network_template',
                    utils.abspath('virt/interfaces.template'),
                    'Template file for injected network')
flags.DEFINE_list('img_handlers', ['loop', 'nbd', 'guestfs'],
                    'Order of methods used to mount disk images')


# NOTE(yamahata): DEFINE_list() doesn't work because the command may
#                 include ','. For example,
#                 mkfs.ext3 -O dir_index,extent -E stride=8,stripe-width=16
#                 --label %(fs_label)s %(target)s
#
#                 DEFINE_list() parses its argument by
#                 [s.strip() for s in argument.split(self._token)]
#                 where self._token = ','
#                 No escape nor exceptional handling for ','.
#                 DEFINE_list() doesn't give us what we need.
flags.DEFINE_multistring('virt_mkfs',
                         ['windows=mkfs.ntfs --fast --label %(fs_label)s '
                          '%(target)s',
                          # NOTE(yamahata): vfat case
                          #'windows=mkfs.vfat -n %(fs_label)s %(target)s',
                          'linux=mkfs.ext3 -L %(fs_label)s -F %(target)s',
                          'default=mkfs.ext3 -L %(fs_label)s -F %(target)s'],
                         'mkfs commands for ephemeral device. The format is'
                         '<os_type>=<mkfs command>')


_MKFS_COMMAND = {}
_DEFAULT_MKFS_COMMAND = None


for s in FLAGS.virt_mkfs:
    # NOTE(yamahata): mkfs command may includes '=' for its options.
    #                 So item.partition('=') doesn't work here
    os_type, mkfs_command = s.split('=', 1)
    if os_type:
        _MKFS_COMMAND[os_type] = mkfs_command
    if os_type == 'default':
        _DEFAULT_MKFS_COMMAND = mkfs_command


def mkfs(os_type, fs_label, target):
    mkfs_command = (_MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND) or
                    '') % locals()
    if mkfs_command:
        utils.execute(*mkfs_command.split())


def extend(image, size):
    """Increase image to size"""
    file_size = os.path.getsize(image)
    if file_size >= size:
        return
    utils.execute('qemu-img', 'resize', image, size)
    # NOTE(vish): attempts to resize filesystem
    utils.execute('e2fsck', '-fp', image, check_exit_code=False)
    utils.execute('resize2fs', image, check_exit_code=False)


class _DiskImage(object):
    """Provide operations on a disk image file."""

    def __init__(self, image, partition=None, use_cow=False,
                 disable_auto_fsck=False, mount_dir=None):
        # These passed to each mounter
        self.image = image
        self.partition = partition
        self.disable_auto_fsck = disable_auto_fsck
        self.mount_dir = mount_dir

        # Internal
        self._mkdir = False
        self._mounter = None
        self._errors = []

        # As a performance tweak, don't bother trying to
        # directly loopback mount a cow image.
        self.handlers = FLAGS.img_handlers[:]
        if use_cow and 'loop' in self.handlers:
            self.handlers.remove('loop')

        if not self.handlers:
            raise exception.Error(_('no capable image handler configured'))

    @property
    def errors(self):
        """Return the collated errors from all operations."""
        return '\n--\n'.join([''] + self._errors)

    @staticmethod
    def _handler_class(mode):
        """Look up the appropriate class to use based on MODE."""
        for cls in (loop.Mount, nbd.Mount, guestfs.Mount):
            if cls.mode == mode:
                return cls
        raise exception.Error(_("unknown disk image handler: %s" % mode))

    def mount(self):
        """Mount a disk image, using the object attributes.

        The first supported means provided by the mount classes is used.

        True, or False is returned and the 'errors' attribute
        contains any diagnostics.
        """
        if self._mounter:
            raise exception.Error(_('image already mounted'))

        if not self.mount_dir:
            self.mount_dir = tempfile.mkdtemp()
            self._mkdir = True

        try:
            for h in self.handlers:
                mounter_cls = self._handler_class(h)
                mounter = mounter_cls(image=self.image,
                                      partition=self.partition,
                                      disable_auto_fsck=self.disable_auto_fsck,
                                      mount_dir=self.mount_dir)
                if mounter.do_mount():
                    self._mounter = mounter
                    break
                else:
                    LOG.debug(mounter.error)
                    self._errors.append(mounter.error)
        finally:
            if not self._mounter:
                self.umount()  # rmdir

        return bool(self._mounter)

    def umount(self):
        """Unmount a disk image from the file system."""
        try:
            if self._mounter:
                self._mounter.do_umount()
        finally:
            if self._mkdir:
                os.rmdir(self.mount_dir)


# Public module functions

def inject_data(image, key=None, net=None, metadata=None,
                partition=None, use_cow=False, disable_auto_fsck=True):
    """Injects a ssh key and optionally net data into a disk image.

    it will mount the image as a fully partitioned disk and attempt to inject
    into the specified partition number.

    If partition is not specified it mounts the image as a single partition.

    """
    img = _DiskImage(image=image, partition=partition, use_cow=use_cow,
                     disable_auto_fsck=disable_auto_fsck)
    if img.mount():
        try:
            inject_data_into_fs(img.mount_dir, key, net, metadata,
                                utils.execute)
        finally:
            img.umount()
    else:
        raise exception.Error(img.errors)


def setup_container(image, container_dir=None, use_cow=False):
    """Setup the LXC container.

    It will mount the loopback image to the container directory in order
    to create the root filesystem for the container.

    LXC does not support qcow2 images yet.
    """
    try:
        img = _DiskImage(image=image, use_cow=use_cow, mount_dir=container_dir)
        if img.mount():
            return img
        else:
            raise exception.Error(img.errors)
    except Exception, exn:
        LOG.exception(_('Failed to mount filesystem: %s'), exn)


def destroy_container(img):
    """Destroy the container once it terminates.

    It will umount the container that is mounted,
    and delete any  linked devices.

    LXC does not support qcow2 images yet.
    """
    try:
        if img:
            img.umount()
    except Exception, exn:
        LOG.exception(_('Failed to remove container: %s'), exn)


def inject_data_into_fs(fs, key, net, metadata, execute):
    """Injects data into a filesystem already mounted by the caller.
    Virt connections can call this directly if they mount their fs
    in a different way to inject_data
    """
    if key:
        _inject_key_into_fs(key, fs, execute=execute)
    if net:
        _inject_net_into_fs(net, fs, execute=execute)
    if metadata:
        _inject_metadata_into_fs(metadata, fs, execute=execute)


def _inject_metadata_into_fs(metadata, fs, execute=None):
    metadata_path = os.path.join(fs, "meta.js")
    metadata = dict([(m.key, m.value) for m in metadata])

    utils.execute('tee', metadata_path,
                  process_input=json.dumps(metadata), run_as_root=True)


def _inject_key_into_fs(key, fs, execute=None):
    """Add the given public ssh key to root's authorized_keys.

    key is an ssh key string.
    fs is the path to the base of the filesystem into which to inject the key.
    """
    sshdir = os.path.join(fs, 'root', '.ssh')
    utils.execute('mkdir', '-p', sshdir, run_as_root=True)
    utils.execute('chown', 'root', sshdir, run_as_root=True)
    utils.execute('chmod', '700', sshdir, run_as_root=True)
    keyfile = os.path.join(sshdir, 'authorized_keys')
    utils.execute('tee', '-a', keyfile,
                  process_input='\n' + key.strip() + '\n', run_as_root=True)


def _inject_net_into_fs(net, fs, execute=None):
    """Inject /etc/network/interfaces into the filesystem rooted at fs.

    net is the contents of /etc/network/interfaces.
    """
    netdir = os.path.join(os.path.join(fs, 'etc'), 'network')
    utils.execute('mkdir', '-p', netdir, run_as_root=True)
    utils.execute('chown', 'root:root', netdir, run_as_root=True)
    utils.execute('chmod', 755, netdir, run_as_root=True)
    netfile = os.path.join(netdir, 'interfaces')
    utils.execute('tee', netfile, process_input=net, run_as_root=True)
