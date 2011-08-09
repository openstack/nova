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


def create(name, memory, vcpus, local_gb, flavorid, swap=0,
           rxtx_quota=0, rxtx_cap=0):
    """Creates instance types."""
    for option in [memory, vcpus, local_gb, flavorid]:
        try:
            int(option)
        except ValueError:
            raise exception.InvalidInput(reason=_("create arguments must "
                                                  "be positive integers"))
    if (int(memory) <= 0) or (int(vcpus) <= 0) or (int(local_gb) < 0):
        raise exception.InvalidInput(reason=_("create arguments must "
                                              "be positive integers"))

    try:
        db.instance_type_create(
                context.get_admin_context(),
                dict(name=name,
                    memory_mb=memory,
                    vcpus=vcpus,
                    local_gb=local_gb,
                    flavorid=flavorid,
                    swap=swap,
                    rxtx_quota=rxtx_quota,
                    rxtx_cap=rxtx_cap))
    except exception.DBError, e:
        LOG.exception(_('DB error: %s') % e)
        raise exception.ApiError(_("Cannot create instance_type with "
                                    "name %(name)s and flavorid %(flavorid)s")
                                    % locals())


def destroy(name):
    """Marks instance types as deleted."""
    if name is None:
        raise exception.InvalidInstanceType(instance_type=name)
    else:
        try:
            db.instance_type_destroy(context.get_admin_context(), name)
        except exception.NotFound:
            LOG.exception(_('Instance type %s not found for deletion') % name)
            raise exception.ApiError(_("Unknown instance type: %s") % name)


def purge(name):
    """Removes instance types from database."""
    if name is None:
        raise exception.InvalidInstanceType(instance_type=name)
    else:
        try:
            db.instance_type_purge(context.get_admin_context(), name)
        except exception.NotFound:
            LOG.exception(_('Instance type %s not found for purge') % name)
            raise exception.ApiError(_("Unknown instance type: %s") % name)


def get_all_types(inactive=0):
    """Get all non-deleted instance_types.

    Pass true as argument if you want deleted instance types returned also.

    """
    return db.instance_type_get_all(context.get_admin_context(), inactive)


get_all_flavors = get_all_types


def get_default_instance_type():
    """Get the default instance type."""
    name = FLAGS.default_instance_type
    try:
        return get_instance_type_by_name(name)
    except exception.DBError:
        raise exception.ApiError(_("Unknown instance type: %s") % name)


def get_instance_type(id):
    """Retrieves single instance type by id."""
    if id is None:
        return get_default_instance_type()
    try:
        ctxt = context.get_admin_context()
        return db.instance_type_get(ctxt, id)
    except exception.DBError:
        raise exception.ApiError(_("Unknown instance type: %s") % id)


def get_instance_type_by_name(name):
    """Retrieves single instance type by name."""
    if name is None:
        return get_default_instance_type()
    try:
        ctxt = context.get_admin_context()
        return db.instance_type_get_by_name(ctxt, name)
    except exception.DBError:
        raise exception.ApiError(_("Unknown instance type: %s") % name)


# TODO(termie): flavor-specific code should probably be in the API that uses
#               flavors.
def get_instance_type_by_flavor_id(flavor_id):
    """Retrieve instance type by flavor_id."""
    ctxt = context.get_admin_context()
    try:
        return db.instance_type_get_by_flavor_id(ctxt, flavor_id)
    except ValueError:
        raise exception.FlavorNotFound(flavor_id=flavor_id)
