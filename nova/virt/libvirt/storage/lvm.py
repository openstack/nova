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

import os

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import units
import six

import nova.conf
from nova import exception
from nova.i18n import _
import nova.privsep.fs

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
        nova.privsep.fs.lvcreate(size, lv, vg,
                                 preallocated=preallocated_space)
    else:
        check_size(vg, lv, size)
        nova.privsep.fs.lvcreate(size, lv, vg)


def get_volume_group_info(vg):
    """Return free/used/total space info for a volume group in bytes

    :param vg: volume group name
    :returns: A dict containing:
             :total: How big the filesystem is (in bytes)
             :free: How much space is free (in bytes)
             :used: How much space is used (in bytes)
    """

    out, err = nova.privsep.fs.vginfo(vg)

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
    out, err = nova.privsep.fs.lvlist(vg)
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
    out, err = nova.privsep.fs.lvinfo(path)
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
        out, _err = nova.privsep.fs.blockdev_size(path)
    except processutils.ProcessExecutionError:
        if not os.path.exists(path):
            raise exception.VolumeBDMPathNotFound(path=path)
        else:
            raise
    return int(out)


def clear_volume(path):
    """Obfuscate the logical volume.

    :param path: logical volume path
    """
    if CONF.libvirt.volume_clear == 'none':
        return

    volume_clear_size = int(CONF.libvirt.volume_clear_size) * units.Mi

    try:
        volume_size = get_volume_size(path)
    except exception.VolumeBDMPathNotFound:
        LOG.warning('Ignoring missing logical volume %(path)s', {'path': path})
        return

    if volume_clear_size != 0 and volume_clear_size < volume_size:
        volume_size = volume_clear_size

    nova.privsep.fs.clear(path, volume_size,
                          shred=(CONF.libvirt.volume_clear == 'shred'))


def remove_volumes(paths):
    """Remove one or more logical volume."""

    errors = []
    for path in paths:
        clear_volume(path)
        try:
            nova.privsep.fs.lvremove(path)
        except processutils.ProcessExecutionError as exp:
            errors.append(six.text_type(exp))
    if errors:
        raise exception.VolumesNotRemoved(reason=(', ').join(errors))
