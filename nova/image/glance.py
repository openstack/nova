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
import inspect
import itertools
import os
import random
import re
import stat
import sys
import time

import cryptography
from cursive import exception as cursive_exception
from cursive import signature_utils
import glanceclient
import glanceclient.exc
from glanceclient.v2 import schemas
from keystoneauth1 import loading as ks_loading
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import timeutils
import six
from six.moves import range
import six.moves.urllib.parse as urlparse

import nova.conf
from nova import exception
import nova.image.download as image_xfers
from nova import objects
from nova.objects import fields
from nova import service_auth
from nova import utils


LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF

_SESSION = None


def _session_and_auth(context):
    # Session is cached, but auth needs to be pulled from context each time.
    global _SESSION

    if not _SESSION:
        _SESSION = ks_loading.load_session_from_conf_options(
            CONF, nova.conf.glance.glance_group.name)

    auth = service_auth.get_auth_plugin(context)

    return _SESSION, auth


def _glanceclient_from_endpoint(context, endpoint, version):
    sess, auth = _session_and_auth(context)

    return glanceclient.Client(version, session=sess, auth=auth,
                               endpoint_override=endpoint,
                               global_request_id=context.global_id)


def generate_glance_url(context):
    """Return a random glance url from the api servers we know about."""
    return next(get_api_servers(context))


def _endpoint_from_image_ref(image_href):
    """Return the image_ref and guessed endpoint from an image url.

    :param image_href: href of an image
    :returns: a tuple of the form (image_id, endpoint_url)
    """
    parts = image_href.split('/')
    image_id = parts[-1]
    # the endpoint is everything in the url except the last 3 bits
    # which are version, 'images', and image_id
    endpoint = '/'.join(parts[:-3])
    return (image_id, endpoint)


def generate_identity_headers(context, status='Confirmed'):
    return {
        'X-Auth-Token': getattr(context, 'auth_token', None),
        'X-User-Id': getattr(context, 'user_id', None),
        'X-Tenant-Id': getattr(context, 'project_id', None),
        'X-Roles': ','.join(getattr(context, 'roles', [])),
        'X-Identity-Status': status,
    }


def get_api_servers(context):
    """Shuffle a list of service endpoints and return an iterator that will
    cycle through the list, looping around to the beginning if necessary.
    """
    # NOTE(efried): utils.get_ksa_adapter().get_endpoint() is the preferred
    # mechanism for endpoint discovery. Only use `api_servers` if you really
    # need to shuffle multiple endpoints.
    if CONF.glance.api_servers:
        api_servers = CONF.glance.api_servers
        random.shuffle(api_servers)
    else:
        sess, auth = _session_and_auth(context)
        ksa_adap = utils.get_ksa_adapter(
            nova.conf.glance.DEFAULT_SERVICE_TYPE,
            ksa_auth=auth, ksa_session=sess,
            min_version='2.0', max_version='2.latest')
        endpoint = utils.get_endpoint(ksa_adap)
        if endpoint:
            # NOTE(mriedem): Due to python-glanceclient bug 1707995 we have
            # to massage the endpoint URL otherwise it won't work properly.
            # We can't use glanceclient.common.utils.strip_version because
            # of bug 1748009.
            endpoint = re.sub(r'/v\d+(\.\d+)?/?$', '/', endpoint)
        api_servers = [endpoint]

    return itertools.cycle(api_servers)


