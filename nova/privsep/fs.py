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

import nova.privsep


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
