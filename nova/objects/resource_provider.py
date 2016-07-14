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

import six
import sqlalchemy as sa
from sqlalchemy.orm import contains_eager

from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models as models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

_INV_TBL = models.Inventory.__table__
_RP_TBL = models.ResourceProvider.__table__


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

    :param conn: DB connection to use.
    :param rp: Resource provider from which to delete inventory.
    :param to_delete: set() containing resource class IDs for records to
                      delete.
    """
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
    for res_class in to_add:
        inv_record = inv_list.find(res_class)
        if inv_record.capacity <= 0:
            raise exception.ObjectActionError(
                action='add inventory', reason='invalid resource capacity')
        ins_stmt = _INV_TBL.insert().values(
                resource_provider_id=rp.id,
                resource_class_id=res_class,
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
    """
    for res_class in to_update:
        inv_record = inv_list.find(res_class)
        if inv_record.capacity <= 0:
            raise exception.ObjectActionError(
                action='update inventory', reason='invalid resource capacity')
        upd_stmt = _INV_TBL.update().where(sa.and_(
                _INV_TBL.c.resource_provider_id == rp.id,
                _INV_TBL.c.resource_class_id == res_class)).values(
                        total=inv_record.total,
                        reserved=inv_record.reserved,
                        min_unit=inv_record.min_unit,
                        max_unit=inv_record.max_unit,
                        step_size=inv_record.step_size,
                        allocation_ratio=inv_record.allocation_ratio)
        res = conn.execute(upd_stmt)
        if not res.rowcount:
            raise exception.NotFound(
                'No inventory of class %s found for update'
                % fields.ResourceClass.from_index(res_class))


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


@db_api.placement_context_manager.writer
def _add_inventory(context, rp, inventory):
    """Add one Inventory that wasn't already on the provider."""
    resource_class_id = fields.ResourceClass.index(inventory.resource_class)
    inv_list = InventoryList(objects=[inventory])
    conn = context.session.connection()
    with conn.begin():
        _add_inventory_to_provider(
            conn, rp, inv_list, set([resource_class_id]))
        rp.generation = _increment_provider_generation(conn, rp)


@db_api.placement_context_manager.writer
def _update_inventory(context, rp, inventory):
    """Update an inventory already on the provider."""
    resource_class_id = fields.ResourceClass.index(inventory.resource_class)
    inv_list = InventoryList(objects=[inventory])
    conn = context.session.connection()
    with conn.begin():
        _update_inventory_for_provider(
            conn, rp, inv_list, set([resource_class_id]))
        rp.generation = _increment_provider_generation(conn, rp)


@db_api.placement_context_manager.writer
def _delete_inventory(context, rp, resource_class_id):
    """Delete up to one Inventory of the given resource_class id."""

    conn = context.session.connection()
    with conn.begin():
        if not _delete_inventory_from_provider(conn, rp, [resource_class_id]):
            raise exception.NotFound(
                'No inventory of class %s found for delete'
                % fields.ResourceClass.from_index(resource_class_id))
        rp.generation = _increment_provider_generation(conn, rp)


@db_api.placement_context_manager.writer
def _set_inventory(context, rp, inv_list):
    """Given an InventoryList object, replaces the inventory of the
    resource provider in a safe, atomic fashion using the resource
    provider's generation as a consistent view marker.

    :param context: Nova RequestContext.
    :param rp: `ResourceProvider` object upon which to set inventory.
    :param inv_list: `InventoryList` object to save to backend storage.
    :raises nova.exception.ConcurrentUpdateDetected: if another thread updated
            the same resource provider's view of its inventory or allocations
            in between the time when this object was originally read
            and the call to set the inventory.
    """

    conn = context.session.connection()

    existing_resources = _get_current_inventory_resources(conn, rp)
    these_resources = set([fields.ResourceClass.index(r.resource_class)
                           for r in inv_list.objects])

    # Determine which resources we should be adding, deleting and/or
    # updating in the resource provider's inventory by comparing sets
    # of resource class identifiers.
    to_add = these_resources - existing_resources
    to_delete = existing_resources - these_resources
    to_update = these_resources & existing_resources

    with conn.begin():
        if to_delete:
            _delete_inventory_from_provider(conn, rp, to_delete)
        if to_add:
            _add_inventory_to_provider(conn, rp, inv_list, to_add)
        if to_update:
            _update_inventory_for_provider(conn, rp, inv_list, to_update)

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


