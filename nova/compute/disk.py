# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

from nova import vendor
from twisted.internet import defer

from nova import exception

@defer.inlineCallbacks
def partition(infile, outfile, local_bytes=0, local_type='ext2', execute=None):
    """Takes a single partition represented by infile and writes a bootable
    drive image into outfile.

    The first 63 sectors (0-62) of the resulting image is a master boot record.
    Infile becomes the first primary partition.
    If local bytes is specified, a second primary partition is created and
    formatted as ext2.

    In the diagram below, dashes represent drive sectors.
     0   a b                c d               e
    +-----+------. . .-------+------. . .------+
    | mbr | primary partiton | local partition |
    +-----+------. . .-------+------. . .------+
    """
    sector_size = 512
    file_size = os.path.getsize(infile)
    if file_size % sector_size != 0:
        logging.warn("Input partition size not evenly divisible by"
                     " sector size: %d / %d", file_size, sector_size)
    primary_sectors = file_size / sector_size
    if local_bytes % sector_size != 0:
        logging.warn("Bytes for local storage not evenly divisible"
                     " by sector size: %d / %d", local_bytes, sector_size)
    local_sectors = local_bytes / sector_size

    mbr_last = 62 # a
    primary_first = mbr_last + 1 # b
    primary_last = primary_first + primary_sectors - 1 # c
    local_first = primary_last + 1 # d
    local_last = local_first + local_sectors - 1 # e
    last_sector = local_last # e

    # create an empty file
    execute('dd if=/dev/zero of=%s count=1 seek=%d bs=%d'
            % (outfile, last_sector, sector_size))

    # make mbr partition
    yield execute('parted --script %s mklabel msdos' % outfile)

    # make primary partition
    yield execute('parted --script %s mkpart primary %ds %ds'
                  % (outfile, primary_first, primary_last))

    # make local partition
    if local_bytes > 0:
        yield execute('parted --script %s mkpartfs primary %s %ds %ds'
                      % (outfile, local_type, local_first, local_last))

    # copy file into partition
    yield execute('dd if=%s of=%s bs=%d seek=%d conv=notrunc,fsync'
                  % (infile, outfile, sector_size, primary_first))

@defer.inlineCallbacks
def inject_data(image, key=None, net=None, partition=None, execute=None):
    """Injects a ssh key and optionally net data into a disk image.

    it will mount the image as a fully partitioned disk and attempt to inject
    into the specified partition number.

    If partition is not specified it mounts the image as a single partition.

    """
    out, err = yield execute('sudo losetup -f --show %s' % image)
    if err:
        raise exception.Error('Could not attach image to loopback: %s' % err)
    device = out.strip()
    try:
        if not partition is None:
            # create partition
            out, err = yield execute('sudo kpartx -a %s' % device)
            if err:
                raise exception.Error('Failed to load partition: %s' % err)
            mapped_device = '/dev/mapper/%sp%s' % (device.split('/')[-1],
                                                   partition)
        else:
            mapped_device = device
        out, err = yield execute('sudo tune2fs -c 0 -i 0 %s' % mapped_device)

        tmpdir = tempfile.mkdtemp()
        try:
            # mount loopback to dir
            out, err = yield execute(
                    'sudo mount %s %s' % (mapped_device, tmpdir))
            if err:
                raise exception.Error('Failed to mount filesystem: %s' % err)

            try:
                if key:
                    # inject key file
                    yield _inject_key_into_fs(key, tmpdir, execute=execute)
                if net:
                    yield _inject_net_into_fs(net, tmpdir, execute=execute)
            finally:
                # unmount device
                yield execute('sudo umount %s' % mapped_device)
        finally:
            # remove temporary directory
            # TODO(termie): scary, is there any thing we can check here?
            yield execute('rm -rf %s' % tmpdir)
            if not partition is None:
                # remove partitions
                yield execute('sudo kpartx -d %s' % device)
    finally:
        # remove loopback
        yield execute('sudo losetup -d %s' % device)

@defer.inlineCallbacks
def _inject_key_into_fs(key, fs, execute=None):
    sshdir = os.path.join(os.path.join(fs, 'root'), '.ssh')
    yield execute('sudo mkdir -p %s' % sshdir) # existing dir doesn't matter
    yield execute('sudo chown root %s' % sshdir)
    yield execute('sudo chmod 700 %s' % sshdir)
    keyfile = os.path.join(sshdir, 'authorized_keys')
    yield execute('sudo tee -a %s' % keyfile, '\n' + key.strip() + '\n')

@defer.inlineCallbacks
def _inject_net_into_fs(net, fs, execute=None):
    netfile = os.path.join(os.path.join(os.path.join(
            fs, 'etc'), 'network'), 'interfaces')
    yield execute('sudo tee %s' % netfile, net)

