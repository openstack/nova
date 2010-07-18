# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
Handling of VM disk images.
"""

import os.path

from nova import flags

FLAGS = flags.FLAGS

flags.DEFINE_bool('use_s3', True,
                  'whether to get images from s3 or use local copy')


def fetch(pool, image, path):
    if FLAGS.use_s3:
        f = _fetch_s3_image
    else:
        f = _fetch_local_image
    return f(pool, image, path)

def _fetch_s3_image(pool, image, path):
    url = _image_url('%s/image' % image)
    d = pool.simpleExecute('curl --silent %s -o %s' % (url, path))
    return d

def _fetch_local_image(pool, image, path):
    source = _image_path('%s/image' % image)
    d = pool.simpleExecute('cp %s %s' % (source, path))
    return d

def _image_path(path):
    return os.path.join(FLAGS.images_path, path)

def _image_url(path):
    return "%s:%s/_images/%s" % (FLAGS.s3_host, FLAGS.s3_port, path)
