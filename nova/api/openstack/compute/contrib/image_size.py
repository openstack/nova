# Copyright 2013 Rackspace Hosting
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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil

authorize = extensions.soft_extension_authorizer('compute', 'image_size')


def make_image(elem):
    elem.set('{%s}size' % Image_size.namespace, '%s:size' % Image_size.alias)


class ImagesSizeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('images')
        elem = xmlutil.SubTemplateElement(root, 'image', selector='images')
        make_image(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Image_size.alias: Image_size.namespace})


class ImageSizeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('image', selector='image')
        make_image(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Image_size.alias: Image_size.namespace})


class ImageSizeController(wsgi.Controller):

    def _extend_image(self, image, image_cache):
        key = "%s:size" % Image_size.alias
        image[key] = image_cache['size']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ["nova.context"]
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ImageSizeTemplate())
            image_resp = resp_obj.obj['image']
            # image guaranteed to be in the cache due to the core API adding
            # it in its 'show' method
            image_cached = req.get_db_item('images', image_resp['id'])
            self._extend_image(image_resp, image_cached)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ImagesSizeTemplate())
            images_resp = list(resp_obj.obj['images'])
            # images guaranteed to be in the cache due to the core API adding
            # it in its 'detail' method
            for image in images_resp:
                image_cached = req.get_db_item('images', image['id'])
                self._extend_image(image, image_cached)


class Image_size(extensions.ExtensionDescriptor):
    """Adds image size to image listings."""

    name = "ImageSize"
    alias = "OS-EXT-IMG-SIZE"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "image_size/api/v1.1")
    updated = "2013-02-19T00:00:00Z"

    def get_controller_extensions(self):
        controller = ImageSizeController()
        extension = extensions.ControllerExtension(self, 'images', controller)
        return [extension]
