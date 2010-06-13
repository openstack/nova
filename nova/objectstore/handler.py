#!/usr/bin/env python
#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

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
import os
import urllib
import json
import logging
import multiprocessing


from nova import vendor
from tornado import escape, web

from nova import exception
from nova import flags
from nova.endpoint import api
from nova.objectstore import bucket
from nova.objectstore import image


FLAGS = flags.FLAGS


def catch_nova_exceptions(target):
    # FIXME: find a way to wrap all handlers in the web.Application.__init__ ?
    def wrapper(*args, **kwargs):
        try:
            return target(*args, **kwargs)
        except exception.NotFound:
            raise web.HTTPError(404)
        except exception.NotAuthorized:
            raise web.HTTPError(403)

    return wrapper


class Application(web.Application):
    """Implementation of an S3-like storage server based on local files."""
    def __init__(self, user_manager):
        web.Application.__init__(self, [
            (r"/", RootHandler),
            (r"/_images/(.+)", ImageDownloadHandler),
            (r"/_images/", ImageHandler),
            (r"/([^/]+)/(.+)", ObjectHandler),
            (r"/([^/]+)/", BucketHandler),
        ])
        self.buckets_path = os.path.abspath(FLAGS.buckets_path)
        self.images_path = os.path.abspath(FLAGS.images_path)

        if not os.path.exists(self.buckets_path):
            raise Exception("buckets_path does not exist")
        if not os.path.exists(self.images_path):
            raise Exception("images_path does not exist")
        self.user_manager = user_manager


