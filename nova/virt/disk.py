# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import os
import tempfile
import time

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger('nova.compute.disk')
FLAGS = flags.FLAGS
flags.DEFINE_integer('minimum_root_size', 1024 * 1024 * 1024 * 10,
                     'minimum size in bytes of root partition')
flags.DEFINE_integer('block_size', 1024 * 1024 * 256,
                     'block_size to use for dd')
flags.DEFINE_integer('timeout_nbd', 10,
                     'time to wait for a NBD device coming up')
flags.DEFINE_integer('max_nbd_devices', 16,
                     'maximum number of possible nbd devices')


def extend(image, size):
    """Increase image to size"""
    file_size = os.path.getsize(image)
    if file_size >= size:
        return
    utils.execute('truncate', '-s', size, image)
    # NOTE(vish): attempts to resize filesystem
    utils.execute('e2fsck', '-fp', image, check_exit_code=False)
    utils.execute('resize2fs', image, check_exit_code=False)


def inject_data(image, key=None, net=None, partition=None, nbd=False):
    """Injects a ssh key and optionally net data into a disk image.

    it will mount the image as a fully partitioned disk and attempt to inject
    into the specified partition number.

    If partition is not specified it mounts the image as a single partition.

    """
    device = _link_device(image, nbd)
    try:
        if not partition is None:
            # create partition
            out, err = utils.execute('sudo', 'kpartx', '-a', device)
            if err:
                raise exception.Error(_('Failed to load partition: %s') % err)
            mapped_device = '/dev/mapper/%sp%s' % (device.split('/')[-1],
                                                   partition)
        else:
            mapped_device = device

        # We can only loopback mount raw images. If the device isn't there,
        # it's normally because it's a .vmdk or a .vdi etc
        if not os.path.exists(mapped_device):
            raise exception.Error('Mapped device was not found (we can'
                                  ' only inject raw disk images): %s' %
                                  mapped_device)

        # Configure ext2fs so that it doesn't auto-check every N boots
        out, err = utils.execute('sudo', 'tune2fs',
                                 '-c', 0, '-i', 0, mapped_device)

        tmpdir = tempfile.mkdtemp()
        try:
            # mount loopback to dir
            out, err = utils.execute(
                    'sudo', 'mount', mapped_device, tmpdir)
            if err:
                raise exception.Error(_('Failed to mount filesystem: %s')
                                      % err)

            try:
                if key:
                    # inject key file
                    _inject_key_into_fs(key, tmpdir)
                if net:
                    _inject_net_into_fs(net, tmpdir)
            finally:
                # unmount device
                utils.execute('sudo', 'umount', mapped_device)
        finally:
            # remove temporary directory
            utils.execute('rmdir', tmpdir)
            if not partition is None:
                # remove partitions
                utils.execute('sudo', 'kpartx', '-d', device)
    finally:
        _unlink_device(device, nbd)


def setup_container(image, container_dir=None, partition=None):
    """Setup the LXC container

    It will mount the loopback image to the container directory in order
    to create the root filesystem for the container
    """
    nbd = False
    device = _link_device(image, nbd)
    err = utils.execute('sudo', 'mount', device, container_dir)
    if err:
        raise exception.Error(_('Failed to mount filesystem: %s')
                             % err)
        _unlink_device(device, nbd)


def destroy_container(target, instance):
    """Destroy the container once it terminates
 
    It will umount the container that is mounted, try to find the loopback
    device associated with the container and delete it.
    """
    try:
        container_dir = '%s/rootfs' % target
        utils.execute('sudo', 'umount', container_dir)
    finally:
        for loop in utils.popen('sudo losetup -a').readlines():
            if instance['name'] in loop:
                device = loop.split(loop, ':')
                utils.execute('sudo', 'losetup', '--detach', device)


def _link_device(image, nbd):
    """Link image to device using loopback or nbd"""
    if nbd:
        device = _allocate_device()
        utils.execute('sudo', 'qemu-nbd', '-c', device, image)
        # NOTE(vish): this forks into another process, so give it a chance
        #             to set up before continuuing
        for i in xrange(FLAGS.timeout_nbd):
            if os.path.exists("/sys/block/%s/pid" % os.path.basename(device)):
                return device
            time.sleep(1)
        raise exception.Error(_('nbd device %s did not show up') % device)
    else:
        out, err = utils.execute('sudo', 'losetup', '--find', '--show', image)
        if err:
            raise exception.Error(_('Could not attach image to loopback: %s')
                                  % err)
        return out.strip()


def _unlink_device(device, nbd):
    """Unlink image from device using loopback or nbd"""
    if nbd:
        utils.execute('sudo', 'qemu-nbd', '-d', device)
        _free_device(device)
    else:
        utils.execute('sudo', 'losetup', '--detach', device)


_DEVICES = ['/dev/nbd%s' % i for i in xrange(FLAGS.max_nbd_devices)]


def _allocate_device():
    # NOTE(vish): This assumes no other processes are allocating nbd devices.
    #             It may race cause a race condition if multiple
    #             workers are running on a given machine.
    while True:
        if not _DEVICES:
            raise exception.Error(_('No free nbd devices'))
        device = _DEVICES.pop()
        if not os.path.exists("/sys/block/%s/pid" % os.path.basename(device)):
            break
    return device


def _free_device(device):
    _DEVICES.append(device)


def _inject_key_into_fs(key, fs):
    """Add the given public ssh key to root's authorized_keys.

    key is an ssh key string.
    fs is the path to the base of the filesystem into which to inject the key.
    """
    sshdir = os.path.join(fs, 'root', '.ssh')
    utils.execute('sudo', 'mkdir', '-p', sshdir)  # existing dir doesn't matter
    utils.execute('sudo', 'chown', 'root', sshdir)
    utils.execute('sudo', 'chmod', '700', sshdir)
    keyfile = os.path.join(sshdir, 'authorized_keys')
    utils.execute('sudo', 'tee', '-a', keyfile,
            process_input='\n' + key.strip() + '\n')


def _inject_net_into_fs(net, fs):
    """Inject /etc/network/interfaces into the filesystem rooted at fs.

    net is the contents of /etc/network/interfaces.
    """
    netdir = os.path.join(os.path.join(fs, 'etc'), 'network')
    utils.execute('sudo', 'mkdir', '-p', netdir)  # existing dir doesn't matter
    utils.execute('sudo', 'chown', 'root:root', netdir)
    utils.execute('sudo', 'chmod', 755, netdir)
    netfile = os.path.join(netdir, 'interfaces')
    utils.execute('sudo', 'tee', netfile, process_input=net)
