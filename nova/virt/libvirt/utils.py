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
import grp
import os
import pwd
import re
import typing as ty
import uuid

import os_traits
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import fileutils

import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import fields as obj_fields
import nova.privsep.fs
import nova.privsep.idmapshift
import nova.privsep.libvirt
import nova.privsep.path
from nova.scheduler import utils as scheduler_utils
from nova import utils
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt.volume import remotefs

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

RESIZE_SNAPSHOT_NAME = 'nova-resize'

# Mapping used to convert libvirt cpu features to traits, for more details, see
# https://github.com/libvirt/libvirt/blob/master/src/cpu_map/
CPU_TRAITS_MAPPING = {
    '3dnow': os_traits.HW_CPU_X86_3DNOW,
    'abm': os_traits.HW_CPU_X86_ABM,
    'aes': os_traits.HW_CPU_X86_AESNI,
    'avx': os_traits.HW_CPU_X86_AVX,
    'avx2': os_traits.HW_CPU_X86_AVX2,
    'avx512bw': os_traits.HW_CPU_X86_AVX512BW,
    'avx512cd': os_traits.HW_CPU_X86_AVX512CD,
    'avx512dq': os_traits.HW_CPU_X86_AVX512DQ,
    'avx512er': os_traits.HW_CPU_X86_AVX512ER,
    'avx512f': os_traits.HW_CPU_X86_AVX512F,
    'avx512pf': os_traits.HW_CPU_X86_AVX512PF,
    'avx512vl': os_traits.HW_CPU_X86_AVX512VL,
    'avx512vnni': os_traits.HW_CPU_X86_AVX512VNNI,
    'avx512vbmi': os_traits.HW_CPU_X86_AVX512VBMI,
    'avx512ifma': os_traits.HW_CPU_X86_AVX512IFMA,
    'avx512vbmi2': os_traits.HW_CPU_X86_AVX512VBMI2,
    'avx512bitalg': os_traits.HW_CPU_X86_AVX512BITALG,
    'vaes': os_traits.HW_CPU_X86_AVX512VAES,
    'gfni': os_traits.HW_CPU_X86_AVX512GFNI,
    'vpclmulqdq': os_traits.HW_CPU_X86_AVX512VPCLMULQDQ,
    'avx512-vpopcntdq': os_traits.HW_CPU_X86_AVX512VPOPCNTDQ,
    'bmi1': os_traits.HW_CPU_X86_BMI,
    'bmi2': os_traits.HW_CPU_X86_BMI2,
    'pclmuldq': os_traits.HW_CPU_X86_CLMUL,
    'f16c': os_traits.HW_CPU_X86_F16C,
    'fma': os_traits.HW_CPU_X86_FMA3,
    'fma4': os_traits.HW_CPU_X86_FMA4,
    'mmx': os_traits.HW_CPU_X86_MMX,
    'mpx': os_traits.HW_CPU_X86_MPX,
    'sha-ni': os_traits.HW_CPU_X86_SHA,
    'sse': os_traits.HW_CPU_X86_SSE,
    'sse2': os_traits.HW_CPU_X86_SSE2,
    'sse3': os_traits.HW_CPU_X86_SSE3,
    'sse4.1': os_traits.HW_CPU_X86_SSE41,
    'sse4.2': os_traits.HW_CPU_X86_SSE42,
    'sse4a': os_traits.HW_CPU_X86_SSE4A,
    'ssse3': os_traits.HW_CPU_X86_SSSE3,
    # We have to continue to support the old (generic) trait for the
    # AMD-specific svm feature.
    'svm': (os_traits.HW_CPU_X86_SVM, os_traits.HW_CPU_X86_AMD_SVM),
    'tbm': os_traits.HW_CPU_X86_TBM,
    # We have to continue to support the old (generic) trait for the
    # Intel-specific vmx feature.
    'vmx': (os_traits.HW_CPU_X86_VMX, os_traits.HW_CPU_X86_INTEL_VMX),
    'xop': os_traits.HW_CPU_X86_XOP
}

# Reverse CPU_TRAITS_MAPPING
TRAITS_CPU_MAPPING = {v: k for k, v in CPU_TRAITS_MAPPING.items()}

# global directory for emulated TPM
VTPM_DIR = '/var/lib/libvirt/swtpm/'


def create_image(
    disk_format: str, path: str, size: ty.Union[str, int],
) -> None:
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
    processutils.execute('qemu-img', 'create', '-f', disk_format, path, size)


