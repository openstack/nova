# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import re

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.network import model as network_model
from nova.openstack.common import log as logging
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


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


def id_to_glance_id(context, image_id):
    """Convert an internal (db) id to a glance id."""
    return db.s3_image_get(context, image_id)['uuid']


def glance_id_to_id(context, glance_id):
    """Convert a glance id to an internal (db) id."""
    if glance_id is None:
        return
    try:
        return db.s3_image_get_by_uuid(context, glance_id)['id']
    except exception.NotFound:
        return db.s3_image_create(context, glance_id)['id']


def ec2_id_to_glance_id(context, ec2_id):
    image_id = ec2_id_to_id(ec2_id)
    return id_to_glance_id(context, image_id)


def glance_id_to_ec2_id(context, glance_id, image_type='ami'):
    image_id = glance_id_to_id(context, glance_id)
    return image_ec2_id(image_id, image_type=image_type)


def ec2_id_to_id(ec2_id):
    """Convert an ec2 ID (i-[base 16 number]) to an instance id (int)"""
    try:
        return int(ec2_id.split('-')[-1], 16)
    except ValueError:
        raise exception.InvalidEc2Id(ec2_id=ec2_id)


def image_ec2_id(image_id, image_type='ami'):
    """Returns image ec2_id using id and three letter type."""
    template = image_type + '-%08x'
    try:
        return id_to_ec2_id(image_id, template=template)
    except ValueError:
        #TODO(wwolf): once we have ec2_id -> glance_id mapping
        # in place, this wont be necessary
        return "ami-00000000"


def get_ip_info_for_instance_from_nw_info(nw_info):
    ip_info = {}
    fixed_ips = nw_info.fixed_ips()
    ip_info['fixed_ips'] = [ip['address'] for ip in fixed_ips
                                          if ip['version'] == 4]
    ip_info['fixed_ip6s'] = [ip['address'] for ip in fixed_ips
                                           if ip['version'] == 6]
    ip_info['floating_ips'] = [ip['address'] for ip in nw_info.floating_ips()]

    return ip_info


def get_ip_info_for_instance(context, instance):
    """Return a dictionary of IP information for an instance"""

    info_cache = instance['info_cache'] or {}
    cached_nwinfo = info_cache.get('network_info')
    # Make sure empty response is turned into []
    if not cached_nwinfo:
        cached_nwinfo = []
    nw_info = network_model.NetworkInfo.hydrate(cached_nwinfo)
    return get_ip_info_for_instance_from_nw_info(nw_info)


def get_availability_zone_by_host(services, host):
    if len(services) > 0:
        return services[0]['availability_zone']
    return 'unknown zone'


def id_to_ec2_id(instance_id, template='i-%08x'):
    """Convert an instance ID (int) to an ec2 ID (i-[base 16 number])"""
    return template % int(instance_id)


def id_to_ec2_inst_id(instance_id):
    """Get or create an ec2 instance ID (i-[base 16 number]) from uuid."""
    if instance_id is None:
        return None
    elif utils.is_uuid_like(instance_id):
        ctxt = context.get_admin_context()
        int_id = get_int_id_from_instance_uuid(ctxt, instance_id)
        return id_to_ec2_id(int_id)
    else:
        return id_to_ec2_id(instance_id)


def ec2_inst_id_to_uuid(context, ec2_id):
    """"Convert an instance id to uuid."""
    int_id = ec2_id_to_id(ec2_id)
    return get_instance_uuid_from_int_id(context, int_id)


def get_instance_uuid_from_int_id(context, int_id):
    return db.get_instance_uuid_by_ec2_id(context, int_id)


def id_to_ec2_snap_id(snapshot_id):
    """Get or create an ec2 volume ID (vol-[base 16 number]) from uuid."""
    if utils.is_uuid_like(snapshot_id):
        ctxt = context.get_admin_context()
        int_id = get_int_id_from_snapshot_uuid(ctxt, snapshot_id)
        return id_to_ec2_id(int_id, 'snap-%08x')
    else:
        return id_to_ec2_id(snapshot_id, 'snap-%08x')


def id_to_ec2_vol_id(volume_id):
    """Get or create an ec2 volume ID (vol-[base 16 number]) from uuid."""
    if utils.is_uuid_like(volume_id):
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


def get_int_id_from_instance_uuid(context, instance_uuid):
    if instance_uuid is None:
        return
    try:
        return db.get_ec2_instance_id_by_uuid(context, instance_uuid)
    except exception.NotFound:
        return db.ec2_instance_create(context, instance_uuid)['id']


def get_int_id_from_volume_uuid(context, volume_uuid):
    if volume_uuid is None:
        return
    try:
        return db.get_ec2_volume_id_by_uuid(context, volume_uuid)
    except exception.NotFound:
        return db.ec2_volume_create(context, volume_uuid)['id']


def get_volume_uuid_from_int_id(context, int_id):
    return db.get_volume_uuid_by_ec2_id(context, int_id)


def ec2_snap_id_to_uuid(ec2_id):
    """Get the corresponding UUID for the given ec2-id."""
    ctxt = context.get_admin_context()

    # NOTE(jgriffith) first strip prefix to get just the numeric
    int_id = ec2_id_to_id(ec2_id)
    return get_snapshot_uuid_from_int_id(ctxt, int_id)


def get_int_id_from_snapshot_uuid(context, snapshot_uuid):
    if snapshot_uuid is None:
        return
    try:
        return db.get_ec2_snapshot_id_by_uuid(context, snapshot_uuid)
    except exception.NotFound:
        return db.ec2_snapshot_create(context, snapshot_uuid)['id']


def get_snapshot_uuid_from_int_id(context, int_id):
    return db.get_snapshot_uuid_by_ec2_id(context, int_id)


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
        if isinstance(value, str) or isinstance(value, unicode):
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
    return dict((f['name'].replace('-', '_'), f['value']['1'])
                for f in filters if f['value']['1']) if filters else {}
