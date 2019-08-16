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


import mock
import os_traits

from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context
from nova import exception
from nova.tests.functional import integrated_helpers
from nova.virt import fake


LOG = logging.getLogger(__name__)


class ProviderTreeTests(integrated_helpers.ProviderUsageBaseTestCase):
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(ProviderTreeTests, self).setUp()
        # Before starting compute, placement has no providers registered
        self.assertEqual([], self._get_all_providers())

        # Start compute without mocking update_provider_tree. The fake driver
        # doesn't implement the method, so this will cause us to start with the
        # legacy get_available_resource()-based inventory discovery and
        # boostrapping of placement data.
        self.compute = self._start_compute(host='host1')

        # Mock out update_provider_tree *after* starting compute with the
        # (unmocked, default, unimplemented) version from the fake driver.
        _p = mock.patch.object(fake.MediumFakeDriver, 'update_provider_tree')
        self.addCleanup(_p.stop)
        self.mock_upt = _p.start()

        # The compute host should have been created in placement with
        # appropriate inventory and no traits
        rps = self._get_all_providers()
        self.assertEqual(1, len(rps))
        self.assertEqual(self.compute.host, rps[0]['name'])
        self.host_uuid = self._get_provider_uuid_by_host(self.compute.host)
        self.assertEqual({
            'DISK_GB': {
                'total': 1028,
                'allocation_ratio': 1.0,
                'max_unit': 1028,
                'min_unit': 1,
                'reserved': 0,
                'step_size': 1,
            },
            'MEMORY_MB': {
                'total': 8192,
                'allocation_ratio': 1.5,
                'max_unit': 8192,
                'min_unit': 1,
                'reserved': 512,
                'step_size': 1,
            },
            'VCPU': {
                'total': 10,
                'allocation_ratio': 16.0,
                'max_unit': 10,
                'min_unit': 1,
                'reserved': 0,
                'step_size': 1,
            },
        }, self._get_provider_inventory(self.host_uuid))
        self.expected_compute_node_traits = (
            self.expected_fake_driver_capability_traits.union(
                # The COMPUTE_NODE trait is always added
                [os_traits.COMPUTE_NODE]))
        self.assertItemsEqual(self.expected_compute_node_traits,
                              self._get_provider_traits(self.host_uuid))

    def _run_update_available_resource(self, startup):
        self.compute.rt.update_available_resource(
            context.get_admin_context(), self.compute.host, startup=startup)

    def _run_update_available_resource_and_assert_raises(
            self, exc=exception.ResourceProviderSyncFailed, startup=False):
        """Invoke ResourceTracker.update_available_resource and assert that it
        results in ResourceProviderSyncFailed.

        _run_periodicals is a little too high up in the call stack to be useful
        for this, because ResourceTracker.update_available_resource_for_node
        swallows all exceptions.
        """
        self.assertRaises(exc, self._run_update_available_resource, startup)

    def test_update_provider_tree_associated_info(self):
        """Inventory in some standard and custom resource classes.  Standard
        and custom traits.  Aggregates.  Custom resource class and trait get
        created; inventory, traits, and aggregates get set properly.
        """
        inv = {
            'VCPU': {
                'total': 10,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 2,
                'step_size': 1,
                'allocation_ratio': 10.0,
            },
            'MEMORY_MB': {
                'total': 1048576,
                'reserved': 2048,
                'min_unit': 1024,
                'max_unit': 131072,
                'step_size': 1024,
                'allocation_ratio': 1.0,
            },
            'CUSTOM_BANDWIDTH': {
                'total': 1250000,
                'reserved': 10000,
                'min_unit': 5000,
                'max_unit': 250000,
                'step_size': 5000,
                'allocation_ratio': 8.0,
            },
        }
        traits = set(['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'CUSTOM_GOLD'])
        aggs = set([uuids.agg1, uuids.agg2])

        def update_provider_tree(prov_tree, nodename):
            prov_tree.update_inventory(self.compute.host, inv)
            prov_tree.update_traits(self.compute.host, traits)
            prov_tree.update_aggregates(self.compute.host, aggs)
        self.mock_upt.side_effect = update_provider_tree

        self.assertNotIn('CUSTOM_BANDWIDTH', self._get_all_resource_classes())
        self.assertNotIn('CUSTOM_GOLD', self._get_all_traits())

        self._run_periodics()

        self.assertIn('CUSTOM_BANDWIDTH', self._get_all_resource_classes())
        self.assertIn('CUSTOM_GOLD', self._get_all_traits())
        self.assertEqual(inv, self._get_provider_inventory(self.host_uuid))
        self.assertItemsEqual(
            traits.union(self.expected_compute_node_traits),
            self._get_provider_traits(self.host_uuid)
        )
        self.assertEqual(aggs,
                         set(self._get_provider_aggregates(self.host_uuid)))

    def _update_provider_tree_multiple_providers(self, startup=False,
                                                 do_reshape=False):
        r"""Make update_provider_tree create multiple providers, including an
        additional root as a sharing provider; and some descendants in the
        compute node's tree.

                   +---------------------------+   +--------------------------+
                   |uuid: self.host_uuid       |   |uuid: uuids.ssp           |
                   |name: self.compute.host    |   |name: 'ssp'               |
                   |inv: (per MediumFakeDriver)|   |inv: DISK_GB=500          |
                   |     VCPU=10               |...|traits: [MISC_SHARES_..., |
                   |     MEMORY_MB=8192        |   |         STORAGE_DISK_SSD]|
                   |     DISK_GB=1028          |   |aggs: [uuids.agg]         |
                   |aggs: [uuids.agg]          |   +--------------------------+
                   +---------------------------+
                         /                   \
             +-----------------+          +-----------------+
             |uuid: uuids.numa1|          |uuid: uuids.numa2|
             |name: 'numa1'    |          |name: 'numa2'    |
             |inv: VCPU=10     |          |inv: VCPU=20     |
             |     MEMORY_MB=1G|          |     MEMORY_MB=2G|
             +-----------------+          +-----------------+
                 /          \                    /         \
        +------------+  +------------+   +------------+  +------------+
        |uuid:       |  |uuid:       |   |uuid:       |  |uuid:       |
        | uuids.pf1_1|  | uuids.pf1_2|   | uuids.pf2_1|  | uuids.pf2_2|
        |name:       |  |name:       |   |name:       |  |name:       |
        | 'pf1_1'    |  | 'pf1_2'    |   | 'pf2_1'    |  | 'pf2_2'    |
        |inv:        |  |inv:        |   |inv:        |  |inv:        |
        | ..NET_VF: 2|  | ..NET_VF: 3|   | ..NET_VF: 3|  | ..NET_VF: 4|
        |traits:     |  |traits:     |   |traits:     |  |traits:     |
        | ..PHYSNET_0|  | ..PHYSNET_1|   | ..PHYSNET_0|  | ..PHYSNET_1|
        +------------+  +------------+   +------------+  +------------+
        """
        def update_provider_tree(prov_tree, nodename, allocations=None):
            if do_reshape and allocations is None:
                raise exception.ReshapeNeeded()

            # Create a shared storage provider as a root
            prov_tree.new_root('ssp', uuids.ssp)
            prov_tree.update_traits(
                'ssp', ['MISC_SHARES_VIA_AGGREGATE', 'STORAGE_DISK_SSD'])
            prov_tree.update_aggregates('ssp', [uuids.agg])
            prov_tree.update_inventory('ssp', {'DISK_GB': {'total': 500}})
            # Compute node is in the same aggregate
            prov_tree.update_aggregates(self.compute.host, [uuids.agg])
            # Create two NUMA nodes as children
            prov_tree.new_child('numa1', self.host_uuid, uuid=uuids.numa1)
            prov_tree.new_child('numa2', self.host_uuid, uuid=uuids.numa2)
            # Give the NUMA nodes the proc/mem inventory.  NUMA 2 has twice as
            # much as NUMA 1 (so we can validate later that everything is where
            # it should be).
            for n in (1, 2):
                inv = {
                    'VCPU': {
                        'total': 10 * n,
                        'reserved': 0,
                        'min_unit': 1,
                        'max_unit': 2,
                        'step_size': 1,
                        'allocation_ratio': 10.0,
                    },
                    'MEMORY_MB': {
                         'total': 1048576 * n,
                         'reserved': 2048,
                         'min_unit': 512,
                         'max_unit': 131072,
                         'step_size': 512,
                         'allocation_ratio': 1.0,
                     },
                }
                prov_tree.update_inventory('numa%d' % n, inv)
            # Each NUMA node has two PFs providing VF inventory on one of two
            # networks
            for n in (1, 2):
                for p in (1, 2):
                    name = 'pf%d_%d' % (n, p)
                    prov_tree.new_child(
                        name, getattr(uuids, 'numa%d' % n),
                        uuid=getattr(uuids, name))
                    trait = 'CUSTOM_PHYSNET_%d' % ((n + p) % 2)
                    prov_tree.update_traits(name, [trait])
                    inv = {
                        'SRIOV_NET_VF': {
                            'total': n + p,
                            'reserved': 0,
                            'min_unit': 1,
                            'max_unit': 1,
                            'step_size': 1,
                            'allocation_ratio': 1.0,
                        },
                    }
                    prov_tree.update_inventory(name, inv)
            if do_reshape:
                # Clear out the compute node's inventory. Its VCPU and
                # MEMORY_MB "moved" to the NUMA RPs and its DISK_GB "moved" to
                # the shared storage provider.
                prov_tree.update_inventory(self.host_uuid, {})
                # Move all the allocations
                for consumer_uuid, alloc_info in allocations.items():
                    allocs = alloc_info['allocations']
                    # All allocations should belong to the compute node.
                    self.assertEqual([self.host_uuid], list(allocs))
                    new_allocs = {}
                    for rc, amt in allocs[self.host_uuid]['resources'].items():
                        # Move VCPU to NUMA1 and MEMORY_MB to NUMA2. Bogus, but
                        # lets us prove stuff ends up where we tell it to go.
                        if rc == 'VCPU':
                            rp_uuid = uuids.numa1
                        elif rc == 'MEMORY_MB':
                            rp_uuid = uuids.numa2
                        elif rc == 'DISK_GB':
                            rp_uuid = uuids.ssp
                        else:
                            self.fail("Unexpected resource on compute node: "
                                      "%s=%d" % (rc, amt))
                        new_allocs[rp_uuid] = {
                            'resources': {rc: amt},
                        }
                    # Add a VF for the heck of it. Again bogus, but see above.
                    new_allocs[uuids.pf1_1] = {
                        'resources': {'SRIOV_NET_VF': 1}
                    }
                    # Now replace just the allocations, leaving the other stuff
                    # (proj/user ID and consumer generation) alone
                    alloc_info['allocations'] = new_allocs

        self.mock_upt.side_effect = update_provider_tree

        if startup:
            self.restart_compute_service(self.compute)
        else:
            self._run_update_available_resource(False)

        # Create a dict, keyed by provider UUID, of all the providers
        rps_by_uuid = {}
        for rp_dict in self._get_all_providers():
            rps_by_uuid[rp_dict['uuid']] = rp_dict

        # All and only the expected providers got created.
        all_uuids = set([self.host_uuid, uuids.ssp, uuids.numa1, uuids.numa2,
                         uuids.pf1_1, uuids.pf1_2, uuids.pf2_1, uuids.pf2_2])
        self.assertEqual(all_uuids, set(rps_by_uuid))

        # Validate tree roots
        tree_uuids = [self.host_uuid, uuids.numa1, uuids.numa2,
                      uuids.pf1_1, uuids.pf1_2, uuids.pf2_1, uuids.pf2_2]
        for tree_uuid in tree_uuids:
            self.assertEqual(self.host_uuid,
                             rps_by_uuid[tree_uuid]['root_provider_uuid'])
        self.assertEqual(uuids.ssp,
                         rps_by_uuid[uuids.ssp]['root_provider_uuid'])

        # SSP has the right traits
        self.assertEqual(
            set(['MISC_SHARES_VIA_AGGREGATE', 'STORAGE_DISK_SSD']),
            set(self._get_provider_traits(uuids.ssp)))

        # SSP has the right inventory
        self.assertEqual(
            500, self._get_provider_inventory(uuids.ssp)['DISK_GB']['total'])

        # SSP and compute are in the same aggregate
        agg_uuids = set([self.host_uuid, uuids.ssp])
        for uuid in agg_uuids:
            self.assertEqual(set([uuids.agg]),
                             set(self._get_provider_aggregates(uuid)))

        # The rest aren't in aggregates
        for uuid in (all_uuids - agg_uuids):
            self.assertEqual(set(), set(self._get_provider_aggregates(uuid)))

        # NUMAs have the right inventory and parentage
        for n in (1, 2):
            numa_uuid = getattr(uuids, 'numa%d' % n)
            self.assertEqual(self.host_uuid,
                             rps_by_uuid[numa_uuid]['parent_provider_uuid'])
            inv = self._get_provider_inventory(numa_uuid)
            self.assertEqual(10 * n, inv['VCPU']['total'])
            self.assertEqual(1048576 * n, inv['MEMORY_MB']['total'])

        # PFs have the right inventory, physnet, and parentage
        self.assertEqual(uuids.numa1,
                         rps_by_uuid[uuids.pf1_1]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_0'],
                         self._get_provider_traits(uuids.pf1_1))
        self.assertEqual(
            2,
            self._get_provider_inventory(uuids.pf1_1)['SRIOV_NET_VF']['total'])

        self.assertEqual(uuids.numa1,
                         rps_by_uuid[uuids.pf1_2]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_1'],
                         self._get_provider_traits(uuids.pf1_2))
        self.assertEqual(
            3,
            self._get_provider_inventory(uuids.pf1_2)['SRIOV_NET_VF']['total'])

        self.assertEqual(uuids.numa2,
                         rps_by_uuid[uuids.pf2_1]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_1'],
                         self._get_provider_traits(uuids.pf2_1))
        self.assertEqual(
            3,
            self._get_provider_inventory(uuids.pf2_1)['SRIOV_NET_VF']['total'])

        self.assertEqual(uuids.numa2,
                         rps_by_uuid[uuids.pf2_2]['parent_provider_uuid'])
        self.assertEqual(['CUSTOM_PHYSNET_0'],
                         self._get_provider_traits(uuids.pf2_2))
        self.assertEqual(
            4,
            self._get_provider_inventory(uuids.pf2_2)['SRIOV_NET_VF']['total'])

        # Compute don't have any extra traits
        self.assertItemsEqual(self.expected_compute_node_traits,
                              self._get_provider_traits(self.host_uuid))

        # NUMAs don't have any traits
        for uuid in (uuids.numa1, uuids.numa2):
            self.assertEqual([], self._get_provider_traits(uuid))

    def test_update_provider_tree_multiple_providers(self):
        self._update_provider_tree_multiple_providers()

    def test_update_provider_tree_multiple_providers_startup(self):
        """The above works the same for startup when no reshape requested."""
        self._update_provider_tree_multiple_providers(startup=True)

    def test_update_provider_tree_bogus_resource_class(self):
        def update_provider_tree(prov_tree, nodename):
            prov_tree.update_inventory(self.compute.host, {'FOO': {}})
        self.mock_upt.side_effect = update_provider_tree

        rcs = self._get_all_resource_classes()
        self.assertIn('VCPU', rcs)
        self.assertNotIn('FOO', rcs)

        self._run_update_available_resource_and_assert_raises()

        rcs = self._get_all_resource_classes()
        self.assertIn('VCPU', rcs)
        self.assertNotIn('FOO', rcs)

    def test_update_provider_tree_bogus_trait(self):
        def update_provider_tree(prov_tree, nodename):
            prov_tree.update_traits(self.compute.host, ['FOO'])
        self.mock_upt.side_effect = update_provider_tree

        traits = self._get_all_traits()
        self.assertIn('HW_CPU_X86_AVX', traits)
        self.assertNotIn('FOO', traits)

        self._run_update_available_resource_and_assert_raises()

        traits = self._get_all_traits()
        self.assertIn('HW_CPU_X86_AVX', traits)
        self.assertNotIn('FOO', traits)

    def _create_instance(self, flavor):
        return self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=flavor['id'],
            networks='none', az='nova:host1')

    def test_reshape(self):
        """On startup, virt driver signals it needs to reshape, then does so.

        This test creates a couple of instances so there are allocations to be
        moved by the reshape operation. Then we do the reshape and make sure
        the inventories and allocations end up where they should.
        """
        # First let's create some instances so we have allocations to move.
        flavors = self.api.get_flavors()
        inst1 = self._create_instance(flavors[0])
        inst2 = self._create_instance(flavors[1])

        # Instance create calls RT._update, which calls
        # driver.update_provider_tree, which is currently mocked to a no-op.
        self.assertEqual(2, self.mock_upt.call_count)
        self.mock_upt.reset_mock()

        # Hit the reshape.
        self._update_provider_tree_multiple_providers(startup=True,
                                                      do_reshape=True)

        # Check the final allocations
        # The compute node provider should have *no* allocations.
        self.assertEqual(
            {}, self._get_allocations_by_provider_uuid(self.host_uuid))
        # And no inventory
        self.assertEqual({}, self._get_provider_inventory(self.host_uuid))
        # NUMA1 got all the VCPU
        self.assertEqual(
            {inst1['id']: {'resources': {'VCPU': 1}},
             inst2['id']: {'resources': {'VCPU': 1}}},
            self._get_allocations_by_provider_uuid(uuids.numa1))
        # NUMA2 got all the memory
        self.assertEqual(
            {inst1['id']: {'resources': {'MEMORY_MB': 512}},
             inst2['id']: {'resources': {'MEMORY_MB': 2048}}},
            self._get_allocations_by_provider_uuid(uuids.numa2))
        # Disk resource ended up on the shared storage provider
        self.assertEqual(
            {inst1['id']: {'resources': {'DISK_GB': 1}},
             inst2['id']: {'resources': {'DISK_GB': 20}}},
            self._get_allocations_by_provider_uuid(uuids.ssp))
        # We put VFs on the first PF in NUMA1
        self.assertEqual(
            {inst1['id']: {'resources': {'SRIOV_NET_VF': 1}},
             inst2['id']: {'resources': {'SRIOV_NET_VF': 1}}},
            self._get_allocations_by_provider_uuid(uuids.pf1_1))
        self.assertEqual(
            {}, self._get_allocations_by_provider_uuid(uuids.pf1_2))
        self.assertEqual(
            {}, self._get_allocations_by_provider_uuid(uuids.pf2_1))
        self.assertEqual(
            {}, self._get_allocations_by_provider_uuid(uuids.pf2_2))
        # This is *almost* redundant - but it makes sure the instances don't
        # have extra allocations from some other provider.
        self.assertEqual(
            {
                uuids.numa1: {
                    'resources': {'VCPU': 1},
                    # Don't care about the generations - rely on placement db
                    # tests to validate that those behave properly.
                    'generation': mock.ANY,
                },
                uuids.numa2: {
                    'resources': {'MEMORY_MB': 512},
                    'generation': mock.ANY,
                },
                uuids.ssp: {
                    'resources': {'DISK_GB': 1},
                    'generation': mock.ANY,
                },
                uuids.pf1_1: {
                    'resources': {'SRIOV_NET_VF': 1},
                    'generation': mock.ANY,
                },
            }, self._get_allocations_by_server_uuid(inst1['id']))
        self.assertEqual(
            {
                uuids.numa1: {
                    'resources': {'VCPU': 1},
                    'generation': mock.ANY,
                },
                uuids.numa2: {
                    'resources': {'MEMORY_MB': 2048},
                    'generation': mock.ANY,
                },
                uuids.ssp: {
                    'resources': {'DISK_GB': 20},
                    'generation': mock.ANY,
                },
                uuids.pf1_1: {
                    'resources': {'SRIOV_NET_VF': 1},
                    'generation': mock.ANY,
                },
            }, self._get_allocations_by_server_uuid(inst2['id']))

        # The first call raises ReshapeNeeded, resulting in the second.
        self.assertEqual(2, self.mock_upt.call_count)
        # The expected value of the allocations kwarg to update_provider_tree
        # for that second call:
        exp_allocs = {
            inst1['id']: {
                'allocations': {
                    uuids.numa1: {'resources': {'VCPU': 1}},
                    uuids.numa2: {'resources': {'MEMORY_MB': 512}},
                    uuids.ssp: {'resources': {'DISK_GB': 1}},
                    uuids.pf1_1: {'resources': {'SRIOV_NET_VF': 1}},
                },
                'consumer_generation': mock.ANY,
                'project_id': mock.ANY,
                'user_id': mock.ANY,
            },
            inst2['id']: {
                'allocations': {
                    uuids.numa1: {'resources': {'VCPU': 1}},
                    uuids.numa2: {'resources': {'MEMORY_MB': 2048}},
                    uuids.ssp: {'resources': {'DISK_GB': 20}},
                    uuids.pf1_1: {'resources': {'SRIOV_NET_VF': 1}},
                },
                'consumer_generation': mock.ANY,
                'project_id': mock.ANY,
                'user_id': mock.ANY,
            },
        }
        self.mock_upt.assert_has_calls([
            mock.call(mock.ANY, 'host1'),
            mock.call(mock.ANY, 'host1', allocations=exp_allocs),
        ])


class TraitsTrackingTests(integrated_helpers.ProviderUsageBaseTestCase):
    compute_driver = 'fake.SmallFakeDriver'

    fake_caps = {
        'supports_attach_interface': True,
        'supports_device_tagging': False,
    }

    def _mock_upt(self, traits_to_add, traits_to_remove):
        """Set up the compute driver with a fake update_provider_tree()
        which injects the given traits into the provider tree
        """
        original_upt = fake.SmallFakeDriver.update_provider_tree

        def fake_upt(self2, ptree, nodename, allocations=None):
            original_upt(self2, ptree, nodename, allocations)
            LOG.debug("injecting traits via fake update_provider_tree(): %s",
                      traits_to_add)
            ptree.add_traits(nodename, *traits_to_add)
            LOG.debug("removing traits via fake update_provider_tree(): %s",
                      traits_to_remove)
            ptree.remove_traits(nodename, *traits_to_remove)

        self.stub_out('nova.virt.fake.FakeDriver.update_provider_tree',
                      fake_upt)

    @mock.patch.dict(fake.SmallFakeDriver.capabilities, clear=True,
                     values=fake_caps)
    def test_resource_provider_traits(self):
        """Test that the compute service reports traits via driver
        capabilities and registers them on the compute host resource
        provider in the placement API.
        """
        custom_trait = 'CUSTOM_FOO'
        ptree_traits = [custom_trait, 'HW_CPU_X86_VMX']

        global_traits = self._get_all_traits()
        self.assertNotIn(custom_trait, global_traits)
        self.assertIn(os_traits.COMPUTE_NET_ATTACH_INTERFACE, global_traits)
        self.assertIn(os_traits.COMPUTE_DEVICE_TAGGING, global_traits)
        self.assertIn(os_traits.COMPUTE_NODE, global_traits)
        self.assertEqual([], self._get_all_providers())

        self._mock_upt(ptree_traits, [])

        self.compute = self._start_compute(host='host1')

        rp_uuid = self._get_provider_uuid_by_host('host1')
        expected_traits = set(
            ptree_traits +
            [os_traits.COMPUTE_NET_ATTACH_INTERFACE, os_traits.COMPUTE_NODE]
        )
        self.assertItemsEqual(expected_traits,
                              self._get_provider_traits(rp_uuid))
        global_traits = self._get_all_traits()
        # CUSTOM_FOO is now a registered trait because the virt driver
        # reported it.
        self.assertIn(custom_trait, global_traits)

        # Now simulate user deletion of driver-provided traits from
        # the compute node provider.
        expected_traits.remove(custom_trait)
        expected_traits.remove(os_traits.COMPUTE_NET_ATTACH_INTERFACE)
        self._set_provider_traits(rp_uuid, list(expected_traits))
        self.assertItemsEqual(expected_traits,
                              self._get_provider_traits(rp_uuid))

        # The above trait deletions are simulations of an out-of-band
        # placement operation, as if the operator used the CLI.  So
        # now we have to "SIGHUP the compute process" to clear the
        # report client cache so the subsequent update picks up the
        # changes.
        self.compute.manager.reset()

        # Add the traits back so that the mock update_provider_tree()
        # can reinject them.
        expected_traits.update(
            [custom_trait, os_traits.COMPUTE_NET_ATTACH_INTERFACE])

        # Now when we run the periodic update task, the trait should
        # reappear in the provider tree and get synced back to
        # placement.
        self._run_periodics()

        self.assertItemsEqual(expected_traits,
                              self._get_provider_traits(rp_uuid))
        global_traits = self._get_all_traits()
        self.assertIn(custom_trait, global_traits)
        self.assertIn(os_traits.COMPUTE_NET_ATTACH_INTERFACE, global_traits)

    @mock.patch.dict(fake.SmallFakeDriver.capabilities, clear=True,
                     values=fake_caps)
    def test_admin_traits_preserved(self):
        """Test that if admin externally sets traits on the resource provider
        then the compute periodic doesn't remove them from placement.
        """
        admin_trait = 'CUSTOM_TRAIT_FROM_ADMIN'
        self._create_trait(admin_trait)
        global_traits = self._get_all_traits()
        self.assertIn(admin_trait, global_traits)

        self.compute = self._start_compute(host='host1')
        rp_uuid = self._get_provider_uuid_by_host('host1')
        traits = self._get_provider_traits(rp_uuid)
        traits.append(admin_trait)
        self._set_provider_traits(rp_uuid, traits)
        self.assertIn(admin_trait, self._get_provider_traits(rp_uuid))

        # SIGHUP the compute process to clear the report client
        # cache, so the subsequent periodic update recalculates everything.
        self.compute.manager.reset()

        self._run_periodics()
        self.assertIn(admin_trait, self._get_provider_traits(rp_uuid))

    @mock.patch.dict(fake.SmallFakeDriver.capabilities, clear=True,
                     values=fake_caps)
    def test_driver_removing_support_for_trait_via_capability(self):
        """Test that if a driver initially reports a trait via a supported
        capability, then at the next periodic update doesn't report
        support for it again, it gets removed from the provider in the
        placement service.
        """
        self.compute = self._start_compute(host='host1')
        rp_uuid = self._get_provider_uuid_by_host('host1')
        trait = os_traits.COMPUTE_NET_ATTACH_INTERFACE
        self.assertIn(trait, self._get_provider_traits(rp_uuid))

        new_caps = dict(fake.SmallFakeDriver.capabilities,
                        **{'supports_attach_interface': False})
        with mock.patch.dict(fake.SmallFakeDriver.capabilities, new_caps):
            self._run_periodics()

        self.assertNotIn(trait, self._get_provider_traits(rp_uuid))

    def test_driver_removing_trait_via_upt(self):
        """Test that if a driver reports a trait via update_provider_tree()
        initially, but at the next periodic update doesn't report it
        again, that it gets removed from placement.
        """
        custom_trait = "CUSTOM_TRAIT_FROM_DRIVER"
        standard_trait = os_traits.HW_CPU_X86_SGX
        self._mock_upt([custom_trait, standard_trait], [])

        self.compute = self._start_compute(host='host1')
        rp_uuid = self._get_provider_uuid_by_host('host1')
        self.assertIn(custom_trait, self._get_provider_traits(rp_uuid))
        self.assertIn(standard_trait, self._get_provider_traits(rp_uuid))

        # Now change the fake update_provider_tree() from injecting the
        # traits to removing them, and run the periodic update.
        self._mock_upt([], [custom_trait, standard_trait])
        self._run_periodics()

        self.assertNotIn(custom_trait, self._get_provider_traits(rp_uuid))
        self.assertNotIn(standard_trait, self._get_provider_traits(rp_uuid))

    @mock.patch.dict(fake.SmallFakeDriver.capabilities, clear=True,
                     values=fake_caps)
    def test_driver_removes_unsupported_trait_from_admin(self):
        """Test that if an admin adds a trait corresponding to a
        capability which is unsupported, then if the provider cache is
        reset, the driver will remove it during the next update.
        """
        self.compute = self._start_compute(host='host1')
        rp_uuid = self._get_provider_uuid_by_host('host1')

        traits = self._get_provider_traits(rp_uuid)
        trait = os_traits.COMPUTE_DEVICE_TAGGING
        self.assertNotIn(trait, traits)

        # Simulate an admin associating the trait with the host via
        # the placement API.
        traits.append(trait)
        self._set_provider_traits(rp_uuid, traits)

        # Check that worked.
        traits = self._get_provider_traits(rp_uuid)
        self.assertIn(trait, traits)

        # SIGHUP the compute process to clear the report client
        # cache, so the subsequent periodic update recalculates everything.
        self.compute.manager.reset()

        self._run_periodics()
        self.assertNotIn(trait, self._get_provider_traits(rp_uuid))
