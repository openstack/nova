# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
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

"""
Handles all requests relating to Virtual Storage Arrays (VSAs).
"""

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import quota
from nova import rpc
from nova.db import base

from nova import compute
from nova import volume
from nova.compute import instance_types


FLAGS = flags.FLAGS
flags.DEFINE_string('drive_type_template_short', '%s_%sGB_%sRPM',
                    'Template string for generation of drive type name')
flags.DEFINE_string('drive_type_template_long', '%s_%sGB_%sRPM_%s',
                    'Template string for generation of drive type name')


LOG = logging.getLogger('nova.drive_types')


def _generate_default_drive_name(type, size_gb, rpm, capabilities):
    if capabilities is None or capabilities == '':
        return FLAGS.drive_type_template_short % \
                (type, str(size_gb), rpm)
    else:
        return FLAGS.drive_type_template_long % \
                (type, str(size_gb), rpm, capabilities)


def drive_type_create(context, type, size_gb, rpm,
                     capabilities='', visible=True, name=None):
    if name is None:
        name = _generate_default_drive_name(type, size_gb, rpm,
                                                capabilities)
    LOG.debug(_("Creating drive type %(name)s: "\
                "%(type)s %(size_gb)s %(rpm)s %(capabilities)s"), locals())

    values = {
        'type': type,
        'size_gb': size_gb,
        'rpm': rpm,
        'capabilities': capabilities,
        'visible': visible,
        'name': name
        }
    return db.drive_type_create(context, values)


def drive_type_update(context, name, **kwargs):
    LOG.debug(_("Updating drive type %(name)s: "), locals())
    return db.drive_type_update(context, name, kwargs)


def drive_type_rename(context, name, new_name=None):

    if new_name is None or \
       new_name == '':
        disk = db.drive_type_get_by_name(context, name)
        new_name = _generate_default_drive_name(disk['type'],
            disk['size_gb'], disk['rpm'], disk['capabilities'])

    LOG.debug(_("Renaming drive type %(name)s to %(new_name)s"), locals())

    values = dict(name=new_name)
    return db.drive_type_update(context, name, values)


def drive_type_delete(context, name):
    LOG.debug(_("Deleting drive type %(name)s"), locals())
    db.drive_type_destroy(context, name)


def drive_type_get(context, id):
    return db.drive_type_get(context, id)


def drive_type_get_by_name(context, name):
    return db.drive_type_get_by_name(context, name)


def drive_type_get_all(context, visible=None):
    return db.drive_type_get_all(context, visible)
