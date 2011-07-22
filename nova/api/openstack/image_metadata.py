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
from xml.dom import minidom

from nova import flags
from nova import image
from nova import quota
from nova import utils
from nova.api.openstack import wsgi


FLAGS = flags.FLAGS


class Controller(object):
    """The image metadata API controller for the Openstack API"""

    def __init__(self):
        self.image_service = image.get_default_image_service()

    def _get_metadata(self, context, image_id, image=None):
        if not image:
            image = self.image_service.show(context, image_id)
        metadata = image.get('properties', {})
        return metadata

    def _check_quota_limit(self, context, metadata):
        if metadata is None:
            return
        num_metadata = len(metadata)
        quota_metadata = quota.allowed_metadata_items(context, num_metadata)
        if quota_metadata < num_metadata:
            expl = _("Image metadata limit exceeded")
            raise exc.HTTPBadRequest(explanation=expl)

    def index(self, req, image_id):
        """Returns the list of metadata for a given instance"""
        context = req.environ['nova.context']
        metadata = self._get_metadata(context, image_id)
        return dict(metadata=metadata)

    def show(self, req, image_id, id):
        context = req.environ['nova.context']
        metadata = self._get_metadata(context, image_id)
        if id in metadata:
            return {'meta': {id: metadata[id]}}
        else:
            raise exc.HTTPNotFound()

    def create(self, req, image_id, body):
        context = req.environ['nova.context']
        img = self.image_service.show(context, image_id)
        metadata = self._get_metadata(context, image_id, img)
        if 'metadata' in body:
            for key, value in body['metadata'].iteritems():
                metadata[key] = value
        self._check_quota_limit(context, metadata)
        img['properties'] = metadata
        self.image_service.update(context, image_id, img, None)
        return dict(metadata=metadata)

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
        img = self.image_service.show(context, image_id)
        metadata = self._get_metadata(context, image_id, img)
        metadata[id] = meta[id]
        self._check_quota_limit(context, metadata)
        img['properties'] = metadata
        self.image_service.update(context, image_id, img, None)

        return req.body

    def delete(self, req, image_id, id):
        context = req.environ['nova.context']
        img = self.image_service.show(context, image_id)
        metadata = self._get_metadata(context, image_id)
        if not id in metadata:
            raise exc.HTTPNotFound()
        metadata.pop(id)
        img['properties'] = metadata
        self.image_service.update(context, image_id, img, None)


class ImageMetadataXMLSerializer(wsgi.XMLDictSerializer):
    def __init__(self, xmlns=wsgi.XMLNS_V11):
        super(ImageMetadataXMLSerializer, self).__init__(xmlns=xmlns)

    def _meta_item_to_xml(self, doc, key, value):
        node = doc.createElement('meta')
        doc.appendChild(node)
        node.setAttribute('key', '%s' % key)
        text = doc.createTextNode('%s' % value)
        node.appendChild(text)
        return node

    def meta_list_to_xml(self, xml_doc, meta_items):
        container_node = xml_doc.createElement('metadata')
        for (key, value) in meta_items:
            item_node = self._meta_item_to_xml(xml_doc, key, value)
            container_node.appendChild(item_node)
        return container_node

    def _meta_list_to_xml_string(self, metadata_dict):
        xml_doc = minidom.Document()
        items = metadata_dict['metadata'].items()
        container_node = self.meta_list_to_xml(xml_doc, items)
        xml_doc.appendChild(container_node)
        self._add_xmlns(container_node)
        return xml_doc.toprettyxml(indent='    ', encoding='UTF-8')

    def index(self, metadata_dict):
        return self._meta_list_to_xml_string(metadata_dict)

    def create(self, metadata_dict):
        return self._meta_list_to_xml_string(metadata_dict)

    def _meta_item_to_xml_string(self, meta_item_dict):
        xml_doc = minidom.Document()
        item_key, item_value = meta_item_dict.items()[0]
        item_node = self._meta_item_to_xml(xml_doc, item_key, item_value)
        xml_doc.appendChild(item_node)
        self._add_xmlns(item_node)
        return xml_doc.toprettyxml(indent='    ', encoding='UTF-8')

    def show(self, meta_item_dict):
        return self._meta_item_to_xml_string(meta_item_dict['meta'])

    def update(self, meta_item_dict):
        return self._meta_item_to_xml_string(meta_item_dict['meta'])


def create_resource():
    body_serializers = {
        'application/xml': ImageMetadataXMLSerializer(),
    }
    serializer = wsgi.ResponseSerializer(body_serializers)

    return wsgi.Resource(Controller(), serializer=serializer)
