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
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova.pci import pci_request
from nova import utils

flavor_opts = [
    cfg.StrOpt('default_flavor',
               # Deprecated in Havana
               deprecated_name='default_instance_type',
               default='m1.small',
               help='default flavor to use for the EC2 API only. The Nova API '
               'does not support a default flavor.'),
]

CONF = cfg.CONF
CONF.register_opts(flavor_opts)

LOG = logging.getLogger(__name__)

VALID_NAME_OR_ID_REGEX = re.compile("^[\w\.\- ]*$")


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


def create(name, memory, vcpus, root_gb, ephemeral_gb=0, flavorid=None,
           swap=0, rxtx_factor=1.0, is_public=True):
    """Creates flavors."""
    if not flavorid:
        flavorid = uuid.uuid4()

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
    valid_name = VALID_NAME_OR_ID_REGEX.search(name)
    if not valid_name:
        msg = _("names can only contain [a-zA-Z0-9_.- ]")
        raise exception.InvalidInput(reason=msg)

    # NOTE(vish): Internally, flavorid is stored as a string but it comes
    #             in through json as an integer, so we convert it here.
    flavorid = unicode(flavorid)

    # ensure leading/trailing whitespaces not present.
    if flavorid.strip() != flavorid:
        msg = _("id cannot contain leading and/or trailing whitespace(s)")
        raise exception.InvalidInput(reason=msg)

    # ensure flavor id does not exceed 255 characters
    utils.check_string_length(flavorid, 'id', min_length=1,
                              max_length=255)

    # ensure flavor id does not contain any special characters
    valid_flavor_id = VALID_NAME_OR_ID_REGEX.search(flavorid)
    if not valid_flavor_id:
        msg = _("id can only contain [a-zA-Z0-9_.- ]")
        raise exception.InvalidInput(reason=msg)

    # Some attributes are positive ( > 0) integers
    for option in ['memory_mb', 'vcpus']:
        try:
            if int(str(kwargs[option])) <= 0:
                raise ValueError()
            kwargs[option] = int(kwargs[option])
        except (ValueError, TypeError):
            msg = _("'%s' argument must be a positive integer") % option
            raise exception.InvalidInput(reason=msg)

    # Some attributes are non-negative ( >= 0) integers
    for option in ['root_gb', 'ephemeral_gb', 'swap']:
        try:
            if int(str(kwargs[option])) < 0:
                raise ValueError()
            kwargs[option] = int(kwargs[option])
        except (ValueError, TypeError):
            msg = _("'%s' argument must be an integer greater than or"
                    " equal to 0") % option
            raise exception.InvalidInput(reason=msg)

    # rxtx_factor should be a positive float
    try:
        kwargs['rxtx_factor'] = float(kwargs['rxtx_factor'])
        if kwargs['rxtx_factor'] <= 0:
            raise ValueError()
    except ValueError:
        msg = _("'rxtx_factor' argument must be a positive float")
        raise exception.InvalidInput(reason=msg)

    kwargs['name'] = name
    kwargs['flavorid'] = flavorid
    # ensure is_public attribute is boolean
    try:
        kwargs['is_public'] = strutils.bool_from_string(
            is_public, strict=True)
    except ValueError:
        raise exception.InvalidInput(reason=_("is_public must be a boolean"))

    try:
        return db.flavor_create(context.get_admin_context(), kwargs)
    except db_exc.DBError as e:
        LOG.exception(_('DB error: %s') % e)
        raise exception.InstanceTypeCreateFailed()


def destroy(name):
    """Marks flavor as deleted."""
    try:
        if not name:
            raise ValueError()
        db.flavor_destroy(context.get_admin_context(), name)
    except (ValueError, exception.NotFound):
        LOG.exception(_('Instance type %s not found for deletion') % name)
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)


def get_all_flavors(ctxt=None, inactive=False, filters=None):
    """Get all non-deleted flavors as a dict.

    Pass true as argument if you want deleted flavors returned also.
    """
    if ctxt is None:
        ctxt = context.get_admin_context()

    inst_types = db.flavor_get_all(
            ctxt, inactive=inactive, filters=filters)

    inst_type_dict = {}
    for inst_type in inst_types:
        inst_type_dict[inst_type['id']] = inst_type
    return inst_type_dict


def get_all_flavors_sorted_list(ctxt=None, inactive=False, filters=None,
                                sort_key='flavorid', sort_dir='asc',
                                limit=None, marker=None):
    """Get all non-deleted flavors as a sorted list.

    Pass true as argument if you want deleted flavors returned also.
    """
    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.flavor_get_all(ctxt, filters=filters, sort_key=sort_key,
                             sort_dir=sort_dir, limit=limit, marker=marker)


def get_default_flavor():
    """Get the default flavor."""
    name = CONF.default_flavor
    return get_flavor_by_name(name)


def get_flavor(instance_type_id, ctxt=None, inactive=False):
    """Retrieves single flavor by id."""
    if instance_type_id is None:
        return get_default_flavor()

    if ctxt is None:
        ctxt = context.get_admin_context()

    if inactive:
        ctxt = ctxt.elevated(read_deleted="yes")

    return db.flavor_get(ctxt, instance_type_id)


def get_flavor_by_name(name, ctxt=None):
    """Retrieves single flavor by name."""
    if name is None:
        return get_default_flavor()

    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.flavor_get_by_name(ctxt, name)


# TODO(termie): flavor-specific code should probably be in the API that uses
#               flavors.
def get_flavor_by_flavor_id(flavorid, ctxt=None, read_deleted="yes"):
    """Retrieve flavor by flavorid.

    :raises: FlavorNotFound
    """
    if ctxt is None:
        ctxt = context.get_admin_context(read_deleted=read_deleted)

    return db.flavor_get_by_flavor_id(ctxt, flavorid, read_deleted)


def get_flavor_access_by_flavor_id(flavorid, ctxt=None):
    """Retrieve flavor access list by flavor id."""
    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.flavor_access_get_by_flavor_id(ctxt, flavorid)


def add_flavor_access(flavorid, projectid, ctxt=None):
    """Add flavor access for project."""
    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.flavor_access_add(ctxt, flavorid, projectid)


def remove_flavor_access(flavorid, projectid, ctxt=None):
    """Remove flavor access for project."""
    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.flavor_access_remove(ctxt, flavorid, projectid)


def extract_flavor(instance, prefix=''):
    """Create an InstanceType-like object from instance's system_metadata
    information.
    """

    instance_type = {}
    sys_meta = utils.instance_sys_meta(instance)
    for key, type_fn in system_metadata_flavor_props.items():
        type_key = '%sinstance_type_%s' % (prefix, key)
        instance_type[key] = type_fn(sys_meta[type_key])
    return instance_type


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
    pci_request.save_flavor_pci_info(metadata, instance_type, prefix)
    return metadata


def delete_flavor_info(metadata, *prefixes):
    """Delete flavor instance_type information from instance's system_metadata
    by prefix.
    """

    for key in system_metadata_flavor_props.keys():
        for prefix in prefixes:
            to_key = '%sinstance_type_%s' % (prefix, key)
            del metadata[to_key]
    pci_request.delete_flavor_pci_info(metadata, *prefixes)
    return metadata