class GlanceClientWrapper(object):
    """Glance client wrapper class that implements retries."""

    def __init__(self, context=None, endpoint=None):
        version = 2
        if endpoint is not None:
            self.client = self._create_static_client(context,
                                                     endpoint,
                                                     version)
        else:
            self.client = None
        self.api_servers = None

    def _create_static_client(self, context, endpoint, version):
        """Create a client that we'll use for every call."""
        self.api_server = str(endpoint)
        return _glanceclient_from_endpoint(context, endpoint, version)

    def _create_onetime_client(self, context, version):
        """Create a client that will be used for one call."""
        if self.api_servers is None:
            self.api_servers = get_api_servers(context)
        self.api_server = next(self.api_servers)
        return _glanceclient_from_endpoint(context, self.api_server, version)

    def call(self, context, version, method, *args, **kwargs):
        """Call a glance client method.  If we get a connection error,
        retry the request according to CONF.glance.num_retries.
        """
        retry_excs = (glanceclient.exc.ServiceUnavailable,
                glanceclient.exc.InvalidEndpoint,
                glanceclient.exc.CommunicationError)
        num_attempts = 1 + CONF.glance.num_retries

        for attempt in range(1, num_attempts + 1):
            client = self.client or self._create_onetime_client(context,
                                                                version)
            try:
                controller = getattr(client,
                                     kwargs.pop('controller', 'images'))
                result = getattr(controller, method)(*args, **kwargs)
                if inspect.isgenerator(result):
                    # Convert generator results to a list, so that we can
                    # catch any potential exceptions now and retry the call.
                    return list(result)
                return result
            except retry_excs as e:
                if attempt < num_attempts:
                    extra = "retrying"
                else:
                    extra = 'done trying'

                LOG.exception("Error contacting glance server "
                              "'%(server)s' for '%(method)s', "
                              "%(extra)s.",
                              {'server': self.api_server,
                               'method': method, 'extra': extra})
                if attempt == num_attempts:
                    raise exception.GlanceConnectionFailed(
                        server=str(self.api_server), reason=six.text_type(e))
                time.sleep(1)


