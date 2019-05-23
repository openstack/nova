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

from nova.api.openstack.api_version_request import \
    MAX_IMAGE_META_PROXY_API_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import image_metadata
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.i18n import _
import nova.image


class ImageMetadataController(wsgi.Controller):
    """The image metadata API controller for the OpenStack API."""

    def __init__(self):
        super(ImageMetadataController, self).__init__()
        self.image_api = nova.image.API()

    def _get_image(self, context, image_id):
        try:
            return self.image_api.get(context, image_id)
        except exception.ImageNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        except exception.ImageNotFound:
            msg = _("Image not found.")
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.Controller.api_version("2.1", MAX_IMAGE_META_PROXY_API_VERSION)
    @wsgi.expected_errors((403, 404))
    def index(self, req, image_id):
        """Returns the list of metadata for a given instance."""
        context = req.environ['nova.context']
        metadata = self._get_image(context, image_id)['properties']
        return dict(metadata=metadata)

    @wsgi.Controller.api_version("2.1", MAX_IMAGE_META_PROXY_API_VERSION)
    @wsgi.expected_errors((403, 404))
    def show(self, req, image_id, id):
        context = req.environ['nova.context']
        metadata = self._get_image(context, image_id)['properties']
        if id in metadata:
            return {'meta': {id: metadata[id]}}
        else:
            raise exc.HTTPNotFound()

    @wsgi.Controller.api_version("2.1", MAX_IMAGE_META_PROXY_API_VERSION)
    @wsgi.expected_errors((400, 403, 404))
    @validation.schema(image_metadata.create)
    def create(self, req, image_id, body):
        context = req.environ['nova.context']
        image = self._get_image(context, image_id)
        for key, value in body['metadata'].items():
            image['properties'][key] = value
        common.check_img_metadata_properties_quota(context,
                                                   image['properties'])
        try:
            image = self.image_api.update(context, image_id, image, data=None,
                                          purge_props=True)
        except exception.ImageNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(metadata=image['properties'])

    @wsgi.Controller.api_version("2.1", MAX_IMAGE_META_PROXY_API_VERSION)
    @wsgi.expected_errors((400, 403, 404))
    @validation.schema(image_metadata.update)
    def update(self, req, image_id, id, body):
        context = req.environ['nova.context']

        meta = body['meta']

        if id not in meta:
            expl = _('Request body and URI mismatch')
            raise exc.HTTPBadRequest(explanation=expl)

        image = self._get_image(context, image_id)
        image['properties'][id] = meta[id]
        common.check_img_metadata_properties_quota(context,
                                                   image['properties'])
        try:
            self.image_api.update(context, image_id, image, data=None,
                                  purge_props=True)
        except exception.ImageNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(meta=meta)

    @wsgi.Controller.api_version("2.1", MAX_IMAGE_META_PROXY_API_VERSION)
    @wsgi.expected_errors((400, 403, 404))
    @validation.schema(image_metadata.update_all)
    def update_all(self, req, image_id, body):
        context = req.environ['nova.context']
        image = self._get_image(context, image_id)
        metadata = body['metadata']
        common.check_img_metadata_properties_quota(context, metadata)
        image['properties'] = metadata
        try:
            self.image_api.update(context, image_id, image, data=None,
                                  purge_props=True)
        except exception.ImageNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        return dict(metadata=metadata)

    @wsgi.Controller.api_version("2.1", MAX_IMAGE_META_PROXY_API_VERSION)
    @wsgi.expected_errors((403, 404))
    @wsgi.response(204)
    def delete(self, req, image_id, id):
        context = req.environ['nova.context']
        image = self._get_image(context, image_id)
        if id not in image['properties']:
            msg = _("Invalid metadata key")
            raise exc.HTTPNotFound(explanation=msg)
        image['properties'].pop(id)
        try:
            self.image_api.update(context, image_id, image, data=None,
                                  purge_props=True)
        except exception.ImageNotAuthorized as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
