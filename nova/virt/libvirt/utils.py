#    Copyright 2010 United States Government as represented by the
#    Administrator of the National Aeronautics and Space Administration.
#    All Rights Reserved.
#    Copyright (c) 2010 Citrix Systems, Inc.
#    Copyright (c) 2011 Piston Cloud Computing, Inc
#    Copyright (c) 2011 OpenStack Foundation
#    (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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
import os
import re

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import fileutils

import nova.conf
from nova.i18n import _
from nova.objects import fields as obj_fields
import nova.privsep.idmapshift
import nova.privsep.libvirt
from nova import utils
from nova.virt.disk import api as disk
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt.volume import remotefs

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

RESIZE_SNAPSHOT_NAME = 'nova-resize'


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
    utils.execute('qemu-img', 'create', '-f', disk_format, path, size)


def create_cow_image(backing_file, path, size=None):
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
    # Explicitly inherit the value of 'cluster_size' property of a qcow2
    # overlay image from its backing file. This can be useful in cases
    # when people create a base image with a non-default 'cluster_size'
    # value or cases when images were created with very old QEMU
    # versions which had a different default 'cluster_size'.
    if base_details and base_details.cluster_size is not None:
        cow_opts += ['cluster_size=%s' % base_details.cluster_size]
    if size is not None:
        cow_opts += ['size=%s' % size]
    if cow_opts:
        # Format as a comma separated list
        csv_opts = ",".join(cow_opts)
        cow_opts = ['-o', csv_opts]
    cmd = base_cmd + cow_opts + [path]
    utils.execute(*cmd)


def create_ploop_image(disk_format, path, size, fs_type):
    """Create ploop image

    :param disk_format: Disk image format (as known by ploop)
    :param path: Desired location of the ploop image
    :param size: Desired size of ploop image. May be given as an int or
                 a string. If given as an int, it will be interpreted
                 as bytes. If it's a string, it should consist of a number
                 with an optional suffix ('K' for Kibibytes,
                 M for Mebibytes, 'G' for Gibibytes, 'T' for Tebibytes).
                 If no suffix is given, it will be interpreted as bytes.
    :param fs_type: Filesystem type
    """
    if not fs_type:
        fs_type = CONF.default_ephemeral_format or \
                  disk.FS_FORMAT_EXT4
    fileutils.ensure_tree(path)
    disk_path = os.path.join(path, 'root.hds')
    nova.privsep.libvirt.ploop_init(size, disk_format, fs_type, disk_path)


def pick_disk_driver_name(hypervisor_version, is_block_dev=False):
    """Pick the libvirt primary backend driver name

    If the hypervisor supports multiple backend drivers we have to tell libvirt
    which one should be used.

    Xen supports the following drivers: "tap", "tap2", "phy", "file", or
    "qemu", being "qemu" the preferred one. Qemu only supports "qemu".

    :param is_block_dev:
    :returns: driver_name or None
    """
    if CONF.libvirt.virt_type == "xen":
        if is_block_dev:
            return "phy"
        else:
            # 4002000 == 4.2.0
            if hypervisor_version >= 4002000:
                try:
                    nova.privsep.libvirt.xend_probe()
                except OSError as exc:
                    if exc.errno == errno.ENOENT:
                        LOG.debug("xend is not found")
                        # libvirt will try to use libxl toolstack
                        return 'qemu'
                    else:
                        raise
                except processutils.ProcessExecutionError:
                    LOG.debug("xend is not started")
                    # libvirt will try to use libxl toolstack
                    return 'qemu'
            # libvirt will use xend/xm toolstack
            try:
                out, err = utils.execute('tap-ctl', 'check',
                                         check_exit_code=False)
                if out == 'ok\n':
                    # 4000000 == 4.0.0
                    if hypervisor_version > 4000000:
                        return "tap2"
                    else:
                        return "tap"
                else:
                    LOG.info("tap-ctl check: %s", out)
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    LOG.debug("tap-ctl tool is not installed")
                else:
                    raise
            return "file"
    elif CONF.libvirt.virt_type in ('kvm', 'qemu'):
        return "qemu"
    else:
        # UML doesn't want a driver_name set
        return None


