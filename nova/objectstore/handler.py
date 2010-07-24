# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2010 OpenStack LLC.
#    Copyright 2010 United States Government as represented by the
#    Administrator of the National Aeronautics and Space Administration.
#    All Rights Reserved.
#
#    Copyright 2009 Facebook
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
Implementation of an S3-like storage server based on local files.

Useful to test features that will eventually run on S3, or if you want to
run something locally that was once running on S3.

We don't support all the features of S3, but it does work with the
standard S3 client for the most basic semantics. To use the standard
S3 client with this module::

    c = S3.AWSAuthConnection("", "", server="localhost", port=8888,
                             is_secure=False)
    c.create_bucket("mybucket")
    c.put("mybucket", "mykey", "a value")
    print c.get("mybucket", "mykey").body

"""

import datetime
import logging
import json
import multiprocessing
import os
from tornado import escape
import urllib

from twisted.application import internet, service
from twisted.web.resource import Resource
from twisted.web import server, static


from nova import exception
from nova import flags
from nova.auth import users
from nova.endpoint import api
from nova.objectstore import bucket
from nova.objectstore import image


FLAGS = flags.FLAGS

def render_xml(request, value):
    assert isinstance(value, dict) and len(value) == 1
    request.setHeader("Content-Type", "application/xml; charset=UTF-8")

    name = value.keys()[0]
    request.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    request.write('<' + escape.utf8(name) +
                 ' xmlns="http://doc.s3.amazonaws.com/2006-03-01">')
    _render_parts(value.values()[0], request.write)
    request.write('</' + escape.utf8(name) + '>')
    request.finish()

def finish(request, content=None):
    if content:
        request.write(content)
    request.finish()

def _render_parts(value, write_cb):
    if isinstance(value, basestring):
        write_cb(escape.xhtml_escape(value))
    elif isinstance(value, int) or isinstance(value, long):
        write_cb(str(value))
    elif isinstance(value, datetime.datetime):
        write_cb(value.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    elif isinstance(value, dict):
        for name, subvalue in value.iteritems():
            if not isinstance(subvalue, list):
                subvalue = [subvalue]
            for subsubvalue in subvalue:
                write_cb('<' + escape.utf8(name) + '>')
                _render_parts(subsubvalue, write_cb)
                write_cb('</' + escape.utf8(name) + '>')
    else:
        raise Exception("Unknown S3 value type %r", value)

def get_argument(request, key, default_value):
    if key in request.args:
        return request.args[key][0]
    return default_value

def get_context(request):
    try:
        # Authorization Header format: 'AWS <access>:<secret>'
        authorization_header = request.getHeader('Authorization')
        if not authorization_header:
            raise exception.NotAuthorized
        access, sep, secret = authorization_header.split(' ')[1].rpartition(':')
        um = users.UserManager.instance()
        print 'um %s' % um
        (user, project) = um.authenticate(access, secret, {}, request.method, request.host, request.uri, False)
        # FIXME: check signature here!
        return api.APIRequestContext(None, user, project)
    except exception.Error as ex:
        logging.debug("Authentication Failure: %s" % ex)
        raise exception.NotAuthorized

class ErrorHandlingResource(Resource):
    """Maps exceptions to 404 / 401 codes.  Won't work for exceptions thrown after NOT_DONE_YET is returned."""
    # TODO(unassigned) (calling-all-twisted-experts): This needs to be plugged in to the right place in twisted...
    #   This doesn't look like it's the right place (consider exceptions in getChild; or after NOT_DONE_YET is returned     
    def render(self, request):
        try:
            return Resource.render(self, request)
        except exception.NotFound:
            request.setResponseCode(404)
            return ''
        except exception.NotAuthorized:
            request.setResponseCode(403)
            return ''

class S3(ErrorHandlingResource):
    """Implementation of an S3-like storage server based on local files."""
    def getChild(self, name, request):
        request.context = get_context(request)

        if name == '':
            return self
        elif name == '_images':
            return ImageResource()
        else:
            return BucketResource(name)

    def render_GET(self, request):
        buckets = [b for b in bucket.Bucket.all() if b.is_authorized(request.context)]

        render_xml(request, {"ListAllMyBucketsResult": {
            "Buckets": {"Bucket": [b.metadata for b in buckets]},
        }})
        return server.NOT_DONE_YET

