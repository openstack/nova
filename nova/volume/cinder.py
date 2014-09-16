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

import copy
import sys

from cinderclient import client as cinder_client
from cinderclient import exceptions as cinder_exception
from cinderclient import service_catalog
from oslo.config import cfg
import six.moves.urllib.parse as urlparse

from nova import availability_zones as az
from nova import exception
from nova.i18n import _
from nova.i18n import _LW
from nova.openstack.common import log as logging
from nova.openstack.common import strutils

cinder_opts = [
    cfg.StrOpt('catalog_info',
            default='volume:cinder:publicURL',
            help='Info to match when looking for cinder in the service '
                 'catalog. Format is: separated values of the form: '
                 '<service_type>:<service_name>:<endpoint_type>',
            deprecated_group='DEFAULT',
            deprecated_name='cinder_catalog_info'),
    cfg.StrOpt('endpoint_template',
               help='Override service catalog lookup with template for cinder '
                    'endpoint e.g. http://localhost:8776/v1/%(project_id)s',
               deprecated_group='DEFAULT',
               deprecated_name='cinder_endpoint_template'),
    cfg.StrOpt('os_region_name',
               help='Region name of this node',
               deprecated_group='DEFAULT',
               deprecated_name='os_region_name'),
    cfg.StrOpt('ca_certificates_file',
               help='Location of ca certificates file to use for cinder '
                    'client requests.',
               deprecated_group='DEFAULT',
               deprecated_name='cinder_ca_certificates_file'),
    cfg.IntOpt('http_retries',
               default=3,
               help='Number of cinderclient retries on failed http calls',
            deprecated_group='DEFAULT',
            deprecated_name='cinder_http_retries'),
    cfg.IntOpt('http_timeout',
               help='HTTP inactivity timeout (in seconds)',
               deprecated_group='DEFAULT',
               deprecated_name='cinder_http_timeout'),
    cfg.BoolOpt('api_insecure',
                default=False,
                help='Allow to perform insecure SSL requests to cinder',
                deprecated_group='DEFAULT',
                deprecated_name='cinder_api_insecure'),
    cfg.BoolOpt('cross_az_attach',
                default=True,
                help='Allow attach between instance and volume in different '
                     'availability zones.',
                deprecated_group='DEFAULT',
                deprecated_name='cinder_cross_az_attach'),
]

CONF = cfg.CONF
# cinder_opts options in the DEFAULT group were deprecated in Juno
CONF.register_opts(cinder_opts, group='cinder')

LOG = logging.getLogger(__name__)

CINDER_URL = None


def cinderclient(context):
    global CINDER_URL
    version = get_cinder_client_version(context)
    c = cinder_client.Client(version,
                             context.user_id,
                             context.auth_token,
                             project_id=context.project_id,
                             auth_url=CINDER_URL,
                             insecure=CONF.cinder.api_insecure,
                             retries=CONF.cinder.http_retries,
                             timeout=CONF.cinder.http_timeout,
                             cacert=CONF.cinder.ca_certificates_file)
    # noauth extracts user_id:project_id from auth_token
    c.client.auth_token = context.auth_token or '%s:%s' % (context.user_id,
                                                           context.project_id)
    c.client.management_url = CINDER_URL
    return c


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

    if vol.attachments:
        att = vol.attachments[0]
        d['attach_status'] = 'attached'
        d['instance_uuid'] = att['server_id']
        d['mountpoint'] = att['device']
    else:
        d['attach_status'] = 'detached'
    # NOTE(dzyu) volume(cinder) v2 API uses 'name' instead of 'display_name',
    # and use 'description' instead of 'display_description' for volume.
    if hasattr(vol, 'display_name'):
        d['display_name'] = vol.display_name
        d['display_description'] = vol.display_description
    else:
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

    return d


def _untranslate_snapshot_summary_view(context, snapshot):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = snapshot.id
    d['status'] = snapshot.status
    d['progress'] = snapshot.progress
    d['size'] = snapshot.size
    d['created_at'] = snapshot.created_at

    # NOTE(dzyu) volume(cinder) v2 API uses 'name' instead of 'display_name',
    # 'description' instead of 'display_description' for snapshot.
    if hasattr(snapshot, 'display_name'):
        d['display_name'] = snapshot.display_name
        d['display_description'] = snapshot.display_description
    else:
        d['display_name'] = snapshot.name
        d['display_description'] = snapshot.description

    d['volume_id'] = snapshot.volume_id
    d['project_id'] = snapshot.project_id
    d['volume_size'] = snapshot.size

    return d


