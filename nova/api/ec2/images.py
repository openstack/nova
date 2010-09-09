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
objectstore daemon.
"""

import json
import urllib

import boto.s3.connection

from nova import flags
from nova import utils
from nova.auth import manager
from nova.image import service


FLAGS = flags.FLAGS


def modify(context, image_id, operation):
    service.S3ImageService(context)._conn().make_request(
        method='POST',
        bucket='_images',
        query_args=service.qs({'image_id': image_id, 'operation': operation}))

    return True


def register(context, image_location):
    """ rpc call to register a new image based from a manifest """

    image_id = utils.generate_uid('ami')
    service.S3ImageService(context)._conn().make_request(
            method='PUT',
            bucket='_images',
            query_args=service.qs({'image_location': image_location,
                           'image_id': image_id}))

    return image_id


def list(context, filter_list=[]):
    """ return a list of all images that a user can see

    optionally filtered by a list of image_id """

    result = service.S3ImageService(context).index().values()
    if not filter_list is None:
        return [i for i in result if i['imageId'] in filter_list]
    return result


def deregister(context, image_id):
    """ unregister an image """
    service.S3ImageService(context).delete(image_id)
