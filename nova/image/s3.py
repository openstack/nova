# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Proxy AMI-related calls from the cloud controller, to the running
objectstore service.
"""

import json
import urllib

import boto.s3.connection

from nova import exception
from nova import flags
from nova import utils
from nova.auth import manager
from nova.image import service


FLAGS = flags.FLAGS


class S3ImageService(service.BaseImageService):

    def modify(self, context, image_id, operation):
        self._conn(context).make_request(
            method='POST',
            bucket='_images',
            query_args=self._qs({'image_id': image_id,
                                 'operation': operation}))
        return True

    def update(self, context, image_id, attributes):
        """update an image's attributes / info.json"""
        attributes.update({"image_id": image_id})
        self._conn(context).make_request(
            method='POST',
            bucket='_images',
            query_args=self._qs(attributes))
        return True

    def register(self, context, image_location):
        """ rpc call to register a new image based from a manifest """
        image_id = utils.generate_uid('ami')
        self._conn(context).make_request(
            method='PUT',
            bucket='_images',
            query_args=self._qs({'image_location': image_location,
                                 'image_id': image_id}))
        return image_id

    def _format_image(self, image):
        """Convert from S3 format to format defined by BaseImageService."""
        i = {}
        i['id'] = image.get('imageId')
        i['kernel_id'] = image.get('kernelId')
        i['ramdisk_id'] = image.get('ramdiskId')
        i['image_location'] = image.get('imageLocation')
        i['image_owner_id'] = image.get('imageOwnerId')
        i['image_state'] = image.get('imageState')
        i['type'] = image.get('type')
        i['is_public'] = image.get('isPublic')
        i['architecture'] = image.get('architecture')
        return i

    def index(self, context):
        """Return a list of all images that a user can see."""
        response = self._conn(context).make_request(
            method='GET',
            bucket='_images')
        images = json.loads(response.read())
        return [self._format_image(i) for i in images]

    def show(self, context, image_id):
        """return a image object if the context has permissions"""
        if FLAGS.connection_type == 'fake':
            return {'imageId': 'bar'}
        result = self.index(context)
        result = [i for i in result if i['imageId'] == image_id]
        if not result:
            raise exception.NotFound(_('Image %s could not be found')
                                     % image_id)
        image = result[0]
        return image

    def deregister(self, context, image_id):
        """ unregister an image """
        self._conn(context).make_request(
             method='DELETE',
             bucket='_images',
             query_args=self._qs({'image_id': image_id}))

    def _conn(self, context):
        access = manager.AuthManager().get_access_key(context.user,
                                                      context.project)
        secret = str(context.user.secret)
        calling = boto.s3.connection.OrdinaryCallingFormat()
        return boto.s3.connection.S3Connection(aws_access_key_id=access,
                                               aws_secret_access_key=secret,
                                               is_secure=False,
                                               calling_format=calling,
                                               port=FLAGS.s3_port,
                                               host=FLAGS.s3_host)

    def _qs(self, params):
        pairs = []
        for key in params.keys():
            pairs.append(key + '=' + urllib.quote(params[key]))
        return '&'.join(pairs)
