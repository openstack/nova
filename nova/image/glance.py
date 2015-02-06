# Copyright 2010 OpenStack Foundation
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

"""Implementation of an image service that uses Glance as the backend."""

from __future__ import absolute_import

import copy
import itertools
import random
import sys
import time

import glanceclient
import glanceclient.exc
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import netutils
from oslo_utils import timeutils
import six
import six.moves.urllib.parse as urlparse

from nova import exception
from nova.i18n import _, _LE
import nova.image.download as image_xfers
from nova.openstack.common import log as logging


glance_opts = [
    cfg.StrOpt('host',
               default='$my_ip',
               help='Default glance hostname or IP address'),
    cfg.IntOpt('port',
               default=9292,
               help='Default glance port'),
    cfg.StrOpt('protocol',
                default='http',
                help='Default protocol to use when connecting to glance. '
                     'Set to https for SSL.'),
    cfg.ListOpt('api_servers',
                help='A list of the glance api servers available to nova. '
                     'Prefix with https:// for ssl-based glance api servers. '
                     '([hostname|ip]:port)'),
    cfg.BoolOpt('api_insecure',
                default=False,
                help='Allow to perform insecure SSL (https) requests to '
                     'glance'),
    cfg.IntOpt('num_retries',
               default=0,
               help='Number of retries when uploading / downloading an image '
                    'to / from glance.'),
    cfg.ListOpt('allowed_direct_url_schemes',
                default=[],
                help='A list of url scheme that can be downloaded directly '
                     'via the direct_url.  Currently supported schemes: '
                     '[file].'),
    ]

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.register_opts(glance_opts, 'glance')
CONF.import_opt('auth_strategy', 'nova.api.auth')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_group('ssl', 'nova.openstack.common.sslutils')


def generate_glance_url():
    """Generate the URL to glance."""
    glance_host = CONF.glance.host
    if netutils.is_valid_ipv6(glance_host):
        glance_host = '[%s]' % glance_host
    return "%s://%s:%d" % (CONF.glance.protocol, glance_host,
                           CONF.glance.port)


def generate_image_url(image_ref):
    """Generate an image URL from an image_ref."""
    return "%s/images/%s" % (generate_glance_url(), image_ref)


def _parse_image_ref(image_href):
    """Parse an image href into composite parts.

    :param image_href: href of an image
    :returns: a tuple of the form (image_id, host, port)
    :raises ValueError

    """
    o = urlparse.urlparse(image_href)
    port = o.port or 80
    host = o.netloc.rsplit(':', 1)[0]
    image_id = o.path.split('/')[-1]
    use_ssl = (o.scheme == 'https')
    return (image_id, host, port, use_ssl)


def generate_identity_headers(context, status='Confirmed'):
    return {
        'X-Auth-Token': getattr(context, 'auth_token', None),
        'X-User-Id': getattr(context, 'user', None),
        'X-Tenant-Id': getattr(context, 'tenant', None),
        'X-Roles': ','.join(context.roles),
        'X-Identity-Status': status,
        'X-Service-Catalog': jsonutils.dumps(context.service_catalog),
    }


def _create_glance_client(context, host, port, use_ssl, version=1):
    """Instantiate a new glanceclient.Client object."""
    params = {}
    if use_ssl:
        scheme = 'https'
        # https specific params
        params['insecure'] = CONF.glance.api_insecure
        params['ssl_compression'] = False
        if CONF.ssl.cert_file:
            params['cert_file'] = CONF.ssl.cert_file
        if CONF.ssl.key_file:
            params['key_file'] = CONF.ssl.key_file
        if CONF.ssl.ca_file:
            params['cacert'] = CONF.ssl.ca_file
    else:
        scheme = 'http'

    if CONF.auth_strategy == 'keystone':
        # NOTE(isethi): Glanceclient <= 0.9.0.49 accepts only
        # keyword 'token', but later versions accept both the
        # header 'X-Auth-Token' and 'token'
        params['token'] = context.auth_token
        params['identity_headers'] = generate_identity_headers(context)
    if netutils.is_valid_ipv6(host):
        # if so, it is ipv6 address, need to wrap it with '[]'
        host = '[%s]' % host
    endpoint = '%s://%s:%s' % (scheme, host, port)
    return glanceclient.Client(str(version), endpoint, **params)


