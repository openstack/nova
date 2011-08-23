# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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

"""Built-in volume type properties."""

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.volume_types')


def create(context, name, extra_specs={}):
    """Creates volume types."""
    try:
        db.volume_type_create(
                context,
                dict(name=name,
                     extra_specs=extra_specs))
    except exception.DBError, e:
        LOG.exception(_('DB error: %s') % e)
        raise exception.ApiError(_("Cannot create volume_type with "
                                    "name %(name)s and specs %(extra_specs)s")
                                    % locals())


def destroy(context, name):
    """Marks volume types as deleted."""
    if name is None:
        raise exception.InvalidVolumeType(volume_type=name)
    else:
        try:
            db.volume_type_destroy(context, name)
        except exception.NotFound:
            LOG.exception(_('Volume type %s not found for deletion') % name)
            raise exception.ApiError(_("Unknown volume type: %s") % name)


def purge(context, name):
    """Removes volume types from database."""
    if name is None:
        raise exception.InvalidVolumeType(volume_type=name)
    else:
        try:
            db.volume_type_purge(context, name)
        except exception.NotFound:
            LOG.exception(_('Volume type %s not found for purge') % name)
            raise exception.ApiError(_("Unknown volume type: %s") % name)


def get_all_types(context, inactive=0):
    """Get all non-deleted volume_types.

    Pass true as argument if you want deleted volume types returned also.

    """
    return db.volume_type_get_all(context, inactive)


def get_volume_type(context, id):
    """Retrieves single volume type by id."""
    if id is None:
        raise exception.ApiError(_("Invalid volume type: %s") % id)

    try:
        return db.volume_type_get(context, id)
    except exception.DBError:
        raise exception.ApiError(_("Unknown volume type: %s") % id)


def get_volume_type_by_name(context, name):
    """Retrieves single volume type by name."""
    if name is None:
        raise exception.ApiError(_("Invalid volume type name: %s") % name)

    try:
        return db.volume_type_get_by_name(context, name)
    except exception.DBError:
        raise exception.ApiError(_("Unknown volume type: %s") % name)
