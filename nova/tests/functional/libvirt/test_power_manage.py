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

import fixtures

from unittest import mock

from nova import context as nova_context
from nova import exception
from nova import objects
from nova.tests import fixtures as nova_fixtures
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import base
from nova.virt import hardware
from nova.virt.libvirt.cpu import api as cpu_api


class PowerManagementTestsBase(base.ServersTestBase):

    ADDITIONAL_FILTERS = ['NUMATopologyFilter']

    ADMIN_API = True

    def setUp(self):
        super(PowerManagementTestsBase, self).setUp()

        self.ctxt = nova_context.get_admin_context()

        # Mock the 'NUMATopologyFilter' filter, as most tests need to inspect
        # this
        host_manager = self.scheduler.manager.host_manager
        numa_filter_class = host_manager.filter_cls_map['NUMATopologyFilter']
        host_pass_mock = mock.Mock(wraps=numa_filter_class().host_passes)
        _p = mock.patch('nova.scheduler.filters'
                        '.numa_topology_filter.NUMATopologyFilter.host_passes',
                        side_effect=host_pass_mock)
        self.mock_filter = _p.start()
        self.addCleanup(_p.stop)

        # for the sake of resizing, we need to patch the two methods below
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_instance_disk_info',
             return_value=[]))
        self.useFixture(fixtures.MockPatch('os.rename'))

        self.useFixture(nova_fixtures.PrivsepFixture())

        # Defining the main flavor for 4 vCPUs all pinned
        self.extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
        }
        self.isolate_extra_spec = {
            'hw:cpu_policy': 'dedicated',
            'hw:cpu_thread_policy': 'prefer',
            'hw:emulator_threads_policy': 'isolate',
        }
        self.pcpu_flavor_id = self._create_flavor(
            vcpu=4, extra_spec=self.extra_spec)
        self.isolate_flavor_id = self._create_flavor(
            vcpu=4, extra_spec=self.isolate_extra_spec)

    def _assert_server_cpus_state(self, server, expected='online'):
        inst = objects.Instance.get_by_uuid(self.ctxt, server['id'])
        if not inst.numa_topology:
            self.fail('Instance should have a NUMA topology in order to know '
                      'its physical CPUs')
        instance_pcpus = inst.numa_topology.cpu_pinning
        self._assert_cpu_set_state(instance_pcpus, expected=expected)
        return instance_pcpus

    def _assert_cpu_set_state(self, cpu_set, expected='online'):
        for i in cpu_set:
            core = cpu_api.Core(i)
            if expected == 'online':
                self.assertTrue(core.online, f'{i} is not online')
            elif expected == 'offline':
                self.assertFalse(core.online, f'{i} is online')
            elif expected == 'powersave':
                self.assertEqual('powersave', core.governor)
            elif expected == 'performance':
                self.assertEqual('performance', core.governor)


class FakeCore(object):

    def __init__(self, i):
        self.ident = i
        self.power_state = 'online'

    @property
    def online(self):
        return self.power_state == 'online'

    @online.setter
    def online(self, state):
        if state:
            self.power_state = 'online'
        else:
            self.power_state = 'offline'


class CoresStub(object):

    def __init__(self):
        self.cores = {}

    def __call__(self, i):
        if i not in self.cores:
            self.cores[i] = FakeCore(i)
        return self.cores[i]


class PowerManagementLiveMigrationTestsBase(base.LibvirtMigrationMixin,
                                            PowerManagementTestsBase):

    def setUp(self):
        super().setUp()

        self.useFixture(nova_fixtures.SysFileSystemFixture())
        self.flags(cpu_dedicated_set='1-9', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)
        self.flags(cpu_power_management=True, group='libvirt')

        # NOTE(artom) Fill up all dedicated CPUs (either with only the
        # instance's CPUs, or instance CPUs + 1 emulator thread). This makes
        # the assertions further down easier.
        self.pcpu_flavor_id = self._create_flavor(
            vcpu=9, extra_spec=self.extra_spec)
        self.isolate_flavor_id = self._create_flavor(
            vcpu=8, extra_spec=self.isolate_extra_spec)

        self.start_compute(
            host_info=fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                           cpu_cores=5, cpu_threads=2),
            hostname='src')
        self.src = self.computes['src']
        self.src.driver.cpu_api.core = CoresStub()
        # NOTE(artom) In init_host() the libvirt driver calls
        # power_down_all_dedicated_cpus(). Call it again now after swapping to
        # our stub to fake reality.
        self.src.driver.cpu_api.power_down_all_dedicated_cpus()

        self.start_compute(
            host_info=fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                           cpu_cores=5, cpu_threads=2),
            hostname='dest')
        self.dest = self.computes['dest']
        self.dest.driver.cpu_api.power_down_all_dedicated_cpus()

    def assert_cores(self, host, cores, online=True):
        for i in cores:
            self.assertEqual(online, host.driver.cpu_api.core(i).online)


