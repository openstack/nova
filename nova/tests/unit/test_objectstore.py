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

import os
import shutil
import tempfile

import boto
from boto import exception as boto_exception
from boto.s3 import connection as s3
from oslo_config import cfg

from nova.objectstore import s3server
from nova import test
from nova import wsgi

CONF = cfg.CONF
CONF.import_opt('s3_host', 'nova.image.s3')

# Create a unique temporary directory. We don't delete after test to
# allow checking the contents after running tests. Users and/or tools
# running the tests need to remove the tests directories.
OSS_TEMPDIR = tempfile.mkdtemp(prefix='test_oss-')

# Create bucket/images path
os.makedirs(os.path.join(OSS_TEMPDIR, 'images'))
os.makedirs(os.path.join(OSS_TEMPDIR, 'buckets'))


class S3APITestCase(test.NoDBTestCase):
    """Test objectstore through S3 API."""

    def setUp(self):
        """Setup users, projects, and start a test server."""
        super(S3APITestCase, self).setUp()
        self.flags(buckets_path=os.path.join(OSS_TEMPDIR, 'buckets'),
                   s3_host='127.0.0.1')

        shutil.rmtree(CONF.buckets_path)
        os.mkdir(CONF.buckets_path)

        router = s3server.S3Application(CONF.buckets_path)
        self.server = wsgi.Server("S3 Objectstore",
                                  router,
                                  host=CONF.s3_host,
                                  port=0)
        self.server.start()

        if not boto.config.has_section('Boto'):
            boto.config.add_section('Boto')

        boto.config.set('Boto', 'num_retries', '0')
        conn = s3.S3Connection(aws_access_key_id='fake',
                               aws_secret_access_key='fake',
                               host=CONF.s3_host,
                               port=self.server.port,
                               is_secure=False,
                               calling_format=s3.OrdinaryCallingFormat())
        self.conn = conn

        def get_http_connection(*args):
            """Get a new S3 connection, don't attempt to reuse connections."""
            return self.conn.new_http_connection(*args)

        self.conn.get_http_connection = get_http_connection

    def _ensure_no_buckets(self, buckets):
        self.assertEqual(len(buckets), 0, "Bucket list was not empty")
        return True

    def _ensure_one_bucket(self, buckets, name):
        self.assertEqual(len(buckets), 1,
                         "Bucket list didn't have exactly one element in it")
        self.assertEqual(buckets[0].name, name, "Wrong name")
        return True

    def test_list_buckets(self):
        # Make sure we are starting with no buckets.
        self._ensure_no_buckets(self.conn.get_all_buckets())

    def test_create_and_delete_bucket(self):
        # Test bucket creation and deletion.
        bucket_name = 'testbucket'

        self.conn.create_bucket(bucket_name)
        self._ensure_one_bucket(self.conn.get_all_buckets(), bucket_name)
        self.conn.delete_bucket(bucket_name)
        self._ensure_no_buckets(self.conn.get_all_buckets())

    def test_create_bucket_and_key_and_delete_key_again(self):
        # Test key operations on buckets.
        bucket_name = 'testbucket'
        key_name = 'somekey'
        key_contents = 'somekey'

        b = self.conn.create_bucket(bucket_name)
        k = b.new_key(key_name)
        k.set_contents_from_string(key_contents)

        bucket = self.conn.get_bucket(bucket_name)

        # make sure the contents are correct
        key = bucket.get_key(key_name)
        self.assertEqual(key.get_contents_as_string(), key_contents,
                         "Bad contents")

        # delete the key
        key.delete()

        self._ensure_no_buckets(bucket.get_all_keys())

    def test_unknown_bucket(self):
        # NOTE(unicell): Since Boto v2.25.0, the underlying implementation
        # of get_bucket method changed from GET to HEAD.
        #
        # Prior to v2.25.0, default validate=True fetched a list of keys in the
        # bucket and raises S3ResponseError. As a side effect of switching to
        # HEAD request, get_bucket call now generates less error message.
        #
        # To keep original semantics, additional get_all_keys call is
        # suggestted per Boto document. This case tests both validate=False and
        # validate=True case for completeness.
        #
        # http://docs.pythonboto.org/en/latest/releasenotes/v2.25.0.html
        # http://docs.pythonboto.org/en/latest/s3_tut.html#accessing-a-bucket
        bucket_name = 'falalala'
        self.assertRaises(boto_exception.S3ResponseError,
                          self.conn.get_bucket,
                          bucket_name)
        bucket = self.conn.get_bucket(bucket_name, validate=False)
        self.assertRaises(boto_exception.S3ResponseError,
                          bucket.get_all_keys,
                          maxkeys=0)

    def tearDown(self):
        """Tear down test server."""
        self.server.stop()
        super(S3APITestCase, self).tearDown()
