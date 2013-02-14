# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import exception
from nova import flags
from nova.image import glance
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils


LOG = logging.getLogger(__name__)

image_opts = [
    cfg.BoolOpt('force_raw_images',
                default=True,
                help='Force backing images to raw format'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(image_opts)


def qemu_img_info(path):
    """Return a dict containing the parsed output from qemu-img info."""

    out, err = utils.execute('env', 'LC_ALL=C', 'LANG=C',
                             'qemu-img', 'info', path)

    # output of qemu-img is 'field: value'
    # except when its in the snapshot listing mode
    data = {}
    for line in out.splitlines():
        pieces = line.split(':', 1)
        if len(pieces) != 2:
            continue
        (field, val) = pieces
        field = field.strip().lower()
        val = val.strip()
        if field == 'snapshot list':
            # Skip everything after the snapshot list
            # which is safe to do since the code prints
            # these out at the end and nobody currently
            # uses this information in openstack as-is.
            break
        data[field] = val

    return data


def fetch(context, image_href, path, _user_id, _project_id):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    (image_service, image_id) = glance.get_remote_image_service(context,
                                                                image_href)
    with utils.remove_path_on_error(path):
        with open(path, "wb") as image_file:
            image_service.download(context, image_id, image_file)


def fetch_to_raw(context, image_href, path, user_id, project_id):
    path_tmp = "%s.part" % path
    fetch(context, image_href, path_tmp, user_id, project_id)

    with utils.remove_path_on_error(path_tmp):
        data = qemu_img_info(path_tmp)

        fmt = data.get('file format')
        if fmt is None:
            raise exception.ImageUnacceptable(
                reason=_("'qemu-img info' parsing failed."),
                image_id=image_href)

        backing_file = data.get('backing file')
        if backing_file is not None:
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=_("fmt=%(fmt)s backed by: %(backing_file)s") % locals())

        if fmt != "raw" and FLAGS.force_raw_images:
            staged = "%s.converted" % path
            LOG.debug("%s was %s, converting to raw" % (image_href, fmt))
            with utils.remove_path_on_error(staged):
                utils.execute('qemu-img', 'convert', '-O', 'raw', path_tmp,
                              staged)
                os.unlink(path_tmp)

                data = qemu_img_info(staged)
                if data.get('file format') != "raw":
                    raise exception.ImageUnacceptable(image_id=image_href,
                        reason=_("Converted to raw, but format is now %s") %
                        data.get('file format'))

                os.rename(staged, path)
        else:
            os.rename(path_tmp, path)
