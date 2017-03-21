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

import functools
import re

from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six

from nova import cache_utils
from nova import context
from nova import exception
from nova.i18n import _
from nova.network import model as network_model
from nova import objects
from nova.objects import base as obj_base

LOG = logging.getLogger(__name__)
# NOTE(vish): cache mapping for one week
_CACHE_TIME = 7 * 24 * 60 * 60
_CACHE = None


def memoize(func):
    @functools.wraps(func)
    def memoizer(context, reqid):
        global _CACHE
        if not _CACHE:
            _CACHE = cache_utils.get_client(expiration_time=_CACHE_TIME)
        key = "%s:%s" % (func.__name__, reqid)
        key = str(key)
        value = _CACHE.get(key)
        if value is None:
            value = func(context, reqid)
            _CACHE.set(key, value)
        return value
    return memoizer


def reset_cache():
    global _CACHE
    _CACHE = None


def image_type(image_type):
    """Converts to a three letter image type.

    aki, kernel => aki
    ari, ramdisk => ari
    anything else => ami

    """
    if image_type == 'kernel':
        return 'aki'
    if image_type == 'ramdisk':
        return 'ari'
    if image_type not in ['aki', 'ari']:
        return 'ami'
    return image_type


def resource_type_from_id(context, resource_id):
    """Get resource type by ID

    Returns a string representation of the Amazon resource type, if known.
    Returns None on failure.

    :param context: context under which the method is called
    :param resource_id: resource_id to evaluate
    """

    known_types = {
        'i': 'instance',
        'r': 'reservation',
        'vol': 'volume',
        'snap': 'snapshot',
        'ami': 'image',
        'aki': 'image',
        'ari': 'image'
    }

    type_marker = resource_id.split('-')[0]

    return known_types.get(type_marker)


@memoize
def id_to_glance_id(context, image_id):
    """Convert an internal (db) id to a glance id."""
    return objects.S3ImageMapping.get_by_id(context, image_id).uuid


@memoize
def glance_id_to_id(context, glance_id):
    """Convert a glance id to an internal (db) id."""
    if not glance_id:
        return
    try:
        return objects.S3ImageMapping.get_by_uuid(context, glance_id).id
    except exception.NotFound:
        s3imap = objects.S3ImageMapping(context, uuid=glance_id)
        s3imap.create()
        return s3imap.id


def ec2_id_to_glance_id(context, ec2_id):
    image_id = ec2_id_to_id(ec2_id)
    return id_to_glance_id(context, image_id)


def glance_id_to_ec2_id(context, glance_id, image_type='ami'):
    image_id = glance_id_to_id(context, glance_id)
    if image_id is None:
        return
    return image_ec2_id(image_id, image_type=image_type)


def ec2_id_to_id(ec2_id):
    """Convert an ec2 ID (i-[base 16 number]) to an instance id (int)."""
    try:
        return int(ec2_id.split('-')[-1], 16)
    except ValueError:
        raise exception.InvalidEc2Id(ec2_id=ec2_id)


def image_ec2_id(image_id, image_type='ami'):
    """Returns image ec2_id using id and three letter type."""
    template = image_type + '-%08x'
    return id_to_ec2_id(image_id, template=template)


def get_ip_info_for_instance_from_nw_info(nw_info):
    if not isinstance(nw_info, network_model.NetworkInfo):
        nw_info = network_model.NetworkInfo.hydrate(nw_info)

    ip_info = {}
    fixed_ips = nw_info.fixed_ips()
    ip_info['fixed_ips'] = [ip['address'] for ip in fixed_ips
                                          if ip['version'] == 4]
    ip_info['fixed_ip6s'] = [ip['address'] for ip in fixed_ips
                                           if ip['version'] == 6]
    ip_info['floating_ips'] = [ip['address'] for ip in nw_info.floating_ips()]

    return ip_info


def get_ip_info_for_instance(context, instance):
    """Return a dictionary of IP information for an instance."""

    if isinstance(instance, obj_base.NovaObject):
        nw_info = instance.info_cache.network_info
    else:
        # FIXME(comstud): Temporary as we transition to objects.
        info_cache = instance.info_cache or {}
        nw_info = info_cache.get('network_info')
    # Make sure empty response is turned into the model
    if not nw_info:
        nw_info = []
    return get_ip_info_for_instance_from_nw_info(nw_info)


def id_to_ec2_id(instance_id, template='i-%08x'):
    """Convert an instance ID (int) to an ec2 ID (i-[base 16 number])."""
    return template % int(instance_id)


