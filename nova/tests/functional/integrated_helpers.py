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

from oslo_config import cfg

from nova import crypto
import nova.image.glance
from nova.openstack.common import log as logging
from nova import service
from nova import test
from nova.tests.functional.api import client
from nova.tests.unit import cast_as_call
from nova.tests.unit import fake_crypto
import nova.tests.unit.image.fake


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
CONF.import_opt('manager', 'nova.cells.opts', group='cells')


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

    def setUp(self):
        super(_IntegratedTestBase, self).setUp()

        f = self._get_flags()
        self.flags(**f)
        self.flags(verbose=True)

        nova.tests.unit.image.fake.stub_out_image_service(self.stubs)
        self.stubs.Set(crypto, 'ensure_ca_filesystem',
                       fake_crypto.ensure_ca_filesystem)
        self.stubs.Set(crypto, 'fetch_ca',
                       fake_crypto.fetch_ca)
        self.stubs.Set(crypto, 'generate_x509_cert',
                       fake_crypto.generate_x509_cert)
        self.flags(scheduler_driver='nova.scheduler.'
                    'chance.ChanceScheduler')
        self._setup_services()
        self._start_api_service()

        self.api = self._get_test_client()

        self.useFixture(cast_as_call.CastAsCall(self.stubs))

    def _setup_services(self):
        self.conductor = self.start_service('conductor',
                                            manager=CONF.conductor.manager)
        self.compute = self.start_service('compute')
        self.cert = self.start_service('cert')
        self.consoleauth = self.start_service('consoleauth')
        self.network = self.start_service('network')
        self.scheduler = self.start_service('scheduler')
        self.cells = self.start_service('cells', manager=CONF.cells.manager)

    def tearDown(self):
        self.osapi.stop()
        nova.tests.unit.image.fake.FakeImageService_reset()
        super(_IntegratedTestBase, self).tearDown()

    def _get_test_client(self):
        return client.TestOpenStackClient('fake', 'fake', self.auth_url)

    def _start_api_service(self):
        self.osapi = service.WSGIService("osapi_compute")
        self.osapi.start()
        self.auth_url = 'http://%(host)s:%(port)s/%(api_version)s' % ({
            'host': self.osapi.host, 'port': self.osapi.port,
            'api_version': self._api_version})

    def _get_flags(self):
        """An opportunity to setup flags, before the services are started."""
        f = {}

        # Ensure tests only listen on localhost
        f['ec2_listen'] = '127.0.0.1'
        f['osapi_compute_listen'] = '127.0.0.1'
        f['metadata_listen'] = '127.0.0.1'

        # Auto-assign ports to allow concurrent tests
        f['ec2_listen_port'] = 0
        f['osapi_compute_listen_port'] = 0
        f['metadata_listen_port'] = 0

        f['fake_network'] = True
        return f

    def get_unused_server_name(self):
        servers = self.api.get_servers()
        server_names = [server['name'] for server in servers]
        return generate_new_element(server_names, 'server')

    def get_invalid_image(self):
        return str(uuid.uuid4())

    def _build_minimal_create_server_request(self):
        server = {}

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
        flavor = self.api.get_flavors()[0]
        LOG.debug("Using flavor: %s" % flavor)
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])

        # Set a valid server name
        server_name = self.get_unused_server_name()
        server['name'] = server_name
        return server
