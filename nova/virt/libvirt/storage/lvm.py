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
#

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import units
import six

import nova.conf
from nova import exception
from nova.i18n import _
from nova.virt.libvirt import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def create_volume(vg, lv, size, sparse=False):
    """Create LVM image.

    Creates a LVM image with given size.

    :param vg: existing volume group which should hold this image
    :param lv: name for this image (logical volume)
    :size: size of image in bytes
    :sparse: create sparse logical volume
    """
    vg_info = get_volume_group_info(vg)
    free_space = vg_info['free']

    def check_size(vg, lv, size):
        if size > free_space:
            raise RuntimeError(_('Insufficient Space on Volume Group %(vg)s.'
                                 ' Only %(free_space)db available,'
                                 ' but %(size)d bytes required'
                                 ' by volume %(lv)s.') %
                               {'vg': vg,
                                'free_space': free_space,
                                'size': size,
                                'lv': lv})

    if sparse:
        preallocated_space = 64 * units.Mi
        check_size(vg, lv, preallocated_space)
        if free_space < size:
            LOG.warning('Volume group %(vg)s will not be able'
                        ' to hold sparse volume %(lv)s.'
                        ' Virtual volume size is %(size)d bytes,'
                        ' but free space on volume group is'
                        ' only %(free_space)db.',
                        {'vg': vg,
                         'free_space': free_space,
                         'size': size,
                         'lv': lv})

        cmd = ('lvcreate', '-L', '%db' % preallocated_space,
                '--virtualsize', '%db' % size, '-n', lv, vg)
    else:
        check_size(vg, lv, size)
        cmd = ('lvcreate', '-L', '%db' % size, '-n', lv, vg)
    utils.execute(*cmd, run_as_root=True, attempts=3)


def get_volume_group_info(vg):
    """Return free/used/total space info for a volume group in bytes

    :param vg: volume group name
    :returns: A dict containing:
             :total: How big the filesystem is (in bytes)
             :free: How much space is free (in bytes)
             :used: How much space is used (in bytes)
    """

    out, err = utils.execute('vgs', '--noheadings', '--nosuffix',
                       '--separator', '|',
                       '--units', 'b', '-o', 'vg_size,vg_free', vg,
                       run_as_root=True)

    info = out.split('|')
    if len(info) != 2:
        raise RuntimeError(_("vg %s must be LVM volume group") % vg)

    return {'total': int(info[0]),
            'free': int(info[1]),
            'used': int(info[0]) - int(info[1])}


def list_volumes(vg):
    """List logical volumes paths for given volume group.

    :param vg: volume group name
    :returns: Return a logical volume list for given volume group
            : Data format example
            : ['volume-aaa', 'volume-bbb', 'volume-ccc']
    """
    out, err = utils.execute('lvs', '--noheadings', '-o', 'lv_name', vg,
                             run_as_root=True)

    return [line.strip() for line in out.splitlines()]


def volume_info(path):
    """Get logical volume info.

    :param path: logical volume path
    :returns: Return a dict object including info of given logical volume
            : Data format example
            : {'#Seg': '1', 'Move': '', 'Log': '', 'Meta%': '', 'Min': '-1',
            : ...
            : 'Free': '9983', 'LV': 'volume-aaa', 'Host': 'xyz.com',
            : 'Active': 'active', 'Path': '/dev/vg/volume-aaa', '#LV': '3',
            : 'Maj': '-1', 'VSize': '50.00g', 'VFree': '39.00g', 'Pool': '',
            : 'VG Tags': '', 'KMaj': '253', 'Convert': '', 'LProfile': '',
            : '#Ext': '12799', 'Attr': '-wi-a-----', 'VG': 'vg',
            : ...
            : 'LSize': '1.00g', '#PV': '1', '#VMdaCps': 'unmanaged'}
    """
    out, err = utils.execute('lvs', '-o', 'vg_all,lv_all',
                             '--separator', '|', path, run_as_root=True)

    info = [line.split('|') for line in out.splitlines()]

    if len(info) != 2:
        raise RuntimeError(_("Path %s must be LVM logical volume") % path)

    return dict(zip(*info))


def get_volume_size(path):
    """Get logical volume size in bytes.

    :param path: logical volume path
    :raises: processutils.ProcessExecutionError if getting the volume size
             fails in some unexpected way.
    :raises: exception.VolumeBDMPathNotFound if the volume path does not exist.
    """
    try:
        out, _err = utils.execute('blockdev', '--getsize64', path,
                                  run_as_root=True)
    except processutils.ProcessExecutionError:
        if not utils.path_exists(path):
            raise exception.VolumeBDMPathNotFound(path=path)
        else:
            raise
    return int(out)


def _zero_volume(path, volume_size):
    """Write zeros over the specified path

    :param path: logical volume path
    :param size: number of zeros to write
    """
    bs = units.Mi
    direct_flags = ('oflag=direct',)
    sync_flags = ()
    remaining_bytes = volume_size

    # The loop efficiently writes zeros using dd,
    # and caters for versions of dd that don't have
    # the easier to use iflag=count_bytes option.
    while remaining_bytes:
        zero_blocks = remaining_bytes // bs
        seek_blocks = (volume_size - remaining_bytes) // bs
        zero_cmd = ('dd', 'bs=%s' % bs,
                    'if=/dev/zero', 'of=%s' % path,
                    'seek=%s' % seek_blocks, 'count=%s' % zero_blocks)
        zero_cmd += direct_flags
        zero_cmd += sync_flags
        if zero_blocks:
            utils.execute(*zero_cmd, run_as_root=True)
        remaining_bytes %= bs
        bs //= units.Ki  # Limit to 3 iterations
        # Use O_DIRECT with initial block size and fdatasync otherwise
        direct_flags = ()
        sync_flags = ('conv=fdatasync',)


def clear_volume(path):
    """Obfuscate the logical volume.

    :param path: logical volume path
    """
    volume_clear = CONF.libvirt.volume_clear

    if volume_clear == 'none':
        return

    volume_clear_size = int(CONF.libvirt.volume_clear_size) * units.Mi

    try:
        volume_size = get_volume_size(path)
    except exception.VolumeBDMPathNotFound:
        LOG.warning('ignoring missing logical volume %(path)s', {'path': path})
        return

    if volume_clear_size != 0 and volume_clear_size < volume_size:
        volume_size = volume_clear_size

    if volume_clear == 'zero':
        # NOTE(p-draigbrady): we could use shred to do the zeroing
        # with -n0 -z, however only versions >= 8.22 perform as well as dd
        _zero_volume(path, volume_size)
    elif volume_clear == 'shred':
        utils.execute('shred', '-n3', '-s%d' % volume_size, path,
                      run_as_root=True)


def remove_volumes(paths):
    """Remove one or more logical volume."""

    errors = []
    for path in paths:
        clear_volume(path)
        lvremove = ('lvremove', '-f', path)
        try:
            utils.execute(*lvremove, attempts=3, run_as_root=True)
        except processutils.ProcessExecutionError as exp:
            errors.append(six.text_type(exp))
    if errors:
        raise exception.VolumesNotRemoved(reason=(', ').join(errors))
