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

"""Implementation of an image service that uses Glance as the backend"""

from __future__ import absolute_import

import copy
import itertools
import random
import sys
import time
import urlparse

import glance.client
from glance.common import exception as glance_exception

from nova import exception
from nova import flags
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


def _parse_image_ref(image_href):
    """Parse an image href into composite parts.

    :param image_href: href of an image
    :returns: a tuple of the form (image_id, host, port)
    :raises ValueError

    """
    o = urlparse.urlparse(image_href)
    port = o.port or 80
    host = o.netloc.split(':', 1)[0]
    image_id = o.path.split('/')[-1]
    return (image_id, host, port)


def _create_glance_client(context, host, port):
    params = {}
    if FLAGS.auth_strategy == 'keystone':
        params['creds'] = {
            'strategy': 'keystone',
            'username': context.user_id,
            'tenant': context.project_id,
        }
        params['auth_tok'] = context.auth_token

    return glance.client.Client(host, port, **params)


def get_api_servers():
    """
    Shuffle a list of FLAGS.glance_api_servers and return an iterator
    that will cycle through the list, looping around to the beginning
    if necessary.
    """
    api_servers = []
    for api_server in FLAGS.glance_api_servers:
        host, port_str = api_server.split(':')
        api_servers.append((host, int(port_str)))
    random.shuffle(api_servers)
    return itertools.cycle(api_servers)


class GlanceClientWrapper(object):
    """Glance client wrapper class that implements retries."""

    def __init__(self, context=None, host=None, port=None):
        if host is not None:
            self.client = self._create_static_client(context, host, port)
        else:
            self.client = None
        self.api_servers = None

    def _create_static_client(self, context, host, port):
        """Create a client that we'll use for every call."""
        self.host = host
        self.port = port
        return _create_glance_client(context, self.host, self.port)

    def _create_onetime_client(self, context):
        """Create a client that will be used for one call."""
        if self.api_servers is None:
            self.api_servers = get_api_servers()
        self.host, self.port = self.api_servers.next()
        return _create_glance_client(context, self.host, self.port)

    def call(self, context, method, *args, **kwargs):
        """
        Call a glance client method.  If we get a connection error,
        retry the request according to FLAGS.glance_num_retries.
        """
        retry_excs = (glance_exception.ClientConnectionError,
                glance_exception.ServiceUnavailable)

        num_attempts = 1 + FLAGS.glance_num_retries

        for attempt in xrange(1, num_attempts + 1):
            client = self.client or self._create_onetime_client(context)
            try:
                return getattr(client, method)(*args, **kwargs)
            except retry_excs as e:
                host = self.host
                port = self.port
                extra = "retrying"
                error_msg = _("Error contacting glance server "
                        "'%(host)s:%(port)s' for '%(method)s', %(extra)s.")
                if attempt == num_attempts:
                    extra = 'done trying'
                    LOG.exception(error_msg, locals())
                    raise exception.GlanceConnectionFailed(
                            host=host, port=port, reason=str(e))
                LOG.exception(error_msg, locals())
                time.sleep(1)


