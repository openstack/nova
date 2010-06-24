# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration. 
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
import random
import urllib

from nova import vendor
import boto
import boto.s3

from nova import flags
from nova import utils

FLAGS = flags.FLAGS

def modify(context, image_id, operation):
    conn(context).make_request(
        method='POST',
        bucket='_images',
        query_args=qs({'image_id': image_id, 'operation': operation}))

    return True


def register(context, image_location):
    """ rpc call to register a new image based from a manifest """

    image_id = utils.generate_uid('ami')
    conn(context).make_request(
            method='PUT',
            bucket='_images',
            query_args=qs({'image_location': image_location,
                           'image_id': image_id}))

    return image_id

def list(context, filter_list=[]):
    """ return a list of all images that a user can see

    optionally filtered by a list of image_id """

    # FIXME: send along the list of only_images to check for
    response = conn(context).make_request(
            method='GET',
            bucket='_images')

    result = json.loads(response.read())
    if not filter_list is None:
        return [i for i in result if i['imageId'] in filter_list]
    return result

def deregister(context, image_id):
    """ unregister an image """
    conn(context).make_request(
            method='DELETE',
            bucket='_images',
            query_args=qs({'image_id': image_id}))

def conn(context):
    return boto.s3.connection.S3Connection (
        aws_access_key_id='%s:%s' % (context.user.access, context.project.name),
        aws_secret_access_key=context.user.secret,
        is_secure=False,
        calling_format=boto.s3.connection.OrdinaryCallingFormat(),
        port=FLAGS.s3_port,
        host=FLAGS.s3_host)


def qs(params):
    pairs = []
    for key in params.keys():
        pairs.append(key + '=' + urllib.quote(params[key]))
    return '&'.join(pairs)