class BucketResource(ErrorHandlingResource):
    def __init__(self, name):
        Resource.__init__(self)
        self.name = name

    def getChild(self, name, request):
        if name == '':
            return self
        else:
            return ObjectResource(bucket.Bucket(self.name), name)

    def render_GET(self, request):
        logging.debug("List keys for bucket %s" % (self.name))

        bucket_object = bucket.Bucket(self.name)

        if not bucket_object.is_authorized(request.context):
            raise exception.NotAuthorized

        prefix = get_argument(request, "prefix", u"")
        marker = get_argument(request, "marker", u"")
        max_keys = int(get_argument(request, "max-keys", 1000))
        terse = int(get_argument(request, "terse", 0))

        results = bucket_object.list_keys(prefix=prefix, marker=marker, max_keys=max_keys, terse=terse)
        render_xml(request, {"ListBucketResult": results})
        return server.NOT_DONE_YET

    def render_PUT(self, request):
        logging.debug("Creating bucket %s" % (self.name))
        try:
            print 'user is %s' % request.context
        except Exception as e:
            logging.exception(e)
        logging.debug("calling bucket.Bucket.create(%r, %r)" % (self.name, request.context))
        bucket.Bucket.create(self.name, request.context)
        return ''

    def render_DELETE(self, request):
        logging.debug("Deleting bucket %s" % (self.name))
        bucket_object = bucket.Bucket(self.name)

        if not bucket_object.is_authorized(request.context):
            raise exception.NotAuthorized

        bucket_object.delete()
        request.setResponseCode(204)
        return ''


class ObjectResource(ErrorHandlingResource):
    def __init__(self, bucket, name):
        Resource.__init__(self)
        self.bucket = bucket
        self.name = name

    def render_GET(self, request):
        logging.debug("Getting object: %s / %s" % (self.bucket.name, self.name))

        if not self.bucket.is_authorized(request.context):
            raise exception.NotAuthorized

        obj = self.bucket[urllib.unquote(self.name)]
        request.setHeader("Content-Type", "application/unknown")
        request.setHeader("Last-Modified", datetime.datetime.utcfromtimestamp(obj.mtime))
        request.setHeader("Etag", '"' + obj.md5 + '"')
        return static.File(obj.path).render_GET(request)

    def render_PUT(self, request):
        logging.debug("Putting object: %s / %s" % (self.bucket.name, self.name))

        if not self.bucket.is_authorized(request.context):
            raise exception.NotAuthorized

        key = urllib.unquote(self.name)
        request.content.seek(0, 0)
        self.bucket[key] = request.content.read()
        request.setHeader("Etag", '"' + self.bucket[key].md5 + '"')
        finish(request)
        return server.NOT_DONE_YET

    def render_DELETE(self, request):
        logging.debug("Deleting object: %s / %s" % (self.bucket.name, self.name))

        if not self.bucket.is_authorized(request.context):
            raise exception.NotAuthorized

        del self.bucket[urllib.unquote(self.name)]
        request.setResponseCode(204)
        return ''

class ImageResource(ErrorHandlingResource):
    isLeaf = True

    def getChild(self, name, request):
        if name == '':
            return self
        else:
            request.setHeader("Content-Type", "application/octet-stream")
            img = image.Image(name)
            return static.File(img.image_path)

    def render_GET(self, request):
        """ returns a json listing of all images
            that a user has permissions to see """

        images = [i for i in image.Image.all() if i.is_authorized(request.context)]

        request.write(json.dumps([i.metadata for i in images]))
        request.finish()
        return server.NOT_DONE_YET

    def render_PUT(self, request):
        """ create a new registered image """

        image_id = get_argument(request, 'image_id', u'')
        image_location = get_argument(request, 'image_location', u'')

        image_path = os.path.join(FLAGS.images_path, image_id)
        if not image_path.startswith(FLAGS.images_path) or \
           os.path.exists(image_path):
            raise exception.NotAuthorized

        bucket_object = bucket.Bucket(image_location.split("/")[0])
        manifest = image_location[len(image_location.split('/')[0])+1:]

        if not bucket_object.is_authorized(request.context):
            raise exception.NotAuthorized

        p = multiprocessing.Process(target=image.Image.register_aws_image,
                args=(image_id, image_location, request.context))
        p.start()
        return ''

    def render_POST(self, request):
        """ update image attributes: public/private """

        image_id = self.get_argument('image_id', u'')
        operation = self.get_argument('operation', u'')

        image_object = image.Image(image_id)

        if not image.is_authorized(request.context):
            raise exception.NotAuthorized

        image_object.set_public(operation=='add')

        return ''

    def render_DELETE(self, request):
        """ delete a registered image """
        image_id = self.get_argument("image_id", u"")
        image_object = image.Image(image_id)

        if not image.is_authorized(request.context):
            raise exception.NotAuthorized

        image_object.delete()

        request.setResponseCode(204)
        return ''

def get_application():
    root = S3()
    factory = server.Site(root)
    application = service.Application("objectstore")
    objectStoreService = internet.TCPServer(FLAGS.s3_port, factory)
    objectStoreService.setServiceParent(application)
    return application
