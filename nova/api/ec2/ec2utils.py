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

from oslo_utils import uuidutils

from nova import cache_utils
from nova import context
from nova import exception
from nova.network import model as network_model
from nova import objects

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


def glance_id_to_ec2_id(context, glance_id, image_type='ami'):
    image_id = glance_id_to_id(context, glance_id)
    if image_id is None:
        return
    return image_ec2_id(image_id, image_type=image_type)


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