def translate_volume_exception(method):
    """Transforms the exception for the volume but keeps its traceback intact.
    """
    def wrapper(self, ctx, volume_id, *args, **kwargs):
        try:
            res = method(self, ctx, volume_id, *args, **kwargs)
        except cinder_exception.ClientException:
            exc_type, exc_value, exc_trace = sys.exc_info()
            if isinstance(exc_value, cinder_exception.NotFound):
                exc_value = exception.VolumeNotFound(volume_id=volume_id)
            elif isinstance(exc_value, cinder_exception.BadRequest):
                exc_value = exception.InvalidInput(reason=exc_value.message)
            raise exc_value, None, exc_trace
        except cinder_exception.ConnectionError:
            exc_type, exc_value, exc_trace = sys.exc_info()
            exc_value = exception.CinderConnectionFailed(
                                                   reason=exc_value.message)
            raise exc_value, None, exc_trace
        return res
    return wrapper


def translate_snapshot_exception(method):
    """Transforms the exception for the snapshot but keeps its traceback
       intact.
    """
    def wrapper(self, ctx, snapshot_id, *args, **kwargs):
        try:
            res = method(self, ctx, snapshot_id, *args, **kwargs)
        except cinder_exception.ClientException:
            exc_type, exc_value, exc_trace = sys.exc_info()
            if isinstance(exc_value, cinder_exception.NotFound):
                exc_value = exception.SnapshotNotFound(snapshot_id=snapshot_id)
            raise exc_value, None, exc_trace
        except cinder_exception.ConnectionError:
            exc_type, exc_value, exc_trace = sys.exc_info()
            exc_value = exception.CinderConnectionFailed(
                                                  reason=exc_value.message)
            raise exc_value, None, exc_trace
        return res
    return wrapper


def get_cinder_client_version(context):
    """Parse cinder client version by endpoint url.

    :param context: Nova auth context.
    :return: str value(1 or 2).
    """
    global CINDER_URL
    # FIXME: the cinderclient ServiceCatalog object is mis-named.
    #        It actually contains the entire access blob.
    # Only needed parts of the service catalog are passed in, see
    # nova/context.py.
    compat_catalog = {
        'access': {'serviceCatalog': context.service_catalog or []}
    }
    sc = service_catalog.ServiceCatalog(compat_catalog)
    if CONF.cinder.endpoint_template:
        url = CONF.cinder.endpoint_template % context.to_dict()
    else:
        info = CONF.cinder.catalog_info
        service_type, service_name, endpoint_type = info.split(':')
        # extract the region if set in configuration
        if CONF.cinder.os_region_name:
            attr = 'region'
            filter_value = CONF.cinder.os_region_name
        else:
            attr = None
            filter_value = None
        url = sc.url_for(attr=attr,
                         filter_value=filter_value,
                         service_type=service_type,
                         service_name=service_name,
                         endpoint_type=endpoint_type)
    LOG.debug('Cinderclient connection created using URL: %s', url)

    valid_versions = ['v1', 'v2']
    magic_tuple = urlparse.urlsplit(url)
    scheme, netloc, path, query, frag = magic_tuple
    components = path.split("/")
    for version in valid_versions:
        if version in components[1]:
            version = version[1:]

            if not CINDER_URL and version == '1':
                msg = _LW('Cinder V1 API is deprecated as of the Juno '
                          'release, and Nova is still configured to use it. '
                          'Enable the V2 API in Cinder and set '
                          'cinder_catalog_info in nova.conf to use it.')
                LOG.warn(msg)

            CINDER_URL = url
            return version
    msg = _("Invalid client version, must be one of: %s") % valid_versions
    raise cinder_exception.UnsupportedVersion(msg)


