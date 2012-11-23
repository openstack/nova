# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2010 United States Government as represented by the
#    Administrator of the National Aeronautics and Space Administration.
#    All Rights Reserved.
#    Copyright (c) 2010 Citrix Systems, Inc.
#    Copyright (c) 2011 Piston Cloud Computing, Inc
#    Copyright (c) 2011 OpenStack LLC
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

import errno
import hashlib
import os
import re

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import images


LOG = logging.getLogger(__name__)


util_opts = [
    cfg.StrOpt('image_info_filename_pattern',
               default='$instances_path/$base_dir_name/%(image)s.info',
               help='Allows image information files to be stored in '
                    'non-standard locations')
    ]

flags.DECLARE('instances_path', 'nova.compute.manager')
flags.DECLARE('base_dir_name', 'nova.compute.manager')
FLAGS = flags.FLAGS
FLAGS.register_opts(util_opts)


def execute(*args, **kwargs):
    return utils.execute(*args, **kwargs)


def get_iscsi_initiator():
    """Get iscsi initiator name for this machine"""
    # NOTE(vish) openiscsi stores initiator name in a file that
    #            needs root permission to read.
    contents = utils.read_file_as_root('/etc/iscsi/initiatorname.iscsi')
    for l in contents.split('\n'):
        if l.startswith('InitiatorName='):
            return l[l.index('=') + 1:].strip()


def create_image(disk_format, path, size):
    """Create a disk image

    :param disk_format: Disk image format (as known by qemu-img)
    :param path: Desired location of the disk image
    :param size: Desired size of disk image. May be given as an int or
                 a string. If given as an int, it will be interpreted
                 as bytes. If it's a string, it should consist of a number
                 with an optional suffix ('K' for Kibibytes,
                 M for Mebibytes, 'G' for Gibibytes, 'T' for Tebibytes).
                 If no suffix is given, it will be interpreted as bytes.
    """
    execute('qemu-img', 'create', '-f', disk_format, path, size)


def create_cow_image(backing_file, path):
    """Create COW image

    Creates a COW image with the given backing file

    :param backing_file: Existing image on which to base the COW image
    :param path: Desired location of the COW image
    """
    execute('qemu-img', 'create', '-f', 'qcow2', '-o',
             'backing_file=%s' % backing_file, path)


def create_lvm_image(vg, lv, size, sparse=False):
    """Create LVM image.

    Creates a LVM image with given size.

    :param vg: existing volume group which should hold this image
    :param lv: name for this image (logical volume)
    :size: size of image in bytes
    :sparse: create sparse logical volume
    """
    free_space = volume_group_free_space(vg)

    def check_size(size):
        if size > free_space:
            raise RuntimeError(_('Insufficient Space on Volume Group %(vg)s.'
                                 ' Only %(free_space)db available,'
                                 ' but %(size)db required'
                                 ' by volume %(lv)s.') % locals())

    if sparse:
        preallocated_space = 64 * 1024 * 1024
        check_size(preallocated_space)
        if free_space < size:
            LOG.warning(_('Volume group %(vg)s will not be able'
                          ' to hold sparse volume %(lv)s.'
                          ' Virtual volume size is %(size)db,'
                          ' but free space on volume group is'
                          ' only %(free_space)db.') % locals())

        cmd = ('lvcreate', '-L', '%db' % preallocated_space,
                '--virtualsize', '%db' % size, '-n', lv, vg)
    else:
        check_size(size)
        cmd = ('lvcreate', '-L', '%db' % size, '-n', lv, vg)
    execute(*cmd, run_as_root=True, attempts=3)


def volume_group_free_space(vg):
    """Return available space on volume group in bytes.

    :param vg: volume group name
    """
    out, err = execute('vgs', '--noheadings', '--nosuffix',
                       '--units', 'b', '-o', 'vg_free', vg,
                       run_as_root=True)
    return int(out.strip())


def list_logical_volumes(vg):
    """List logical volumes paths for given volume group.

    :param vg: volume group name
    """
    out, err = execute('lvs', '--noheadings', '-o', 'lv_name', vg,
                       run_as_root=True)

    return [line.strip() for line in out.splitlines()]


def logical_volume_size(path):
    """Get logical volume size in bytes.

    :param path: logical volume path
    """
    # TODO(p-draigbrady) POssibly replace with the more general
    # use of blockdev --getsize64 in future
    out, _err = execute('lvs', '-o', 'lv_size', '--noheadings', '--units',
                        'b', '--nosuffix', path, run_as_root=True)

    return int(out)