def id_to_ec2_inst_id(instance_id):
    """Get or create an ec2 instance ID (i-[base 16 number]) from uuid."""
    if instance_id is None:
        return None
    elif uuidutils.is_uuid_like(instance_id):
        ctxt = context.get_admin_context()
        int_id = get_int_id_from_instance_uuid(ctxt, instance_id)
        return id_to_ec2_id(int_id)
    else:
        return id_to_ec2_id(instance_id)


def ec2_inst_id_to_uuid(context, ec2_id):
    """"Convert an instance id to uuid."""
    int_id = ec2_id_to_id(ec2_id)
    return get_instance_uuid_from_int_id(context, int_id)


@memoize
def get_instance_uuid_from_int_id(context, int_id):
    imap = objects.EC2InstanceMapping.get_by_id(context, int_id)
    return imap.uuid


def id_to_ec2_snap_id(snapshot_id):
    """Get or create an ec2 volume ID (vol-[base 16 number]) from uuid."""
    if uuidutils.is_uuid_like(snapshot_id):
        ctxt = context.get_admin_context()
        int_id = get_int_id_from_snapshot_uuid(ctxt, snapshot_id)
        return id_to_ec2_id(int_id, 'snap-%08x')
    else:
        return id_to_ec2_id(snapshot_id, 'snap-%08x')


def id_to_ec2_vol_id(volume_id):
    """Get or create an ec2 volume ID (vol-[base 16 number]) from uuid."""
    if uuidutils.is_uuid_like(volume_id):
        ctxt = context.get_admin_context()
        int_id = get_int_id_from_volume_uuid(ctxt, volume_id)
        return id_to_ec2_id(int_id, 'vol-%08x')
    else:
        return id_to_ec2_id(volume_id, 'vol-%08x')


def ec2_vol_id_to_uuid(ec2_id):
    """Get the corresponding UUID for the given ec2-id."""
    ctxt = context.get_admin_context()

    # NOTE(jgriffith) first strip prefix to get just the numeric
    int_id = ec2_id_to_id(ec2_id)
    return get_volume_uuid_from_int_id(ctxt, int_id)


_ms_time_regex = re.compile('^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3,6}Z$')


def status_to_ec2_attach_status(volume):
    """Get the corresponding EC2 attachment state.

    According to EC2 API, the valid attachment status in response is:
    attaching | attached | detaching | detached
    """
    volume_status = volume.get('status')
    attach_status = volume.get('attach_status')
    if volume_status in ('attaching', 'detaching'):
        ec2_attach_status = volume_status
    elif attach_status in ('attached', 'detached'):
        ec2_attach_status = attach_status
    else:
        msg = _("Unacceptable attach status:%s for ec2 API.") % attach_status
        raise exception.Invalid(msg)
    return ec2_attach_status


def is_ec2_timestamp_expired(request, expires=None):
    """Checks the timestamp or expiry time included in an EC2 request
    and returns true if the request is expired
    """
    timestamp = request.get('Timestamp')
    expiry_time = request.get('Expires')

    def parse_strtime(strtime):
        if _ms_time_regex.match(strtime):
            # NOTE(MotoKen): time format for aws-sdk-java contains millisecond
            time_format = "%Y-%m-%dT%H:%M:%S.%fZ"
        else:
            time_format = "%Y-%m-%dT%H:%M:%SZ"
        return timeutils.parse_strtime(strtime, time_format)

    try:
        if timestamp and expiry_time:
            msg = _("Request must include either Timestamp or Expires,"
                    " but cannot contain both")
            LOG.error(msg)
            raise exception.InvalidRequest(msg)
        elif expiry_time:
            query_time = parse_strtime(expiry_time)
            return timeutils.is_older_than(query_time, -1)
        elif timestamp:
            query_time = parse_strtime(timestamp)

            # Check if the difference between the timestamp in the request
            # and the time on our servers is larger than 5 minutes, the
            # request is too old (or too new).
            if query_time and expires:
                return timeutils.is_older_than(query_time, expires) or \
                       timeutils.is_newer_than(query_time, expires)
        return False
    except ValueError:
        LOG.info("Timestamp is invalid.")
        return True


@memoize
def get_int_id_from_instance_uuid(context, instance_uuid):
    if instance_uuid is None:
        return
    try:
        imap = objects.EC2InstanceMapping.get_by_uuid(context, instance_uuid)
        return imap.id
    except exception.NotFound:
        imap = objects.EC2InstanceMapping(context)
        imap.uuid = instance_uuid
        imap.create()
        return imap.id


