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

import collections
import copy
# NOTE(cdent): The resource provider objects are designed to never be
# used over RPC. Remote manipulation is done with the placement HTTP
# API. The 'remotable' decorators should not be used.

import os_traits
from oslo_concurrency import lockutils
from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import versionutils
import six
import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import contains_eager
from sqlalchemy import sql
from sqlalchemy.sql import null

from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models as models
from nova.db.sqlalchemy import resource_class_cache as rc_cache
from nova import exception
from nova.i18n import _, _LW
from nova import objects
from nova.objects import base
from nova.objects import fields

_TRAIT_TBL = models.Trait.__table__
_ALLOC_TBL = models.Allocation.__table__
_INV_TBL = models.Inventory.__table__
_RP_TBL = models.ResourceProvider.__table__
_RC_TBL = models.ResourceClass.__table__
_AGG_TBL = models.PlacementAggregate.__table__
_RP_AGG_TBL = models.ResourceProviderAggregate.__table__
_RP_TRAIT_TBL = models.ResourceProviderTrait.__table__
_PROJECT_TBL = models.Project.__table__
_USER_TBL = models.User.__table__
_CONSUMER_TBL = models.Consumer.__table__
_RC_CACHE = None
_TRAIT_LOCK = 'trait_sync'
_TRAITS_SYNCED = False

LOG = logging.getLogger(__name__)


@db_api.api_context_manager.reader
def _ensure_rc_cache(ctx):
    """Ensures that a singleton resource class cache has been created in the
    module's scope.

    :param ctx: `nova.context.RequestContext` that may be used to grab a DB
                connection.
    """
    global _RC_CACHE
    if _RC_CACHE is not None:
        return
    _RC_CACHE = rc_cache.ResourceClassCache(ctx)


@oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
@db_api.api_context_manager.writer
def _trait_sync(ctx):
    """Sync the os_traits symbols to the database.

    Reads all symbols from the os_traits library, checks if any of them do
    not exist in the database and bulk-inserts those that are not. This is
    done once per process using this code if either Trait.get_by_name or
    TraitList.get_all is called.

    :param ctx: `nova.context.RequestContext` that may be used to grab a DB
                connection.
    """
    # Create a set of all traits in the os_traits library.
    std_traits = set(os_traits.get_traits())
    conn = ctx.session.connection()
    sel = sa.select([_TRAIT_TBL.c.name])
    res = conn.execute(sel).fetchall()
    # Create a set of all traits in the db that are not custom
    # traits.
    db_traits = set(
        r[0] for r in res
        if not os_traits.is_custom(r[0])
    )
    # Determine those traits which are in os_traits but not
    # currently in the database, and insert them.
    need_sync = std_traits - db_traits
    ins = _TRAIT_TBL.insert()
    batch_args = [
        {'name': six.text_type(trait)}
        for trait in need_sync
    ]
    if batch_args:
        try:
            conn.execute(ins, batch_args)
            LOG.info("Synced traits from os_traits into API DB: %s",
                     need_sync)
        except db_exc.DBDuplicateEntry:
            pass  # some other process sync'd, just ignore


def _ensure_trait_sync(ctx):
    """Ensures that the os_traits library is synchronized to the traits db.

    If _TRAITS_SYNCED is False then this process has not tried to update the
    traits db. Do so by calling _trait_sync. Since the placement API server
    could be multi-threaded, lock around testing _TRAITS_SYNCED to avoid
    duplicating work.

    Different placement API server processes that talk to the same database
    will avoid issues through the power of transactions.

    :param ctx: `nova.context.RequestContext` that may be used to grab a DB
                connection.
    """
    global _TRAITS_SYNCED
    # If another thread is doing this work, wait for it to complete.
    # When that thread is done _TRAITS_SYNCED will be true in this
    # thread and we'll simply return.
    with lockutils.lock(_TRAIT_LOCK):
        if not _TRAITS_SYNCED:
            _trait_sync(ctx)
            _TRAITS_SYNCED = True


def _get_current_inventory_resources(conn, rp):
    """Returns a set() containing the resource class IDs for all resources
    currently having an inventory record for the supplied resource provider.

    :param conn: DB connection to use.
    :param rp: Resource provider to query inventory for.
    """
    cur_res_sel = sa.select([_INV_TBL.c.resource_class_id]).where(
            _INV_TBL.c.resource_provider_id == rp.id)
    existing_resources = conn.execute(cur_res_sel).fetchall()
    return set([r[0] for r in existing_resources])


def _delete_inventory_from_provider(conn, rp, to_delete):
    """Deletes any inventory records from the supplied provider and set() of
    resource class identifiers.

    If there are allocations for any of the inventories to be deleted raise
    InventoryInUse exception.

    :param conn: DB connection to use.
    :param rp: Resource provider from which to delete inventory.
    :param to_delete: set() containing resource class IDs for records to
                      delete.
    """
    allocation_query = sa.select(
        [_ALLOC_TBL.c.resource_class_id.label('resource_class')]).where(
             sa.and_(_ALLOC_TBL.c.resource_provider_id == rp.id,
                     _ALLOC_TBL.c.resource_class_id.in_(to_delete))
         ).group_by(_ALLOC_TBL.c.resource_class_id)
    allocations = conn.execute(allocation_query).fetchall()
    if allocations:
        resource_classes = ', '.join([_RC_CACHE.string_from_id(alloc[0])
                                      for alloc in allocations])
        raise exception.InventoryInUse(resource_classes=resource_classes,
                                       resource_provider=rp.uuid)

    del_stmt = _INV_TBL.delete().where(sa.and_(
            _INV_TBL.c.resource_provider_id == rp.id,
            _INV_TBL.c.resource_class_id.in_(to_delete)))
    res = conn.execute(del_stmt)
    return res.rowcount


def _add_inventory_to_provider(conn, rp, inv_list, to_add):
    """Inserts new inventory records for the supplied resource provider.

    :param conn: DB connection to use.
    :param rp: Resource provider to add inventory to.
    :param inv_list: InventoryList object
    :param to_add: set() containing resource class IDs to search inv_list for
                   adding to resource provider.
    """
    for rc_id in to_add:
        rc_str = _RC_CACHE.string_from_id(rc_id)
        inv_record = inv_list.find(rc_str)
        if inv_record.capacity <= 0:
            raise exception.InvalidInventoryCapacity(
                resource_class=rc_str,
                resource_provider=rp.uuid)
        ins_stmt = _INV_TBL.insert().values(
                resource_provider_id=rp.id,
                resource_class_id=rc_id,
                total=inv_record.total,
                reserved=inv_record.reserved,
                min_unit=inv_record.min_unit,
                max_unit=inv_record.max_unit,
                step_size=inv_record.step_size,
                allocation_ratio=inv_record.allocation_ratio)
        conn.execute(ins_stmt)


def _update_inventory_for_provider(conn, rp, inv_list, to_update):
    """Updates existing inventory records for the supplied resource provider.

    :param conn: DB connection to use.
    :param rp: Resource provider on which to update inventory.
    :param inv_list: InventoryList object
    :param to_update: set() containing resource class IDs to search inv_list
                      for updating in resource provider.
    :returns: A list of (uuid, class) tuples that have exceeded their
              capacity after this inventory update.
    """
    exceeded = []
    for rc_id in to_update:
        rc_str = _RC_CACHE.string_from_id(rc_id)
        inv_record = inv_list.find(rc_str)
        if inv_record.capacity <= 0:
            raise exception.InvalidInventoryCapacity(
                resource_class=rc_str,
                resource_provider=rp.uuid)
        allocation_query = sa.select(
            [func.sum(_ALLOC_TBL.c.used).label('usage')]).\
            where(sa.and_(
                _ALLOC_TBL.c.resource_provider_id == rp.id,
                _ALLOC_TBL.c.resource_class_id == rc_id))
        allocations = conn.execute(allocation_query).first()
        if (allocations
            and allocations['usage'] is not None
            and allocations['usage'] > inv_record.capacity):
            exceeded.append((rp.uuid, rc_str))
        upd_stmt = _INV_TBL.update().where(sa.and_(
                _INV_TBL.c.resource_provider_id == rp.id,
                _INV_TBL.c.resource_class_id == rc_id)).values(
                        total=inv_record.total,
                        reserved=inv_record.reserved,
                        min_unit=inv_record.min_unit,
                        max_unit=inv_record.max_unit,
                        step_size=inv_record.step_size,
                        allocation_ratio=inv_record.allocation_ratio)
        res = conn.execute(upd_stmt)
        if not res.rowcount:
            raise exception.InventoryWithResourceClassNotFound(
                    resource_class=rc_str)
    return exceeded


def _increment_provider_generation(conn, rp):
    """Increments the supplied provider's generation value, supplying the
    currently-known generation. Returns whether the increment succeeded.

    :param conn: DB connection to use.
    :param rp: `ResourceProvider` whose generation should be updated.
    :returns: The new resource provider generation value if successful.
    :raises nova.exception.ConcurrentUpdateDetected: if another thread updated
            the same resource provider's view of its inventory or allocations
            in between the time when this object was originally read
            and the call to set the inventory.
    """
    rp_gen = rp.generation
    new_generation = rp_gen + 1
    upd_stmt = _RP_TBL.update().where(sa.and_(
            _RP_TBL.c.id == rp.id,
            _RP_TBL.c.generation == rp_gen)).values(
                    generation=(new_generation))

    res = conn.execute(upd_stmt)
    if res.rowcount != 1:
        raise exception.ConcurrentUpdateDetected
    return new_generation


@db_api.api_context_manager.writer
def _add_inventory(context, rp, inventory):
    """Add one Inventory that wasn't already on the provider.

    :raises `exception.ResourceClassNotFound` if inventory.resource_class
            cannot be found in either the standard classes or the DB.
    """
    _ensure_rc_cache(context)
    rc_id = _RC_CACHE.id_from_string(inventory.resource_class)
    inv_list = InventoryList(objects=[inventory])
    conn = context.session.connection()
    with conn.begin():
        _add_inventory_to_provider(
            conn, rp, inv_list, set([rc_id]))
        rp.generation = _increment_provider_generation(conn, rp)


@db_api.api_context_manager.writer
def _update_inventory(context, rp, inventory):
    """Update an inventory already on the provider.

    :raises `exception.ResourceClassNotFound` if inventory.resource_class
            cannot be found in either the standard classes or the DB.
    """
    _ensure_rc_cache(context)
    rc_id = _RC_CACHE.id_from_string(inventory.resource_class)
    inv_list = InventoryList(objects=[inventory])
    conn = context.session.connection()
    with conn.begin():
        exceeded = _update_inventory_for_provider(
            conn, rp, inv_list, set([rc_id]))
        rp.generation = _increment_provider_generation(conn, rp)
    return exceeded


@db_api.api_context_manager.writer
def _delete_inventory(context, rp, resource_class):
    """Delete up to one Inventory of the given resource_class string.

    :raises `exception.ResourceClassNotFound` if resource_class
            cannot be found in either the standard classes or the DB.
    """
    _ensure_rc_cache(context)
    conn = context.session.connection()
    rc_id = _RC_CACHE.id_from_string(resource_class)
    with conn.begin():
        if not _delete_inventory_from_provider(conn, rp, [rc_id]):
            raise exception.NotFound(
                'No inventory of class %s found for delete'
                % resource_class)
        rp.generation = _increment_provider_generation(conn, rp)


