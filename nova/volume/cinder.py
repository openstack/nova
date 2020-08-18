# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Handles all requests relating to volumes + cinder.
"""

import collections
import copy
import functools
import sys

from cinderclient import api_versions as cinder_api_versions
from cinderclient import apiclient as cinder_apiclient
from cinderclient import client as cinder_client
from cinderclient import exceptions as cinder_exception
from keystoneauth1 import exceptions as keystone_exception
from keystoneauth1 import loading as ks_loading
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import strutils
import retrying
import six
from six.moves import urllib

from nova import availability_zones as az
import nova.conf
from nova import exception
from nova.i18n import _
from nova import service_auth


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

_ADMIN_AUTH = None
_SESSION = None


def reset_globals():
    """Testing method to reset globals.
    """
    global _ADMIN_AUTH
    global _SESSION

    _ADMIN_AUTH = None
    _SESSION = None


def _load_auth_plugin(conf):
    auth_plugin = ks_loading.load_auth_from_conf_options(conf,
                                    nova.conf.cinder.cinder_group.name)

    if auth_plugin:
        return auth_plugin

    if conf.cinder.auth_type is None:
        LOG.error('The [cinder] section of your nova configuration file '
                  'must be configured for authentication with the '
                  'block-storage service endpoint.')
    err_msg = _('Unknown auth type: %s') % conf.cinder.auth_type
    raise cinder_exception.Unauthorized(401, message=err_msg)


def _load_session():
    global _SESSION

    if not _SESSION:
        _SESSION = ks_loading.load_session_from_conf_options(
            CONF, nova.conf.cinder.cinder_group.name)


def _get_auth(context):
    global _ADMIN_AUTH
    # NOTE(lixipeng): Auth token is none when call
    # cinder API from compute periodic tasks, context
    # from them generated from 'context.get_admin_context'
    # which only set is_admin=True but is without token.
    # So add load_auth_plugin when this condition appear.
    if context.is_admin and not context.auth_token:
        if not _ADMIN_AUTH:
            _ADMIN_AUTH = _load_auth_plugin(CONF)
        return _ADMIN_AUTH
    else:
        return service_auth.get_auth_plugin(context)


# NOTE(efried): Bug #1752152
# This method is copied/adapted from cinderclient.client.get_server_version so
# we can use _SESSION.get rather than a raw requests.get to retrieve the
# version document. This enables HTTPS by gleaning cert info from the session
# config.
def _get_server_version(context, url):
    """Queries the server via the naked endpoint and gets version info.

    :param context: The nova request context for auth.
    :param url: url of the cinder endpoint
    :returns: APIVersion object for min and max version supported by
              the server
    """
    min_version = "2.0"
    current_version = "2.0"

    _load_session()
    auth = _get_auth(context)

    try:
        u = urllib.parse.urlparse(url)
        version_url = None

        # NOTE(andreykurilin): endpoint URL has at least 2 formats:
        #   1. The classic (legacy) endpoint:
        #       http://{host}:{optional_port}/v{2 or 3}/{project-id}
        #       http://{host}:{optional_port}/v{2 or 3}
        #   3. Under wsgi:
        #       http://{host}:{optional_port}/volume/v{2 or 3}
        for ver in ['v2', 'v3']:
            if u.path.endswith(ver) or "/{0}/".format(ver) in u.path:
                path = u.path[:u.path.rfind(ver)]
                version_url = '%s://%s%s' % (u.scheme, u.netloc, path)
                break

        if not version_url:
            # NOTE(andreykurilin): probably, it is one of the next cases:
            #  * https://volume.example.com/
            #  * https://example.com/volume
            # leave as is without cropping.
            version_url = url

        response = _SESSION.get(version_url, auth=auth)
        data = jsonutils.loads(response.text)
        versions = data['versions']
        for version in versions:
            if '3.' in version['version']:
                min_version = version['min_version']
                current_version = version['version']
                break
    except cinder_exception.ClientException as e:
        LOG.warning("Error in server version query:%s\n"
                    "Returning APIVersion 2.0", six.text_type(e.message))
    return (cinder_api_versions.APIVersion(min_version),
            cinder_api_versions.APIVersion(current_version))


# NOTE(efried): Bug #1752152
# This method is copied/adapted from
# cinderclient.client.get_highest_client_server_version.  See note on
# _get_server_version.
def _get_highest_client_server_version(context, url):
    """Returns highest APIVersion supported version by client and server."""
    min_server, max_server = _get_server_version(context, url)
    max_client = cinder_api_versions.APIVersion(
        cinder_api_versions.MAX_VERSION)
    return min(max_server, max_client)


def _check_microversion(context, url, microversion):
    """Checks to see if the requested microversion is supported by the current
    version of python-cinderclient and the volume API endpoint.

    :param context: The nova request context for auth.
    :param url: Cinder API endpoint URL.
    :param microversion: Requested microversion. If not available at the given
        API endpoint URL, a CinderAPIVersionNotAvailable exception is raised.
    :returns: The microversion if it is available. This can be used to
        construct the cinder v3 client object.
    :raises: CinderAPIVersionNotAvailable if the microversion is not available.
    """
    max_api_version = _get_highest_client_server_version(context, url)
    # Check if the max_api_version matches the requested minimum microversion.
    if max_api_version.matches(microversion):
        # The requested microversion is supported by the client and the server.
        return microversion
    raise exception.CinderAPIVersionNotAvailable(version=microversion)


def _get_cinderclient_parameters(context):
    _load_session()

    auth = _get_auth(context)

    url = None

    service_type, service_name, interface = CONF.cinder.catalog_info.split(':')

    service_parameters = {'service_type': service_type,
                          'interface': interface,
                          'region_name': CONF.cinder.os_region_name}
    # Only include the service_name if it's provided.
    if service_name:
        service_parameters['service_name'] = service_name

    if CONF.cinder.endpoint_template:
        url = CONF.cinder.endpoint_template % context.to_dict()
    else:
        url = _SESSION.get_endpoint(auth, **service_parameters)

    return auth, service_parameters, url


def is_microversion_supported(context, microversion):
    # NOTE(efried): Work around bug #1752152.  Call the cinderclient() builder
    # in a way that just does a microversion check.
    cinderclient(context, microversion=microversion, check_only=True)


def cinderclient(context, microversion=None, skip_version_check=False,
                 check_only=False):
    """Constructs a cinder client object for making API requests.

    :param context: The nova request context for auth.
    :param microversion: Optional microversion to check against the client.
        This implies that Cinder v3 is required for any calls that require a
        microversion. If the microversion is not available, this method will
        raise an CinderAPIVersionNotAvailable exception.
    :param skip_version_check: If True and a specific microversion is
        requested, the version discovery check is skipped and the microversion
        is used directly. This should only be used if a previous check for the
        same microversion was successful.
    :param check_only: If True, don't build the actual client; just do the
        setup and version checking.
    :raises: UnsupportedCinderAPIVersion if a major version other than 3 is
        requested.
    :raises: CinderAPIVersionNotAvailable if microversion checking is requested
        and the specified microversion is higher than what the service can
        handle.
    :returns: A cinderclient.client.Client wrapper, unless check_only is False.
    """

    endpoint_override = None
    auth, service_parameters, url = _get_cinderclient_parameters(context)

    if CONF.cinder.endpoint_template:
        endpoint_override = url

    # TODO(jamielennox): This should be using proper version discovery from
    # the cinder service rather than just inspecting the URL for certain string
    # values.
    version = cinder_client.get_volume_api_from_url(url)

    if version != '3':
        raise exception.UnsupportedCinderAPIVersion(version=version)

    version = '3.0'
    # Check to see a specific microversion is requested and if so, can it
    # be handled by the backing server.
    if microversion is not None:
        if skip_version_check:
            version = microversion
        else:
            version = _check_microversion(context, url, microversion)

    if check_only:
        return

    return cinder_client.Client(version,
                                session=_SESSION,
                                auth=auth,
                                endpoint_override=endpoint_override,
                                connect_retries=CONF.cinder.http_retries,
                                global_request_id=context.global_id,
                                **service_parameters)


def _untranslate_volume_summary_view(context, vol):
    """Maps keys for volumes summary view."""
    d = {}
    d['id'] = vol.id
    d['status'] = vol.status
    d['size'] = vol.size
    d['availability_zone'] = vol.availability_zone
    d['created_at'] = vol.created_at

    # TODO(jdg): The calling code expects attach_time and
    #            mountpoint to be set. When the calling
    #            code is more defensive this can be
    #            removed.
    d['attach_time'] = ""
    d['mountpoint'] = ""
    d['multiattach'] = getattr(vol, 'multiattach', False)

    if vol.attachments:
        d['attachments'] = collections.OrderedDict()
        for attachment in vol.attachments:
            a = {attachment['server_id']:
                 {'attachment_id': attachment.get('attachment_id'),
                  'mountpoint': attachment.get('device')}
                 }
            d['attachments'].update(a.items())

        d['attach_status'] = 'attached'
    else:
        d['attach_status'] = 'detached'
    d['display_name'] = vol.name
    d['display_description'] = vol.description
    # TODO(jdg): Information may be lost in this translation
    d['volume_type_id'] = vol.volume_type
    d['snapshot_id'] = vol.snapshot_id
    d['bootable'] = strutils.bool_from_string(vol.bootable)
    d['volume_metadata'] = {}
    for key, value in vol.metadata.items():
        d['volume_metadata'][key] = value

    if hasattr(vol, 'volume_image_metadata'):
        d['volume_image_metadata'] = copy.deepcopy(vol.volume_image_metadata)

    # The 3.48 microversion exposes a shared_targets boolean and service_uuid
    # string parameter which can be used with locks during volume attach
    # and detach.
    if hasattr(vol, 'shared_targets'):
        d['shared_targets'] = vol.shared_targets
        d['service_uuid'] = vol.service_uuid

    if hasattr(vol, 'migration_status'):
        d['migration_status'] = vol.migration_status

    return d


def _untranslate_volume_type_view(volume_type):
    """Maps keys for volume type view."""
    v = {}

    v['id'] = volume_type.id
    v['name'] = volume_type.name

    return v


def _untranslate_snapshot_summary_view(context, snapshot):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = snapshot.id
    d['status'] = snapshot.status
    d['progress'] = snapshot.progress
    d['size'] = snapshot.size
    d['created_at'] = snapshot.created_at
    d['display_name'] = snapshot.name
    d['display_description'] = snapshot.description

    d['volume_id'] = snapshot.volume_id
    d['project_id'] = snapshot.project_id
    d['volume_size'] = snapshot.size

    return d


def _translate_attachment_ref(attachment_ref):
    """Building old style connection_info by adding the 'data' key back."""
    translated_con_info = {}
    connection_info_data = attachment_ref.pop('connection_info', None)
    if connection_info_data:
        connection_info_data.pop('attachment_id', None)
        translated_con_info['driver_volume_type'] = \
            connection_info_data.pop('driver_volume_type', None)
        translated_con_info['data'] = connection_info_data
        translated_con_info['status'] = attachment_ref.pop('status', None)
        translated_con_info['instance'] = attachment_ref.pop('instance', None)
        translated_con_info['attached_at'] = attachment_ref.pop('attached_at',
                                                                None)
        translated_con_info['detached_at'] = attachment_ref.pop('detached_at',
                                                                None)

        # Now the catch all...
        for k, v in attachment_ref.items():
            # Keep these as top-level fields on the attachment record.
            if k not in ("id", "attach_mode"):
                translated_con_info[k] = v

    attachment_ref['connection_info'] = translated_con_info

    return attachment_ref


def translate_cinder_exception(method):
    """Transforms a cinder exception but keeps its traceback intact."""
    @functools.wraps(method)
    def wrapper(self, ctx, *args, **kwargs):
        try:
            res = method(self, ctx, *args, **kwargs)
        except (cinder_exception.ConnectionError,
                keystone_exception.ConnectionError) as exc:
            err_msg = encodeutils.exception_to_unicode(exc)
            _reraise(exception.CinderConnectionFailed(reason=err_msg))
        except (keystone_exception.BadRequest,
                cinder_exception.BadRequest) as exc:
            err_msg = encodeutils.exception_to_unicode(exc)
            _reraise(exception.InvalidInput(reason=err_msg))
        except (keystone_exception.Forbidden,
                cinder_exception.Forbidden) as exc:
            err_msg = encodeutils.exception_to_unicode(exc)
            _reraise(exception.Forbidden(err_msg))
        return res
    return wrapper


def translate_create_exception(method):
    """Transforms the exception for create but keeps its traceback intact.
    """
    def wrapper(self, ctx, size, *args, **kwargs):
        try:
            res = method(self, ctx, size, *args, **kwargs)
        except (keystone_exception.NotFound, cinder_exception.NotFound) as e:
            _reraise(exception.NotFound(message=e.message))
        except cinder_exception.OverLimit as e:
            _reraise(exception.OverQuota(message=e.message))
        return res
    return translate_cinder_exception(wrapper)


def translate_volume_exception(method):
    """Transforms the exception for the volume but keeps its traceback intact.
    """
    def wrapper(self, ctx, volume_id, *args, **kwargs):
        try:
            res = method(self, ctx, volume_id, *args, **kwargs)
        except (keystone_exception.NotFound, cinder_exception.NotFound):
            _reraise(exception.VolumeNotFound(volume_id=volume_id))
        except cinder_exception.OverLimit as e:
            _reraise(exception.OverQuota(message=e.message))
        return res
    return translate_cinder_exception(wrapper)


def translate_attachment_exception(method):
    """Transforms the exception for the attachment but keeps its traceback
    intact.
    """
    def wrapper(self, ctx, attachment_id, *args, **kwargs):
        try:
            res = method(self, ctx, attachment_id, *args, **kwargs)
        except (keystone_exception.NotFound, cinder_exception.NotFound):
            _reraise(exception.VolumeAttachmentNotFound(
                attachment_id=attachment_id))
        return res
    return translate_cinder_exception(wrapper)


def translate_snapshot_exception(method):
    """Transforms the exception for the snapshot but keeps its traceback
       intact.
    """
    def wrapper(self, ctx, snapshot_id, *args, **kwargs):
        try:
            res = method(self, ctx, snapshot_id, *args, **kwargs)
        except (keystone_exception.NotFound, cinder_exception.NotFound):
            _reraise(exception.SnapshotNotFound(snapshot_id=snapshot_id))
        return res
    return translate_cinder_exception(wrapper)


def translate_mixed_exceptions(method):
    """Transforms exceptions that can come from both volumes and snapshots."""
    def wrapper(self, ctx, res_id, *args, **kwargs):
        try:
            res = method(self, ctx, res_id, *args, **kwargs)
        except (keystone_exception.NotFound, cinder_exception.NotFound):
            _reraise(exception.VolumeNotFound(volume_id=res_id))
        except cinder_exception.OverLimit:
            _reraise(exception.OverQuota(overs='snapshots'))
        return res
    return translate_cinder_exception(wrapper)


def _reraise(desired_exc):
    raise desired_exc.with_traceback(sys.exc_info()[2])


class API(object):
    """API for interacting with the volume manager."""

    @translate_volume_exception
    def get(self, context, volume_id, microversion=None):
        """Get the details about a volume given it's ID.

        :param context: the nova request context
        :param volume_id: the id of the volume to get
        :param microversion: optional string microversion value
        :raises: CinderAPIVersionNotAvailable if the specified microversion is
            not available.
        """
        item = cinderclient(
            context, microversion=microversion).volumes.get(volume_id)
        return _untranslate_volume_summary_view(context, item)

    @translate_cinder_exception
    def get_all(self, context, search_opts=None):
        search_opts = search_opts or {}
        items = cinderclient(context).volumes.list(detailed=True,
                                                   search_opts=search_opts)

        rval = []

        for item in items:
            rval.append(_untranslate_volume_summary_view(context, item))

        return rval

    def check_attached(self, context, volume):
        if volume['status'] != "in-use":
            msg = _("volume '%(vol)s' status must be 'in-use'. Currently in "
                    "'%(status)s' status") % {"vol": volume['id'],
                                              "status": volume['status']}
            raise exception.InvalidVolume(reason=msg)

    def check_availability_zone(self, context, volume, instance=None):
        """Ensure that the availability zone is the same.

        :param context: the nova request context
        :param volume: the volume attached to the instance
        :param instance: nova.objects.instance.Instance object
        :raises: InvalidVolume if the instance availability zone does not
            equal the volume's availability zone
        """

        # TODO(walter-boring): move this check to Cinder as part of
        # the reserve call.
        if instance and not CONF.cinder.cross_az_attach:
            instance_az = az.get_instance_availability_zone(context, instance)
            if instance_az != volume['availability_zone']:
                msg = _("Instance %(instance)s and volume %(vol)s are not in "
                        "the same availability_zone. Instance is in "
                        "%(ins_zone)s. Volume is in %(vol_zone)s") % {
                            "instance": instance.uuid,
                            "vol": volume['id'],
                            'ins_zone': instance_az,
                            'vol_zone': volume['availability_zone']}
                raise exception.InvalidVolume(reason=msg)

    @translate_volume_exception
    def reserve_volume(self, context, volume_id):
        cinderclient(context).volumes.reserve(volume_id)

    @translate_volume_exception
    def unreserve_volume(self, context, volume_id):
        cinderclient(context).volumes.unreserve(volume_id)

    @translate_volume_exception
    def begin_detaching(self, context, volume_id):
        cinderclient(context).volumes.begin_detaching(volume_id)

    @translate_volume_exception
    def roll_detaching(self, context, volume_id):
        cinderclient(context).volumes.roll_detaching(volume_id)

    @translate_volume_exception
    def attach(self, context, volume_id, instance_uuid, mountpoint, mode='rw'):
        cinderclient(context).volumes.attach(volume_id, instance_uuid,
                                             mountpoint, mode=mode)

    @translate_volume_exception
    @retrying.retry(stop_max_attempt_number=5,
                    retry_on_exception=lambda e:
                    type(e) == cinder_apiclient.exceptions.InternalServerError)
    def detach(self, context, volume_id, instance_uuid=None,
               attachment_id=None):
        client = cinderclient(context)
        if attachment_id is None:
            volume = self.get(context, volume_id)
            if volume['multiattach']:
                attachments = volume.get('attachments', {})
                if instance_uuid:
                    attachment_id = attachments.get(instance_uuid, {}).\
                            get('attachment_id')
                    if not attachment_id:
                        LOG.warning("attachment_id couldn't be retrieved "
                                    "for volume %(volume_id)s with "
                                    "instance_uuid %(instance_id)s. The "
                                    "volume has the 'multiattach' flag "
                                    "enabled, without the attachment_id "
                                    "Cinder most probably cannot perform "
                                    "the detach.",
                                    {'volume_id': volume_id,
                                     'instance_id': instance_uuid})
                else:
                    LOG.warning("attachment_id couldn't be retrieved for "
                                "volume %(volume_id)s. The volume has the "
                                "'multiattach' flag enabled, without the "
                                "attachment_id Cinder most probably "
                                "cannot perform the detach.",
                                {'volume_id': volume_id})

        client.volumes.detach(volume_id, attachment_id)

    @translate_volume_exception
    def initialize_connection(self, context, volume_id, connector):
        try:
            connection_info = cinderclient(
                context).volumes.initialize_connection(volume_id, connector)
            connection_info['connector'] = connector
            return connection_info
        except cinder_exception.ClientException as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    'Initialize connection failed for volume %(vol)s on host '
                    '%(host)s. Error: %(msg)s Code: %(code)s. '
                    'Attempting to terminate connection.',
                    {'vol': volume_id,
                     'host': connector.get('host'),
                     'msg': six.text_type(ex),
                     'code': ex.code})
                try:
                    self.terminate_connection(context, volume_id, connector)
                except Exception as exc:
                    LOG.error(
                        'Connection between volume %(vol)s and host %(host)s '
                        'might have succeeded, but attempt to terminate '
                        'connection has failed. Validate the connection and '
                        'determine if manual cleanup is needed. '
                        'Error: %(msg)s Code: %(code)s.',
                        {'vol': volume_id,
                        'host': connector.get('host'),
                        'msg': six.text_type(exc),
                        'code': exc.code if hasattr(exc, 'code') else None})

    @translate_volume_exception
    @retrying.retry(stop_max_attempt_number=5,
                    retry_on_exception=lambda e:
                    type(e) == cinder_apiclient.exceptions.InternalServerError)
    def terminate_connection(self, context, volume_id, connector):
        return cinderclient(context).volumes.terminate_connection(volume_id,
                                                                  connector)

    @translate_cinder_exception
    def migrate_volume_completion(self, context, old_volume_id, new_volume_id,
                                  error=False):
        return cinderclient(context).volumes.migrate_volume_completion(
            old_volume_id, new_volume_id, error)

    @translate_create_exception
    def create(self, context, size, name, description, snapshot=None,
               image_id=None, volume_type=None, metadata=None,
               availability_zone=None):
        client = cinderclient(context)

        if snapshot is not None:
            snapshot_id = snapshot['id']
        else:
            snapshot_id = None

        kwargs = dict(snapshot_id=snapshot_id,
                      volume_type=volume_type,
                      availability_zone=availability_zone,
                      metadata=metadata,
                      imageRef=image_id,
                      name=name,
                      description=description)

        item = client.volumes.create(size, **kwargs)
        return _untranslate_volume_summary_view(context, item)

    @translate_volume_exception
    def delete(self, context, volume_id):
        cinderclient(context).volumes.delete(volume_id)

    @translate_volume_exception
    def update(self, context, volume_id, fields):
        raise NotImplementedError()

    @translate_cinder_exception
    def get_absolute_limits(self, context):
        """Returns quota limit and usage information for the given tenant

        See the <volumev3>/v3/{project_id}/limits API reference for details.

        :param context: The nova RequestContext for the user request. Note
            that the limit information returned from Cinder is specific to
            the project_id within this context.
        :returns: dict of absolute limits
        """
        # cinderclient returns a generator of AbsoluteLimit objects, so iterate
        # over the generator and return a dictionary which is easier for the
        # nova client-side code to handle.
        limits = cinderclient(context).limits.get().absolute
        return {limit.name: limit.value for limit in limits}

    @translate_snapshot_exception
    def get_snapshot(self, context, snapshot_id):
        item = cinderclient(context).volume_snapshots.get(snapshot_id)
        return _untranslate_snapshot_summary_view(context, item)

    @translate_cinder_exception
    def get_all_snapshots(self, context):
        items = cinderclient(context).volume_snapshots.list(detailed=True)
        rvals = []

        for item in items:
            rvals.append(_untranslate_snapshot_summary_view(context, item))

        return rvals

    @translate_mixed_exceptions
    def create_snapshot(self, context, volume_id, name, description):
        item = cinderclient(context).volume_snapshots.create(volume_id,
                                                             False,
                                                             name,
                                                             description)
        return _untranslate_snapshot_summary_view(context, item)

    @translate_mixed_exceptions
    def create_snapshot_force(self, context, volume_id, name, description):
        item = cinderclient(context).volume_snapshots.create(volume_id,
                                                             True,
                                                             name,
                                                             description)

        return _untranslate_snapshot_summary_view(context, item)

    @translate_snapshot_exception
    def delete_snapshot(self, context, snapshot_id):
        cinderclient(context).volume_snapshots.delete(snapshot_id)

    @translate_cinder_exception
    def get_all_volume_types(self, context):
        items = cinderclient(context).volume_types.list()
        rvals = []

        for item in items:
            rvals.append(_untranslate_volume_type_view(item))

        return rvals

    @translate_cinder_exception
    def get_volume_encryption_metadata(self, context, volume_id):
        return cinderclient(context).volumes.get_encryption_metadata(volume_id)

    @translate_snapshot_exception
    def update_snapshot_status(self, context, snapshot_id, status):
        vs = cinderclient(context).volume_snapshots

        # '90%' here is used to tell Cinder that Nova is done
        # with its portion of the 'creating' state. This can
        # be removed when we are able to split the Cinder states
        # into 'creating' and a separate state of
        # 'creating_in_nova'. (Same for 'deleting' state.)

        vs.update_snapshot_status(
            snapshot_id,
            {'status': status,
             'progress': '90%'}
        )

    @translate_volume_exception
    def attachment_create(self, context, volume_id, instance_id,
                          connector=None, mountpoint=None):
        """Create a volume attachment. This requires microversion >= 3.44.

        The attachment_create call was introduced in microversion 3.27. We
        need 3.44 as minmum here as we need attachment_complete to finish the
        attaching process and it which was introduced in version 3.44.

        :param context: The nova request context.
        :param volume_id: UUID of the volume on which to create the attachment.
        :param instance_id: UUID of the instance to which the volume will be
            attached.
        :param connector: host connector dict; if None, the attachment will
            be 'reserved' but not yet attached.
        :param mountpoint: Optional mount device name for the attachment,
            e.g. "/dev/vdb". This is only used if a connector is provided.
        :returns: a dict created from the
            cinderclient.v3.attachments.VolumeAttachment object with a backward
            compatible connection_info dict
        """
        # NOTE(mriedem): Due to a limitation in the POST /attachments/
        # API in Cinder, we have to pass the mountpoint in via the
        # host connector rather than pass it in as a top-level parameter
        # like in the os-attach volume action API. Hopefully this will be
        # fixed some day with a new Cinder microversion but until then we
        # work around it client-side.
        _connector = connector
        if _connector and mountpoint and 'mountpoint' not in _connector:
            # Make a copy of the connector so we don't modify it by
            # reference.
            _connector = copy.deepcopy(connector)
            _connector['mountpoint'] = mountpoint

        try:
            attachment_ref = cinderclient(context, '3.44').attachments.create(
                volume_id, _connector, instance_id)
            return _translate_attachment_ref(attachment_ref)
        except cinder_exception.ClientException as ex:
            with excutils.save_and_reraise_exception():
                # NOTE: It is unnecessary to output BadRequest(400) error log,
                # because operators don't need to debug such cases.
                if getattr(ex, 'code', None) != 400:
                    LOG.error('Create attachment failed for volume '
                              '%(volume_id)s. Error: %(msg)s Code: %(code)s',
                              {'volume_id': volume_id,
                               'msg': six.text_type(ex),
                               'code': getattr(ex, 'code', None)},
                              instance_uuid=instance_id)

    @translate_attachment_exception
    def attachment_get(self, context, attachment_id):
        """Gets a volume attachment.

        :param context: The nova request context.
        :param attachment_id: UUID of the volume attachment to get.
        :returns: a dict created from the
            cinderclient.v3.attachments.VolumeAttachment object with a backward
            compatible connection_info dict
        """
        try:
            attachment_ref = cinderclient(
                context, '3.44', skip_version_check=True).attachments.show(
                attachment_id)
            translated_attach_ref = _translate_attachment_ref(
                attachment_ref.to_dict())
            return translated_attach_ref
        except cinder_exception.ClientException as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Show attachment failed for attachment '
                          '%(id)s. Error: %(msg)s Code: %(code)s',
                          {'id': attachment_id,
                           'msg': six.text_type(ex),
                           'code': getattr(ex, 'code', None)})

    @translate_attachment_exception
    def attachment_update(self, context, attachment_id, connector,
                          mountpoint=None):
        """Updates the connector on the volume attachment. An attachment
        without a connector is considered reserved but not fully attached.

        :param context: The nova request context.
        :param attachment_id: UUID of the volume attachment to update.
        :param connector: host connector dict. This is required when updating
            a volume attachment. To terminate a connection, the volume
            attachment for that connection must be deleted.
        :param mountpoint: Optional mount device name for the attachment,
            e.g. "/dev/vdb". Theoretically this is optional per volume backend,
            but in practice it's normally required so it's best to always
            provide a value.
        :returns: a dict created from the
            cinderclient.v3.attachments.VolumeAttachment object with a backward
            compatible connection_info dict
        """
        # NOTE(mriedem): Due to a limitation in the PUT /attachments/{id}
        # API in Cinder, we have to pass the mountpoint in via the
        # host connector rather than pass it in as a top-level parameter
        # like in the os-attach volume action API. Hopefully this will be
        # fixed some day with a new Cinder microversion but until then we
        # work around it client-side.
        _connector = connector
        if mountpoint and 'mountpoint' not in connector:
            # Make a copy of the connector so we don't modify it by
            # reference.
            _connector = copy.deepcopy(connector)
            _connector['mountpoint'] = mountpoint

        try:
            attachment_ref = cinderclient(
                context, '3.44', skip_version_check=True).attachments.update(
                    attachment_id, _connector)
            translated_attach_ref = _translate_attachment_ref(
                attachment_ref.to_dict())
            return translated_attach_ref
        except cinder_exception.ClientException as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Update attachment failed for attachment '
                          '%(id)s. Error: %(msg)s Code: %(code)s',
                          {'id': attachment_id,
                           'msg': six.text_type(ex),
                           'code': getattr(ex, 'code', None)})

    @translate_attachment_exception
    @retrying.retry(stop_max_attempt_number=5,
                    retry_on_exception=lambda e:
                    type(e) == cinder_apiclient.exceptions.InternalServerError)
    def attachment_delete(self, context, attachment_id):
        try:
            cinderclient(
                context, '3.44', skip_version_check=True).attachments.delete(
                    attachment_id)
        except cinder_exception.ClientException as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Delete attachment failed for attachment '
                          '%(id)s. Error: %(msg)s Code: %(code)s',
                          {'id': attachment_id,
                           'msg': six.text_type(ex),
                           'code': getattr(ex, 'code', None)})

    @translate_attachment_exception
    def attachment_complete(self, context, attachment_id):
        """Marks a volume attachment complete.

        This call should be used to inform Cinder that a volume attachment is
        fully connected on the compute host so Cinder can apply the necessary
        state changes to the volume info in its database.

        :param context: The nova request context.
        :param attachment_id: UUID of the volume attachment to update.
        """
        try:
            cinderclient(
                context, '3.44', skip_version_check=True).attachments.complete(
                    attachment_id)
        except cinder_exception.ClientException as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Complete attachment failed for attachment '
                          '%(id)s. Error: %(msg)s Code: %(code)s',
                          {'id': attachment_id,
                           'msg': six.text_type(ex),
                           'code': getattr(ex, 'code', None)})
