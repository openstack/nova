# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2010 OpenStack LLC.
# All Rights Reserved.
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


from urlparse import urlparse


from nova import exception
import nova.image.glance
from nova.utils import import_class
from nova import flags


FLAGS = flags.FLAGS


def parse_image_ref(image_ref):
    """Parse an image href into composite parts.

    If the image_ref passed in is an integer, it will
    return (image_ref, None, None), otherwise it will
    return (image_id, host, port)

    :param image_ref: href or id of an image

    """
    if str(image_ref).isdigit():
        return (int(image_ref), None, None)

    o = urlparse(image_ref)
    port = o.port or 80
    host = o.netloc.split(':', 1)[0]
    image_id = int(o.path.split('/')[-1])
    return (image_id, host, port)


def get_default_image_service():
    ImageService = import_class(FLAGS.image_service)
    return ImageService()


def get_image_service(image_ref):
    """Get the proper image_service and id for the given image_ref.

    The image_ref param can be an href of the form
    http://myglanceserver:9292/images/42, or just an int such as 42. If the
    image_ref is an int, then the default image service is returned.

    :param image_ref: image ref/id for an image
    :returns: a tuple of the form (image_service, image_id)

    """
    image_ref = image_ref or 0
    if str(image_ref).isdigit():
        return (get_default_image_service(), int(image_ref))

    try:
        (image_id, host, port) = parse_image_ref(image_ref)
    except:
        raise exception.InvalidImageRef(image_ref=image_ref)
    glance_client = nova.image.glance.GlanceClient(host, port)
    image_service = nova.image.glance.GlanceImageService(glance_client)
    return (image_service, image_id)