@db_api.api_context_manager.writer
def _set_inventory(context, rp, inv_list):
    """Given an InventoryList object, replaces the inventory of the
    resource provider in a safe, atomic fashion using the resource
    provider's generation as a consistent view marker.

    :param context: Nova RequestContext.
    :param rp: `ResourceProvider` object upon which to set inventory.
    :param inv_list: `InventoryList` object to save to backend storage.
    :returns: A list of (uuid, class) tuples that have exceeded their
              capacity after this inventory update.
    :raises nova.exception.ConcurrentUpdateDetected: if another thread updated
            the same resource provider's view of its inventory or allocations
            in between the time when this object was originally read
            and the call to set the inventory.
    :raises `exception.ResourceClassNotFound` if any resource class in any
            inventory in inv_list cannot be found in either the standard
            classes or the DB.
    :raises `exception.InventoryInUse` if we attempt to delete inventory
            from a provider that has allocations for that resource class.
    """
    _ensure_rc_cache(context)
    conn = context.session.connection()

    existing_resources = _get_current_inventory_resources(conn, rp)
    these_resources = set([_RC_CACHE.id_from_string(r.resource_class)
                           for r in inv_list.objects])

    # Determine which resources we should be adding, deleting and/or
    # updating in the resource provider's inventory by comparing sets
    # of resource class identifiers.
    to_add = these_resources - existing_resources
    to_delete = existing_resources - these_resources
    to_update = these_resources & existing_resources
    exceeded = []

    with conn.begin():
        if to_delete:
            _delete_inventory_from_provider(conn, rp, to_delete)
        if to_add:
            _add_inventory_to_provider(conn, rp, inv_list, to_add)
        if to_update:
            exceeded = _update_inventory_for_provider(conn, rp, inv_list,
                                                      to_update)

        # Here is where we update the resource provider's generation value.
        # If this update updates zero rows, that means that another
        # thread has updated the inventory for this resource provider
        # between the time the caller originally read the resource provider
        # record and inventory information and this point. We raise an
        # exception here which will rollback the above transaction and
        # return an error to the caller to indicate that they can attempt
        # to retry the inventory save after reverifying any capacity
        # conditions and re-reading the existing inventory information.
        rp.generation = _increment_provider_generation(conn, rp)

    return exceeded


@base.NovaObjectRegistry.register
class ResourceProvider(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add destroy()
    # Version 1.2: Add get_aggregates(), set_aggregates()
    # Version 1.3: Turn off remotable
    # Version 1.4: Add set/get_traits methods
    VERSION = '1.4'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(nullable=False),
        'name': fields.StringField(nullable=False),
        'generation': fields.IntegerField(nullable=False),
    }

    def create(self):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        if 'uuid' not in self:
            raise exception.ObjectActionError(action='create',
                                              reason='uuid is required')
        if 'name' not in self:
            raise exception.ObjectActionError(action='create',
                                              reason='name is required')
        updates = self.obj_get_changes()
        db_rp = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_rp)

    def destroy(self):
        self._delete(self._context, self.id)

    def save(self):
        updates = self.obj_get_changes()
        if updates and list(updates.keys()) != ['name']:
            raise exception.ObjectActionError(
                action='save',
                reason='Immutable fields changed')
        self._update_in_db(self._context, self.id, updates)

    @classmethod
    def get_by_uuid(cls, context, uuid):
        db_resource_provider = cls._get_by_uuid_from_db(context, uuid)
        return cls._from_db_object(context, cls(), db_resource_provider)

    def add_inventory(self, inventory):
        """Add one new Inventory to the resource provider.

        Fails if Inventory of the provided resource class is
        already present.
        """
        _add_inventory(self._context, self, inventory)
        self.obj_reset_changes()

    def delete_inventory(self, resource_class):
        """Delete Inventory of provided resource_class."""
        _delete_inventory(self._context, self, resource_class)
        self.obj_reset_changes()

    def set_inventory(self, inv_list):
        """Set all resource provider Inventory to be the provided list."""
        exceeded = _set_inventory(self._context, self, inv_list)
        for uuid, rclass in exceeded:
            LOG.warning(_LW('Resource provider %(uuid)s is now over-'
                            'capacity for %(resource)s'),
                        {'uuid': uuid, 'resource': rclass})
        self.obj_reset_changes()

    def update_inventory(self, inventory):
        """Update one existing Inventory of the same resource class.

        Fails if no Inventory of the same class is present.
        """
        exceeded = _update_inventory(self._context, self, inventory)
        for uuid, rclass in exceeded:
            LOG.warning(_LW('Resource provider %(uuid)s is now over-'
                            'capacity for %(resource)s'),
                        {'uuid': uuid, 'resource': rclass})
        self.obj_reset_changes()

    def get_aggregates(self):
        """Get the aggregate uuids associated with this resource provider."""
        return self._get_aggregates(self._context, self.id)

    def set_aggregates(self, aggregate_uuids):
        """Set the aggregate uuids associated with this resource provider.

        If an aggregate does not exist, one will be created using the
        provided uuid.
        """
        self._set_aggregates(self._context, self.id, aggregate_uuids)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        db_rp = models.ResourceProvider()
        db_rp.update(updates)
        context.session.add(db_rp)
        return db_rp

    @staticmethod
    @db_api.api_context_manager.writer
    def _delete(context, _id):
        # Don't delete the resource provider if it has allocations.
        rp_allocations = context.session.query(models.Allocation).filter(
                models.Allocation.resource_provider_id == _id).count()
        if rp_allocations:
            raise exception.ResourceProviderInUse()
        # Delete any inventory associated with the resource provider
        context.session.query(models.Inventory).\
            filter(models.Inventory.resource_provider_id == _id).delete()
        # Delete any aggregate associations for the resource provider
        # The name substitution on the next line is needed to satisfy pep8
        RPA_model = models.ResourceProviderAggregate
        context.session.query(RPA_model).\
                filter(RPA_model.resource_provider_id == _id).delete()
        # delete any trait associations for the resource provider
        RPT_model = models.ResourceProviderTrait
        context.session.query(RPT_model).\
                filter(RPT_model.resource_provider_id == _id).delete()
        # Now delete the RP records
        result = context.session.query(models.ResourceProvider).\
                 filter(models.ResourceProvider.id == _id).delete()
        if not result:
            raise exception.NotFound()

    @staticmethod
    @db_api.api_context_manager.writer
    def _update_in_db(context, id, updates):
        db_rp = context.session.query(models.ResourceProvider).filter_by(
            id=id).first()
        db_rp.update(updates)
        db_rp.save(context.session)

    @staticmethod
    def _from_db_object(context, resource_provider, db_resource_provider):
        for field in resource_provider.fields:
            setattr(resource_provider, field, db_resource_provider[field])
        resource_provider._context = context
        resource_provider.obj_reset_changes()
        return resource_provider

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_uuid_from_db(context, uuid):
        result = context.session.query(models.ResourceProvider).filter_by(
            uuid=uuid).first()
        if not result:
            raise exception.NotFound(
            'No resource provider with uuid %s found'
            % uuid)
        return result

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_aggregates(context, rp_id):
        conn = context.session.connection()
        join_statement = sa.join(
            _AGG_TBL, _RP_AGG_TBL, sa.and_(
                _AGG_TBL.c.id == _RP_AGG_TBL.c.aggregate_id,
                _RP_AGG_TBL.c.resource_provider_id == rp_id))
        sel = sa.select([_AGG_TBL.c.uuid]).select_from(join_statement)
        return [r[0] for r in conn.execute(sel).fetchall()]

    @classmethod
    @db_api.api_context_manager.writer
    def _set_aggregates(cls, context, rp_id, provided_aggregates):
        # When aggregate uuids are persisted no validation is done
        # to ensure that they refer to something that has meaning
        # elsewhere. It is assumed that code which makes use of the
        # aggregates, later, will validate their fitness.
        # TODO(cdent): At the moment we do not delete
        # a PlacementAggregate that no longer has any associations
        # with at least one resource provider. We may wish to do that
        # to avoid bloat if it turns out we're creating a lot of noise.
        # Not doing now to move things along.
        provided_aggregates = set(provided_aggregates)
        existing_aggregates = set(cls._get_aggregates(context, rp_id))
        to_add = provided_aggregates - existing_aggregates
        target_aggregates = list(provided_aggregates)

        # Create any aggregates that do not yet exist in
        # PlacementAggregates. This is different from
        # the set in existing_aggregates; those are aggregates for
        # which there are associations for the resource provider
        # at rp_id. The following loop checks for the existence of any
        # aggregate with the provided uuid. In this way we only
        # create a new row in the PlacementAggregate table if the
        # aggregate uuid has never been seen before. Code further
        # below will update the associations.
        for agg_uuid in to_add:
            found_agg = context.session.query(models.PlacementAggregate.uuid).\
                filter_by(uuid=agg_uuid).first()
            if not found_agg:
                new_aggregate = models.PlacementAggregate(uuid=agg_uuid)
                try:
                    context.session.add(new_aggregate)
                    # Flush each aggregate to explicitly call the INSERT
                    # statement that could result in an integrity error
                    # if some other thread has added this agg_uuid. This
                    # also makes sure that the new aggregates have
                    # ids when the SELECT below happens.
                    context.session.flush()
                except db_exc.DBDuplicateEntry:
                    # Something else has already added this agg_uuid
                    pass

        # Remove all aggregate associations so we can refresh them
        # below. This means that all associations are added, but the
        # aggregates themselves stay around.
        context.session.query(models.ResourceProviderAggregate).filter_by(
            resource_provider_id=rp_id).delete()

        # Set resource_provider_id, aggregate_id pairs to
        # ResourceProviderAggregate table.
        if target_aggregates:
            select_agg_id = sa.select([rp_id, models.PlacementAggregate.id]).\
                where(models.PlacementAggregate.uuid.in_(target_aggregates))
            insert_aggregates = models.ResourceProviderAggregate.__table__.\
                insert().from_select(['resource_provider_id', 'aggregate_id'],
                                     select_agg_id)
            conn = context.session.connection()
            conn.execute(insert_aggregates)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_traits_from_db(context, _id):
        db_traits = context.session.query(models.Trait).join(
            models.ResourceProviderTrait,
            sa.and_(
                models.Trait.id == models.ResourceProviderTrait.trait_id,
                models.ResourceProviderTrait.resource_provider_id == _id
            )).all()
        return db_traits

    @base.remotable
    def get_traits(self):
        db_traits = self._get_traits_from_db(self._context, self.id)
        return base.obj_make_list(self._context, TraitList(self._context),
            Trait, db_traits)

    @staticmethod
    @db_api.api_context_manager.writer
    def _set_traits_to_db(context, rp, _id, traits):
        existing_traits = ResourceProvider._get_traits_from_db(context, _id)
        traits_dict = {trait.name: trait for trait in traits}
        existing_traits_dict = {trait.name: trait for trait in existing_traits}

        to_add_names = (set(traits_dict.keys()) -
            set(existing_traits_dict.keys()))
        to_delete_names = (set(existing_traits_dict.keys()) -
            set(traits_dict.keys()))
        to_delete_ids = [existing_traits_dict[name].id
                            for name in to_delete_names]

        conn = context.session.connection()
        with conn.begin():
            if to_delete_names:
                context.session.query(models.ResourceProviderTrait).filter(
                    sa.and_(
                        models.ResourceProviderTrait.trait_id.in_(
                            to_delete_ids),
                        (models.ResourceProviderTrait.resource_provider_id ==
                         _id)
                    )
                ).delete(synchronize_session='fetch')
            if to_add_names:
                for name in to_add_names:
                    rp_trait = models.ResourceProviderTrait()
                    rp_trait.trait_id = traits_dict[name].id
                    rp_trait.resource_provider_id = _id
                    context.session.add(rp_trait)
            rp.generation = _increment_provider_generation(conn, rp)

    @base.remotable
    def set_traits(self, traits):
        self._set_traits_to_db(self._context, self, self.id, traits)


