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

import os

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import imageutils
from oslo_utils.imageutils import format_inspector

from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.i18n import _
from nova.image import glance
import nova.privsep.qemu

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF
IMAGE_API = glance.API()


def qemu_img_info(path, format=None):
    """Return an object containing the parsed output from qemu-img info."""
    if not os.path.exists(path) and not path.startswith('rbd:'):
        raise exception.DiskNotFound(location=path)

    info = nova.privsep.qemu.unprivileged_qemu_img_info(path, format=format)
    return imageutils.QemuImgInfo(info, format='json')


def privileged_qemu_img_info(path, format=None, output_format='json'):
    """Return an object containing the parsed output from qemu-img info."""
    if not os.path.exists(path) and not path.startswith('rbd:'):
        raise exception.DiskNotFound(location=path)

    info = nova.privsep.qemu.privileged_qemu_img_info(path, format=format)
    return imageutils.QemuImgInfo(info, format='json')


def convert_image(source, dest, in_format, out_format, run_as_root=False,
                  compress=False, src_encryption=None, dest_encryption=None):
    """Convert image to other format."""
    if in_format is None:
        raise RuntimeError("convert_image without input format is a security"
                           " risk")
    _convert_image(source, dest, in_format, out_format, run_as_root,
                   compress=compress, src_encryption=src_encryption,
                   dest_encryption=dest_encryption)


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


def _convert_image(source, dest, in_format, out_format, run_as_root,
                   compress=False, src_encryption=None, dest_encryption=None):
    try:
        with compute_utils.disk_ops_semaphore:
            if not run_as_root:
                nova.privsep.qemu.unprivileged_convert_image(
                    source, dest, in_format, out_format, CONF.instances_path,
                    compress, src_encryption=src_encryption,
                    dest_encryption=dest_encryption)
            else:
                nova.privsep.qemu.convert_image(
                    source, dest, in_format, out_format, CONF.instances_path,
                    compress, src_encryption=src_encryption,
                    dest_encryption=dest_encryption)

    except processutils.ProcessExecutionError as exp:
        msg = (_("Unable to convert image to %(format)s: %(exp)s") %
               {'format': out_format, 'exp': exp})
        raise exception.ImageUnacceptable(image_id=source, reason=msg)


def fetch(context, image_href, path, trusted_certs=None):
    with fileutils.remove_path_on_error(path):
        with compute_utils.disk_ops_semaphore:
            IMAGE_API.download(context, image_href, dest_path=path,
                               trusted_certs=trusted_certs)


def get_info(context, image_href):
    return IMAGE_API.get(context, image_href)


def check_vmdk_image(image_id, data):
    # Check some rules about VMDK files. Specifically we want to make
    # sure that the "create-type" of the image is one that we allow.
    # Some types of VMDK files can reference files outside the disk
    # image and we do not want to allow those for obvious reasons.

    types = CONF.compute.vmdk_allowed_types

    if not len(types):
        LOG.warning('Refusing to allow VMDK image as vmdk_allowed_'
                    'types is empty')
        msg = _('Invalid VMDK create-type specified')
        raise exception.ImageUnacceptable(image_id=image_id, reason=msg)

    try:
        create_type = data.format_specific['data']['create-type']
    except KeyError:
        msg = _('Unable to determine VMDK create-type')
        raise exception.ImageUnacceptable(image_id=image_id, reason=msg)

    if create_type not in CONF.compute.vmdk_allowed_types:
        LOG.warning('Refusing to process VMDK file with create-type of %r '
                    'which is not in allowed set of: %s', create_type,
                    ','.join(CONF.compute.vmdk_allowed_types))
        msg = _('Invalid VMDK create-type specified')
        raise exception.ImageUnacceptable(image_id=image_id, reason=msg)


