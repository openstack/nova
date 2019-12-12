# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2011 Ken Pepple
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

"""Built-in instance properties."""

import re

from oslo_utils import strutils
from oslo_utils import uuidutils
import six

import nova.conf
from nova import context
from nova.db import api as db
from nova import exception
from nova.i18n import _
from nova import objects
from nova import utils

CONF = nova.conf.CONF

# Validate extra specs key names.
VALID_EXTRASPEC_NAME_REGEX = re.compile(r"[\w\.\- :]+$", re.UNICODE)


def _int_or_none(val):
    if val is not None:
        return int(val)


system_metadata_flavor_props = {
    'id': int,
    'name': str,
    'memory_mb': int,
    'vcpus': int,
    'root_gb': int,
    'ephemeral_gb': int,
    'flavorid': str,
    'swap': int,
    'rxtx_factor': float,
    'vcpu_weight': _int_or_none,
    }


system_metadata_flavor_extra_props = [
    'hw:numa_cpus.', 'hw:numa_mem.',
]


def create(name, memory, vcpus, root_gb, ephemeral_gb=0, flavorid=None,
           swap=0, rxtx_factor=1.0, is_public=True, description=None):
    """Creates flavors."""
    if not flavorid:
        flavorid = uuidutils.generate_uuid()

    kwargs = {
        'memory_mb': memory,
        'vcpus': vcpus,
        'root_gb': root_gb,
        'ephemeral_gb': ephemeral_gb,
        'swap': swap,
        'rxtx_factor': rxtx_factor,
        'description': description
    }

    if isinstance(name, six.string_types):
        name = name.strip()

    # NOTE(vish): Internally, flavorid is stored as a string but it comes
    #             in through json as an integer, so we convert it here.
    flavorid = six.text_type(flavorid)

    # NOTE(wangbo): validate attributes of the creating flavor.
    # ram and vcpus should be positive ( > 0) integers.
    # disk, ephemeral and swap should be non-negative ( >= 0) integers.
    flavor_attributes = {
        'memory_mb': ('ram', 1),
        'vcpus': ('vcpus', 1),
        'root_gb': ('disk', 0),
        'ephemeral_gb': ('ephemeral', 0),
        'swap': ('swap', 0)
    }

    for key, value in flavor_attributes.items():
        kwargs[key] = utils.validate_integer(kwargs[key], value[0], value[1],
                                             db.MAX_INT)

    # rxtx_factor should be a positive float
    try:
        kwargs['rxtx_factor'] = float(kwargs['rxtx_factor'])
        if (kwargs['rxtx_factor'] <= 0 or
                kwargs['rxtx_factor'] > db.SQL_SP_FLOAT_MAX):
            raise ValueError()
    except ValueError:
        msg = (_("'rxtx_factor' argument must be a float between 0 and %g") %
               db.SQL_SP_FLOAT_MAX)
        raise exception.InvalidInput(reason=msg)

    kwargs['name'] = name
    kwargs['flavorid'] = flavorid
    # ensure is_public attribute is boolean
    try:
        kwargs['is_public'] = strutils.bool_from_string(
            is_public, strict=True)
    except ValueError:
        raise exception.InvalidInput(reason=_("is_public must be a boolean"))

    flavor = objects.Flavor(context=context.get_admin_context(), **kwargs)
    flavor.create()
    return flavor


# TODO(termie): flavor-specific code should probably be in the API that uses
#               flavors.
def get_flavor_by_flavor_id(flavorid, ctxt=None, read_deleted="yes"):
    """Retrieve flavor by flavorid.

    :raises: FlavorNotFound
    """
    if ctxt is None:
        ctxt = context.get_admin_context(read_deleted=read_deleted)

    return objects.Flavor.get_by_flavor_id(ctxt, flavorid, read_deleted)


# NOTE(danms): This method is deprecated, do not use it!
# Use instance.{old_,new_,}flavor instead, as instances no longer
# have flavor information in system_metadata.
def extract_flavor(instance, prefix=''):
    """Create a Flavor object from instance's system_metadata
    information.
    """

    flavor = objects.Flavor()
    sys_meta = utils.instance_sys_meta(instance)

    if not sys_meta:
        return None

    for key in system_metadata_flavor_props.keys():
        type_key = '%sinstance_type_%s' % (prefix, key)
        setattr(flavor, key, sys_meta[type_key])

    # NOTE(danms): We do NOT save all of extra_specs, but only the
    # NUMA-related ones that we need to avoid an uglier alternative. This
    # should be replaced by a general split-out of flavor information from
    # system_metadata very soon.
    extra_specs = [(k, v) for k, v in sys_meta.items()
                   if k.startswith('%sinstance_type_extra_' % prefix)]
    if extra_specs:
        flavor.extra_specs = {}
        for key, value in extra_specs:
            extra_key = key[len('%sinstance_type_extra_' % prefix):]
            flavor.extra_specs[extra_key] = value

    return flavor


# NOTE(danms): This method is deprecated, do not use it!
# Use instance.{old_,new_,}flavor instead, as instances no longer
# have flavor information in system_metadata.
def save_flavor_info(metadata, instance_type, prefix=''):
    """Save properties from instance_type into instance's system_metadata,
    in the format of:

      [prefix]instance_type_[key]

    This can be used to update system_metadata in place from a type, as well
    as stash information about another instance_type for later use (such as
    during resize).
    """

    for key in system_metadata_flavor_props.keys():
        to_key = '%sinstance_type_%s' % (prefix, key)
        metadata[to_key] = instance_type[key]

    # NOTE(danms): We do NOT save all of extra_specs here, but only the
    # NUMA-related ones that we need to avoid an uglier alternative. This
    # should be replaced by a general split-out of flavor information from
    # system_metadata very soon.
    extra_specs = instance_type.get('extra_specs', {})
    for extra_prefix in system_metadata_flavor_extra_props:
        for key in extra_specs:
            if key.startswith(extra_prefix):
                to_key = '%sinstance_type_extra_%s' % (prefix, key)
                metadata[to_key] = extra_specs[key]

    return metadata


def validate_extra_spec_keys(key_names_list):
    for key_name in key_names_list:
        if not VALID_EXTRASPEC_NAME_REGEX.match(key_name):
            expl = _('Key Names can only contain alphanumeric characters, '
                     'periods, dashes, underscores, colons and spaces.')
            raise exception.InvalidInput(message=expl)
