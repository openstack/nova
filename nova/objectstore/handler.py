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
import json
import multiprocessing
import os
import urllib

from twisted.application import internet
from twisted.application import service
from twisted.web import error
from twisted.web import resource
from twisted.web import server
from twisted.web import static

from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.auth import manager
from nova.objectstore import bucket
from nova.objectstore import image


LOG = logging.getLogger('nova.objectstore.handler')
FLAGS = flags.FLAGS
flags.DEFINE_string('s3_listen_host', '', 'Host to listen on.')


def render_xml(request, value):
    """Writes value as XML string to request"""
    assert isinstance(value, dict) and len(value) == 1
    request.setHeader("Content-Type", "application/xml; charset=UTF-8")

    name = value.keys()[0]
    request.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    request.write('<' + utils.utf8(name) +
                 ' xmlns="http://doc.s3.amazonaws.com/2006-03-01">')
    _render_parts(value.values()[0], request.write)
    request.write('</' + utils.utf8(name) + '>')
    request.finish()


def finish(request, content=None):
    """Finalizer method for request"""
    if content:
        request.write(content)
    request.finish()


def _render_parts(value, write_cb):
    """Helper method to render different Python objects to XML"""
    if isinstance(value, basestring):
        write_cb(utils.xhtml_escape(value))
    elif isinstance(value, int) or isinstance(value, long):
        write_cb(str(value))
    elif isinstance(value, datetime.datetime):
        write_cb(value.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    elif isinstance(value, dict):
        for name, subvalue in value.iteritems():
            if not isinstance(subvalue, list):
                subvalue = [subvalue]
            for subsubvalue in subvalue:
                write_cb('<' + utils.utf8(name) + '>')
                _render_parts(subsubvalue, write_cb)
                write_cb('</' + utils.utf8(name) + '>')
    else:
        raise Exception(_("Unknown S3 value type %r"), value)


def get_argument(request, key, default_value):
    """Returns the request's value at key, or default_value
    if not found
    """
    if key in request.args:
        return request.args[key][0]
    return default_value


def get_context(request):
    """Returns the supplied request's context object"""
    try:
        # Authorization Header format: 'AWS <access>:<secret>'
        authorization_header = request.getHeader('Authorization')
        if not authorization_header:
            raise exception.NotAuthorized()
        auth_header_value = authorization_header.split(' ')[1]
        access, _ignored, secret = auth_header_value.rpartition(':')
        am = manager.AuthManager()
        (user, project) = am.authenticate(access,
                                          secret,
                                          {},
                                          request.method,
                                          request.getRequestHostname(),
                                          request.uri,
                                          headers=request.getAllHeaders(),
                                          check_type='s3')
        rv = context.RequestContext(user, project)
        LOG.audit(_("Authenticated request"), context=rv)
        return rv
    except exception.Error as ex:
        LOG.debug(_("Authentication Failure: %s"), ex)
        raise exception.NotAuthorized()


class ErrorHandlingResource(resource.Resource):
    """Maps exceptions to 404 / 401 codes.  Won't work for
    exceptions thrown after NOT_DONE_YET is returned.
    """
    # TODO(unassigned) (calling-all-twisted-experts): This needs to be
    #                   plugged in to the right place in twisted...
    #                   This doesn't look like it's the right place
    #                   (consider exceptions in getChild; or after
    #                   NOT_DONE_YET is returned
    def render(self, request):
        """Renders the response as XML"""
        try:
            return resource.Resource.render(self, request)
        except exception.NotFound:
            request.setResponseCode(404)
            return ''
        except exception.NotAuthorized:
            request.setResponseCode(403)
            return ''


class S3(ErrorHandlingResource):
    """Implementation of an S3-like storage server based on local files."""
    def __init__(self):
        ErrorHandlingResource.__init__(self)

    def getChild(self, name, request):  # pylint: disable=C0103
        """Returns either the image or bucket resource"""
        request.context = get_context(request)
        if name == '':
            return self
        elif name == '_images':
            return ImagesResource()
        else:
            return BucketResource(name)

    def render_GET(self, request):  # pylint: disable=R0201
        """Renders the GET request for a list of buckets as XML"""
        LOG.debug(_('List of buckets requested'), context=request.context)
        buckets = [b for b in bucket.Bucket.all()
                   if b.is_authorized(request.context)]

        render_xml(request, {"ListAllMyBucketsResult": {
            "Buckets": {"Bucket": [b.metadata for b in buckets]},
        }})
        return server.NOT_DONE_YET


class BucketResource(ErrorHandlingResource):
    """A web resource containing an S3-like bucket"""
    def __init__(self, name):
        resource.Resource.__init__(self)
        self.name = name

    def getChild(self, name, request):
        """Returns the bucket resource itself, or the object resource
        the bucket contains if a name is supplied
        """
        if name == '':
            return self
        else:
            return ObjectResource(bucket.Bucket(self.name), name)

    def render_GET(self, request):
        "Returns the keys for the bucket resource"""
        LOG.debug(_("List keys for bucket %s"), self.name)

        try:
            bucket_object = bucket.Bucket(self.name)
        except exception.NotFound:
            return error.NoResource(message="No such bucket").render(request)

        if not bucket_object.is_authorized(request.context):
            LOG.audit(_("Unauthorized attempt to access bucket %s"),
                      self.name, context=request.context)
            raise exception.NotAuthorized()

        prefix = get_argument(request, "prefix", u"")
        marker = get_argument(request, "marker", u"")
        max_keys = int(get_argument(request, "max-keys", 1000))
        terse = int(get_argument(request, "terse", 0))

        results = bucket_object.list_keys(prefix=prefix,
                                          marker=marker,
                                          max_keys=max_keys,
                                          terse=terse)
        render_xml(request, {"ListBucketResult": results})
        return server.NOT_DONE_YET

    def render_PUT(self, request):
        "Creates the bucket resource"""
        LOG.debug(_("Creating bucket %s"), self.name)
        LOG.debug("calling bucket.Bucket.create(%r, %r)",
                      self.name,
                      request.context)
        bucket.Bucket.create(self.name, request.context)
        request.finish()
        return server.NOT_DONE_YET

    def render_DELETE(self, request):
        """Deletes the bucket resource"""
        LOG.debug(_("Deleting bucket %s"), self.name)
        bucket_object = bucket.Bucket(self.name)

        if not bucket_object.is_authorized(request.context):
            LOG.audit(_("Unauthorized attempt to delete bucket %s"),
                      self.name, context=request.context)
            raise exception.NotAuthorized()

        bucket_object.delete()
        request.setResponseCode(204)
        return ''


class ObjectResource(ErrorHandlingResource):
    """The resource returned from a bucket"""
    def __init__(self, bucket, name):
        resource.Resource.__init__(self)
        self.bucket = bucket
        self.name = name

    def render_GET(self, request):
        """Returns the object

        Raises NotAuthorized if user in request context is not
        authorized to delete the object.
        """
        bname = self.bucket.name
        nm = self.name
        LOG.debug(_("Getting object: %(bname)s / %(nm)s") % locals())

        if not self.bucket.is_authorized(request.context):
            LOG.audit(_("Unauthorized attempt to get object %(nm)s"
                    " from bucket %(bname)s") % locals(),
                    context=request.context)
            raise exception.NotAuthorized()

        obj = self.bucket[urllib.unquote(self.name)]
        request.setHeader("Content-Type", "application/unknown")
        request.setHeader("Last-Modified",
                          datetime.datetime.utcfromtimestamp(obj.mtime))
        request.setHeader("Etag", '"' + obj.md5 + '"')
        return static.File(obj.path).render_GET(request)

    def render_PUT(self, request):
        """Modifies/inserts the object and returns a result code

        Raises NotAuthorized if user in request context is not
        authorized to delete the object.
        """
        nm = self.name
        bname = self.bucket.name
        LOG.debug(_("Putting object: %(bname)s / %(nm)s") % locals())

        if not self.bucket.is_authorized(request.context):
            LOG.audit(_("Unauthorized attempt to upload object %(nm)s to"
                    " bucket %(bname)s") % locals(), context=request.context)
            raise exception.NotAuthorized()

        key = urllib.unquote(self.name)
        request.content.seek(0, 0)
        self.bucket[key] = request.content.read()
        request.setHeader("Etag", '"' + self.bucket[key].md5 + '"')
        finish(request)
        return server.NOT_DONE_YET

    def render_DELETE(self, request):
        """Deletes the object and returns a result code

        Raises NotAuthorized if user in request context is not
        authorized to delete the object.
        """
        nm = self.name
        bname = self.bucket.name
        LOG.debug(_("Deleting object: %(bname)s / %(nm)s") % locals(),
                  context=request.context)

        if not self.bucket.is_authorized(request.context):
            LOG.audit(_("Unauthorized attempt to delete object %(nm)s from "
                      "bucket %(bname)s") % locals(), context=request.context)
            raise exception.NotAuthorized()

        del self.bucket[urllib.unquote(self.name)]
        request.setResponseCode(204)
        return ''


class ImageResource(ErrorHandlingResource):
    """A web resource representing a single image"""
    isLeaf = True

    def __init__(self, name):
        resource.Resource.__init__(self)
        self.img = image.Image(name)

    def render_GET(self, request):
        """Returns the image file"""
        if not self.img.is_authorized(request.context, True):
            raise exception.NotAuthorized()
        return static.File(self.img.image_path,
                           defaultType='application/octet-stream').\
                           render_GET(request)


class ImagesResource(resource.Resource):
    """A web resource representing a list of images"""

    def getChild(self, name, _request):
        """Returns itself or an ImageResource if no name given"""
        if name == '':
            return self
        else:
            return ImageResource(name)

    def render_GET(self, request):  # pylint: disable=R0201
        """ returns a json listing of all images
            that a user has permissions to see """

        images = [i for i in image.Image.all() \
                  if i.is_authorized(request.context, readonly=True)]

        # Bug #617776:
        # We used to have 'type' in the image metadata, but this field
        # should be called 'imageType', as per the EC2 specification.
        # For compat with old metadata files we copy type to imageType if
        # imageType is not present.
        # For compat with euca2ools (and any other clients using the
        # incorrect name) we copy imageType to type.
        # imageType is primary if we end up with both in the metadata file
        # (which should never happen).
        def decorate(m):
            if 'imageType' not in m and 'type' in m:
                m[u'imageType'] = m['type']
            elif 'imageType' in m:
                m[u'type'] = m['imageType']
            if 'displayName' not in m:
                m[u'displayName'] = u''
            return m

        request.write(json.dumps([decorate(i.metadata) for i in images]))
        request.finish()
        return server.NOT_DONE_YET

    def render_PUT(self, request):  # pylint: disable=R0201
        """ create a new registered image """

        image_id = get_argument(request, 'image_id', u'')
        image_location = get_argument(request, 'image_location', u'')

        image_path = os.path.join(FLAGS.images_path, image_id)
        if ((not image_path.startswith(FLAGS.images_path)) or
                os.path.exists(image_path)):
            LOG.audit(_("Not authorized to upload image: invalid directory "
                      "%s"),
                      image_path, context=request.context)
            raise exception.NotAuthorized()

        bucket_object = bucket.Bucket(image_location.split("/")[0])

        if not bucket_object.is_authorized(request.context):
            LOG.audit(_("Not authorized to upload image: unauthorized "
                      "bucket %s"), bucket_object.name,
                      context=request.context)
            raise exception.NotAuthorized()

        LOG.audit(_("Starting image upload: %s"), image_id,
                  context=request.context)
        p = multiprocessing.Process(target=image.Image.register_aws_image,
                args=(image_id, image_location, request.context))
        p.start()
        return ''

    def render_POST(self, request):  # pylint: disable=R0201
        """Update image attributes: public/private"""

        # image_id required for all requests
        image_id = get_argument(request, 'image_id', u'')
        image_object = image.Image(image_id)
        if not image_object.is_authorized(request.context):
            LOG.audit(_("Not authorized to update attributes of image %s"),
                      image_id, context=request.context)
            raise exception.NotAuthorized()

        operation = get_argument(request, 'operation', u'')
        if operation:
            # operation implies publicity toggle
            newstatus = (operation == 'add')
            LOG.audit(_("Toggling publicity flag of image %(image_id)s"
                    " %(newstatus)r") % locals(), context=request.context)
            image_object.set_public(newstatus)
        else:
            # other attributes imply update
            LOG.audit(_("Updating user fields on image %s"), image_id,
                     context=request.context)
            clean_args = {}
            for arg in request.args.keys():
                clean_args[arg] = request.args[arg][0]
            image_object.update_user_editable_fields(clean_args)
        return ''

    def render_DELETE(self, request):  # pylint: disable=R0201
        """Delete a registered image"""
        image_id = get_argument(request, "image_id", u"")
        image_object = image.Image(image_id)

        if not image_object.is_authorized(request.context):
            LOG.audit(_("Unauthorized attempt to delete image %s"),
                      image_id, context=request.context)
            raise exception.NotAuthorized()

        image_object.delete()
        LOG.audit(_("Deleted image: %s"), image_id, context=request.context)

        request.setResponseCode(204)
        return ''


def get_site():
    """Support for WSGI-like interfaces"""
    root = S3()
    site = server.Site(root)
    return site


def get_application():
    """Support WSGI-like interfaces"""
    factory = get_site()
    application = service.Application("objectstore")
    # Disabled because of lack of proper introspection in Twisted
    # or possibly different versions of twisted?
    # pylint: disable=E1101
    objectStoreService = internet.TCPServer(FLAGS.s3_port, factory,
                                            interface=FLAGS.s3_listen_host)
    objectStoreService.setServiceParent(application)
    return application
