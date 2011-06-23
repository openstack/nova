# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 University of Southern California
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

from webob import exc

from nova import db
from nova import quota
from nova.api.openstack import faults
from nova.api.openstack import wsgi


class Controller(object):
    """ The flavor extra specs API controller for the Openstack API """

    def __init__(self):
        self.compute_api = compute.API()
        super(Controller, self).__init__()

    def _get_extra_specs(self, context, flavor_id):
        extra_specs = self.db.instance_type_extra_specs_get(context, flavor_id)
        specs_dict = {}
        for key, value in specs.iteritems():
            specs_dict[key] = value
        return dict(extra=specs_dict)

    def _check_body(self, body):
        if body == None or body == "":
            expl = _('No Request Body')
            raise exc.HTTPBadRequest(explanation=expl)

    def index(self, req, flavor_id):
        """ Returns the list of extra specs for a givenflavor """
        context = req.environ['nova.context']
        return self._get_extra_specs(context, flavor_id)

    def create(self, req, flavor_id, body):
        self._check_body(body)
        context = req.environ['nova.context']
        specs = body.get('extra')
        try:
            self.db.instance_type_extra_specs_update_or_create(context,
                                                               flavor_id,
                                                               specs)
        except quota.QuotaError as error:
            self._handle_quota_error(error)
        return body

    def update(self, req, flavor_id, id, body):
        self._check_body(body)
        context = req.environ['nova.context']
        if not id in body:
            expl = _('Request body and URI mismatch')
            raise exc.HTTPBadRequest(explanation=expl)
        if len(body) > 1:
            expl = _('Request body contains too many items')
            raise exc.HTTPBadRequest(explanation=expl)
        try:
            self.db.instance_type_extra_specs_update_or_create(context,
                                                               flavor_id,
                                                               body)
        except quota.QuotaError as error:
            self._handle_quota_error(error)

        return body

    def show(self, req, flavor_id, id):
        """ Return a single extra spec item """
        context = req.environ['nova.context']
        specs = self._get_extra_specs(context, flavor_id)
        if id in specs['extra']:
            return {id: specs['extra'][id]}
        else:
            return faults.Fault(exc.HTTPNotFound())

    def delete(self, req, flavor_id, id):
        """ Deletes an existing extra spec """
        context = req.environ['nova.context']
        self.instance_type_extra_specs_delete(context, flavor_id, id)

    def _handle_quota_error(self, error):
        """Reraise quota errors as api-specific http exceptions."""
        if error.code == "MetadataLimitExceeded":
            raise exc.HTTPBadRequest(explanation=error.message)
        raise error


def create_resource():
    serializers = {
        'application/xml': wsgi.XMLDictSerializer(xmlns=wsgi.XMLNS_V11),
    }

    return wsgi.Resource(Controller(), serializers=serializers)
