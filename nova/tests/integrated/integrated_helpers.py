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
from nova import flags
from nova import service
from nova import test  # For the flags
from nova.auth import manager
from nova.exception import Error
from nova.log import logging
from nova.tests.integrated.api import client


FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.tests.integrated')


def generate_random_alphanumeric(length):
    """Creates a random alphanumeric string of specified length"""
    return ''.join(random.choice(string.ascii_uppercase + string.digits)
                   for _x in range(length))


def generate_random_numeric(length):
    """Creates a random numeric string of specified length"""
    return ''.join(random.choice(string.digits)
                   for _x in range(length))


def generate_new_element(items, prefix, numeric=False):
    """Creates a random string with prefix, that is not in 'items' list"""
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
            # TODO(justinsb): No way to create an image through API???
            #created_image = self.openstack_api.post_image(image)
            #images.append(created_image)
            raise exception.Error("No way to create an image through API??")

        if images:
            return images[0]
        return None


class IntegratedUnitTestContext(object):
    __INSTANCE = None

    def __init__(self):
        self.auth_manager = manager.AuthManager()

        self.wsgi_server = None
        self.wsgi_apps = []
        self.api_service = None

        self.services = []
        self.auth_url = None
        self.project_name = None

        self.setup()

    def setup(self):
        self._start_services()

        self._create_test_user()

    def _create_test_user(self):
        self.test_user = self._create_unittest_user()

        # No way to currently pass this through the OpenStack API
        self.project_name = 'openstack'
        self._configure_project(self.project_name, self.test_user)

    def _start_services(self):
        self._start_compute_service()
        self._start_volume_service()
        self._start_scheduler_service()
        self._start_network_service()

        # WSGI shutdown broken :-(
        # bug731668
        if not self.api_service:
            self._start_api_service()

    def _start_compute_service(self):
        compute_service = service.Service.create(binary='nova-compute')
        compute_service.start()
        self.services.append(compute_service)
        return compute_service

    def _start_network_service(self):
        network_service = service.Service.create(binary='nova-network')
        network_service.start()
        self.services.append(network_service)
        return network_service

    def _start_volume_service(self):
        volume_service = service.Service.create(binary='nova-volume')
        volume_service.start()
        self.services.append(volume_service)
        return volume_service

    def _start_scheduler_service(self):
        scheduler_service = service.Service.create(binary='nova-scheduler')
        scheduler_service.start()
        self.services.append(scheduler_service)
        return scheduler_service

    def cleanup(self):
        for service in self.services:
            service.kill()
        self.services = []
        # TODO(justinsb): Shutdown WSGI & anything else we startup
        # bug731668
        # WSGI shutdown broken :-(
        # self.wsgi_server.terminate()
        # self.wsgi_server = None
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

    def _start_api_service(self):
        api_service = service.ApiService.create()
        api_service.start()

        if not api_service:
            raise Exception("API Service was None")

        # WSGI shutdown broken :-(
        #self.services.append(volume_service)
        self.api_service = api_service

        self.auth_url = 'http://localhost:8774/v1.0'

        return api_service

    # WSGI shutdown broken :-(
    # bug731668
    #@staticmethod
    #def get():
    #    if not IntegratedUnitTestContext.__INSTANCE:
    #        IntegratedUnitTestContext.startup()
    #        #raise Error("Must call IntegratedUnitTestContext::startup")
    #    return IntegratedUnitTestContext.__INSTANCE

    @staticmethod
    def startup():
        # Because WSGI shutdown is broken at the moment, we have to recycle
        # bug731668
        if IntegratedUnitTestContext.__INSTANCE:
            #raise Error("Multiple calls to IntegratedUnitTestContext.startup")
            IntegratedUnitTestContext.__INSTANCE.setup()
        else:
            IntegratedUnitTestContext.__INSTANCE = IntegratedUnitTestContext()
        return IntegratedUnitTestContext.__INSTANCE

    @staticmethod
    def shutdown():
        if not IntegratedUnitTestContext.__INSTANCE:
            raise Error("Must call IntegratedUnitTestContext::startup")
        IntegratedUnitTestContext.__INSTANCE.cleanup()
        # WSGI shutdown broken :-(
        # bug731668
        #IntegratedUnitTestContext.__INSTANCE = None


class _IntegratedTestBase(test.TestCase):
    def setUp(self):
        super(_IntegratedTestBase, self).setUp()

        f = self._get_flags()
        self.flags(**f)

        context = IntegratedUnitTestContext.startup()
        self.user = context.test_user
        self.api = self.user.openstack_api

    def tearDown(self):
        IntegratedUnitTestContext.shutdown()
        super(_IntegratedTestBase, self).tearDown()

    def _get_flags(self):
        """An opportunity to setup flags, before the services are started"""
        f = {}
        #f['network_driver'] = 'nova.network.fake.FakeNetworkDriver'
        f['fake_network'] = True
        return f

    def _build_minimal_create_server_request(self):
        server = {}

        image = self.user.get_valid_image(create=True)
        image_id = image['id']

        #TODO(justinsb): This is FUBAR
        image_id = abs(hash(image_id))

        # We now have a valid imageId
        server['imageId'] = image_id

        # Set a valid flavorId
        flavor = self.api.get_flavors()[0]
        LOG.debug("Using flavor: %s" % flavor)
        server['flavorId'] = flavor['id']

        # Set a valid server name
        server_name = self.user.get_unused_server_name()
        server['name'] = server_name

        return server
