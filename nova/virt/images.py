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
from nova.image import glance as glance_image_service
import nova.image
from nova import log as logging
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.virt.images')


def fetch(context, image_href, path, _user_id, _project_id):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    (image_service, image_id) = nova.image.get_image_service(context,
                                                             image_href)
    with open(path, "wb") as image_file:
        metadata = image_service.get(context, image_id, image_file)
    return metadata


def fetch_to_raw(context, image_href, path, user_id, project_id):
    path_tmp = "%s.part" % path
    metadata = fetch(context, image_href, path_tmp, user_id, project_id)

    def _qemu_img_info(path):

        out, err = utils.execute('env', 'LC_ALL=C', 'LANG=C',
            'qemu-img', 'info', path)

        # output of qemu-img is 'field: value'
        # the fields of interest are 'file format' and 'backing file'
        data = {}
        for line in out.splitlines():
            (field, val) = line.split(':', 1)
            if val[0] == " ":
                val = val[1:]
            data[field] = val

        return(data)

    data = _qemu_img_info(path_tmp)

    fmt = data.get("file format", None)
    if fmt == None:
        os.unlink(path_tmp)
        raise exception.ImageUnacceptable(
            reason=_("'qemu-img info' parsing failed."), image_id=image_href)

    if fmt != "raw":
        staged = "%s.converted" % path
        if "backing file" in data:
            backing_file = data['backing file']
            os.unlink(path_tmp)
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=_("fmt=%(fmt)s backed by: %(backing_file)s") % locals())

        LOG.debug("%s was %s, converting to raw" % (image_href, fmt))
        out, err = utils.execute('qemu-img', 'convert', '-O', 'raw',
                                 path_tmp, staged)
        os.unlink(path_tmp)

        data = _qemu_img_info(staged)
        if data.get('file format', None) != "raw":
            os.unlink(staged)
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=_("Converted to raw, but format is now %s") %
                data.get('file format', None))

        os.rename(staged, path)

    else:
        os.rename(path_tmp, path)

    return metadata
