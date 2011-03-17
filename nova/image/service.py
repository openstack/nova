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


class BaseImageService(object):

    """Base class for providing image search and retrieval services"""

    def index(self, context):
        """
        Returns a sequence of mappings of id and name information about
        images.

        :rtype: array
        :retval: a sequence of mappings with the following signature
                    {'id': opaque id of image, 'name': name of image}

        """
        raise NotImplementedError

    def detail(self, context):
        """
        Returns a sequence of mappings of detailed information about images.

        :rtype: array
        :retval: a sequence of mappings with the following signature
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
        """
        Returns a dict containing image metadata for the given opaque image id.

        :retval a mapping with the following signature:

            {'id': opaque id of image,
             'name': name of image,
             'created_at': creation datetime object,
             'updated_at': modification datetime object,
             'deleted_at': deletion datetime object or None,
             'deleted': boolean indicating if image has been deleted,
             'status': string description of image status,
             'is_public': boolean indicating if image is public
             }, ...

        :raises NotFound if the image does not exist
        """
        raise NotImplementedError

    def get(self, context, data):
        """
        Returns a dict containing image metadata and writes image data to data.

        :param data: a file-like object to hold binary image data

        :raises NotFound if the image does not exist
        """
        raise NotImplementedError

    def create(self, context, metadata, data=None):
        """
        Store the image metadata and data and return the new image metadata.

        :raises AlreadyExists if the image already exist.

        """
        raise NotImplementedError

    def update(self, context, image_id, metadata, data=None):
        """Update the given image metadata and data and return the metadata

        :raises NotFound if the image does not exist.

        """
        raise NotImplementedError

    def delete(self, context, image_id):
        """
        Delete the given image.

        :raises NotFound if the image does not exist.

        """
        raise NotImplementedError