@memoize
def get_int_id_from_volume_uuid(context, volume_uuid):
    if volume_uuid is None:
        return
    try:
        vmap = objects.EC2VolumeMapping.get_by_uuid(context, volume_uuid)
        return vmap.id
    except exception.NotFound:
        vmap = objects.EC2VolumeMapping(context)
        vmap.uuid = volume_uuid
        vmap.create()
        return vmap.id


@memoize
def get_volume_uuid_from_int_id(context, int_id):
    vmap = objects.EC2VolumeMapping.get_by_id(context, int_id)
    return vmap.uuid


def ec2_snap_id_to_uuid(ec2_id):
    """Get the corresponding UUID for the given ec2-id."""
    ctxt = context.get_admin_context()

    # NOTE(jgriffith) first strip prefix to get just the numeric
    int_id = ec2_id_to_id(ec2_id)
    return get_snapshot_uuid_from_int_id(ctxt, int_id)


@memoize
def get_int_id_from_snapshot_uuid(context, snapshot_uuid):
    if snapshot_uuid is None:
        return
    try:
        smap = objects.EC2SnapshotMapping.get_by_uuid(context, snapshot_uuid)
        return smap.id
    except exception.NotFound:
        smap = objects.EC2SnapshotMapping(context, uuid=snapshot_uuid)
        smap.create()
        return smap.id


@memoize
def get_snapshot_uuid_from_int_id(context, int_id):
    smap = objects.EC2SnapshotMapping.get_by_id(context, int_id)
    return smap.uuid


_c2u = re.compile('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))')


def camelcase_to_underscore(str):
    return _c2u.sub(r'_\1', str).lower().strip('_')


def _try_convert(value):
    """Return a non-string from a string or unicode, if possible.

    ============= =====================================================
    When value is returns
    ============= =====================================================
    zero-length   ''
    'None'        None
    'True'        True case insensitive
    'False'       False case insensitive
    '0', '-0'     0
    0xN, -0xN     int from hex (positive) (N is any number)
    0bN, -0bN     int from binary (positive) (N is any number)
    *             try conversion to int, float, complex, fallback value

    """
    def _negative_zero(value):
        epsilon = 1e-7
        return 0 if abs(value) < epsilon else value

    if len(value) == 0:
        return ''
    if value == 'None':
        return None
    lowered_value = value.lower()
    if lowered_value == 'true':
        return True
    if lowered_value == 'false':
        return False
    for prefix, base in [('0x', 16), ('0b', 2), ('0', 8), ('', 10)]:
        try:
            if lowered_value.startswith((prefix, "-" + prefix)):
                return int(lowered_value, base)
        except ValueError:
            pass
    try:
        return _negative_zero(float(value))
    except ValueError:
        return value


def dict_from_dotted_str(items):
    """parse multi dot-separated argument into dict.
    EBS boot uses multi dot-separated arguments like
    BlockDeviceMapping.1.DeviceName=snap-id
    Convert the above into
    {'block_device_mapping': {'1': {'device_name': snap-id}}}
    """
    args = {}
    for key, value in items:
        parts = key.split(".")
        key = str(camelcase_to_underscore(parts[0]))
        if isinstance(value, six.string_types):
            # NOTE(vish): Automatically convert strings back
            #             into their respective values
            value = _try_convert(value)

            if len(parts) > 1:
                d = args.get(key, {})
                args[key] = d
                for k in parts[1:-1]:
                    k = camelcase_to_underscore(k)
                    v = d.get(k, {})
                    d[k] = v
                    d = v
                d[camelcase_to_underscore(parts[-1])] = value
            else:
                args[key] = value

    return args


def search_opts_from_filters(filters):
    return {f['name'].replace('-', '_'): f['value']['1']
            for f in filters if f['value']['1']} if filters else {}


def regex_from_ec2_regex(ec2_re):
    """Converts an EC2-style regex to a python regex.
    Approach is based on python fnmatch.
    """

    iter_ec2_re = iter(ec2_re)

    py_re = ''
    for char in iter_ec2_re:
        if char == '*':
            py_re += '.*'
        elif char == '?':
            py_re += '.'
        elif char == '\\':
            try:
                next_char = next(iter_ec2_re)
            except StopIteration:
                next_char = ''
            if next_char == '*' or next_char == '?':
                py_re += '[%s]' % next_char
            else:
                py_re += '\\\\' + next_char
        else:
            py_re += re.escape(char)
    return '\A%s\Z(?s)' % py_re
