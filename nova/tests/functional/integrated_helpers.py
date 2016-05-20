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
import uuid

from oslo_log import log as logging

import nova.conf
import nova.image.glance
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import cast_as_call
import nova.tests.unit.image.fake


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


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
        if candidate not in items:
            return candidate
        LOG.debug("Random collision on %s" % candidate)


class _IntegratedTestBase(test.TestCase):
    REQUIRES_LOCKING = True
    ADMIN_API = False

    def setUp(self):
        super(_IntegratedTestBase, self).setUp()

        f = self._get_flags()
        self.flags(**f)
        self.flags(verbose=True)

        nova.tests.unit.image.fake.stub_out_image_service(self)
        self._setup_services()

        self.api_fixture = self.useFixture(
            nova_fixtures.OSAPIFixture(self.api_major_version))

        # if the class needs to run as admin, make the api endpoint
        # the admin, otherwise it's safer to run as non admin user.
        if self.ADMIN_API:
            self.api = self.api_fixture.admin_api
        else:
            self.api = self.api_fixture.api

        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

    def _setup_compute_service(self):
        return self.start_service('compute')

    def _setup_scheduler_service(self):
        self.flags(scheduler_driver='chance_scheduler')
        return self.start_service('scheduler')

    def _setup_services(self):
        self.conductor = self.start_service('conductor',
                                            manager=CONF.conductor.manager)
        self.compute = self._setup_compute_service()
        self.consoleauth = self.start_service('consoleauth')

        self.network = self.start_service('network')
        self.scheduler = self._setup_scheduler_service()

    def _get_flags(self):
        """Allow subclass to modify global config before we start services."""
        # NOTE(sdague): _get_flags is used by about 13 tests that
        # subclass this mostly to modify the extensions list. We
        # should instead make that declarative in the future, at which
        # point we can get rid of this.
        return {}

    def get_unused_server_name(self):
        servers = self.api.get_servers()
        server_names = [server['name'] for server in servers]
        return generate_new_element(server_names, 'server')

    def get_unused_flavor_name_id(self):
        flavors = self.api.get_flavors()
        flavor_names = list()
        flavor_ids = list()
        [(flavor_names.append(flavor['name']),
         flavor_ids.append(flavor['id']))
         for flavor in flavors]
        return (generate_new_element(flavor_names, 'flavor'),
                int(generate_new_element(flavor_ids, '', True)))

    def get_invalid_image(self):
        return str(uuid.uuid4())

    def _get_any_image_href(self):
        image = self.api.get_images()[0]
        LOG.debug("Image: %s" % image)

        if self._image_ref_parameter in image:
            image_href = image[self._image_ref_parameter]
        else:
            image_href = image['id']
            image_href = 'http://fake.server/%s' % image_href
        return image_href

    def _build_minimal_create_server_request(self):
        server = {}

        image_href = self._get_any_image_href()

        # We now have a valid imageId
        server[self._image_ref_parameter] = image_href

        # Set a valid flavorId
        flavor = self.api.get_flavors()[0]
        LOG.debug("Using flavor: %s" % flavor)
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])

        # Set a valid server name
        server_name = self.get_unused_server_name()
        server['name'] = server_name
        return server

    def _create_flavor_body(self, name, ram, vcpus, disk, ephemeral, id, swap,
                            rxtx_factor, is_public):
        return {
            "flavor": {
                "name": name,
                "ram": ram,
                "vcpus": vcpus,
                "disk": disk,
                "OS-FLV-EXT-DATA:ephemeral": ephemeral,
                "id": id,
                "swap": swap,
                "rxtx_factor": rxtx_factor,
                "os-flavor-access:is_public": is_public,
            }
        }

    def _create_flavor(self, memory_mb=2048, vcpu=2, disk=10, ephemeral=10,
                       swap=0, rxtx_factor=1.0, is_public=True,
                       extra_spec=None):
        flv_name, flv_id = self.get_unused_flavor_name_id()
        body = self._create_flavor_body(flv_name, memory_mb, vcpu, disk,
                                        ephemeral, flv_id, swap, rxtx_factor,
                                        is_public)
        self.api_fixture.admin_api.post_flavor(body)
        if extra_spec is not None:
            spec = {"extra_specs": extra_spec}
            self.api_fixture.admin_api.post_extra_spec(flv_id, spec)
        return flv_id

    def _build_server(self, flavor_id):
        server = {}

        image_href = self._get_any_image_href()
        image = self.api.get_images()[0]
        LOG.debug("Image: %s" % image)

        if self._image_ref_parameter in image:
            image_href = image[self._image_ref_parameter]
        else:
            image_href = image['id']
            image_href = 'http://fake.server/%s' % image_href

        # We now have a valid imageId
        server[self._image_ref_parameter] = image_href

        # Set a valid flavorId
        flavor = self.api.get_flavor(flavor_id)
        LOG.debug("Using flavor: %s" % flavor)
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])

        # Set a valid server name
        server_name = self.get_unused_server_name()
        server['name'] = server_name
        return server

    def _check_api_endpoint(self, endpoint, expected_middleware):
        app = self.api_fixture.osapi.app.get((None, '/v2'))

        while getattr(app, 'application', False):
            for middleware in expected_middleware:
                if isinstance(app.application, middleware):
                    expected_middleware.remove(middleware)
                    break
            app = app.application

        self.assertEqual([],
                         expected_middleware,
                         ("The expected wsgi middlewares %s are not "
                          "existed") % expected_middleware)
