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
Properties of an object stored within a bucket.
"""

from nova.exception import NotFound, NotAuthorized

import os
import nova.crypto

class Object(object):
    def __init__(self, bucket, key):
        """ wrapper class of an existing key """
        self.bucket = bucket
        self.key = key
        self.path = bucket._object_path(key)
        if not os.path.isfile(self.path):
            raise NotFound

    def __repr__(self):
        return "<Object %s/%s>" % (self.bucket, self.key)

    @property
    def md5(self):
        """ computes the MD5 of the contents of file """
        with open(self.path, "r") as f:
            return nova.crypto.compute_md5(f)

    @property
    def mtime(self):
        """ mtime of file """
        return os.path.getmtime(self.path)

    def read(self):
         """ read all contents of key into memory and return """
         return self.file.read()

    @property
    def file(self):
        """ return a file object for the key """
        return open(self.path, 'rb')

    def delete(self):
        """ deletes the file """
        os.unlink(self.path)