@base.NovaObjectRegistry.register
class ResourceProvider(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add destroy()
    VERSION = '1.1'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(nullable=False),
        'name': fields.StringField(nullable=False),
        'generation': fields.IntegerField(nullable=False),
    }

    @base.remotable
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

    @base.remotable
    def destroy(self):
        self._delete(self._context, self.id)

    @base.remotable
    def save(self):
        updates = self.obj_get_changes()
        if updates and updates.keys() != ['name']:
            raise exception.ObjectActionError(
                action='save',
                reason='Immutable fields changed')
        self._update_in_db(self._context, self.id, updates)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        db_resource_provider = cls._get_by_uuid_from_db(context, uuid)
        return cls._from_db_object(context, cls(), db_resource_provider)

    @base.remotable
    def add_inventory(self, inventory):
        """Add one new Inventory to the resource provider.

        Fails if Inventory of the provided resource class is
        already present.
        """
        _add_inventory(self._context, self, inventory)
        self.obj_reset_changes()

    @base.remotable
    def delete_inventory(self, resource_class):
        """Delete Inventory of provided resource_class."""
        resource_class_id = fields.ResourceClass.index(resource_class)
        _delete_inventory(self._context, self, resource_class_id)
        self.obj_reset_changes()

    @base.remotable
    def set_inventory(self, inv_list):
        """Set all resource provider Inventory to be the provided list."""
        _set_inventory(self._context, self, inv_list)
        self.obj_reset_changes()

    @base.remotable
    def update_inventory(self, inventory):
        """Update one existing Inventory of the same resource class.

        Fails if no Inventory of the same class is present.
        """
        _update_inventory(self._context, self, inventory)
        self.obj_reset_changes()

    @staticmethod
    @db_api.placement_context_manager.writer
    def _create_in_db(context, updates):
        db_rp = models.ResourceProvider()
        db_rp.update(updates)
        context.session.add(db_rp)
        return db_rp

    @staticmethod
    @db_api.placement_context_manager.writer
    def _delete(context, _id):
        # Don't delete the resource provider if it has allocations.
        rp_allocations = context.session.query(models.Allocation).\
                         filter(models.Allocation.resource_provider_id == _id).\
                         count()
        if rp_allocations:
            raise exception.ResourceProviderInUse()
        # Delete any inventory associated with the resource provider
        context.session.query(models.Inventory).\
            filter(models.Inventory.resource_provider_id == _id).delete()
        result = context.session.query(models.ResourceProvider).\
                 filter(models.ResourceProvider.id == _id).delete()
        if not result:
            raise exception.NotFound()

    @staticmethod
    @db_api.placement_context_manager.writer
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
    @db_api.placement_context_manager.reader
    def _get_by_uuid_from_db(context, uuid):
        result = context.session.query(models.ResourceProvider).filter_by(
            uuid=uuid).first()
        if not result:
            raise exception.NotFound()
        return result


@base.NovaObjectRegistry.register
class ResourceProviderList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial Version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('ResourceProvider'),
    }

    @staticmethod
    @db_api.placement_context_manager.reader
    def _get_all_by_filters_from_db(context, filters):
        if not filters:
            filters = {}
        query = context.session.query(models.ResourceProvider)
        if 'name' in filters:
            query = query.filter_by(name=filters['name'])
        query = query.filter_by(can_host=filters.get('can_host', 0))
        return query.all()

    @base.remotable_classmethod
    def get_all_by_filters(cls, context, filters=None):
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
            resource_class = updates.pop('resource_class')
        except KeyError:
            raise exception.ObjectActionError(
                action='create',
                reason='resource_class required')
        updates['resource_class_id'] = fields.ResourceClass.index(
            resource_class)
        return updates

    @staticmethod
    def _from_db_object(context, target, source):
        for field in target.fields:
            if field not in ('resource_provider', 'resource_class'):
                setattr(target, field, source[field])

        if 'resource_class' not in target:
            target.resource_class = (
                target.fields['resource_class'].from_index(
                    source['resource_class_id']))
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


