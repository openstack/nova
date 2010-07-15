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
Simple object store using Blobs and JSON files on disk.
"""

import datetime
import glob
import json
import os
import bisect

from nova import exception
from nova import flags
from nova import utils
from nova.objectstore import stored

FLAGS = flags.FLAGS
flags.DEFINE_string('buckets_path', utils.abspath('../buckets'),
                    'path to s3 buckets')

class Bucket(object):
    def __init__(self, name):
        self.name = name
        self.path = os.path.abspath(os.path.join(FLAGS.buckets_path, name))
        if not self.path.startswith(os.path.abspath(FLAGS.buckets_path)) or \
           not os.path.isdir(self.path):
            raise exception.NotFound()

        self.ctime = os.path.getctime(self.path)

    def __repr__(self):
        return "<Bucket: %s>" % self.name

    @staticmethod
    def all():
        """ list of all buckets """
        buckets = []
        for fn in glob.glob("%s/*.json" % FLAGS.buckets_path):
            try:
                json.load(open(fn))
                name = os.path.split(fn)[-1][:-5]
                buckets.append(Bucket(name))
            except:
                pass

        return buckets

    @staticmethod
    def create(bucket_name, context):
        """Create a new bucket owned by a project.

        @bucket_name: a string representing the name of the bucket to create
        @context: a nova.auth.api.ApiContext object representing who owns the bucket.

        Raises:
            NotAuthorized: if the bucket is already exists or has invalid name
        """
        path = os.path.abspath(os.path.join(
            FLAGS.buckets_path, bucket_name))
        if not path.startswith(os.path.abspath(FLAGS.buckets_path)) or \
           os.path.exists(path):
               raise exception.NotAuthorized()

        os.makedirs(path)

        with open(path+'.json', 'w') as f:
            json.dump({'ownerId': context.project.id}, f)

    @property
    def metadata(self):
        """ dictionary of metadata around bucket,
        keys are 'Name' and 'CreationDate'
        """

        return {
            "Name": self.name,
            "CreationDate": datetime.datetime.utcfromtimestamp(self.ctime),
        }

    @property
    def owner_id(self):
        try:
            with open(self.path+'.json') as f:
                return json.load(f)['ownerId']
        except:
            return None

    def is_authorized(self, context):
        try:
            return context.user.is_admin() or self.owner_id == context.project.id
        except Exception, e:
            pass

    def list_keys(self, prefix='', marker=None, max_keys=1000, terse=False):
        object_names = []
        for root, dirs, files in os.walk(self.path):
            for file_name in files:
                object_names.append(os.path.join(root, file_name)[len(self.path)+1:])
        object_names.sort()
        contents = []

        start_pos = 0
        if marker:
            start_pos = bisect.bisect_right(object_names, marker, start_pos)
        if prefix:
            start_pos = bisect.bisect_left(object_names, prefix, start_pos)

        truncated = False
        for object_name in object_names[start_pos:]:
            if not object_name.startswith(prefix):
                break
            if len(contents) >= max_keys:
                truncated = True
                break
            object_path = self._object_path(object_name)
            c = {"Key": object_name}
            if not terse:
                info = os.stat(object_path)
                c.update({
                    "LastModified": datetime.datetime.utcfromtimestamp(
                        info.st_mtime),
                    "Size": info.st_size,
                })
            contents.append(c)
            marker = object_name

        return {
            "Name": self.name,
            "Prefix": prefix,
            "Marker": marker,
            "MaxKeys": max_keys,
            "IsTruncated": truncated,
            "Contents": contents,
        }

    def _object_path(self, object_name):
        fn = os.path.join(self.path, object_name)

        if not fn.startswith(self.path):
            raise exception.NotAuthorized()

        return fn

    def delete(self):
        if len(os.listdir(self.path)) > 0:
            raise exception.NotAuthorized()
        os.rmdir(self.path)
        os.remove(self.path+'.json')

    def __getitem__(self, key):
        return stored.Object(self, key)

    def __setitem__(self, key, value):
        with open(self._object_path(key), 'wb') as f:
            f.write(value)

    def __delitem__(self, key):
        stored.Object(self, key).delete()