def clear_logical_volume(path):
    """Obfuscate the logical volume.

    :param path: logical volume path
    """
    # TODO(p-draigbrady): We currently overwrite with zeros
    # but we may want to make this configurable in future
    # for more or less security conscious setups.

    vol_size = logical_volume_size(path)
    bs = 1024 * 1024
    remaining_bytes = vol_size

    # The loop caters for versions of dd that
    # don't support the iflag=count_bytes option.
    while remaining_bytes:
        zero_blocks = remaining_bytes / bs
        seek_blocks = (vol_size - remaining_bytes) / bs
        zero_cmd = ('dd', 'bs=%s' % bs,
                    'if=/dev/zero', 'of=%s' % path,
                    'seek=%s' % seek_blocks, 'count=%s' % zero_blocks)
        if zero_blocks:
            utils.execute(*zero_cmd, run_as_root=True)
        remaining_bytes %= bs
        bs /= 1024  # Limit to 3 iterations


def remove_logical_volumes(*paths):
    """Remove one or more logical volume."""

    for path in paths:
        clear_logical_volume(path)

    if paths:
        lvremove = ('lvremove', '-f') + paths
        execute(*lvremove, attempts=3, run_as_root=True)


def pick_disk_driver_name(is_block_dev=False):
    """Pick the libvirt primary backend driver name

    If the hypervisor supports multiple backend drivers, then the name
    attribute selects the primary backend driver name, while the optional
    type attribute provides the sub-type.  For example, xen supports a name
    of "tap", "tap2", "phy", or "file", with a type of "aio" or "qcow2",
    while qemu only supports a name of "qemu", but multiple types including
    "raw", "bochs", "qcow2", and "qed".

    :param is_block_dev:
    :returns: driver_name or None
    """
    if FLAGS.libvirt_type == "xen":
        if is_block_dev:
            return "phy"
        else:
            return "tap"
    elif FLAGS.libvirt_type in ('kvm', 'qemu'):
        return "qemu"
    else:
        # UML doesn't want a driver_name set
        return None


def get_disk_size(path):
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    size = images.qemu_img_info(path)['virtual size']
    size = size.split('(')[1].split()[0]
    return int(size)


def get_disk_backing_file(path):
    """Get the backing file of a disk image

    :param path: Path to the disk image
    :returns: a path to the image's backing store
    """
    backing_file = images.qemu_img_info(path).get('backing file')

    if backing_file:
        if 'actual path: ' in backing_file:
            backing_file = backing_file.split('actual path: ')[1][:-1]
        backing_file = os.path.basename(backing_file)

    return backing_file


def copy_image(src, dest, host=None):
    """Copy a disk image to an existing directory

    :param src: Source image
    :param dest: Destination path
    :param host: Remote host
    """

    if not host:
        # We shell out to cp because that will intelligently copy
        # sparse files.  I.E. holes will not be written to DEST,
        # rather recreated efficiently.  In addition, since
        # coreutils 8.11, holes can be read efficiently too.
        execute('cp', src, dest)
    else:
        dest = "%s:%s" % (host, dest)
        # Try rsync first as that can compress and create sparse dest files.
        # Note however that rsync currently doesn't read sparse files
        # efficiently: https://bugzilla.samba.org/show_bug.cgi?id=8918
        # At least network traffic is mitigated with compression.
        try:
            # Do a relatively light weight test first, so that we
            # can fall back to scp, without having run out of space
            # on the destination for example.
            execute('rsync', '--sparse', '--compress', '--dry-run', src, dest)
        except exception.ProcessExecutionError:
            execute('scp', src, dest)
        else:
            execute('rsync', '--sparse', '--compress', src, dest)


def mkfs(fs, path, label=None):
    """Format a file or block device

    :param fs: Filesystem type (examples include 'swap', 'ext3', 'ext4'
               'btrfs', etc.)
    :param path: Path to file or block device to format
    :param label: Volume label to use
    """
    if fs == 'swap':
        execute('mkswap', path)
    else:
        args = ['mkfs', '-t', fs]
        #add -F to force no interactive excute on non-block device.
        if fs in ['ext3', 'ext4']:
            args.extend(['-F'])
        if label:
            args.extend(['-n', label])
        args.append(path)
        execute(*args)


def write_to_file(path, contents, umask=None):
    """Write the given contents to a file

    :param path: Destination file
    :param contents: Desired contents of the file
    :param umask: Umask to set when creating this file (will be reset)
    """
    if umask:
        saved_umask = os.umask(umask)

    try:
        with open(path, 'w') as f:
            f.write(contents)
    finally:
        if umask:
            os.umask(saved_umask)


def chown(path, owner):
    """Change ownership of file or directory

    :param path: File or directory whose ownership to change
    :param owner: Desired new owner (given as uid or username)
    """
    execute('chown', owner, path, run_as_root=True)


def create_snapshot(disk_path, snapshot_name):
    """Create a snapshot in a disk image

    :param disk_path: Path to disk image
    :param snapshot_name: Name of snapshot in disk image
    """
    qemu_img_cmd = ('qemu-img',
                    'snapshot',
                    '-c',
                    snapshot_name,
                    disk_path)
    # NOTE(vish): libvirt changes ownership of images
    execute(*qemu_img_cmd, run_as_root=True)


