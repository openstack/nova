# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
Handling of VM disk images.
"""

import operator
import os

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import imageutils
from oslo_utils import units

import nova.conf
from nova import exception
from nova.i18n import _
from nova import image
from nova import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF
IMAGE_API = image.API()

QEMU_IMG_LIMITS = processutils.ProcessLimits(
    cpu_time=30,
    address_space=1 * units.Gi)

# This is set by the libvirt driver on startup. The version is used to
# determine what flags need to be set on the command line.
QEMU_VERSION = None
QEMU_VERSION_REQ_SHARED = 2010000


def qemu_img_info(path, format=None):
    """Return an object containing the parsed output from qemu-img info."""
    # TODO(mikal): this code should not be referring to a libvirt specific
    # flag.
    if not os.path.exists(path) and CONF.libvirt.images_type != 'rbd':
        raise exception.DiskNotFound(location=path)

    try:
        # The following check is about ploop images that reside within
        # directories and always have DiskDescriptor.xml file beside them
        if (os.path.isdir(path) and
            os.path.exists(os.path.join(path, "DiskDescriptor.xml"))):
            path = os.path.join(path, "root.hds")

        cmd = ('env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info', path)
        if format is not None:
            cmd = cmd + ('-f', format)
        # Check to see if the qemu version is >= 2.10 because if so, we need
        # to add the --force-share flag.
        if QEMU_VERSION and operator.ge(QEMU_VERSION, QEMU_VERSION_REQ_SHARED):
            cmd = cmd + ('--force-share',)
        out, err = utils.execute(*cmd, prlimit=QEMU_IMG_LIMITS)
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

    return imageutils.QemuImgInfo(out)


def convert_image(source, dest, in_format, out_format, run_as_root=False):
    """Convert image to other format."""
    if in_format is None:
        raise RuntimeError("convert_image without input format is a security"
                           " risk")
    _convert_image(source, dest, in_format, out_format, run_as_root)


def convert_image_unsafe(source, dest, out_format, run_as_root=False):
    """Convert image to other format, doing unsafe automatic input format
    detection. Do not call this function.
    """

    # NOTE: there is only 1 caller of this function:
    # imagebackend.Lvm.create_image. It is not easy to fix that without a
    # larger refactor, so for the moment it has been manually audited and
    # allowed to continue. Remove this function when Lvm.create_image has
    # been fixed.
    _convert_image(source, dest, None, out_format, run_as_root)


def _convert_image(source, dest, in_format, out_format, run_as_root):
    # NOTE(mdbooth): qemu-img convert defaults to cache=unsafe, which means
    # that data is not synced to disk at completion. We explicitly use
    # cache=none here to (1) ensure that we don't interfere with other
    # applications using the host's io cache, and (2) ensure that the data is
    # on persistent storage when the command exits. Without (2), a host crash
    # may leave a corrupt image in the image cache, which Nova cannot recover
    # automatically.
    # NOTE(zigo): we cannot use -t none if the instances dir is mounted on a
    # filesystem that doesn't have support for O_DIRECT, which is the case
    # for example with tmpfs. This simply crashes "openstack server create"
    # in environments like live distributions. In such case, the best choice
    # is writethrough, which is power-failure safe, but still faster than
    # writeback.
    if utils.supports_direct_io(CONF.instances_path):
        cache_mode = 'none'
    else:
        cache_mode = 'writethrough'
    cmd = ('qemu-img', 'convert', '-t', cache_mode, '-O', out_format)

    if in_format is not None:
        cmd = cmd + ('-f', in_format)
    cmd = cmd + (source, dest)
    try:
        utils.execute(*cmd, run_as_root=run_as_root)
    except processutils.ProcessExecutionError as exp:
        msg = (_("Unable to convert image to %(format)s: %(exp)s") %
               {'format': out_format, 'exp': exp})
        raise exception.ImageUnacceptable(image_id=source, reason=msg)


def fetch(context, image_href, path):
    with fileutils.remove_path_on_error(path):
        IMAGE_API.download(context, image_href, dest_path=path)


def get_info(context, image_href):
    return IMAGE_API.get(context, image_href)


def fetch_to_raw(context, image_href, path):
    path_tmp = "%s.part" % path
    fetch(context, image_href, path_tmp)

    with fileutils.remove_path_on_error(path_tmp):
        data = qemu_img_info(path_tmp)

        fmt = data.file_format
        if fmt is None:
            raise exception.ImageUnacceptable(
                reason=_("'qemu-img info' parsing failed."),
                image_id=image_href)

        backing_file = data.backing_file
        if backing_file is not None:
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=(_("fmt=%(fmt)s backed by: %(backing_file)s") %
                        {'fmt': fmt, 'backing_file': backing_file}))

        if fmt != "raw" and CONF.force_raw_images:
            staged = "%s.converted" % path
            LOG.debug("%s was %s, converting to raw", image_href, fmt)
            with fileutils.remove_path_on_error(staged):
                try:
                    convert_image(path_tmp, staged, fmt, 'raw')
                except exception.ImageUnacceptable as exp:
                    # re-raise to include image_href
                    raise exception.ImageUnacceptable(image_id=image_href,
                        reason=_("Unable to convert image to raw: %(exp)s")
                        % {'exp': exp})

                os.unlink(path_tmp)

                data = qemu_img_info(staged)
                if data.file_format != "raw":
                    raise exception.ImageUnacceptable(image_id=image_href,
                        reason=_("Converted to raw, but format is now %s") %
                        data.file_format)

                os.rename(staged, path)
        else:
            os.rename(path_tmp, path)
