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

import os

from lxml import etree

from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import images

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


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
    base_cmd = ['qemu-img', 'create', '-f', 'qcow2']
    cow_opts = []
    if backing_file:
        cow_opts += ['backing_file=%s' % backing_file]
        base_details = images.qemu_img_info(backing_file)
    else:
        base_details = None
    # This doesn't seem to get inherited so force it to...
    # http://paste.ubuntu.com/1213295/
    # TODO(harlowja) probably file a bug against qemu-img/qemu
    if base_details and base_details.cluster_size is not None:
        cow_opts += ['cluster_size=%s' % base_details.cluster_size]
    # For now don't inherit this due the following discussion...
    # See: http://www.gossamer-threads.com/lists/openstack/dev/10592
    # if 'preallocation' in base_details:
    #     cow_opts += ['preallocation=%s' % base_details['preallocation']]
    if base_details and base_details.encryption:
        cow_opts += ['encryption=%s' % base_details.encryption]
    if cow_opts:
        # Format as a comma separated list
        csv_opts = ",".join(cow_opts)
        cow_opts = ['-o', csv_opts]
    cmd = base_cmd + cow_opts + [path]
    execute(*cmd)


def create_lvm_image(vg, lv, size, sparse=False):
    """Create LVM image.

    Creates a LVM image with given size.

    :param vg: existing volume group which should hold this image
    :param lv: name for this image (logical volume)
    :size: size of image in bytes
    :sparse: create sparse logical volume
    """
    free_space = volume_group_free_space(vg)

    def check_size(vg, lv, size):
        if size > free_space:
            raise RuntimeError(_('Insufficient Space on Volume Group %(vg)s.'
                                 ' Only %(free_space)db available,'
                                 ' but %(size)db required'
                                 ' by volume %(lv)s.') % locals())

    if sparse:
        preallocated_space = 64 * 1024 * 1024
        check_size(vg, lv, preallocated_space)
        if free_space < size:
            LOG.warning(_('Volume group %(vg)s will not be able'
                          ' to hold sparse volume %(lv)s.'
                          ' Virtual volume size is %(size)db,'
                          ' but free space on volume group is'
                          ' only %(free_space)db.') % locals())

        cmd = ('lvcreate', '-L', '%db' % preallocated_space,
                '--virtualsize', '%db' % size, '-n', lv, vg)
    else:
        check_size(vg, lv, size)
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


def logical_volume_info(path):
    """Get logical volume info.

    :param path: logical volume path
    """
    out, err = execute('lvs', '-o', 'vg_all,lv_all',
                       '--separator', '|', path, run_as_root=True)

    info = [line.split('|') for line in out.splitlines()]

    if len(info) != 2:
        raise RuntimeError(_("Path %s must be LVM logical volume") % path)

    return dict(zip(*info))


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
    direct_flags = ('oflag=direct',)
    remaining_bytes = vol_size

    # The loop caters for versions of dd that
    # don't support the iflag=count_bytes option.
    while remaining_bytes:
        zero_blocks = remaining_bytes / bs
        seek_blocks = (vol_size - remaining_bytes) / bs
        zero_cmd = ('dd', 'bs=%s' % bs,
                    'if=/dev/zero', 'of=%s' % path,
                    'seek=%s' % seek_blocks, 'count=%s' % zero_blocks)
        zero_cmd += direct_flags
        if zero_blocks:
            utils.execute(*zero_cmd, run_as_root=True)
        remaining_bytes %= bs
        bs /= 1024  # Limit to 3 iterations
        direct_flags = ()  # Only use O_DIRECT with initial block size


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
    if CONF.libvirt_type == "xen":
        if is_block_dev:
            return "phy"
        else:
            return "file"
    elif CONF.libvirt_type in ('kvm', 'qemu'):
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
    size = images.qemu_img_info(path).virtual_size
    return int(size)


def get_disk_backing_file(path):
    """Get the backing file of a disk image

    :param path: Path to the disk image
    :returns: a path to the image's backing store
    """
    backing_file = images.qemu_img_info(path).backing_file
    if backing_file:
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


def find_disk(virt_dom):
    """Find root device path for instance

    May be file or device"""
    xml_desc = virt_dom.XMLDesc(0)
    domain = etree.fromstring(xml_desc)
    if CONF.libvirt_type == 'lxc':
        source = domain.find('devices/filesystem/source')
        disk_path = source.get('dir')
        disk_path = disk_path[0:disk_path.rfind('rootfs')]
        disk_path = os.path.join(disk_path, 'disk')
    else:
        source = domain.find('devices/disk/source')
        disk_path = source.get('file') or source.get('dev')

    if not disk_path:
        raise RuntimeError(_("Can't retrieve root device path "
                             "from instance libvirt configuration"))

    return disk_path


def get_disk_type(path):
    """Retrieve disk type (raw, qcow2, lvm) for given file"""
    if path.startswith('/dev'):
        return 'lvm'

    return images.qemu_img_info(path).file_format


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