class GlanceImageServiceV2(object):
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

        for scheme, mod in download_modules.items():
            if scheme not in CONF.glance.allowed_direct_url_schemes:
                continue

            try:
                self._download_handlers[scheme] = mod.get_download_handler()
            except Exception as ex:
                LOG.error('When loading the module %(module_str)s the '
                          'following error occurred: %(ex)s',
                          {'module_str': str(mod), 'ex': ex})

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
        try:
            image = self._client.call(context, 2, 'get', image_id)
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
            LOG.error("Failed to instantiate the download handler "
                      "for %(scheme)s", {'scheme': scheme})
        return

    def detail(self, context, **kwargs):
        """Calls out to Glance for a list of detailed image information."""
        params = _extract_query_params_v2(kwargs)
        try:
            images = self._client.call(context, 2, 'list', **params)
        except Exception:
            _reraise_translated_exception()

        _images = []
        for image in images:
            if _is_image_available(context, image):
                _images.append(_translate_from_glance(image))

        return _images

    @staticmethod
    def _safe_fsync(fh):
        """Performs os.fsync on a filehandle only if it is supported.

        fsync on a pipe, FIFO, or socket raises OSError with EINVAL.  This
        method discovers whether the target filehandle is one of these types
        and only performs fsync if it isn't.

        :param fh: Open filehandle (not a path or fileno) to maybe fsync.
        """
        fileno = fh.fileno()
        mode = os.fstat(fileno).st_mode
        # A pipe answers True to S_ISFIFO
        if not any(check(mode) for check in (stat.S_ISFIFO, stat.S_ISSOCK)):
            os.fsync(fileno)

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
                        LOG.info("Successfully transferred using %s", o.scheme)
                        return
                    except Exception:
                        LOG.exception("Download image error")

        try:
            image_chunks = self._client.call(context, 2, 'data', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if image_chunks.wrapped is None:
            # None is a valid return value, but there's nothing we can do with
            # a image with no associated data
            raise exception.ImageUnacceptable(image_id=image_id,
                reason='Image has no associated data')

        # Retrieve properties for verification of Glance image signature
        verifier = None
        if CONF.glance.verify_glance_signatures:
            image_meta_dict = self.show(context, image_id,
                                        include_locations=False)
            image_meta = objects.ImageMeta.from_dict(image_meta_dict)
            img_signature = image_meta.properties.get('img_signature')
            img_sig_hash_method = image_meta.properties.get(
                'img_signature_hash_method'
            )
            img_sig_cert_uuid = image_meta.properties.get(
                'img_signature_certificate_uuid'
            )
            img_sig_key_type = image_meta.properties.get(
                'img_signature_key_type'
            )
            try:
                verifier = signature_utils.get_verifier(
                    context=context,
                    img_signature_certificate_uuid=img_sig_cert_uuid,
                    img_signature_hash_method=img_sig_hash_method,
                    img_signature=img_signature,
                    img_signature_key_type=img_sig_key_type,
                )
            except cursive_exception.SignatureVerificationError:
                with excutils.save_and_reraise_exception():
                    LOG.error('Image signature verification failed '
                              'for image: %s', image_id)

        close_file = False
        if data is None and dst_path:
            data = open(dst_path, 'wb')
            close_file = True

        if data is None:

            # Perform image signature verification
            if verifier:
                try:
                    for chunk in image_chunks:
                        verifier.update(chunk)
                    verifier.verify()

                    LOG.info('Image signature verification succeeded '
                             'for image: %s', image_id)

                except cryptography.exceptions.InvalidSignature:
                    with excutils.save_and_reraise_exception():
                        LOG.error('Image signature verification failed '
                                  'for image: %s', image_id)
            return image_chunks
        else:
            try:
                for chunk in image_chunks:
                    if verifier:
                        verifier.update(chunk)
                    data.write(chunk)
                if verifier:
                    verifier.verify()
                    LOG.info('Image signature verification succeeded '
                             'for image %s', image_id)
            except cryptography.exceptions.InvalidSignature:
                data.truncate(0)
                with excutils.save_and_reraise_exception():
                    LOG.error('Image signature verification failed '
                              'for image: %s', image_id)
            except Exception as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error("Error writing to %(path)s: %(exception)s",
                              {'path': dst_path, 'exception': ex})
            finally:
                if close_file:
                    # Ensure that the data is pushed all the way down to
                    # persistent storage. This ensures that in the event of a
                    # subsequent host crash we don't have running instances
                    # using a corrupt backing file.
                    data.flush()
                    self._safe_fsync(data)
                    data.close()

    def create(self, context, image_meta, data=None):
        """Store the image data and return the new image object."""
        # Here we workaround the situation when user wants to activate an
        # empty image right after the creation. In Glance v1 api (and
        # therefore in Nova) it is enough to set 'size = 0'. v2 api
        # doesn't allow this hack - we have to send an upload request with
        # empty data.
        force_activate = data is None and image_meta.get('size') == 0

        sent_service_image_meta = _translate_to_glance(image_meta)

        try:
            image = self._create_v2(context, sent_service_image_meta,
                                    data, force_activate)
        except glanceclient.exc.HTTPException:
            _reraise_translated_exception()

        return _translate_from_glance(image)

    def _add_location(self, context, image_id, location):
        # 'show_multiple_locations' must be enabled in glance api conf file.
        try:
            return self._client.call(context, 2, 'add_location', image_id,
                                     location, {})
        except glanceclient.exc.HTTPBadRequest:
            _reraise_translated_exception()

    def _upload_data(self, context, image_id, data):
        self._client.call(context, 2, 'upload', image_id, data)
        return self._client.call(context, 2, 'get', image_id)

    def _get_image_create_disk_format_default(self, context):
        """Gets an acceptable default image disk_format based on the schema.
        """
        # These preferred disk formats are in order:
        # 1. we want qcow2 if possible (at least for backward compat)
        # 2. vhd for xenapi and hyperv
        # 3. vmdk for vmware
        # 4. raw should be universally accepted
        preferred_disk_formats = (
            fields.DiskFormat.QCOW2,
            fields.DiskFormat.VHD,
            fields.DiskFormat.VMDK,
            fields.DiskFormat.RAW,
        )

        # Get the image schema - note we don't cache this value since it could
        # change under us. This looks a bit funky, but what it's basically
        # doing is calling glanceclient.v2.Client.schemas.get('image').
        image_schema = self._client.call(context, 2, 'get', 'image',
                                         controller='schemas')
        # get the disk_format schema property from the raw schema
        disk_format_schema = (
            image_schema.raw()['properties'].get('disk_format') if image_schema
                                                                else {}
        )
        if disk_format_schema and 'enum' in disk_format_schema:
            supported_disk_formats = disk_format_schema['enum']
            # try a priority ordered list
            for preferred_format in preferred_disk_formats:
                if preferred_format in supported_disk_formats:
                    return preferred_format
            # alright, let's just return whatever is available
            LOG.debug('Unable to find a preferred disk_format for image '
                      'creation with the Image Service v2 API. Using: %s',
                      supported_disk_formats[0])
            return supported_disk_formats[0]

        LOG.warning('Unable to determine disk_format schema from the '
                    'Image Service v2 API. Defaulting to '
                    '%(preferred_disk_format)s.',
                    {'preferred_disk_format': preferred_disk_formats[0]})
        return preferred_disk_formats[0]

    def _create_v2(self, context, sent_service_image_meta, data=None,
                   force_activate=False):
        # Glance v1 allows image activation without setting disk and
        # container formats, v2 doesn't. It leads to the dirtiest workaround
        # where we have to hardcode this parameters.
        if force_activate:
            data = ''
            if 'disk_format' not in sent_service_image_meta:
                sent_service_image_meta['disk_format'] = (
                    self._get_image_create_disk_format_default(context)
                )
            if 'container_format' not in sent_service_image_meta:
                sent_service_image_meta['container_format'] = 'bare'

        location = sent_service_image_meta.pop('location', None)
        image = self._client.call(
            context, 2, 'create', **sent_service_image_meta)
        image_id = image['id']

        # Sending image location in a separate request.
        if location:
            image = self._add_location(context, image_id, location)

        # If we have some data we have to send it in separate request and
        # update the image then.
        if data is not None:
            image = self._upload_data(context, image_id, data)

        return image

    def update(self, context, image_id, image_meta, data=None,
               purge_props=True):
        """Modify the given image with the new data."""
        sent_service_image_meta = _translate_to_glance(image_meta)
        # NOTE(bcwaldon): id is not an editable field, but it is likely to be
        # passed in by calling code. Let's be nice and ignore it.
        sent_service_image_meta.pop('id', None)
        sent_service_image_meta['image_id'] = image_id

        try:
            if purge_props:
                # In Glance v2 we have to explicitly set prop names
                # we want to remove.
                all_props = set(self.show(
                        context, image_id)['properties'].keys())
                props_to_update = set(
                        image_meta.get('properties', {}).keys())
                remove_props = list(all_props - props_to_update)
                sent_service_image_meta['remove_props'] = remove_props

            image = self._update_v2(context, sent_service_image_meta, data)
        except Exception:
            _reraise_translated_image_exception(image_id)

        return _translate_from_glance(image)

    def _update_v2(self, context, sent_service_image_meta, data=None):
        location = sent_service_image_meta.pop('location', None)
        image_id = sent_service_image_meta['image_id']
        image = self._client.call(
            context, 2, 'update', **sent_service_image_meta)

        # Sending image location in a separate request.
        if location:
            image = self._add_location(context, image_id, location)

        # If we have some data we have to send it in separate request and
        # update the image then.
        if data is not None:
            image = self._upload_data(context, image_id, data)

        return image

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.
        :raises: NotAuthorized if the user is not an owner.
        :raises: ImageNotAuthorized if the user is not authorized.
        :raises: ImageDeleteConflict if the image is conflicted to delete.

        """
        try:
            self._client.call(context, 2, 'delete', image_id)
        except glanceclient.exc.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        except glanceclient.exc.HTTPForbidden:
            raise exception.ImageNotAuthorized(image_id=image_id)
        except glanceclient.exc.HTTPConflict as exc:
            raise exception.ImageDeleteConflict(reason=six.text_type(exc))
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


def _extract_query_params_v2(params):
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

    # adopt filters to be accepted by glance v2 api
    filters = _params['filters']
    new_filters = {}

    for filter_ in filters:
        # remove 'property-' prefix from filters by custom properties
        if filter_.startswith('property-'):
            new_filters[filter_.lstrip('property-')] = filters[filter_]
        elif filter_ == 'changes-since':
            # convert old 'changes-since' into new 'updated_at' filter
            updated_at = 'gte:' + filters['changes-since']
            new_filters['updated_at'] = updated_at
        elif filter_ == 'is_public':
            # convert old 'is_public' flag into 'visibility' filter
            # omit the filter if is_public is None
            is_public = filters['is_public']
            if is_public.lower() in ('true', '1'):
                new_filters['visibility'] = 'public'
            elif is_public.lower() in ('false', '0'):
                new_filters['visibility'] = 'private'
        else:
            new_filters[filter_] = filters[filter_]

    _params['filters'] = new_filters

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
    image_meta = _convert_to_v2(image_meta)
    return image_meta


def _convert_to_v2(image_meta):
    output = {}
    for name, value in image_meta.items():
        if name == 'properties':
            for prop_name, prop_value in value.items():
                # if allow_additional_image_properties is disabled we can't
                # define kernel_id and ramdisk_id as None, so we have to omit
                # these properties if they are not set.
                if prop_name in ('kernel_id', 'ramdisk_id') and \
                                prop_value is not None and \
                                prop_value.strip().lower() in ('none', ''):
                    continue
                # in glance only string and None property values are allowed,
                # v1 client accepts any values and converts them to string,
                # v2 doesn't - so we have to take care of it.
                elif prop_value is None or isinstance(
                        prop_value, six.string_types):
                    output[prop_name] = prop_value
                else:
                    output[prop_name] = str(prop_value)

        elif name in ('min_ram', 'min_disk'):
            output[name] = int(value)
        elif name == 'is_public':
            output['visibility'] = 'public' if value else 'private'
        elif name in ('size', 'deleted'):
            continue
        else:
            output[name] = value
    return output


def _translate_from_glance(image, include_locations=False):
    image_meta = _extract_attributes_v2(
        image, include_locations=include_locations)

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
    # TODO(mfedosin): Remove this function once we move to glance V2
    # completely.
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
        # NOTE(mdorman): 'size' attribute must not be 'None', so use 0 instead
        elif attr == 'size':
            # NOTE(mriedem): A snapshot image may not have the size attribute
            # set so default to 0.
            output[attr] = getattr(image, attr, 0) or 0
        else:
            # NOTE(xarses): Anything that is caught with the default value
            # will result in an additional lookup to glance for said attr.
            # Notable attributes that could have this issue:
            # disk_format, container_format, name, deleted, checksum
            output[attr] = getattr(image, attr, None)

    output['properties'] = getattr(image, 'properties', {})

    return output


def _extract_attributes_v2(image, include_locations=False):
    include_locations_attrs = ['direct_url', 'locations']
    omit_attrs = ['self', 'schema', 'protected', 'virtual_size', 'file',
                  'tags']
    raw_schema = image.schema
    schema = schemas.Schema(raw_schema)
    output = {'properties': {}, 'deleted': False, 'deleted_at': None,
              'disk_format': None, 'container_format': None, 'name': None,
              'checksum': None}
    for name, value in image.items():
        if (name in omit_attrs
                or name in include_locations_attrs and not include_locations):
            continue
        elif name == 'visibility':
            output['is_public'] = value == 'public'
        elif name == 'size' and value is None:
            output['size'] = 0
        elif schema.is_base_property(name):
            output[name] = value
        else:
            output['properties'][name] = value

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
    six.reraise(type(new_exc), new_exc, exc_trace)


def _reraise_translated_exception():
    """Transform the exception but keep its traceback intact."""
    exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_plain_exception(exc_value)
    six.reraise(type(new_exc), new_exc, exc_trace)


def _translate_image_exception(image_id, exc_value):
    if isinstance(exc_value, (glanceclient.exc.Forbidden,
                    glanceclient.exc.Unauthorized)):
        return exception.ImageNotAuthorized(image_id=image_id)
    if isinstance(exc_value, glanceclient.exc.NotFound):
        return exception.ImageNotFound(image_id=image_id)
    if isinstance(exc_value, glanceclient.exc.BadRequest):
        return exception.ImageBadRequest(image_id=image_id,
                                         response=six.text_type(exc_value))
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
        (image_id, endpoint) = _endpoint_from_image_ref(image_href)
        glance_client = GlanceClientWrapper(context=context,
                                            endpoint=endpoint)
    except ValueError:
        raise exception.InvalidImageRef(image_href=image_href)

    image_service = GlanceImageServiceV2(client=glance_client)
    return image_service, image_id


def get_default_image_service():
    return GlanceImageServiceV2()


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
