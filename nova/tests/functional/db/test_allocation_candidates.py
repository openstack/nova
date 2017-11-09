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
from nova import context
from nova.objects import fields
from nova.objects import resource_provider as rp_obj
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel


class AllocationCandidatesTestCase(test.NoDBTestCase):
    """Tests a variety of scenarios with both shared and non-shared resource
    providers that the AllocationCandidates.get_by_filters() method returns a
    set of alternative allocation requests and provider summaries that may be
    used by the scheduler to sort/weigh the options it has for claiming
    resources against providers.
    """

    USES_DB_SELF = True

    def setUp(self):
        super(AllocationCandidatesTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.api_db = self.useFixture(fixtures.Database(database='api'))
        self.ctx = context.RequestContext('fake-user', 'fake-project')

    def _requested_resources(self):
        # The resources we will request
        resources = {
            fields.ResourceClass.VCPU: 1,
            fields.ResourceClass.MEMORY_MB: 64,
            fields.ResourceClass.DISK_GB: 1500,
        }
        return resources

    def _find_summary_for_provider(self, p_sums, rp_uuid):
        for summary in p_sums:
            if summary.resource_provider.uuid == rp_uuid:
                return summary

    def _find_summary_for_resource(self, p_sum, rc_name):
        for resource in p_sum.resources:
            if resource.resource_class == rc_name:
                return resource

    def _find_requests_for_provider(self, reqs, rp_uuid):
        res = []
        for ar in reqs:
            for rr in ar.resource_requests:
                if rr.resource_provider.uuid == rp_uuid:
                    res.append(rr)
        return res

    def _find_request_for_resource(self, res_reqs, rc_name):
        for rr in res_reqs:
            if rr.resource_class == rc_name:
                return rr

    def test_all_local(self):
        """Create some resource providers that can satisfy the request for
        resources with local (non-shared) resources and verify that the
        allocation requests returned by AllocationCandidates correspond with
        each of these resource providers.
        """
        # Create two compute node providers with VCPU, RAM and local disk
        cn1_uuid = uuidsentinel.cn1
        cn1 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn1',
            uuid=cn1_uuid,
        )
        cn1.create()

        cn2_uuid = uuidsentinel.cn2
        cn2 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn2',
            uuid=cn2_uuid,
        )
        cn2.create()

        cn3_uuid = uuidsentinel.cn3
        cn3 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn3',
            uuid=cn3_uuid
        )
        cn3.create()

        for cn in (cn1, cn2, cn3):
            vcpu = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=32768,
                reserved=0,
                min_unit=64,
                max_unit=32768,
                step_size=64,
                allocation_ratio=1.5,
            )
            if cn.uuid == cn3_uuid:
                disk_gb = rp_obj.Inventory(
                    resource_provider=cn,
                    resource_class=fields.ResourceClass.DISK_GB,
                    total=1000,
                    reserved=100,
                    min_unit=10,
                    max_unit=1000,
                    step_size=10,
                    allocation_ratio=1.0,
                )
            else:
                disk_gb = rp_obj.Inventory(
                    resource_provider=cn,
                    resource_class=fields.ResourceClass.DISK_GB,
                    total=2000,
                    reserved=100,
                    min_unit=10,
                    max_unit=2000,
                    step_size=10,
                    allocation_ratio=1.0,
                )
            disk_gb.obj_set_defaults()
            inv_list = rp_obj.InventoryList(objects=[
                vcpu,
                memory_mb,
                disk_gb,
            ])
            cn.set_inventory(inv_list)

        # Ask for the alternative placement possibilities and verify each
        # provider is returned
        requested_resources = self._requested_resources()
        p_alts = rp_obj.AllocationCandidates.get_by_filters(
            self.ctx,
            filters={
                'resources': requested_resources,
            },
        )

        # Verify the provider summary information indicates 0 usage and
        # capacity calculated from above inventory numbers for both compute
        # nodes
        p_sums = p_alts.provider_summaries
        self.assertEqual(2, len(p_sums))

        p_sum_rps = set([ps.resource_provider.uuid for ps in p_sums])

        self.assertEqual(set([cn1_uuid, cn2_uuid]), p_sum_rps)

        cn1_p_sum = self._find_summary_for_provider(p_sums, cn1_uuid)
        self.assertIsNotNone(cn1_p_sum)
        self.assertEqual(3, len(cn1_p_sum.resources))

        cn1_p_sum_vcpu = self._find_summary_for_resource(cn1_p_sum, 'VCPU')
        self.assertIsNotNone(cn1_p_sum_vcpu)

        expected_capacity = (24 * 16.0)
        self.assertEqual(expected_capacity, cn1_p_sum_vcpu.capacity)
        self.assertEqual(0, cn1_p_sum_vcpu.used)

        # Let's verify the disk for the second compute node
        cn2_p_sum = self._find_summary_for_provider(p_sums, cn2_uuid)
        self.assertIsNotNone(cn2_p_sum)
        self.assertEqual(3, len(cn2_p_sum.resources))

        cn2_p_sum_disk = self._find_summary_for_resource(cn2_p_sum, 'DISK_GB')
        self.assertIsNotNone(cn2_p_sum_disk)

        expected_capacity = ((2000 - 100) * 1.0)
        self.assertEqual(expected_capacity, cn2_p_sum_disk.capacity)
        self.assertEqual(0, cn2_p_sum_disk.used)

        # Verify the allocation requests that are returned. There should be 2
        # allocation requests, one for each compute node, containing 3
        # resources in each allocation request, one each for VCPU, RAM, and
        # disk. The amounts of the requests should correspond to the requested
        # resource amounts in the filter:resources dict passed to
        # AllocationCandidates.get_by_filters().
        a_reqs = p_alts.allocation_requests
        self.assertEqual(2, len(a_reqs))

        a_req_rps = set()
        for ar in a_reqs:
            for rr in ar.resource_requests:
                a_req_rps.add(rr.resource_provider.uuid)

        self.assertEqual(set([cn1_uuid, cn2_uuid]), a_req_rps)

        cn1_reqs = self._find_requests_for_provider(a_reqs, cn1_uuid)
        # There should be a req object for each resource we have requested
        self.assertEqual(3, len(cn1_reqs))

        cn1_req_vcpu = self._find_request_for_resource(cn1_reqs, 'VCPU')
        self.assertIsNotNone(cn1_req_vcpu)
        self.assertEqual(requested_resources['VCPU'], cn1_req_vcpu.amount)

        cn2_req_disk = self._find_request_for_resource(cn1_reqs, 'DISK_GB')
        self.assertIsNotNone(cn2_req_disk)
        self.assertEqual(requested_resources['DISK_GB'], cn2_req_disk.amount)

    def test_local_with_shared_disk(self):
        """Create some resource providers that can satisfy the request for
        resources with local VCPU and MEMORY_MB but rely on a shared storage
        pool to satisfy DISK_GB and verify that the allocation requests
        returned by AllocationCandidates have DISK_GB served up by the shared
        storage pool resource provider and VCPU/MEMORY_MB by the compute node
        providers
        """
        # The aggregate that will be associated to everything...
        agg_uuid = uuidsentinel.agg

        # Create two compute node providers with VCPU, RAM and NO local disk
        cn1_uuid = uuidsentinel.cn1
        cn1 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn1',
            uuid=cn1_uuid,
        )
        cn1.create()

        cn2_uuid = uuidsentinel.cn2
        cn2 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn2',
            uuid=cn2_uuid,
        )
        cn2.create()

        # Populate the two compute node providers with inventory, sans DISK_GB
        for cn in (cn1, cn2):
            vcpu = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024,
                reserved=0,
                min_unit=64,
                max_unit=1024,
                step_size=1,
                allocation_ratio=1.5,
            )
            inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb])
            cn.set_inventory(inv_list)

        # Create the shared storage pool
        ss_uuid = uuidsentinel.ss
        ss = rp_obj.ResourceProvider(
            self.ctx,
            name='shared storage',
            uuid=ss_uuid,
        )
        ss.create()

        # Give the shared storage pool some inventory of DISK_GB
        disk_gb = rp_obj.Inventory(
            resource_provider=ss,
            resource_class=fields.ResourceClass.DISK_GB,
            total=2000,
            reserved=100,
            min_unit=10,
            max_unit=2000,
            step_size=1,
            allocation_ratio=1.0,
        )
        inv_list = rp_obj.InventoryList(objects=[disk_gb])
        ss.set_inventory(inv_list)

        # Mark the shared storage pool as having inventory shared among any
        # provider associated via aggregate
        t = rp_obj.Trait.get_by_name(self.ctx, "MISC_SHARES_VIA_AGGREGATE")
        ss.set_traits(rp_obj.TraitList(objects=[t]))

        # Now associate the shared storage pool and both compute nodes with the
        # same aggregate
        cn1.set_aggregates([agg_uuid])
        cn2.set_aggregates([agg_uuid])
        ss.set_aggregates([agg_uuid])

        # Ask for the alternative placement possibilities and verify each
        # compute node provider is listed in the allocation requests as well as
        # the shared storage pool provider
        requested_resources = self._requested_resources()
        p_alts = rp_obj.AllocationCandidates.get_by_filters(
            self.ctx,
            filters={
                'resources': requested_resources,
            },
        )

        # Verify the provider summary information indicates 0 usage and
        # capacity calculated from above inventory numbers for both compute
        # nodes
        p_sums = p_alts.provider_summaries
        self.assertEqual(3, len(p_sums))

        p_sum_rps = set([ps.resource_provider.uuid for ps in p_sums])

        self.assertEqual(set([cn1_uuid, cn2_uuid, ss_uuid]), p_sum_rps)

        cn1_p_sum = self._find_summary_for_provider(p_sums, cn1_uuid)
        self.assertIsNotNone(cn1_p_sum)
        self.assertEqual(2, len(cn1_p_sum.resources))

        cn1_p_sum_vcpu = self._find_summary_for_resource(cn1_p_sum, 'VCPU')
        self.assertIsNotNone(cn1_p_sum_vcpu)

        expected_capacity = (24 * 16.0)
        self.assertEqual(expected_capacity, cn1_p_sum_vcpu.capacity)
        self.assertEqual(0, cn1_p_sum_vcpu.used)

        # Let's verify memory for the second compute node
        cn2_p_sum = self._find_summary_for_provider(p_sums, cn2_uuid)
        self.assertIsNotNone(cn2_p_sum)
        self.assertEqual(2, len(cn2_p_sum.resources))

        cn2_p_sum_ram = self._find_summary_for_resource(cn2_p_sum, 'MEMORY_MB')
        self.assertIsNotNone(cn2_p_sum_ram)

        expected_capacity = (1024 * 1.5)
        self.assertEqual(expected_capacity, cn2_p_sum_ram.capacity)
        self.assertEqual(0, cn2_p_sum_ram.used)

        # Let's verify only diks for the shared storage pool
        ss_p_sum = self._find_summary_for_provider(p_sums, ss_uuid)
        self.assertIsNotNone(ss_p_sum)
        self.assertEqual(1, len(ss_p_sum.resources))

        ss_p_sum_disk = self._find_summary_for_resource(ss_p_sum, 'DISK_GB')
        self.assertIsNotNone(ss_p_sum_disk)

        expected_capacity = ((2000 - 100) * 1.0)
        self.assertEqual(expected_capacity, ss_p_sum_disk.capacity)
        self.assertEqual(0, ss_p_sum_disk.used)

        # Verify the allocation requests that are returned. There should be 2
        # allocation requests, one for each compute node, containing 3
        # resources in each allocation request, one each for VCPU, RAM, and
        # disk. The amounts of the requests should correspond to the requested
        # resource amounts in the filter:resources dict passed to
        # AllocationCandidates.get_by_filters(). The providers for VCPU and
        # MEMORY_MB should be the compute nodes while the provider for the
        # DISK_GB should be the shared storage pool
        a_reqs = p_alts.allocation_requests
        self.assertEqual(2, len(a_reqs))

        a_req_rps = set()
        for ar in a_reqs:
            for rr in ar.resource_requests:
                a_req_rps.add(rr.resource_provider.uuid)

        self.assertEqual(set([cn1_uuid, cn2_uuid, ss_uuid]), a_req_rps)

        cn1_reqs = self._find_requests_for_provider(a_reqs, cn1_uuid)
        # There should be a req object for only VCPU and MEMORY_MB
        self.assertEqual(2, len(cn1_reqs))

        cn1_req_vcpu = self._find_request_for_resource(cn1_reqs, 'VCPU')
        self.assertIsNotNone(cn1_req_vcpu)
        self.assertEqual(requested_resources['VCPU'], cn1_req_vcpu.amount)

        cn2_reqs = self._find_requests_for_provider(a_reqs, cn2_uuid)

        # There should NOT be an allocation resource request that lists a
        # compute node provider UUID for DISK_GB, since the shared storage pool
        # is the thing that is providing the disk
        cn1_req_disk = self._find_request_for_resource(cn1_reqs, 'DISK_GB')
        self.assertIsNone(cn1_req_disk)
        cn2_req_disk = self._find_request_for_resource(cn2_reqs, 'DISK_GB')
        self.assertIsNone(cn2_req_disk)

        # Let's check the second compute node for MEMORY_MB
        cn2_req_ram = self._find_request_for_resource(cn2_reqs, 'MEMORY_MB')
        self.assertIsNotNone(cn2_req_ram)
        self.assertEqual(requested_resources['MEMORY_MB'], cn2_req_ram.amount)

        # We should find the shared storage pool providing the DISK_GB for each
        # of the allocation requests
        ss_reqs = self._find_requests_for_provider(a_reqs, ss_uuid)
        self.assertEqual(2, len(ss_reqs))

        # Shared storage shouldn't be listed as providing anything but disk...
        ss_req_ram = self._find_request_for_resource(ss_reqs, 'MEMORY_MB')
        self.assertIsNone(ss_req_ram)

        ss_req_disk = self._find_request_for_resource(ss_reqs, 'DISK_GB')
        self.assertIsNotNone(ss_req_disk)
        self.assertEqual(requested_resources['DISK_GB'], ss_req_disk.amount)

        # Test for bug #1705071. We query for allocation candidates with a
        # request for ONLY the DISK_GB (the resource that is shared with
        # compute nodes) and no VCPU/MEMORY_MB. Before the fix for bug
        # #1705071, this resulted in a KeyError

        p_alts = rp_obj.AllocationCandidates.get_by_filters(
            self.ctx,
            filters={
                'resources': {
                    'DISK_GB': 10,
                }
            },
        )

        # We should only have provider summary information for the sharing
        # storage provider, since that's the only provider that can be
        # allocated against for this request.  In the future, we may look into
        # returning the shared-with providers in the provider summaries, but
        # that's a distant possibility.
        p_sums = p_alts.provider_summaries
        self.assertEqual(1, len(p_sums))

        p_sum_rps = set([ps.resource_provider.uuid for ps in p_sums])

        self.assertEqual(set([ss_uuid]), p_sum_rps)

        # The allocation_requests will only include the shared storage
        # provider because the only thing we're requesting to allocate is
        # against the provider of DISK_GB, which happens to be the shared
        # storage provider.
        a_reqs = p_alts.allocation_requests
        self.assertEqual(1, len(a_reqs))

        a_req_rps = set()
        for ar in a_reqs:
            for rr in ar.resource_requests:
                a_req_rps.add(rr.resource_provider.uuid)

        self.assertEqual(set([ss_uuid]), a_req_rps)

    def test_local_with_shared_custom_resource(self):
        """Create some resource providers that can satisfy the request for
        resources with local VCPU and MEMORY_MB but rely on a shared resource
        provider to satisfy a custom resource requirement and verify that the
        allocation requests returned by AllocationCandidates have the custom
        resource served up by the shared custom resource provider and
        VCPU/MEMORY_MB by the compute node providers
        """
        # The aggregate that will be associated to everything...
        agg_uuid = uuidsentinel.agg

        # Create two compute node providers with VCPU, RAM and NO local
        # CUSTOM_MAGIC resources
        cn1_uuid = uuidsentinel.cn1
        cn1 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn1',
            uuid=cn1_uuid,
        )
        cn1.create()

        cn2_uuid = uuidsentinel.cn2
        cn2 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn2',
            uuid=cn2_uuid,
        )
        cn2.create()

        # Populate the two compute node providers with inventory
        for cn in (cn1, cn2):
            vcpu = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024,
                reserved=0,
                min_unit=64,
                max_unit=1024,
                step_size=1,
                allocation_ratio=1.5,
            )
            inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb])
            cn.set_inventory(inv_list)

        # Create a custom resource called MAGIC
        magic_rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_MAGIC',
        )
        magic_rc.create()

        # Create the shared provider that servers MAGIC
        magic_p_uuid = uuidsentinel.magic_p
        magic_p = rp_obj.ResourceProvider(
            self.ctx,
            name='shared custom resource provider',
            uuid=magic_p_uuid,
        )
        magic_p.create()

        # Give the provider some MAGIC
        magic = rp_obj.Inventory(
            resource_provider=magic_p,
            resource_class=magic_rc.name,
            total=2048,
            reserved=1024,
            min_unit=10,
            max_unit=2048,
            step_size=1,
            allocation_ratio=1.0,
        )
        inv_list = rp_obj.InventoryList(objects=[magic])
        magic_p.set_inventory(inv_list)

        # Mark the magic provider as having inventory shared among any provider
        # associated via aggregate
        t = rp_obj.Trait(
            self.ctx,
            name="MISC_SHARES_VIA_AGGREGATE",
        )
        # TODO(jaypipes): Once MISC_SHARES_VIA_AGGREGATE is a standard
        # os-traits trait, we won't need to create() here. Instead, we will
        # just do:
        # t = rp_obj.Trait.get_by_name(
        #    self.context,
        #    "MISC_SHARES_VIA_AGGREGATE",
        # )
        t.create()
        magic_p.set_traits(rp_obj.TraitList(objects=[t]))

        # Now associate the shared custom resource provider and both compute
        # nodes with the same aggregate
        cn1.set_aggregates([agg_uuid])
        cn2.set_aggregates([agg_uuid])
        magic_p.set_aggregates([agg_uuid])

        # The resources we will request
        requested_resources = {
            fields.ResourceClass.VCPU: 1,
            fields.ResourceClass.MEMORY_MB: 64,
            magic_rc.name: 512,
        }

        p_alts = rp_obj.AllocationCandidates.get_by_filters(
            self.ctx,
            filters={
                'resources': requested_resources,
            },
        )

        # Verify the allocation requests that are returned. There should be 2
        # allocation requests, one for each compute node, containing 3
        # resources in each allocation request, one each for VCPU, RAM, and
        # MAGIC. The amounts of the requests should correspond to the requested
        # resource amounts in the filter:resources dict passed to
        # AllocationCandidates.get_by_filters(). The providers for VCPU and
        # MEMORY_MB should be the compute nodes while the provider for the
        # MAGIC should be the shared custom resource provider.
        a_reqs = p_alts.allocation_requests
        self.assertEqual(2, len(a_reqs))

        a_req_rps = set()
        for ar in a_reqs:
            for rr in ar.resource_requests:
                a_req_rps.add(rr.resource_provider.uuid)

        self.assertEqual(set([cn1_uuid, cn2_uuid, magic_p_uuid]), a_req_rps)

        cn1_reqs = self._find_requests_for_provider(a_reqs, cn1_uuid)
        # There should be a req object for only VCPU and MEMORY_MB
        self.assertEqual(2, len(cn1_reqs))

        cn1_req_vcpu = self._find_request_for_resource(cn1_reqs, 'VCPU')
        self.assertIsNotNone(cn1_req_vcpu)
        self.assertEqual(requested_resources['VCPU'], cn1_req_vcpu.amount)

        cn2_reqs = self._find_requests_for_provider(a_reqs, cn2_uuid)

        # There should NOT be an allocation resource request that lists a
        # compute node provider UUID for MAGIC, since the shared
        # custom provider is the thing that is providing the disk
        cn1_req_disk = self._find_request_for_resource(cn1_reqs, magic_rc.name)
        self.assertIsNone(cn1_req_disk)
        cn2_req_disk = self._find_request_for_resource(cn2_reqs, magic_rc.name)
        self.assertIsNone(cn2_req_disk)

        # Let's check the second compute node for MEMORY_MB
        cn2_req_ram = self._find_request_for_resource(cn2_reqs, 'MEMORY_MB')
        self.assertIsNotNone(cn2_req_ram)
        self.assertEqual(requested_resources['MEMORY_MB'], cn2_req_ram.amount)

        # We should find the shared custom resource provider providing the
        # MAGIC for each of the allocation requests
        magic_p_reqs = self._find_requests_for_provider(a_reqs, magic_p_uuid)
        self.assertEqual(2, len(magic_p_reqs))

        # Shared custom resource provider shouldn't be listed as providing
        # anything but MAGIC...
        magic_p_req_ram = self._find_request_for_resource(
            magic_p_reqs, 'MEMORY_MB')
        self.assertIsNone(magic_p_req_ram)

        magic_p_req_magic = self._find_request_for_resource(
            magic_p_reqs, magic_rc.name)
        self.assertIsNotNone(magic_p_req_magic)
        self.assertEqual(
            requested_resources[magic_rc.name], magic_p_req_magic.amount)

    def test_mix_local_and_shared(self):
        # The aggregate that will be associated to shared storage pool
        agg_uuid = uuidsentinel.agg

        # Create three compute node providers with VCPU and RAM, but only
        # the third compute node has DISK. The first two computes will
        # share the storage from the shared storage pool
        cn1_uuid = uuidsentinel.cn1
        cn1 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn1',
            uuid=cn1_uuid,
        )
        cn1.create()

        cn2_uuid = uuidsentinel.cn2
        cn2 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn2',
            uuid=cn2_uuid,
        )
        cn2.create()

        cn3_uuid = uuidsentinel.cn3
        cn3 = rp_obj.ResourceProvider(
            self.ctx,
            name='cn3',
            uuid=cn3_uuid
        )
        cn3.create()

        # Populate the two compute node providers with inventory
        for cn in (cn1, cn2, cn3):
            vcpu = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.VCPU,
                total=24,
                reserved=0,
                min_unit=1,
                max_unit=24,
                step_size=1,
                allocation_ratio=16.0,
            )
            memory_mb = rp_obj.Inventory(
                resource_provider=cn,
                resource_class=fields.ResourceClass.MEMORY_MB,
                total=1024,
                reserved=0,
                min_unit=64,
                max_unit=1024,
                step_size=1,
                allocation_ratio=1.5,
            )
            disk_gb = rp_obj.Inventory(
                resource_provider=cn3,
                resource_class=fields.ResourceClass.DISK_GB,
                total=2000,
                reserved=100,
                min_unit=10,
                max_unit=2000,
                step_size=1,
                allocation_ratio=1.0,
            )
            if cn == cn3:
                inv_list = rp_obj.InventoryList(
                    objects=[vcpu, memory_mb, disk_gb])
            else:
                inv_list = rp_obj.InventoryList(objects=[vcpu, memory_mb])
            cn.set_inventory(inv_list)

        # Create the shared storage pool
        ss_uuid = uuidsentinel.ss
        ss = rp_obj.ResourceProvider(
            self.ctx,
            name='shared storage',
            uuid=ss_uuid,
        )
        ss.create()

        # Give the shared storage pool some inventory of DISK_GB
        disk_gb = rp_obj.Inventory(
            resource_provider=ss,
            resource_class=fields.ResourceClass.DISK_GB,
            total=2000,
            reserved=100,
            min_unit=10,
            max_unit=2000,
            step_size=1,
            allocation_ratio=1.0,
        )
        inv_list = rp_obj.InventoryList(objects=[disk_gb])
        ss.set_inventory(inv_list)

        t = rp_obj.Trait.get_by_name(self.ctx, "MISC_SHARES_VIA_AGGREGATE")
        ss.set_traits(rp_obj.TraitList(objects=[t]))

        # Put the cn1, cn2 and ss in the same aggregate
        cn1.set_aggregates([agg_uuid])
        cn2.set_aggregates([agg_uuid])
        ss.set_aggregates([agg_uuid])

        requested_resources = self._requested_resources()
        p_alts = rp_obj.AllocationCandidates.get_by_filters(
            self.ctx,
            filters={
                'resources': requested_resources,
            },
        )

        # Expect cn1, cn2, cn3 and ss in the summaries
        p_sums = p_alts.provider_summaries
        self.assertEqual(4, len(p_sums))

        p_sum_rps = set([ps.resource_provider.uuid for ps in p_sums])

        self.assertEqual(set([cn1_uuid, cn2_uuid,
                              ss_uuid, cn3_uuid]),
                         p_sum_rps)

        # Expect three allocation requests: (cn1, ss), (cn2, ss), (cn3)
        a_reqs = p_alts.allocation_requests
        self.assertEqual(3, len(a_reqs))

        expected_ar = []
        for ar in a_reqs:
            rr_set = set()
            for rr in ar.resource_requests:
                rr_set.add(rr.resource_provider.uuid)
            expected_ar.append(rr_set)

        self.assertEqual(sorted(expected_ar),
                         sorted([set([cn1.uuid, ss.uuid]),
                                 set([cn2.uuid, ss.uuid]), set([cn3.uuid])]))