class PowerManagementLiveMigrationTests(PowerManagementLiveMigrationTestsBase):

    def test_live_migrate_server(self):
        self.server = self._create_server(
            flavor_id=self.pcpu_flavor_id,
            expected_state='ACTIVE', host='src')
        server = self._live_migrate(self.server)
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        # We've powered down the source cores, and powered up the destination
        # ones.
        self.assert_cores(self.src, range(1, 10), online=False)
        self.assert_cores(self.dest, range(1, 10), online=True)

    def test_live_migrate_server_with_emulator_threads_isolate(self):
        self.server = self._create_server(
            flavor_id=self.isolate_flavor_id,
            expected_state='ACTIVE', host='src')
        server = self._live_migrate(self.server)
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        # We're using a flavor with 8 CPUs, but with the extra dedicated CPU
        # for the emulator threads, we expect all 9 cores to be powered up on
        # the dest, and down on the source.
        self.assert_cores(self.src, range(1, 10), online=False)
        self.assert_cores(self.dest, range(1, 10), online=True)


class PowerManagementLiveMigrationRollbackTests(
    PowerManagementLiveMigrationTestsBase):

    def _migrate_stub(self, domain, destination, params, flags):
        conn = self.src.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        dom.fail_job()

    def test_live_migrate_server_rollback(self):
        self.server = self._create_server(
            flavor_id=self.pcpu_flavor_id,
            expected_state='ACTIVE', host='src')
        server = self._live_migrate(self.server,
                                    migration_expected_state='failed')
        self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])
        self.assert_cores(self.src, range(1, 10), online=True)
        self.assert_cores(self.dest, range(1, 10), online=False)

    def test_live_migrate_server_with_emulator_threads_isolate_rollback(self):
        self.server = self._create_server(
            flavor_id=self.isolate_flavor_id,
            expected_state='ACTIVE', host='src')
        server = self._live_migrate(self.server,
                                    migration_expected_state='failed')
        self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])
        # We're using a flavor with 8 CPUs, but with the extra dedicated CPU
        # for the emulator threads, we expect all 9 cores to be powered back
        # down on the dest, and up on the source.
        self.assert_cores(self.src, range(1, 10), online=True)
        self.assert_cores(self.dest, range(1, 10), online=False)