def do_image_deep_inspection(img, image_href, path):
    ami_formats = ('ami', 'aki', 'ari')
    disk_format = img['disk_format']
    try:
        # NOTE(danms): Use our own cautious inspector module to make sure
        # the image file passes safety checks.
        # See https://bugs.launchpad.net/nova/+bug/2059809 for details.

        # Make sure we have a format inspector for the claimed format, else
        # it is something we do not support and must reject. AMI is excluded.
        if (disk_format not in ami_formats and
                not format_inspector.get_inspector(disk_format)):
            raise exception.ImageUnacceptable(
                image_id=image_href,
                reason=_('Image not in a supported format'))

        inspector = format_inspector.detect_file_format(path)
        inspector.safety_check()

        # Images detected as gpt but registered as raw are legacy "whole disk"
        # formats, which we continue to allow for now.
        # AMI formats can be other things, so don't obsess over this
        # requirement for them. Otherwise, make sure our detection agrees
        # with glance.
        if disk_format == 'raw' and str(inspector) == 'gpt':
            LOG.debug('Image %s registered as raw, but detected as gpt',
                      image_href)
        elif disk_format not in ami_formats and str(inspector) != disk_format:
            # If we detected the image as something other than glance claimed,
            # we abort.
            LOG.warning('Image %s expected to be %s but detected as %s',
                        image_href, disk_format, str(inspector))
            raise exception.ImageUnacceptable(
                image_id=image_href,
                reason=_('Image content does not match disk_format'))
    except format_inspector.SafetyCheckFailed as e:
        LOG.error('Image %s failed safety check: %s', image_href, e)
        raise exception.ImageUnacceptable(
            image_id=image_href,
            reason=(_('Image does not pass safety check')))
    except format_inspector.ImageFormatError:
        # If the inspector we chose based on the image's metadata does not
        # think the image is the proper format, we refuse to use it.
        raise exception.ImageUnacceptable(
            image_id=image_href,
            reason=_('Image content does not match disk_format'))
    except Exception:
        raise exception.ImageUnacceptable(
            image_id=image_href,
            reason=_('Image not in a supported format'))
    if disk_format in ('iso',) + ami_formats:
        # ISO or AMI image passed safety check; qemu will treat this as raw
        # from here so return the expected formats it will find.
        disk_format = 'raw'
    return disk_format


def fetch_to_raw(context, image_href, path, trusted_certs=None):
    path_tmp = "%s.part" % path
    fetch(context, image_href, path_tmp, trusted_certs)

    with fileutils.remove_path_on_error(path_tmp):
        if not CONF.workarounds.disable_deep_image_inspection:
            # If we're doing deep inspection, we take the determined format
            # from it.
            img = IMAGE_API.get(context, image_href)
            force_format = do_image_deep_inspection(img, image_href, path_tmp)
        else:
            force_format = None

        # Only run qemu-img after we have done deep inspection (if enabled).
        # If it was not enabled, we will let it detect the format.
        data = qemu_img_info(path_tmp)
        fmt = data.file_format
        if fmt is None:
            raise exception.ImageUnacceptable(
                reason=_("'qemu-img info' parsing failed."),
                image_id=image_href)
        elif force_format is not None and fmt != force_format:
            # Format inspector and qemu-img must agree on the format, else
            # we reject. This will catch VMDK some variants that we don't
            # explicitly support because qemu will identify them as such
            # and we will not.
            LOG.warning('Image %s detected by qemu as %s but we expected %s',
                        image_href, fmt, force_format)
            raise exception.ImageUnacceptable(
                image_id=image_href,
                reason=_('Image content does not match disk_format'))

        backing_file = data.backing_file
        if backing_file is not None:
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=(_("fmt=%(fmt)s backed by: %(backing_file)s") %
                        {'fmt': fmt, 'backing_file': backing_file}))

        try:
            data_file = data.format_specific['data']['data-file']
        except (KeyError, TypeError, AttributeError):
            data_file = None
        if data_file is not None:
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=(_("fmt=%(fmt)s has data-file: %(data_file)s") %
                        {'fmt': fmt, 'data_file': data_file}))

        if fmt == 'vmdk':
            check_vmdk_image(image_href, data)

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