@db_api.api_context_manager.reader
def _get_providers_with_shared_capacity(ctx, rc_id, amount):
    """Returns a list of resource provider IDs (internal IDs, not UUIDs)
    that have capacity for a requested amount of a resource and indicate that
    they share resource via an aggregate association.

    Shared resource providers are marked with a standard trait called
    MISC_SHARES_VIA_AGGREGATE. This indicates that the provider allows its
    inventory to be consumed by other resource providers associated via an
    aggregate link.

    For example, assume we have two compute nodes, CN_1 and CN_2, each with
    inventory of VCPU and MEMORY_MB but not DISK_GB (in other words, these are
    compute nodes with no local disk). There is a resource provider called
    "NFS_SHARE" that has an inventory of DISK_GB and has the
    MISC_SHARES_VIA_AGGREGATE trait. Both the "CN_1" and "CN_2" compute node
    resource providers and the "NFS_SHARE" resource provider are associated
    with an aggregate called "AGG_1".

    The scheduler needs to determine the resource providers that can fulfill a
    request for 2 VCPU, 1024 MEMORY_MB and 100 DISK_GB.

    Clearly, no single provider can satisfy the request for all three
    resources, since neither compute node has DISK_GB inventory and the
    NFS_SHARE provider has no VCPU or MEMORY_MB inventories.

    However, if we consider the NFS_SHARE resource provider as providing
    inventory of DISK_GB for both CN_1 and CN_2, we can include CN_1 and CN_2
    as potential fits for the requested set of resources.

    To facilitate that matching query, this function returns all providers that
    indicate they share their inventory with providers in some aggregate and
    have enough capacity for the requested amount of a resource.

    To follow the example above, if we were to call
    _get_providers_with_shared_capacity(ctx, "DISK_GB", 100), we would want to
    get back the ID for the NFS_SHARE resource provider.
    """
    # The SQL we need to generate here looks like this:
    #
    # SELECT rp.id
    # FROM resource_providers AS rp
    #   INNER JOIN resource_provider_traits AS rpt
    #     ON rp.id = rpt.resource_provider_id
    #   INNER JOIN traits AS t
    #     AND rpt.trait_id = t.id
    #     AND t.name = "MISC_SHARES_VIA_AGGREGATE"
    #   INNER JOIN inventories AS inv
    #     ON rp.id = inv.resource_provider_id
    #     AND inv.resource_class_id = $rc_id
    #   LEFT JOIN (
    #     SELECT resource_provider_id, SUM(used) as used
    #     FROM allocations
    #     WHERE resource_class_id = $rc_id
    #     GROUP BY resource_provider_id
    #   ) AS usage
    #     ON rp.id = usage.resource_provider_id
    # WHERE COALESCE(usage.used, 0) + $amount <= (
    #   inv.total + inv.reserved) * inv.allocation_ratio
    # ) AND
    #   inv.min_unit <= $amount AND
    #   inv.max_unit >= $amount AND
    #   $amount % inv.step_size = 0
    # GROUP BY rp.id

    rp_tbl = sa.alias(_RP_TBL, name='rp')
    inv_tbl = sa.alias(_INV_TBL, name='inv')
    t_tbl = sa.alias(_TRAIT_TBL, name='t')
    rpt_tbl = sa.alias(_RP_TRAIT_TBL, name='rpt')

    rp_to_rpt_join = sa.join(
        rp_tbl, rpt_tbl,
        rp_tbl.c.id == rpt_tbl.c.resource_provider_id,
    )

    rpt_to_t_join = sa.join(
        rp_to_rpt_join, t_tbl,
        sa.and_(
            rpt_tbl.c.trait_id == t_tbl.c.id,
            # The traits table wants unicode trait names, but os_traits
            # presents native str, so we need to cast.
            t_tbl.c.name == six.text_type(os_traits.MISC_SHARES_VIA_AGGREGATE),
        ),
    )

    rp_to_inv_join = sa.join(
        rpt_to_t_join, inv_tbl,
        sa.and_(
            rpt_tbl.c.resource_provider_id == inv_tbl.c.resource_provider_id,
            inv_tbl.c.resource_class_id == rc_id,
        ),
    )

    usage = sa.select([_ALLOC_TBL.c.resource_provider_id,
                       sql.func.sum(_ALLOC_TBL.c.used).label('used')])
    usage = usage.where(_ALLOC_TBL.c.resource_class_id == rc_id)
    usage = usage.group_by(_ALLOC_TBL.c.resource_provider_id)
    usage = sa.alias(usage, name='usage')

    inv_to_usage_join = sa.outerjoin(
        rp_to_inv_join, usage,
        inv_tbl.c.resource_provider_id == usage.c.resource_provider_id,
    )

    sel = sa.select([rp_tbl.c.id]).select_from(inv_to_usage_join)
    sel = sel.where(
        sa.and_(
            func.coalesce(usage.c.used, 0) + amount <= (
                inv_tbl.c.total - inv_tbl.c.reserved
            ) * inv_tbl.c.allocation_ratio,
            inv_tbl.c.min_unit <= amount,
            inv_tbl.c.max_unit >= amount,
            amount % inv_tbl.c.step_size == 0,
        ),
    )
    sel = sel.group_by(rp_tbl.c.id)
    return [r[0] for r in ctx.session.execute(sel)]


