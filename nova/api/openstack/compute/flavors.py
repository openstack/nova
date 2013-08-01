# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import instance_types
from nova import exception


def make_flavor(elem, detailed=False):
    elem.set('name')
    elem.set('id')
    if detailed:
        elem.set('ram')
        elem.set('disk')
        elem.set('vcpus', xmlutil.EmptyStringSelector('vcpus'))

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


class Controller(wsgi.Controller):
    """Flavor controller for the OpenStack API."""

    _view_builder_class = flavors_view.ViewBuilder

    @wsgi.serializers(xml=MinimalFlavorsTemplate)
    def index(self, req):
        """Return all flavors in brief."""
        flavors = self._get_flavors(req)
        return self._view_builder.index(req, flavors)

    @wsgi.serializers(xml=FlavorsTemplate)
    def detail(self, req):
        """Return all flavors in detail."""
        flavors = self._get_flavors(req)
        req.cache_db_flavors(flavors)
        return self._view_builder.detail(req, flavors)

    @wsgi.serializers(xml=FlavorTemplate)
    def show(self, req, id):
        """Return data about the given flavor id."""
        try:
            context = req.environ['nova.context']
            flavor = instance_types.get_instance_type_by_flavor_id(id,
                    ctxt=context)
            req.cache_db_flavor(flavor)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound()

        return self._view_builder.show(req, flavor)

    def _get_is_public(self, req):
        """Parse is_public into something usable."""
        is_public = req.params.get('is_public', None)

        if is_public is None:
            # preserve default value of showing only public flavors
            return True
        elif is_public is True or \
            is_public.lower() in ['t', 'true', 'yes', '1']:
            return True
        elif is_public is False or \
            is_public.lower() in ['f', 'false', 'no', '0']:
            return False
        elif is_public.lower() == 'none':
            # value to match all flavors, ignore is_public
            return None
        else:
            msg = _('Invalid is_public filter [%s]') % req.params['is_public']
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_flavors(self, req):
        """Helper function that returns a list of flavor dicts."""
        filters = {}

        context = req.environ['nova.context']
        if context.is_admin:
            # Only admin has query access to all flavor types
            filters['is_public'] = self._get_is_public(req)
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

        flavors = instance_types.get_all_types(context, filters=filters)
        flavors_list = flavors.values()
        sorted_flavors = sorted(flavors_list,
                                key=lambda item: item['flavorid'])
        limited_flavors = common.limited_by_marker(sorted_flavors, req)
        return limited_flavors


def create_resource():
    return wsgi.Resource(Controller())