class PowerManagementTests(PowerManagementTestsBase):
    """Test suite for a single host with 9 dedicated cores and 1 used for OS"""

    def setUp(self):
        super(PowerManagementTests, self).setUp()

        self.useFixture(nova_fixtures.SysFileSystemFixture())

        # Defining the CPUs to be pinned.
        self.flags(cpu_dedicated_set='1-9', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)
        self.flags(cpu_power_management=True, group='libvirt')

        self.flags(allow_resize_to_same_host=True)
        self.host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=5, cpu_threads=2)
        self.compute1 = self.start_compute(host_info=self.host_info,
                                           hostname='compute1')
        # All cores are shutdown at startup, let's check.
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        self._assert_cpu_set_state(cpu_dedicated_set, expected='offline')

    def test_compute_service_starts_with_power_management_and_zero_pcpu(self):
        self.flags(cpu_dedicated_set=None, cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)
        self.flags(cpu_power_management=True, group='libvirt')
        self.start_compute(host_info=self.host_info, hostname='compute2')
        # NOTE(gibi): we test that no exception is raised by start_compute

    def test_create_server(self):
        server = self._create_server(
            flavor_id=self.pcpu_flavor_id,
            expected_state='ACTIVE')
        # Let's verify that the pinned CPUs are now online
        self._assert_server_cpus_state(server, expected='online')

        # Verify that the unused CPUs are still offline
        inst = objects.Instance.get_by_uuid(self.ctxt, server['id'])
        instance_pcpus = inst.numa_topology.cpu_pinning
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        unused_cpus = cpu_dedicated_set - instance_pcpus
        self._assert_cpu_set_state(unused_cpus, expected='offline')
        return server

    def test_delete_server(self):
        server = self.test_create_server()
        self._delete_server(server)
        # Let's verify that the pinned CPUs are now offline
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        self._assert_cpu_set_state(cpu_dedicated_set, expected='offline')

    def test_delete_server_device_busy(self):
        # This test verifies bug 2065927 is resolved.
        server = self.test_create_server()
        inst = objects.Instance.get_by_uuid(self.ctxt, server['id'])
        instance_pcpus = inst.numa_topology.cpu_pinning
        self._assert_cpu_set_state(instance_pcpus, expected='online')
        with mock.patch(
            'nova.filesystem.write_sys.__wrapped__',
            side_effect=[
                exception.DeviceBusy(file_path='fake'),
                None]):

            self._delete_server(server)
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        # Verify that the unused CPUs are still offline
        unused_cpus = cpu_dedicated_set - instance_pcpus
        self._assert_cpu_set_state(unused_cpus, expected='offline')
        # and the pinned CPUs are offline
        self._assert_cpu_set_state(instance_pcpus, expected='offline')

    def test_create_server_with_emulator_threads_isolate(self):
        server = self._create_server(
            flavor_id=self.isolate_flavor_id,
            expected_state='ACTIVE')
        # Let's verify that the pinned CPUs are now online
        self._assert_server_cpus_state(server, expected='online')
        instance = objects.Instance.get_by_uuid(self.ctxt, server['id'])
        numa_topology = instance.numa_topology
        # Make sure we've pinned the emulator threads to a separate core
        self.assertTrue(numa_topology.cpuset_reserved)
        self.assertTrue(
            numa_topology.cpu_pinning.isdisjoint(
                numa_topology.cpuset_reserved))
        self._assert_cpu_set_state(numa_topology.cpuset_reserved,
                                   expected='online')

    def test_start_stop_server_with_emulator_threads_isolate(self):
        server = self._create_server(
            flavor_id=self.isolate_flavor_id,
            expected_state='ACTIVE')
        # Let's verify that the pinned CPUs are now online
        self._assert_server_cpus_state(server, expected='online')
        instance = objects.Instance.get_by_uuid(self.ctxt, server['id'])
        numa_topology = instance.numa_topology
        # Make sure we've pinned the emulator threads to a separate core
        self.assertTrue(numa_topology.cpuset_reserved)
        self.assertTrue(
            numa_topology.cpu_pinning.isdisjoint(
                numa_topology.cpuset_reserved))
        self._assert_cpu_set_state(numa_topology.cpuset_reserved,
                                   expected='online')
        # Stop and assert we've powered down the emulator threads core as well
        server = self._stop_server(server)
        self._assert_cpu_set_state(numa_topology.cpuset_reserved,
                                   expected='offline')

    def test_stop_start_server(self):
        server = self._create_server(
            flavor_id=self.pcpu_flavor_id,
            expected_state='ACTIVE')

        server = self._stop_server(server)
        # Let's verify that the pinned CPUs are now stopped...
        self._assert_server_cpus_state(server, expected='offline')

        server = self._start_server(server)
        # ...and now, they should be back.
        self._assert_server_cpus_state(server, expected='online')

    def test_resize(self):
        server = self._create_server(
            flavor_id=self.pcpu_flavor_id,
            expected_state='ACTIVE')
        server_pcpus = self._assert_server_cpus_state(server,
                                                      expected='online')

        new_flavor_id = self._create_flavor(
            vcpu=5, extra_spec=self.extra_spec)
        self._resize_server(server, new_flavor_id)
        server2_pcpus = self._assert_server_cpus_state(server,
                                                       expected='online')
        # Even if the resize is not confirmed yet, the original guest is now
        # destroyed so the cores are now offline.
        self._assert_cpu_set_state(server_pcpus, expected='offline')

        # let's revert the resize
        self._revert_resize(server)
        # So now the original CPUs will be online again, while the previous
        # cores should be back offline.
        self._assert_cpu_set_state(server_pcpus, expected='online')
        self._assert_cpu_set_state(server2_pcpus, expected='offline')

    def test_changing_strategy_fails(self):
        # As a reminder, all cores have been shutdown before.
        # Now we want to change the strategy and then we restart the service
        self.flags(cpu_power_management_strategy='governor', group='libvirt')
        # See, this is not possible as we would have offline CPUs.
        self.assertRaises(exception.InvalidConfiguration,
                          self.restart_compute_service, hostname='compute1')