def get_disk_size(path, format=None):
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :param format: the on-disk format of path
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    size = images.qemu_img_info(path, format).virtual_size
    return int(size)


def get_disk_backing_file(path, basename=True, format=None):
    """Get the backing file of a disk image

    :param path: Path to the disk image
    :returns: a path to the image's backing store
    """
    backing_file = images.qemu_img_info(path, format).backing_file
    if backing_file and basename:
        backing_file = os.path.basename(backing_file)

    return backing_file


def copy_image(src, dest, host=None, receive=False,
               on_execute=None, on_completion=None,
               compression=True):
    """Copy a disk image to an existing directory

    :param src: Source image
    :param dest: Destination path
    :param host: Remote host
    :param receive: Reverse the rsync direction
    :param on_execute: Callback method to store pid of process in cache
    :param on_completion: Callback method to remove pid of process from cache
    :param compression: Allows to use rsync operation with or without
                        compression
    """

    if not host:
        # We shell out to cp because that will intelligently copy
        # sparse files.  I.E. holes will not be written to DEST,
        # rather recreated efficiently.  In addition, since
        # coreutils 8.11, holes can be read efficiently too.
        # we add '-r' argument because ploop disks are directories
        utils.execute('cp', '-r', src, dest)
    else:
        if receive:
            src = "%s:%s" % (utils.safe_ip_format(host), src)
        else:
            dest = "%s:%s" % (utils.safe_ip_format(host), dest)

        remote_filesystem_driver = remotefs.RemoteFilesystem()
        remote_filesystem_driver.copy_file(src, dest,
            on_execute=on_execute, on_completion=on_completion,
            compression=compression)


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


def chown_for_id_maps(path, id_maps):
    """Change ownership of file or directory for an id mapped
    environment

    :param path: File or directory whose ownership to change
    :param id_maps: List of type LibvirtConfigGuestIDMap
    """
    uid_maps = [id_map for id_map in id_maps if
                isinstance(id_map, vconfig.LibvirtConfigGuestUIDMap)]
    gid_maps = [id_map for id_map in id_maps if
                isinstance(id_map, vconfig.LibvirtConfigGuestGIDMap)]
    nova.privsep.idmapshift.shift(path, uid_maps, gid_maps)


def extract_snapshot(disk_path, source_fmt, out_path, dest_fmt):
    """Extract a snapshot from a disk image.
    Note that nobody should write to the disk image during this operation.

    :param disk_path: Path to disk image
    :param out_path: Desired path of extracted snapshot
    """
    # NOTE(markmc): ISO is just raw to qemu-img
    if dest_fmt == 'iso':
        dest_fmt = 'raw'
    if dest_fmt == 'ploop':
        dest_fmt = 'parallels'

    qemu_img_cmd = ('qemu-img', 'convert', '-f', source_fmt, '-O', dest_fmt)

    # Conditionally enable compression of snapshots.
    if CONF.libvirt.snapshot_compression and dest_fmt == "qcow2":
        qemu_img_cmd += ('-c',)

    qemu_img_cmd += (disk_path, out_path)
    utils.execute(*qemu_img_cmd)


def load_file(path):
    """Read contents of file

    :param path: File to read
    """
    with open(path, 'r') as fp:
        return fp.read()


