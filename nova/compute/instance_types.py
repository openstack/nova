# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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

"""
The built-in instance properties.
"""

from nova import context
from nova import db
from nova import flags
from nova import exception

FLAGS = flags.FLAGS


def create(name, memory, vcpus, local_gb, flavorid):
    """Creates instance types / flavors
       arguments: name memory_mb vcpus local_gb"""
    for option in [memory, flavorid, local_gb, vcpus]:
        if (option <= 0) or (option.__class__ == int):
            raise InvalidParameters
    db.instance_type_create(context.get_admin_context(),
                            dict(name=name, memory_mb=memory,
                            vcpus=vcpus, local_gb=local_gb,
                            flavorid=flavorid))


def delete(name):
    """Marks instance types / flavors as deleted
    arguments: name"""
    if name == None:
        raise InvalidParameters
    else:
        records = db.instance_type_destroy(context.get_admin_context(),
                                            name)


def get_all_types():
    """retrieves all instance_types"""
    return db.instance_type_get_all()


def get_all_flavors():
    """retrieves all flavors. alias for instance_types.get_all_types()"""
    return get_all_types()


def get_by_type(instance_type):
    """retrieve instance_type details"""
    if instance_type is None:
        return FLAGS.default_instance_type
    try:
        ctxt = context.get_admin_context()
        inst_type = db.instance_type_get_by_name(ctxt, instance_type)
        return inst_type['name']
    except exception.DBError:
        raise exception.ApiError(_("Unknown instance type: %s"),
                                 instance_type)


def get_by_flavor_id(flavor_id):
    """retrieve instance_type's name by flavor_id"""
    if flavor_id is None:
        return FLAGS.default_instance_type
    try:
        ctxt = context.get_admin_context()
        flavor = db.instance_type_get_by_flavor_id(ctxt, flavor_id)
        return flavor['name']
    except exception.DBError:
        raise exception.ApiError(_("Unknown flavor: %s"),
                                 flavor_id)
