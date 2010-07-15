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

import glob
import hashlib
import logging
import os
import shutil
import tempfile

from nova import vendor

from nova import flags
from nova import objectstore
from nova import test
from nova.auth import users

FLAGS = flags.FLAGS


oss_tempdir = tempfile.mkdtemp(prefix='test_oss-')


# delete tempdirs from previous runs (we don't delete after test to allow
# checking the contents after running tests)
for path in glob.glob(os.path.abspath(os.path.join(oss_tempdir, '../test_oss-*'))):
    if path != oss_tempdir:
        shutil.rmtree(path)


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
        self.assert_(bucket.is_authorized(self.context) == False)

        # admin is authorized to use bucket
        self.context.user = self.um.get_user('admin_user')
        self.context.project = None
        self.assert_(bucket.is_authorized(self.context))

        # new buckets are empty
        self.assert_(bucket.list_keys()['Contents'] == [])

        # storing keys works
        bucket['foo'] = "bar"

        self.assert_(len(bucket.list_keys()['Contents']) == 1)

        self.assert_(bucket['foo'].read() == 'bar')

        # md5 of key works
        self.assert_(bucket['foo'].md5 == hashlib.md5('bar').hexdigest())

        # deleting non-empty bucket throws exception
        exception = False
        try:
            bucket.delete()
        except:
            exception = True

        self.assert_(exception)

        # deleting key
        del bucket['foo']

        # deleting empty button
        bucket.delete()

        # accessing deleted bucket throws exception
        exception = False
        try:
            objectstore.bucket.Bucket('new_bucket')
        except:
            exception = True

        self.assert_(exception)

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
        self.assert_(my_img.is_authorized(self.context) == False)

# class ApiObjectStoreTestCase(test.BaseTestCase):
#     def setUp(self):
#         super(ApiObjectStoreTestCase, self).setUp()
#         FLAGS.fake_users   = True
#         FLAGS.buckets_path = os.path.join(tempdir, 'buckets')
#         FLAGS.images_path  = os.path.join(tempdir, 'images')
#         FLAGS.ca_path = os.path.join(os.path.dirname(__file__), 'CA')
#
#         self.users = users.UserManager.instance()
#         self.app  = handler.Application(self.users)
#
#         self.host = '127.0.0.1'
#
#         self.conn = boto.s3.connection.S3Connection(
#             aws_access_key_id=user.access,
#             aws_secret_access_key=user.secret,
#             is_secure=False,
#             calling_format=boto.s3.connection.OrdinaryCallingFormat(),
#             port=FLAGS.s3_port,
#             host=FLAGS.s3_host)
#
#         self.mox.StubOutWithMock(self.ec2, 'new_http_connection')
#
#     def tearDown(self):
#         FLAGS.Reset()
#         super(ApiObjectStoreTestCase, self).tearDown()
#
#     def test_describe_instances(self):
#         self.expect_http()
#         self.mox.ReplayAll()
#
#         self.assertEqual(self.ec2.get_all_instances(), [])
