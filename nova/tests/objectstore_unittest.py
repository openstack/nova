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
Unittets for S3 objectstore clone.
"""

import boto
import glob
import hashlib
import logging
import os
import shutil
import tempfile

from boto.s3.connection import S3Connection, OrdinaryCallingFormat
from twisted.internet import reactor, threads, defer
from twisted.web import http, server

from nova import flags
from nova import objectstore
from nova import test
from nova.auth import manager
from nova.exception import NotEmpty, NotFound
from nova.objectstore import image
from nova.objectstore.handler import S3


FLAGS = flags.FLAGS

# Create a unique temporary directory. We don't delete after test to
# allow checking the contents after running tests. Users and/or tools
# running the tests need to remove the tests directories.
OSS_TEMPDIR = tempfile.mkdtemp(prefix='test_oss-')

# Create bucket/images path
os.makedirs(os.path.join(OSS_TEMPDIR, 'images'))
os.makedirs(os.path.join(OSS_TEMPDIR, 'buckets'))


class ObjectStoreTestCase(test.BaseTestCase):
    """Test objectstore API directly."""

    def setUp(self): # pylint: disable-msg=C0103
        """Setup users and projects."""
        super(ObjectStoreTestCase, self).setUp()
        self.flags(buckets_path=os.path.join(OSS_TEMPDIR, 'buckets'),
                   images_path=os.path.join(OSS_TEMPDIR, 'images'),
                   ca_path=os.path.join(os.path.dirname(__file__), 'CA'))
        logging.getLogger().setLevel(logging.DEBUG)

        self.auth_manager = manager.AuthManager()
        self.auth_manager.create_user('user1')
        self.auth_manager.create_user('user2')
        self.auth_manager.create_user('admin_user', admin=True)
        self.auth_manager.create_project('proj1', 'user1', 'a proj', ['user1'])
        self.auth_manager.create_project('proj2', 'user2', 'a proj', ['user2'])

        class Context(object):
            """Dummy context for running tests."""
            user = None
            project = None

        self.context = Context()

    def tearDown(self): # pylint: disable-msg=C0103
        """Tear down users and projects."""
        self.auth_manager.delete_project('proj1')
        self.auth_manager.delete_project('proj2')
        self.auth_manager.delete_user('user1')
        self.auth_manager.delete_user('user2')
        self.auth_manager.delete_user('admin_user')
        super(ObjectStoreTestCase, self).tearDown()

    def test_buckets(self):
        """Test the bucket API."""
        self.context.user = self.auth_manager.get_user('user1')
        self.context.project = self.auth_manager.get_project('proj1')
        objectstore.bucket.Bucket.create('new_bucket', self.context)
        bucket = objectstore.bucket.Bucket('new_bucket')

        # creator is authorized to use bucket
        self.assert_(bucket.is_authorized(self.context))

        # another user is not authorized
        self.context.user = self.auth_manager.get_user('user2')
        self.context.project = self.auth_manager.get_project('proj2')
        self.assertFalse(bucket.is_authorized(self.context))

        # admin is authorized to use bucket
        self.context.user = self.auth_manager.get_user('admin_user')
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
        "Test the image API."
        self.context.user = self.auth_manager.get_user('user1')
        self.context.project = self.auth_manager.get_project('proj1')

        # create a bucket for our bundle
        objectstore.bucket.Bucket.create('image_bucket', self.context)
        bucket = objectstore.bucket.Bucket('image_bucket')

        # upload an image manifest/parts
        bundle_path = os.path.join(os.path.dirname(__file__), 'bundle')
        for path in glob.glob(bundle_path + '/*'):
            bucket[os.path.basename(path)] = open(path, 'rb').read()

        # register an image
        image.Image.register_aws_image('i-testing',
                                       'image_bucket/1mb.manifest.xml',
                                       self.context)

        # verify image
        my_img = image.Image('i-testing')
        result_image_file = os.path.join(my_img.path, 'image')
        self.assertEqual(os.stat(result_image_file).st_size, 1048576)

        sha = hashlib.sha1(open(result_image_file).read()).hexdigest()
        self.assertEqual(sha, '3b71f43ff30f4b15b5cd85dd9e95ebc7e84eb5a3')

        # verify image permissions
        self.context.user = self.auth_manager.get_user('user2')
        self.context.project = self.auth_manager.get_project('proj2')
        self.assertFalse(my_img.is_authorized(self.context))


class TestHTTPChannel(http.HTTPChannel):
    """Dummy site required for twisted.web"""

    def checkPersistence(self, _, __): # pylint: disable-msg=C0103
        """Otherwise we end up with an unclean reactor."""
        return False


class TestSite(server.Site):
    """Dummy site required for twisted.web"""
    protocol = TestHTTPChannel


class S3APITestCase(test.TrialTestCase):
    """Test objectstore through S3 API."""

    def setUp(self): # pylint: disable-msg=C0103
        """Setup users, projects, and start a test server."""
        super(S3APITestCase, self).setUp()

        FLAGS.auth_driver = 'nova.auth.ldapdriver.FakeLdapDriver'
        FLAGS.buckets_path = os.path.join(OSS_TEMPDIR, 'buckets')

        self.auth_manager = manager.AuthManager()
        self.admin_user = self.auth_manager.create_user('admin', admin=True)
        self.admin_project = self.auth_manager.create_project('admin',
                                                              self.admin_user)

        shutil.rmtree(FLAGS.buckets_path)
        os.mkdir(FLAGS.buckets_path)

        root = S3()
        self.site = TestSite(root)
        # pylint: disable-msg=E1101
        self.listening_port = reactor.listenTCP(0, self.site,
                                                interface='127.0.0.1')
        # pylint: enable-msg=E1101
        self.tcp_port = self.listening_port.getHost().port


        if not boto.config.has_section('Boto'):
            boto.config.add_section('Boto')
        boto.config.set('Boto', 'num_retries', '0')
        self.conn = S3Connection(aws_access_key_id=self.admin_user.access,
                                 aws_secret_access_key=self.admin_user.secret,
                                 host='127.0.0.1',
                                 port=self.tcp_port,
                                 is_secure=False,
                                 calling_format=OrdinaryCallingFormat())

        def get_http_connection(host, is_secure):
            """Get a new S3 connection, don't attempt to reuse connections."""
            return self.conn.new_http_connection(host, is_secure)

        self.conn.get_http_connection = get_http_connection

    def _ensure_no_buckets(self, buckets): # pylint: disable-msg=C0111
        self.assertEquals(len(buckets), 0, "Bucket list was not empty")
        return True

    def _ensure_one_bucket(self, buckets, name): # pylint: disable-msg=C0111
        self.assertEquals(len(buckets), 1,
                          "Bucket list didn't have exactly one element in it")
        self.assertEquals(buckets[0].name, name, "Wrong name")
        return True

    def test_000_list_buckets(self):
        """Make sure we are starting with no buckets."""
        deferred = threads.deferToThread(self.conn.get_all_buckets)
        deferred.addCallback(self._ensure_no_buckets)
        return deferred

    def test_001_create_and_delete_bucket(self):
        """Test bucket creation and deletion."""
        bucket_name = 'testbucket'

        deferred = threads.deferToThread(self.conn.create_bucket, bucket_name)
        deferred.addCallback(lambda _:
                             threads.deferToThread(self.conn.get_all_buckets))

        deferred.addCallback(self._ensure_one_bucket, bucket_name)

        deferred.addCallback(lambda _:
                             threads.deferToThread(self.conn.delete_bucket,
                                                   bucket_name))
        deferred.addCallback(lambda _:
                             threads.deferToThread(self.conn.get_all_buckets))
        deferred.addCallback(self._ensure_no_buckets)
        return deferred

    def test_002_create_bucket_and_key_and_delete_key_again(self):
        """Test key operations on buckets."""
        bucket_name = 'testbucket'
        key_name = 'somekey'
        key_contents = 'somekey'

        deferred = threads.deferToThread(self.conn.create_bucket, bucket_name)
        deferred.addCallback(lambda b:
                             threads.deferToThread(b.new_key, key_name))
        deferred.addCallback(lambda k:
                             threads.deferToThread(k.set_contents_from_string,
                                                   key_contents))

        def ensure_key_contents(bucket_name, key_name, contents):
            """Verify contents for a key in the given bucket."""
            bucket = self.conn.get_bucket(bucket_name)
            key = bucket.get_key(key_name)
            self.assertEquals(key.get_contents_as_string(), contents,
                              "Bad contents")

        deferred.addCallback(lambda _:
                             threads.deferToThread(ensure_key_contents,
                                                   bucket_name, key_name,
                                                   key_contents))

        def delete_key(bucket_name, key_name):
            """Delete a key for the given bucket."""
            bucket = self.conn.get_bucket(bucket_name)
            key = bucket.get_key(key_name)
            key.delete()

        deferred.addCallback(lambda _:
                             threads.deferToThread(delete_key, bucket_name,
                                                   key_name))
        deferred.addCallback(lambda _:
                             threads.deferToThread(self.conn.get_bucket,
                                                   bucket_name))
        deferred.addCallback(lambda b: threads.deferToThread(b.get_all_keys))
        deferred.addCallback(self._ensure_no_buckets)
        return deferred

    def tearDown(self): # pylint: disable-msg=C0103
        """Tear down auth and test server."""
        self.auth_manager.delete_user('admin')
        self.auth_manager.delete_project('admin')
        stop_listening = defer.maybeDeferred(self.listening_port.stopListening)
        return defer.DeferredList([stop_listening])
