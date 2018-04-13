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

from oslo_utils import strutils
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import flavors as schema
from nova.api.openstack.compute.views import flavors as flavors_view
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import flavors
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import flavor_extra_specs as fes_policies
from nova import utils

ALIAS = 'flavors'


class FlavorsController(wsgi.Controller):
    """Flavor controller for the OpenStack API."""

    _view_builder_class = flavors_view.ViewBuilder

    @validation.query_schema(schema.index_query)
    @wsgi.expected_errors(400)
    def index(self, req):
        """Return all flavors in brief."""
        limited_flavors = self._get_flavors(req)
        return self._view_builder.index(req, limited_flavors)

    @validation.query_schema(schema.index_query)
    @wsgi.expected_errors(400)
    def detail(self, req):
        """Return all flavors in detail."""
        context = req.environ['nova.context']
        limited_flavors = self._get_flavors(req)
        req.cache_db_flavors(limited_flavors)
        include_extra_specs = False
        if api_version_request.is_supported(
                req, flavors_view.FLAVOR_EXTRA_SPECS_MICROVERSION):
            include_extra_specs = context.can(
                fes_policies.POLICY_ROOT % 'index', fatal=False)
        return self._view_builder.detail(
            req, limited_flavors, include_extra_specs=include_extra_specs)

    @wsgi.expected_errors(404)
    def show(self, req, id):
        """Return data about the given flavor id."""
        context = req.environ['nova.context']
        try:
            flavor = flavors.get_flavor_by_flavor_id(id, ctxt=context)
            req.cache_db_flavor(flavor)
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        include_extra_specs = False
        if api_version_request.is_supported(
                req, flavors_view.FLAVOR_EXTRA_SPECS_MICROVERSION):
            include_extra_specs = context.can(
                fes_policies.POLICY_ROOT % 'index', fatal=False)
        include_description = api_version_request.is_supported(
            req, flavors_view.FLAVOR_DESCRIPTION_MICROVERSION)
        return self._view_builder.show(
            req, flavor, include_description=include_description,
            include_extra_specs=include_extra_specs)

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
        limit, marker = common.get_limit_and_marker(req)

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
                msg = (_('Invalid minDisk filter [%s]') %
                       req.params['minDisk'])
                raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            limited_flavors = objects.FlavorList.get_all(context,
                filters=filters, sort_key=sort_key, sort_dir=sort_dir,
                limit=limit, marker=marker)
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return limited_flavors
