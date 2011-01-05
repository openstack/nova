# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import exception


def limited(items, req):
    """Return a slice of items according to requested offset and limit.

    items - a sliceable
    req - wobob.Request possibly containing offset and limit GET variables.
          offset is where to start in the list, and limit is the maximum number
          of items to return.

    If limit is not specified, 0, or > 1000, defaults to 1000.
    """

    offset = int(req.GET.get('offset', 0))
    limit = int(req.GET.get('limit', 0))
    if not limit:
        limit = 1000
    limit = min(1000, limit)
    range_end = offset + limit
    return items[offset:range_end]


def get_image_id_from_image_hash(image_service, context, image_hash):
    """Given an Image ID Hash, return an objectstore Image ID.

    image_service - reference to objectstore compatible image service.
    context - security context for image service requests.
    image_hash - hash of the image ID.
    """

    # FIX(sandy): This is terribly inefficient. It pulls all images
    # from objectstore in order to find the match. ObjectStore
    # should have a numeric counterpart to the string ID.
    try:
        items = image_service.detail(context)
    except NotImplementedError:
        items = image_service.index(context)
    for image in items:
        image_id = image['imageId']
        if abs(hash(image_id)) == int(image_hash):
            return image_id
    raise exception.NotFound(image_hash)
