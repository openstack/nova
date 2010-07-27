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

import boto
import glob
import hashlib
import logging
import os
import shutil
import tempfile

from nova import flags
from nova import objectstore
from nova import test
from nova.auth import users
from nova.objectstore.handler import S3
from nova.exception import NotEmpty, NotFound, NotAuthorized

from boto.s3.connection import S3Connection, OrdinaryCallingFormat
from twisted.internet import reactor, threads, defer
from twisted.web import http, server

FLAGS = flags.FLAGS

oss_tempdir = tempfile.mkdtemp(prefix='test_oss-')


# delete tempdirs from previous runs (we don't delete after test to allow
# checking the contents after running tests)
# TODO: This fails on the test box with a permission denied error
# Also, doing these things in a global tempdir means that different runs of
# the test suite on the same box could clobber each other.
#for path in glob.glob(os.path.abspath(os.path.join(oss_tempdir, '../test_oss-*'))):
#    if path != oss_tempdir:
#        shutil.rmtree(path)


# create bucket/images path
os.makedirs(os.path.join(oss_tempdir, 'images'))
os.makedirs(os.path.join(oss_tempdir, 'buckets'))

class ObjectStoreTestCase(test.BaseTestCase):
    def setUp(self):
        super(ObjectStoreTestCase, self).setUp()
        self.flags(fake_users=True,
                   buckets_path=os.path.join(oss_tempdir, 'buckets'),
                   images_path=os.path.join(oss_tempdir, 'images'),
                   ca_path=os.path.join(os.path.dirname(__file__), 'CA'))
        logging.getLogger().setLevel(logging.DEBUG)

        self.um = users.UserManager.instance()
        try:
            self.um.create_user('user1')
        except: pass
        try:
            self.um.create_user('user2')
        except: pass
        try:
            self.um.create_user('admin_user', admin=True)
        except: pass
        try:
            self.um.create_project('proj1', 'user1', 'a proj', ['user1'])
        except: pass
        try:
            self.um.create_project('proj2', 'user2', 'a proj', ['user2'])
        except: pass
        class Context(object): pass
        self.context = Context()

    def tearDown(self):
        self.um.delete_project('proj1')
        self.um.delete_project('proj2')
        self.um.delete_user('user1')
        self.um.delete_user('user2')
        self.um.delete_user('admin_user')
        super(ObjectStoreTestCase, self).tearDown()

    def test_buckets(self):
        self.context.user = self.um.get_user('user1')
        self.context.project = self.um.get_project('proj1')
        objectstore.bucket.Bucket.create('new_bucket', self.context)
        bucket = objectstore.bucket.Bucket('new_bucket')

        # creator is authorized to use bucket
        self.assert_(bucket.is_authorized(self.context))

        # another user is not authorized
        self.context.user = self.um.get_user('user2')
        self.context.project = self.um.get_project('proj2')
        self.assertFalse(bucket.is_authorized(self.context))

        # admin is authorized to use bucket
        self.context.user = self.um.get_user('admin_user')
        self.context.project = None
        self.assertTrue(bucket.is_authorized(self.context))

        # new buckets are empty
        self.assertTrue(bucket.list_keys()['Contents'] == [])

        # storing keys works
        bucket['foo'] = "bar"

        self.assertEquals(len(bucket.list_keys()['Contents']), 1)

        self.assertEquals(bucket['foo'].read(), 'bar')

        # md5 of key works
        self.assertEquals(bucket['foo'].md5, hashlib.md5('bar').hexdigest())

        # deleting non-empty bucket should throw a NotEmpty exception
        self.assertRaises(NotEmpty, bucket.delete)

        # deleting key
        del bucket['foo']

        # deleting empty bucket
        bucket.delete()

        # accessing deleted bucket throws exception
        self.assertRaises(NotFound, objectstore.bucket.Bucket, 'new_bucket')

    def test_images(self):
        self.context.user = self.um.get_user('user1')
        self.context.project = self.um.get_project('proj1')

        # create a bucket for our bundle
        objectstore.bucket.Bucket.create('image_bucket', self.context)
        bucket = objectstore.bucket.Bucket('image_bucket')

        # upload an image manifest/parts
        bundle_path = os.path.join(os.path.dirname(__file__), 'bundle')
        for path in glob.glob(bundle_path + '/*'):
            bucket[os.path.basename(path)] = open(path, 'rb').read()

        # register an image
        objectstore.image.Image.register_aws_image('i-testing', 'image_bucket/1mb.manifest.xml', self.context)

        # verify image
        my_img = objectstore.image.Image('i-testing')
        result_image_file = os.path.join(my_img.path, 'image')
        self.assertEqual(os.stat(result_image_file).st_size, 1048576)

        sha = hashlib.sha1(open(result_image_file).read()).hexdigest()
        self.assertEqual(sha, '3b71f43ff30f4b15b5cd85dd9e95ebc7e84eb5a3')

        # verify image permissions
        self.context.user = self.um.get_user('user2')
        self.context.project = self.um.get_project('proj2')
        self.assertFalse(my_img.is_authorized(self.context))


