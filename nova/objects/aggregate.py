#    Copyright 2013 IBM Corp.
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

from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import uuidutils
import six
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func
from sqlalchemy.sql import text

from nova.compute import utils as compute_utils
from nova import db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova.db.sqlalchemy import models as main_models
from nova import exception
from nova.i18n import _, _LW
from nova import objects
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)

DEPRECATED_FIELDS = ['deleted', 'deleted_at']


@db_api.api_context_manager.reader
def _aggregate_get_from_db(context, aggregate_id):
    query = context.session.query(api_models.Aggregate).\
            options(joinedload('_hosts')).\
            options(joinedload('_metadata'))
    query = query.filter(api_models.Aggregate.id == aggregate_id)

    aggregate = query.first()

    if not aggregate:
        raise exception.AggregateNotFound(aggregate_id=aggregate_id)

    return aggregate


@db_api.api_context_manager.reader
def _aggregate_get_from_db_by_uuid(context, aggregate_uuid):
    query = context.session.query(api_models.Aggregate).\
            options(joinedload('_hosts')).\
            options(joinedload('_metadata'))
    query = query.filter(api_models.Aggregate.uuid == aggregate_uuid)

    aggregate = query.first()

    if not aggregate:
        raise exception.AggregateNotFound(aggregate_id=aggregate_uuid)

    return aggregate


def _host_add_to_db(context, aggregate_id, host):
    try:
        with db_api.api_context_manager.writer.using(context):
            # Check to see if the aggregate exists
            _aggregate_get_from_db(context, aggregate_id)

            host_ref = api_models.AggregateHost()
            host_ref.update({"host": host, "aggregate_id": aggregate_id})
            host_ref.save(context.session)
            return host_ref
    except db_exc.DBDuplicateEntry:
        raise exception.AggregateHostExists(host=host,
                                            aggregate_id=aggregate_id)


def _host_delete_from_db(context, aggregate_id, host):
    count = 0
    with db_api.api_context_manager.writer.using(context):
        # Check to see if the aggregate exists
        _aggregate_get_from_db(context, aggregate_id)

        query = context.session.query(api_models.AggregateHost)
        query = query.filter(api_models.AggregateHost.aggregate_id ==
                                aggregate_id)
        count = query.filter_by(host=host).delete()

    if count == 0:
        raise exception.AggregateHostNotFound(aggregate_id=aggregate_id,
                                              host=host)


def _metadata_add_to_db(context, aggregate_id, metadata, max_retries=10,
                        set_delete=False):
    all_keys = metadata.keys()
    for attempt in range(max_retries):
        try:
            with db_api.api_context_manager.writer.using(context):
                query = context.session.query(api_models.AggregateMetadata).\
                            filter_by(aggregate_id=aggregate_id)

                if set_delete:
                    query.filter(~api_models.AggregateMetadata.key.
                                 in_(all_keys)).\
                                 delete(synchronize_session=False)

                already_existing_keys = set()
                if all_keys:
                    query = query.filter(
                        api_models.AggregateMetadata.key.in_(all_keys))
                    for meta_ref in query.all():
                        key = meta_ref.key
                        meta_ref.update({"value": metadata[key]})
                        already_existing_keys.add(key)

                new_entries = []
                for key, value in metadata.items():
                    if key in already_existing_keys:
                        continue
                    new_entries.append({"key": key,
                                        "value": value,
                                        "aggregate_id": aggregate_id})
                if new_entries:
                    context.session.execute(
                        api_models.AggregateMetadata.__table__.insert(),
                        new_entries)

                return metadata
        except db_exc.DBDuplicateEntry:
            # a concurrent transaction has been committed,
            # try again unless this was the last attempt
            with excutils.save_and_reraise_exception() as ctxt:
                if attempt < max_retries - 1:
                    ctxt.reraise = False
                else:
                    msg = _("Add metadata failed for aggregate %(id)s "
                            "after %(retries)s retries") % \
                              {"id": aggregate_id, "retries": max_retries}
                    LOG.warning(msg)


@db_api.api_context_manager.writer
def _metadata_delete_from_db(context, aggregate_id, key):
    # Check to see if the aggregate exists
    _aggregate_get_from_db(context, aggregate_id)

    query = context.session.query(api_models.AggregateMetadata)
    query = query.filter(api_models.AggregateMetadata.aggregate_id ==
                            aggregate_id)
    count = query.filter_by(key=key).delete()

    if count == 0:
        raise exception.AggregateMetadataNotFound(
                            aggregate_id=aggregate_id, metadata_key=key)


