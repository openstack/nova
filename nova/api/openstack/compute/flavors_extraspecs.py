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

import six
import webob

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import flavors_extraspecs
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.i18n import _
from nova.policies import flavor_extra_specs as fes_policies
from nova import utils


class FlavorExtraSpecsController(wsgi.Controller):
    """The flavor extra specs API controller for the OpenStack API."""
    def _get_extra_specs(self, context, flavor_id):
        flavor = common.get_flavor(context, flavor_id)
        return dict(extra_specs=flavor.extra_specs)

    # NOTE(gmann): Max length for numeric value is being checked
    # explicitly as json schema cannot have max length check for numeric value
    def _check_extra_specs_value(self, specs):
        for value in specs.values():
            try:
                if isinstance(value, (six.integer_types, float)):
                    value = six.text_type(value)
                    utils.check_string_length(value, 'extra_specs value',
                                              max_length=255)
            except exception.InvalidInput as error:
                raise webob.exc.HTTPBadRequest(
                          explanation=error.format_message())

    @extensions.expected_errors(404)
    def index(self, req, flavor_id):
        """Returns the list of extra specs for a given flavor."""
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'index')
        return self._get_extra_specs(context, flavor_id)

    # NOTE(gmann): Here should be 201 instead of 200 by v2.1
    # +microversions because the flavor extra specs has been created
    # completely when returning a response.
    @extensions.expected_errors((400, 404, 409))
    @validation.schema(flavors_extraspecs.create)
    def create(self, req, flavor_id, body):
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'create')

        specs = body['extra_specs']
        self._check_extra_specs_value(specs)
        flavor = common.get_flavor(context, flavor_id)
        try:
            flavor.extra_specs = dict(flavor.extra_specs, **specs)
            flavor.save()
        except exception.FlavorExtraSpecUpdateCreateFailed as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return body

    @extensions.expected_errors((400, 404, 409))
    @validation.schema(flavors_extraspecs.update)
    def update(self, req, flavor_id, id, body):
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'update')

        self._check_extra_specs_value(body)
        if id not in body:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        flavor = common.get_flavor(context, flavor_id)
        try:
            flavor.extra_specs = dict(flavor.extra_specs, **body)
            flavor.save()
        except exception.FlavorExtraSpecUpdateCreateFailed as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return body

    @extensions.expected_errors(404)
    def show(self, req, flavor_id, id):
        """Return a single extra spec item."""
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'show')
        flavor = common.get_flavor(context, flavor_id)
        try:
            return {id: flavor.extra_specs[id]}
        except KeyError:
            msg = _("Flavor %(flavor_id)s has no extra specs with "
                    "key %(key)s.") % dict(flavor_id=flavor_id,
                                           key=id)
            raise webob.exc.HTTPNotFound(explanation=msg)

    # NOTE(gmann): Here should be 204(No Content) instead of 200 by v2.1
    # +microversions because the flavor extra specs has been deleted
    # completely when returning a response.
    @extensions.expected_errors(404)
    def delete(self, req, flavor_id, id):
        """Deletes an existing extra spec."""
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'delete')
        flavor = common.get_flavor(context, flavor_id)
        try:
            del flavor.extra_specs[id]
            flavor.save()
        except (exception.FlavorExtraSpecsNotFound,
                exception.FlavorNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except KeyError:
            msg = _("Flavor %(flavor_id)s has no extra specs with "
                    "key %(key)s.") % dict(flavor_id=flavor_id,
                                           key=id)
            raise webob.exc.HTTPNotFound(explanation=msg)
