# Copyright 2018 Michael Still and Aptira
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
Helpers for qemu tasks.
"""

import os

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import units

from nova import exception
from nova.i18n import _
import nova.privsep.utils

LOG = logging.getLogger(__name__)

QEMU_IMG_LIMITS = processutils.ProcessLimits(
    cpu_time=30,
    address_space=1 * units.Gi)


@nova.privsep.sys_admin_pctxt.entrypoint
def convert_image(source, dest, in_format, out_format, instances_path,
                  compress):
    unprivileged_convert_image(source, dest, in_format, out_format,
                               instances_path, compress)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_convert_image(source, dest, in_format, out_format,
                               instances_path, compress):
    # NOTE(mdbooth, kchamart): `qemu-img convert` defaults to
    # 'cache=writeback' for the source image, and 'cache=unsafe' for the
    # target, which means that data is not synced to disk at completion.
    # We explicitly use 'cache=none' here, for the target image, to (1)
    # ensure that we don't interfere with other applications using the
    # host's I/O cache, and (2) ensure that the data is on persistent
    # storage when the command exits. Without (2), a host crash may
    # leave a corrupt image in the image cache, which Nova cannot
    # recover automatically.

    # NOTE(zigo, kchamart): We cannot use `qemu-img convert -t none` if
    # the 'instance_dir' is mounted on a filesystem that doesn't support
    # O_DIRECT, which is the case, for example, with 'tmpfs'. This
    # simply crashes `openstack server create` in environments like live
    # distributions. In such cases, the best choice is 'writeback',
    # which (a) makes the conversion multiple times faster; and (b) is
    # as safe as it can be, because at the end of the conversion it,
    # just like 'writethrough', calls fsync(2)|fdatasync(2), which
    # ensures to safely write the data to the physical disk.

    # NOTE(mikal): there is an assumption here that the source and destination
    # are in the instances_path. Is that worth enforcing?
    if nova.privsep.utils.supports_direct_io(instances_path):
        cache_mode = 'none'
    else:
        cache_mode = 'writeback'
    cmd = ('qemu-img', 'convert', '-t', cache_mode, '-O', out_format)

    if in_format is not None:
        cmd = cmd + ('-f', in_format)

    if compress:
        cmd += ('-c',)

    cmd = cmd + (source, dest)
    processutils.execute(*cmd)


@nova.privsep.sys_admin_pctxt.entrypoint
def privileged_qemu_img_info(path, format=None):
    """Return an oject containing the parsed output from qemu-img info

    This is a privileged call to qemu-img info using the sys_admin_pctxt
    entrypoint allowing host block devices etc to be accessed.
    """
    return unprivileged_qemu_img_info(path, format=format)


def unprivileged_qemu_img_info(path, format=None):
    """Return an object containing the parsed output from qemu-img info."""
    try:
        # The following check is about ploop images that reside within
        # directories and always have DiskDescriptor.xml file beside them
        if (os.path.isdir(path) and
            os.path.exists(os.path.join(path, "DiskDescriptor.xml"))):
            path = os.path.join(path, "root.hds")

        cmd = (
            'env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info', path,
            '--force-share', '--output=json',
        )
        if format is not None:
            cmd = cmd + ('-f', format)
        out, err = processutils.execute(*cmd, prlimit=QEMU_IMG_LIMITS)
    except processutils.ProcessExecutionError as exp:
        if exp.exit_code == -9:
            # this means we hit prlimits, make the exception more specific
            msg = (_("qemu-img aborted by prlimits when inspecting "
                    "%(path)s : %(exp)s") % {'path': path, 'exp': exp})
        elif exp.exit_code == 1 and 'No such file or directory' in exp.stderr:
            # The os.path.exists check above can race so this is a simple
            # best effort at catching that type of failure and raising a more
            # specific error.
            raise exception.DiskNotFound(location=path)
        else:
            msg = (_("qemu-img failed to execute on %(path)s : %(exp)s") %
                   {'path': path, 'exp': exp})
        raise exception.InvalidDiskInfo(reason=msg)

    if not out:
        msg = (_("Failed to run qemu-img info on %(path)s : %(error)s") %
               {'path': path, 'error': err})
        raise exception.InvalidDiskInfo(reason=msg)
    return out
