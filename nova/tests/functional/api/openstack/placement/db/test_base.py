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
"""Base class and convenience utilities for functional placement tests."""


from oslo_utils import uuidutils

from nova.api.openstack.placement import exception
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova import context
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


def _allocate_from_provider(rp, rc, used):
    # NOTE(efried): Always use a random consumer UUID - we don't want to
    # override any existing allocations from the test case.
    rp_obj.AllocationList(
        rp._context, objects=[
            rp_obj.Allocation(
                rp._context, resource_provider=rp, resource_class=rc,
                consumer_id=uuidutils.generate_uuid(), used=used)]
    ).create_all()


class PlacementDbBaseTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(PlacementDbBaseTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.api_db = self.useFixture(fixtures.Database(database='api'))
        # Reset the _TRAITS_SYNCED global before we start and after
        # we are done since other tests (notably the gabbi tests)
        # may have caused it to change.
        self._reset_traits_synced()
        self.addCleanup(self._reset_traits_synced)
        self.ctx = context.RequestContext('fake-user', 'fake-project')
        # For debugging purposes, populated by _create_provider and used by
        # _validate_allocation_requests to make failure results more readable.
        self.rp_uuid_to_name = {}

    @staticmethod
    def _reset_traits_synced():
        """Reset the _TRAITS_SYNCED boolean to base state."""
        rp_obj._TRAITS_SYNCED = False

    def _create_provider(self, name, *aggs, **kwargs):
        parent = kwargs.get('parent')
        rp = rp_obj.ResourceProvider(self.ctx, name=name,
                                     uuid=getattr(uuids, name))
        if parent:
            rp.parent_provider_uuid = parent
        rp.create()
        if aggs:
            rp.set_aggregates(aggs)
        self.rp_uuid_to_name[rp.uuid] = name
        return rp

    def _make_allocation(self, inv_dict, alloc_dict):
        rp_uuid = uuids.allocation_resource_provider
        rp = rp_obj.ResourceProvider(
            context=self.ctx,
            uuid=rp_uuid,
            name=rp_uuid)
        rp.create()
        disk_inv = rp_obj.Inventory(context=self.ctx,
                resource_provider=rp, **inv_dict)
        inv_list = rp_obj.InventoryList(objects=[disk_inv])
        rp.set_inventory(inv_list)
        alloc = rp_obj.Allocation(self.ctx, resource_provider=rp,
                **alloc_dict)
        alloc_list = rp_obj.AllocationList(self.ctx, objects=[alloc])
        alloc_list.create_all()
        return rp, alloc