class GlanceImageService(object):
    """Provides storage and retrieval of disk image objects within Glance."""

    def __init__(self, client=None):
        self._client = client or GlanceClientWrapper()

    def detail(self, context, **kwargs):
        """Calls out to Glance for a list of detailed image information."""
        params = self._extract_query_params(kwargs)
        image_metas = self._get_images(context, **params)

        images = []
        for image_meta in image_metas:
            if self._is_image_available(context, image_meta):
                base_image_meta = self._translate_from_glance(image_meta)
                images.append(base_image_meta)
        return images

    def _extract_query_params(self, params):
        _params = {}
        accepted_params = ('filters', 'marker', 'limit',
                           'sort_key', 'sort_dir')
        for param in accepted_params:
            if param in params:
                _params[param] = params.get(param)
        return _params

    def _get_images(self, context, **kwargs):
        """Get image entitites from images service"""
        # ensure filters is a dict
        kwargs['filters'] = kwargs.get('filters') or {}
        # NOTE(vish): don't filter out private images
        kwargs['filters'].setdefault('is_public', 'none')

        return self._fetch_images(context, 'get_images_detailed', **kwargs)

    def _fetch_images(self, context, fetch_method, **kwargs):
        """Paginate through results from glance server"""
        try:
            images = self._client.call(context, fetch_method, **kwargs)
        except Exception:
            _reraise_translated_exception()

        if not images:
            # break out of recursive loop to end pagination
            return

        for image in images:
            yield image

        try:
            # attempt to advance the marker in order to fetch next page
            kwargs['marker'] = images[-1]['id']
        except KeyError:
            raise exception.ImagePaginationFailed()

        try:
            kwargs['limit'] = kwargs['limit'] - len(images)
            # break if we have reached a provided limit
            if kwargs['limit'] <= 0:
                return
        except KeyError:
            # ignore missing limit, just proceed without it
            pass

        for image in self._fetch_images(context, fetch_method, **kwargs):
            yield image

    def show(self, context, image_id):
        """Returns a dict with image data for the given opaque image id."""
        try:
            image_meta = self._client.call(context, 'get_image_meta',
                    image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if not self._is_image_available(context, image_meta):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = self._translate_from_glance(image_meta)
        return base_image_meta

    def download(self, context, image_id, data):
        """Calls out to Glance for metadata and data and writes data."""
        try:
            image_meta, image_chunks = self._client.call(context,
                    'get_image', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        for chunk in image_chunks:
            data.write(chunk)

    def create(self, context, image_meta, data=None):
        """Store the image data and return the new image id.

        :raises: AlreadyExists if the image already exist.

        """
        sent_service_image_meta = self._translate_to_glance(image_meta)
        recv_service_image_meta = self._client.call(context,
                'add_image', sent_service_image_meta, data)
        base_image_meta = self._translate_from_glance(recv_service_image_meta)
        return base_image_meta

    def update(self, context, image_id, image_meta, data=None, features=None):
        """Replace the contents of the given image with the new data.

        :raises: ImageNotFound if the image does not exist.

        """
        # NOTE(vish): show is to check if image is available
        self.show(context, image_id)
        image_meta = self._translate_to_glance(image_meta)
        try:
            image_meta = self._client.call(context, 'update_image',
                    image_id, image_meta, data, features)
        except Exception:
            _reraise_translated_image_exception(image_id)

        base_image_meta = self._translate_from_glance(image_meta)
        return base_image_meta

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.
        :raises: NotAuthorized if the user is not an owner.

        """
        # NOTE(vish): show is to check if image is available
        self.show(context, image_id)
        try:
            result = self._client.call(context, 'delete_image', image_id)
        except glance_exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        return result

    @staticmethod
    def _translate_to_glance(image_meta):
        image_meta = _convert_to_string(image_meta)
        image_meta = _remove_read_only(image_meta)
        return image_meta

    @staticmethod
    def _translate_from_glance(image_meta):
        image_meta = _limit_attributes(image_meta)
        image_meta = _convert_timestamps_to_datetimes(image_meta)
        image_meta = _convert_from_string(image_meta)
        return image_meta

    @staticmethod
    def _is_image_available(context, image_meta):
        """Check image availability.

        This check is needed in case Nova and Glance are deployed
        without authentication turned on.
        """
        # The presence of an auth token implies this is an authenticated
        # request and we need not handle the noauth use-case.
        if hasattr(context, 'auth_token') and context.auth_token:
            return True

        if image_meta['is_public'] or context.is_admin:
            return True

        properties = image_meta['properties']

        if context.project_id and ('owner_id' in properties):
            return str(properties['owner_id']) == str(context.project_id)

        if context.project_id and ('project_id' in properties):
            return str(properties['project_id']) == str(context.project_id)

        try:
            user_id = properties['user_id']
        except KeyError:
            return False

        return str(user_id) == str(context.user_id)


def _convert_timestamps_to_datetimes(image_meta):
    """Returns image with timestamp fields converted to datetime objects."""
    for attr in ['created_at', 'updated_at', 'deleted_at']:
        if image_meta.get(attr):
            image_meta[attr] = timeutils.parse_isotime(image_meta[attr])
    return image_meta


# NOTE(bcwaldon): used to store non-string data in glance metadata
def _json_loads(properties, attr):
    prop = properties[attr]
    if isinstance(prop, basestring):
        properties[attr] = jsonutils.loads(prop)


def _json_dumps(properties, attr):
    prop = properties[attr]
    if not isinstance(prop, basestring):
        properties[attr] = jsonutils.dumps(prop)


_CONVERT_PROPS = ('block_device_mapping', 'mappings')


def _convert(method, metadata):
    metadata = copy.deepcopy(metadata)
    properties = metadata.get('properties')
    if properties:
        for attr in _CONVERT_PROPS:
            if attr in properties:
                method(properties, attr)

    return metadata


def _convert_from_string(metadata):
    return _convert(_json_loads, metadata)


def _convert_to_string(metadata):
    return _convert(_json_dumps, metadata)


def _limit_attributes(image_meta):
    IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                        'container_format', 'checksum', 'id',
                        'name', 'created_at', 'updated_at',
                        'deleted_at', 'deleted', 'status',
                        'min_disk', 'min_ram', 'is_public']
    output = {}
    for attr in IMAGE_ATTRIBUTES:
        output[attr] = image_meta.get(attr)

    output['properties'] = image_meta.get('properties', {})

    return output


def _remove_read_only(image_meta):
    IMAGE_ATTRIBUTES = ['updated_at', 'created_at', 'deleted_at']
    output = copy.deepcopy(image_meta)
    for attr in IMAGE_ATTRIBUTES:
        if attr in output:
            del output[attr]
    return output


def _reraise_translated_image_exception(image_id):
    """Transform the exception for the image but keep its traceback intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_image_exception(image_id, exc_type, exc_value)
    raise new_exc, None, exc_trace


def _reraise_translated_exception():
    """Transform the exception but keep its traceback intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_plain_exception(exc_type, exc_value)
    raise new_exc, None, exc_trace


def _translate_image_exception(image_id, exc_type, exc_value):
    if exc_type in (glance_exception.Forbidden,
                    glance_exception.NotAuthenticated,
                    glance_exception.MissingCredentialError):
        return exception.ImageNotAuthorized(image_id=image_id)
    if exc_type is glance_exception.NotFound:
        return exception.ImageNotFound(image_id=image_id)
    if exc_type is glance_exception.Invalid:
        return exception.Invalid(exc_value)
    return exc_value


def _translate_plain_exception(exc_type, exc_value):
    if exc_type in (glance_exception.Forbidden,
                    glance_exception.NotAuthenticated,
                    glance_exception.MissingCredentialError):
        return exception.NotAuthorized(exc_value)
    if exc_type is glance_exception.NotFound:
        return exception.NotFound(exc_value)
    if exc_type is glance_exception.Invalid:
        return exception.Invalid(exc_value)
    return exc_value


def get_remote_image_service(context, image_href):
    """Create an image_service and parse the id from the given image_href.

    The image_href param can be an href of the form
    'http://example.com:9292/v1/images/b8b2c6f7-7345-4e2f-afa2-eedaba9cbbe3',
    or just an id such as 'b8b2c6f7-7345-4e2f-afa2-eedaba9cbbe3'. If the
    image_href is a standalone id, then the default image service is returned.

    :param image_href: href that describes the location of an image
    :returns: a tuple of the form (image_service, image_id)

    """
    #NOTE(bcwaldon): If image_href doesn't look like a URI, assume its a
    # standalone image ID
    if '/' not in str(image_href):
        image_service = get_default_image_service()
        return image_service, image_href

    try:
        (image_id, glance_host, glance_port) = _parse_image_ref(image_href)
        glance_client = GlanceClientWrapper(context=context,
                host=glance_host, port=glance_port)
    except ValueError:
        raise exception.InvalidImageRef(image_href=image_href)

    image_service = GlanceImageService(client=glance_client)
    return image_service, image_id


def get_default_image_service():
    return GlanceImageService()