class API(object):
    """API for interacting with the volume manager."""

    @translate_volume_exception
    def get(self, context, volume_id):
        item = cinderclient(context).volumes.get(volume_id)
        return _untranslate_volume_summary_view(context, item)

    def get_all(self, context, search_opts=None):
        search_opts = search_opts or {}
        items = cinderclient(context).volumes.list(detailed=True)
        rval = []

        for item in items:
            rval.append(_untranslate_volume_summary_view(context, item))

        return rval

    def check_attached(self, context, volume):
        if volume['status'] != "in-use":
            msg = _("status must be 'in-use'")
            raise exception.InvalidVolume(reason=msg)

    def check_attach(self, context, volume, instance=None):
        # TODO(vish): abstract status checking?
        if volume['status'] != "available":
            msg = _("status must be 'available'")
            raise exception.InvalidVolume(reason=msg)
        if volume['attach_status'] == "attached":
            msg = _("already attached")
            raise exception.InvalidVolume(reason=msg)
        if instance and not CONF.cinder.cross_az_attach:
            # NOTE(sorrison): If instance is on a host we match against it's AZ
            #                 else we check the intended AZ
            if instance.get('host'):
                instance_az = az.get_instance_availability_zone(
                    context, instance)
            else:
                instance_az = instance['availability_zone']
            if instance_az != volume['availability_zone']:
                msg = _("Instance and volume not in same availability_zone")
                raise exception.InvalidVolume(reason=msg)

    def check_detach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] == "available":
            msg = _("already detached")
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
    def detach(self, context, volume_id):
        cinderclient(context).volumes.detach(volume_id)

    @translate_volume_exception
    def initialize_connection(self, context, volume_id, connector):
        return cinderclient(context).volumes.initialize_connection(volume_id,
                                                                   connector)

    @translate_volume_exception
    def terminate_connection(self, context, volume_id, connector):
        return cinderclient(context).volumes.terminate_connection(volume_id,
                                                                  connector)

    def migrate_volume_completion(self, context, old_volume_id, new_volume_id,
                                  error=False):
        return cinderclient(context).volumes.migrate_volume_completion(
            old_volume_id, new_volume_id, error)

    def create(self, context, size, name, description, snapshot=None,
               image_id=None, volume_type=None, metadata=None,
               availability_zone=None):

        if snapshot is not None:
            snapshot_id = snapshot['id']
        else:
            snapshot_id = None

        kwargs = dict(snapshot_id=snapshot_id,
                      volume_type=volume_type,
                      user_id=context.user_id,
                      project_id=context.project_id,
                      availability_zone=availability_zone,
                      metadata=metadata,
                      imageRef=image_id)

        version = get_cinder_client_version(context)
        if version == '1':
            kwargs['display_name'] = name
            kwargs['display_description'] = description
        elif version == '2':
            kwargs['name'] = name
            kwargs['description'] = description

        try:
            item = cinderclient(context).volumes.create(size, **kwargs)
            return _untranslate_volume_summary_view(context, item)
        except cinder_exception.OverLimit:
            raise exception.OverQuota(overs='volumes')
        except cinder_exception.BadRequest as e:
            raise exception.InvalidInput(reason=unicode(e))

    @translate_volume_exception
    def delete(self, context, volume_id):
        cinderclient(context).volumes.delete(volume_id)

    @translate_volume_exception
    def update(self, context, volume_id, fields):
        raise NotImplementedError()

    @translate_snapshot_exception
    def get_snapshot(self, context, snapshot_id):
        item = cinderclient(context).volume_snapshots.get(snapshot_id)
        return _untranslate_snapshot_summary_view(context, item)

    def get_all_snapshots(self, context):
        items = cinderclient(context).volume_snapshots.list(detailed=True)
        rvals = []

        for item in items:
            rvals.append(_untranslate_snapshot_summary_view(context, item))

        return rvals

    @translate_volume_exception
    def create_snapshot(self, context, volume_id, name, description):
        item = cinderclient(context).volume_snapshots.create(volume_id,
                                                             False,
                                                             name,
                                                             description)
        return _untranslate_snapshot_summary_view(context, item)

    @translate_volume_exception
    def create_snapshot_force(self, context, volume_id, name, description):
        item = cinderclient(context).volume_snapshots.create(volume_id,
                                                             True,
                                                             name,
                                                             description)

        return _untranslate_snapshot_summary_view(context, item)

    @translate_snapshot_exception
    def delete_snapshot(self, context, snapshot_id):
        cinderclient(context).volume_snapshots.delete(snapshot_id)

    def get_volume_encryption_metadata(self, context, volume_id):
        return cinderclient(context).volumes.get_encryption_metadata(volume_id)

    @translate_volume_exception
    def get_volume_metadata(self, context, volume_id):
        vol = cinderclient(context).volumes.get(volume_id)
        return vol.metadata

    @translate_volume_exception
    def delete_volume_metadata(self, context, volume_id, keys):
        cinderclient(context).volumes.delete_metadata(volume_id, keys)

    @translate_volume_exception
    def update_volume_metadata(self, context, volume_id,
                               metadata, delete=False):
        if delete:
            # Completely replace volume metadata with one given
            return cinderclient(context).volumes.update_all_metadata(
                volume_id, metadata)
        else:
            return cinderclient(context).volumes.set_metadata(
                volume_id, metadata)

    @translate_volume_exception
    def get_volume_metadata_value(self, context, volume_id, key):
        vol = cinderclient(context).volumes.get(volume_id)
        return vol.metadata.get(key)

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
