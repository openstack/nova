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

import glanceclient
import glanceclient.exc

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
    use_ssl = (o.scheme == 'https')
    return (image_id, host, port, use_ssl)


def _create_glance_client(context, host, port, use_ssl, version=1):
    """Instantiate a new glanceclient.Client object"""
    if use_ssl:
        scheme = 'https'
    else:
        scheme = 'http'
    params = {}
    params['insecure'] = FLAGS.glance_api_insecure
    if FLAGS.auth_strategy == 'keystone':
        params['token'] = context.auth_token
    endpoint = '%s://%s:%s' % (scheme, host, port)
    return glanceclient.Client(str(version), endpoint, **params)


def get_api_servers():
    """
    Shuffle a list of FLAGS.glance_api_servers and return an iterator
    that will cycle through the list, looping around to the beginning
    if necessary.
    """
    api_servers = []
    for api_server in FLAGS.glance_api_servers:
        if '//' not in api_server:
            api_server = 'http://' + api_server
        o = urlparse.urlparse(api_server)
        port = o.port or 80
        host = o.netloc.split(':', 1)[0]
        use_ssl = (o.scheme == 'https')
        api_servers.append((host, port, use_ssl))
    random.shuffle(api_servers)
    return itertools.cycle(api_servers)


class GlanceClientWrapper(object):
    """Glance client wrapper class that implements retries."""

    def __init__(self, context=None, host=None, port=None, use_ssl=False,
                 version=1):
        if host is not None:
            self.client = self._create_static_client(context,
                                                     host, port,
                                                     use_ssl, version)
        else:
            self.client = None
        self.api_servers = None

    def _create_static_client(self, context, host, port, use_ssl, version):
        """Create a client that we'll use for every call."""
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.version = version
        return _create_glance_client(context,
                                     self.host, self.port,
                                     self.use_ssl, self.version)

    def _create_onetime_client(self, context, version):
        """Create a client that will be used for one call."""
        if self.api_servers is None:
            self.api_servers = get_api_servers()
        self.host, self.port, self.use_ssl = self.api_servers.next()
        return _create_glance_client(context,
                                     self.host, self.port,
                                     self.use_ssl, version)

    def call(self, context, version, method, *args, **kwargs):
        """
        Call a glance client method.  If we get a connection error,
        retry the request according to FLAGS.glance_num_retries.
        """
        retry_excs = (glanceclient.exc.ServiceUnavailable,
                glanceclient.exc.InvalidEndpoint,
                glanceclient.exc.CommunicationError)
        num_attempts = 1 + FLAGS.glance_num_retries

        for attempt in xrange(1, num_attempts + 1):
            client = self.client or self._create_onetime_client(context,
                                                                version)
            try:
                return getattr(client.images, method)(*args, **kwargs)
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
        try:
            images = self._client.call(context, 1, 'list', **params)
        except Exception:
            _reraise_translated_exception()

        _images = []
        for image in images:
            if self._is_image_available(context, image):
                _images.append(self._translate_from_glance(image))

        return _images

    def _extract_query_params(self, params):
        _params = {}
        accepted_params = ('filters', 'marker', 'limit',
                           'sort_key', 'sort_dir')
        for param in accepted_params:
            if param in params:
                _params[param] = params.get(param)

        # ensure filters is a dict
        _params.setdefault('filters', {})
        # NOTE(vish): don't filter out private images
        _params['filters'].setdefault('is_public', 'none')

        return _params

    def show(self, context, image_id):
        """Returns a dict with image data for the given opaque image id."""
        try:
            image = self._client.call(context, 1, 'get', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if not self._is_image_available(context, image):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = self._translate_from_glance(image)
        return base_image_meta

    def get_location(self, context, image_id):
        """Returns the direct url representing the backend storage location,
        or None if this attribute is not shown by Glance."""
        try:
            client = GlanceClientWrapper()
            image_meta = client.call(context, 2, 'get', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if not self._is_image_available(context, image_meta):
            raise exception.ImageNotFound(image_id=image_id)

        return getattr(image_meta, 'direct_url', None)

    def download(self, context, image_id, data):
        """Calls out to Glance for metadata and data and writes data."""
        try:
            image_chunks = self._client.call(context, 1, 'data', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        for chunk in image_chunks:
            data.write(chunk)

    def create(self, context, image_meta, data=None):
        """Store the image data and return the new image object."""
        sent_service_image_meta = self._translate_to_glance(image_meta)

        if data:
            sent_service_image_meta['data'] = data

        recv_service_image_meta = self._client.call(context, 1, 'create',
                                                    **sent_service_image_meta)

        return self._translate_from_glance(recv_service_image_meta)

    def update(self, context, image_id, image_meta, data=None,
            purge_props=True):
        """Modify the given image with the new data."""
        image_meta = self._translate_to_glance(image_meta)
        image_meta['purge_props'] = purge_props
        #NOTE(bcwaldon): id is not an editable field, but it is likely to be
        # passed in by calling code. Let's be nice and ignore it.
        image_meta.pop('id', None)
        if data:
            image_meta['data'] = data
        try:
            image_meta = self._client.call(context, 1, 'update',
                                           image_id, **image_meta)
        except Exception:
            _reraise_translated_image_exception(image_id)
        else:
            return self._translate_from_glance(image_meta)

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.
        :raises: NotAuthorized if the user is not an owner.

        """
        try:
            self._client.call(context, 1, 'delete', image_id)
        except glanceclient.exc.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        return True

    @staticmethod
    def _translate_to_glance(image_meta):
        image_meta = _convert_to_string(image_meta)
        image_meta = _remove_read_only(image_meta)
        return image_meta

    @staticmethod
    def _translate_from_glance(image):
        image_meta = _extract_attributes(image)
        image_meta = _convert_timestamps_to_datetimes(image_meta)
        image_meta = _convert_from_string(image_meta)
        return image_meta

    @staticmethod
    def _is_image_available(context, image):
        """Check image availability.

        This check is needed in case Nova and Glance are deployed
        without authentication turned on.
        """
        # The presence of an auth token implies this is an authenticated
        # request and we need not handle the noauth use-case.
        if hasattr(context, 'auth_token') and context.auth_token:
            return True

        if image.is_public or context.is_admin:
            return True

        properties = image.properties

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


def _extract_attributes(image):
    IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                        'container_format', 'checksum', 'id',
                        'name', 'created_at', 'updated_at',
                        'deleted_at', 'deleted', 'status',
                        'min_disk', 'min_ram', 'is_public']
    output = {}
    for attr in IMAGE_ATTRIBUTES:
        output[attr] = getattr(image, attr, None)

    output['properties'] = getattr(image, 'properties', {})

    return output


def _remove_read_only(image_meta):
    IMAGE_ATTRIBUTES = ['status', 'updated_at', 'created_at', 'deleted_at']
    output = copy.deepcopy(image_meta)
    for attr in IMAGE_ATTRIBUTES:
        if attr in output:
            del output[attr]
    return output


def _reraise_translated_image_exception(image_id):
    """Transform the exception for the image but keep its traceback intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_image_exception(image_id, exc_value)
    raise new_exc, None, exc_trace


def _reraise_translated_exception():
    """Transform the exception but keep its traceback intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_plain_exception(exc_value)
    raise new_exc, None, exc_trace


def _translate_image_exception(image_id, exc_value):
    if isinstance(exc_value, (glanceclient.exc.Forbidden,
                    glanceclient.exc.Unauthorized)):
        return exception.ImageNotAuthorized(image_id=image_id)
    if isinstance(exc_value, glanceclient.exc.NotFound):
        return exception.ImageNotFound(image_id=image_id)
    if isinstance(exc_value, glanceclient.exc.BadRequest):
        return exception.Invalid(exc_value)
    return exc_value


def _translate_plain_exception(exc_value):
    if isinstance(exc_value, (glanceclient.exc.Forbidden,
                    glanceclient.exc.Unauthorized)):
        return exception.NotAuthorized(exc_value)
    if isinstance(exc_value, glanceclient.exc.NotFound):
        return exception.NotFound(exc_value)
    if isinstance(exc_value, glanceclient.exc.BadRequest):
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
        (image_id, glance_host, glance_port, use_ssl) = \
            _parse_image_ref(image_href)
        glance_client = GlanceClientWrapper(context=context,
                host=glance_host, port=glance_port, use_ssl=use_ssl)
    except ValueError:
        raise exception.InvalidImageRef(image_href=image_href)

    image_service = GlanceImageService(client=glance_client)
    return image_service, image_id


def get_default_image_service():
    return GlanceImageService()
