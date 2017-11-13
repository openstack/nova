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
from nova import exception
from nova.objects import fields
from nova.objects import resource_provider as rp_obj
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel as uuids


def _add_inventory(rp, rc, total, **kwargs):
    kwargs.setdefault('max_unit', total)
    inv = rp_obj.Inventory(rp._context, resource_provider=rp,
                           resource_class=rc, total=total, **kwargs)
    inv.obj_set_defaults()
    rp.add_inventory(inv)


def _set_traits(rp, *traits):
    tlist = []
    for tname in traits:
        try:
            trait = rp_obj.Trait.get_by_name(rp._context, tname)
        except exception.TraitNotFound:
            trait = rp_obj.Trait(rp._context, name=tname)
            trait.create()
        tlist.append(trait)
    rp.set_traits(rp_obj.TraitList(objects=tlist))


def _provider_uuids_from_iterable(objs):
    """Return the set of resource_provider.uuid from an iterable.

    :param objs: Iterable of any object with a resource_provider attribute
                 (e.g. an AllocationRequest.resource_requests or an
                 AllocationCandidates.provider_summaries).
    """
    return set(obj.resource_provider.uuid for obj in objs)


def _find_summary_for_provider(p_sums, rp_uuid):
    for summary in p_sums:
        if summary.resource_provider.uuid == rp_uuid:
            return summary


