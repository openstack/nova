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

from lxml import etree
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging

from nova.compute import arch
from nova.compute import vm_mode
from nova.i18n import _
from nova.i18n import _LI
from nova import utils
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt.volume import remotefs
from nova.virt import volumeutils

libvirt_opts = [
    cfg.BoolOpt('snapshot_compression',
                default=False,
                help='Compress snapshot images when possible. This '
                     'currently applies exclusively to qcow2 images'),
    ]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts, 'libvirt')
CONF.import_opt('instances_path', 'nova.compute.manager')
LOG = logging.getLogger(__name__)

RESIZE_SNAPSHOT_NAME = 'nova-resize'


def execute(*args, **kwargs):
    return utils.execute(*args, **kwargs)


def get_iscsi_initiator():
    return volumeutils.get_iscsi_initiator()


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
    execute(*cmd)


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
                    execute('xend', 'status',
                            run_as_root=True, check_exit_code=True)
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
                out, err = execute('tap-ctl', 'check', check_exit_code=False)
                if out == 'ok\n':
                    # 4000000 == 4.0.0
                    if hypervisor_version > 4000000:
                        return "tap2"
                    else:
                        return "tap"
                else:
                    LOG.info(_LI("tap-ctl check: %s"), out)
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
        execute('cp', src, dest)
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


def chown(path, owner):
    """Change ownership of file or directory

    :param path: File or directory whose ownership to change
    :param owner: Desired new owner (given as uid or username)
    """
    execute('chown', owner, path, run_as_root=True)


def update_mtime(path):
    """Touch a file without being the owner.

    :param path: File bump the mtime on
    """
    execute('touch', '-c', path, run_as_root=True)


def _id_map_to_config(id_map):
    return "%s:%s:%s" % (id_map.start, id_map.target, id_map.count)


def chown_for_id_maps(path, id_maps):
    """Change ownership of file or directory for an id mapped
    environment

    :param path: File or directory whose ownership to change
    :param id_maps: List of type LibvirtConfigGuestIDMap
    """
    uid_maps_str = ','.join([_id_map_to_config(id_map) for id_map in id_maps if
                             isinstance(id_map,
                                        vconfig.LibvirtConfigGuestUIDMap)])
    gid_maps_str = ','.join([_id_map_to_config(id_map) for id_map in id_maps if
                             isinstance(id_map,
                                        vconfig.LibvirtConfigGuestGIDMap)])
    execute('nova-idmapshift', '-i', '-u', uid_maps_str,
            '-g', gid_maps_str, path, run_as_root=True)


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
    execute(*qemu_img_cmd)


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


def file_delete(path):
    """Delete (unlink) file

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return os.unlink(path)


def path_exists(path):
    """Returns if path exists

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return os.path.exists(path)


def find_disk(virt_dom):
    """Find root device path for instance

    May be file or device
    """
    xml_desc = virt_dom.XMLDesc(0)
    domain = etree.fromstring(xml_desc)
    os_type = domain.find('os/type').text
    driver = None
    if CONF.libvirt.virt_type == 'lxc':
        filesystem = domain.find('devices/filesystem')
        driver = filesystem.find('driver')

        source = filesystem.find('source')
        disk_path = source.get('dir')
        disk_path = disk_path[0:disk_path.rfind('rootfs')]
        disk_path = os.path.join(disk_path, 'disk')
    elif CONF.libvirt.virt_type == 'parallels' and os_type == vm_mode.EXE:
        filesystem = domain.find('devices/filesystem')
        driver = filesystem.find('driver')

        source = filesystem.find('source')
        disk_path = source.get('file')
    else:
        disk = domain.find('devices/disk')
        driver = disk.find('driver')

        source = disk.find('source')
        disk_path = source.get('file') or source.get('dev')
        if not disk_path and CONF.libvirt.images_type == 'rbd':
            disk_path = source.get('name')
            if disk_path:
                disk_path = 'rbd:' + disk_path

    if not disk_path:
        raise RuntimeError(_("Can't retrieve root device path "
                             "from instance libvirt configuration"))

    if driver is not None:
        format = driver.get('type')
        # This is a legacy quirk of libvirt/xen. Everything else should
        # report the on-disk format in type.
        if format == 'aio':
            format = 'raw'
    else:
        format = None
    return (disk_path, format)


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


def fetch_image(context, target, image_id, user_id, project_id, max_size=0):
    """Grab image."""
    images.fetch_to_raw(context, image_id, target, user_id, project_id,
                        max_size=max_size)


def fetch_raw_image(context, target, image_id, user_id, project_id,
                    max_size=0):
    """Grab initrd or kernel image.

    This function does not attempt raw conversion, as these images will
    already be in raw format.
    """
    images.fetch(context, image_id, target, user_id, project_id,
                 max_size=max_size)


def get_instance_path(instance, forceold=False, relative=False):
    """Determine the correct path for instance storage.

    This method determines the directory name for instance storage, while
    handling the fact that we changed the naming style to something more
    unique in the grizzly release.

    :param instance: the instance we want a path for
    :param forceold: force the use of the pre-grizzly format
    :param relative: if True, just the relative path is returned

    :returns: a path to store information about that instance
    """
    pre_grizzly_name = os.path.join(CONF.instances_path, instance.name)
    if forceold or os.path.exists(pre_grizzly_name):
        if relative:
            return instance.name
        return pre_grizzly_name

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

    return arch.from_host()


def is_mounted(mount_path, source=None):
    """Check if the given source is mounted at given destination point."""
    try:
        check_cmd = ['findmnt', '--target', mount_path]
        if source:
            check_cmd.extend(['--source', source])

        utils.execute(*check_cmd)
        return True
    except processutils.ProcessExecutionError:
        return False
    except OSError as exc:
        # info since it's not required to have this tool.
        if exc.errno == errno.ENOENT:
            LOG.info(_LI("findmnt tool is not installed"))
        return False


def is_valid_hostname(hostname):
    return re.match(r"^[\w\-\.:]+$", hostname)
