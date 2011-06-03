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

from nova import context
from nova import flags
import nova.image
from nova import log as logging
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.virt.images')


def fetch(image_href, path, _user, _project):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    (image_service, image_id) = nova.image.get_image_service(image_href)
    with open(path, "wb") as image_file:
        elevated = context.get_admin_context()
        metadata = image_service.get(elevated, image_id, image_file)
    return metadata


# TODO(vish): xenapi should use the glance client code directly instead
#             of retrieving the image using this method.
def image_url(image):
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        return "http://%s:%s/images/%s" % (FLAGS.glance_host,
            FLAGS.glance_port, image)
    return "http://%s:%s/_images/%s/image" % (FLAGS.s3_host, FLAGS.s3_port,
                                              image)
