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

from unittest import mock

from nova import context as nova_context
from nova import exception
from nova.objects import service
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


class ServiceTestCase(test.TestCase,
                      integrated_helpers.InstanceHelperMixin):
    """Contains scenarios for testing services.
    """

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        # Use the standard fixtures.
        self.useFixture(nova_fixtures.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

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
        server_req = self._build_server()
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(server, 'ACTIVE')
        # Cell cache should be populated after creating a server.
        self.assertTrue(nova_context.CELL_CACHE)
        self.scheduler.reset()
        # Cell cache should be empty after the service reset.
        self.assertEqual({}, nova_context.CELL_CACHE)

        # Now test the WSGI service.
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(server, 'ACTIVE')
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
        server_req = self._build_server()
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(server, 'ACTIVE')
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
        self._wait_for_state_change(server, 'ACTIVE')
        # Cell cache should be populated after creating a server.
        self.assertTrue(nova_context.CELL_CACHE)
        # we need to mock nova.utils.raise_if_old_compute() that is run at
        # service startup as that will check the global service level which
        # populates the cell cache
        with mock.patch("nova.utils.raise_if_old_compute"):
            self.metadata.stop()
            self.metadata.start()
        # Cell cache should be empty after the service reset.
        self.assertEqual({}, nova_context.CELL_CACHE)


class TestOldComputeCheck(
        test.TestCase, integrated_helpers.InstanceHelperMixin):

    def test_conductor_fails_to_start_with_old_compute(self):
        old_version = service.SERVICE_VERSION_ALIASES[
            service.OLDEST_SUPPORTED_SERVICE_VERSION] - 1
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=old_version):
            self.assertRaises(
                exception.TooOldComputeService, self.start_service,
                'conductor')

    def test_api_fails_to_start_with_old_compute(self):
        old_version = service.SERVICE_VERSION_ALIASES[
            service.OLDEST_SUPPORTED_SERVICE_VERSION] - 1
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=old_version):
            self.assertRaises(
                exception.TooOldComputeService, self.useFixture,
                nova_fixtures.OSAPIFixture(api_version='v2.1'))

    def test_compute_fails_to_start_with_old_compute(self):
        old_version = service.SERVICE_VERSION_ALIASES[
            service.OLDEST_SUPPORTED_SERVICE_VERSION] - 1
        with mock.patch(
                "nova.objects.service.get_minimum_version_all_cells",
                return_value=old_version):
            self.assertRaises(
                exception.TooOldComputeService, self._start_compute, 'host1')
