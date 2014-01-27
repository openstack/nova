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

from nova.api.openstack.compute.views import flavors as flavors_view
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import flavors
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import strutils
from nova import utils


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
            context = req.environ['nova.context']
            flavor = flavors.get_flavor_by_flavor_id(id, ctxt=context)
            req.cache_db_flavor(flavor)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound()

        return self._view_builder.show(req, flavor)

    def _parse_is_public(self, is_public):
        """Parse is_public into something usable."""

        if is_public is None:
            # preserve default value of showing only public flavors
            return True
        elif utils.is_none_string(is_public):
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
        sort_key = req.params.get('sort_key') or 'flavorid'
        sort_dir = req.params.get('sort_dir') or 'asc'
        limit = req.params.get('limit') or None
        marker = req.params.get('marker') or None

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

        try:
            limited_flavors = flavors.get_all_flavors_sorted_list(context,
                filters=filters, sort_key=sort_key, sort_dir=sort_dir,
                limit=limit, marker=marker)
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return limited_flavors


def create_resource():
    return wsgi.Resource(Controller())
