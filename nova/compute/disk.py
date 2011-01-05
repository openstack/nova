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

import logging
import os
import tempfile

from nova import exception
from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_integer('minimum_root_size', 1024 * 1024 * 1024 * 10,
                     'minimum size in bytes of root partition')
flags.DEFINE_integer('block_size', 1024 * 1024 * 256,
                     'block_size to use for dd')


def partition(infile, outfile, local_bytes=0, resize=True, local_type='ext2'):
    """
    Turns a partition (infile) into a bootable drive image (outfile).

    The first 63 sectors (0-62) of the resulting image is a master boot record.
    Infile becomes the first primary partition.
    If local bytes is specified, a second primary partition is created and
    formatted as ext2.

    ::

        In the diagram below, dashes represent drive sectors.
        +-----+------. . .-------+------. . .------+
        | 0  a| b               c|d               e|
        +-----+------. . .-------+------. . .------+
        | mbr | primary partiton | local partition |
        +-----+------. . .-------+------. . .------+

    """
    sector_size = 512
    file_size = os.path.getsize(infile)
    if resize and file_size < FLAGS.minimum_root_size:
        last_sector = FLAGS.minimum_root_size / sector_size - 1
        utils.execute('dd if=/dev/zero of=%s count=1 seek=%d bs=%d'
                % (infile, last_sector, sector_size))
        utils.execute('e2fsck -fp %s' % infile, check_exit_code=False)
        utils.execute('resize2fs %s' % infile)
        file_size = FLAGS.minimum_root_size
    elif file_size % sector_size != 0:
        logging.warn(_("Input partition size not evenly divisible by"
                       " sector size: %d / %d"), file_size, sector_size)
    primary_sectors = file_size / sector_size
    if local_bytes % sector_size != 0:
        logging.warn(_("Bytes for local storage not evenly divisible"
                       " by sector size: %d / %d"), local_bytes, sector_size)
    local_sectors = local_bytes / sector_size

    mbr_last = 62  # a
    primary_first = mbr_last + 1  # b
    primary_last = primary_first + primary_sectors - 1  # c
    local_first = primary_last + 1  # d
    local_last = local_first + local_sectors - 1  # e
    last_sector = local_last  # e

    # create an empty file
    utils.execute('dd if=/dev/zero of=%s count=1 seek=%d bs=%d'
            % (outfile, mbr_last, sector_size))

    # make mbr partition
    utils.execute('parted --script %s mklabel msdos' % outfile)

    # append primary file
    utils.execute('dd if=%s of=%s bs=%s conv=notrunc,fsync oflag=append'
            % (infile, outfile, FLAGS.block_size))

    # make primary partition
    utils.execute('parted --script %s mkpart primary %ds %ds'
            % (outfile, primary_first, primary_last))

    if local_bytes > 0:
        # make the file bigger
        utils.execute('dd if=/dev/zero of=%s count=1 seek=%d bs=%d'
                % (outfile, last_sector, sector_size))
        # make and format local partition
        utils.execute('parted --script %s mkpartfs primary %s %ds %ds'
                % (outfile, local_type, local_first, local_last))


def extend(image, size):
    file_size = os.path.getsize(image)
    if file_size >= size:
        return
    return utils.execute('truncate -s %s %s' % (size, image))


def inject_data(image, key=None, net=None, partition=None):
    """Injects a ssh key and optionally net data into a disk image.

    it will mount the image as a fully partitioned disk and attempt to inject
    into the specified partition number.

    If partition is not specified it mounts the image as a single partition.

    """
    device = _link_device(image)
    try:
        if not partition is None:
            # create partition
            out, err = utils.execute('sudo kpartx -a %s' % device)
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
        out, err = utils.execute('sudo tune2fs -c 0 -i 0 %s' % mapped_device)

        tmpdir = tempfile.mkdtemp()
        try:
            # mount loopback to dir
            out, err = utils.execute(
                    'sudo mount %s %s' % (mapped_device, tmpdir))
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
                utils.execute('sudo umount %s' % mapped_device)
        finally:
            # remove temporary directory
            utils.execute('rmdir %s' % tmpdir)
            if not partition is None:
                # remove partitions
                utils.execute('sudo kpartx -d %s' % device)
    finally:
        _unlink_device(image, device)


def _link_device(image):
    if FLAGS.use_cow_images:
        device = _allocate_device()
        utils.execute('sudo qemu-nbd -c %s %s' % (device, image))
        return device
    else:
        out, err = utils.execute('sudo losetup --find --show %s' % image)
        if err:
            raise exception.Error(_('Could not attach image to loopback: %s')
                                  % err)
        return out.strip()


def _unlink_device(device):
    if FLAGS.use_cow_images:
        utils.execute('sudo qemu-nbd -d %s' % device)
        _free_device(device)
    else:
        utils.execute('sudo losetup --detach %s' % device)


_DEVICES = ['/dev/nbd%s' % i for i in xrange(16)]

def _allocate_device():
    # NOTE(vish): This assumes no other processes are using nbd devices.
    #             It will race cause a race condition if multiple
    #             workers are running on a given machine.
    if not _DEVICES:
        raise exception.Error(_('No free nbd devices'))
    return _DEVICES.pop()


def _free_device(device):
    _DEVICES.append(device)


def _inject_key_into_fs(key, fs):
    """Add the given public ssh key to root's authorized_keys.

    key is an ssh key string.
    fs is the path to the base of the filesystem into which to inject the key.
    """
    sshdir = os.path.join(fs, 'root', '.ssh')
    utils.execute('sudo mkdir -p %s' % sshdir)  # existing dir doesn't matter
    utils.execute('sudo chown root %s' % sshdir)
    utils.execute('sudo chmod 700 %s' % sshdir)
    keyfile = os.path.join(sshdir, 'authorized_keys')
    utils.execute('sudo tee -a %s' % keyfile, '\n' + key.strip() + '\n')


def _inject_net_into_fs(net, fs):
    """Inject /etc/network/interfaces into the filesystem rooted at fs.

    net is the contents of /etc/network/interfaces.
    """
    netdir = os.path.join(os.path.join(fs, 'etc'), 'network')
    utils.execute('sudo mkdir -p %s' % netdir)  # existing dir doesn't matter
    utils.execute('sudo chown root:root %s' % netdir)
    utils.execute('sudo chmod 755 %s' % netdir)
    netfile = os.path.join(netdir, 'interfaces')
    utils.execute('sudo tee %s' % netfile, net)
