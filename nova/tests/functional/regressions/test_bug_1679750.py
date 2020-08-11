# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg
from oslo_config import fixture as config_fixture
from placement import conf as placement_conf
from placement.tests import fixtures as placement_db

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class TestLocalDeleteAllocations(test.TestCase,
                                 integrated_helpers.InstanceHelperMixin):
    def setUp(self):
        super(TestLocalDeleteAllocations, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        # The NeutronFixture is needed to show security groups for a server.
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api
        # We need the latest microversion to force-down the compute service
        self.admin_api.microversion = 'latest'

        self.start_service('conductor')

        self.start_service('scheduler')

    @staticmethod
    def _get_usages(placement_api, rp_uuid):
        fmt = '/resource_providers/%(uuid)s/usages'
        resp = placement_api.get(fmt % {'uuid': rp_uuid})
        return resp.body['usages']

    def test_local_delete_removes_allocations_after_compute_restart(self):
        """Tests that allocations are removed after a local delete.

        This tests the scenario where a server is local deleted (because the
        compute host is down) and we want to make sure that its allocations
        have been cleaned up once the nova-compute service restarts.

        In this scenario we conditionally use the PlacementFixture to simulate
        the case that nova-api isn't configured to talk to placement, thus we
        need to manage the placement database independently.
        """
        config = cfg.ConfigOpts()
        placement_config = self.useFixture(config_fixture.Config(config))
        placement_conf.register_opts(config)
        self.useFixture(placement_db.Database(placement_config,
                                             set_config=True))
        # Get allocations, make sure they are 0.
        with func_fixtures.PlacementFixture(
                conf_fixture=placement_config, db=False,
                register_opts=False) as placement:
            compute = self.start_service('compute')
            placement_api = placement.api
            resp = placement_api.get('/resource_providers')
            rp_uuid = resp.body['resource_providers'][0]['uuid']
            usages_before = self._get_usages(placement_api, rp_uuid)
            for usage in usages_before.values():
                self.assertEqual(0, usage)

            # Create a server.
            server = self._build_server(networks='none')
            server = self.admin_api.post_server({'server': server})
            server = self._wait_for_state_change(server, 'ACTIVE')

            # Assert usages are non zero now.
            usages_during = self._get_usages(placement_api, rp_uuid)
            for usage in usages_during.values():
                self.assertNotEqual(0, usage)

            # Force-down compute to trigger local delete.
            compute.stop()
            compute_service_id = self.admin_api.get_services(
                host=compute.host, binary='nova-compute')[0]['id']
            self.admin_api.put_service(compute_service_id,
                                       {'forced_down': True})

        # Delete the server (will be a local delete because compute is down).
        self._delete_server(server)

        with func_fixtures.PlacementFixture(
                conf_fixture=placement_config, db=False,
                register_opts=False) as placement:
            placement_api = placement.api
            # Assert usages are still non-zero.
            usages_during = self._get_usages(placement_api, rp_uuid)
            for usage in usages_during.values():
                self.assertNotEqual(0, usage)

            # Start the compute service again. Before it comes up, it will
            # call the update_available_resource code in the ResourceTracker
            # which is what "heals" the allocations for the deleted instance.
            compute.start()

            # Get the allocations again to check against the original.
            usages_after = self._get_usages(placement_api, rp_uuid)

        # They should match.
        self.assertEqual(usages_before, usages_after)

    def test_local_delete_removes_allocations_from_api(self):
        """Tests that the compute API deletes allocations when the compute
        service on which the instance was running is down.
        """
        placement_api = self.useFixture(func_fixtures.PlacementFixture()).api
        compute = self.start_service('compute')
        # Get allocations, make sure they are 0.
        resp = placement_api.get('/resource_providers')
        rp_uuid = resp.body['resource_providers'][0]['uuid']
        usages_before = self._get_usages(placement_api, rp_uuid)
        for usage in usages_before.values():
            self.assertEqual(0, usage)

        # Create a server.
        server = self._build_server(networks='none')
        server = self.admin_api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')

        # Assert usages are non zero now.
        usages_during = self._get_usages(placement_api, rp_uuid)
        for usage in usages_during.values():
            self.assertNotEqual(0, usage)

        # Force-down compute to trigger local delete.
        compute.stop()
        compute_service_id = self.admin_api.get_services(
            host=compute.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute_service_id, {'forced_down': True})

        # Delete the server (will be a local delete because compute is down).
        self._delete_server(server)

        # Get the allocations again to make sure they were deleted.
        usages_after = self._get_usages(placement_api, rp_uuid)

        # They should match.
        self.assertEqual(usages_before, usages_after)
