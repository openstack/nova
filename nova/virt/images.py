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
import time
import urlparse

from nova import flags
from nova import process
from nova.auth import manager
from nova.auth import signer


FLAGS = flags.FLAGS
flags.DEFINE_bool('use_s3', True,
                  'whether to get images from s3 or use local copy')


def fetch(image, path, user, project):
    if FLAGS.use_s3:
        f = _fetch_s3_image
    else:
        f = _fetch_local_image
    return f(image, path, user, project)


def _fetch_s3_image(image, path, user, project):
    url = image_url(image)

    # This should probably move somewhere else, like e.g. a download_as
    # method on User objects and at the same time get rewritten to use
    # twisted web client.
    headers = {}
    headers['Date'] = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

    (_, _, url_path, _, _, _) = urlparse.urlparse(url)
    access = manager.AuthManager().get_access_key(user, project)
    signature = signer.Signer(user.secret.encode()).s3_authorization(headers,
                                                                     'GET',
                                                                     url_path)
    headers['Authorization'] = 'AWS %s:%s' % (access, signature)

    cmd = ['/usr/bin/curl', '--fail', '--silent', url]
    for (k,v) in headers.iteritems():
        cmd += ['-H', '%s: %s' % (k,v)]

    cmd += ['-o', path]
    return process.SharedPool().execute(executable=cmd[0], args=cmd[1:])


def _fetch_local_image(image, path, user, project):
    source = _image_path('%s/image' % image)
    return process.simple_execute('cp %s %s' % (source, path))


def _image_path(path):
    return os.path.join(FLAGS.images_path, path)


def image_url(image):
    return "http://%s:%s/_images/%s/image" % (FLAGS.s3_host, FLAGS.s3_port,
                                              image)