@db_api.api_context_manager.reader
def _get_all_with_shared(ctx, resources):
    """Uses some more advanced SQL to find providers that either have the
    requested resources "locally" or are associated with a provider that shares
    those requested resources.

    :param resources: Dict keyed by resource class integer ID of requested
                      amounts of that resource
    """
    # NOTE(jaypipes): The SQL we generate here depends on which resource
    # classes have providers that share that resource via an aggregate.
    #
    # We begin building a "join chain" by starting with a projection from the
    # resource_providers table:
    #
    # SELECT rp.id
    # FROM resource_providers AS rp
    #
    # in addition to a copy of resource_provider_aggregates for each resource
    # class that has a shared provider:
    #
    #  resource_provider_aggregates AS sharing_{RC_NAME},
    #
    # We then join to a copy of the inventories table for each resource we are
    # requesting:
    #
    # {JOIN TYPE} JOIN inventories AS inv_{RC_NAME}
    #  ON {JOINING TABLE}.id = inv_{RC_NAME}.resource_provider_id
    #  AND inv_{RC_NAME}.resource_class_id = $RC_ID
    # LEFT JOIN (
    #  SELECT resource_provider_id, SUM(used) AS used
    #  FROM allocations
    #  WHERE resource_class_id = $VCPU_ID
    #  GROUP BY resource_provider_id
    # ) AS usage_{RC_NAME}
    #  ON inv_{RC_NAME}.resource_provider_id = \
    #      usage_{RC_NAME}.resource_provider_id
    #
    # For resource classes that DO NOT have any shared resource providers, the
    # {JOIN TYPE} will be an INNER join, because we are filtering out any
    # resource providers that do not have local inventory of that resource
    # class.
    #
    # For resource classes that DO have shared resource providers, the {JOIN
    # TYPE} will be a LEFT (OUTER) join.
    #
    # For the first join, {JOINING TABLE} will be resource_providers. For each
    # subsequent resource class that is added to the SQL expression, {JOINING
    # TABLE} will be the alias of the inventories table that refers to the
    # previously-processed resource class.
    #
    # For resource classes that DO have shared providers, we also perform a
    # "butterfly join" against two copies of the resource_provider_aggregates
    # table:
    #
    # +-----------+  +------------+  +-------------+  +------------+
    # | last_inv  |  | rpa_shared |  | rpa_sharing |  | rp_sharing |
    # +-----------|  +------------+  +-------------+  +------------+
    # | rp_id     |=>| rp_id      |  | rp_id       |<=| id         |
    # |           |  | agg_id     |<=| agg_id      |  |            |
    # +-----------+  +------------+  +-------------+  +------------+
    #
    # Note in the diagram above, we call the _get_providers_sharing_capacity()
    # for a resource class to construct the "rp_sharing" set/table.
    #
    # The first part of the butterfly join is an outer join against a copy of
    # the resource_provider_aggregates table in order to winnow results to
    # providers that are associated with any aggregate that the sharing
    # provider is associated with:
    #
    # LEFT JOIN resource_provider_aggregates AS shared_{RC_NAME}
    #  ON {JOINING_TABLE}.id = shared_{RC_NAME}.resource_provider_id
    #
    # The above is then joined to the set of aggregates associated with the set
    # of sharing providers for that resource:
    #
    # LEFT JOIN resource_provider_aggregates AS sharing_{RC_NAME}
    #  ON shared_{RC_NAME}.aggregate_id = sharing_{RC_NAME}.aggregate_id
    #
    # We calculate the WHERE conditions based on whether the resource class has
    # any shared providers.
    #
    # For resource classes that DO NOT have any shared resource providers, the
    # WHERE clause constructed finds resource providers that have inventory for
    # "local" resource providers:
    #
    # WHERE (COALESCE(usage_vcpu.used, 0) + $AMOUNT <=
    #   (inv_{RC_NAME}.total + inv_{RC_NAME}.reserved)
    #   * inv_{RC_NAME}.allocation_ratio
    # AND
    # inv_{RC_NAME}.min_unit <= $AMOUNT AND
    # inv_{RC_NAME}.max_unit >= $AMOUNT AND
    # $AMOUNT_VCPU % inv_{RC_NAME}.step_size == 0)
    #
    # For resource classes that DO have shared resource providers, the WHERE
    # clause is slightly more complicated:
    #
    # WHERE (
    #   inv_{RC_NAME}.resource_provider_id IS NOT NULL AND
    #   (
    #     (
    #     COALESCE(usage_{RC_NAME}.used, 0) + $AMOUNT_VCPU <=
    #       (inv_{RC_NAME}.total + inv_{RC_NAME}.reserved)
    #       * inv_{RC_NAME}.allocation_ratio
    #     ) AND
    #     inv_{RC_NAME}.min_unit <= $AMOUNT_VCPU AND
    #     inv_{RC_NAME}.max_unit >= $AMOUNT_VCPU AND
    #     $AMOUNT_VCPU % inv_{RC_NAME}.step_size == 0
    #   ) OR
    #   sharing_{RC_NAME}.resource_provider_id IS NOT NULL
    # )
    #
    # Finally, we GROUP BY the resource provider ID:
    #
    # GROUP BY rp.id
    #
    # To show an example, here is the exact SQL that will be generated in an
    # environment that has a shared storage pool and compute nodes that have
    # vCPU and RAM associated with the same aggregate as the provider
    # representing the shared storage pool:
    #
    # SELECT rp.*
    # FROM resource_providers AS rp
    # INNER JOIN inventories AS inv_vcpu
    #  ON rp.id = inv_vcpu.resource_provider_id
    #  AND inv_vcpu.resource_class_id = $VCPU_ID
    # LEFT JOIN (
    #  SELECT resource_provider_id, SUM(used) AS used
    #  FROM allocations
    #  WHERE resource_class_id = $VCPU_ID
    #  GROUP BY resource_provider_id
    # ) AS usage_vcpu
    #  ON inv_vcpu.resource_provider_id = \
    #       usage_vcpu.resource_provider_id
    # INNER JOIN inventories AS inv_memory_mb
    # ON inv_vcpu.resource_provider_id = inv_memory_mb.resource_provider_id
    # AND inv_memory_mb.resource_class_id = $MEMORY_MB_ID
    # LEFT JOIN (
    #  SELECT resource_provider_id, SUM(used) AS used
    #  FROM allocations
    #  WHERE resource_class_id = $MEMORY_MB_ID
    #  GROUP BY resource_provider_id
    # ) AS usage_memory_mb
    #  ON inv_memory_mb.resource_provider_id = \
    #       usage_memory_mb.resource_provider_id
    # LEFT JOIN inventories AS inv_disk_gb
    #  ON inv_memory_mb.resource_provider_id = \
    #       inv_disk_gb.resource_provider_id
    #  AND inv_disk_gb.resource_class_id = $DISK_GB_ID
    # LEFT JOIN (
    #  SELECT resource_provider_id, SUM(used) AS used
    #  FROM allocations
    #  WHERE resource_class_id = $DISK_GB_ID
    #  GROUP BY resource_provider_id
    # ) AS usage_disk_gb
    #  ON inv_disk_gb.resource_provider_id = \
    #       usage_disk_gb.resource_provider_id
    # LEFT JOIN resource_provider_aggregates AS shared_disk_gb
    #  ON inv_memory_mb.resource_provider_id = \
    #       shared_disk.resource_provider_id
    # LEFT JOIN resource_provider_aggregates AS sharing_disk_gb
    #  ON shared_disk_gb.aggregate_id = sharing_disk_gb.aggregate_id
    # AND sharing_disk_gb.resource_provider_id IN ($RPS_SHARING_DISK)
    # WHERE (
    #   (
    #     COALESCE(usage_vcpu.used, 0) + $AMOUNT_VCPU <=
    #     (inv_vcpu.total + inv_vcpu.reserved)
    #     * inv_vcpu.allocation_ratio
    #   ) AND
    #   inv_vcpu.min_unit <= $AMOUNT_VCPU AND
    #   inv_vcpu.max_unit >= $AMOUNT_VCPU AND
    #   $AMOUNT_VCPU % inv_vcpu.step_size == 0
    # ) AND (
    #   (
    #     COALESCE(usage_memory_mb.used, 0) + $AMOUNT_VCPU <=
    #     (inv_memory_mb.total + inv_memory_mb.reserved)
    #     * inv_memory_mb.allocation_ratio
    #   ) AND
    #   inv_memory_mb.min_unit <= $AMOUNT_MEMORY_MB AND
    #   inv_memory_mb.max_unit >= $AMOUNT_MEMORY_MB AND
    #   $AMOUNT_MEMORY_MB % inv_memory_mb.step_size == 0
    # ) AND (
    #   inv_disk.resource_provider_id IS NOT NULL AND
    #   (
    #     (
    #       COALESCE(usage_disk_gb.used, 0) + $AMOUNT_DISK_GB <=
    #         (inv_disk_gb.total + inv_disk_gb.reserved)
    #         * inv_disk_gb.allocation_ratio
    #     ) AND
    #     inv_disk_gb.min_unit <= $AMOUNT_DISK_GB AND
    #     inv_disk_gb.max_unit >= $AMOUNT_DISK_GB AND
    #     $AMOUNT_DISK_GB % inv_disk_gb.step_size == 0
    #   ) OR
    #     sharing_disk_gb.resource_provider_id IS NOT NULL
    # )
    # GROUP BY rp.id

    rpt = sa.alias(_RP_TBL, name="rp")

    # Contains a set of resource provider IDs for each resource class requested
    sharing_providers = {
        rc_id: _get_providers_with_shared_capacity(ctx, rc_id, amount)
        for rc_id, amount in resources.items()
    }

    name_map = {
        rc_id: _RC_CACHE.string_from_id(rc_id).lower()
        for rc_id in resources.keys()
    }

    # Dict, keyed by resource class ID, of an aliased table object for the
    # inventories table winnowed to only that resource class.
    inv_tables = {
        rc_id: sa.alias(_INV_TBL, name='inv_%s' % name_map[rc_id])
        for rc_id in resources.keys()
    }

    # Dict, keyed by resource class ID, of a derived table (subquery in the
    # FROM clause or JOIN) against the allocations table  winnowed to only that
    # resource class, grouped by resource provider.
    usage_tables = {
        rc_id: sa.alias(
            sa.select([
                _ALLOC_TBL.c.resource_provider_id,
                sql.func.sum(_ALLOC_TBL.c.used).label('used'),
            ]).where(
                _ALLOC_TBL.c.resource_class_id == rc_id
            ).group_by(
                _ALLOC_TBL.c.resource_provider_id
            ),
            name='usage_%s' % name_map[rc_id],
        )
        for rc_id in resources.keys()
    }

    # Dict, keyed by resource class ID, of an aliased table of
    # resource_provider_aggregates representing the aggregates associated with
    # a provider sharing the resource class
    sharing_tables = {
        rc_id: sa.alias(_RP_AGG_TBL, name='sharing_%s' % name_map[rc_id])
        for rc_id in resources.keys()
        if len(sharing_providers[rc_id]) > 0
    }

    # Dict, keyed by resource class ID, of an aliased table of
    # resource_provider_aggregates representing the resource providers
    # associated by aggregate to the providers sharing a particular resource
    # class.
    shared_tables = {
        rc_id: sa.alias(_RP_AGG_TBL, name='shared_%s' % name_map[rc_id])
        for rc_id in resources.keys()
        if len(sharing_providers[rc_id]) > 0
    }

    # List of the WHERE conditions we build up by looking at the contents
    # of the sharing providers
    where_conds = []

    # Primary selection is on the resource_providers table and all of the
    # aliased table copies of resource_provider_aggregates for each resource
    # being shared
    sel = sa.select([rpt.c.id])

    # The chain of joins that we eventually pass to select_from()
    join_chain = None
    # The last inventory join
    lastij = None

    # TODO(jaypipes): It is necessary to sort the sharing_providers.items()
    # below. The SQL JOINs that are generated by the _get_all_with_shared()
    # function depend on a specific order. For non-shared resources, an INNER
    # JOIN is done to the preceding derived query whereas for shared resources,
    # a LEFT JOIN is done.
    #
    # If we do the LEFT JOIN followed by INNER JOINs, the SQL expression will
    # produce an incorrect projection, so the sort on the value of the dict
    # here will result in the non-shared resources being handled first, which
    # is what we want.
    #
    # ref: https://bugs.launchpad.net/nova/+bug/1705231
    for rc_id, sps in sorted(sharing_providers.items(), key=lambda x: x[1]):
        it = inv_tables[rc_id]
        ut = usage_tables[rc_id]
        amount = resources[rc_id]

        if join_chain is None:
            rp_link = rpt
            jc = rpt.c.id == it.c.resource_provider_id
        else:
            rp_link = join_chain
            jc = lastij.c.resource_provider_id == it.c.resource_provider_id

        # We can do a more efficient INNER JOIN when we don't have shared
        # resource providers for this resource class
        joiner = sa.join
        if sps:
            joiner = sa.outerjoin
        inv_join = joiner(
            rp_link, it,
            sa.and_(
                jc,
                # Add a join condition winnowing this copy of inventories table
                # to only the resource class being analyzed in this loop...
                it.c.resource_class_id == rc_id,
            ),
        )
        lastij = it
        usage_join = sa.outerjoin(
            inv_join, ut,
            it.c.resource_provider_id == ut.c.resource_provider_id,
        )
        join_chain = usage_join

        usage_cond = sa.and_(
            (
            (sql.func.coalesce(ut.c.used, 0) + amount) <=
            (it.c.total - it.c.reserved) * it.c.allocation_ratio
            ),
            it.c.min_unit <= amount,
            it.c.max_unit >= amount,
            amount % it.c.step_size == 0,
        )
        if not sps:
            where_conds.append(usage_cond)
        else:
            sharing = sharing_tables[rc_id]
            shared = shared_tables[rc_id]
            cond = sa.or_(
                sa.and_(
                    it.c.resource_provider_id != sa.null(),
                    usage_cond,
                ),
                sharing.c.resource_provider_id != sa.null(),
            )
            where_conds.append(cond)

            # We need to add the "butterfly" join now that produces the set of
            # resource providers associated with a provider that is sharing the
            # resource via an aggregate
            shared_join = sa.outerjoin(
                join_chain, shared,
                rpt.c.id == shared.c.resource_provider_id,
            )
            sharing_join = sa.outerjoin(
                shared_join, sharing,
                sa.and_(
                    shared.c.aggregate_id == sharing.c.aggregate_id,
                    sharing.c.resource_provider_id.in_(sps),
                ),
            )
            join_chain = sharing_join

    sel = sel.select_from(join_chain)
    sel = sel.where(sa.and_(*where_conds))
    sel = sel.group_by(rpt.c.id)

    return [r for r in ctx.session.execute(sel)]


@base.NovaObjectRegistry.register
class ResourceProviderList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial Version
    # Version 1.1: Turn off remotable
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('ResourceProvider'),
    }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_by_filters_from_db(context, filters):
        # Eg. filters can be:
        #  filters = {
        #      'name': <name>,
        #      'uuid': <uuid>,
        #      'member_of': [<aggregate_uuid>, <aggregate_uuid>]
        #      'resources': {
        #          'VCPU': 1,
        #          'MEMORY_MB': 1024
        #      }
        #  }
        if not filters:
            filters = {}
        else:
            # Since we modify the filters, copy them so that we don't modify
            # them in the calling program.
            filters = copy.deepcopy(filters)
        name = filters.pop('name', None)
        uuid = filters.pop('uuid', None)
        member_of = filters.pop('member_of', [])

        resources = filters.pop('resources', {})
        # NOTE(sbauza): We want to key the dict by the resource class IDs
        # and we want to make sure those class names aren't incorrect.
        resources = {_RC_CACHE.id_from_string(r_name): amount
                     for r_name, amount in resources.items()}
        query = context.session.query(models.ResourceProvider)
        if name:
            query = query.filter(models.ResourceProvider.name == name)
        if uuid:
            query = query.filter(models.ResourceProvider.uuid == uuid)

        # If 'member_of' has values join with the PlacementAggregates to
        # get those resource providers that are associated with any of the
        # list of aggregate uuids provided with 'member_of'.
        if member_of:
            join_statement = sa.join(_AGG_TBL, _RP_AGG_TBL, sa.and_(
                _AGG_TBL.c.id == _RP_AGG_TBL.c.aggregate_id,
                _AGG_TBL.c.uuid.in_(member_of)))
            resource_provider_id = _RP_AGG_TBL.c.resource_provider_id
            rps_in_aggregates = sa.select(
                [resource_provider_id]).select_from(join_statement)
            query = query.filter(models.ResourceProvider.id.in_(
                rps_in_aggregates))

        if not resources:
            # Returns quickly the list in case we don't need to check the
            # resource usage
            return query.all()

        # NOTE(sbauza): In case we want to look at the resource criteria, then
        # the SQL generated from this case looks something like:
        # SELECT
        #   rp.*
        # FROM resource_providers AS rp
        # JOIN inventories AS inv
        # ON rp.id = inv.resource_provider_id
        # LEFT JOIN (
        #    SELECT resource_provider_id, resource_class_id, SUM(used) AS used
        #    FROM allocations
        #    WHERE resource_class_id IN ($RESOURCE_CLASSES)
        #    GROUP BY resource_provider_id, resource_class_id
        # ) AS usage
        #     ON inv.resource_provider_id = usage.resource_provider_id
        #     AND inv.resource_class_id = usage.resource_class_id
        # AND (inv.resource_class_id = $X AND (used + $AMOUNT_X <= (
        #        total + reserved) * inv.allocation_ratio) AND
        #        inv.min_unit <= $AMOUNT_X AND inv.max_unit >= $AMOUNT_X AND
        #        $AMOUNT_X % inv.step_size == 0)
        #      OR (inv.resource_class_id = $Y AND (used + $AMOUNT_Y <= (
        #        total + reserved) * inv.allocation_ratio) AND
        #        inv.min_unit <= $AMOUNT_Y AND inv.max_unit >= $AMOUNT_Y AND
        #        $AMOUNT_Y % inv.step_size == 0)
        #      OR (inv.resource_class_id = $Z AND (used + $AMOUNT_Z <= (
        #        total + reserved) * inv.allocation_ratio) AND
        #        inv.min_unit <= $AMOUNT_Z AND inv.max_unit >= $AMOUNT_Z AND
        #        $AMOUNT_Z % inv.step_size == 0))
        # GROUP BY rp.id
        # HAVING
        #  COUNT(DISTINCT(inv.resource_class_id)) == len($RESOURCE_CLASSES)
        #
        # with a possible additional WHERE clause for the name and uuid that
        # comes from the above filters

        # First JOIN between inventories and RPs is here
        join_clause = _RP_TBL.c.id == _INV_TBL.c.resource_provider_id
        query = query.join(_INV_TBL, join_clause)

        # Now, below is the LEFT JOIN for getting the allocations usage
        usage = sa.select([_ALLOC_TBL.c.resource_provider_id,
                           _ALLOC_TBL.c.resource_class_id,
                           sql.func.sum(_ALLOC_TBL.c.used).label('used')])
        usage = usage.where(_ALLOC_TBL.c.resource_class_id.in_(
            resources.keys()))
        usage = usage.group_by(_ALLOC_TBL.c.resource_provider_id,
                               _ALLOC_TBL.c.resource_class_id)
        usage = sa.alias(usage, name='usage')
        query = query.outerjoin(
            usage,
            sa.and_(
                usage.c.resource_provider_id == (
                    _INV_TBL.c.resource_provider_id),
                usage.c.resource_class_id == _INV_TBL.c.resource_class_id))

        # And finally, we verify for each resource class if the requested
        # amount isn't more than the left space (considering the allocation
        # ratio, the reserved space and the min and max amount possible sizes)
        where_clauses = [
            sa.and_(
                _INV_TBL.c.resource_class_id == r_idx,
                (func.coalesce(usage.c.used, 0) + amount <= (
                    _INV_TBL.c.total - _INV_TBL.c.reserved
                ) * _INV_TBL.c.allocation_ratio),
                _INV_TBL.c.min_unit <= amount,
                _INV_TBL.c.max_unit >= amount,
                amount % _INV_TBL.c.step_size == 0
            )
            for (r_idx, amount) in resources.items()]
        query = query.filter(sa.or_(*where_clauses))
        query = query.group_by(_RP_TBL.c.id)
        # NOTE(sbauza): Only RPs having all the asked resources can be provided
        query = query.having(sql.func.count(
            sa.distinct(_INV_TBL.c.resource_class_id)) == len(resources))

        return query.all()

    @classmethod
    def get_all_by_filters(cls, context, filters=None):
        """Returns a list of `ResourceProvider` objects that have sufficient
        resources in their inventories to satisfy the amounts specified in the
        `filters` parameter.

        If no resource providers can be found, the function will return an
        empty list.

        :param context: `nova.context.RequestContext` that may be used to grab
                        a DB connection.
        :param filters: Can be `name`, `uuid`, `member_of` or `resources` where
                        `member_of` is a list of aggregate uuids and
                        `resources` is a dict of amounts keyed by resource
                        classes.
        :type filters: dict
        """
        _ensure_rc_cache(context)
        resource_providers = cls._get_all_by_filters_from_db(context, filters)
        return base.obj_make_list(context, cls(context),
                                  objects.ResourceProvider, resource_providers)


