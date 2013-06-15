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

import functools
import os

from oslo.config import cfg

from nova import exception
from nova.openstack.common import fileutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import imageutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import imagehandler

LOG = logging.getLogger(__name__)

image_opts = [
    cfg.BoolOpt('force_raw_images',
                default=True,
                help='Force backing images to raw format'),
]

CONF = cfg.CONF
CONF.register_opts(image_opts)


def qemu_img_info(path):
    """Return an object containing the parsed output from qemu-img info."""
    # TODO(mikal): this code should not be referring to a libvirt specific
    # flag.
    if not os.path.exists(path) and CONF.libvirt.images_type != 'rbd':
        return imageutils.QemuImgInfo()

    out, err = utils.execute('env', 'LC_ALL=C', 'LANG=C',
                             'qemu-img', 'info', path)
    return imageutils.QemuImgInfo(out)


def convert_image(source, dest, out_format, run_as_root=False):
    """Convert image to other format."""
    cmd = ('qemu-img', 'convert', '-O', out_format, source, dest)
    utils.execute(*cmd, run_as_root=run_as_root)


def _remove_image_on_exec(context, image_href, user_id, project_id,
                          imagehandler_args, image_path):
    for handler, loc, image_meta in imagehandler.handle_image(context,
                                                              image_href,
                                                              user_id,
                                                              project_id,
                                                              image_path):
        # The loop will stop when the handle function returns success.
        handler.remove_image(context, image_href, image_meta, image_path,
                             user_id, project_id, loc, **imagehandler_args)
    fileutils.delete_if_exists(image_path)


def fetch(context, image_href, path, _user_id, _project_id,
          max_size=0, imagehandler_args=None):
    """Fetch image and returns whether the image was stored locally."""
    imagehandler_args = imagehandler_args or {}
    _remove_image_fun = functools.partial(_remove_image_on_exec,
                                          context, image_href,
                                          _user_id, _project_id,
                                          imagehandler_args)

    fetched_to_local = True
    with fileutils.remove_path_on_error(path, remove=_remove_image_fun):
        for handler, loc, image_meta in imagehandler.handle_image(context,
                                                                  image_href,
                                                                  _user_id,
                                                                  _project_id,
                                                                  path):
            # The loop will stop when the handle function returns success.
            handler.fetch_image(context, image_href, image_meta, path,
                                _user_id, _project_id, loc,
                                **imagehandler_args)
            fetched_to_local = handler.is_local()
    return fetched_to_local


def fetch_to_raw(context, image_href, path, user_id, project_id,
                 max_size=0, imagehandler_args=None):
    path_tmp = "%s.part" % path
    fetched_to_local = fetch(context, image_href, path_tmp,
                             user_id, project_id,
                             max_size=max_size,
                             imagehandler_args=imagehandler_args)

    if not fetched_to_local:
        return

    imagehandler_args = imagehandler_args or {}
    _remove_image_fun = functools.partial(_remove_image_on_exec,
                                          context, image_href,
                                          user_id, project_id,
                                          imagehandler_args)

    with fileutils.remove_path_on_error(path_tmp, remove=_remove_image_fun):
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

        # We can't generally shrink incoming images, so disallow
        # images > size of the flavor we're booting.  Checking here avoids
        # an immediate DoS where we convert large qcow images to raw
        # (which may compress well but not be sparse).
        # TODO(p-draigbrady): loop through all flavor sizes, so that
        # we might continue here and not discard the download.
        # If we did that we'd have to do the higher level size checks
        # irrespective of whether the base image was prepared or not.
        disk_size = data.virtual_size
        if max_size and max_size < disk_size:
            msg = _('%(base)s virtual size %(disk_size)s '
                    'larger than flavor root disk size %(size)s')
            LOG.error(msg % {'base': path,
                             'disk_size': disk_size,
                             'size': max_size})
            raise exception.FlavorDiskTooSmall()

        if fmt != "raw" and CONF.force_raw_images:
            staged = "%s.converted" % path
            LOG.debug("%s was %s, converting to raw" % (image_href, fmt))

            with fileutils.remove_path_on_error(staged):
                convert_image(path_tmp, staged, 'raw')

                data = qemu_img_info(staged)
                if data.file_format != "raw":
                    raise exception.ImageUnacceptable(image_id=image_href,
                        reason=_("Converted to raw, but format is now %s") %
                        data.file_format)

                for handler_context in imagehandler.handle_image(context,
                                                                 image_href,
                                                                 user_id,
                                                                 project_id,
                                                                 staged):
                    (handler, loc, image_meta) = handler_context
                    # The loop will stop when the handle function
                    # return success.
                    handler.move_image(context, image_href, image_meta,
                                       staged, path,
                                       user_id, project_id, loc,
                                       **imagehandler_args)

                for handler_context in imagehandler.handle_image(context,
                                                                 image_href,
                                                                 user_id,
                                                                 project_id,
                                                                 path_tmp):
                    (handler, loc, image_meta) = handler_context
                    handler.remove_image(context, image_href, image_meta,
                                         path_tmp, user_id, project_id, loc,
                                         **imagehandler_args)
        else:
            for handler_context in imagehandler.handle_image(context,
                                                             image_href,
                                                             user_id,
                                                             project_id,
                                                             path_tmp):
                (handler, loc, image_meta) = handler_context
                handler.move_image(context, image_href, image_meta,
                                   path_tmp, path,
                                   user_id, project_id, loc,
                                   **imagehandler_args)
