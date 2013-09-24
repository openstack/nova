# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova.openstack.common.gettextutils import _


# NOTE(cyeoh): We cannot use the metadata serializers from
# nova.api.openstack.common because the JSON format is different from
# the V2 API. The metadata serializer for V2 is in common because it
# is shared between image and server metadata, but since the image api
# is not ported to the V3 API there is no point creating a common
# version for the V3 API
class MetaItemDeserializer(wsgi.MetadataXMLDeserializer):
    def deserialize(self, text):
        dom = xmlutil.safe_minidom_parse_string(text)
        metadata_node = self.find_first_child_named(dom, "metadata")
        key = metadata_node.getAttribute("key")
        metadata = {}
        metadata[key] = self.extract_text(metadata_node)
        return {'body': {'metadata': metadata}}


class MetaItemTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        sel = xmlutil.Selector('metadata', xmlutil.get_items, 0)
        root = xmlutil.TemplateElement('metadata', selector=sel)
        root.set('key', 0)
        root.text = 1
        return xmlutil.MasterTemplate(root, 1, nsmap=common.metadata_nsmap)


class ServerMetadataController(wsgi.Controller):
    """The server metadata API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        super(ServerMetadataController, self).__init__()

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

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=common.MetadataTemplate)
    def index(self, req, server_id):
        """Returns the list of metadata for a given instance."""
        context = req.environ['nova.context']
        return {'metadata': self._get_metadata(context, server_id)}

    @extensions.expected_errors((400, 404, 409, 413))
    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    @wsgi.response(201)
    def create(self, req, server_id, body):
        if not self.is_valid_body(body, 'metadata'):
            msg = _("Malformed request body")
            raise exc.HTTPBadRequest(explanation=msg)
        metadata = body['metadata']
        context = req.environ['nova.context']

        new_metadata = self._update_instance_metadata(context,
                                                      server_id,
                                                      metadata,
                                                      delete=False)

        return {'metadata': new_metadata}

    @extensions.expected_errors((400, 404, 409, 413))
    @wsgi.serializers(xml=MetaItemTemplate)
    @wsgi.deserializers(xml=MetaItemDeserializer)
    def update(self, req, server_id, id, body):
        if not self.is_valid_body(body, 'metadata'):
            msg = _("Malformed request body")
            raise exc.HTTPBadRequest(explanation=msg)
        meta_item = body['metadata']
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

        return {'metadata': meta_item}

    @extensions.expected_errors((400, 404, 409, 413))
    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    def update_all(self, req, server_id, body):
        if not self.is_valid_body(body, 'metadata'):
            msg = _("Malformed request body")
            raise exc.HTTPBadRequest(explanation=msg)
        metadata = body['metadata']
        context = req.environ['nova.context']
        new_metadata = self._update_instance_metadata(context,
                                                      server_id,
                                                      metadata,
                                                      delete=True)

        return {'metadata': new_metadata}

    def _update_instance_metadata(self, context, server_id, metadata,
                                  delete=False):
        try:
            server = self.compute_api.get(context, server_id)
            return self.compute_api.update_instance_metadata(context,
                                                             server,
                                                             metadata,
                                                             delete)

        except exception.InstanceNotFound:
            msg = _('Server does not exist')
            raise exc.HTTPNotFound(explanation=msg)

        except exception.InvalidMetadata as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())

        except exception.InvalidMetadataSize as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message())

        except exception.QuotaError as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.format_message(),
                headers={'Retry-After': 0})

        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'update metadata')

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=MetaItemTemplate)
    def show(self, req, server_id, id):
        """Return a single metadata item."""
        context = req.environ['nova.context']
        data = self._get_metadata(context, server_id)

        try:
            return {'metadata': {id: data[id]}}
        except KeyError:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

    @extensions.expected_errors((404, 409))
    @wsgi.response(204)
    def delete(self, req, server_id, id):
        """Deletes an existing metadata."""
        context = req.environ['nova.context']

        metadata = self._get_metadata(context, server_id)

        if id not in metadata:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

        try:
            server = self.compute_api.get(context, server_id)
            self.compute_api.delete_instance_metadata(context, server, id)

        except exception.InstanceNotFound:
            msg = _('Server does not exist')
            raise exc.HTTPNotFound(explanation=msg)

        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete metadata')


class ServerMetadata(extensions.V3APIExtensionBase):
    """Server Metadata API."""
    name = "Server Metadata"
    alias = "server-metadata"
    namespace = "http://docs.openstack.org/compute/core/server_metadata/v3"
    version = 1

    def get_resources(self):
        parent = {'member_name': 'server',
                  'collection_name': 'servers'}
        resources = [extensions.ResourceExtension('metadata',
                                                  ServerMetadataController(),
                                                  member_name='server_meta',
                                                  parent=parent,
                                                  custom_routes_fn=
                                                  self.server_metadata_map
                                                  )]
        return resources

    def get_controller_extensions(self):
        return []

    def server_metadata_map(self, mapper, wsgi_resource):
        mapper.connect("metadata", "/servers/{server_id}/metadata",
                       controller=wsgi_resource,
                       action='update_all', conditions={"method": ['PUT']})
