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

from nova import context as nova_context
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture


class ServiceTestCase(test.TestCase,
                      integrated_helpers.InstanceHelperMixin):
    """Contains scenarios for testing services.
    """

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        # Use the standard fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        # Start nova controller services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).api
        self.start_service('conductor')
        self.scheduler = self.start_service('scheduler')
        # Our OSAPIFixture does not use a WSGIService, so just use the metadata
        # server fixture (which uses WSGIService) for testing.
        self.metadata = self.useFixture(
            nova_fixtures.OSMetadataServer()).metadata
        # Start one compute service.
        self.start_service('compute')

    def test_service_reset_resets_cell_cache(self):
        """Tests that the cell cache for database transaction context managers
        is cleared after a service reset (example scenario: SIGHUP).
        """
        server_req = self._build_minimal_create_server_request(
            self.api, 'test-service-reset')
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        # Cell cache should be populated after creating a server.
        self.assertTrue(nova_context.CELL_CACHE)
        self.scheduler.reset()
        # Cell cache should be empty after the service reset.
        self.assertEqual({}, nova_context.CELL_CACHE)

        # Now test the WSGI service.
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        # Cell cache should be populated after creating a server.
        self.assertTrue(nova_context.CELL_CACHE)
        self.metadata.reset()
        # Cell cache should be empty after the service reset.
        self.assertEqual({}, nova_context.CELL_CACHE)

    def test_service_start_resets_cell_cache(self):
        """Tests that the cell cache for database transaction context managers
        is cleared upon a service start (example scenario: service start after
        a SIGTERM and the parent process forks child process workers).
        """
        server_req = self._build_minimal_create_server_request(
            self.api, 'test-service-start')
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        # Cell cache should be populated after creating a server.
        self.assertTrue(nova_context.CELL_CACHE)
        self.scheduler.stop()
        # NOTE(melwitt): Simulate a service starting after being stopped. The
        # scenario we want to handle is one where during start, the parent
        # process forks child process workers while one or more of its cached
        # database transaction context managers is inside a locked code
        # section. If the child processes are forked while the lock is locked,
        # the child processes begin with an already locked lock that can never
        # be acquired again. The result is that requests gets stuck and fail
        # with a CellTimeout error.
        self.scheduler.start()
        # Cell cache should be empty after the service start.
        self.assertEqual({}, nova_context.CELL_CACHE)

        # Now test the WSGI service.
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        # Cell cache should be populated after creating a server.
        self.assertTrue(nova_context.CELL_CACHE)
        self.metadata.stop()
        self.metadata.start()
        # Cell cache should be empty after the service reset.
        self.assertEqual({}, nova_context.CELL_CACHE)
