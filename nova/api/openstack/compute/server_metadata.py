# Copyright 2011 OpenStack Foundation
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

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import server_metadata
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova.i18n import _
from nova.policies import server_metadata as sm_policies


class ServerMetadataController(wsgi.Controller):
    """The server metadata API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        super(ServerMetadataController, self).__init__()

    def _get_metadata(self, context, server_id):
        server = common.get_instance(self.compute_api, context, server_id)
        try:
            # NOTE(mikal): get_instance_metadata sometimes returns
            # InstanceNotFound in unit tests, even though the instance is
            # fetched on the line above. I blame mocking.
            meta = self.compute_api.get_instance_metadata(context, server)
        except exception.InstanceNotFound:
            msg = _('Server does not exist')
            raise exc.HTTPNotFound(explanation=msg)
        meta_dict = {}
        for key, value in meta.items():
            meta_dict[key] = value
        return meta_dict

    @extensions.expected_errors(404)
    def index(self, req, server_id):
        """Returns the list of metadata for a given instance."""
        context = req.environ['nova.context']
        context.can(sm_policies.POLICY_ROOT % 'index')
        return {'metadata': self._get_metadata(context, server_id)}

    @extensions.expected_errors((400, 403, 404, 409))
    # NOTE(gmann): Returns 200 for backwards compatibility but should be 201
    # as this operation complete the creation of metadata.
    @validation.schema(server_metadata.create)
    def create(self, req, server_id, body):
        metadata = body['metadata']
        context = req.environ['nova.context']
        context.can(sm_policies.POLICY_ROOT % 'create')
        new_metadata = self._update_instance_metadata(context,
                                                      server_id,
                                                      metadata,
                                                      delete=False)

        return {'metadata': new_metadata}

    @extensions.expected_errors((400, 403, 404, 409))
    @validation.schema(server_metadata.update)
    def update(self, req, server_id, id, body):
        context = req.environ['nova.context']
        context.can(sm_policies.POLICY_ROOT % 'update')
        meta_item = body['meta']
        if id not in meta_item:
            expl = _('Request body and URI mismatch')
            raise exc.HTTPBadRequest(explanation=expl)

        self._update_instance_metadata(context,
                                       server_id,
                                       meta_item,
                                       delete=False)

        return {'meta': meta_item}

    @extensions.expected_errors((400, 403, 404, 409))
    @validation.schema(server_metadata.update_all)
    def update_all(self, req, server_id, body):
        context = req.environ['nova.context']
        context.can(sm_policies.POLICY_ROOT % 'update_all')
        metadata = body['metadata']
        new_metadata = self._update_instance_metadata(context,
                                                      server_id,
                                                      metadata,
                                                      delete=True)

        return {'metadata': new_metadata}

    def _update_instance_metadata(self, context, server_id, metadata,
                                  delete=False):
        server = common.get_instance(self.compute_api, context, server_id)
        try:
            return self.compute_api.update_instance_metadata(context,
                                                             server,
                                                             metadata,
                                                             delete)

        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        except exception.QuotaError as error:
            raise exc.HTTPForbidden(explanation=error.format_message())

        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'update metadata', server_id)

    @extensions.expected_errors(404)
    def show(self, req, server_id, id):
        """Return a single metadata item."""
        context = req.environ['nova.context']
        context.can(sm_policies.POLICY_ROOT % 'show')
        data = self._get_metadata(context, server_id)

        try:
            return {'meta': {id: data[id]}}
        except KeyError:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

    @extensions.expected_errors((404, 409))
    @wsgi.response(204)
    def delete(self, req, server_id, id):
        """Deletes an existing metadata."""
        context = req.environ['nova.context']
        context.can(sm_policies.POLICY_ROOT % 'delete')
        metadata = self._get_metadata(context, server_id)

        if id not in metadata:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

        server = common.get_instance(self.compute_api, context, server_id)
        try:
            self.compute_api.delete_instance_metadata(context, server, id)

        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete metadata', server_id)
