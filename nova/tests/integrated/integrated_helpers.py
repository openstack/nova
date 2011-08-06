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

from nova import exception
from nova import service
from nova import test  # For the flags
from nova.auth import manager
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


class TestUser(object):
    def __init__(self, name, secret, auth_url):
        self.name = name
        self.secret = secret
        self.auth_url = auth_url

        if not auth_url:
            raise exception.Error("auth_url is required")
        self.openstack_api = client.TestOpenStackClient(self.name,
                                                        self.secret,
                                                        self.auth_url)

    def get_unused_server_name(self):
        servers = self.openstack_api.get_servers()
        server_names = [server['name'] for server in servers]
        return generate_new_element(server_names, 'server')

    def get_invalid_image(self):
        images = self.openstack_api.get_images()
        image_ids = [image['id'] for image in images]
        return generate_new_element(image_ids, '', numeric=True)

    def get_valid_image(self, create=False):
        images = self.openstack_api.get_images()
        if create and not images:
            # TODO(justinsb): No way currently to create an image through API
            #created_image = self.openstack_api.post_image(image)
            #images.append(created_image)
            raise exception.Error("No way to create an image through API")

        if images:
            return images[0]
        return None


class IntegratedUnitTestContext(object):
    def __init__(self, auth_url):
        self.auth_manager = manager.AuthManager()

        self.auth_url = auth_url
        self.project_name = None

        self.test_user = None

        self.setup()

    def setup(self):
        self._create_test_user()

    def _create_test_user(self):
        self.test_user = self._create_unittest_user()

        # No way to currently pass this through the OpenStack API
        self.project_name = 'openstack'
        self._configure_project(self.project_name, self.test_user)

    def cleanup(self):
        self.test_user = None

    def _create_unittest_user(self):
        users = self.auth_manager.get_users()
        user_names = [user.name for user in users]
        auth_name = generate_new_element(user_names, 'unittest_user_')
        auth_key = generate_random_alphanumeric(16)

        # Right now there's a bug where auth_name and auth_key are reversed
        # bug732907
        auth_key = auth_name

        self.auth_manager.create_user(auth_name, auth_name, auth_key, False)
        return TestUser(auth_name, auth_key, self.auth_url)

    def _configure_project(self, project_name, user):
        projects = self.auth_manager.get_projects()
        project_names = [project.name for project in projects]
        if not project_name in project_names:
            project = self.auth_manager.create_project(project_name,
                                                       user.name,
                                                       description=None,
                                                       member_users=None)
        else:
            self.auth_manager.add_to_project(user.name, project_name)


class _IntegratedTestBase(test.TestCase):
    def setUp(self):
        super(_IntegratedTestBase, self).setUp()

        f = self._get_flags()
        self.flags(**f)
        self.flags(verbose=True)

        def fake_get_image_service(image_href):
            image_id = int(str(image_href).split('/')[-1])
            return (nova.image.fake.FakeImageService(), image_id)
        self.stubs.Set(nova.image, 'get_image_service', fake_get_image_service)

        # set up services
        self.start_service('compute')
        self.start_service('volume')
        self.start_service('network')
        self.start_service('scheduler')

        self._start_api_service()

        self.context = IntegratedUnitTestContext(self.auth_url)

        self.user = self.context.test_user
        self.api = self.user.openstack_api

    def _start_api_service(self):
        osapi = service.WSGIService("osapi")
        osapi.start()
        self.auth_url = 'http://%s:%s/v1.1' % (osapi.host, osapi.port)
        LOG.warn(self.auth_url)

    def tearDown(self):
        self.context.cleanup()
        super(_IntegratedTestBase, self).tearDown()

    def _get_flags(self):
        """An opportunity to setup flags, before the services are started."""
        f = {}

        # Auto-assign ports to allow concurrent tests
        f['ec2_listen_port'] = 0
        f['osapi_listen_port'] = 0

        f['image_service'] = 'nova.image.fake.FakeImageService'
        f['fake_network'] = True
        return f

    def _build_minimal_create_server_request(self):
        server = {}

        image = self.user.get_valid_image(create=True)
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
        server_name = self.user.get_unused_server_name()
        server['name'] = server_name

        return server