def create_cow_image(
    backing_file: ty.Optional[str], path: str, size: ty.Optional[int] = None,
) -> None:
    """Create COW image

    Creates a COW image with the given backing file

    :param backing_file: Existing image on which to base the COW image
    :param path: Desired location of the COW image
    """
    base_cmd = ['qemu-img', 'create', '-f', 'qcow2']
    cow_opts = []
    if backing_file:
        base_details = images.qemu_img_info(backing_file)
        cow_opts += ['backing_file=%s' % backing_file]
        cow_opts += ['backing_fmt=%s' % base_details.file_format]
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
    processutils.execute(*cmd)


def create_ploop_image(
    disk_format: str, path: str, size: ty.Union[int, str], fs_type: str,
) -> None:
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
                  nova.privsep.fs.FS_FORMAT_EXT4
    fileutils.ensure_tree(path)
    disk_path = os.path.join(path, 'root.hds')
    nova.privsep.libvirt.ploop_init(size, disk_format, fs_type, disk_path)


def pick_disk_driver_name(
    hypervisor_version: int, is_block_dev: bool = False,
) -> ty.Optional[str]:
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
                out, err = processutils.execute('tap-ctl', 'check',
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


def get_disk_size(path: str, format: ty.Optional[str] = None) -> int:
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :param format: the on-disk format of path
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    size = images.qemu_img_info(path, format).virtual_size
    return int(size)


def get_disk_backing_file(
    path: str, basename: bool = True, format: ty.Optional[str] = None,
) -> ty.Optional[str]:
    """Get the backing file of a disk image

    :param path: Path to the disk image
    :returns: a path to the image's backing store
    """
    backing_file = images.qemu_img_info(path, format).backing_file
    if backing_file and basename:
        backing_file = os.path.basename(backing_file)

    return backing_file


def copy_image(
    src: str,
    dest: str,
    host: ty.Optional[str] = None,
    receive: bool = False,
    on_execute: ty.Callable = None,
    on_completion: ty.Callable = None,
    compression: bool = True,
) -> None:
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
        processutils.execute('cp', '-r', src, dest)
    else:
        if receive:
            src = "%s:%s" % (utils.safe_ip_format(host), src)
        else:
            dest = "%s:%s" % (utils.safe_ip_format(host), dest)

        remote_filesystem_driver = remotefs.RemoteFilesystem()
        remote_filesystem_driver.copy_file(src, dest,
            on_execute=on_execute, on_completion=on_completion,
            compression=compression)


def chown_for_id_maps(
    path: str, id_maps: ty.List[vconfig.LibvirtConfigGuestIDMap],
) -> None:
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


def extract_snapshot(
    disk_path: str, source_fmt: str, out_path: str, dest_fmt: str,
) -> None:
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

    compress = CONF.libvirt.snapshot_compression and dest_fmt == "qcow2"
    images.convert_image(disk_path, out_path, source_fmt, dest_fmt,
                         compress=compress)


# TODO(stephenfin): This is dumb; remove it.
def load_file(path: str) -> str:
    """Read contents of file

    :param path: File to read
    """
    with open(path, 'r') as fp:
        return fp.read()


# TODO(stephenfin): Remove this; we have suitably powerful mocking abilities
# nowadays
def file_open(*args, **kwargs):
    """Open file

    see built-in open() documentation for more details

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return open(*args, **kwargs)


def find_disk(guest: libvirt_guest.Guest) -> ty.Tuple[str, ty.Optional[str]]:
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


def get_disk_type_from_path(path: str) -> ty.Optional[str]:
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


def get_fs_info(path: str) -> ty.Dict[str, int]:
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
    return {'total': total, 'free': free, 'used': used}


def fetch_image(
    context: nova_context.RequestContext,
    target: str,
    image_id: str,
    trusted_certs: ty.Optional['objects.TrustedCerts'] = None,
) -> None:
    """Grab image.

    :param context: nova.context.RequestContext auth request context
    :param target: target path to put the image
    :param image_id: id of the image to fetch
    :param trusted_certs: optional objects.TrustedCerts for image validation
    """
    images.fetch_to_raw(context, image_id, target, trusted_certs)


def fetch_raw_image(
    context: nova_context.RequestContext,
    target: str,
    image_id: str,
    trusted_certs: ty.Optional['objects.TrustedCerts'] = None,
) -> None:
    """Grab initrd or kernel image.

    This function does not attempt raw conversion, as these images will
    already be in raw format.

    :param context: nova.context.RequestContext auth request context
    :param target: target path to put the image
    :param image_id: id of the image to fetch
    :param trusted_certs: optional objects.TrustedCerts for image validation
    """
    images.fetch(context, image_id, target, trusted_certs)


def get_instance_path(
    instance: 'objects.Instance', relative: bool = False,
) -> str:
    """Determine the correct path for instance storage.

    This method determines the directory name for instance storage.

    :param instance: the instance we want a path for
    :param relative: if True, just the relative path is returned

    :returns: a path to store information about that instance
    """
    if relative:
        return instance.uuid
    return os.path.join(CONF.instances_path, instance.uuid)


def get_instance_path_at_destination(
    instance: 'objects.Instance',
    migrate_data: ty.Optional['objects.LibvirtLiveMigrateData'] = None,
) -> str:
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


def get_arch(image_meta: 'objects.ImageMeta') -> str:
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


def is_mounted(mount_path: str, source: ty.Optional[str] = None) -> bool:
    """Check if the given source is mounted at given destination point."""
    if not os.path.ismount(mount_path):
        return False

    if source is None:
        return True

    with open('/proc/mounts', 'r') as proc_mounts:
        mounts = [mount.split() for mount in proc_mounts.readlines()]
        return any(mnt[0] == source and mnt[1] == mount_path for mnt in mounts)


def is_valid_hostname(hostname: str) -> bool:
    return bool(re.match(r"^[\w\-\.:]+$", hostname))


def version_to_string(version: ty.Tuple[int, int, int]) -> str:
    """Returns string version based on tuple"""
    return '.'.join([str(x) for x in version])


def cpu_features_to_traits(features: ty.Set[str]) -> ty.Dict[str, bool]:
    """Returns this driver's CPU traits dict where keys are trait names from
    CPU_TRAITS_MAPPING, values are boolean indicates whether the trait should
    be set in the provider tree.

    :param features: A set of feature names (short, lowercase,
            CPU_TRAITS_MAPPING's keys).
    """
    traits = {}
    for feature_name, val in CPU_TRAITS_MAPPING.items():
        trait_tuple = val if isinstance(val, tuple) else (val,)
        for trait_name in trait_tuple:
            traits[trait_name] = feature_name in features

    return traits


def get_cpu_model_from_arch(arch: str) -> str:
    mode = 'qemu64'
    if arch == obj_fields.Architecture.I686:
        mode = 'qemu32'
    elif arch == obj_fields.Architecture.PPC64LE:
        mode = 'POWER8'
    # NOTE(kevinz): In aarch64, cpu model 'max' will offer the capabilities
    # that all the stuff it can currently emulate, both for "TCG" and "KVM"
    elif arch == obj_fields.Architecture.AARCH64:
        mode = 'max'
    return mode


def get_machine_type(image_meta: 'objects.ImageMeta') -> ty.Optional[str]:
    """The guest machine type can be set as an image metadata property, or
    otherwise based on architecture-specific defaults. If no defaults are
    found then None will be returned. This will ultimately lead to QEMU using
    its own default which is currently the 'pc' machine type.
    """
    if image_meta.properties.get('hw_machine_type') is not None:
        return image_meta.properties.hw_machine_type

    # If set in the config, use that as the default.
    return get_default_machine_type(get_arch(image_meta))


def get_default_machine_type(arch: str) -> ty.Optional[str]:
    # NOTE(lyarwood): Values defined in [libvirt]/hw_machine_type take
    # precedence here if available for the provided arch.
    for mapping in CONF.libvirt.hw_machine_type or {}:
        host_arch, _, machine_type = mapping.partition('=')
        if machine_type == '':
            LOG.warning("Invalid hw_machine_type config value %s", mapping)
        elif host_arch == arch:
            return machine_type
    # NOTE(kchamart): For ARMv7 and AArch64, use the 'virt' board as the
    # default machine type.  It is the recommended board, which is designed
    # to be used with virtual machines.  The 'virt' board is more flexible,
    # supports PCI, 'virtio', has decent RAM limits, etc.
    #
    # NOTE(sean-k-mooney): Nova's default for x86 is still 'pc', so
    # use that, not 'q35', for x86_64 and i686.
    #
    # NOTE(aspiers): If you change this, don't forget to update the
    # docs and metadata for hw_machine_type in glance.
    default_mtypes = {
        obj_fields.Architecture.ARMV7: "virt",
        obj_fields.Architecture.AARCH64: "virt",
        obj_fields.Architecture.S390: "s390-ccw-virtio",
        obj_fields.Architecture.S390X: "s390-ccw-virtio",
        obj_fields.Architecture.I686: "pc",
        obj_fields.Architecture.X86_64: "pc",
    }
    return default_mtypes.get(arch)


def mdev_name2uuid(mdev_name: str) -> str:
    """Convert an mdev name (of the form mdev_<uuid_with_underscores>) to a
    uuid (of the form 8-4-4-4-12).
    """
    return str(uuid.UUID(mdev_name[5:].replace('_', '-')))


def mdev_uuid2name(mdev_uuid: str) -> str:
    """Convert an mdev uuid (of the form 8-4-4-4-12) to a name (of the form
    mdev_<uuid_with_underscores>).
    """
    return "mdev_" + mdev_uuid.replace('-', '_')


def get_flags_by_flavor_specs(flavor: 'objects.Flavor') -> ty.Set[str]:
    req_spec = objects.RequestSpec(flavor=flavor)
    resource_request = scheduler_utils.ResourceRequest(req_spec)
    required_traits = resource_request.all_required_traits

    flags = [TRAITS_CPU_MAPPING[trait] for trait in required_traits
             if trait in TRAITS_CPU_MAPPING]

    return set(flags)


def save_and_migrate_vtpm_dir(
    instance_uuid: str,
    inst_base_resize: str,
    inst_base: str,
    dest: str,
    on_execute: ty.Callable,
    on_completion: ty.Callable,
) -> None:
    """Save vTPM data to instance directory and migrate to the destination.

    If the instance has vTPM enabled, then we need to save its vTPM data
    locally (to allow for revert) and then migrate the data to the dest node.
    Do so by copying vTPM data from the swtpm data directory to a resize
    working directory, $inst_base_resize, and then copying this to the remote
    directory at $dest:$inst_base.

    :param instance_uuid: The instance's UUID.
    :param inst_base_resize: The instance's base resize working directory.
    :param inst_base: The instances's base directory on the destination host.
    :param dest: Destination host.
    :param on_execute: Callback method to store PID of process in cache.
    :param on_completion: Callback method to remove PID of process from cache.
    :returns: None.
    """
    vtpm_dir = os.path.join(VTPM_DIR, instance_uuid)
    if not os.path.exists(vtpm_dir):
        return

    # We likely need to create the instance swtpm directory on the dest node
    # with ownership that is not the user running nova. We only have
    # permissions to copy files to <instance_path> on the dest node so we need
    # to get creative.

    # First, make a new directory in the local instance directory
    swtpm_dir = os.path.join(inst_base_resize, 'swtpm')
    fileutils.ensure_tree(swtpm_dir)
    # Now move the per-instance swtpm persistent files into the
    # local instance directory.
    nova.privsep.path.move_tree(vtpm_dir, swtpm_dir)
    # Now adjust ownership.
    nova.privsep.path.chown(
        swtpm_dir, os.geteuid(), os.getegid(), recursive=True)
    # Copy the swtpm subtree to the remote instance directory
    copy_image(
        swtpm_dir, inst_base, host=dest, on_execute=on_execute,
        on_completion=on_completion)


def restore_vtpm_dir(swtpm_dir: str) -> None:
    """Given a saved TPM directory, restore it where libvirt can find it.

    :path swtpm_dir: Path to swtpm directory.
    :returns: None
    """
    # Ensure global swtpm dir exists with suitable
    # permissions/ownership
    if not os.path.exists(VTPM_DIR):
        nova.privsep.path.makedirs(VTPM_DIR)
        nova.privsep.path.chmod(VTPM_DIR, 0o711)
    elif not os.path.isdir(VTPM_DIR):
        msg = _(
            'Guest wants emulated TPM but host path %s is not a directory.')
        raise exception.Invalid(msg % VTPM_DIR)

    # These can raise KeyError but they're validated by the driver on startup.
    uid = pwd.getpwnam(CONF.libvirt.swtpm_user).pw_uid
    gid = grp.getgrnam(CONF.libvirt.swtpm_group).gr_gid

    # Set ownership of instance-specific files
    nova.privsep.path.chown(swtpm_dir, uid, gid, recursive=True)
    # Move instance-specific directory to global dir
    nova.privsep.path.move_tree(swtpm_dir, VTPM_DIR)
