# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack Foundation
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

import webob

from nova.api.openstack import common
from nova.api.openstack.compute.views import flavors as flavors_view
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import flavors
from nova import exception
from nova.openstack.common import strutils


def make_flavor(elem, detailed=False):
    elem.set('name')
    elem.set('id')
    if detailed:
        elem.set('ram')
        elem.set('disk')
        elem.set('vcpus', xmlutil.EmptyStringSelector('vcpus'))
        # NOTE(vish): this was originally added without a namespace
        elem.set('swap', xmlutil.EmptyStringSelector('swap'))

    xmlutil.make_links(elem, 'links')


flavor_nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}


class FlavorTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavor', selector='flavor')
        make_flavor(root, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=flavor_nsmap)


class MinimalFlavorsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavors')
        elem = xmlutil.SubTemplateElement(root, 'flavor', selector='flavors')
        make_flavor(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=flavor_nsmap)


class FlavorsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavors')
        elem = xmlutil.SubTemplateElement(root, 'flavor', selector='flavors')
        make_flavor(elem, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=flavor_nsmap)


class FlavorsController(wsgi.Controller):
    """Flavor controller for the OpenStack API."""

    _view_builder_class = flavors_view.ViewBuilder

    @wsgi.serializers(xml=MinimalFlavorsTemplate)
    def index(self, req):
        """Return all flavors in brief."""
        limited_flavors = self._get_flavors(req)
        return self._view_builder.index(req, limited_flavors)

    @wsgi.serializers(xml=FlavorsTemplate)
    def detail(self, req):
        """Return all flavors in detail."""
        limited_flavors = self._get_flavors(req)
        req.cache_db_flavors(limited_flavors)
        return self._view_builder.detail(req, limited_flavors)

    @wsgi.serializers(xml=FlavorTemplate)
    def show(self, req, id):
        """Return data about the given flavor id."""
        try:
            flavor = flavors.get_flavor_by_flavor_id(id)
            req.cache_db_flavor(flavor)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound()

        return self._view_builder.show(req, flavor)

    def _parse_is_public(self, is_public):
        """Parse is_public into something usable."""

        if is_public is None:
            # preserve default value of showing only public flavors
            return True
        elif is_public == 'none':
            return None
        else:
            try:
                return strutils.bool_from_string(is_public, strict=True)
            except ValueError:
                msg = _('Invalid is_public filter [%s]') % is_public
                raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_flavors(self, req):
        """Helper function that returns a list of flavor dicts."""
        filters = {}

        context = req.environ['nova.context']
        if context.is_admin:
            # Only admin has query access to all flavor types
            filters['is_public'] = self._parse_is_public(
                    req.params.get('is_public', None))
        else:
            filters['is_public'] = True
            filters['disabled'] = False

        if 'minRam' in req.params:
            try:
                filters['min_memory_mb'] = int(req.params['minRam'])
            except ValueError:
                msg = _('Invalid minRam filter [%s]') % req.params['minRam']
                raise webob.exc.HTTPBadRequest(explanation=msg)

        if 'minDisk' in req.params:
            try:
                filters['min_root_gb'] = int(req.params['minDisk'])
            except ValueError:
                msg = _('Invalid minDisk filter [%s]') % req.params['minDisk']
                raise webob.exc.HTTPBadRequest(explanation=msg)

        limited_flavors = flavors.get_all_flavors(context, filters=filters)
        flavors_list = limited_flavors.values()
        sorted_flavors = sorted(flavors_list,
                                key=lambda item: item['flavorid'])
        limited_flavors = common.limited_by_marker(sorted_flavors, req)
        return limited_flavors


class Flavors(extensions.V3APIExtensionBase):
    """ Flavors Extension. """
    name = "flavors"
    alias = "flavors"
    namespace = "http://docs.openstack.org/compute/core/flavors/v3"
    version = 1

    def get_resources(self):
        collection_actions = {'detail': 'GET'}
        member_actions = {'action': 'POST'}

        resources = [
            extensions.ResourceExtension('flavors',
                                         FlavorsController(),
                                         member_name='flavor',
                                         collection_actions=collection_actions,
                                         member_actions=member_actions)
            ]
        return resources

    def get_controller_extensions(self):
        return []
