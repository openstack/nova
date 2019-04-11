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

from oslo_concurrency import processutils
from oslo_log import log as logging

import nova.privsep.utils


LOG = logging.getLogger(__name__)


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