@db_api.placement_context_manager.writer
def _create_inventory_in_db(context, updates):
    db_inventory = models.Inventory()
    db_inventory.update(updates)
    context.session.add(db_inventory)
    return db_inventory


@db_api.placement_context_manager.writer
def _update_inventory_in_db(context, id_, updates):
    result = context.session.query(
        models.Inventory).filter_by(id=id_).update(updates)
    if not result:
        raise exception.NotFound()


@base.NovaObjectRegistry.register
class Inventory(_HasAResourceProvider):
    # Version 1.0: Initial version
    VERSION = '1.0'

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

    @property
    def capacity(self):
        """Inventory capacity, adjusted by allocation_ratio."""
        return int((self.total - self.reserved) * self.allocation_ratio)

    @base.remotable
    def create(self):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self._make_db(self.obj_get_changes())
        db_inventory = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_inventory)

    @base.remotable
    def save(self):
        if 'id' not in self:
            raise exception.ObjectActionError(action='save',
                                              reason='not created')
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
    VERSION = '1.0'

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
        if isinstance(res_class, six.string_types):
            res_class = fields.ResourceClass.index(res_class)

        for inv_rec in self.objects:
            if fields.ResourceClass.index(inv_rec.resource_class) == res_class:
                return inv_rec

    @staticmethod
    @db_api.placement_context_manager.reader
    def _get_all_by_resource_provider(context, rp_uuid):
        return context.session.query(models.Inventory).\
            join(models.Inventory.resource_provider).\
            options(contains_eager('resource_provider')).\
            filter(models.ResourceProvider.uuid == rp_uuid).all()

    @base.remotable_classmethod
    def get_all_by_resource_provider_uuid(cls, context, rp_uuid):
        db_inventory_list = cls._get_all_by_resource_provider(context,
                                                              rp_uuid)
        return base.obj_make_list(context, cls(context), objects.Inventory,
                                  db_inventory_list)


@base.NovaObjectRegistry.register
class Allocation(_HasAResourceProvider):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'resource_provider': fields.ObjectField('ResourceProvider'),
        'consumer_id': fields.UUIDField(),
        'resource_class': fields.ResourceClassField(),
        'used': fields.IntegerField(),
    }

    @staticmethod
    @db_api.placement_context_manager.writer
    def _create_in_db(context, updates):
        db_allocation = models.Allocation()
        db_allocation.update(updates)
        context.session.add(db_allocation)
        return db_allocation

    @staticmethod
    @db_api.placement_context_manager.writer
    def _destroy(context, id):
        result = context.session.query(models.Allocation).filter_by(
            id=id).delete()
        if not result:
            raise exception.NotFound()

    @base.remotable
    def create(self):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self._make_db(self.obj_get_changes())
        db_allocation = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_allocation)

    @base.remotable
    def destroy(self):
        self._destroy(self._context, self.id)


@base.NovaObjectRegistry.register
class AllocationList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial Version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Allocation'),
    }

    @staticmethod
    @db_api.placement_context_manager.reader
    def _get_allocations_from_db(context, rp_uuid):
        query = (context.session.query(models.Allocation)
                 .join(models.Allocation.resource_provider)
                 .options(contains_eager('resource_provider'))
                 .filter(models.ResourceProvider.uuid == rp_uuid))
        return query.all()

    @base.remotable_classmethod
    def get_all_by_resource_provider_uuid(cls, context, rp_uuid):
        db_allocation_list = cls._get_allocations_from_db(
            context, rp_uuid)
        return base.obj_make_list(
            context, cls(context), objects.Allocation, db_allocation_list)
