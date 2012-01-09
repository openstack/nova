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
from nova import exception
from nova import flags
from nova import image


FLAGS = flags.FLAGS


class Controller(object):
    """The image metadata API controller for the Openstack API"""

    def __init__(self):
        self.image_service = image.get_default_image_service()

    def _get_image(self, context, image_id):
        try:
            return self.image_service.show(context, image_id)
        except exception.NotFound:
            msg = _("Image not found.")
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.serializers(xml=common.MetadataTemplate)
    def index(self, req, image_id):
        """Returns the list of metadata for a given instance"""
        context = req.environ['nova.context']
        metadata = self._get_image(context, image_id)['properties']
        return dict(metadata=metadata)

    @wsgi.serializers(xml=common.MetaItemTemplate)
    def show(self, req, image_id, id):
        context = req.environ['nova.context']
        metadata = self._get_image(context, image_id)['properties']
        if id in metadata:
            return {'meta': {id: metadata[id]}}
        else:
            raise exc.HTTPNotFound()

    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    def create(self, req, image_id, body):
        context = req.environ['nova.context']
        image = self._get_image(context, image_id)
        if 'metadata' in body:
            for key, value in body['metadata'].iteritems():
                image['properties'][key] = value
        common.check_img_metadata_quota_limit(context, image['properties'])
        self.image_service.update(context, image_id, image, None)
        return dict(metadata=image['properties'])

    @wsgi.serializers(xml=common.MetaItemTemplate)
    @wsgi.deserializers(xml=common.MetaItemDeserializer)
    def update(self, req, image_id, id, body):
        context = req.environ['nova.context']

        try:
            meta = body['meta']
        except KeyError:
            expl = _('Incorrect request body format')
            raise exc.HTTPBadRequest(explanation=expl)

        if not id in meta:
            expl = _('Request body and URI mismatch')
            raise exc.HTTPBadRequest(explanation=expl)
        if len(meta) > 1:
            expl = _('Request body contains too many items')
            raise exc.HTTPBadRequest(explanation=expl)

        image = self._get_image(context, image_id)
        image['properties'][id] = meta[id]
        common.check_img_metadata_quota_limit(context, image['properties'])
        self.image_service.update(context, image_id, image, None)
        return dict(meta=meta)

    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    def update_all(self, req, image_id, body):
        context = req.environ['nova.context']
        image = self._get_image(context, image_id)
        metadata = body.get('metadata', {})
        common.check_img_metadata_quota_limit(context, metadata)
        image['properties'] = metadata
        self.image_service.update(context, image_id, image, None)
        return dict(metadata=metadata)

    @wsgi.response(204)
    def delete(self, req, image_id, id):
        context = req.environ['nova.context']
        image = self._get_image(context, image_id)
        if not id in image['properties']:
            msg = _("Invalid metadata key")
            raise exc.HTTPNotFound(explanation=msg)
        image['properties'].pop(id)
        self.image_service.update(context, image_id, image, None)


def create_resource():
    return wsgi.Resource(Controller())