def _find_summary_for_resource(p_sum, rc_name):
    for resource in p_sum.resources:
        if resource.resource_class == rc_name:
            return resource


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
        self.requested_resources = {
            fields.ResourceClass.VCPU: 1,
            fields.ResourceClass.MEMORY_MB: 64,
            fields.ResourceClass.DISK_GB: 1500,
        }
        # For debugging purposes, populated by _create_provider and used by
        # _validate_allocation_requests to make failure results more readable.
        self.rp_uuid_to_name = {}

    def _get_allocation_candidates(self, resources=None):
        # The resources we will request
        if resources is None:
            resources = self.requested_resources
        return rp_obj.AllocationCandidates.get_by_filters(
            self.ctx,
            filters={
                'resources': resources,
            },
        )

    def _create_provider(self, name, *aggs):
        rp = rp_obj.ResourceProvider(self.ctx, name=name,
                                     uuid=getattr(uuids, name))
        rp.create()
        if aggs:
            rp.set_aggregates(aggs)
        self.rp_uuid_to_name[rp.uuid] = name
        return rp

    def _validate_allocation_requests(self, expected, candidates):
        """Assert correctness of allocation requests in allocation candidates.

        This is set up to make it easy for the caller to specify the expected
        result, to make that expected structure readable for someone looking at
        the test case, and to make test failures readable for debugging.

        :param expected: A list of lists of tuples representing the expected
                         allocation requests, of the form:
             [
                [(resource_provider_name, resource_class_name, resource_count),
                 ...,
                ],
                ...
             ]
        :param candidates: The result from AllocationCandidates.get_by_filters.
        """
        # Extract/convert allocation requests from candidates
        observed = []
        for ar in candidates.allocation_requests:
            rrs = []
            for rr in ar.resource_requests:
                rrs.append((self.rp_uuid_to_name[rr.resource_provider.uuid],
                            rr.resource_class, rr.amount))
            rrs.sort()
            observed.append(rrs)
        observed.sort()

        # Sort the guts of the expected structure
        for rr in expected:
            rr.sort()
        expected.sort()

        # Now we ought to be able to compare them
        self.assertEqual(expected, observed)

    def test_all_local(self):
        """Create some resource providers that can satisfy the request for
        resources with local (non-shared) resources and verify that the
        allocation requests returned by AllocationCandidates correspond with
        each of these resource providers.
        """
        # Create three compute node providers with VCPU, RAM and local disk
        for name in ('cn1', 'cn2', 'cn3'):
            cn = self._create_provider(name)
            _add_inventory(cn, fields.ResourceClass.VCPU, 24,
                           allocation_ratio=16.0)
            _add_inventory(cn, fields.ResourceClass.MEMORY_MB, 32768,
                           min_unit=64, step_size=64, allocation_ratio=1.5)
            total_gb = 1000 if name == 'cn3' else 2000
            _add_inventory(cn, fields.ResourceClass.DISK_GB, total_gb,
                           reserved=100, min_unit=10, step_size=10,
                           allocation_ratio=1.0)

        # Ask for the alternative placement possibilities and verify each
        # provider is returned
        alloc_cands = self._get_allocation_candidates()

        # Verify the provider summary information indicates 0 usage and
        # capacity calculated from above inventory numbers for both compute
        # nodes
        # TODO(efried): Come up with a terse & readable way to validate
        # provider summaries
        p_sums = alloc_cands.provider_summaries

        self.assertEqual(set([uuids.cn1, uuids.cn2]),
                         _provider_uuids_from_iterable(p_sums))

        cn1_p_sum = _find_summary_for_provider(p_sums, uuids.cn1)
        self.assertIsNotNone(cn1_p_sum)
        self.assertEqual(3, len(cn1_p_sum.resources))

        cn1_p_sum_vcpu = _find_summary_for_resource(cn1_p_sum, 'VCPU')
        self.assertIsNotNone(cn1_p_sum_vcpu)

        expected_capacity = (24 * 16.0)
        self.assertEqual(expected_capacity, cn1_p_sum_vcpu.capacity)
        self.assertEqual(0, cn1_p_sum_vcpu.used)

        # Let's verify the disk for the second compute node
        cn2_p_sum = _find_summary_for_provider(p_sums, uuids.cn2)
        self.assertIsNotNone(cn2_p_sum)
        self.assertEqual(3, len(cn2_p_sum.resources))

        cn2_p_sum_disk = _find_summary_for_resource(cn2_p_sum, 'DISK_GB')
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
        expected = [
            [('cn1', fields.ResourceClass.VCPU, 1),
             ('cn1', fields.ResourceClass.MEMORY_MB, 64),
             ('cn1', fields.ResourceClass.DISK_GB, 1500)],
            [('cn2', fields.ResourceClass.VCPU, 1),
             ('cn2', fields.ResourceClass.MEMORY_MB, 64),
             ('cn2', fields.ResourceClass.DISK_GB, 1500)],
        ]
        self._validate_allocation_requests(expected, alloc_cands)

    def test_local_with_shared_disk(self):
        """Create some resource providers that can satisfy the request for
        resources with local VCPU and MEMORY_MB but rely on a shared storage
        pool to satisfy DISK_GB and verify that the allocation requests
        returned by AllocationCandidates have DISK_GB served up by the shared
        storage pool resource provider and VCPU/MEMORY_MB by the compute node
        providers
        """
        # The aggregate that will be associated to everything...
        agg_uuid = uuids.agg

        # Create two compute node providers with VCPU, RAM and NO local disk,
        # associated with the aggregate.
        for name in ('cn1', 'cn2'):
            cn = self._create_provider(name, agg_uuid)
            _add_inventory(cn, fields.ResourceClass.VCPU, 24,
                           allocation_ratio=16.0)
            _add_inventory(cn, fields.ResourceClass.MEMORY_MB, 1024,
                           min_unit=64, allocation_ratio=1.5)

        # Create the shared storage pool, asociated with the same aggregate
        ss = self._create_provider('shared storage', agg_uuid)

        # Give the shared storage pool some inventory of DISK_GB
        _add_inventory(ss, fields.ResourceClass.DISK_GB, 2000, reserved=100,
                       min_unit=10)

        # Mark the shared storage pool as having inventory shared among any
        # provider associated via aggregate
        _set_traits(ss, "MISC_SHARES_VIA_AGGREGATE")

        # Ask for the alternative placement possibilities and verify each
        # compute node provider is listed in the allocation requests as well as
        # the shared storage pool provider
        alloc_cands = self._get_allocation_candidates()

        # Verify the provider summary information indicates 0 usage and
        # capacity calculated from above inventory numbers for both compute
        # nodes
        # TODO(efried): Come up with a terse & readable way to validate
        # provider summaries
        p_sums = alloc_cands.provider_summaries

        self.assertEqual(set([uuids.cn1, uuids.cn2, ss.uuid]),
                         _provider_uuids_from_iterable(p_sums))

        cn1_p_sum = _find_summary_for_provider(p_sums, uuids.cn1)
        self.assertIsNotNone(cn1_p_sum)
        self.assertEqual(2, len(cn1_p_sum.resources))

        cn1_p_sum_vcpu = _find_summary_for_resource(cn1_p_sum, 'VCPU')
        self.assertIsNotNone(cn1_p_sum_vcpu)

        expected_capacity = (24 * 16.0)
        self.assertEqual(expected_capacity, cn1_p_sum_vcpu.capacity)
        self.assertEqual(0, cn1_p_sum_vcpu.used)

        # Let's verify memory for the second compute node
        cn2_p_sum = _find_summary_for_provider(p_sums, uuids.cn2)
        self.assertIsNotNone(cn2_p_sum)
        self.assertEqual(2, len(cn2_p_sum.resources))

        cn2_p_sum_ram = _find_summary_for_resource(cn2_p_sum, 'MEMORY_MB')
        self.assertIsNotNone(cn2_p_sum_ram)

        expected_capacity = (1024 * 1.5)
        self.assertEqual(expected_capacity, cn2_p_sum_ram.capacity)
        self.assertEqual(0, cn2_p_sum_ram.used)

        # Let's verify only diks for the shared storage pool
        ss_p_sum = _find_summary_for_provider(p_sums, ss.uuid)
        self.assertIsNotNone(ss_p_sum)
        self.assertEqual(1, len(ss_p_sum.resources))

        ss_p_sum_disk = _find_summary_for_resource(ss_p_sum, 'DISK_GB')
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
        expected = [
            [('cn1', fields.ResourceClass.VCPU, 1),
             ('cn1', fields.ResourceClass.MEMORY_MB, 64),
             ('shared storage', fields.ResourceClass.DISK_GB, 1500)],
            [('cn2', fields.ResourceClass.VCPU, 1),
             ('cn2', fields.ResourceClass.MEMORY_MB, 64),
             ('shared storage', fields.ResourceClass.DISK_GB, 1500)],
        ]
        self._validate_allocation_requests(expected, alloc_cands)

        # Test for bug #1705071. We query for allocation candidates with a
        # request for ONLY the DISK_GB (the resource that is shared with
        # compute nodes) and no VCPU/MEMORY_MB. Before the fix for bug
        # #1705071, this resulted in a KeyError

        alloc_cands = self._get_allocation_candidates(
            resources={
                'DISK_GB': 10,
            }
        )

        # We should only have provider summary information for the sharing
        # storage provider, since that's the only provider that can be
        # allocated against for this request.  In the future, we may look into
        # returning the shared-with providers in the provider summaries, but
        # that's a distant possibility.
        self.assertEqual(
            set([ss.uuid]),
            _provider_uuids_from_iterable(alloc_cands.provider_summaries))

        # The allocation_requests will only include the shared storage
        # provider because the only thing we're requesting to allocate is
        # against the provider of DISK_GB, which happens to be the shared
        # storage provider.
        expected = [[('shared storage', fields.ResourceClass.DISK_GB, 10)]]
        self._validate_allocation_requests(expected, alloc_cands)

    def test_local_with_shared_custom_resource(self):
        """Create some resource providers that can satisfy the request for
        resources with local VCPU and MEMORY_MB but rely on a shared resource
        provider to satisfy a custom resource requirement and verify that the
        allocation requests returned by AllocationCandidates have the custom
        resource served up by the shared custom resource provider and
        VCPU/MEMORY_MB by the compute node providers
        """
        # The aggregate that will be associated to everything...
        agg_uuid = uuids.agg

        # Create two compute node providers with VCPU, RAM and NO local
        # CUSTOM_MAGIC resources, associated with the aggregate.
        for name in ('cn1', 'cn2'):
            cn = self._create_provider(name, agg_uuid)
            _add_inventory(cn, fields.ResourceClass.VCPU, 24,
                           allocation_ratio=16.0)
            _add_inventory(cn, fields.ResourceClass.MEMORY_MB, 1024,
                           min_unit=64, allocation_ratio=1.5)

        # Create a custom resource called MAGIC
        magic_rc = rp_obj.ResourceClass(
            self.ctx,
            name='CUSTOM_MAGIC',
        )
        magic_rc.create()

        # Create the shared provider that serves CUSTOM_MAGIC, associated with
        # the same aggregate
        magic_p = self._create_provider('shared custom resource provider',
                                        agg_uuid)
        _add_inventory(magic_p, magic_rc.name, 2048, reserved=1024,
                       min_unit=10)

        # Mark the magic provider as having inventory shared among any provider
        # associated via aggregate
        _set_traits(magic_p, "MISC_SHARES_VIA_AGGREGATE")

        # The resources we will request
        requested_resources = {
            fields.ResourceClass.VCPU: 1,
            fields.ResourceClass.MEMORY_MB: 64,
            magic_rc.name: 512,
        }

        alloc_cands = self._get_allocation_candidates(
            resources=requested_resources)

        # Verify the allocation requests that are returned. There should be 2
        # allocation requests, one for each compute node, containing 3
        # resources in each allocation request, one each for VCPU, RAM, and
        # MAGIC. The amounts of the requests should correspond to the requested
        # resource amounts in the filter:resources dict passed to
        # AllocationCandidates.get_by_filters(). The providers for VCPU and
        # MEMORY_MB should be the compute nodes while the provider for the
        # MAGIC should be the shared custom resource provider.
        expected = [
            [('cn1', fields.ResourceClass.VCPU, 1),
             ('cn1', fields.ResourceClass.MEMORY_MB, 64),
             ('shared custom resource provider', magic_rc.name, 512)],
            [('cn2', fields.ResourceClass.VCPU, 1),
             ('cn2', fields.ResourceClass.MEMORY_MB, 64),
             ('shared custom resource provider', magic_rc.name, 512)],
        ]
        self._validate_allocation_requests(expected, alloc_cands)

    def test_mix_local_and_shared(self):
        # The aggregate that will be associated to shared storage pool
        agg_uuid = uuids.agg

        # Create three compute node providers with VCPU and RAM, but only
        # the third compute node has DISK. The first two computes will
        # share the storage from the shared storage pool.
        for name in ('cn1', 'cn2', 'cn3'):
            cn = self._create_provider(name)
            _add_inventory(cn, fields.ResourceClass.VCPU, 24,
                           allocation_ratio=16.0)
            _add_inventory(cn, fields.ResourceClass.MEMORY_MB, 1024,
                           min_unit=64, allocation_ratio=1.5)
            if name == 'cn3':
                _add_inventory(cn, fields.ResourceClass.DISK_GB, 2000,
                               reserved=100, min_unit=10)
            else:
                cn.set_aggregates([agg_uuid])

        # Create the shared storage pool
        ss = self._create_provider('shared storage')

        # Give the shared storage pool some inventory of DISK_GB
        _add_inventory(ss, fields.ResourceClass.DISK_GB, 2000, reserved=100,
                       min_unit=10)

        _set_traits(ss, "MISC_SHARES_VIA_AGGREGATE")

        # Put the ss RP in the same aggregate as the first two compute nodes
        ss.set_aggregates([agg_uuid])

        alloc_cands = self._get_allocation_candidates()

        # Expect cn1, cn2, cn3 and ss in the summaries
        self.assertEqual(
            set([uuids.cn1, uuids.cn2, ss.uuid, uuids.cn3]),
            _provider_uuids_from_iterable(alloc_cands.provider_summaries))

        # Expect three allocation requests: (cn1, ss), (cn2, ss), (cn3)
        expected = [
            [('cn1', fields.ResourceClass.VCPU, 1),
             ('cn1', fields.ResourceClass.MEMORY_MB, 64),
             ('shared storage', fields.ResourceClass.DISK_GB, 1500)],
            [('cn2', fields.ResourceClass.VCPU, 1),
             ('cn2', fields.ResourceClass.MEMORY_MB, 64),
             ('shared storage', fields.ResourceClass.DISK_GB, 1500)],
            [('cn3', fields.ResourceClass.VCPU, 1),
             ('cn3', fields.ResourceClass.MEMORY_MB, 64),
             ('cn3', fields.ResourceClass.DISK_GB, 1500)],
        ]
        self._validate_allocation_requests(expected, alloc_cands)

    def test_common_rc(self):
        """Candidates when cn and shared have inventory in the same class."""
        cn = self._create_provider('cn', uuids.agg1)
        _add_inventory(cn, fields.ResourceClass.VCPU, 24)
        _add_inventory(cn, fields.ResourceClass.MEMORY_MB, 2048)
        _add_inventory(cn, fields.ResourceClass.DISK_GB, 1600)

        ss = self._create_provider('ss', uuids.agg1)
        _set_traits(ss, "MISC_SHARES_VIA_AGGREGATE")
        _add_inventory(ss, fields.ResourceClass.DISK_GB, 1600)

        alloc_cands = self._get_allocation_candidates()

        # One allocation_request should have cn + ss; the other should have
        # just the cn.
        expected = [
            [('cn', fields.ResourceClass.VCPU, 1),
             ('cn', fields.ResourceClass.MEMORY_MB, 64),
             ('cn', fields.ResourceClass.DISK_GB, 1500)],
            # TODO(efried): Due to bug #1724613, the cn + ss candidate is not
            # returned.  Uncomment this when the bug is fixed.
            # [('cn', fields.ResourceClass.VCPU, 1),
            #  ('cn', fields.ResourceClass.MEMORY_MB, 64),
            #  ('ss', fields.ResourceClass.DISK_GB, 1500)],
        ]

        self._validate_allocation_requests(expected, alloc_cands)

    def test_common_rc_traits_split(self):
        """Validate filters when traits are split across cn and shared RPs."""
        # NOTE(efried): This test case only applies to the scenario where we're
        # requesting resources via the RequestGroup where
        # use_same_provider=False

        cn = self._create_provider('cn', uuids.agg1)
        _add_inventory(cn, fields.ResourceClass.VCPU, 24)
        _add_inventory(cn, fields.ResourceClass.MEMORY_MB, 2048)
        _add_inventory(cn, fields.ResourceClass.DISK_GB, 1600)
        # The compute node's disk is SSD
        _set_traits(cn, 'HW_CPU_X86_SSE', 'STORAGE_DISK_SSD')

        ss = self._create_provider('ss', uuids.agg1)
        _add_inventory(ss, fields.ResourceClass.DISK_GB, 1600)
        # The shared storage's disk is RAID
        _set_traits(ss, 'MISC_SHARES_VIA_AGGREGATE', 'CUSTOM_RAID')

        alloc_cands = rp_obj.AllocationCandidates.get_by_filters(
            self.ctx, filters={
                'resources': self.requested_resources,
                'traits': ['HW_CPU_X86_SSE', 'STORAGE_DISK_SSD', 'CUSTOM_RAID']
            }
        )

        # TODO(efried): Okay, bear with me here:
        # TODO(efried): Bug #1724633: we'd *like* to get no candidates, because
        # there's no single DISK_GB resource with both STORAGE_DISK_SSD and
        # CUSTOM_RAID traits.  So this is the ideal expected value:
        # expected = []
        # TODO(efried): But under the design as currently conceived, we would
        # get the cn + ss candidate, because that combination satisfies both
        # traits:
        # expected = [
        #     [('cn', fields.ResourceClass.VCPU, 1),
        #      ('cn', fields.ResourceClass.MEMORY_MB, 64),
        #      ('ss', fields.ResourceClass.DISK_GB, 1500)],
        # ]
        # TODO(efried): However, until https://review.openstack.org/#/c/479766/
        # lands, the traits are ignored, so this behaves just like
        # test_common_rc above, which is subject to bug #1724613:
        expected = [
            [('cn', fields.ResourceClass.VCPU, 1),
             ('cn', fields.ResourceClass.MEMORY_MB, 64),
             ('cn', fields.ResourceClass.DISK_GB, 1500)],
        ]

        self._validate_allocation_requests(expected, alloc_cands)