class _HasAResourceProvider(base.NovaObject):
    """Code shared between Inventory and Allocation

    Both contain a ResourceProvider.
    """

    @staticmethod
    def _make_db(updates):
        try:
            resource_provider = updates.pop('resource_provider')
            updates['resource_provider_id'] = resource_provider.id
        except (KeyError, NotImplementedError):
            raise exception.ObjectActionError(
                action='create',
                reason='resource_provider required')
        try:
            rc_str = updates.pop('resource_class')
        except KeyError:
            raise exception.ObjectActionError(
                action='create',
                reason='resource_class required')
        updates['resource_class_id'] = _RC_CACHE.id_from_string(rc_str)
        return updates

    @staticmethod
    def _from_db_object(context, target, source):
        _ensure_rc_cache(context)
        for field in target.fields:
            if field not in ('resource_provider', 'resource_class'):
                setattr(target, field, source[field])

        if 'resource_class' not in target:
            rc_str = _RC_CACHE.string_from_id(source['resource_class_id'])
            target.resource_class = rc_str
        if ('resource_provider' not in target and
                'resource_provider' in source):
            target.resource_provider = ResourceProvider()
            ResourceProvider._from_db_object(
                context,
                target.resource_provider,
                source['resource_provider'])

        target._context = context
        target.obj_reset_changes()
        return target


@db_api.api_context_manager.writer
def _create_inventory_in_db(context, updates):
    db_inventory = models.Inventory()
    db_inventory.update(updates)
    context.session.add(db_inventory)
    return db_inventory


@db_api.api_context_manager.writer
def _update_inventory_in_db(context, id_, updates):
    result = context.session.query(
        models.Inventory).filter_by(id=id_).update(updates)
    if not result:
        raise exception.NotFound()


@base.NovaObjectRegistry.register
class Inventory(_HasAResourceProvider):
    # Version 1.0: Initial version
    # Version 1.1: Changed resource_class to allow custom strings
    # Version 1.2: Turn off remotable
    VERSION = '1.2'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'resource_provider': fields.ObjectField('ResourceProvider'),
        'resource_class': fields.ResourceClassField(read_only=True),
        'total': fields.NonNegativeIntegerField(),
        'reserved': fields.NonNegativeIntegerField(default=0),
        'min_unit': fields.NonNegativeIntegerField(default=1),
        'max_unit': fields.NonNegativeIntegerField(default=1),
        'step_size': fields.NonNegativeIntegerField(default=1),
        'allocation_ratio': fields.NonNegativeFloatField(default=1.0),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(Inventory, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'resource_class' in primitive:
            rc = primitive['resource_class']
            rc_cache.raise_if_custom_resource_class_pre_v1_1(rc)

    @property
    def capacity(self):
        """Inventory capacity, adjusted by allocation_ratio."""
        return int((self.total - self.reserved) * self.allocation_ratio)

    def create(self):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        _ensure_rc_cache(self._context)
        updates = self._make_db(self.obj_get_changes())
        db_inventory = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_inventory)

    def save(self):
        if 'id' not in self:
            raise exception.ObjectActionError(action='save',
                                              reason='not created')
        _ensure_rc_cache(self._context)
        updates = self.obj_get_changes()
        updates.pop('id', None)
        self._update_in_db(self._context, self.id, updates)

    @staticmethod
    def _create_in_db(context, updates):
        return _create_inventory_in_db(context, updates)

    @staticmethod
    def _update_in_db(context, id_, updates):
        return _update_inventory_in_db(context, id_, updates)


@base.NovaObjectRegistry.register
class InventoryList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial Version
    # Version 1.1: Turn off remotable
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('Inventory'),
    }

    def find(self, res_class):
        """Return the inventory record from the list of Inventory records that
        matches the supplied resource class, or None.

        :param res_class: An integer or string representing a resource
                          class. If the value is a string, the method first
                          looks up the resource class identifier from the
                          string.
        """
        if not isinstance(res_class, six.string_types):
            raise ValueError

        for inv_rec in self.objects:
            if inv_rec.resource_class == res_class:
                return inv_rec

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_by_resource_provider(context, rp_uuid):
        return context.session.query(models.Inventory).\
            join(models.Inventory.resource_provider).\
            options(contains_eager('resource_provider')).\
            filter(models.ResourceProvider.uuid == rp_uuid).all()

    @classmethod
    def get_all_by_resource_provider_uuid(cls, context, rp_uuid):
        db_inventory_list = cls._get_all_by_resource_provider(context,
                                                              rp_uuid)
        return base.obj_make_list(context, cls(context), objects.Inventory,
                                  db_inventory_list)