def get_api_servers():
    """Shuffle a list of CONF.glance.api_servers and return an iterator
    that will cycle through the list, looping around to the beginning
    if necessary.
    """
    api_servers = []

    configured_servers = (['%s:%s' % (CONF.glance.host, CONF.glance.port)]
                          if CONF.glance.api_servers is None
                          else CONF.glance.api_servers)
    for api_server in configured_servers:
        if '//' not in api_server:
            api_server = 'http://' + api_server
        o = urlparse.urlparse(api_server)
        port = o.port or 80
        host = o.netloc.rsplit(':', 1)[0]
        if host[0] == '[' and host[-1] == ']':
            host = host[1:-1]
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
        """Call a glance client method.  If we get a connection error,
        retry the request according to CONF.glance.num_retries.
        """
        retry_excs = (glanceclient.exc.ServiceUnavailable,
                glanceclient.exc.InvalidEndpoint,
                glanceclient.exc.CommunicationError)
        num_attempts = 1 + CONF.glance.num_retries

        for attempt in xrange(1, num_attempts + 1):
            client = self.client or self._create_onetime_client(context,
                                                                version)
            try:
                return getattr(client.images, method)(*args, **kwargs)
            except retry_excs as e:
                host = self.host
                port = self.port

                if attempt < num_attempts:
                    extra = "retrying"
                else:
                    extra = 'done trying'

                error_msg = (_("Error contacting glance server "
                               "'%(host)s:%(port)s' for '%(method)s', "
                               "%(extra)s.") %
                             {'host': host, 'port': port,
                              'method': method, 'extra': extra})
                LOG.exception(error_msg)
                if attempt == num_attempts:
                    raise exception.GlanceConnectionFailed(
                            host=host, port=port, reason=six.text_type(e))
                time.sleep(1)


