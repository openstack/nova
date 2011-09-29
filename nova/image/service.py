# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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


from nova import utils


class BaseImageService(object):
    """Base class for providing image search and retrieval services.

    ImageService exposes two concepts of metadata:

        1. First-class attributes: This is metadata that is common to all
           ImageService subclasses and is shared across all hypervisors. These
           attributes are defined by IMAGE_ATTRS.

        2. Properties: This is metdata that is specific to an ImageService,
           and Image, or a particular hypervisor. Any attribute not present in
           BASE_IMAGE_ATTRS should be considered an image property.

    This means that ImageServices will return BASE_IMAGE_ATTRS as keys in the
    metadata dict, all other attributes will be returned as keys in the nested
    'properties' dict.

    """

    BASE_IMAGE_ATTRS = ['id', 'name', 'created_at', 'updated_at',
                        'deleted_at', 'deleted', 'status', 'is_public']

    # NOTE(sirp): ImageService subclasses may override this to aid translation
    # between BaseImageService attributes and additional metadata stored by
    # the ImageService subclass
    SERVICE_IMAGE_ATTRS = []

    def index(self, context, *args, **kwargs):
        """List images.

        :returns: a sequence of mappings with the following signature
                  {'id': opaque id of image, 'name': name of image}

        """
        raise NotImplementedError

    def detail(self, context, *args, **kwargs):
        """Detailed information about an images.

        :returns: a sequence of mappings with the following signature
                    {'id': opaque id of image,
                     'name': name of image,
                     'created_at': creation datetime object,
                     'updated_at': modification datetime object,
                     'deleted_at': deletion datetime object or None,
                     'deleted': boolean indicating if image has been deleted,
                     'status': string description of image status,
                     'is_public': boolean indicating if image is public
                     }

        If the service does not implement a method that provides a detailed
        set of information about images, then the method should raise
        NotImplementedError, in which case Nova will emulate this method
        with repeated calls to show() for each image received from the
        index() method.

        """
        raise NotImplementedError

    def show(self, context, image_id):
        """Detailed information about an image.

        :returns: a mapping with the following signature:
            {'id': opaque id of image,
             'name': name of image,
             'created_at': creation datetime object,
             'updated_at': modification datetime object,
             'deleted_at': deletion datetime object or None,
             'deleted': boolean indicating if image has been deleted,
             'status': string description of image status,
             'is_public': boolean indicating if image is public
             }, ...

        :raises: NotFound if the image does not exist

        """
        raise NotImplementedError

    def get(self, context, data):
        """Get an image.

        :param data: a file-like object to hold binary image data
        :returns: a dict containing image metadata, writes image data to data.
        :raises: NotFound if the image does not exist

        """
        raise NotImplementedError

    def create(self, context, metadata, data=None):
        """Store the image metadata and data.

        :returns: the new image metadata.
        :raises: AlreadyExists if the image already exist.

        """
        raise NotImplementedError

    def update(self, context, image_id, metadata, data=None):
        """Update the given image metadata and data and return the metadata.

        :raises: NotFound if the image does not exist.

        """
        raise NotImplementedError

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: NotFound if the image does not exist.

        """
        raise NotImplementedError

    @staticmethod
    def _is_image_available(context, image_meta):
        """Check image availability.

        Images are always available if they are public or if the user is an
        admin.

        Otherwise, we filter by project_id (if present) and then fall-back to
        images owned by user.

        """
        # FIXME(sirp): We should be filtering by user_id on the Glance side
        # for security; however, we can't do that until we get authn/authz
        # sorted out. Until then, filtering in Nova.
        if image_meta['is_public'] or context.is_admin:
            return True

        properties = image_meta['properties']

        if context.project_id and ('owner_id' in properties):
            return str(properties['owner_id']) == str(context.project_id)

        if context.project_id and ('project_id' in properties):
            return str(properties['project_id']) == str(context.project_id)

        try:
            user_id = properties['user_id']
        except KeyError:
            return False

        return str(user_id) == str(context.user_id)

    @classmethod
    def _translate_to_base(cls, metadata):
        """Return a metadata dictionary that is BaseImageService compliant.

        This is used by subclasses to expose only a metadata dictionary that
        is the same across ImageService implementations.

        """
        return cls._propertify_metadata(metadata, cls.BASE_IMAGE_ATTRS)

    @classmethod
    def _translate_to_service(cls, metadata):
        """Return a metadata dict that is usable by the ImageService subclass.

        As an example, Glance has additional attributes (like 'location'); the
        BaseImageService considers these properties, but we need to translate
        these back to first-class attrs for sending to Glance. This method
        handles this by allowing you to specify the attributes an ImageService
        considers first-class.

        """
        if not cls.SERVICE_IMAGE_ATTRS:
            raise NotImplementedError(_('Cannot use this without specifying '
                                        'SERVICE_IMAGE_ATTRS for subclass'))
        return cls._propertify_metadata(metadata, cls.SERVICE_IMAGE_ATTRS)

    @staticmethod
    def _propertify_metadata(metadata, keys):
        """Move unknown keys to a nested 'properties' dict.

        :returns: a new dict with the keys moved.

        """
        flattened = utils.flatten_dict(metadata)
        attributes, properties = utils.partition_dict(flattened, keys)
        attributes['properties'] = properties
        return attributes
