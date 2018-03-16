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

from nova.api.openstack.placement import deploy
from nova.api.openstack.placement import exception
from nova.api.openstack.placement.objects import consumer as consumer_obj
from nova.api.openstack.placement.objects import project as project_obj
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.api.openstack.placement.objects import user as user_obj
from nova import context
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel as uuids


def add_inventory(rp, rc, total, **kwargs):
    kwargs.setdefault('max_unit', total)
    inv = rp_obj.Inventory(rp._context, resource_provider=rp,
                           resource_class=rc, total=total, **kwargs)
    inv.obj_set_defaults()
    rp.add_inventory(inv)
    return inv


def set_traits(rp, *traits):
    tlist = []
    for tname in traits:
        try:
            trait = rp_obj.Trait.get_by_name(rp._context, tname)
        except exception.TraitNotFound:
            trait = rp_obj.Trait(rp._context, name=tname)
            trait.create()
        tlist.append(trait)
    rp.set_traits(rp_obj.TraitList(objects=tlist))
    return tlist


class PlacementDbBaseTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(PlacementDbBaseTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.placement_db = self.useFixture(
                fixtures.Database(database='placement'))
        self.ctx = context.RequestContext('fake-user', 'fake-project')
        self.user_obj = user_obj.User(self.ctx, external_id='fake-user')
        self.user_obj.create()
        self.project_obj = project_obj.Project(
            self.ctx, external_id='fake-project')
        self.project_obj.create()
        # Do database syncs, such as traits sync.
        deploy.update_database()
        # For debugging purposes, populated by _create_provider and used by
        # _validate_allocation_requests to make failure results more readable.
        self.rp_uuid_to_name = {}

    def _create_provider(self, name, *aggs, **kwargs):
        parent = kwargs.get('parent')
        root = kwargs.get('root')
        uuid = kwargs.get('uuid', getattr(uuids, name))
        rp = rp_obj.ResourceProvider(self.ctx, name=name, uuid=uuid)
        if parent:
            rp.parent_provider_uuid = parent
        if root:
            rp.root_provider_uuid = root
        rp.create()
        if aggs:
            rp.set_aggregates(aggs)
        self.rp_uuid_to_name[rp.uuid] = name
        return rp

    def allocate_from_provider(self, rp, rc, used, consumer_id=None,
                               consumer=None):
        # NOTE(efried): If not specified, use a random consumer UUID - we don't
        # want to override any existing allocations from the test case.
        consumer_id = consumer_id or uuidutils.generate_uuid()
        if consumer is None:
            try:
                consumer = consumer_obj.Consumer.get_by_uuid(
                    self.ctx, consumer_id)
            except exception.NotFound:
                consumer = consumer_obj.Consumer(
                    self.ctx, uuid=consumer_id, user=self.user_obj,
                    project=self.project_obj)
                consumer.create()
        alloc_list = rp_obj.AllocationList(
            self.ctx, objects=[
                rp_obj.Allocation(
                    self.ctx, resource_provider=rp, resource_class=rc,
                    consumer=consumer, used=used)]
        )
        alloc_list.create_all()
        return alloc_list

    def _make_allocation(self, inv_dict, alloc_dict):
        rp = self._create_provider('allocation_resource_provider')
        disk_inv = rp_obj.Inventory(context=self.ctx,
                resource_provider=rp, **inv_dict)
        inv_list = rp_obj.InventoryList(objects=[disk_inv])
        rp.set_inventory(inv_list)
        consumer_id = alloc_dict['consumer_id']
        try:
            c = consumer_obj.Consumer.get_by_uuid(self.ctx, consumer_id)
        except exception.NotFound:
            c = consumer_obj.Consumer(
                self.ctx, uuid=consumer_id, user=self.user_obj,
                project=self.project_obj)
            c.create()
        alloc = rp_obj.Allocation(self.ctx, resource_provider=rp,
                consumer=c, **alloc_dict)
        alloc_list = rp_obj.AllocationList(self.ctx, objects=[alloc])
        alloc_list.create_all()
        return rp, alloc
