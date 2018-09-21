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

import mock

import fixtures
from six.moves import StringIO

from nova.cmd import manage
from nova import config
from nova import context
from nova import objects
from nova import test
from nova.tests.functional import integrated_helpers

CONF = config.CONF


class NovaManageDBIronicTest(test.TestCase):
    def setUp(self):
        super(NovaManageDBIronicTest, self).setUp()
        self.commands = manage.DbCommands()
        self.context = context.RequestContext('fake-user', 'fake-project')

        self.service1 = objects.Service(context=self.context,
                                       host='fake-host1',
                                       binary='nova-compute',
                                       topic='fake-host1',
                                       report_count=1,
                                       disabled=False,
                                       disabled_reason=None,
                                       availability_zone='nova',
                                       forced_down=False)
        self.service1.create()

        self.service2 = objects.Service(context=self.context,
                                       host='fake-host2',
                                       binary='nova-compute',
                                       topic='fake-host2',
                                       report_count=1,
                                       disabled=False,
                                       disabled_reason=None,
                                       availability_zone='nova',
                                       forced_down=False)
        self.service2.create()

        self.service3 = objects.Service(context=self.context,
                                       host='fake-host3',
                                       binary='nova-compute',
                                       topic='fake-host3',
                                       report_count=1,
                                       disabled=False,
                                       disabled_reason=None,
                                       availability_zone='nova',
                                       forced_down=False)
        self.service3.create()

        self.cn1 = objects.ComputeNode(context=self.context,
                                       service_id=self.service1.id,
                                       host='fake-host1',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node1',
                                       cpu_info='{}')
        self.cn1.create()

        self.cn2 = objects.ComputeNode(context=self.context,
                                       service_id=self.service1.id,
                                       host='fake-host1',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node2',
                                       cpu_info='{}')
        self.cn2.create()

        self.cn3 = objects.ComputeNode(context=self.context,
                                       service_id=self.service2.id,
                                       host='fake-host2',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node3',
                                       cpu_info='{}')
        self.cn3.create()

        self.cn4 = objects.ComputeNode(context=self.context,
                                       service_id=self.service3.id,
                                       host='fake-host3',
                                       hypervisor_type='libvirt',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node4',
                                       cpu_info='{}')
        self.cn4.create()

        self.cn5 = objects.ComputeNode(context=self.context,
                                       service_id=self.service2.id,
                                       host='fake-host2',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node5',
                                       cpu_info='{}')
        self.cn5.create()

        self.insts = []
        for cn in (self.cn1, self.cn2, self.cn3, self.cn4, self.cn4, self.cn5):
            flavor = objects.Flavor(extra_specs={})
            inst = objects.Instance(context=self.context,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id,
                                    flavor=flavor,
                                    node=cn.hypervisor_hostname)
            inst.create()
            self.insts.append(inst)

        self.ironic_insts = [i for i in self.insts
                             if i.node != self.cn4.hypervisor_hostname]
        self.virt_insts = [i for i in self.insts
                           if i.node == self.cn4.hypervisor_hostname]

    def test_ironic_flavor_migration_by_host_and_node(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-host1',
                                                    'fake-node2', False, False)
        self.assertEqual(0, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            if inst.node == 'fake-node2':
                self.assertIn(k, inst.flavor.extra_specs)
                self.assertEqual('1', inst.flavor.extra_specs[k])
            else:
                self.assertNotIn(k, inst.flavor.extra_specs)

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_by_host(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-host1', None,
                                                    False, False)
        self.assertEqual(0, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            if inst.node in ('fake-node1', 'fake-node2'):
                self.assertIn(k, inst.flavor.extra_specs)
                self.assertEqual('1', inst.flavor.extra_specs[k])
            else:
                self.assertNotIn(k, inst.flavor.extra_specs)

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_by_host_not_ironic(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-host3', None,
                                                    False, False)
        self.assertEqual(1, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_all_hosts(self):
        ret = self.commands.ironic_flavor_migration('test', None, None,
                                                    True, False)
        self.assertEqual(0, ret)
        k = 'resources:CUSTOM_TEST'

        for inst in self.ironic_insts:
            inst.refresh()
            self.assertIn(k, inst.flavor.extra_specs)
            self.assertEqual('1', inst.flavor.extra_specs[k])

        for inst in self.virt_insts:
            inst.refresh()
            self.assertNotIn(k, inst.flavor.extra_specs)

    def test_ironic_flavor_migration_invalid(self):
        # No host or node and not "all"
        ret = self.commands.ironic_flavor_migration('test', None, None,
                                                    False, False)
        self.assertEqual(3, ret)

        # No host, only node
        ret = self.commands.ironic_flavor_migration('test', None, 'fake-node',
                                                    False, False)
        self.assertEqual(3, ret)

        # Asked for all but provided a node
        ret = self.commands.ironic_flavor_migration('test', None, 'fake-node',
                                                    True, False)
        self.assertEqual(3, ret)

        # Asked for all but provided a host
        ret = self.commands.ironic_flavor_migration('test', 'fake-host', None,
                                                    True, False)
        self.assertEqual(3, ret)

        # Asked for all but provided a host and node
        ret = self.commands.ironic_flavor_migration('test', 'fake-host',
                                                    'fake-node', True, False)
        self.assertEqual(3, ret)

        # Did not provide a resource_class
        ret = self.commands.ironic_flavor_migration(None, 'fake-host',
                                                    'fake-node', False, False)
        self.assertEqual(3, ret)

    def test_ironic_flavor_migration_no_match(self):
        ret = self.commands.ironic_flavor_migration('test', 'fake-nonexist',
                                                    None, False, False)
        self.assertEqual(1, ret)

        ret = self.commands.ironic_flavor_migration('test', 'fake-nonexist',
                                                    'fake-node', False, False)
        self.assertEqual(1, ret)

    def test_ironic_two_instances(self):
        # NOTE(danms): This shouldn't be possible, but simulate it like
        # someone hacked the database, which should also cover any other
        # way this could happen.

        # Since we created two instances on cn4 in setUp() we can convert that
        # to an ironic host and cause the two-instances-on-one-ironic paradox
        # to happen.
        self.cn4.hypervisor_type = 'ironic'
        self.cn4.save()
        ret = self.commands.ironic_flavor_migration('test', 'fake-host3',
                                                    'fake-node4', False, False)
        self.assertEqual(2, ret)


class NovaManageCellV2Test(test.TestCase):
    def setUp(self):
        super(NovaManageCellV2Test, self).setUp()
        self.commands = manage.CellV2Commands()
        self.context = context.RequestContext('fake-user', 'fake-project')

        self.service1 = objects.Service(context=self.context,
                                        host='fake-host1',
                                        binary='nova-compute',
                                        topic='fake-host1',
                                        report_count=1,
                                        disabled=False,
                                        disabled_reason=None,
                                        availability_zone='nova',
                                        forced_down=False)
        self.service1.create()

        self.cn1 = objects.ComputeNode(context=self.context,
                                       service_id=self.service1.id,
                                       host='fake-host1',
                                       hypervisor_type='ironic',
                                       vcpus=1,
                                       memory_mb=1024,
                                       local_gb=10,
                                       vcpus_used=1,
                                       memory_mb_used=1024,
                                       local_gb_used=10,
                                       hypervisor_version=0,
                                       hypervisor_hostname='fake-node1',
                                       cpu_info='{}')
        self.cn1.create()

    def test_delete_host(self):
        cells = objects.CellMappingList.get_all(self.context)

        self.commands.discover_hosts()

        # We should have one mapped node
        cns = objects.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(cns))
        self.assertEqual(1, cns[0].mapped)

        for cell in cells:
            r = self.commands.delete_host(cell.uuid, 'fake-host1')
            if r == 0:
                break

        # Our node should now be unmapped
        cns = objects.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(cns))
        self.assertEqual(0, cns[0].mapped)

    def test_delete_cell_force_unmaps_computes(self):
        cells = objects.CellMappingList.get_all(self.context)

        self.commands.discover_hosts()

        # We should have one host mapping
        hms = objects.HostMappingList.get_all(self.context)
        self.assertEqual(1, len(hms))

        # We should have one mapped node
        cns = objects.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(cns))
        self.assertEqual(1, cns[0].mapped)

        for cell in cells:
            res = self.commands.delete_cell(cell.uuid, force=True)
            self.assertEqual(0, res)

        # The host mapping should be deleted since the force option is used
        hms = objects.HostMappingList.get_all(self.context)
        self.assertEqual(0, len(hms))

        # All our cells should be deleted
        cells = objects.CellMappingList.get_all(self.context)
        self.assertEqual(0, len(cells))

        # Our node should now be unmapped
        cns = objects.ComputeNodeList.get_all(self.context)
        self.assertEqual(1, len(cns))
        self.assertEqual(0, cns[0].mapped)


