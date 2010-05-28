# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import glob
import hashlib
import logging
import os
import shutil
import tempfile

from nova import vendor

from nova import flags
from nova import rpc
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
        self.conn = rpc.Connection.instance()
        logging.getLogger().setLevel(logging.DEBUG)

        self.um = users.UserManager.instance()

    def test_buckets(self):
        try:
            self.um.create_user('user1')
        except: pass
        try:
            self.um.create_user('user2')
        except: pass
        try:
            self.um.create_user('admin_user', admin=True)
        except: pass

        objectstore.bucket.Bucket.create('new_bucket', self.um.get_user('user1'))
        bucket = objectstore.bucket.Bucket('new_bucket')

        # creator is authorized to use bucket
        self.assert_(bucket.is_authorized(self.um.get_user('user1')))

        # another user is not authorized
        self.assert_(bucket.is_authorized(self.um.get_user('user2')) == False)

        # admin is authorized to use bucket
        self.assert_(bucket.is_authorized(self.um.get_user('admin_user')))

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
        self.um.delete_user('user1')
        self.um.delete_user('user2')
        self.um.delete_user('admin_user')

    def test_images(self):
        try:
            self.um.create_user('image_creator')
        except: pass
        image_user = self.um.get_user('image_creator')

        # create a bucket for our bundle
        objectstore.bucket.Bucket.create('image_bucket', image_user)
        bucket = objectstore.bucket.Bucket('image_bucket')

        # upload an image manifest/parts
        bundle_path = os.path.join(os.path.dirname(__file__), 'bundle')
        for path in glob.glob(bundle_path + '/*'):
            bucket[os.path.basename(path)] = open(path, 'rb').read()

        # register an image
        objectstore.image.Image.create('i-testing', 'image_bucket/1mb.manifest.xml', image_user)

        # verify image
        my_img = objectstore.image.Image('i-testing')
        result_image_file = os.path.join(my_img.path, 'image')
        self.assertEqual(os.stat(result_image_file).st_size, 1048576)

        sha = hashlib.sha1(open(result_image_file).read()).hexdigest()
        self.assertEqual(sha, '3b71f43ff30f4b15b5cd85dd9e95ebc7e84eb5a3')

        # verify image permissions
        try:
            self.um.create_user('new_user')
        except: pass
        new_user = self.um.get_user('new_user')
        self.assert_(my_img.is_authorized(new_user) == False)

        self.um.delete_user('new_user')
        self.um.delete_user('image_creator')

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