@base.NovaObjectRegistry.register
class Allocation(_HasAResourceProvider):
    # Version 1.0: Initial version
    # Version 1.1: Changed resource_class to allow custom strings
    # Version 1.2: Turn off remotable
    VERSION = '1.2'

    fields = {
        'id': fields.IntegerField(),
        'resource_provider': fields.ObjectField('ResourceProvider'),
        'consumer_id': fields.UUIDField(),
        'resource_class': fields.ResourceClassField(),
        'used': fields.IntegerField(),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(Allocation, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'resource_class' in primitive:
            rc = primitive['resource_class']
            rc_cache.raise_if_custom_resource_class_pre_v1_1(rc)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        db_allocation = models.Allocation()
        db_allocation.update(updates)
        context.session.add(db_allocation)
        # We may be in a nested context manager so must flush so the
        # caller receives an id.
        context.session.flush()
        return db_allocation

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy(context, id):
        result = context.session.query(models.Allocation).filter_by(
            id=id).delete()
        if not result:
            raise exception.NotFound()

    def destroy(self):
        self._destroy(self._context, self.id)


def _delete_current_allocs(conn, consumer_id):
    """Deletes any existing allocations that correspond to the allocations to
    be written. This is wrapped in a transaction, so if the write subsequently
    fails, the deletion will also be rolled back.
    """
    del_sql = _ALLOC_TBL.delete().where(
        _ALLOC_TBL.c.consumer_id == consumer_id)
    conn.execute(del_sql)


def _check_capacity_exceeded(conn, allocs):
    """Checks to see if the supplied allocation records would result in any of
    the inventories involved having their capacity exceeded.

    Raises an InvalidAllocationCapacityExceeded exception if any inventory
    would be exhausted by the allocation. Raises an
    InvalidAllocationConstraintsViolated exception if any of the `step_size`,
    `min_unit` or `max_unit` constraints in an inventory will be violated
    by any one of the allocations.

    If no inventories would be exceeded or violated by the allocations, the
    function returns a list of `ResourceProvider` objects that contain the
    generation at the time of the check.

    :param conn: SQLalchemy Connection object to use
    :param allocs: List of `Allocation` objects to check
    """
    # The SQL generated below looks like this:
    # SELECT
    #   rp.id,
    #   rp.uuid,
    #   rp.generation,
    #   inv.resource_class_id,
    #   inv.total,
    #   inv.reserved,
    #   inv.allocation_ratio,
    #   allocs.used
    # FROM resource_providers AS rp
    # JOIN inventories AS i1
    # ON rp.id = i1.resource_provider_id
    # LEFT JOIN (
    #    SELECT resource_provider_id, resource_class_id, SUM(used) AS used
    #    FROM allocations
    #    WHERE resource_class_id IN ($RESOURCE_CLASSES)
    #    GROUP BY resource_provider_id, resource_class_id
    # ) AS allocs
    # ON inv.resource_provider_id = allocs.resource_provider_id
    # AND inv.resource_class_id = allocs.resource_class_id
    # WHERE rp.uuid IN ($RESOURCE_PROVIDERS)
    # AND inv.resource_class_id IN ($RESOURCE_CLASSES)
    #
    # We then take the results of the above and determine if any of the
    # inventory will have its capacity exceeded.
    rc_ids = set([_RC_CACHE.id_from_string(a.resource_class)
                       for a in allocs])
    provider_uuids = set([a.resource_provider.uuid for a in allocs])

    usage = sa.select([_ALLOC_TBL.c.resource_provider_id,
                       _ALLOC_TBL.c.resource_class_id,
                       sql.func.sum(_ALLOC_TBL.c.used).label('used')])
    usage = usage.where(_ALLOC_TBL.c.resource_class_id.in_(rc_ids))
    usage = usage.group_by(_ALLOC_TBL.c.resource_provider_id,
                           _ALLOC_TBL.c.resource_class_id)
    usage = sa.alias(usage, name='usage')

    inv_join = sql.join(_RP_TBL, _INV_TBL,
            sql.and_(_RP_TBL.c.id == _INV_TBL.c.resource_provider_id,
                     _INV_TBL.c.resource_class_id.in_(rc_ids)))
    primary_join = sql.outerjoin(inv_join, usage,
        sql.and_(
            _INV_TBL.c.resource_provider_id == usage.c.resource_provider_id,
            _INV_TBL.c.resource_class_id == usage.c.resource_class_id)
    )
    cols_in_output = [
        _RP_TBL.c.id.label('resource_provider_id'),
        _RP_TBL.c.uuid,
        _RP_TBL.c.generation,
        _INV_TBL.c.resource_class_id,
        _INV_TBL.c.total,
        _INV_TBL.c.reserved,
        _INV_TBL.c.allocation_ratio,
        _INV_TBL.c.min_unit,
        _INV_TBL.c.max_unit,
        _INV_TBL.c.step_size,
        usage.c.used,
    ]

    sel = sa.select(cols_in_output).select_from(primary_join)
    sel = sel.where(
            sa.and_(_RP_TBL.c.uuid.in_(provider_uuids),
                    _INV_TBL.c.resource_class_id.in_(rc_ids)))
    records = conn.execute(sel)
    # Create a map keyed by (rp_uuid, res_class) for the records in the DB
    usage_map = {}
    provs_with_inv = set()
    for record in records:
        map_key = (record['uuid'], record['resource_class_id'])
        if map_key in usage_map:
            raise KeyError("%s already in usage_map, bad query" % str(map_key))
        usage_map[map_key] = record
        provs_with_inv.add(record["uuid"])
    # Ensure that all providers have existing inventory
    missing_provs = provider_uuids - provs_with_inv
    if missing_provs:
        class_str = ', '.join([_RC_CACHE.string_from_id(rc_id)
                               for rc_id in rc_ids])
        provider_str = ', '.join(missing_provs)
        raise exception.InvalidInventory(resource_class=class_str,
                resource_provider=provider_str)

    res_providers = {}
    for alloc in allocs:
        rc_id = _RC_CACHE.id_from_string(alloc.resource_class)
        rp_uuid = alloc.resource_provider.uuid
        key = (rp_uuid, rc_id)
        try:
            usage = usage_map[key]
        except KeyError:
            # The resource class at rc_id is not in the usage map.
            raise exception.InvalidInventory(
                    resource_class=alloc.resource_class,
                    resource_provider=rp_uuid)
        amount_needed = alloc.used
        allocation_ratio = usage['allocation_ratio']
        min_unit = usage['min_unit']
        max_unit = usage['max_unit']
        step_size = usage['step_size']

        # check min_unit, max_unit, step_size
        if (amount_needed < min_unit or amount_needed > max_unit or
                amount_needed % step_size != 0):
            LOG.warning(
                _LW("Allocation for %(rc)s on resource provider %(rp)s "
                    "violates min_unit, max_unit, or step_size. "
                    "Requested: %(requested)s, min_unit: %(min_unit)s, "
                    "max_unit: %(max_unit)s, step_size: %(step_size)s"),
                {'rc': alloc.resource_class,
                 'rp': rp_uuid,
                 'requested': amount_needed,
                 'min_unit': min_unit,
                 'max_unit': max_unit,
                 'step_size': step_size})
            raise exception.InvalidAllocationConstraintsViolated(
                resource_class=alloc.resource_class,
                resource_provider=rp_uuid)

        # usage["used"] can be returned as None
        used = usage['used'] or 0
        capacity = (usage['total'] - usage['reserved']) * allocation_ratio
        if capacity < (used + amount_needed):
            LOG.warning(
                _LW("Over capacity for %(rc)s on resource provider %(rp)s. "
                    "Needed: %(needed)s, Used: %(used)s, Capacity: %(cap)s"),
                {'rc': alloc.resource_class,
                 'rp': rp_uuid,
                 'needed': amount_needed,
                 'used': used,
                 'cap': capacity})
            raise exception.InvalidAllocationCapacityExceeded(
                resource_class=alloc.resource_class,
                resource_provider=rp_uuid)
        if rp_uuid not in res_providers:
            res_providers[rp_uuid] = alloc.resource_provider
    return list(res_providers.values())


def _ensure_lookup_table_entry(conn, tbl, external_id):
    """Ensures the supplied external ID exists in the specified lookup table
    and if not, adds it. Returns the internal ID.

    :param conn: DB connection object to use
    :param tbl: The lookup table
    :param external_id: The external project or user identifier
    :type external_id: string
    """
    # Grab the project internal ID if it exists in the projects table
    sel = sa.select([tbl.c.id]).where(
        tbl.c.external_id == external_id
    )
    res = conn.execute(sel).fetchall()
    if not res:
        try:
            res = conn.execute(tbl.insert().values(external_id=external_id))
            return res.inserted_primary_key[0]
        except db_exc.DBDuplicateEntry:
            # Another thread added it just before us, so just read the
            # internal ID that that thread created...
            res = conn.execute(sel).fetchall()

    return res[0][0]


def _ensure_project(conn, external_id):
    """Ensures the supplied external project ID exists in the projects lookup
    table and if not, adds it. Returns the internal project ID.

    :param conn: DB connection object to use
    :param external_id: The external project identifier
    :type external_id: string
    """
    return _ensure_lookup_table_entry(conn, _PROJECT_TBL, external_id)


def _ensure_user(conn, external_id):
    """Ensures the supplied external user ID exists in the users lookup table
    and if not, adds it. Returns the internal user ID.

    :param conn: DB connection object to use
    :param external_id: The external user identifier
    :type external_id: string
    """
    return _ensure_lookup_table_entry(conn, _USER_TBL, external_id)


@base.NovaObjectRegistry.register
class AllocationList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial Version
    # Version 1.1: Add create_all() and delete_all()
    # Version 1.2: Turn off remotable
    # Version 1.3: Add project_id and user_id fields
    VERSION = '1.3'

    fields = {
        'objects': fields.ListOfObjectsField('Allocation'),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
    }

    @staticmethod
    @db_api.api_context_manager.writer
    def _delete_allocations(context, allocations):
        for allocation in allocations:
            allocation._context = context
            allocation.destroy()

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_allocations_from_db(context, resource_provider_uuid=None,
                                 consumer_id=None):
        query = (context.session.query(models.Allocation)
                 .join(models.Allocation.resource_provider)
                 .options(contains_eager('resource_provider')))
        if resource_provider_uuid:
            query = query.filter(
                models.ResourceProvider.uuid == resource_provider_uuid)
        if consumer_id:
            query = query.filter(
                models.Allocation.consumer_id == consumer_id)
        return query.all()

    def _ensure_consumer_project_user(self, conn, consumer_id):
        """Examines the project_id, user_id of the object along with the
        supplied consumer_id and ensures that there are records in the
        consumers, projects, and users table for these entities.

        :param consumer_id: Comes from the Allocation object being processed
        """
        if (self.obj_attr_is_set('project_id') and
                self.project_id is not None and
                self.obj_attr_is_set('user_id') and
                self.user_id is not None):
            # Grab the project internal ID if it exists in the projects table
            pid = _ensure_project(conn, self.project_id)
            # Grab the user internal ID if it exists in the users table
            uid = _ensure_user(conn, self.user_id)

            # Add the consumer if it doesn't already exist
            sel_stmt = sa.select([_CONSUMER_TBL.c.uuid]).where(
                _CONSUMER_TBL.c.uuid == consumer_id)
            result = conn.execute(sel_stmt).fetchall()
            if not result:
                try:
                    conn.execute(_CONSUMER_TBL.insert().values(
                        uuid=consumer_id,
                        project_id=pid,
                        user_id=uid))
                except db_exc.DBDuplicateEntry:
                    # We assume at this time that a consumer project/user can't
                    # change, so if we get here, we raced and should just pass
                    # if the consumer already exists.
                    pass

    @oslo_db_api.wrap_db_retry(max_retries=5, retry_on_deadlock=True)
    @db_api.api_context_manager.writer
    def _set_allocations(self, context, allocs):
        """Write a set of allocations.

        We must check that there is capacity for each allocation.
        If there is not we roll back the entire set.

        :raises `exception.ResourceClassNotFound` if any resource class in any
                allocation in allocs cannot be found in either the standard
                classes or the DB.
        :raises `exception.InvalidAllocationCapacityExceeded` if any inventory
                would be exhausted by the allocation.
        :raises `InvalidAllocationConstraintsViolated` if any of the
                `step_size`, `min_unit` or `max_unit` constraints in an
                inventory will be violated by any one of the allocations.
        """
        _ensure_rc_cache(context)
        conn = context.session.connection()

        # Short-circuit out if there are any allocations with string
        # resource class names that don't exist this will raise a
        # ResourceClassNotFound exception.
        for alloc in allocs:
            if 'id' in alloc:
                raise exception.ObjectActionError(action='create',
                                                  reason='already created')

        # Before writing any allocation records, we check that the submitted
        # allocations do not cause any inventory capacity to be exceeded for
        # any resource provider and resource class involved in the allocation
        # transaction. _check_capacity_exceeded() raises an exception if any
        # inventory capacity is exceeded. If capacity is not exceeeded, the
        # function returns a list of ResourceProvider objects containing the
        # generation of the resource provider at the time of the check. These
        # objects are used at the end of the allocation transaction as a guard
        # against concurrent updates.
        with conn.begin():
            # First delete any existing allocations for that rp/consumer combo.
            consumer_id = allocs[0].consumer_id
            _delete_current_allocs(conn, consumer_id)
            before_gens = _check_capacity_exceeded(conn, allocs)
            self._ensure_consumer_project_user(conn, consumer_id)
            # Now add the allocations that were passed in.
            for alloc in allocs:
                rp = alloc.resource_provider
                rc_id = _RC_CACHE.id_from_string(alloc.resource_class)
                ins_stmt = _ALLOC_TBL.insert().values(
                        resource_provider_id=rp.id,
                        resource_class_id=rc_id,
                        consumer_id=alloc.consumer_id,
                        used=alloc.used)
                conn.execute(ins_stmt)

            # Generation checking happens here. If the inventory for
            # this resource provider changed out from under us,
            # this will raise a ConcurrentUpdateDetected which can be caught
            # by the caller to choose to try again. It will also rollback the
            # transaction so that these changes always happen atomically.
            for rp in before_gens:
                rp.generation = _increment_provider_generation(conn, rp)

    @classmethod
    def get_all_by_resource_provider_uuid(cls, context, rp_uuid):
        db_allocation_list = cls._get_allocations_from_db(
            context, resource_provider_uuid=rp_uuid)
        return base.obj_make_list(
            context, cls(context), objects.Allocation, db_allocation_list)

    @classmethod
    def get_all_by_consumer_id(cls, context, consumer_id):
        db_allocation_list = cls._get_allocations_from_db(
            context, consumer_id=consumer_id)
        return base.obj_make_list(
            context, cls(context), objects.Allocation, db_allocation_list)

    def create_all(self):
        """Create the supplied allocations."""
        # TODO(jaypipes): Retry the allocation writes on
        # ConcurrentUpdateDetected
        self._set_allocations(self._context, self.objects)

    def delete_all(self):
        self._delete_allocations(self._context, self.objects)

    def __repr__(self):
        strings = [repr(x) for x in self.objects]
        return "AllocationList[" + ", ".join(strings) + "]"


@base.NovaObjectRegistry.register
class Usage(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Changed resource_class to allow custom strings
    VERSION = '1.1'

    fields = {
        'resource_class': fields.ResourceClassField(read_only=True),
        'usage': fields.NonNegativeIntegerField(),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(Usage, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'resource_class' in primitive:
            rc = primitive['resource_class']
            rc_cache.raise_if_custom_resource_class_pre_v1_1(rc)

    @staticmethod
    def _from_db_object(context, target, source):
        for field in target.fields:
            if field not in ('resource_class'):
                setattr(target, field, source[field])

        if 'resource_class' not in target:
            rc_str = _RC_CACHE.string_from_id(source['resource_class_id'])
            target.resource_class = rc_str

        target._context = context
        target.obj_reset_changes()
        return target


@base.NovaObjectRegistry.register
class UsageList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Turn off remotable
    # Version 1.2: Add get_all_by_project_user()
    VERSION = '1.2'

    fields = {
        'objects': fields.ListOfObjectsField('Usage'),
    }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_by_resource_provider_uuid(context, rp_uuid):
        query = (context.session.query(models.Inventory.resource_class_id,
                 func.coalesce(func.sum(models.Allocation.used), 0))
                 .join(models.ResourceProvider,
                       models.Inventory.resource_provider_id ==
                       models.ResourceProvider.id)
                 .outerjoin(models.Allocation,
                            sql.and_(models.Inventory.resource_provider_id ==
                                     models.Allocation.resource_provider_id,
                                     models.Inventory.resource_class_id ==
                                     models.Allocation.resource_class_id))
                 .filter(models.ResourceProvider.uuid == rp_uuid)
                 .group_by(models.Inventory.resource_class_id))
        result = [dict(resource_class_id=item[0], usage=item[1])
                  for item in query.all()]
        return result

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_by_project_user(context, project_id, user_id=None):
        query = (context.session.query(models.Allocation.resource_class_id,
                 func.coalesce(func.sum(models.Allocation.used), 0))
                 .join(models.Consumer,
                       models.Allocation.consumer_id == models.Consumer.uuid)
                 .join(models.Project,
                       models.Consumer.project_id == models.Project.id)
                 .filter(models.Project.external_id == project_id))
        if user_id:
            query = query.join(models.User,
                               models.Consumer.user_id == models.User.id)
            query = query.filter(models.User.external_id == user_id)
        query = query.group_by(models.Allocation.resource_class_id)
        result = [dict(resource_class_id=item[0], usage=item[1])
                  for item in query.all()]
        return result

    @classmethod
    def get_all_by_resource_provider_uuid(cls, context, rp_uuid):
        _ensure_rc_cache(context)
        usage_list = cls._get_all_by_resource_provider_uuid(context, rp_uuid)
        return base.obj_make_list(context, cls(context), Usage, usage_list)

    @classmethod
    def get_all_by_project_user(cls, context, project_id, user_id=None):
        _ensure_rc_cache(context)
        usage_list = cls._get_all_by_project_user(context, project_id,
                                                  user_id=user_id)
        return base.obj_make_list(context, cls(context), Usage, usage_list)

    def __repr__(self):
        strings = [repr(x) for x in self.objects]
        return "UsageList[" + ", ".join(strings) + "]"


@base.NovaObjectRegistry.register
class ResourceClass(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    CUSTOM_NAMESPACE = 'CUSTOM_'
    """All non-standard resource classes must begin with this string."""

    MIN_CUSTOM_RESOURCE_CLASS_ID = 10000
    """Any user-defined resource classes must have an identifier greater than
    or equal to this number.
    """

    # Retry count for handling possible race condition in creating resource
    # class. We don't ever want to hit this, as it is simply a race when
    # creating these classes, but this is just a stopgap to prevent a potential
    # infinite loop.
    RESOURCE_CREATE_RETRY_COUNT = 100

    fields = {
        'id': fields.IntegerField(read_only=True),
        'name': fields.ResourceClassField(nullable=False),
    }

    @staticmethod
    def _from_db_object(context, target, source):
        for field in target.fields:
            setattr(target, field, source[field])

        target._context = context
        target.obj_reset_changes()
        return target

    @classmethod
    def get_by_name(cls, context, name):
        """Return a ResourceClass object with the given string name.

        :param name: String name of the resource class to find

        :raises: ResourceClassNotFound if no such resource class was found
        """
        _ensure_rc_cache(context)
        rc_id = _RC_CACHE.id_from_string(name)
        obj = cls(context, id=rc_id, name=name)
        obj.obj_reset_changes()
        return obj

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_next_id(context):
        """Utility method to grab the next resource class identifier to use for
         user-defined resource classes.
        """
        query = context.session.query(func.max(models.ResourceClass.id))
        max_id = query.one()[0]
        if not max_id:
            return ResourceClass.MIN_CUSTOM_RESOURCE_CLASS_ID
        else:
            return max_id + 1

    def create(self):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        if 'name' not in self:
            raise exception.ObjectActionError(action='create',
                                              reason='name is required')
        if self.name in fields.ResourceClass.STANDARD:
            raise exception.ResourceClassExists(resource_class=self.name)

        if not self.name.startswith(self.CUSTOM_NAMESPACE):
            raise exception.ObjectActionError(
                action='create',
                reason='name must start with ' + self.CUSTOM_NAMESPACE)

        updates = self.obj_get_changes()
        # There is the possibility of a race when adding resource classes, as
        # the ID is generated locally. This loop catches that exception, and
        # retries until either it succeeds, or a different exception is
        # encountered.
        retries = self.RESOURCE_CREATE_RETRY_COUNT
        while retries:
            retries -= 1
            try:
                rc = self._create_in_db(self._context, updates)
                self._from_db_object(self._context, self, rc)
                break
            except db_exc.DBDuplicateEntry as e:
                if 'id' in e.columns:
                    # Race condition for ID creation; try again
                    continue
                # The duplication is on the other unique column, 'name'. So do
                # not retry; raise the exception immediately.
                raise exception.ResourceClassExists(resource_class=self.name)
        else:
            # We have no idea how common it will be in practice for the retry
            # limit to be exceeded. We set it high in the hope that we never
            # hit this point, but added this log message so we know that this
            # specific situation occurred.
            LOG.warning(_LW("Exceeded retry limit on ID generation while "
                            "creating ResourceClass %(name)s"),
                        {'name': self.name})
            msg = _("creating resource class %s") % self.name
            raise exception.MaxDBRetriesExceeded(action=msg)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        next_id = ResourceClass._get_next_id(context)
        rc = models.ResourceClass()
        rc.update(updates)
        rc.id = next_id
        context.session.add(rc)
        return rc

    def destroy(self):
        if 'id' not in self:
            raise exception.ObjectActionError(action='destroy',
                                              reason='ID attribute not found')
        # Never delete any standard resource class, since the standard resource
        # classes don't even exist in the database table anyway.
        _ensure_rc_cache(self._context)
        if self.id in (rc['id'] for rc in _RC_CACHE.STANDARDS):
            raise exception.ResourceClassCannotDeleteStandard(
                    resource_class=self.name)

        self._destroy(self._context, self.id, self.name)
        _RC_CACHE.clear()

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy(context, _id, name):
        # Don't delete the resource class if it is referred to in the
        # inventories table.
        num_inv = context.session.query(models.Inventory).filter(
                models.Inventory.resource_class_id == _id).count()
        if num_inv:
            raise exception.ResourceClassInUse(resource_class=name)

        res = context.session.query(models.ResourceClass).filter(
                models.ResourceClass.id == _id).delete()
        if not res:
            raise exception.NotFound()

    def save(self):
        if 'id' not in self:
            raise exception.ObjectActionError(action='save',
                                              reason='ID attribute not found')
        updates = self.obj_get_changes()
        # Never update any standard resource class, since the standard resource
        # classes don't even exist in the database table anyway.
        _ensure_rc_cache(self._context)
        if self.id in (rc['id'] for rc in _RC_CACHE.STANDARDS):
            raise exception.ResourceClassCannotUpdateStandard(
                    resource_class=self.name)
        self._save(self._context, self.id, self.name, updates)
        _RC_CACHE.clear()

    @staticmethod
    @db_api.api_context_manager.writer
    def _save(context, id, name, updates):
        db_rc = context.session.query(models.ResourceClass).filter_by(
            id=id).first()
        db_rc.update(updates)
        try:
            db_rc.save(context.session)
        except db_exc.DBDuplicateEntry:
            raise exception.ResourceClassExists(resource_class=name)


@base.NovaObjectRegistry.register
class ResourceClassList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Turn off remotable
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('ResourceClass'),
    }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all(context):
        _ensure_rc_cache(context)
        customs = list(context.session.query(models.ResourceClass).all())
        return _RC_CACHE.STANDARDS + customs

    @classmethod
    def get_all(cls, context):
        resource_classes = cls._get_all(context)
        return base.obj_make_list(context, cls(context),
                                  objects.ResourceClass, resource_classes)

    def __repr__(self):
        strings = [repr(x) for x in self.objects]
        return "ResourceClassList[" + ", ".join(strings) + "]"


@base.NovaObjectRegistry.register
class Trait(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    # All the user-defined traits must begin with this prefix.
    CUSTOM_NAMESPACE = 'CUSTOM_'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'name': fields.StringField(nullable=False)
    }

    @staticmethod
    def _from_db_object(context, trait, db_trait):
        for key in trait.fields:
            setattr(trait, key, db_trait[key])
        trait.obj_reset_changes()
        trait._context = context
        return trait

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        trait = models.Trait()
        trait.update(updates)
        context.session.add(trait)
        return trait

    def create(self):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        if 'name' not in self:
            raise exception.ObjectActionError(action='create',
                                              reason='name is required')

        updates = self.obj_get_changes()

        try:
            db_trait = self._create_in_db(self._context, updates)
        except db_exc.DBDuplicateEntry:
            raise exception.TraitExists(name=self.name)

        self._from_db_object(self._context, self, db_trait)

    @staticmethod
    @db_api.api_context_manager.writer  # trait sync can cause a write
    def _get_by_name_from_db(context, name):
        _ensure_trait_sync(context)
        result = context.session.query(models.Trait).filter_by(
            name=name).first()
        if not result:
            raise exception.TraitNotFound(name=name)
        return result

    @classmethod
    def get_by_name(cls, context, name):
        db_trait = cls._get_by_name_from_db(context, six.text_type(name))
        return cls._from_db_object(context, cls(), db_trait)

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, _id, name):
        num = context.session.query(models.ResourceProviderTrait).filter(
            models.ResourceProviderTrait.trait_id == _id).count()
        if num:
            raise exception.TraitInUse(name=name)

        res = context.session.query(models.Trait).filter_by(
            name=name).delete()
        if not res:
            raise exception.TraitNotFound(name=name)

    def destroy(self):
        if 'name' not in self:
            raise exception.ObjectActionError(action='destroy',
                                              reason='name is required')

        if not self.name.startswith(self.CUSTOM_NAMESPACE):
            raise exception.TraitCannotDeleteStandard(name=self.name)

        if 'id' not in self:
            raise exception.ObjectActionError(action='destroy',
                                              reason='ID attribute not found')

        self._destroy_in_db(self._context, self.id, self.name)


@base.NovaObjectRegistry.register
class TraitList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Trait')
    }

    @staticmethod
    @db_api.api_context_manager.writer  # trait sync can cause a write
    def _get_all_from_db(context, filters):
        _ensure_trait_sync(context)
        if not filters:
            filters = {}

        query = context.session.query(models.Trait)
        if 'name_in' in filters:
            query = query.filter(models.Trait.name.in_(
                [six.text_type(n) for n in filters['name_in']]
            ))
        if 'prefix' in filters:
            query = query.filter(
                models.Trait.name.like(six.text_type(filters['prefix'] + '%')))
        if 'associated' in filters:
            if filters['associated']:
                query = query.join(models.ResourceProviderTrait,
                    models.Trait.id == models.ResourceProviderTrait.trait_id
                ).distinct()
            else:
                query = query.outerjoin(models.ResourceProviderTrait,
                    models.Trait.id == models.ResourceProviderTrait.trait_id
                ).filter(models.ResourceProviderTrait.trait_id == null())

        return query.all()

    @base.remotable_classmethod
    def get_all(cls, context, filters=None):
        db_traits = cls._get_all_from_db(context, filters)
        return base.obj_make_list(context, cls(context), Trait, db_traits)


@base.NovaObjectRegistry.register_if(False)
class AllocationRequestResource(base.NovaObject):
    # 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'resource_provider': fields.ObjectField('ResourceProvider'),
        'resource_class': fields.ResourceClassField(read_only=True),
        'amount': fields.NonNegativeIntegerField(),
    }


@base.NovaObjectRegistry.register_if(False)
class AllocationRequest(base.NovaObject):
    # 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'resource_requests': fields.ListOfObjectsField(
            'AllocationRequestResource'
        ),
    }


