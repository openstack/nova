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
import shutil
import sys
import time
import urllib2
import urlparse

from nova import context
from nova import flags
from nova import log as logging
from nova import utils
from nova.auth import manager
from nova.auth import signer


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.virt.images')


def fetch(image_id, path, _user, _project):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    image_service = utils.get_default_image_service()
    with open(path, "wb") as image_file:
        elevated = context.get_admin_context()
        metadata = image_service.get(elevated, image_id, image_file)
    return metadata


# NOTE(vish): The methods below should be unnecessary, but I'm leaving
#             them in case the glance client does not work on windows.
def _fetch_image_no_curl(url, path, headers):
    request = urllib2.Request(url)
    for (k, v) in headers.iteritems():
        request.add_header(k, v)

    def urlretrieve(urlfile, fpath):
        chunk = 1 * 1024 * 1024
        f = open(fpath, "wb")
        while 1:
            data = urlfile.read(chunk)
            if not data:
                break
            f.write(data)

    urlopened = urllib2.urlopen(request)
    urlretrieve(urlopened, path)
    LOG.debug(_("Finished retreving %(url)s -- placed in %(path)s") % locals())


def _fetch_s3_image(image, path, user, project):
    url = image_url(image)

    # This should probably move somewhere else, like e.g. a download_as
    # method on User objects and at the same time get rewritten to use
    # a web client.
    headers = {}
    headers['Date'] = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

    (_, _, url_path, _, _, _) = urlparse.urlparse(url)
    access = manager.AuthManager().get_access_key(user, project)
    signature = signer.Signer(user.secret.encode()).s3_authorization(headers,
                                                                     'GET',
                                                                     url_path)
    headers['Authorization'] = 'AWS %s:%s' % (access, signature)

    if sys.platform.startswith('win'):
        return _fetch_image_no_curl(url, path, headers)
    else:
        cmd = ['/usr/bin/curl', '--fail', '--silent', url]
        for (k, v) in headers.iteritems():
            cmd += ['-H', '\'%s: %s\'' % (k, v)]

        cmd += ['-o', path]
        return utils.execute(*cmd)


def _fetch_local_image(image, path, user, project):
    source = _image_path(os.path.join(image, 'image'))
    if sys.platform.startswith('win'):
        return shutil.copy(source, path)
    else:
        return utils.execute('cp', source, path)


def _image_path(path):
    return os.path.join(FLAGS.images_path, path)


# TODO(vish): xenapi should use the glance client code directly instead
#             of retrieving the image using this method.
def image_url(image):
    if FLAGS.image_service == "nova.image.glance.GlanceImageService":
        return "http://%s:%s/images/%s" % (FLAGS.glance_host,
            FLAGS.glance_port, image)
    return "http://%s:%s/_images/%s/image" % (FLAGS.s3_host, FLAGS.s3_port,
                                              image)
