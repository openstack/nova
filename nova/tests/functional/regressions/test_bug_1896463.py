# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import fixtures
import time

from oslo_config import cfg

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova import utils
from nova.virt import fake


CONF = cfg.CONF


class TestEvacuateResourceTrackerRace(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):
    """Demonstrate bug #1896463.

    Trigger a race condition between an almost finished evacuation that is
    dropping the migration context, and the _update_available_resource()
    periodic task that already loaded the instance list but haven't loaded the
    migration list yet. The result is that the PCI allocation made by the
    evacuation is deleted by the overlapping periodic task run and the instance
    will not have PCI allocation after the evacuation.
    """

    def setUp(self):
        super().setUp()
        self.neutron = self.useFixture(nova_fixtures.NeutronFixture(self))
        self.glance = self.useFixture(nova_fixtures.GlanceFixture(self))
        self.placement = self.useFixture(func_fixtures.PlacementFixture()).api

        self.api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.admin_api = self.api_fixture.admin_api
        self.admin_api.microversion = 'latest'
        self.api = self.admin_api

        self.start_service('conductor')
        self.start_service('scheduler')

        self.flags(compute_driver='fake.FakeDriverWithPciResources')
        self.useFixture(
            fake.FakeDriverWithPciResources.
                FakeDriverWithPciResourcesConfigFixture())

        self.compute1 = self._start_compute('host1')
        self.compute1_id = self._get_compute_node_id_by_host('host1')
        self.compute1_service_id = self.admin_api.get_services(
            host='host1', binary='nova-compute')[0]['id']

        self.compute2 = self._start_compute('host2')
        self.compute2_id = self._get_compute_node_id_by_host('host2')
        self.compute2_service_id = self.admin_api.get_services(
            host='host2', binary='nova-compute')[0]['id']

        # add extra ports and the related network to the neutron fixture
        # specifically for these tests. It cannot be added globally in the
        # fixture init as it adds a second network that makes auto allocation
        # based test to fail due to ambiguous networks.
        self.neutron._ports[self.neutron.sriov_port['id']] = \
            copy.deepcopy(self.neutron.sriov_port)
        self.neutron._networks[
            self.neutron.network_2['id']] = self.neutron.network_2
        self.neutron._subnets[
            self.neutron.subnet_2['id']] = self.neutron.subnet_2

        self.ctxt = context.get_admin_context()

    def _get_compute_node_id_by_host(self, host):
        # we specifically need the integer id of the node not the UUID so we
        # need to use the old microversion
        with utils.temporary_mutation(self.admin_api, microversion='2.52'):
            hypers = self.admin_api.api_get(
                'os-hypervisors').body['hypervisors']
            for hyper in hypers:
                if hyper['hypervisor_hostname'] == host:
                    return hyper['id']

            self.fail('Hypervisor with hostname=%s not found' % host)

    def _assert_pci_device_allocated(
            self, instance_uuid, compute_node_id, num=1):
        """Assert that a given number of PCI devices are allocated to the
        instance on the given host.
        """

        devices = objects.PciDeviceList.get_by_instance_uuid(
            self.ctxt, instance_uuid)
        devices_on_host = [dev for dev in devices
                           if dev.compute_node_id == compute_node_id]
        self.assertEqual(num, len(devices_on_host))

    def test_evacuate_races_with_update_available_resource(self):
        # Create a server with a direct port to have PCI allocation
        server = self._create_server(
            name='test-server-for-bug-1896463',
            networks=[{'port': self.neutron.sriov_port['id']}],
            host='host1'
        )

        self._assert_pci_device_allocated(server['id'], self.compute1_id)
        self._assert_pci_device_allocated(
            server['id'], self.compute2_id, num=0)

        # stop and force down the compute the instance is on to allow
        # evacuation
        self.compute1.stop()
        self.admin_api.put_service(
            self.compute1_service_id, {'forced_down': 'true'})

        # Inject some sleeps both in the Instance.drop_migration_context and
        # the MigrationList.get_in_progress_and_error code to make them
        # overlap.
        # We want to create the following execution scenario:
        # 1) The evacuation makes a move claim on the dest including the PCI
        #    claim. This means there is a migration context. But the evacuation
        #    is not complete yet so the instance.host does not point to the
        #    dest host.
        # 2) The dest resource tracker starts an _update_available_resource()
        #    periodic task and this task loads the list of instances on its
        #    host from the DB. Our instance is not in this list due to #1.
        # 3) The evacuation finishes, the instance.host is set to the dest host
        #    and the migration context is deleted.
        # 4) The periodic task now loads the list of in-progress migration from
        #    the DB to check for incoming our outgoing migrations. However due
        #    to #3 our instance is not in this list either.
        # 5) The periodic task cleans up every lingering PCI claim that is not
        #    connected to any instance collected above from the instance list
        #    and from the migration list. As our instance is not in either of
        #    the lists, the resource tracker  cleans up the PCI allocation for
        #    the already finished evacuation of our instance.
        #
        # Unfortunately we cannot reproduce the above situation without sleeps.
        # We need that the evac starts first then the periodic starts, but not
        # finishes, then evac finishes, then periodic finishes. If I trigger
        # and run the whole periodic in a wrapper of drop_migration_context
        # then I could not reproduce the situation described at #4). In general
        # it is not
        #
        #   evac
        #    |
        #    |
        #    |     periodic
        #    |        |
        #    |        |
        #    |        x
        #    |
        #    |
        #    x
        #
        # but
        #
        #   evac
        #    |
        #    |
        #    |     periodic
        #    |        |
        #    |        |
        #    |        |
        #    x        |
        #             |
        #             x
        #
        # what is needed need.
        #
        # Starting the periodic from the test in a separate thread at
        # drop_migration_context() might work but that is an extra complexity
        # in the test code. Also it might need a sleep still to make the
        # reproduction stable but only one sleep instead of two.
        orig_drop = objects.Instance.drop_migration_context

        def slow_drop(*args, **kwargs):
            time.sleep(1)
            return orig_drop(*args, **kwargs)

        self.useFixture(
            fixtures.MockPatch(
                'nova.objects.instance.Instance.drop_migration_context',
                new=slow_drop))

        orig_get_mig = objects.MigrationList.get_in_progress_and_error

        def slow_get_mig(*args, **kwargs):
            time.sleep(2)
            return orig_get_mig(*args, **kwargs)

        self.useFixture(
            fixtures.MockPatch(
                'nova.objects.migration.MigrationList.'
                'get_in_progress_and_error',
                new=slow_get_mig))

        self.admin_api.post_server_action(server['id'], {'evacuate': {}})
        # we trigger the _update_available_resource periodic to overlap with
        # the already started evacuation
        self._run_periodics()

        self._wait_for_server_parameter(
            server, {'OS-EXT-SRV-ATTR:host': 'host2', 'status': 'ACTIVE'})

        self._assert_pci_device_allocated(server['id'], self.compute1_id)
        self._assert_pci_device_allocated(server['id'], self.compute2_id)
