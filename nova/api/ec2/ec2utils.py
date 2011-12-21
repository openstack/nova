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

from nova import exception
from nova import flags
from nova import ipv6
from nova import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.ec2.ec2utils")


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


def get_ip_info_for_instance(context, instance):
    """Return a list of all fixed IPs for an instance"""

    ip_info = dict(fixed_ips=[], fixed_ip6s=[], floating_ips=[])

    fixed_ips = instance['fixed_ips']
    for fixed_ip in fixed_ips:
        fixed_addr = fixed_ip['address']
        network = fixed_ip.get('network')
        vif = fixed_ip.get('virtual_interface')
        if not network or not vif:
            name = instance['name']
            ip = fixed_ip['address']
            LOG.warn(_("Instance %(name)s has stale IP "
                    "address: %(ip)s (no network or vif)") % locals())
            continue
        cidr_v6 = network.get('cidr_v6')
        if FLAGS.use_ipv6 and cidr_v6:
            ipv6_addr = ipv6.to_global(cidr_v6, vif['address'],
                    network['project_id'])
            if ipv6_addr not in ip_info['fixed_ip6s']:
                ip_info['fixed_ip6s'].append(ipv6_addr)

        for floating_ip in fixed_ip.get('floating_ips', []):
            float_addr = floating_ip['address']
            ip_info['floating_ips'].append(float_addr)
        ip_info['fixed_ips'].append(fixed_addr)
    return ip_info


def get_availability_zone_by_host(services, host):
    if len(services) > 0:
        return services[0]['availability_zone']
    return 'unknown zone'


def id_to_ec2_id(instance_id, template='i-%08x'):
    """Convert an instance ID (int) to an ec2 ID (i-[base 16 number])"""
    return template % int(instance_id)


def id_to_ec2_snap_id(instance_id):
    """Convert an snapshot ID (int) to an ec2 snapshot ID
    (snap-[base 16 number])"""
    return id_to_ec2_id(instance_id, 'snap-%08x')


def id_to_ec2_vol_id(instance_id):
    """Convert an volume ID (int) to an ec2 volume ID (vol-[base 16 number])"""
    return id_to_ec2_id(instance_id, 'vol-%08x')


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
    if len(value) == 0:
        return ''
    if value == 'None':
        return None
    lowered_value = value.lower()
    if lowered_value == 'true':
        return True
    if lowered_value == 'false':
        return False
    valueneg = value[1:] if value[0] == '-' else value
    if valueneg == '0':
        return 0
    if valueneg == '':
        return value
    if valueneg[0] == '0':
        if valueneg[1] in 'xX':
            return int(value, 16)
        elif valueneg[1] in 'bB':
            return int(value, 2)
        else:
            try:
                return int(value, 8)
            except ValueError:
                pass
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return complex(value)
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