@db_api.api_context_manager.writer
def _aggregate_create_in_db(context, values, metadata=None):
    query = context.session.query(api_models.Aggregate)
    query = query.filter(api_models.Aggregate.name == values['name'])
    aggregate = query.first()

    if not aggregate:
        aggregate = api_models.Aggregate()
        aggregate.update(values)
        aggregate.save(context.session)
        # We don't want these to be lazy loaded later.  We know there is
        # nothing here since we just created this aggregate.
        aggregate._hosts = []
        aggregate._metadata = []
    else:
        raise exception.AggregateNameExists(aggregate_name=values['name'])
    if metadata:
        _metadata_add_to_db(context, aggregate.id, metadata)
        context.session.expire(aggregate, ['_metadata'])
        aggregate._metadata

    return aggregate


@db_api.api_context_manager.writer
def _aggregate_delete_from_db(context, aggregate_id):
    # Delete Metadata first
    context.session.query(api_models.AggregateMetadata).\
        filter_by(aggregate_id=aggregate_id).\
        delete()

    count = context.session.query(api_models.Aggregate).\
                filter(api_models.Aggregate.id == aggregate_id).\
                delete()

    if count == 0:
        raise exception.AggregateNotFound(aggregate_id=aggregate_id)


@db_api.api_context_manager.writer
def _aggregate_update_to_db(context, aggregate_id, values):
    aggregate = _aggregate_get_from_db(context, aggregate_id)

    set_delete = True
    if "availability_zone" in values:
        az = values.pop('availability_zone')
        if 'metadata' not in values:
            values['metadata'] = {'availability_zone': az}
            set_delete = False
        else:
            values['metadata']['availability_zone'] = az
    metadata = values.get('metadata')
    if metadata is not None:
        _metadata_add_to_db(context, aggregate_id, values.pop('metadata'),
                            set_delete=set_delete)

    aggregate.update(values)
    try:
        aggregate.save(context.session)
    except db_exc.DBDuplicateEntry:
        if 'name' in values:
            raise exception.AggregateNameExists(
                aggregate_name=values['name'])
        else:
            raise
    return _aggregate_get_from_db(context, aggregate_id)


