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
import time

from oslo_log import log as logging

import nova.conf
import nova.image.glance
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.unit import cast_as_call
import nova.tests.unit.image.fake
from nova.tests import uuidsentinel as uuids


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
        LOG.debug("Random collision on %s", candidate)


class _IntegratedTestBase(test.TestCase):
    REQUIRES_LOCKING = True
    ADMIN_API = False
    # Override this in subclasses which use the NeutronFixture. New tests
    # should rely on Neutron since nova-network is deprecated. The default
    # value of False here is only temporary while we update the existing
    # functional tests to use Neutron.
    USE_NEUTRON = False

    def setUp(self):
        super(_IntegratedTestBase, self).setUp()

        # TODO(mriedem): Fix the functional tests to work with Neutron.
        self.flags(use_neutron=self.USE_NEUTRON)

        nova.tests.unit.image.fake.stub_out_image_service(self)

        self.useFixture(cast_as_call.CastAsCall(self))
        placement = self.useFixture(nova_fixtures.PlacementFixture())
        self.placement_api = placement.api

        self._setup_services()

        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

    def _setup_compute_service(self):
        return self.start_service('compute')

    def _setup_scheduler_service(self):
        self.flags(group='scheduler', driver='chance_scheduler')
        return self.start_service('scheduler')

    def _setup_services(self):
        # NOTE(danms): Set the global MQ connection to that of our first cell
        # for any cells-ignorant code. Normally this is defaulted in the tests
        # which will result in us not doing the right thing.
        if 'cell1' in self.cell_mappings:
            self.flags(transport_url=self.cell_mappings['cell1'].transport_url)
        self.conductor = self.start_service('conductor')
        self.consoleauth = self.start_service('consoleauth')

        if self.USE_NEUTRON:
            self.neutron = self.useFixture(nova_fixtures.NeutronFixture(self))
        else:
            self.network = self.start_service('network',
                                              manager=CONF.network_manager)
        self.scheduler = self._setup_scheduler_service()

        self.compute = self._setup_compute_service()
        self.api_fixture = self.useFixture(
            nova_fixtures.OSAPIFixture(self.api_major_version))

        # if the class needs to run as admin, make the api endpoint
        # the admin, otherwise it's safer to run as non admin user.
        if self.ADMIN_API:
            self.api = self.api_fixture.admin_api
        else:
            self.api = self.api_fixture.api

        if hasattr(self, 'microversion'):
            self.api.microversion = self.microversion

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
        return uuids.fake

    def _build_minimal_create_server_request(self):
        server = {}

        # We now have a valid imageId
        server[self._image_ref_parameter] = self.api.get_images()[0]['id']

        # Set a valid flavorId
        flavor = self.api.get_flavors()[0]
        LOG.debug("Using flavor: %s", flavor)
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
        image = self.api.get_images()[0]
        LOG.debug("Image: %s", image)

        # We now have a valid imageId
        server[self._image_ref_parameter] = image['id']

        # Set a valid flavorId
        flavor = self.api.get_flavor(flavor_id)
        LOG.debug("Using flavor: %s", flavor)
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])

        # Set a valid server name
        server_name = self.get_unused_server_name()
        server['name'] = server_name
        return server

    def _check_api_endpoint(self, endpoint, expected_middleware):
        app = self.api_fixture.app().get((None, '/v2'))

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


class InstanceHelperMixin(object):
    def _wait_for_server_parameter(self, admin_api, server, expected_params,
                                   max_retries=10):
        retry_count = 0
        while True:
            server = admin_api.get_server(server['id'])
            if all([server[attr] == expected_params[attr]
                    for attr in expected_params]):
                break
            retry_count += 1
            if retry_count == max_retries:
                self.fail('Wait for state change failed, '
                          'expected_params=%s, server=%s'
                          % (expected_params, server))
            time.sleep(0.5)

        return server

    def _wait_for_state_change(self, admin_api, server, expected_status,
                               max_retries=10):
        return self._wait_for_server_parameter(
            admin_api, server, {'status': expected_status}, max_retries)

    def _build_minimal_create_server_request(self, api, name, image_uuid=None,
                                             flavor_id=None, networks=None,
                                             az=None):
        server = {}

        # We now have a valid imageId
        server['imageRef'] = image_uuid or api.get_images()[0]['id']

        if not flavor_id:
            # Set a valid flavorId
            flavor_id = api.get_flavors()[1]['id']
        server['flavorRef'] = ('http://fake.server/%s' % flavor_id)
        server['name'] = name
        if networks is not None:
            server['networks'] = networks
        if az is not None:
            server['availability_zone'] = az
        return server

    def _wait_until_deleted(self, server):
        try:
            for i in range(40):
                server = self.api.get_server(server['id'])
                if server['status'] == 'ERROR':
                    self.fail('Server went to error state instead of'
                              'disappearing.')
                time.sleep(0.5)

            self.fail('Server failed to delete.')
        except api_client.OpenStackApiNotFoundException:
            return

    def _wait_for_action_fail_completion(
            self, server, expected_action, event_name, api=None):
        """Polls instance action events for the given instance, action and
        action event name until it finds the action event with an error
        result.
        """
        if api is None:
            api = self.api
        completion_event = None
        for attempt in range(10):
            actions = api.get_instance_actions(server['id'])
            # Look for the migrate action.
            for action in actions:
                if action['action'] == expected_action:
                    events = (
                        api.api_get(
                            '/servers/%s/os-instance-actions/%s' %
                            (server['id'], action['request_id'])
                        ).body['instanceAction']['events'])
                    # Look for the action event being in error state.
                    for event in events:
                        if (event['event'] == event_name and
                                event['result'] is not None and
                                event['result'].lower() == 'error'):
                            completion_event = event
                            # Break out of the events loop.
                            break
                    if completion_event:
                        # Break out of the actions loop.
                        break
            # We didn't find the completion event yet, so wait a bit.
            time.sleep(0.5)

        if completion_event is None:
            self.fail('Timed out waiting for %s failure event. Current '
                      'instance actions: %s' % (event_name, actions))

    def _wait_for_migration_status(self, server, expected_status):
        """Waits for a migration record with the given status to be found
        for the given server, else the test fails. The migration record, if
        found, is returned.
        """
        api = getattr(self, 'admin_api', None)
        if api is None:
            api = self.api

        for attempt in range(10):
            migrations = api.api_get('/os-migrations').body['migrations']
            for migration in migrations:
                if (migration['instance_uuid'] == server['id'] and
                        migration['status'].lower() ==
                        expected_status.lower()):
                    return migration
            time.sleep(0.5)
        self.fail('Timed out waiting for migration with status "%s" for '
                  'instance: %s' % (expected_status, server['id']))
