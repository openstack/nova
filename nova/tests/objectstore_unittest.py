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
import os
import shutil
import tempfile

from boto.s3.connection import S3Connection, OrdinaryCallingFormat
from twisted.internet import reactor, threads, defer
from twisted.web import http, server

from nova import context
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


class ObjectStoreTestCase(test.TestCase):
    """Test objectstore API directly."""

    def setUp(self):
        """Setup users and projects."""
        super(ObjectStoreTestCase, self).setUp()
        self.flags(buckets_path=os.path.join(OSS_TEMPDIR, 'buckets'),
                   images_path=os.path.join(OSS_TEMPDIR, 'images'),
                   ca_path=os.path.join(os.path.dirname(__file__), 'CA'))

        self.auth_manager = manager.AuthManager()
        self.auth_manager.create_user('user1')
        self.auth_manager.create_user('user2')
        self.auth_manager.create_user('admin_user', admin=True)
        self.auth_manager.create_project('proj1', 'user1', 'a proj', ['user1'])
        self.auth_manager.create_project('proj2', 'user2', 'a proj', ['user2'])
        self.context = context.RequestContext('user1', 'proj1')

    def tearDown(self):
        """Tear down users and projects."""
        self.auth_manager.delete_project('proj1')
        self.auth_manager.delete_project('proj2')
        self.auth_manager.delete_user('user1')
        self.auth_manager.delete_user('user2')
        self.auth_manager.delete_user('admin_user')
        super(ObjectStoreTestCase, self).tearDown()

    def test_buckets(self):
        """Test the bucket API."""
        objectstore.bucket.Bucket.create('new_bucket', self.context)
        bucket = objectstore.bucket.Bucket('new_bucket')

        # creator is authorized to use bucket
        self.assert_(bucket.is_authorized(self.context))

        # another user is not authorized
        context2 = context.RequestContext('user2', 'proj2')
        self.assertFalse(bucket.is_authorized(context2))

        # admin is authorized to use bucket
        admin_context = context.RequestContext('admin_user', None)
        self.assertTrue(bucket.is_authorized(admin_context))

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
        self.do_test_images('1mb.manifest.xml', True,
                            'image_bucket1', 'i-testing1')

    def test_images_no_kernel_or_ramdisk(self):
        self.do_test_images('1mb.no_kernel_or_ramdisk.manifest.xml',
                            False, 'image_bucket2', 'i-testing2')

    def do_test_images(self, manifest_file, expect_kernel_and_ramdisk,
                             image_bucket, image_name):
        "Test the image API."

        # create a bucket for our bundle
        objectstore.bucket.Bucket.create(image_bucket, self.context)
        bucket = objectstore.bucket.Bucket(image_bucket)

        # upload an image manifest/parts
        bundle_path = os.path.join(os.path.dirname(__file__), 'bundle')
        for path in glob.glob(bundle_path + '/*'):
            bucket[os.path.basename(path)] = open(path, 'rb').read()

        # register an image
        image.Image.register_aws_image(image_name,
                                       '%s/%s' % (image_bucket, manifest_file),
                                       self.context)

        # verify image
        my_img = image.Image(image_name)
        result_image_file = os.path.join(my_img.path, 'image')
        self.assertEqual(os.stat(result_image_file).st_size, 1048576)

        sha = hashlib.sha1(open(result_image_file).read()).hexdigest()
        self.assertEqual(sha, '3b71f43ff30f4b15b5cd85dd9e95ebc7e84eb5a3')

        if expect_kernel_and_ramdisk:
            # Verify the default kernel and ramdisk are set
            self.assertEqual(my_img.metadata['kernelId'], 'aki-test')
            self.assertEqual(my_img.metadata['ramdiskId'], 'ari-test')
        else:
            # Verify that the default kernel and ramdisk (the one from FLAGS)
            # doesn't get embedded in the metadata
            self.assertFalse('kernelId' in my_img.metadata)
            self.assertFalse('ramdiskId' in my_img.metadata)

        # verify image permissions
        context2 = context.RequestContext('user2', 'proj2')
        self.assertFalse(my_img.is_authorized(context2))

        # change user-editable fields
        my_img.update_user_editable_fields({'display_name': 'my cool image'})
        self.assertEqual('my cool image', my_img.metadata['displayName'])
        my_img.update_user_editable_fields({'display_name': ''})
        self.assert_(not my_img.metadata['displayName'])


class TestHTTPChannel(http.HTTPChannel):
    """Dummy site required for twisted.web"""

    def checkPersistence(self, _, __):  # pylint: disable=C0103
        """Otherwise we end up with an unclean reactor."""
        return False


class TestSite(server.Site):
    """Dummy site required for twisted.web"""
    protocol = TestHTTPChannel


class S3APITestCase(test.TestCase):
    """Test objectstore through S3 API."""

    def setUp(self):
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
        # pylint: disable=E1101
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

    def _ensure_no_buckets(self, buckets):  # pylint: disable=C0111
        self.assertEquals(len(buckets), 0, "Bucket list was not empty")
        return True

    def _ensure_one_bucket(self, buckets, name):  # pylint: disable=C0111
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

    def tearDown(self):
        """Tear down auth and test server."""
        self.auth_manager.delete_user('admin')
        self.auth_manager.delete_project('admin')
        stop_listening = defer.maybeDeferred(self.listening_port.stopListening)
        super(S3APITestCase, self).tearDown()
        return defer.DeferredList([stop_listening])