class TestNovaManagePlacementHealAllocations(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Functional tests for nova-manage placement heal_allocations"""

    # This is required by the parent class.
    compute_driver = 'fake.SmallFakeDriver'
    # We want to test iterating across multiple cells.
    NUMBER_OF_CELLS = 2

    def setUp(self):
        # Since the CachingScheduler does not use Placement, we want to use
        # the CachingScheduler to create instances and then we can heal their
        # allocations via the CLI.
        self.flags(driver='caching_scheduler', group='scheduler')
        super(TestNovaManagePlacementHealAllocations, self).setUp()
        self.cli = manage.PlacementCommands()
        # We need to start a compute in each non-cell0 cell.
        for cell_name, cell_mapping in self.cell_mappings.items():
            if cell_mapping.uuid == objects.CellMapping.CELL0_UUID:
                continue
            self._start_compute(cell_name, cell_name=cell_name)
        # Make sure we have two hypervisors reported in the API.
        hypervisors = self.admin_api.api_get(
            '/os-hypervisors').body['hypervisors']
        self.assertEqual(2, len(hypervisors))
        self.flavor = self.api.get_flavors()[0]
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        # On startup, the CachingScheduler runs a periodic task to pull the
        # initial set of compute nodes out of the database which it then puts
        # into a cache (hence the name of the driver). This can race with
        # actually starting the compute services so we need to restart the
        # scheduler to refresh the cache.
        self.scheduler_service.stop()
        self.scheduler_service.manager.driver.all_host_states = None
        self.scheduler_service.start()

    def _boot_and_assert_no_allocations(self, flavor, hostname):
        """Creates a server on the given host and asserts neither have usage

        :param flavor: the flavor used to create the server
        :param hostname: the host on which to create the server
        :returns: two-item tuple of the server and the compute node resource
                  provider uuid
        """
        server_req = self._build_minimal_create_server_request(
            self.api, 'some-server', flavor_id=flavor['id'],
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')
        server_req['availability_zone'] = 'nova:%s' % hostname
        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(
            self.admin_api, created_server, 'ACTIVE')

        # Verify that our source host is what the server ended up on
        self.assertEqual(hostname, server['OS-EXT-SRV-ATTR:host'])

        # Check that the compute node resource provider has no allocations.
        rp_uuid = self._get_provider_uuid_by_host(hostname)
        provider_usages = self._get_provider_usages(rp_uuid)
        for resource_class, usage in provider_usages.items():
            self.assertEqual(
                0, usage,
                'Compute node resource provider %s should not have %s '
                'usage when using the CachingScheduler.' %
                (hostname, resource_class))

        # Check that the server has no allocations.
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual({}, allocations,
                         'Server should not have allocations when using '
                         'the CachingScheduler.')
        return server, rp_uuid

    def _assert_healed(self, server, rp_uuid):
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertIn(rp_uuid, allocations,
                      'Allocations not found for server %s and compute node '
                      'resource provider. %s\nOutput:%s' %
                      (server['id'], rp_uuid, self.output.getvalue()))
        self.assertFlavorMatchesAllocation(
            self.flavor, allocations[rp_uuid]['resources'])

    def test_heal_allocations_paging(self):
        """This test runs the following scenario:

        * Schedule server1 to cell1 and assert it doesn't have allocations.
        * Schedule server2 to cell2 and assert it doesn't have allocations.
        * Run "nova-manage placement heal_allocations --max-count 1" to make
          sure we stop with just one instance and the return code is 1.
        * Run "nova-manage placement heal_allocations" and assert both
          both instances now have allocations against their respective compute
          node resource providers.
        """
        server1, rp_uuid1 = self._boot_and_assert_no_allocations(
            self.flavor, 'cell1')
        server2, rp_uuid2 = self._boot_and_assert_no_allocations(
            self.flavor, 'cell2')

        # heal server1 and server2 in separate calls
        for x in range(2):
            result = self.cli.heal_allocations(max_count=1, verbose=True)
            self.assertEqual(1, result, self.output.getvalue())
            output = self.output.getvalue()
            self.assertIn('Max count reached. Processed 1 instances.', output)
            # If this is the 2nd call, we'll have skipped the first instance.
            if x == 0:
                self.assertNotIn('already has allocations', output)
            else:
                self.assertIn('already has allocations', output)

        self._assert_healed(server1, rp_uuid1)
        self._assert_healed(server2, rp_uuid2)

        # run it again to make sure nothing was processed
        result = self.cli.heal_allocations(verbose=True)
        self.assertEqual(4, result, self.output.getvalue())
        self.assertIn('already has allocations', self.output.getvalue())

    def test_heal_allocations_paging_max_count_more_than_num_instances(self):
        """Sets up 2 instances in cell1 and 1 instance in cell2. Then specify
        --max-count=10, processes 3 instances, rc is 0
        """
        servers = []  # This is really a list of 2-item tuples.
        for x in range(2):
            servers.append(
                self._boot_and_assert_no_allocations(self.flavor, 'cell1'))
        servers.append(
            self._boot_and_assert_no_allocations(self.flavor, 'cell2'))
        result = self.cli.heal_allocations(max_count=10, verbose=True)
        self.assertEqual(0, result, self.output.getvalue())
        self.assertIn('Processed 3 instances.', self.output.getvalue())
        for server, rp_uuid in servers:
            self._assert_healed(server, rp_uuid)

    def test_heal_allocations_paging_more_instances_remain(self):
        """Tests that there is one instance in cell1 and two instances in
        cell2, with a --max-count=2. This tests that we stop in cell2 once
        max_count is reached.
        """
        servers = []  # This is really a list of 2-item tuples.
        servers.append(
            self._boot_and_assert_no_allocations(self.flavor, 'cell1'))
        for x in range(2):
            servers.append(
                self._boot_and_assert_no_allocations(self.flavor, 'cell2'))
        result = self.cli.heal_allocations(max_count=2, verbose=True)
        self.assertEqual(1, result, self.output.getvalue())
        self.assertIn('Max count reached. Processed 2 instances.',
                      self.output.getvalue())
        # Assert that allocations were healed on the instances we expect. Order
        # works here because cell mappings are retrieved by id in ascending
        # order so oldest to newest, and instances are also retrieved from each
        # cell by created_at in ascending order, which matches the order we put
        # created servers in our list.
        for x in range(2):
            self._assert_healed(*servers[x])
        # And assert the remaining instance does not have allocations.
        allocations = self._get_allocations_by_server_uuid(
            servers[2][0]['id'])
        self.assertEqual({}, allocations)

    def test_heal_allocations_unlimited(self):
        """Sets up 2 instances in cell1 and 1 instance in cell2. Then
        don't specify --max-count, processes 3 instances, rc is 0.
        """
        servers = []  # This is really a list of 2-item tuples.
        for x in range(2):
            servers.append(
                self._boot_and_assert_no_allocations(self.flavor, 'cell1'))
        servers.append(
            self._boot_and_assert_no_allocations(self.flavor, 'cell2'))
        result = self.cli.heal_allocations(verbose=True)
        self.assertEqual(0, result, self.output.getvalue())
        self.assertIn('Processed 3 instances.', self.output.getvalue())
        for server, rp_uuid in servers:
            self._assert_healed(server, rp_uuid)

    def test_heal_allocations_shelved(self):
        """Tests the scenario that an instance with no allocations is shelved
        so heal_allocations skips it (since the instance is not on a host).
        """
        server, rp_uuid = self._boot_and_assert_no_allocations(
            self.flavor, 'cell1')
        self.api.post_server_action(server['id'], {'shelve': None})
        # The server status goes to SHELVED_OFFLOADED before the host/node
        # is nulled out in the compute service, so we also have to wait for
        # that so we don't race when we run heal_allocations.
        server = self._wait_for_server_parameter(
            self.admin_api, server,
            {'OS-EXT-SRV-ATTR:host': None, 'status': 'SHELVED_OFFLOADED'})
        result = self.cli.heal_allocations(verbose=True)
        self.assertEqual(4, result, self.output.getvalue())
        self.assertIn('Instance %s is not on a host.' % server['id'],
                      self.output.getvalue())
        # Check that the server has no allocations.
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual({}, allocations,
                         'Shelved-offloaded server should not have '
                         'allocations.')

    def test_heal_allocations_task_in_progress(self):
        """Tests the case that heal_allocations skips over an instance which
        is undergoing a task state transition (in this case pausing).
        """
        server, rp_uuid = self._boot_and_assert_no_allocations(
            self.flavor, 'cell1')

        def fake_pause_instance(_self, ctxt, instance, *a, **kw):
            self.assertEqual('pausing', instance.task_state)
        # We have to stub out pause_instance so that the instance is stuck with
        # task_state != None.
        self.stub_out('nova.compute.manager.ComputeManager.pause_instance',
                      fake_pause_instance)
        self.api.post_server_action(server['id'], {'pause': None})
        result = self.cli.heal_allocations(verbose=True)
        self.assertEqual(4, result, self.output.getvalue())
        # Check that the server has no allocations.
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual({}, allocations,
                         'Server undergoing task state transition should '
                         'not have allocations.')
        # Assert something was logged for this instance when it was skipped.
        self.assertIn('Instance %s is undergoing a task state transition: '
                      'pausing' % server['id'], self.output.getvalue())

    def test_heal_allocations_ignore_deleted_server(self):
        """Creates two servers, deletes one, and then runs heal_allocations
        to make sure deleted servers are filtered out.
        """
        # Create a server that we'll leave alive
        self._boot_and_assert_no_allocations(self.flavor, 'cell1')
        # and another that we'll delete
        server, _ = self._boot_and_assert_no_allocations(self.flavor, 'cell1')
        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)
        result = self.cli.heal_allocations(verbose=True)
        self.assertEqual(0, result, self.output.getvalue())
        self.assertIn('Processed 1 instances.', self.output.getvalue())

    def test_heal_allocations_update_sentinel_consumer(self):
        """Tests the scenario that allocations were created before microversion
        1.8 when consumer (project_id and user_id) were not required so the
        consumer information is using sentinel values from config.

        Since the CachingScheduler used in this test class won't actually
        create allocations during scheduling, we have to create the allocations
        out-of-band and then run our heal routine to see they get updated with
        the instance project and user information.
        """
        server, rp_uuid = self._boot_and_assert_no_allocations(
            self.flavor, 'cell1')
        # Now we'll create allocations using microversion < 1.8 to so that
        # placement creates the consumer record with the config-based project
        # and user values.
        alloc_body = {
            "allocations": [
                {
                    "resource_provider": {
                        "uuid": rp_uuid
                    },
                    "resources": {
                        "MEMORY_MB": self.flavor['ram'],
                        "VCPU": self.flavor['vcpus'],
                        "DISK_GB": self.flavor['disk']
                    }
                }
            ]
        }
        self.placement_api.put('/allocations/%s' % server['id'], alloc_body)
        # Make sure we did that correctly. Use version 1.12 so we can assert
        # the project_id and user_id are based on the sentinel values.
        allocations = self.placement_api.get(
            '/allocations/%s' % server['id'], version='1.12').body
        self.assertEqual(CONF.placement.incomplete_consumer_project_id,
                         allocations['project_id'])
        self.assertEqual(CONF.placement.incomplete_consumer_user_id,
                         allocations['user_id'])
        allocations = allocations['allocations']
        self.assertIn(rp_uuid, allocations)
        self.assertFlavorMatchesAllocation(
            self.flavor, allocations[rp_uuid]['resources'])
        # Now run heal_allocations which should update the consumer info.
        result = self.cli.heal_allocations(verbose=True)
        self.assertEqual(0, result, self.output.getvalue())
        output = self.output.getvalue()
        self.assertIn('Successfully updated allocations for instance', output)
        self.assertIn('Processed 1 instances.', output)
        # Now assert that the consumer was actually updated.
        allocations = self.placement_api.get(
            '/allocations/%s' % server['id'], version='1.12').body
        self.assertEqual(server['tenant_id'], allocations['project_id'])
        self.assertEqual(server['user_id'], allocations['user_id'])


class TestNovaManagePlacementSyncAggregates(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Functional tests for nova-manage placement sync_aggregates"""

    # This is required by the parent class.
    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(TestNovaManagePlacementSyncAggregates, self).setUp()
        self.cli = manage.PlacementCommands()
        # Start two computes. At least two computes are useful for testing
        # to make sure removing one from an aggregate doesn't remove the other.
        self._start_compute('host1')
        self._start_compute('host2')
        # Make sure we have two hypervisors reported in the API.
        hypervisors = self.admin_api.api_get(
            '/os-hypervisors').body['hypervisors']
        self.assertEqual(2, len(hypervisors))
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))

    def _create_aggregate(self, name):
        return self.admin_api.post_aggregate({'aggregate': {'name': name}})

    def test_sync_aggregates(self):
        """This is a simple test which does the following:

        - add each host to a unique aggregate
        - add both hosts to a shared aggregate
        - run sync_aggregates and assert both providers are in two aggregates
        - run sync_aggregates again and make sure nothing changed
        """
        # create three aggregates, one per host and one shared
        host1_agg = self._create_aggregate('host1')
        host2_agg = self._create_aggregate('host2')
        shared_agg = self._create_aggregate('shared')

        # Add the hosts to the aggregates. We have to temporarily mock out the
        # scheduler report client to *not* mirror the add host changes so that
        # sync_aggregates will do the job.
        with mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                        'aggregate_add_host'):
            self.admin_api.add_host_to_aggregate(host1_agg['id'], 'host1')
            self.admin_api.add_host_to_aggregate(host2_agg['id'], 'host2')
            self.admin_api.add_host_to_aggregate(shared_agg['id'], 'host1')
            self.admin_api.add_host_to_aggregate(shared_agg['id'], 'host2')

        # Run sync_aggregates and assert both providers are in two aggregates.
        result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(0, result, self.output.getvalue())

        host_to_rp_uuid = {}
        for host in ('host1', 'host2'):
            rp_uuid = self._get_provider_uuid_by_host(host)
            host_to_rp_uuid[host] = rp_uuid
            rp_aggregates = self._get_provider_aggregates(rp_uuid)
            self.assertEqual(2, len(rp_aggregates),
                             '%s should be in two provider aggregates' % host)
            self.assertIn(
                'Successfully added host (%s) and provider (%s) to aggregate '
                '(%s)' % (host, rp_uuid, shared_agg['uuid']),
                self.output.getvalue())

        # Remove host1 from the shared aggregate. Again, we have to temporarily
        # mock out the call from the aggregates API to placement to mirror the
        # change.
        with mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                        'aggregate_remove_host'):
            self.admin_api.remove_host_from_aggregate(
                shared_agg['id'], 'host1')

        # Run sync_aggregates and assert the provider for host1 is still in two
        # aggregates and host2's provider is still in two aggregates.
        # TODO(mriedem): When we add an option to remove providers from
        # placement aggregates when the corresponding host isn't in a compute
        # aggregate, we can test that the host1 provider is only left in one
        # aggregate.
        result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(0, result, self.output.getvalue())
        for host in ('host1', 'host2'):
            rp_uuid = host_to_rp_uuid[host]
            rp_aggregates = self._get_provider_aggregates(rp_uuid)
            self.assertEqual(2, len(rp_aggregates),
                             '%s should be in two provider aggregates' % host)


