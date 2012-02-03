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

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.instance_types')


def create(name, memory, vcpus, root_gb, ephemeral_gb, flavorid, swap=None,
           rxtx_factor=None):
    """Creates instance types."""

    if swap is None:
        swap = 0
    if rxtx_factor is None:
        rxtx_factor = 1

    kwargs = {
        'memory_mb': memory,
        'vcpus': vcpus,
        'root_gb': root_gb,
        'ephemeral_gb': ephemeral_gb,
        'swap': swap,
        'rxtx_factor': rxtx_factor,
    }

    # ensure some attributes are integers and greater than or equal to 0
    for option in kwargs:
        try:
            kwargs[option] = int(kwargs[option])
            assert kwargs[option] >= 0
        except (ValueError, AssertionError):
            msg = _("create arguments must be positive integers")
            raise exception.InvalidInput(reason=msg)

    # some value are required to be nonzero, not just positive
    for option in ['memory_mb', 'vcpus']:
        try:
            assert kwargs[option] > 0
        except AssertionError:
            msg = _("create arguments must be positive integers")
            raise exception.InvalidInput(reason=msg)

    kwargs['name'] = name
    kwargs['flavorid'] = flavorid

    try:
        return db.instance_type_create(context.get_admin_context(), kwargs)
    except exception.DBError, e:
        LOG.exception(_('DB error: %s') % e)
        msg = _("Cannot create instance_type with name %(name)s and "
                "flavorid %(flavorid)s") % locals()
        raise exception.ApiError(msg)


def destroy(name):
    """Marks instance types as deleted."""
    try:
        assert name is not None
        db.instance_type_destroy(context.get_admin_context(), name)
    except (AssertionError, exception.NotFound):
        LOG.exception(_('Instance type %s not found for deletion') % name)
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)


def purge(name):
    """Removes instance types from database."""
    try:
        assert name is not None
        db.instance_type_purge(context.get_admin_context(), name)
    except (AssertionError, exception.NotFound):
        LOG.exception(_('Instance type %s not found for purge') % name)
        raise exception.InstanceTypeNotFoundByName(instance_type_name=name)


def get_all_types(inactive=0, filters=None):
    """Get all non-deleted instance_types.

    Pass true as argument if you want deleted instance types returned also.

    """
    ctxt = context.get_admin_context()
    inst_types = db.instance_type_get_all(ctxt, inactive, filters)
    inst_type_dict = {}
    for inst_type in inst_types:
        inst_type_dict[inst_type['name']] = inst_type
    return inst_type_dict

get_all_flavors = get_all_types


def get_default_instance_type():
    """Get the default instance type."""
    name = FLAGS.default_instance_type
    try:
        return get_instance_type_by_name(name)
    except exception.InstanceTypeNotFound as e:
        raise exception.ApiError(e)


def get_instance_type(instance_type_id):
    """Retrieves single instance type by id."""
    if instance_type_id is None:
        return get_default_instance_type()

    ctxt = context.get_admin_context()
    try:
        return db.instance_type_get(ctxt, instance_type_id)
    except exception.InstanceTypeNotFound as e:
        raise exception.ApiError(e)


def get_instance_type_by_name(name):
    """Retrieves single instance type by name."""
    if name is None:
        return get_default_instance_type()

    ctxt = context.get_admin_context()

    try:
        return db.instance_type_get_by_name(ctxt, name)
    except exception.InstanceTypeNotFound as e:
        raise exception.ApiError(e)


# TODO(termie): flavor-specific code should probably be in the API that uses
#               flavors.
def get_instance_type_by_flavor_id(flavorid):
    """Retrieve instance type by flavorid.

    :raises: FlavorNotFound
    """
    ctxt = context.get_admin_context()
    return db.instance_type_get_by_flavor_id(ctxt, flavorid)
