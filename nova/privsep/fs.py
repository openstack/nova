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
def resize2fs(image, check_exit_code):
    unprivileged_resize2fs(image, check_exit_code)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_resize2fs(image, check_exit_code):
    try:
        processutils.execute('e2fsck',
                             '-fp',
                             image,
                             check_exit_code=[0, 1, 2])
    except processutils.ProcessExecutionError as exc:
        LOG.debug("Checking the file system with e2fsck has failed, "
                  "the resize will be aborted. (%s)", exc)
    else:
        processutils.execute('resize2fs',
                             image,
                             check_exit_code=check_exit_code)


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
