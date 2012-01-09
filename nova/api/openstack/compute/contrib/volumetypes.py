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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova import exception
from nova.volume import volume_types


def make_voltype(elem):
    elem.set('id')
    elem.set('name')
    extra_specs = xmlutil.make_flat_dict('extra_specs', selector='extra_specs')
    elem.append(extra_specs)


class VolumeTypeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_type', selector='volume_type')
        make_voltype(root)
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_types')
        sel = lambda obj, do_raise=False: obj.values()
        elem = xmlutil.SubTemplateElement(root, 'volume_type', selector=sel)
        make_voltype(elem)
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypesController(object):
    """ The volume types API controller for the Openstack API """

    @wsgi.serializers(xml=VolumeTypesTemplate)
    def index(self, req):
        """ Returns the list of volume types """
        context = req.environ['nova.context']
        return volume_types.get_all_types(context)

    @wsgi.serializers(xml=VolumeTypeTemplate)
    def create(self, req, body):
        """Creates a new volume type."""
        context = req.environ['nova.context']

        if not body or body == "":
            raise exc.HTTPUnprocessableEntity()

        vol_type = body.get('volume_type', None)
        if vol_type is None or vol_type == "":
            raise exc.HTTPUnprocessableEntity()

        name = vol_type.get('name', None)
        specs = vol_type.get('extra_specs', {})

        if name is None or name == "":
            raise exc.HTTPUnprocessableEntity()

        try:
            volume_types.create(context, name, specs)
            vol_type = volume_types.get_volume_type_by_name(context, name)
        except exception.QuotaError as error:
            self._handle_quota_error(error)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return {'volume_type': vol_type}

    @wsgi.serializers(xml=VolumeTypeTemplate)
    def show(self, req, id):
        """ Return a single volume type item """
        context = req.environ['nova.context']

        try:
            vol_type = volume_types.get_volume_type(context, id)
        except exception.NotFound or exception.ApiError:
            raise exc.HTTPNotFound()

        return {'volume_type': vol_type}

    def delete(self, req, id):
        """ Deletes an existing volume type """
        context = req.environ['nova.context']

        try:
            vol_type = volume_types.get_volume_type(context, id)
            volume_types.destroy(context, vol_type['name'])
        except exception.NotFound:
            raise exc.HTTPNotFound()

    def _handle_quota_error(self, error):
        """Reraise quota errors as api-specific http exceptions."""
        if error.code == "MetadataLimitExceeded":
            raise exc.HTTPBadRequest(explanation=error.message)
        raise error


class VolumeTypeExtraSpecsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.make_flat_dict('extra_specs', selector='extra_specs')
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypeExtraSpecTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        tagname = xmlutil.Selector('key')

        def extraspec_sel(obj, do_raise=False):
            # Have to extract the key and value for later use...
            key, value = obj.items()[0]
            return dict(key=key, value=value)

        root = xmlutil.TemplateElement(tagname, selector=extraspec_sel)
        root.text = 'value'
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypeExtraSpecsController(object):
    """ The volume type extra specs API controller for the Openstack API """

    def _get_extra_specs(self, context, vol_type_id):
        extra_specs = db.volume_type_extra_specs_get(context, vol_type_id)
        specs_dict = {}
        for key, value in extra_specs.iteritems():
            specs_dict[key] = value
        return dict(extra_specs=specs_dict)

    def _check_body(self, body):
        if body is None or body == "":
            expl = _('No Request Body')
            raise exc.HTTPBadRequest(explanation=expl)

    @wsgi.serializers(xml=VolumeTypeExtraSpecsTemplate)
    def index(self, req, vol_type_id):
        """ Returns the list of extra specs for a given volume type """
        context = req.environ['nova.context']
        return self._get_extra_specs(context, vol_type_id)

    @wsgi.serializers(xml=VolumeTypeExtraSpecsTemplate)
    def create(self, req, vol_type_id, body):
        self._check_body(body)
        context = req.environ['nova.context']
        specs = body.get('extra_specs')
        try:
            db.volume_type_extra_specs_update_or_create(context,
                                                            vol_type_id,
                                                            specs)
        except exception.QuotaError as error:
            self._handle_quota_error(error)
        return body

    @wsgi.serializers(xml=VolumeTypeExtraSpecTemplate)
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
            db.volume_type_extra_specs_update_or_create(context,
                                                            vol_type_id,
                                                            body)
        except exception.QuotaError as error:
            self._handle_quota_error(error)

        return body

    @wsgi.serializers(xml=VolumeTypeExtraSpecTemplate)
    def show(self, req, vol_type_id, id):
        """ Return a single extra spec item """
        context = req.environ['nova.context']
        specs = self._get_extra_specs(context, vol_type_id)
        if id in specs['extra_specs']:
            return {id: specs['extra_specs'][id]}
        else:
            raise exc.HTTPNotFound()

    def delete(self, req, vol_type_id, id):
        """ Deletes an existing extra spec """
        context = req.environ['nova.context']
        db.volume_type_extra_specs_delete(context, vol_type_id, id)

    def _handle_quota_error(self, error):
        """Reraise quota errors as api-specific http exceptions."""
        if error.code == "MetadataLimitExceeded":
            raise exc.HTTPBadRequest(explanation=error.message)
        raise error


class Volumetypes(extensions.ExtensionDescriptor):
    """Volume types support"""

    name = "VolumeTypes"
    alias = "os-volume-types"
    namespace = "http://docs.openstack.org/compute/ext/volume_types/api/v1.1"
    updated = "2011-08-24T00:00:00+00:00"

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
