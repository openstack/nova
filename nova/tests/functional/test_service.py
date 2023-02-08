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

import functools
from unittest import mock

import fixtures
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context as nova_context
from nova import exception
from nova.objects import service
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.virt import node


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


class TestComputeStartupChecks(test.TestCase):
    STUB_COMPUTE_ID = False

    def setUp(self):
        super().setUp()
        self.useFixture(nova_fixtures.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        self._local_uuid = str(uuids.node)

        self.useFixture(fixtures.MockPatch(
            'nova.virt.node.get_local_node_uuid',
            functools.partial(self.local_uuid, True)))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.node.read_local_node_uuid',
            self.local_uuid))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.node.write_local_node_uuid',
            mock.DEFAULT))
        self.flags(compute_driver='fake.FakeDriverWithoutFakeNodes')

    def local_uuid(self, get=False):
        if get and not self._local_uuid:
            # Simulate the get_local_node_uuid behavior of calling write once
            self._local_uuid = str(uuids.node)
            node.write_local_node_uuid(self._local_uuid)
        return self._local_uuid

    def test_compute_node_identity_greenfield(self):
        # Level-set test case to show that starting and re-starting without
        # any error cases works as expected.

        # Start with no local compute_id
        self._local_uuid = None
        self.start_service('compute')

        # Start should have generated and written a compute id
        node.write_local_node_uuid.assert_called_once_with(str(uuids.node))

        # Starting again should succeed and not cause another write
        self.start_service('compute')
        node.write_local_node_uuid.assert_called_once_with(str(uuids.node))

    def test_compute_node_identity_deleted(self):
        self.start_service('compute')

        # Simulate the compute_id file being deleted
        self._local_uuid = None

        # Should refuse to start because it's not our first time and the file
        # being missing is a hard error.
        exc = self.assertRaises(exception.InvalidConfiguration,
                                self.start_service, 'compute')
        self.assertIn('lost that state', str(exc))

    def test_compute_node_hostname_changed(self):
        # Start our compute once to create the node record
        self.start_service('compute')

        # Starting with a different hostname should trigger the abort
        exc = self.assertRaises(exception.InvalidConfiguration,
                                self.start_service, 'compute', host='other')
        self.assertIn('hypervisor_hostname', str(exc))

    def test_compute_node_uuid_changed(self):
        # Start our compute once to create the node record
        self.start_service('compute')

        # Simulate a changed local compute_id file
        self._local_uuid = str(uuids.othernode)

        # We should fail to create the compute node record again, but with a
        # useful error message about why.
        exc = self.assertRaises(exception.InvalidConfiguration,
                                self.start_service, 'compute')
        self.assertIn('Duplicate compute node record', str(exc))
