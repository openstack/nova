# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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

""" The volume type & volume types extra specs extension"""

from webob import exc

from nova import db
from nova import exception
from nova import quota
from nova.volume import volume_types
from nova.api.openstack import extensions
from nova.api.openstack import faults
from nova.api.openstack import wsgi


class VolumeTypesController(object):
    """ The volume types API controller for the Openstack API """

    def index(self, req):
        """ Returns the list of volume types """
        context = req.environ['nova.context']
        return volume_types.get_all_types(context)

    def create(self, req, body):
        """Creates a new volume type."""
        context = req.environ['nova.context']

        if not body or body == "":
            return faults.Fault(exc.HTTPUnprocessableEntity())

        vol_type = body.get('volume_type', None)
        if vol_type is None or vol_type == "":
            return faults.Fault(exc.HTTPUnprocessableEntity())

        name = vol_type.get('name', None)
        specs = vol_type.get('extra_specs', {})

        if name is None or name == "":
            return faults.Fault(exc.HTTPUnprocessableEntity())

        try:
            volume_types.create(context, name, specs)
            vol_type = volume_types.get_volume_type_by_name(context, name)
        except quota.QuotaError as error:
            self._handle_quota_error(error)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        return {'volume_type': vol_type}

    def show(self, req, id):
        """ Return a single volume type item """
        context = req.environ['nova.context']

        try:
            vol_type = volume_types.get_volume_type(context, id)
        except exception.NotFound or exception.ApiError:
            return faults.Fault(exc.HTTPNotFound())

        return {'volume_type': vol_type}

    def delete(self, req, id):
        """ Deletes an existing volume type """
        context = req.environ['nova.context']

        try:
            vol_type = volume_types.get_volume_type(context, id)
            volume_types.destroy(context, vol_type['name'])
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

    def _handle_quota_error(self, error):
        """Reraise quota errors as api-specific http exceptions."""
        if error.code == "MetadataLimitExceeded":
            raise exc.HTTPBadRequest(explanation=error.message)
        raise error


class VolumeTypeExtraSpecsController(object):
    """ The volume type extra specs API controller for the Openstack API """

    def _get_extra_specs(self, context, vol_type_id):
        extra_specs = db.api.volume_type_extra_specs_get(context, vol_type_id)
        specs_dict = {}
        for key, value in extra_specs.iteritems():
            specs_dict[key] = value
        return dict(extra_specs=specs_dict)

    def _check_body(self, body):
        if body == None or body == "":
            expl = _('No Request Body')
            raise exc.HTTPBadRequest(explanation=expl)

    def index(self, req, vol_type_id):
        """ Returns the list of extra specs for a given volume type """
        context = req.environ['nova.context']
        return self._get_extra_specs(context, vol_type_id)

    def create(self, req, vol_type_id, body):
        self._check_body(body)
        context = req.environ['nova.context']
        specs = body.get('extra_specs')
        try:
            db.api.volume_type_extra_specs_update_or_create(context,
                                                            vol_type_id,
                                                            specs)
        except quota.QuotaError as error:
            self._handle_quota_error(error)
        return body

    def update(self, req, vol_type_id, id, body):
        self._check_body(body)
        context = req.environ['nova.context']
        if not id in body:
            expl = _('Request body and URI mismatch')
            raise exc.HTTPBadRequest(explanation=expl)
        if len(body) > 1:
            expl = _('Request body contains too many items')
            raise exc.HTTPBadRequest(explanation=expl)
        try:
            db.api.volume_type_extra_specs_update_or_create(context,
                                                            vol_type_id,
                                                            body)
        except quota.QuotaError as error:
            self._handle_quota_error(error)

        return body

    def show(self, req, vol_type_id, id):
        """ Return a single extra spec item """
        context = req.environ['nova.context']
        specs = self._get_extra_specs(context, vol_type_id)
        if id in specs['extra_specs']:
            return {id: specs['extra_specs'][id]}
        else:
            return faults.Fault(exc.HTTPNotFound())

    def delete(self, req, vol_type_id, id):
        """ Deletes an existing extra spec """
        context = req.environ['nova.context']
        db.api.volume_type_extra_specs_delete(context, vol_type_id, id)

    def _handle_quota_error(self, error):
        """Reraise quota errors as api-specific http exceptions."""
        if error.code == "MetadataLimitExceeded":
            raise exc.HTTPBadRequest(explanation=error.message)
        raise error


class Volumetypes(extensions.ExtensionDescriptor):

    def get_name(self):
        return "VolumeTypes"

    def get_alias(self):
        return "os-volume-types"

    def get_description(self):
        return "Volume types support"

    def get_namespace(self):
        return \
         "http://docs.openstack.org/ext/volume_types/api/v1.1"

    def get_updated(self):
        return "2011-08-24T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
                    'os-volume-types',
                    VolumeTypesController())
        resources.append(res)

        res = extensions.ResourceExtension('extra_specs',
                            VolumeTypeExtraSpecsController(),
                            parent=dict(
                                member_name='vol_type',
                                collection_name='os-volume-types'))
        resources.append(res)

        return resources
