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
libvirt specific routines.
"""

import binascii
import errno
import os
import stat

from oslo_concurrency import processutils
from oslo_utils import units

import nova.privsep


@nova.privsep.sys_admin_pctxt.entrypoint
def last_bytes(path, num):
    # NOTE(mikal): this is implemented in this contrived manner because you
    # can't mock a decorator in python (they're loaded at file parse time,
    # and the mock happens later).
    with open(path, 'rb') as f:
        return _last_bytes_inner(f, num)


def _last_bytes_inner(file_like_object, num):
    """Return num bytes from the end of the file, and remaining byte count.

    :param file_like_object: The file to read
    :param num: The number of bytes to return

    :returns: (data, remaining)
    """

    try:
        file_like_object.seek(-num, os.SEEK_END)
    except IOError as e:
        # seek() fails with EINVAL when trying to go before the start of
        # the file. It means that num is larger than the file size, so
        # just go to the start.
        if e.errno == errno.EINVAL:
            file_like_object.seek(0, os.SEEK_SET)
        else:
            raise

    remaining = file_like_object.tell()
    return (file_like_object.read(), remaining)


@nova.privsep.sys_admin_pctxt.entrypoint
def dmcrypt_create_volume(target, device, cipher, key_size, key):
    """Sets up a dmcrypt mapping

    :param target: device mapper logical device name
    :param device: underlying block device
    :param cipher: encryption cipher string digestible by cryptsetup
    :param key_size: encryption key size
    :param key: encoded encryption key bytestring
    """
    cmd = ('cryptsetup',
           'create',
           target,
           device,
           '--cipher=' + cipher,
           '--key-size=' + str(key_size),
           '--key-file=-')
    key = binascii.hexlify(key).decode('utf-8')
    processutils.execute(*cmd, process_input=key)


@nova.privsep.sys_admin_pctxt.entrypoint
def dmcrypt_delete_volume(target):
    """Deletes a dmcrypt mapping

    :param target: name of the mapped logical device
    """
    processutils.execute('cryptsetup', 'remove', target)


@nova.privsep.sys_admin_pctxt.entrypoint
def ploop_init(size, disk_format, fs_type, disk_path):
    """Initialize ploop disk, make it readable for non-root user

    :param disk_format: data allocation format (raw or expanded)
    :param fs_type: filesystem (ext4, ext3, none)
    :param disk_path: ploop image file
    """
    processutils.execute('ploop', 'init', '-s', size, '-f', disk_format, '-t',
                         fs_type, disk_path, run_as_root=True,
                         check_exit_code=True)

    # Add read access for all users, because "ploop init" creates
    # disk with rw rights only for root. OpenStack user should have access
    # to the disk to request info via "qemu-img info"
    # TODO(mikal): this is a faithful rendition of the pre-privsep code from
    # the libvirt driver, but it seems undesirable to me. It would be good to
    # create the loop file with the right owner or group such that we don't
    # need to have it world readable. I don't have access to a system to test
    # this on however.
    st = os.stat(disk_path)
    os.chmod(disk_path, st.st_mode | stat.S_IROTH)


@nova.privsep.sys_admin_pctxt.entrypoint
def ploop_resize(disk_path, size):
    """Resize ploop disk

    :param disk_path: ploop image file
    :param size: new size (in bytes)
    """
    processutils.execute('prl_disk_tool', 'resize',
                         '--size', '%dM' % (size // units.Mi),
                         '--resize_partition',
                         '--hdd', disk_path,
                         run_as_root=True, check_exit_code=True)


@nova.privsep.sys_admin_pctxt.entrypoint
def ploop_restore_descriptor(image_dir, base_delta, fmt):
    """Restore ploop disk descriptor XML

    :param image_dir: path to where descriptor XML is created
    :param base_delta: ploop image file containing the data
    :param fmt: ploop data allocation format (raw or expanded)
    """
    processutils.execute('ploop', 'restore-descriptor', '-f', fmt,
                         image_dir, base_delta,
                         run_as_root=True, check_exit_code=True)


@nova.privsep.sys_admin_pctxt.entrypoint
def enable_hairpin(interface):
    """Enable hairpin mode for a libvirt guest."""
    with open('/sys/class/net/%s/brport/hairpin_mode' % interface, 'w') as f:
        f.write('1')


@nova.privsep.sys_admin_pctxt.entrypoint
def disable_multicast_snooping(interface):
    """Disable multicast snooping for a bridge."""
    with open('/sys/class/net/%s/bridge/multicast_snooping' % interface,
              'w') as f:
        f.write('0')


@nova.privsep.sys_admin_pctxt.entrypoint
def disable_ipv6(interface):
    """Disable ipv6 for a bridge."""
    with open('/proc/sys/net/ipv6/conf/%s/disable_ipv' % interface, 'w') as f:
        f.write('1')