class TestHTTPChannel(http.HTTPChannel):
    # Otherwise we end up with an unclean reactor
    def checkPersistence(self, _, __):
        return False


class TestSite(server.Site):
    protocol = TestHTTPChannel


class S3APITestCase(test.TrialTestCase):
    def setUp(self):
        super(S3APITestCase, self).setUp()
        FLAGS.fake_users   = True
        FLAGS.buckets_path = os.path.join(oss_tempdir, 'buckets')

        shutil.rmtree(FLAGS.buckets_path)
        os.mkdir(FLAGS.buckets_path)

        root = S3()
        self.site = TestSite(root)
        self.listening_port = reactor.listenTCP(0, self.site, interface='127.0.0.1')
        self.tcp_port = self.listening_port.getHost().port


        if not boto.config.has_section('Boto'):
            boto.config.add_section('Boto')
        boto.config.set('Boto', 'num_retries', '0')
        self.conn = S3Connection(aws_access_key_id='admin',
                                 aws_secret_access_key='admin',
                                 host='127.0.0.1',
                                 port=self.tcp_port,
                                 is_secure=False,
                                 calling_format=OrdinaryCallingFormat())

        # Don't attempt to reuse connections
        def get_http_connection(host, is_secure):
            return self.conn.new_http_connection(host, is_secure)
        self.conn.get_http_connection = get_http_connection

    def _ensure_empty_list(self, l):
        self.assertEquals(len(l), 0, "List was not empty")
        return True

    def _ensure_only_bucket(self, l, name):
        self.assertEquals(len(l), 1, "List didn't have exactly one element in it")
        self.assertEquals(l[0].name, name, "Wrong name")

    def test_000_list_buckets(self):
        d = threads.deferToThread(self.conn.get_all_buckets)
        d.addCallback(self._ensure_empty_list)
        return d

    def test_001_create_and_delete_bucket(self):
        bucket_name = 'testbucket'

        d = threads.deferToThread(self.conn.create_bucket, bucket_name)
        d.addCallback(lambda _:threads.deferToThread(self.conn.get_all_buckets))

        def ensure_only_bucket(l, name):
            self.assertEquals(len(l), 1, "List didn't have exactly one element in it")
            self.assertEquals(l[0].name, name, "Wrong name")
        d.addCallback(ensure_only_bucket, bucket_name)

        d.addCallback(lambda _:threads.deferToThread(self.conn.delete_bucket, bucket_name))
        d.addCallback(lambda _:threads.deferToThread(self.conn.get_all_buckets))
        d.addCallback(self._ensure_empty_list)
        return d

    def test_002_create_bucket_and_key_and_delete_key_again(self):
        bucket_name = 'testbucket'
        key_name = 'somekey'
        key_contents = 'somekey'

        d = threads.deferToThread(self.conn.create_bucket, bucket_name)
        d.addCallback(lambda b:threads.deferToThread(b.new_key, key_name))
        d.addCallback(lambda k:threads.deferToThread(k.set_contents_from_string, key_contents))
        def ensure_key_contents(bucket_name, key_name, contents):
            bucket = self.conn.get_bucket(bucket_name)
            key = bucket.get_key(key_name)
            self.assertEquals(key.get_contents_as_string(), contents,  "Bad contents")
        d.addCallback(lambda _:threads.deferToThread(ensure_key_contents, bucket_name, key_name, key_contents))
        def delete_key(bucket_name, key_name):
            bucket = self.conn.get_bucket(bucket_name)
            key = bucket.get_key(key_name)
            key.delete()
        d.addCallback(lambda _:threads.deferToThread(delete_key, bucket_name, key_name))
        d.addCallback(lambda _:threads.deferToThread(self.conn.get_bucket, bucket_name))
        d.addCallback(lambda b:threads.deferToThread(b.get_all_keys))
        d.addCallback(self._ensure_empty_list)
        return d

    def tearDown(self):
        super(S3APITestCase, self).tearDown()
        return defer.DeferredList([defer.maybeDeferred(self.listening_port.stopListening)])