class GlanceImageService(object):
    """Provides storage and retrieval of disk image objects within Glance."""

    def __init__(self, client=None):
        self._client = client or GlanceClientWrapper()
        # NOTE(jbresnah) build the table of download handlers at the beginning
        # so that operators can catch errors at load time rather than whenever
        # a user attempts to use a module.  Note this cannot be done in glance
        # space when this python module is loaded because the download module
        # may require configuration options to be parsed.
        self._download_handlers = {}
        download_modules = image_xfers.load_transfer_modules()

        for scheme, mod in download_modules.iteritems():
            if scheme not in CONF.glance.allowed_direct_url_schemes:
                continue

            try:
                self._download_handlers[scheme] = mod.get_download_handler()
            except Exception as ex:
                LOG.error(_LE('When loading the module %(module_str)s the '
                              'following error occurred: %(ex)s'),
                          {'module_str': str(mod), 'ex': ex})

    def detail(self, context, **kwargs):
        """Calls out to Glance for a list of detailed image information."""
        params = _extract_query_params(kwargs)
        try:
            images = self._client.call(context, 1, 'list', **params)
        except Exception:
            _reraise_translated_exception()

        _images = []
        for image in images:
            if _is_image_available(context, image):
                _images.append(_translate_from_glance(image))

        return _images

    def show(self, context, image_id, include_locations=False,
             show_deleted=True):
        """Returns a dict with image data for the given opaque image id.

        :param context: The context object to pass to image client
        :param image_id: The UUID of the image
        :param include_locations: (Optional) include locations in the returned
                                  dict of information if the image service API
                                  supports it. If the image service API does
                                  not support the locations attribute, it will
                                  still be included in the returned dict, as an
                                  empty list.
        :param show_deleted: (Optional) show the image even the status of
                             image is deleted.
        """
        version = 1
        if include_locations:
            version = 2
        try:
            image = self._client.call(context, version, 'get', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if not show_deleted and getattr(image, 'deleted', False):
            raise exception.ImageNotFound(image_id=image_id)

        if not _is_image_available(context, image):
            raise exception.ImageNotFound(image_id=image_id)

        image = _translate_from_glance(image,
                                       include_locations=include_locations)
        if include_locations:
            locations = image.get('locations', None) or []
            du = image.get('direct_url', None)
            if du:
                locations.append({'url': du, 'metadata': {}})
            image['locations'] = locations

        return image

    def _get_transfer_module(self, scheme):
        try:
            return self._download_handlers[scheme]
        except KeyError:
            return None
        except Exception:
            LOG.error(_LE("Failed to instantiate the download handler "
                          "for %(scheme)s"), {'scheme': scheme})
        return

    def download(self, context, image_id, data=None, dst_path=None):
        """Calls out to Glance for data and writes data."""
        if CONF.glance.allowed_direct_url_schemes and dst_path is not None:
            image = self.show(context, image_id, include_locations=True)
            for entry in image.get('locations', []):
                loc_url = entry['url']
                loc_meta = entry['metadata']
                o = urlparse.urlparse(loc_url)
                xfer_mod = self._get_transfer_module(o.scheme)
                if xfer_mod:
                    try:
                        xfer_mod.download(context, o, dst_path, loc_meta)
                        msg = _("Successfully transferred "
                                "using %s") % o.scheme
                        LOG.info(msg)
                        return
                    except Exception as ex:
                        LOG.exception(ex)

        try:
            image_chunks = self._client.call(context, 1, 'data', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        close_file = False
        if data is None and dst_path:
            data = open(dst_path, 'wb')
            close_file = True

        if data is None:
            return image_chunks
        else:
            try:
                for chunk in image_chunks:
                    data.write(chunk)
            finally:
                if close_file:
                    data.close()

    def create(self, context, image_meta, data=None):
        """Store the image data and return the new image object."""
        sent_service_image_meta = _translate_to_glance(image_meta)

        if data:
            sent_service_image_meta['data'] = data

        try:
            recv_service_image_meta = self._client.call(
                context, 1, 'create', **sent_service_image_meta)
        except glanceclient.exc.HTTPException:
            _reraise_translated_exception()

        return _translate_from_glance(recv_service_image_meta)

    def update(self, context, image_id, image_meta, data=None,
            purge_props=True):
        """Modify the given image with the new data."""
        image_meta = _translate_to_glance(image_meta)
        image_meta['purge_props'] = purge_props
        # NOTE(bcwaldon): id is not an editable field, but it is likely to be
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
            return _translate_from_glance(image_meta)

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.
        :raises: NotAuthorized if the user is not an owner.
        :raises: ImageNotAuthorized if the user is not authorized.

        """
        try:
            self._client.call(context, 1, 'delete', image_id)
        except glanceclient.exc.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        except glanceclient.exc.HTTPForbidden:
            raise exception.ImageNotAuthorized(image_id=image_id)
        return True


def _extract_query_params(params):
    _params = {}
    accepted_params = ('filters', 'marker', 'limit',
                       'page_size', 'sort_key', 'sort_dir')
    for param in accepted_params:
        if params.get(param):
            _params[param] = params.get(param)

    # ensure filters is a dict
    _params.setdefault('filters', {})
    # NOTE(vish): don't filter out private images
    _params['filters'].setdefault('is_public', 'none')

    return _params


def _is_image_available(context, image):
    """Check image availability.

    This check is needed in case Nova and Glance are deployed
    without authentication turned on.
    """
    # The presence of an auth token implies this is an authenticated
    # request and we need not handle the noauth use-case.
    if hasattr(context, 'auth_token') and context.auth_token:
        return True

    def _is_image_public(image):
        # NOTE(jaypipes) V2 Glance API replaced the is_public attribute
        # with a visibility attribute. We do this here to prevent the
        # glanceclient for a V2 image model from throwing an
        # exception from warlock when trying to access an is_public
        # attribute.
        if hasattr(image, 'visibility'):
            return str(image.visibility).lower() == 'public'
        else:
            return image.is_public

    if context.is_admin or _is_image_public(image):
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


def _translate_to_glance(image_meta):
    image_meta = _convert_to_string(image_meta)
    image_meta = _remove_read_only(image_meta)
    return image_meta


def _translate_from_glance(image, include_locations=False):
    image_meta = _extract_attributes(image,
                                     include_locations=include_locations)
    image_meta = _convert_timestamps_to_datetimes(image_meta)
    image_meta = _convert_from_string(image_meta)
    return image_meta


def _convert_timestamps_to_datetimes(image_meta):
    """Returns image with timestamp fields converted to datetime objects."""
    for attr in ['created_at', 'updated_at', 'deleted_at']:
        if image_meta.get(attr):
            image_meta[attr] = timeutils.parse_isotime(image_meta[attr])
    return image_meta


# NOTE(bcwaldon): used to store non-string data in glance metadata
def _json_loads(properties, attr):
    prop = properties[attr]
    if isinstance(prop, six.string_types):
        properties[attr] = jsonutils.loads(prop)


def _json_dumps(properties, attr):
    prop = properties[attr]
    if not isinstance(prop, six.string_types):
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


def _extract_attributes(image, include_locations=False):
    # NOTE(hdd): If a key is not found, base.Resource.__getattr__() may perform
    # a get(), resulting in a useless request back to glance. This list is
    # therefore sorted, with dependent attributes as the end
    # 'deleted_at' depends on 'deleted'
    # 'checksum' depends on 'status' == 'active'
    IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                        'container_format', 'status', 'id',
                        'name', 'created_at', 'updated_at',
                        'deleted', 'deleted_at', 'checksum',
                        'min_disk', 'min_ram', 'is_public',
                        'direct_url', 'locations']

    queued = getattr(image, 'status') == 'queued'
    queued_exclude_attrs = ['disk_format', 'container_format']
    include_locations_attrs = ['direct_url', 'locations']
    output = {}

    for attr in IMAGE_ATTRIBUTES:
        if attr == 'deleted_at' and not output['deleted']:
            output[attr] = None
        elif attr == 'checksum' and output['status'] != 'active':
            output[attr] = None
        # image may not have 'name' attr
        elif attr == 'name':
            output[attr] = getattr(image, attr, None)
        # NOTE(liusheng): queued image may not have these attributes and 'name'
        elif queued and attr in queued_exclude_attrs:
            output[attr] = getattr(image, attr, None)
        # NOTE(mriedem): Only get location attrs if including locations.
        elif attr in include_locations_attrs:
            if include_locations:
                output[attr] = getattr(image, attr, None)
        else:
            # NOTE(xarses): Anything that is caught with the default value
            # will result in a additional lookup to glance for said attr.
            # Notable attributes that could have this issue:
            # disk_format, container_format, name, deleted, checksum
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
        return exception.Invalid(six.text_type(exc_value))
    return exc_value


def _translate_plain_exception(exc_value):
    if isinstance(exc_value, (glanceclient.exc.Forbidden,
                    glanceclient.exc.Unauthorized)):
        return exception.Forbidden(six.text_type(exc_value))
    if isinstance(exc_value, glanceclient.exc.NotFound):
        return exception.NotFound(six.text_type(exc_value))
    if isinstance(exc_value, glanceclient.exc.BadRequest):
        return exception.Invalid(six.text_type(exc_value))
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
    # NOTE(bcwaldon): If image_href doesn't look like a URI, assume its a
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


class UpdateGlanceImage(object):
    def __init__(self, context, image_id, metadata, stream):
        self.context = context
        self.image_id = image_id
        self.metadata = metadata
        self.image_stream = stream

    def start(self):
        image_service, image_id = (
            get_remote_image_service(self.context, self.image_id))
        image_service.update(self.context, image_id, self.metadata,
                             self.image_stream, purge_props=False)
