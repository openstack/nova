# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
LOG = logging.getLogger('nova.volume.volume_types')


def create(context, name, extra_specs={}):
    """Creates volume types."""
    try:
        db.volume_type_create(context,
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


def get_all_types(context, inactive=0, search_opts={}):
    """Get all non-deleted volume_types.

    Pass true as argument if you want deleted volume types returned also.

    """
    vol_types = db.volume_type_get_all(context, inactive)

    if search_opts:
        LOG.debug(_("Searching by: %s") % str(search_opts))

        def _check_extra_specs_match(vol_type, searchdict):
            for k, v in searchdict.iteritems():
                if k not in vol_type['extra_specs'].keys()\
                   or vol_type['extra_specs'][k] != v:
                    return False
            return True

        # search_option to filter_name mapping.
        filter_mapping = {'extra_specs': _check_extra_specs_match}

        result = {}
        for type_name, type_args in vol_types.iteritems():
            # go over all filters in the list
            for opt, values in search_opts.iteritems():
                try:
                    filter_func = filter_mapping[opt]
                except KeyError:
                    # no such filter - ignore it, go to next filter
                    continue
                else:
                    if filter_func(type_args, values):
                        result[type_name] = type_args
                        break
        vol_types = result
    return vol_types


def get_volume_type(ctxt, id):
    """Retrieves single volume type by id."""
    if id is None:
        raise exception.InvalidVolumeType(volume_type=id)

    if ctxt is None:
        ctxt = context.get_admin_context()

    try:
        return db.volume_type_get(ctxt, id)
    except exception.DBError:
        raise exception.ApiError(_("Unknown volume type: %s") % id)


def get_volume_type_by_name(context, name):
    """Retrieves single volume type by name."""
    if name is None:
        raise exception.InvalidVolumeType(volume_type=name)

    try:
        return db.volume_type_get_by_name(context, name)
    except exception.DBError:
        raise exception.ApiError(_("Unknown volume type: %s") % name)


def is_key_value_present(volume_type_id, key, value, volume_type=None):
    if volume_type_id is None:
        return False

    if volume_type is None:
        volume_type = get_volume_type(context.get_admin_context(),
                                      volume_type_id)
    if volume_type.get('extra_specs') is None or\
       volume_type['extra_specs'].get(key) != value:
        return False
    else:
        return True


def is_vsa_drive(volume_type_id, volume_type=None):
    return is_key_value_present(volume_type_id,
                'type', 'vsa_drive', volume_type)


def is_vsa_volume(volume_type_id, volume_type=None):
    return is_key_value_present(volume_type_id,
                'type', 'vsa_volume', volume_type)


def is_vsa_object(volume_type_id):
    if volume_type_id is None:
        return False

    volume_type = get_volume_type(context.get_admin_context(),
                                  volume_type_id)

    return is_vsa_drive(volume_type_id, volume_type) or\
           is_vsa_volume(volume_type_id, volume_type)
