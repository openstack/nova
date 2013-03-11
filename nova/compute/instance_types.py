# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import uuid

from oslo.config import cfg

from nova import context
from nova import db
from nova import exception
from nova.openstack.common.db import exception as db_exc
from nova.openstack.common import log as logging
from nova import utils

instance_type_opts = [
    cfg.StrOpt('default_instance_type',
               default='m1.small',
               help='default instance type to use, testing only'),
]

CONF = cfg.CONF
CONF.register_opts(instance_type_opts)

LOG = logging.getLogger(__name__)

INVALID_NAME_REGEX = re.compile("[^\w\.\- ]")


def _int_or_none(val):
    if val is not None:
        return int(val)


system_metadata_instance_type_props = {
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


def create(name, memory, vcpus, root_gb, ephemeral_gb=None, flavorid=None,
           swap=None, rxtx_factor=None, is_public=True):
    """Creates instance types."""

    if flavorid is None or flavorid == '':
        flavorid = uuid.uuid4()
    if swap is None:
        swap = 0
    if rxtx_factor is None:
        rxtx_factor = 1.0
    if ephemeral_gb is None:
        ephemeral_gb = 0

    kwargs = {
        'memory_mb': memory,
        'vcpus': vcpus,
        'root_gb': root_gb,
        'ephemeral_gb': ephemeral_gb,
        'swap': swap,
        'rxtx_factor': rxtx_factor,
    }

    # ensure name do not exceed 255 characters
    utils.check_string_length(name, 'name', min_length=1, max_length=255)

    # ensure name does not contain any special characters
    invalid_name = INVALID_NAME_REGEX.search(name)
    if invalid_name:
        msg = _("names can only contain [a-zA-Z0-9_.- ]")
        raise exception.InvalidInput(reason=msg)

    # ensure some attributes are integers and greater than or equal to 0
    for option in ['memory_mb', 'vcpus', 'root_gb', 'ephemeral_gb', 'swap']:
        try:
            kwargs[option] = int(kwargs[option])
            assert kwargs[option] >= 0
        except (ValueError, AssertionError):
            msg = _("'%s' argument must be a positive integer") % option
            raise exception.InvalidInput(reason=msg)

    # rxtx_factor should be a positive float
    try:
        kwargs['rxtx_factor'] = float(kwargs['rxtx_factor'])
        assert kwargs['rxtx_factor'] > 0
    except (ValueError, AssertionError):
        msg = _("'rxtx_factor' argument must be a positive float")
        raise exception.InvalidInput(reason=msg)

    # some value are required to be nonzero, not just positive
    for option in ['memory_mb', 'vcpus']:
        try:
            assert kwargs[option] > 0
        except AssertionError:
            msg = _("'%s' argument must be greater than 0") % option
            raise exception.InvalidInput(reason=msg)

    kwargs['name'] = name
    # NOTE(vish): Internally, flavorid is stored as a string but it comes
    #             in through json as an integer, so we convert it here.
    kwargs['flavorid'] = unicode(flavorid)

    # ensure is_public attribute is boolean
    if not utils.is_valid_boolstr(is_public):
        msg = _("is_public must be a boolean")
        raise exception.InvalidInput(reason=msg)
    kwargs['is_public'] = utils.bool_from_str(is_public)

    try:
        return db.instance_type_create(context.get_admin_context(), kwargs)
    except db_exc.DBError, e:
        LOG.exception(_('DB error: %s') % e)
        raise exception.InstanceTypeCreateFailed()


def destroy(name):
    """Marks instance types as deleted."""
    try:
        assert name is not None
        db.instance_type_destroy(context.get_admin_context(), name)
    except (AssertionError, exception.NotFound):
        LOG.exception(_('Instance type %s not found for deletion') % name)
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)


def get_all_types(ctxt=None, inactive=False, filters=None):
    """Get all non-deleted instance_types.

    Pass true as argument if you want deleted instance types returned also.
    """
    if ctxt is None:
        ctxt = context.get_admin_context()

    inst_types = db.instance_type_get_all(
            ctxt, inactive=inactive, filters=filters)

    inst_type_dict = {}
    for inst_type in inst_types:
        inst_type_dict[inst_type['name']] = inst_type
    return inst_type_dict

get_all_flavors = get_all_types


def get_default_instance_type():
    """Get the default instance type."""
    name = CONF.default_instance_type
    return get_instance_type_by_name(name)


def get_instance_type(instance_type_id, ctxt=None, inactive=False):
    """Retrieves single instance type by id."""
    if instance_type_id is None:
        return get_default_instance_type()

    if ctxt is None:
        ctxt = context.get_admin_context()

    if inactive:
        ctxt = ctxt.elevated(read_deleted="yes")

    return db.instance_type_get(ctxt, instance_type_id)


def get_instance_type_by_name(name, ctxt=None):
    """Retrieves single instance type by name."""
    if name is None:
        return get_default_instance_type()

    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.instance_type_get_by_name(ctxt, name)


# TODO(termie): flavor-specific code should probably be in the API that uses
#               flavors.
def get_instance_type_by_flavor_id(flavorid, ctxt=None, read_deleted="yes"):
    """Retrieve instance type by flavorid.

    :raises: FlavorNotFound
    """
    if ctxt is None:
        ctxt = context.get_admin_context(read_deleted=read_deleted)

    return db.instance_type_get_by_flavor_id(ctxt, flavorid)


def get_instance_type_access_by_flavor_id(flavorid, ctxt=None):
    """Retrieve instance type access list by flavor id."""
    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.instance_type_access_get_by_flavor_id(ctxt, flavorid)


def add_instance_type_access(flavorid, projectid, ctxt=None):
    """Add instance type access for project."""
    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.instance_type_access_add(ctxt, flavorid, projectid)


def remove_instance_type_access(flavorid, projectid, ctxt=None):
    """Remove instance type access for project."""
    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.instance_type_access_remove(ctxt, flavorid, projectid)


def extract_instance_type(instance, prefix=''):
    """Create an InstanceType-like object from instance's system_metadata
    information."""

    instance_type = {}
    sys_meta = utils.metadata_to_dict(instance['system_metadata'])
    for key, type_fn in system_metadata_instance_type_props.items():
        type_key = '%sinstance_type_%s' % (prefix, key)
        instance_type[key] = type_fn(sys_meta[type_key])
    return instance_type


def save_instance_type_info(metadata, instance_type, prefix=''):
    """Save properties from instance_type into instance's system_metadata,
    in the format of:

      [prefix]instance_type_[key]

    This can be used to update system_metadata in place from a type, as well
    as stash information about another instance_type for later use (such as
    during resize)."""

    for key in system_metadata_instance_type_props.keys():
        to_key = '%sinstance_type_%s' % (prefix, key)
        metadata[to_key] = instance_type[key]
    return metadata


def delete_instance_type_info(metadata, *prefixes):
    """Delete instance_type information from instance's system_metadata
    by prefix."""

    for key in system_metadata_instance_type_props.keys():
        for prefix in prefixes:
            to_key = '%sinstance_type_%s' % (prefix, key)
            del metadata[to_key]
    return metadata