@base.NovaObjectRegistry.register_if(False)
class ProviderSummaryResource(base.NovaObject):
    # 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'resource_class': fields.ResourceClassField(read_only=True),
        'capacity': fields.NonNegativeIntegerField(),
        'used': fields.NonNegativeIntegerField(),
    }


@base.NovaObjectRegistry.register_if(False)
class ProviderSummary(base.NovaObject):
    # 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'resource_provider': fields.ObjectField('ResourceProvider'),
        'resources': fields.ListOfObjectsField('ProviderSummaryResource'),
        'traits': fields.ListOfObjectsField('Trait'),
    }


@db_api.api_context_manager.reader
def _get_usages_by_provider_and_rc(ctx, rp_ids, rc_ids):
    """Returns a row iterator of usage records grouped by resource provider ID
    and resource class ID for all resource providers and resource classes
    involved in our request
    """
    # We build up a SQL expression that looks like this:
    # SELECT
    #   rp.id as resource_provider_id
    # , rp.uuid as resource_provider_uuid
    # , inv.resource_class_id
    # , inv.total
    # , inv.reserved
    # , inv.allocation_ratio
    # , usage.used
    # FROM resource_providers AS rp
    # JOIN inventories AS inv
    #  ON rp.id = inv.resource_provider_id
    # LEFT JOIN (
    #   SELECT resource_provider_id, resource_class_id, SUM(used) as used
    #   FROM allocations
    #   WHERE resource_provider_id IN ($rp_ids)
    #   AND resource_class_id IN ($rc_ids)
    #   GROUP BY resource_provider_id, resource_class_id
    # )
    # AS usages
    #   ON inv.resource_provider_id = usage.resource_provider_id
    #   AND inv.resource_class_id = usage.resource_class_id
    # WHERE rp.id IN ($rp_ids)
    # AND inv.resource_class_id IN ($rc_ids)
    rpt = sa.alias(_RP_TBL, name="rp")
    inv = sa.alias(_INV_TBL, name="inv")
    # Build our derived table (subquery in the FROM clause) that sums used
    # amounts for resource provider and resource class
    usage = sa.alias(
        sa.select([
            _ALLOC_TBL.c.resource_provider_id,
            _ALLOC_TBL.c.resource_class_id,
            sql.func.sum(_ALLOC_TBL.c.used).label('used'),
        ]).where(
            sa.and_(
                _ALLOC_TBL.c.resource_provider_id.in_(rp_ids),
                _ALLOC_TBL.c.resource_class_id.in_(rc_ids),
            ),
        ).group_by(
            _ALLOC_TBL.c.resource_provider_id,
            _ALLOC_TBL.c.resource_class_id
        ),
        name='usage',
    )
    # Build a join between the resource providers and inventories table
    rpt_inv_join = sa.join(rpt, inv, rpt.c.id == inv.c.resource_provider_id)
    # And then join to the derived table of usages
    usage_join = sa.outerjoin(
        rpt_inv_join,
        usage,
        sa.and_(
            usage.c.resource_provider_id == inv.c.resource_provider_id,
            usage.c.resource_class_id == inv.c.resource_class_id,
        ),
    )
    query = sa.select([
        rpt.c.id.label("resource_provider_id"),
        rpt.c.uuid.label("resource_provider_uuid"),
        inv.c.resource_class_id,
        inv.c.total,
        inv.c.reserved,
        inv.c.allocation_ratio,
        usage.c.used,
    ]).select_from(usage_join).where(
        sa.and_(rpt.c.id.in_(rp_ids),
                inv.c.resource_class_id.in_(rc_ids)))
    return ctx.session.execute(query).fetchall()