@base.NovaObjectRegistry.register
class Aggregate(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Added uuid field
    # Version 1.3: Added get_by_uuid method
    VERSION = '1.3'

    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.UUIDField(nullable=False),
        'name': fields.StringField(),
        'hosts': fields.ListOfStringsField(nullable=True),
        'metadata': fields.DictOfStringsField(nullable=True),
        }

    obj_extra_fields = ['availability_zone']

    def __init__(self, *args, **kwargs):
        super(Aggregate, self).__init__(*args, **kwargs)
        self._in_api = False

    @staticmethod
    def _from_db_object(context, aggregate, db_aggregate):
        for key in aggregate.fields:
            if key == 'metadata':
                db_key = 'metadetails'
            elif key in DEPRECATED_FIELDS and key not in db_aggregate:
                continue
            else:
                db_key = key
            setattr(aggregate, key, db_aggregate[db_key])

        # NOTE: This can be removed when we remove compatibility with
        # the old aggregate model.
        if any(f not in db_aggregate for f in DEPRECATED_FIELDS):
            aggregate.deleted_at = None
            aggregate.deleted = False

        aggregate._context = context
        aggregate.obj_reset_changes()

        return aggregate

    def _assert_no_hosts(self, action):
        if 'hosts' in self.obj_what_changed():
            raise exception.ObjectActionError(
                action=action,
                reason='hosts updated inline')

    @property
    def in_api(self):
        if self._in_api:
            return True
        else:
            try:
                _aggregate_get_from_db(self._context, self.id)
                self._in_api = True
            except exception.AggregateNotFound:
                pass
            return self._in_api

    @base.remotable_classmethod
    def get_by_id(cls, context, aggregate_id):
        try:
            db_aggregate = _aggregate_get_from_db(context, aggregate_id)
        except exception.AggregateNotFound:
            db_aggregate = db.aggregate_get(context, aggregate_id)
        return cls._from_db_object(context, cls(), db_aggregate)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, aggregate_uuid):
        try:
            db_aggregate = _aggregate_get_from_db_by_uuid(context,
                                                          aggregate_uuid)
        except exception.AggregateNotFound:
            db_aggregate = db.aggregate_get_by_uuid(context, aggregate_uuid)
        return cls._from_db_object(context, cls(), db_aggregate)

    @staticmethod
    @db_api.pick_context_manager_reader
    def _ensure_migrated(context):
        result = context.session.query(main_models.Aggregate).\
                 filter_by(deleted=0).count()
        if result:
            LOG.warning(
                _LW('Main database contains %(count)i unmigrated aggregates'),
                {'count': result})
        return result == 0

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

        # NOTE(mdoff): Once we have made it past a point where we know
        # all aggregates have been migrated, we can remove this. Ideally
        # in Ocata with a blocker migration to be sure.
        if not self._ensure_migrated(self._context):
            raise exception.ObjectActionError(
                action='create',
                reason='main database still contains aggregates')

        self._assert_no_hosts('create')
        updates = self.obj_get_changes()
        payload = dict(updates)
        if 'metadata' in updates:
            # NOTE(danms): For some reason the notification format is weird
            payload['meta_data'] = payload.pop('metadata')
        if 'uuid' not in updates:
            updates['uuid'] = uuidutils.generate_uuid()
            self.uuid = updates['uuid']
            LOG.debug('Generated uuid %(uuid)s for aggregate',
                      dict(uuid=updates['uuid']))
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "create.start",
                                                    payload)
        compute_utils.notify_about_aggregate_action(
            context=self._context,
            aggregate=self,
            action=fields.NotificationAction.CREATE,
            phase=fields.NotificationPhase.START)

        metadata = updates.pop('metadata', None)
        db_aggregate = _aggregate_create_in_db(self._context, updates,
                                               metadata=metadata)
        self._from_db_object(self._context, self, db_aggregate)
        payload['aggregate_id'] = self.id
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "create.end",
                                                    payload)
        compute_utils.notify_about_aggregate_action(
            context=self._context,
            aggregate=self,
            action=fields.NotificationAction.CREATE,
            phase=fields.NotificationPhase.END)

    @base.remotable
    def save(self):
        self._assert_no_hosts('save')
        updates = self.obj_get_changes()

        payload = {'aggregate_id': self.id}
        if 'metadata' in updates:
            payload['meta_data'] = updates['metadata']
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updateprop.start",
                                                    payload)
        updates.pop('id', None)
        try:
            db_aggregate = _aggregate_update_to_db(self._context,
                                                   self.id, updates)
        except exception.AggregateNotFound:
            db_aggregate = db.aggregate_update(self._context, self.id, updates)

        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updateprop.end",
                                                    payload)
        self._from_db_object(self._context, self, db_aggregate)

    @base.remotable
    def update_metadata(self, updates):
        if self.in_api:
            metadata_delete = _metadata_delete_from_db
            metadata_add = _metadata_add_to_db
        else:
            metadata_delete = db.aggregate_metadata_delete
            metadata_add = db.aggregate_metadata_add

        payload = {'aggregate_id': self.id,
                   'meta_data': updates}
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updatemetadata.start",
                                                    payload)
        to_add = {}
        for key, value in updates.items():
            if value is None:
                try:
                    metadata_delete(self._context, self.id, key)
                except exception.AggregateMetadataNotFound:
                    pass
                try:
                    self.metadata.pop(key)
                except KeyError:
                    pass
            else:
                to_add[key] = value
                self.metadata[key] = value
        metadata_add(self._context, self.id, to_add)
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updatemetadata.end",
                                                    payload)
        self.obj_reset_changes(fields=['metadata'])

    @base.remotable
    def destroy(self):
        try:
            _aggregate_delete_from_db(self._context, self.id)
        except exception.AggregateNotFound:
            db.aggregate_delete(self._context, self.id)

    @base.remotable
    def add_host(self, host):
        if self.in_api:
            _host_add_to_db(self._context, self.id, host)
        else:
            db.aggregate_host_add(self._context, self.id, host)

        if self.hosts is None:
            self.hosts = []
        self.hosts.append(host)
        self.obj_reset_changes(fields=['hosts'])

    @base.remotable
    def delete_host(self, host):
        if self.in_api:
            _host_delete_from_db(self._context, self.id, host)
        else:
            db.aggregate_host_delete(self._context, self.id, host)

        self.hosts.remove(host)
        self.obj_reset_changes(fields=['hosts'])

    @property
    def availability_zone(self):
        return self.metadata.get('availability_zone', None)


@db_api.api_context_manager.reader
def _get_all_from_db(context):
    query = context.session.query(api_models.Aggregate).\
            options(joinedload('_hosts')).\
            options(joinedload('_metadata'))

    return query.all()


@db_api.api_context_manager.reader
def _get_by_host_from_db(context, host, key=None):
    query = context.session.query(api_models.Aggregate).\
            options(joinedload('_hosts')).\
            options(joinedload('_metadata'))
    query = query.join('_hosts')
    query = query.filter(api_models.AggregateHost.host == host)

    if key:
        query = query.join("_metadata").filter(
            api_models.AggregateMetadata.key == key)

    return query.all()


