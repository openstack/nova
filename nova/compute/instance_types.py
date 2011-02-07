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
# FIXME(kpepple) for dynamic flavors
# INSTANCE_TYPES = {
#     'm1.tiny': dict(memory_mb=512, vcpus=1, local_gb=0, flavorid=1),
#     'm1.small': dict(memory_mb=2048, vcpus=1, local_gb=20, flavorid=2),
#     'm1.medium': dict(memory_mb=4096, vcpus=2, local_gb=40, flavorid=3),
#     'm1.large': dict(memory_mb=8192, vcpus=4, local_gb=80, flavorid=4),
#     'm1.xlarge': dict(memory_mb=16384, vcpus=8, local_gb=160, flavorid=5)}


def get_all_types():
    """retrieves all instance_types"""
    return db.instance_type_get_all()


def get_all_flavors():
    """retrieves all flavors. alias for instance_types.get_all_types()"""
    return get_all_types()


def get_by_type(instance_type):
    """retrieve instance_type details"""
    # FIXME(kpepple) for dynamic flavors
    if instance_type is None:
        return FLAGS.default_instance_type
    try:
        ctxt = context.get_admin_context()
        inst_type = db.instance_type_get_by_name(ctxt, instance_type)
    except Exception, e:
        print e
        raise exception.ApiError(_("Unknown instance type: %s"),
                                 instance_type)
    return inst_type['name']


def get_by_flavor_id(flavor_id):
    """retrieve instance_type's name by flavor_id"""
    if flavor_id is None:
        return FLAGS.default_instance_type
    try:
        ctxt = context.get_admin_context()
        flavor = db.instance_type_get_by_flavor_id(ctxt, flavor_id)
    except Exception, e:
        raise exception.ApiError(_("Unknown flavor: %s"),
                                 flavor_id)
    return flavor['name']
