# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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
Helpers for filesystem related routines.
"""

import hashlib
import six

from oslo_concurrency import processutils
from oslo_log import log as logging

import nova.privsep


LOG = logging.getLogger(__name__)


@nova.privsep.sys_admin_pctxt.entrypoint
def mount(fstype, device, mountpoint, options):
    mount_cmd = ['mount']
    if fstype:
        mount_cmd.extend(['-t', fstype])
    if options is not None:
        mount_cmd.extend(options)
    mount_cmd.extend([device, mountpoint])
    return processutils.execute(*mount_cmd)


@nova.privsep.sys_admin_pctxt.entrypoint
def umount(mountpoint):
    processutils.execute('umount', mountpoint, attempts=3, delay_on_retry=True)


@nova.privsep.sys_admin_pctxt.entrypoint
def lvcreate(size, lv, vg, preallocated=None):
    cmd = ['lvcreate']
    if not preallocated:
        cmd.extend(['-L', '%db' % size])
    else:
        cmd.extend(['-L', '%db' % preallocated,
                    '--virtualsize', '%db' % size])
    cmd.extend(['-n', lv, vg])
    processutils.execute(*cmd, attempts=3)


@nova.privsep.sys_admin_pctxt.entrypoint
def vginfo(vg):
    return processutils.execute('vgs', '--noheadings', '--nosuffix',
                                '--separator', '|', '--units', 'b',
                                '-o', 'vg_size,vg_free', vg)


@nova.privsep.sys_admin_pctxt.entrypoint
def lvlist(vg):
    return processutils.execute('lvs', '--noheadings', '-o', 'lv_name', vg)


@nova.privsep.sys_admin_pctxt.entrypoint
def lvinfo(path):
    return processutils.execute('lvs', '-o', 'vg_all,lv_all',
                                '--separator', '|', path)


@nova.privsep.sys_admin_pctxt.entrypoint
def lvremove(path):
    processutils.execute('lvremove', '-f', path, attempts=3)


@nova.privsep.sys_admin_pctxt.entrypoint
def blockdev_size(path):
    return processutils.execute('blockdev', '--getsize64', path)


@nova.privsep.sys_admin_pctxt.entrypoint
def blockdev_flush(path):
    return processutils.execute('blockdev', '--flushbufs', path)


@nova.privsep.sys_admin_pctxt.entrypoint
def clear(path, volume_size, shred=False):
    cmd = ['shred']
    if shred:
        cmd.extend(['-n3'])
    else:
        cmd.extend(['-n0', '-z'])
    cmd.extend(['-s%d' % volume_size, path])
    processutils.execute(*cmd)


@nova.privsep.sys_admin_pctxt.entrypoint
def loopsetup(path):
    return processutils.execute('losetup', '--find', '--show', path)


@nova.privsep.sys_admin_pctxt.entrypoint
def loopremove(device):
    return processutils.execute('losetup', '--detach', device, attempts=3)


@nova.privsep.sys_admin_pctxt.entrypoint
def nbd_connect(device, image):
    return processutils.execute('qemu-nbd', '-c', device, image)


@nova.privsep.sys_admin_pctxt.entrypoint
def nbd_disconnect(device):
    return processutils.execute('qemu-nbd', '-d', device)


@nova.privsep.sys_admin_pctxt.entrypoint
def create_device_maps(device):
    return processutils.execute('kpartx', '-a', device)


@nova.privsep.sys_admin_pctxt.entrypoint
def remove_device_maps(device):
    return processutils.execute('kpartx', '-d', device)


@nova.privsep.sys_admin_pctxt.entrypoint
def get_filesystem_type(device):
    return processutils.execute('blkid', '-o', 'value', '-s', 'TYPE', device,
                                check_exit_code=[0, 2])


@nova.privsep.sys_admin_pctxt.entrypoint
def e2fsck(image, flags='-fp'):
    unprivileged_e2fsck(image, flags=flags)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_e2fsck(image, flags='-fp'):
    processutils.execute('e2fsck', flags, image, check_exit_code=[0, 1, 2])


@nova.privsep.sys_admin_pctxt.entrypoint
def resize2fs(image, check_exit_code, size=None):
    unprivileged_resize2fs(image, check_exit_code=check_exit_code, size=size)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_resize2fs(image, check_exit_code, size=None):
    if size:
        cmd = ['resize2fs', image, size]
    else:
        cmd = ['resize2fs', image]

    processutils.execute(*cmd, check_exit_code=check_exit_code)


@nova.privsep.sys_admin_pctxt.entrypoint
def create_partition_table(device, style, check_exit_code=True):
    processutils.execute('parted', '--script', device, 'mklabel', style,
                         check_exit_code=check_exit_code)


@nova.privsep.sys_admin_pctxt.entrypoint
def create_partition(device, style, start, end, check_exit_code=True):
    processutils.execute('parted', '--script', device, '--',
                         'mkpart', style, start, end,
                         check_exit_code=check_exit_code)


@nova.privsep.sys_admin_pctxt.entrypoint
def list_partitions(device):
    return unprivileged_list_partitions(device)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_list_partitions(device):
    """Return partition information (num, size, type) for a device."""

    out, _err = processutils.execute('parted', '--script', '--machine',
                                     device, 'unit s', 'print')
    lines = [line for line in out.split('\n') if line]
    partitions = []

    LOG.debug('Partitions:')
    for line in lines[2:]:
        line = line.rstrip(';')
        num, start, end, size, fstype, name, flags = line.split(':')
        num = int(num)
        start = int(start.rstrip('s'))
        end = int(end.rstrip('s'))
        size = int(size.rstrip('s'))
        LOG.debug('  %(num)s: %(fstype)s %(size)d sectors',
                  {'num': num, 'fstype': fstype, 'size': size})
        partitions.append((num, start, size, fstype, name, flags))

    return partitions


@nova.privsep.sys_admin_pctxt.entrypoint
def resize_partition(device, start, end, bootable):
    return unprivileged_resize_partition(device, start, end, bootable)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_resize_partition(device, start, end, bootable):
    processutils.execute('parted', '--script', device, 'rm', '1')
    processutils.execute('parted', '--script', device, 'mkpart',
                         'primary', '%ds' % start, '%ds' % end)
    if bootable:
        processutils.execute('parted', '--script', device,
                             'set', '1', 'boot', 'on')


@nova.privsep.sys_admin_pctxt.entrypoint
def ext_journal_disable(device):
    processutils.execute('tune2fs', '-O ^has_journal', device)


@nova.privsep.sys_admin_pctxt.entrypoint
def ext_journal_enable(device):
    processutils.execute('tune2fs', '-j', device)


# NOTE(mikal): nova allows deployers to configure the command line which is
# used to create a filesystem of a given type. This is frankly a little bit
# weird, but its also historical and probably should be in some sort of
# museum. So, we do that thing here, but it requires a funny dance in order
# to load that configuration at startup.

# NOTE(mikal): I really feel like this whole thing should be deprecated, I
# just don't think its a great idea to let people specify a command in a
# configuration option to run a root.

_MKFS_COMMAND = {}
_DEFAULT_MKFS_COMMAND = None

FS_FORMAT_EXT2 = "ext2"
FS_FORMAT_EXT3 = "ext3"
FS_FORMAT_EXT4 = "ext4"
FS_FORMAT_XFS = "xfs"
FS_FORMAT_NTFS = "ntfs"
FS_FORMAT_VFAT = "vfat"

SUPPORTED_FS_TO_EXTEND = (
    FS_FORMAT_EXT2,
    FS_FORMAT_EXT3,
    FS_FORMAT_EXT4)

_DEFAULT_FILE_SYSTEM = FS_FORMAT_VFAT
_DEFAULT_FS_BY_OSTYPE = {'linux': FS_FORMAT_EXT4,
                         'windows': FS_FORMAT_NTFS}


def load_mkfs_command(os_type, command):
    global _MKFS_COMMAND
    global _DEFAULT_MKFS_COMMAND

    _MKFS_COMMAND[os_type] = command
    if os_type == 'default':
        _DEFAULT_MKFS_COMMAND = command


def get_fs_type_for_os_type(os_type):
    global _MKFS_COMMAND

    return os_type if _MKFS_COMMAND.get(os_type) else 'default'


# NOTE(mikal): this method needs to be duplicated from utils because privsep
# can't depend on code outside the privsep directory.
def _get_hash_str(base_str):
    """Returns string that represents MD5 hash of base_str (in hex format).

    If base_str is a Unicode string, encode it to UTF-8.
    """
    if isinstance(base_str, six.text_type):
        base_str = base_str.encode('utf-8')
    return hashlib.md5(base_str).hexdigest()


def get_file_extension_for_os_type(os_type, default_ephemeral_format,
                                   specified_fs=None):
    global _MKFS_COMMAND
    global _DEFAULT_MKFS_COMMAND

    mkfs_command = _MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND)
    if mkfs_command:
        extension = mkfs_command
    else:
        if not specified_fs:
            specified_fs = default_ephemeral_format
            if not specified_fs:
                specified_fs = _DEFAULT_FS_BY_OSTYPE.get(os_type,
                                                         _DEFAULT_FILE_SYSTEM)
        extension = specified_fs
    return _get_hash_str(extension)[:7]


@nova.privsep.sys_admin_pctxt.entrypoint
def mkfs(fs, path, label=None):
    unprivileged_mkfs(fs, path, label=None)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_mkfs(fs, path, label=None):
    """Format a file or block device

    :param fs: Filesystem type (examples include 'swap', 'ext3', 'ext4'
               'btrfs', etc.)
    :param path: Path to file or block device to format
    :param label: Volume label to use
    """
    if fs == 'swap':
        args = ['mkswap']
    else:
        args = ['mkfs', '-t', fs]
    # add -F to force no interactive execute on non-block device.
    if fs in ('ext3', 'ext4', 'ntfs'):
        args.extend(['-F'])
    if label:
        if fs in ('msdos', 'vfat'):
            label_opt = '-n'
        else:
            label_opt = '-L'
        args.extend([label_opt, label])
    args.append(path)
    processutils.execute(*args)


@nova.privsep.sys_admin_pctxt.entrypoint
def _inner_configurable_mkfs(os_type, fs_label, target):
    mkfs_command = (_MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND) or
                    '') % {'fs_label': fs_label, 'target': target}
    processutils.execute(*mkfs_command.split())


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def configurable_mkfs(os_type, fs_label, target, run_as_root,
                      default_ephemeral_format, specified_fs=None):
    # Format a file or block device using a user provided command for each
    # os type. If user has not provided any configuration, format type will
    # be used according to a default_ephemeral_format configuration or a
    # system default.
    global _MKFS_COMMAND
    global _DEFAULT_MKFS_COMMAND

    mkfs_command = (_MKFS_COMMAND.get(os_type, _DEFAULT_MKFS_COMMAND) or
                    '') % {'fs_label': fs_label, 'target': target}
    if mkfs_command:
        if run_as_root:
            _inner_configurable_mkfs(os_type, fs_label, target)
        else:
            processutils.execute(*mkfs_command.split())

    else:
        if not specified_fs:
            specified_fs = default_ephemeral_format
            if not specified_fs:
                specified_fs = _DEFAULT_FS_BY_OSTYPE.get(os_type,
                                                         _DEFAULT_FILE_SYSTEM)

        if run_as_root:
            mkfs(specified_fs, target, fs_label)
        else:
            unprivileged_mkfs(specified_fs, target, fs_label)
