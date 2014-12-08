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
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.i18n import _


class Controller(object):
    """The server metadata API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        super(Controller, self).__init__()

    def _get_metadata(self, context, server_id):
        try:
            server = self.compute_api.get(context, server_id)
            meta = self.compute_api.get_instance_metadata(context, server)
        except exception.InstanceNotFound:
            msg = _('Server does not exist')
            raise exc.HTTPNotFound(explanation=msg)

        meta_dict = {}
        for key, value in meta.iteritems():
            meta_dict[key] = value
        return meta_dict

    def index(self, req, server_id):
        """Returns the list of metadata for a given instance."""
        context = req.environ['nova.context']
        return {'metadata': self._get_metadata(context, server_id)}

    def create(self, req, server_id, body):
        try:
            metadata = body['metadata']
        except (KeyError, TypeError):
            msg = _("Malformed request body")
            raise exc.HTTPBadRequest(explanation=msg)
        if not isinstance(metadata, dict):
            msg = _("Malformed request body. metadata must be object")
            raise exc.HTTPBadRequest(explanation=msg)

        context = req.environ['nova.context']

        new_metadata = self._update_instance_metadata(context,
                                                      server_id,
                                                      metadata,
                                                      delete=False)

        return {'metadata': new_metadata}

    def update(self, req, server_id, id, body):
        try:
            meta_item = body['meta']
        except (TypeError, KeyError):
            expl = _('Malformed request body')
            raise exc.HTTPBadRequest(explanation=expl)

        if not isinstance(meta_item, dict):
            msg = _("Malformed request body. meta item must be object")
            raise exc.HTTPBadRequest(explanation=msg)

        if id not in meta_item:
            expl = _('Request body and URI mismatch')
            raise exc.HTTPBadRequest(explanation=expl)

        if len(meta_item) > 1:
            expl = _('Request body contains too many items')
            raise exc.HTTPBadRequest(explanation=expl)

        context = req.environ['nova.context']
        self._update_instance_metadata(context,
                                       server_id,
                                       meta_item,
                                       delete=False)

        return {'meta': meta_item}

    def update_all(self, req, server_id, body):
        try:
            metadata = body['metadata']
        except (TypeError, KeyError):
            expl = _('Malformed request body')
            raise exc.HTTPBadRequest(explanation=expl)

        if not isinstance(metadata, dict):
            msg = _("Malformed request body. metadata must be object")
            raise exc.HTTPBadRequest(explanation=msg)

        context = req.environ['nova.context']
        new_metadata = self._update_instance_metadata(context,
                                                      server_id,
                                                      metadata,
                                                      delete=True)

        return {'metadata': new_metadata}

    def _update_instance_metadata(self, context, server_id, metadata,
                                  delete=False):
        try:
            server = self.compute_api.get(context, server_id,
                                          want_objects=True)
            return self.compute_api.update_instance_metadata(context,
                                                             server,
                                                             metadata,
                                                             delete)

        except exception.InstanceNotFound:
            msg = _('Server does not exist')
            raise exc.HTTPNotFound(explanation=msg)

        except (ValueError, AttributeError):
            msg = _("Malformed request body")
            raise exc.HTTPBadRequest(explanation=msg)

        except exception.InvalidMetadata as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

        except exception.InvalidMetadataSize as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message())

        except exception.QuotaError as error:
            raise exc.HTTPForbidden(explanation=error.format_message())

        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'update metadata', server_id)

    def show(self, req, server_id, id):
        """Return a single metadata item."""
        context = req.environ['nova.context']
        data = self._get_metadata(context, server_id)

        try:
            return {'meta': {id: data[id]}}
        except KeyError:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.response(204)
    def delete(self, req, server_id, id):
        """Deletes an existing metadata."""
        context = req.environ['nova.context']

        metadata = self._get_metadata(context, server_id)

        if id not in metadata:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

        server = common.get_instance(self.compute_api, context, server_id,
                                     want_objects=True)
        try:
            self.compute_api.delete_instance_metadata(context, server, id)

        except exception.InstanceNotFound:
            msg = _('Server does not exist')
            raise exc.HTTPNotFound(explanation=msg)

        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())

        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete metadata', server_id)


def create_resource():
    return wsgi.Resource(Controller())
