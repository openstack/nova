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

""" The Drive Types extension for Virtual Storage Arrays"""


from webob import exc

from nova.vsa import drive_types
from nova import exception
from nova import db
from nova import quota
from nova import log as logging
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import faults
from nova.api.openstack import wsgi

LOG = logging.getLogger("nova.api.drive_types")


def _drive_type_view(drive):
    """Maps keys for drive types view."""
    d = {}

    d['id'] = drive['id']
    d['displayName'] = drive['name']
    d['type'] = drive['type']
    d['size'] = drive['size_gb']
    d['rpm'] = drive['rpm']
    d['capabilities'] = drive['capabilities']
    return d


class DriveTypeController(object):
    """The Drive Type API controller for the OpenStack API."""

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "drive_type": [
                    "id",
                    "displayName",
                    "type",
                    "size",
                    "rpm",
                    "capabilities",
                    ]}}}

    def index(self, req):
        """Returns a list of drive types."""

        context = req.environ['nova.context']
        dtypes = drive_types.get_all(context)
        limited_list = common.limited(dtypes, req)
        res = [_drive_type_view(drive) for drive in limited_list]
        return {'drive_types': res}

    def show(self, req, id):
        """Return data about the given drive type."""
        context = req.environ['nova.context']

        try:
            drive = drive_types.get(context, id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        return {'drive_type': _drive_type_view(drive)}

    def create(self, req, body):
        """Creates a new drive type."""
        context = req.environ['nova.context']

        if not body:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        drive = body['drive_type']

        name = drive.get('displayName')
        type = drive.get('type')
        size = drive.get('size')
        rpm = drive.get('rpm')
        capabilities = drive.get('capabilities')

        LOG.audit(_("Create drive type %(name)s for "\
                    "%(type)s:%(size)s:%(rpm)s"), locals(), context=context)

        new_drive = drive_types.create(context,
                                      type=type,
                                      size_gb=size,
                                      rpm=rpm,
                                      capabilities=capabilities,
                                      name=name)

        return {'drive_type': _drive_type_view(new_drive)}

    def delete(self, req, id):
        """Deletes a drive type."""
        context = req.environ['nova.context']

        LOG.audit(_("Delete drive type with id: %s"), id, context=context)

        try:
            drive_types.delete(context, id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        # return exc.HTTPAccepted()


class Drive_types(extensions.ExtensionDescriptor):

    def get_name(self):
        return "DriveTypes"

    def get_alias(self):
        return "zadr-drive_types"

    def get_description(self):
        return "Drive Types support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/drive_types/api/v1.1"

    def get_updated(self):
        return "2011-06-29T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
                            'zadr-drive_types',
                            DriveTypeController())

        resources.append(res)
        return resources
