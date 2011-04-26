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

from urlparse import urlparse

import webob

from nova import exception
from nova import flags
from nova import log as logging
from nova import wsgi


LOG = logging.getLogger('nova.api.openstack.common')


FLAGS = flags.FLAGS


XML_NS_V10 = 'http://docs.rackspacecloud.com/servers/api/v1.0'
XML_NS_V11 = 'http://docs.openstack.org/compute/api/v1.1'


def limited(items, request, max_limit=FLAGS.osapi_max_limit):
    """
    Return a slice of items according to requested offset and limit.

    @param items: A sliceable entity
    @param request: `wsgi.Request` possibly containing 'offset' and 'limit'
                    GET variables. 'offset' is where to start in the list,
                    and 'limit' is the maximum number of items to return. If
                    'limit' is not specified, 0, or > max_limit, we default
                    to max_limit. Negative values for either offset or limit
                    will cause exc.HTTPBadRequest() exceptions to be raised.
    @kwarg max_limit: The maximum number of items to return from 'items'
    """
    try:
        offset = int(request.GET.get('offset', 0))
    except ValueError:
        raise webob.exc.HTTPBadRequest(_('offset param must be an integer'))

    try:
        limit = int(request.GET.get('limit', max_limit))
    except ValueError:
        raise webob.exc.HTTPBadRequest(_('limit param must be an integer'))

    if limit < 0:
        raise webob.exc.HTTPBadRequest(_('limit param must be positive'))

    if offset < 0:
        raise webob.exc.HTTPBadRequest(_('offset param must be positive'))

    limit = min(max_limit, limit or max_limit)
    range_end = offset + limit
    return items[offset:range_end]


def limited_by_marker(items, request, max_limit=FLAGS.osapi_max_limit):
    """Return a slice of items according to the requested marker and limit."""

    try:
        marker = int(request.GET.get('marker', 0))
    except ValueError:
        raise webob.exc.HTTPBadRequest(_('marker param must be an integer'))

    try:
        limit = int(request.GET.get('limit', max_limit))
    except ValueError:
        raise webob.exc.HTTPBadRequest(_('limit param must be an integer'))

    if limit < 0:
        raise webob.exc.HTTPBadRequest(_('limit param must be positive'))

    limit = min(max_limit, limit)
    start_index = 0
    if marker:
        start_index = -1
        for i, item in enumerate(items):
            if item['id'] == marker:
                start_index = i + 1
                break
        if start_index < 0:
            raise webob.exc.HTTPBadRequest(_('marker [%s] not found' % marker))
    range_end = start_index + limit
    return items[start_index:range_end]


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
        image_id = image['id']
        try:
            if abs(hash(image_id)) == int(image_hash):
                return image_id
        except ValueError:
            msg = _("Requested image_id has wrong format: %s,"
                    "should have numerical format") % image_id
            LOG.error(msg)
            raise Exception(msg)
    raise exception.ImageNotFound(image_id=image_hash)


def get_id_from_href(href):
    """Return the id portion of a url as an int.

    Given: http://www.foo.com/bar/123?q=4
    Returns: 123

    """
    try:
        return int(urlparse(href).path.split('/')[-1])
    except:
        LOG.debug(_("Error extracting id from href: %s") % href)
        raise webob.exc.HTTPBadRequest(_('could not parse id from href'))


class OpenstackController(wsgi.Controller):
    def get_default_xmlns(self, req):
        # Use V10 by default
        return XML_NS_V10