class PowerManagementTestsGovernor(PowerManagementTestsBase):
    """Test suite for speific governor usage (same 10-core host)"""

    def setUp(self):
        super(PowerManagementTestsGovernor, self).setUp()

        self.useFixture(nova_fixtures.SysFileSystemFixture())

        # Defining the CPUs to be pinned.
        self.flags(cpu_dedicated_set='1-9', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_power_management_strategy='governor', group='libvirt')

        self.flags(allow_resize_to_same_host=True)
        self.host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=5, cpu_threads=2)
        self.compute1 = self.start_compute(host_info=self.host_info,
                                           hostname='compute1')

    def test_create(self):
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        # With the governor strategy, cores are still online but run with a
        # powersave governor.
        self._assert_cpu_set_state(cpu_dedicated_set, expected='powersave')

        # Now, start an instance
        server = self._create_server(
            flavor_id=self.pcpu_flavor_id,
            expected_state='ACTIVE')
        # When pinned cores are run, the governor state is now performance
        self._assert_server_cpus_state(server, expected='performance')

    def test_changing_strategy_fails(self):
        # Arbitratly set a core governor strategy to be performance
        cpu_api.Core(1).set_high_governor()
        # and then forget about it while changing the strategy.
        self.flags(cpu_power_management_strategy='cpu_state', group='libvirt')
        # This time, this wouldn't be acceptable as some core would have a
        # difference performance while Nova would only online/offline it.
        self.assertRaises(exception.InvalidConfiguration,
                          self.restart_compute_service, hostname='compute1')


class PowerManagementTestsGovernorNotSupported(PowerManagementTestsBase):
    """Test suite for OS without governor support usage (same 10-core host)"""

    def setUp(self):
        super(PowerManagementTestsGovernorNotSupported, self).setUp()

        self.useFixture(nova_fixtures.SysFileSystemFixture(
            cpufreq_enabled=False))

        # Defining the CPUs to be pinned.
        self.flags(cpu_dedicated_set='1-9', cpu_shared_set=None,
                   group='compute')
        self.flags(vcpu_pin_set=None)
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_power_management_strategy='cpu_state', group='libvirt')

        self.flags(allow_resize_to_same_host=True)
        self.host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                              cpu_cores=5, cpu_threads=2)

    def test_enabling_governor_strategy_fails(self):
        self.flags(cpu_power_management_strategy='governor', group='libvirt')
        self.assertRaises(exception.FileNotFound, self.start_compute,
                          host_info=self.host_info, hostname='compute1')

    def test_enabling_cpu_state_strategy_works(self):
        self.flags(cpu_power_management_strategy='cpu_state', group='libvirt')
        self.compute1 = self.start_compute(host_info=self.host_info,
                                           hostname='compute1')
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        self._assert_cpu_set_state(cpu_dedicated_set, expected='offline')


class PowerManagementMixedInstances(PowerManagementTestsBase):
    """Test suite for a single host with 6 dedicated cores, 3 shared and one
    OS-restricted.
    """

    def setUp(self):
        super(PowerManagementMixedInstances, self).setUp()

        self.useFixture(nova_fixtures.SysFileSystemFixture())

        # Defining 6 CPUs to be dedicated, not all of them in a series.
        self.flags(cpu_dedicated_set='1-3,5-7', cpu_shared_set='4,8-9',
                   group='compute')
        self.flags(vcpu_pin_set=None)
        self.flags(cpu_power_management=True, group='libvirt')

        self.host_info = fakelibvirt.HostInfo(cpu_nodes=1, cpu_sockets=1,
                                         cpu_cores=5, cpu_threads=2)
        self.compute1 = self.start_compute(host_info=self.host_info,
                                           hostname='compute1')

        # Make sure only 6 are offline now
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        self._assert_cpu_set_state(cpu_dedicated_set, expected='offline')

        # cores 4 and 8-9 should be online
        self._assert_cpu_set_state({4, 8, 9}, expected='online')

    def test_standard_server_works_and_passes(self):

        std_flavor_id = self._create_flavor(vcpu=2)
        self._create_server(flavor_id=std_flavor_id, expected_state='ACTIVE')

        # Since this is an instance with floating vCPUs on the shared set, we
        # can only lookup the host CPUs and see they haven't changed state.
        cpu_dedicated_set = hardware.get_cpu_dedicated_set()
        self._assert_cpu_set_state(cpu_dedicated_set, expected='offline')
        self._assert_cpu_set_state({4, 8, 9}, expected='online')

        # We can now try to boot an instance with pinned CPUs to test the mix
        pinned_server = self._create_server(
            flavor_id=self.pcpu_flavor_id,
            expected_state='ACTIVE')
        # We'll see that its CPUs are now online
        self._assert_server_cpus_state(pinned_server, expected='online')
        # but it doesn't change the shared set
        self._assert_cpu_set_state({4, 8, 9}, expected='online')