@db_api.api_context_manager.reader
def _get_by_metadata_key_from_db(context, key):
    query = context.session.query(api_models.Aggregate)
    query = query.join("_metadata")
    query = query.filter(api_models.AggregateMetadata.key == key)
    query = query.options(contains_eager("_metadata"))
    query = query.options(joinedload("_hosts"))

    return query.all()


@base.NovaObjectRegistry.register
class AggregateList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added key argument to get_by_host()
    #              Aggregate <= version 1.1
    # Version 1.2: Added get_by_metadata_key
    VERSION = '1.2'

    fields = {
        'objects': fields.ListOfObjectsField('Aggregate'),
        }

    # NOTE(mdoff): Calls to this can be removed when we remove
    # compatibility with the old aggregate model.
    @staticmethod
    def _fill_deprecated(db_aggregate):
        db_aggregate['deleted_at'] = None
        db_aggregate['deleted'] = False
        return db_aggregate

    @classmethod
    def _filter_db_aggregates(cls, db_aggregates, hosts):
        if not isinstance(hosts, set):
            hosts = set(hosts)
        filtered_aggregates = []
        for db_aggregate in db_aggregates:
            for host in db_aggregate['hosts']:
                if host in hosts:
                    filtered_aggregates.append(db_aggregate)
                    break
        return filtered_aggregates

    @base.remotable_classmethod
    def get_all(cls, context):
        api_db_aggregates = [cls._fill_deprecated(agg) for agg in
                                _get_all_from_db(context)]
        db_aggregates = db.aggregate_get_all(context)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates + api_db_aggregates)

    @base.remotable_classmethod
    def get_by_host(cls, context, host, key=None):
        api_db_aggregates = [cls._fill_deprecated(agg) for agg in
                            _get_by_host_from_db(context, host, key=key)]
        db_aggregates = db.aggregate_get_by_host(context, host, key=key)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates + api_db_aggregates)

    @base.remotable_classmethod
    def get_by_metadata_key(cls, context, key, hosts=None):
        api_db_aggregates = [cls._fill_deprecated(agg) for agg in
                            _get_by_metadata_key_from_db(context, key=key)]
        db_aggregates = db.aggregate_get_by_metadata_key(context, key=key)

        all_aggregates = db_aggregates + api_db_aggregates
        if hosts is not None:
            all_aggregates = cls._filter_db_aggregates(all_aggregates, hosts)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  all_aggregates)


@db_api.pick_context_manager_reader
def _get_main_db_aggregate_ids(context, limit):
    from nova.db.sqlalchemy import models
    return [x[0] for x in context.session.query(models.Aggregate.id).
            filter_by(deleted=0).
            limit(limit)]


def migrate_aggregates(ctxt, count):
    main_db_ids = _get_main_db_aggregate_ids(ctxt, count)
    if not main_db_ids:
        return 0, 0

    count_all = len(main_db_ids)
    count_hit = 0

    for aggregate_id in main_db_ids:
        try:
            aggregate = Aggregate.get_by_id(ctxt, aggregate_id)
            remove = ['metadata', 'hosts']
            values = {field: getattr(aggregate, field)
                      for field in aggregate.fields if field not in remove}
            _aggregate_create_in_db(ctxt, values, metadata=aggregate.metadata)
            for host in aggregate.hosts:
                _host_add_to_db(ctxt, aggregate_id, host)
            count_hit += 1
            db.aggregate_delete(ctxt, aggregate.id)
        except exception.AggregateNotFound:
            LOG.warning(
                _LW('Aggregate id %(id)i disappeared during migration'),
                {'id': aggregate_id})
        except (exception.AggregateNameExists) as e:
            LOG.error(six.text_type(e))

    return count_all, count_hit


def _adjust_autoincrement(context, value):
    engine = db_api.get_api_engine()
    if engine.name == 'postgresql':
        # NOTE(danms): If we migrated some aggregates in the above function,
        # then we will have confused postgres' sequence for the autoincrement
        # primary key. MySQL does not care about this, but since postgres does,
        # we need to reset this to avoid a failure on the next aggregate
        # creation.
        engine.execute(
            text('ALTER SEQUENCE aggregates_id_seq RESTART WITH %i;' % (
                value)))


@db_api.api_context_manager.reader
def _get_max_aggregate_id(context):
    return context.session.query(func.max(api_models.Aggregate.id)).one()[0]


def migrate_aggregate_reset_autoincrement(ctxt, count):
    max_id = _get_max_aggregate_id(ctxt) or 0
    _adjust_autoincrement(ctxt, max_id + 1)
    return 0, 0