class TestDBArchiveDeletedRows(integrated_helpers._IntegratedTestBase):
    """Functional tests for the "nova-manage db archive_deleted_rows" CLI."""
    USE_NEUTRON = True
    api_major_version = 'v2.1'
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'

    def setUp(self):
        super(TestDBArchiveDeletedRows, self).setUp()
        self.cli = manage.DbCommands()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))

    def test_archive_instance_group_members(self):
        """Tests that instance_group_member records in the API DB are deleted
        when a server group member instance is archived.
        """
        # Create a server group.
        group = self.api.post_server_groups(
            {'name': 'test_archive_instance_group_members',
             'policies': ['affinity']})
        # Create two servers in the group.
        server = self._build_minimal_create_server_request()
        server['min_count'] = 2
        server_req = {
            'server': server, 'os:scheduler_hints': {'group': group['id']}}
        # Since we don't pass return_reservation_id=True we get the first
        # server back in the response. We're also using the CastAsCall fixture
        # (from the base class) fixture so we don't have to worry about the
        # server being ACTIVE.
        server = self.api.post_server(server_req)
        # Assert we have two group members.
        self.assertEqual(
            2, len(self.api.get_server_group(group['id'])['members']))
        # Now delete one server and then we can archive.
        server = self.api.get_server(server['id'])
        self.api.delete_server(server['id'])
        helper = integrated_helpers.InstanceHelperMixin()
        helper.api = self.api
        helper._wait_until_deleted(server)
        # Now archive.
        self.cli.archive_deleted_rows(verbose=True)
        # Assert only one instance_group_member record was deleted.
        self.assertRegexpMatches(self.output.getvalue(),
                                 ".*instance_group_member.*\| 1.*")
        # And that we still have one remaining group member.
        self.assertEqual(
            1, len(self.api.get_server_group(group['id'])['members']))
