# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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
Provides common functionality for integrated unit tests
"""

import random
import string

from nova import service
from nova import test  # For the flags
import nova.image.glance
from nova.log import logging
from nova.tests.integrated.api import client


LOG = logging.getLogger('nova.tests.integrated')


def generate_random_alphanumeric(length):
    """Creates a random alphanumeric string of specified length."""
    return ''.join(random.choice(string.ascii_uppercase + string.digits)
                   for _x in range(length))


def generate_random_numeric(length):
    """Creates a random numeric string of specified length."""
    return ''.join(random.choice(string.digits)
                   for _x in range(length))


def generate_new_element(items, prefix, numeric=False):
    """Creates a random string with prefix, that is not in 'items' list."""
    while True:
        if numeric:
            candidate = prefix + generate_random_numeric(8)
        else:
            candidate = prefix + generate_random_alphanumeric(8)
        if not candidate in items:
            return candidate
        LOG.debug("Random collision on %s" % candidate)


class _IntegratedTestBase(test.TestCase):
    def setUp(self):
        super(_IntegratedTestBase, self).setUp()

        f = self._get_flags()
        self.flags(**f)
        self.flags(verbose=True)

        def fake_get_image_service(context, image_href):
            image_id = int(str(image_href).split('/')[-1])
            return (nova.image.fake.FakeImageService(), image_id)
        self.stubs.Set(nova.image, 'get_image_service', fake_get_image_service)

        # set up services
        self.start_service('compute')
        self.start_service('volume')
        self.start_service('network')
        self.start_service('scheduler')

        self._start_api_service()

        self.api = client.TestOpenStackClient('fake', 'fake', self.auth_url)

    def _start_api_service(self):
        osapi = service.WSGIService("osapi")
        osapi.start()
        self.auth_url = 'http://%s:%s/v1.1' % (osapi.host, osapi.port)
        LOG.warn(self.auth_url)

    def _get_flags(self):
        """An opportunity to setup flags, before the services are started."""
        f = {}

        # Auto-assign ports to allow concurrent tests
        f['ec2_listen_port'] = 0
        f['osapi_listen_port'] = 0

        f['image_service'] = 'nova.image.fake.FakeImageService'
        f['fake_network'] = True
        return f

    def get_unused_server_name(self):
        servers = self.api.get_servers()
        server_names = [server['name'] for server in servers]
        return generate_new_element(server_names, 'server')

    def get_invalid_image(self):
        images = self.api.get_images()
        image_ids = [image['id'] for image in images]
        return generate_new_element(image_ids, '', numeric=True)

    def _build_minimal_create_server_request(self):
        server = {}

        image = self.api.get_images()[0]
        LOG.debug("Image: %s" % image)

        if 'imageRef' in image:
            image_href = image['imageRef']
        else:
            image_href = image['id']
            image_href = 'http://fake.server/%s' % image_href

        # We now have a valid imageId
        server['imageRef'] = image_href

        # Set a valid flavorId
        flavor = self.api.get_flavors()[0]
        LOG.debug("Using flavor: %s" % flavor)
        server['flavorRef'] = 'http://fake.server/%s' % flavor['id']

        # Set a valid server name
        server_name = self.get_unused_server_name()
        server['name'] = server_name

        return server