def file_open(*args, **kwargs):
    """Open file

    see built-in open() documentation for more details

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return open(*args, **kwargs)


def find_disk(guest):
    """Find root device path for instance

    May be file or device
    """
    guest_config = guest.get_config()

    disk_format = None
    if guest_config.virt_type == 'lxc':
        filesystem = next(d for d in guest_config.devices
                          if isinstance(d, vconfig.LibvirtConfigGuestFilesys))
        disk_path = filesystem.source_dir
        disk_path = disk_path[0:disk_path.rfind('rootfs')]
        disk_path = os.path.join(disk_path, 'disk')
    elif (guest_config.virt_type == 'parallels' and
          guest_config.os_type == obj_fields.VMMode.EXE):
        filesystem = next(d for d in guest_config.devices
                          if isinstance(d, vconfig.LibvirtConfigGuestFilesys))
        disk_format = filesystem.driver_type
        disk_path = filesystem.source_file
    else:
        disk = next(d for d in guest_config.devices
                    if isinstance(d, vconfig.LibvirtConfigGuestDisk))
        disk_format = disk.driver_format
        disk_path = disk.source_path if disk.source_type != 'mount' else None
        if not disk_path and disk.source_protocol == 'rbd':
            disk_path = disk.source_name
            if disk_path:
                disk_path = 'rbd:' + disk_path

    if not disk_path:
        raise RuntimeError(_("Can't retrieve root device path "
                             "from instance libvirt configuration"))

    # This is a legacy quirk of libvirt/xen. Everything else should
    # report the on-disk format in type.
    if disk_format == 'aio':
        disk_format = 'raw'
    return (disk_path, disk_format)


def get_disk_type_from_path(path):
    """Retrieve disk type (raw, qcow2, lvm, ploop) for given file."""
    if path.startswith('/dev'):
        return 'lvm'
    elif path.startswith('rbd:'):
        return 'rbd'
    elif (os.path.isdir(path) and
          os.path.exists(os.path.join(path, "DiskDescriptor.xml"))):
        return 'ploop'

    # We can't reliably determine the type from this path
    return None


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


def fetch_image(context, target, image_id):
    """Grab image."""
    images.fetch_to_raw(context, image_id, target)


def fetch_raw_image(context, target, image_id):
    """Grab initrd or kernel image.

    This function does not attempt raw conversion, as these images will
    already be in raw format.
    """
    images.fetch(context, image_id, target)


def get_instance_path(instance, relative=False):
    """Determine the correct path for instance storage.

    This method determines the directory name for instance storage.

    :param instance: the instance we want a path for
    :param relative: if True, just the relative path is returned

    :returns: a path to store information about that instance
    """
    if relative:
        return instance.uuid
    return os.path.join(CONF.instances_path, instance.uuid)


def get_instance_path_at_destination(instance, migrate_data=None):
    """Get the instance path on destination node while live migration.

    This method determines the directory name for instance storage on
    destination node, while live migration.

    :param instance: the instance we want a path for
    :param migrate_data: if not None, it is a dict which holds data
                         required for live migration without shared
                         storage.

    :returns: a path to store information about that instance
    """
    instance_relative_path = None
    if migrate_data:
        instance_relative_path = migrate_data.instance_relative_path
    # NOTE(mikal): this doesn't use libvirt_utils.get_instance_path
    # because we are ensuring that the same instance directory name
    # is used as was at the source
    if instance_relative_path:
        instance_dir = os.path.join(CONF.instances_path,
                                    instance_relative_path)
    else:
        instance_dir = get_instance_path(instance)
    return instance_dir


def get_arch(image_meta):
    """Determine the architecture of the guest (or host).

    This method determines the CPU architecture that must be supported by
    the hypervisor. It gets the (guest) arch info from image_meta properties,
    and it will fallback to the nova-compute (host) arch if no architecture
    info is provided in image_meta.

    :param image_meta: the metadata associated with the instance image

    :returns: guest (or host) architecture
    """
    if image_meta:
        image_arch = image_meta.properties.get('hw_architecture')
        if image_arch is not None:
            return image_arch

    return obj_fields.Architecture.from_host()


def is_mounted(mount_path, source=None):
    """Check if the given source is mounted at given destination point."""
    if not os.path.ismount(mount_path):
        return False

    if source is None:
        return True

    with open('/proc/mounts', 'r') as proc_mounts:
        mounts = [mount.split() for mount in proc_mounts.readlines()]
        return any(mnt[0] == source and mnt[1] == mount_path for mnt in mounts)


def is_valid_hostname(hostname):
    return re.match(r"^[\w\-\.:]+$", hostname)