def delete_snapshot(disk_path, snapshot_name):
    """Create a snapshot in a disk image

    :param disk_path: Path to disk image
    :param snapshot_name: Name of snapshot in disk image
    """
    qemu_img_cmd = ('qemu-img',
                    'snapshot',
                    '-d',
                    snapshot_name,
                    disk_path)
    # NOTE(vish): libvirt changes ownership of images
    execute(*qemu_img_cmd, run_as_root=True)


def extract_snapshot(disk_path, source_fmt, snapshot_name, out_path, dest_fmt):
    """Extract a named snapshot from a disk image

    :param disk_path: Path to disk image
    :param snapshot_name: Name of snapshot in disk image
    :param out_path: Desired path of extracted snapshot
    """
    # NOTE(markmc): ISO is just raw to qemu-img
    if dest_fmt == 'iso':
        dest_fmt = 'raw'
    qemu_img_cmd = ('qemu-img',
                    'convert',
                    '-f',
                    source_fmt,
                    '-O',
                    dest_fmt,
                    '-s',
                    snapshot_name,
                    disk_path,
                    out_path)
    execute(*qemu_img_cmd)


def load_file(path):
    """Read contents of file

    :param path: File to read
    """
    with open(path, 'r') as fp:
        return fp.read()


def file_open(*args, **kwargs):
    """Open file

    see built-in file() documentation for more details

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return file(*args, **kwargs)


def file_delete(path):
    """Delete (unlink) file

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return os.unlink(path)


def get_fs_info(path):
    """Get free/used/total space info for a filesystem

    :param path: Any dirent on the filesystem
    :returns: A dict containing:

             :free: How much space is free (in bytes)
             :used: How much space is used (in bytes)
             :total: How big the filesystem is (in bytes)
    """
    hddinfo = os.statvfs(path)
    total = hddinfo.f_frsize * hddinfo.f_blocks
    free = hddinfo.f_frsize * hddinfo.f_bavail
    used = hddinfo.f_frsize * (hddinfo.f_blocks - hddinfo.f_bfree)
    return {'total': total,
            'free': free,
            'used': used}


def fetch_image(context, target, image_id, user_id, project_id):
    """Grab image"""
    images.fetch_to_raw(context, image_id, target, user_id, project_id)


def get_info_filename(base_path):
    """Construct a filename for storing addtional information about a base
    image.

    Returns a filename.
    """

    base_file = os.path.basename(base_path)
    return (FLAGS.image_info_filename_pattern
            % {'image': base_file})


def is_valid_info_file(path):
    """Test if a given path matches the pattern for info files."""

    digest_size = hashlib.sha1().digestsize * 2
    regexp = (FLAGS.image_info_filename_pattern
              % {'image': ('([0-9a-f]{%(digest_size)d}|'
                           '[0-9a-f]{%(digest_size)d}_sm|'
                           '[0-9a-f]{%(digest_size)d}_[0-9]+)'
                           % {'digest_size': digest_size})})
    m = re.match(regexp, path)
    if m:
        return True
    return False


def read_stored_info(base_path, field=None):
    """Read information about an image.

    Returns an empty dictionary if there is no info, just the field value if
    a field is requested, or the entire dictionary otherwise.
    """

    info_file = get_info_filename(base_path)
    if not os.path.exists(info_file):
        # Special case to handle essex checksums being converted
        old_filename = base_path + '.sha1'
        if field == 'sha1' and os.path.exists(old_filename):
            hash_file = open(old_filename)
            hash_value = hash_file.read()
            hash_file.close()

            write_stored_info(base_path, field=field, value=hash_value)
            os.remove(old_filename)
            d = {field: hash_value}

        else:
            d = {}

    else:
        LOG.info(_('Reading image info file: %s'), info_file)
        f = open(info_file, 'r')
        serialized = f.read().rstrip()
        f.close()
        LOG.info(_('Read: %s'), serialized)

        try:
            d = jsonutils.loads(serialized)

        except ValueError, e:
            LOG.error(_('Error reading image info file %(filename)s: '
                        '%(error)s'),
                      {'filename': info_file,
                       'error': e})
            d = {}

    if field:
        return d.get(field, None)
    return d


def write_stored_info(target, field=None, value=None):
    """Write information about an image."""

    if not field:
        return

    info_file = get_info_filename(target)
    utils.ensure_tree(os.path.dirname(info_file))

    d = read_stored_info(info_file)
    d[field] = value
    serialized = jsonutils.dumps(d)

    LOG.info(_('Writing image info file: %s'), info_file)
    LOG.info(_('Wrote: %s'), serialized)
    f = open(info_file, 'w')
    f.write(serialized)
    f.close()