@base.NovaObjectRegistry.register_if(False)
class AllocationCandidates(base.NovaObject):
    """The AllocationCandidates object is a collection of possible allocations
    that match some request for resources, along with some summary information
    about the resource providers involved in these allocation candidates.
    """
    # 1.0: Initial version
    VERSION = '1.0'

    fields = {
        # A collection of allocation possibilities that can be attempted by the
        # caller that would, at the time of calling, meet the requested
        # resource constraints
        'allocation_requests': fields.ListOfObjectsField('AllocationRequest'),
        # Information about usage and inventory that relate to any provider
        # contained in any of the AllocationRequest objects in the
        # allocation_requests field
        'provider_summaries': fields.ListOfObjectsField('ProviderSummary'),
    }

    @classmethod
    def get_by_filters(cls, context, filters):
        """Returns an AllocationCandidates object containing all resource
        providers matching a set of supplied resource constraints, with a set
        of allocation requests constructed from that list of resource
        providers.

        :param filters: A dict of filters containing one or more of the
                        following keys:

            'resources': A dict, keyed by resource class name, of amounts of
                         that resource being requested. The resource provider
                         must either have capacity for the amount being
                         requested or be associated via aggregate to a provider
                         that shares this resource and has capacity for the
                         requested amount.
        """
        _ensure_rc_cache(context)
        alloc_reqs, provider_summaries = cls._get_by_filters(context, filters)
        return cls(
            context,
            allocation_requests=alloc_reqs,
            provider_summaries=provider_summaries,
        )

    # TODO(jaypipes): See what we can pull out of here into helper functions to
    # minimize the complexity of this method.
    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_filters(context, filters):
        # We first get the list of "root providers" that either have the
        # requested resources or are associated with the providers that
        # share one or more of the requested resource(s)
        resources = filters.get('resources')
        if not resources:
            raise ValueError(_("Supply a resources collection in filters."))

        # Transform resource string names to internal integer IDs
        resources = {
            _RC_CACHE.id_from_string(key): value
            for key, value in resources.items()
        }

        roots = [r[0] for r in _get_all_with_shared(context, resources)]

        if not roots:
            return [], []

        # Contains a set of resource provider IDs for each resource class
        # requested
        sharing_providers = {
            rc_id: _get_providers_with_shared_capacity(context, rc_id, amount)
            for rc_id, amount in resources.items()
        }
        # We need to grab usage information for all the providers identified as
        # potentially fulfilling part of the resource request. This includes
        # "root providers" returned from _get_all_with_shared() as well as all
        # the providers of shared resources. Here, we simply grab a unique set
        # of all those resource provider internal IDs by set union'ing them
        # together
        all_rp_ids = set(roots)
        for rps in sharing_providers.values():
            all_rp_ids |= set(rps)

        # Grab usage summaries for each provider (local or sharing) and
        # resource class requested
        usages = _get_usages_by_provider_and_rc(
            context,
            all_rp_ids,
            list(resources.keys()),
        )

        # Build up a dict, keyed by internal resource provider ID, of usage
        # information from which we will then build both allocation request and
        # provider summary information
        summaries = {}
        for usage in usages:
            u_rp_id = usage['resource_provider_id']
            u_rp_uuid = usage['resource_provider_uuid']
            u_rc_id = usage['resource_class_id']
            # NOTE(jaypipes): usage['used'] may be None due to the LEFT JOIN of
            # the usages subquery, so we coerce NULL values to 0 here.
            used = usage['used'] or 0
            allocation_ratio = usage['allocation_ratio']
            cap = int((usage['total'] - usage['reserved']) * allocation_ratio)

            summary = summaries.get(u_rp_id)
            if not summary:
                summary = {
                    'uuid': u_rp_uuid,
                    'resources': {},
                    # TODO(jaypipes): Fill in the provider's traits...
                    'traits': [],
                }
                summaries[u_rp_id] = summary
            summary['resources'][u_rc_id] = {
                'capacity': cap,
                'used': used,
            }

        # Next, build up a list of allocation requests. These allocation
        # requests are AllocationRequest objects, containing resource provider
        # UUIDs, resource class names and amounts to consume from that resource
        # provider
        alloc_request_objs = []

        # Build a dict, keyed by resource class ID, of
        # AllocationRequestResource objects that represent each resource
        # provider for a shared resource
        sharing_resource_requests = collections.defaultdict(list)
        for shared_rc_id in sharing_providers.keys():
            sharing = sharing_providers[shared_rc_id]
            for sharing_rp_id in sharing:
                sharing_summary = summaries[sharing_rp_id]
                sharing_rp_uuid = sharing_summary['uuid']
                sharing_res_req = AllocationRequestResource(
                    context,
                    resource_provider=ResourceProvider(
                        context,
                        uuid=sharing_rp_uuid,
                    ),
                    resource_class=_RC_CACHE.string_from_id(shared_rc_id),
                    amount=resources[shared_rc_id],
                )
                sharing_resource_requests[shared_rc_id].append(sharing_res_req)

        for root_rp_id in roots:
            if root_rp_id not in summaries:
                # This resource provider is not providing any resources that
                # have been requested. This means that this resource provider
                # has some requested resources shared *with* it but the
                # allocation of the requested resource will not be made against
                # it. Since this provider won't actually have an allocation
                # request written for it, we just ignore it and continue
                continue
            root_summary = summaries[root_rp_id]
            root_rp_uuid = root_summary['uuid']
            local_resources = set(
                rc_id for rc_id in resources.keys()
                if rc_id in root_summary['resources']
            )
            shared_resources = set(
                rc_id for rc_id in resources.keys()
                if rc_id not in root_summary['resources']
            )
            # Determine if the root provider actually has all the resources
            # requested. If not, we need to add an AllocationRequest
            # alternative containing this resource for each sharing provider
            has_all = len(shared_resources) == 0
            if has_all:
                resource_requests = [
                    AllocationRequestResource(
                        context,
                        resource_provider=ResourceProvider(
                            context,
                            uuid=root_rp_uuid,
                        ),
                        resource_class=_RC_CACHE.string_from_id(rc_id),
                        amount=amount,
                    ) for rc_id, amount in resources.items()
                ]
                req_obj = AllocationRequest(
                    context,
                    resource_requests=resource_requests,
                )
                alloc_request_objs.append(req_obj)
                continue

            has_none = len(local_resources) == 0
            if has_none:
                # This resource provider doesn't actually provide any requested
                # resource. It only has requested resources shared *with* it.
                # We do not list this provider in allocation_requests but do
                # list it in provider_summaries.
                continue

            # If there are no resource providers sharing resources involved in
            # this request, there's no point building a set of allocation
            # requests that involve resource providers other than the "root
            # providers" that have all the local resources on them
            if not sharing_resource_requests:
                continue

            # add an AllocationRequest that includes local resources from the
            # root provider and shared resources from each sharing provider of
            # that resource class
            non_shared_resources = local_resources - shared_resources
            non_shared_requests = [
                AllocationRequestResource(
                    context,
                    resource_provider=ResourceProvider(
                        context,
                        uuid=root_rp_uuid,
                    ),
                    resource_class=_RC_CACHE.string_from_id(rc_id),
                    amount=amount,
                ) for rc_id, amount in resources.items()
                if rc_id in non_shared_resources
            ]
            sharing_request_tuples = zip(
                sharing_resource_requests[shared_rc_id]
                for shared_rc_id in shared_resources
            )
            # sharing_request_tuples will now contain a list of tuples with the
            # tuples being AllocationRequestResource objects for each provider
            # of a shared resource
            for shared_request_tuple in sharing_request_tuples:
                shared_requests = list(*shared_request_tuple)
                resource_requests = non_shared_requests + shared_requests
                req_obj = AllocationRequest(
                    context,
                    resource_requests=resource_requests,
                )
                alloc_request_objs.append(req_obj)

        # Finally, construct the object representations for the provider
        # summaries we built above. These summaries may be used by the
        # scheduler (or any other caller) to sort and weigh for its eventual
        # placement and claim decisions
        summary_objs = []
        for rp_id, summary in summaries.items():
            rp_uuid = summary['uuid']
            rps_resources = []
            for rc_id, usage in summary['resources'].items():
                rc_name = _RC_CACHE.string_from_id(rc_id)
                rpsr_obj = ProviderSummaryResource(
                    context,
                    resource_class=rc_name,
                    capacity=usage['capacity'],
                    used=usage['used'],
                )
                rps_resources.append(rpsr_obj)

            summary_obj = ProviderSummary(
                context,
                resource_provider=ResourceProvider(
                    context,
                    uuid=rp_uuid,
                ),
                resources=rps_resources,
            )
            summary_objs.append(summary_obj)

        return alloc_request_objs, summary_objs