class BaseRequestHandler(web.RequestHandler):
    SUPPORTED_METHODS = ("PUT", "GET", "DELETE", "HEAD")

    @property
    def context(self):
        if not hasattr(self, '_context'):
            try:
                # Authorization Header format: 'AWS <access>:<secret>'
                access, sep, secret = self.request.headers['Authorization'].split(' ')[1].rpartition(':')
                (user, project) = self.application.user_manager.authenticate(access, secret, {}, self.request.method, self.request.host, self.request.path, False)
                # FIXME: check signature here!
                self._context = api.APIRequestContext(self, user, project)
            except exception.Error, ex:
                logging.debug("Authentication Failure: %s" % ex)
                raise web.HTTPError(403)
        return self._context

    def render_xml(self, value):
        assert isinstance(value, dict) and len(value) == 1
        self.set_header("Content-Type", "application/xml; charset=UTF-8")
        name = value.keys()[0]
        parts = []
        parts.append('<' + escape.utf8(name) +
                     ' xmlns="http://doc.s3.amazonaws.com/2006-03-01">')
        self._render_parts(value.values()[0], parts)
        parts.append('</' + escape.utf8(name) + '>')
        self.finish('<?xml version="1.0" encoding="UTF-8"?>\n' +
                    ''.join(parts))

    def _render_parts(self, value, parts=[]):
        if isinstance(value, basestring):
            parts.append(escape.xhtml_escape(value))
        elif isinstance(value, int) or isinstance(value, long):
            parts.append(str(value))
        elif isinstance(value, datetime.datetime):
            parts.append(value.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        elif isinstance(value, dict):
            for name, subvalue in value.iteritems():
                if not isinstance(subvalue, list):
                    subvalue = [subvalue]
                for subsubvalue in subvalue:
                    parts.append('<' + escape.utf8(name) + '>')
                    self._render_parts(subsubvalue, parts)
                    parts.append('</' + escape.utf8(name) + '>')
        else:
            raise Exception("Unknown S3 value type %r", value)

    def head(self, *args, **kwargs):
        return self.get(*args, **kwargs)


class RootHandler(BaseRequestHandler):
    def get(self):
        buckets = [b for b in bucket.Bucket.all() if b.is_authorized(self.context)]

        self.render_xml({"ListAllMyBucketsResult": {
            "Buckets": {"Bucket": [b.metadata for b in buckets]},
        }})


class BucketHandler(BaseRequestHandler):
    @catch_nova_exceptions
    def get(self, bucket_name):
        logging.debug("List keys for bucket %s" % (bucket_name))

        bucket_object = bucket.Bucket(bucket_name)

        if not bucket_object.is_authorized(self.context):
            raise web.HTTPError(403)

        prefix = self.get_argument("prefix", u"")
        marker = self.get_argument("marker", u"")
        max_keys = int(self.get_argument("max-keys", 1000))
        terse = int(self.get_argument("terse", 0))

        results = bucket_object.list_keys(prefix=prefix, marker=marker, max_keys=max_keys, terse=terse)
        self.render_xml({"ListBucketResult": results})

    @catch_nova_exceptions
    def put(self, bucket_name):
        logging.debug("Creating bucket %s" % (bucket_name))
        bucket.Bucket.create(bucket_name, self.context)
        self.finish()

    @catch_nova_exceptions
    def delete(self, bucket_name):
        logging.debug("Deleting bucket %s" % (bucket_name))
        bucket_object = bucket.Bucket(bucket_name)

        if not bucket_object.is_authorized(self.context):
            raise web.HTTPError(403)

        bucket_object.delete()
        self.set_status(204)
        self.finish()


class ObjectHandler(BaseRequestHandler):
    @catch_nova_exceptions
    def get(self, bucket_name, object_name):
        logging.debug("Getting object: %s / %s" % (bucket_name, object_name))

        bucket_object = bucket.Bucket(bucket_name)

        if not bucket_object.is_authorized(self.context):
            raise web.HTTPError(403)

        obj = bucket_object[urllib.unquote(object_name)]
        self.set_header("Content-Type", "application/unknown")
        self.set_header("Last-Modified", datetime.datetime.utcfromtimestamp(obj.mtime))
        self.set_header("Etag", '"' + obj.md5 + '"')
        self.finish(obj.read())

    @catch_nova_exceptions
    def put(self, bucket_name, object_name):
        logging.debug("Putting object: %s / %s" % (bucket_name, object_name))
        bucket_object = bucket.Bucket(bucket_name)

        if not bucket_object.is_authorized(self.context):
            raise web.HTTPError(403)

        key = urllib.unquote(object_name)
        bucket_object[key] = self.request.body
        self.set_header("Etag", '"' + bucket_object[key].md5 + '"')
        self.finish()

    @catch_nova_exceptions
    def delete(self, bucket_name, object_name):
        logging.debug("Deleting object: %s / %s" % (bucket_name, object_name))
        bucket_object = bucket.Bucket(bucket_name)

        if not bucket_object.is_authorized(self.context):
            raise web.HTTPError(403)

        del bucket_object[urllib.unquote(object_name)]
        self.set_status(204)
        self.finish()


class ImageDownloadHandler(BaseRequestHandler):
    SUPPORTED_METHODS = ("GET", )

    @catch_nova_exceptions
    def get(self, image_id):
        """ send the decrypted image file

        streaming content through python is slow and should only be used
        in development mode.  You should serve files via a web server
        in production.
        """

        self.set_header("Content-Type", "application/octet-stream")

        READ_SIZE = 64*1024

        img = image.Image(image_id)
        with open(img.image_path, 'rb') as fp:
            s = fp.read(READ_SIZE)
            while s:
                self.write(s)
                s = fp.read(READ_SIZE)

        self.finish()

class ImageHandler(BaseRequestHandler):
    SUPPORTED_METHODS = ("POST", "PUT", "GET", "DELETE")

    @catch_nova_exceptions
    def get(self):
        """ returns a json listing of all images
            that a user has permissions to see """

        images = [i for i in image.Image.all() if i.is_authorized(self.context)]

        self.finish(json.dumps([i.metadata for i in images]))

    @catch_nova_exceptions
    def put(self):
        """ create a new registered image """

        image_id = self.get_argument('image_id', u'')
        image_location = self.get_argument('image_location', u'')

        image_path = os.path.join(FLAGS.images_path, image_id)
        if not image_path.startswith(FLAGS.images_path) or \
           os.path.exists(image_path):
            raise web.HTTPError(403)

        bucket_object = bucket.Bucket(image_location.split("/")[0])
        manifest = image_location[len(image_location.split('/')[0])+1:]

        if not bucket_object.is_authorized(self.context):
            raise web.HTTPError(403)

        p = multiprocessing.Process(target=image.Image.create,args=
            (image_id, image_location, self.context))
        p.start()
        self.finish()

    @catch_nova_exceptions
    def post(self):
        """ update image attributes: public/private """

        image_id = self.get_argument('image_id', u'')
        operation = self.get_argument('operation', u'')

        image_object = image.Image(image_id)

        if not image.is_authorized(self.context):
            raise web.HTTPError(403)

        image_object.set_public(operation=='add')

        self.finish()

    @catch_nova_exceptions
    def delete(self):
        """ delete a registered image """
        image_id = self.get_argument("image_id", u"")
        image_object = image.Image(image_id)

        if not image.is_authorized(self.context):
            raise web.HTTPError(403)

        image_object.delete()

        self.set_status(204)
