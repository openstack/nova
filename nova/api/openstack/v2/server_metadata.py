# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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


class Controller(object):
    """ The server metadata API controller for the Openstack API """

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

    @wsgi.serializers(xml=common.MetadataTemplate)
    def index(self, req, server_id):
        """ Returns the list of metadata for a given instance """
        context = req.environ['nova.context']
        return {'metadata': self._get_metadata(context, server_id)}

    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    def create(self, req, server_id, body):
        try:
            metadata = body['metadata']
        except (KeyError, TypeError):
            msg = _("Malformed request body")
            raise exc.HTTPBadRequest(explanation=msg)

        context = req.environ['nova.context']

        new_metadata = self._update_instance_metadata(context,
                                                      server_id,
                                                      metadata,
                                                      delete=False)

        return {'metadata': new_metadata}

    @wsgi.serializers(xml=common.MetaItemTemplate)
    @wsgi.deserializers(xml=common.MetaItemDeserializer)
    def update(self, req, server_id, id, body):
        try:
            meta_item = body['meta']
        except (TypeError, KeyError):
            expl = _('Malformed request body')
            raise exc.HTTPBadRequest(explanation=expl)

        try:
            meta_value = meta_item[id]
        except (AttributeError, KeyError):
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

    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    def update_all(self, req, server_id, body):
        try:
            metadata = body['metadata']
        except (TypeError, KeyError):
            expl = _('Malformed request body')
            raise exc.HTTPBadRequest(explanation=expl)

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

        except (ValueError, AttributeError):
            msg = _("Malformed request body")
            raise exc.HTTPBadRequest(explanation=msg)

        except exception.QuotaError as error:
            self._handle_quota_error(error)

    @wsgi.serializers(xml=common.MetaItemTemplate)
    def show(self, req, server_id, id):
        """ Return a single metadata item """
        context = req.environ['nova.context']
        data = self._get_metadata(context, server_id)

        try:
            return {'meta': {id: data[id]}}
        except KeyError:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.response(204)
    def delete(self, req, server_id, id):
        """ Deletes an existing metadata """
        context = req.environ['nova.context']

        metadata = self._get_metadata(context, server_id)

        try:
            meta_value = metadata[id]
        except KeyError:
            msg = _("Metadata item was not found")
            raise exc.HTTPNotFound(explanation=msg)

        try:
            server = self.compute_api.get(context, server_id)
            self.compute_api.delete_instance_metadata(context, server, id)
        except exception.InstanceNotFound:
            msg = _('Server does not exist')
            raise exc.HTTPNotFound(explanation=msg)

    def _handle_quota_error(self, error):
        """Reraise quota errors as api-specific http exceptions."""
        if error.code == "MetadataLimitExceeded":
            raise exc.HTTPRequestEntityTooLarge(explanation=error.message,
                                                headers={'Retry-After': 0})
        raise error


def create_resource():
    return wsgi.Resource(Controller())
