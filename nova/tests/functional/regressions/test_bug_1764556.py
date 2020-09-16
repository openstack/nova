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

from nova import context as nova_context
from nova.db import api as db
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture
from nova import utils


class InstanceListWithDeletedServicesTestCase(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Contains regression testing for bug 1764556 which is similar to bug
    1746509 but different in that it deals with a deleted service and compute
    node which was not upgraded to the point of having a UUID and that causes
    problems later when an instance which was running on that node is migrated
    back to an upgraded service with the same hostname. This is because the
    service uuid migration routine gets a ServiceNotFound error when loading
    up a deleted service by hostname.
    """
    def setUp(self):
        super(InstanceListWithDeletedServicesTestCase, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())

        # The NeutronFixture is needed to stub out validate_networks in API.
        self.useFixture(nova_fixtures.NeutronFixture(self))

        # We need the computes reporting into placement for the filter
        # scheduler to pick a host.
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api
        self.admin_api.microversion = 'latest'

        # the image fake backend needed for image discovery
        self.useFixture(nova_fixtures.GlanceFixture(self))

        self.api.microversion = 'latest'

        self.start_service('conductor')
        self.start_service('scheduler')

    def _migrate_server(self, server, target_host):
        self.admin_api.api_post('/servers/%s/action' % server['id'],
                                {'migrate': None})
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual(target_host, server['OS-EXT-SRV-ATTR:host'])
        self.admin_api.api_post('/servers/%s/action' % server['id'],
                                {'confirmResize': None},
                                check_response_status=[204])
        server = self._wait_for_state_change(server, 'ACTIVE')
        return server

    def test_instance_list_deleted_service_with_no_uuid(self):
        """This test covers the following scenario:

        1. create an instance on a host which we'll simulate to be old
           by not having a uuid set
        2. migrate the instance to the "newer" host that has a service uuid
        3. delete the old service/compute node
        4. start a new service with the old hostname (still host1); this will
           also create a new compute_nodes table record for that host/node
        5. migrate the instance back to the host1 service
        6. list instances which will try to online migrate the old service uuid
        """
        host1 = self.start_service('compute', host='host1')

        # Create an instance which will be on host1 since it's the only host.
        server_req = self._build_server(networks='none')
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(server, 'ACTIVE')

        # Now we start a 2nd compute which is "upgraded" (has a uuid) and
        # we'll migrate the instance to that host.
        host2 = self.start_service('compute', host='host2')
        self.assertIsNotNone(host2.service_ref.uuid)

        server = self._migrate_server(server, 'host2')

        # Delete the host1 service (which implicitly deletes the host1 compute
        # node record).
        host1.stop()
        self.admin_api.api_delete(
            '/os-services/%s' % host1.service_ref.uuid)
        # We should now only have 1 compute service (host2).
        compute_services = self.admin_api.api_get(
            '/os-services?binary=nova-compute').body['services']
        self.assertEqual(1, len(compute_services))
        # Make sure the compute node is also gone.
        self.admin_api.api_get(
            '/os-hypervisors?hypervisor_hostname_pattern=host1',
            check_response_status=[404])

        # Now recreate the host1 service and compute node by restarting the
        # service.
        self.restart_compute_service(host1)
        # At this point, host1's service should have a uuid.
        self.assertIsNotNone(host1.service_ref.uuid)

        # Sanity check that there are 3 services in the database, but only 1
        # is deleted.
        ctxt = nova_context.get_admin_context()
        with utils.temporary_mutation(ctxt, read_deleted='yes'):
            services = db.service_get_all_by_binary(ctxt, 'nova-compute')
            self.assertEqual(3, len(services))
            deleted_services = [svc for svc in services if svc['deleted']]
            self.assertEqual(1, len(deleted_services))
            deleted_service = deleted_services[0]
            self.assertEqual('host1', deleted_service['host'])

        # Now migrate the instance back to host1.
        self._migrate_server(server, 'host1')

        # Now null out the service uuid to simulate that the deleted host1
        # is old. We have to do this through the DB API directly since the
        # Service object won't allow a null uuid field. We also have to do
        # this *after* deleting the service via the REST API and migrating the
        # server because otherwise that will set a uuid when looking up the
        # service.
        with utils.temporary_mutation(ctxt, read_deleted='yes'):
            service_ref = db.service_update(
                ctxt, deleted_service['id'], {'uuid': None})
            self.assertIsNone(service_ref['uuid'])

        # Finally, list servers as an admin so it joins on services to get host
        # information.
        servers = self.admin_api.get_servers(detail=True)
        for server in servers:
            self.assertEqual('UP', server['host_status'])
