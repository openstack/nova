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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.compute import flavors
from nova import exception
from nova import objects
from nova.openstack.common.gettextutils import _


class FlavorExtraSpecsController(object):
    """The flavor extra specs API controller for the OpenStack API."""
    ALIAS = 'flavor-extra-specs'

    def __init__(self, *args, **kwargs):
        super(FlavorExtraSpecsController, self).__init__(*args, **kwargs)
        self.authorize = extensions.extension_authorizer('compute',
                                                         'v3:' + self.ALIAS)

    def _get_extra_specs(self, context, flavor_id):
        flavor = objects.Flavor.get_by_flavor_id(context, flavor_id)
        return dict(extra_specs=flavor.extra_specs)

    def _check_body(self, body):
        if body is None or body == "":
            expl = _('No Request Body')
            raise webob.exc.HTTPBadRequest(explanation=expl)

    def _check_key_names(self, keys):
        try:
            flavors.validate_extra_spec_keys(keys)
        except exception.InvalidInput as error:
            raise webob.exc.HTTPBadRequest(explanation=error.format_message())

    @extensions.expected_errors(())
    def index(self, req, flavor_id):
        """Returns the list of extra specs for a given flavor."""
        context = req.environ['nova.context']
        self.authorize(context, action='index')
        return self._get_extra_specs(context, flavor_id)

    @extensions.expected_errors((400, 404, 409))
    @wsgi.response(201)
    def create(self, req, flavor_id, body):
        context = req.environ['nova.context']
        self.authorize(context, action='create')
        self._check_body(body)
        specs = body.get('extra_specs', {})
        if not specs or type(specs) is not dict:
            raise webob.exc.HTTPBadRequest(_('No or bad extra_specs provided'))
        self._check_key_names(specs.keys())
        try:
            flavor = objects.Flavor.get_by_flavor_id(context, flavor_id)
            flavor.extra_specs = dict(flavor.extra_specs, **specs)
            flavor.save()
        except exception.FlavorExtraSpecUpdateCreateFailed as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return body

    @extensions.expected_errors((400, 404, 409))
    def update(self, req, flavor_id, id, body):
        context = req.environ['nova.context']
        self.authorize(context, action='update')
        self._check_body(body)
        if id not in body:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        if len(body) > 1:
            expl = _('Request body contains too many items')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        try:
            flavor = objects.Flavor.get_by_flavor_id(context, flavor_id)
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
        self.authorize(context, action='show')
        try:
            flavor = objects.Flavor.get_by_flavor_id(context, flavor_id)
            return {id: flavor.extra_specs[id]}
        except (exception.FlavorExtraSpecsNotFound,
                exception.FlavorNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except KeyError:
            msg = _("Flavor %(flavor_id)s has no extra specs with "
                    "key %(key)s.") % dict(flavor_id=flavor_id,
                                           key=id)
            raise webob.exc.HTTPNotFound(explanation=msg)

    @wsgi.response(204)
    @extensions.expected_errors(404)
    def delete(self, req, flavor_id, id):
        """Deletes an existing extra spec."""
        context = req.environ['nova.context']
        self.authorize(context, action='delete')
        try:
            flavor = objects.Flavor.get_by_flavor_id(context, flavor_id)
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


class FlavorsExtraSpecs(extensions.V3APIExtensionBase):
    """Flavors extra specs support."""
    name = 'FlavorsExtraSpecs'
    alias = FlavorExtraSpecsController.ALIAS
    version = 1

    def get_resources(self):
        extra_specs = extensions.ResourceExtension(
                self.alias,
                FlavorExtraSpecsController(),
                parent=dict(member_name='flavor', collection_name='flavors'))

        return [extra_specs]

    def get_controller_extensions(self):
        return []
