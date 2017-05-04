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
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import joinedload

from nova.compute import utils as compute_utils
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova.i18n import _
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

        # NOTE: This can be removed when we bump Aggregate to v2.0
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

    @base.remotable_classmethod
    def get_by_id(cls, context, aggregate_id):
        db_aggregate = _aggregate_get_from_db(context, aggregate_id)
        return cls._from_db_object(context, cls(), db_aggregate)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, aggregate_uuid):
        db_aggregate = _aggregate_get_from_db_by_uuid(context,
                                                      aggregate_uuid)
        return cls._from_db_object(context, cls(), db_aggregate)

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

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
        compute_utils.notify_about_aggregate_action(
            context=self._context,
            aggregate=self,
            action=fields.NotificationAction.UPDATE_PROP,
            phase=fields.NotificationPhase.START)
        updates.pop('id', None)
        db_aggregate = _aggregate_update_to_db(self._context,
                                               self.id, updates)
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updateprop.end",
                                                    payload)
        compute_utils.notify_about_aggregate_action(
            context=self._context,
            aggregate=self,
            action=fields.NotificationAction.UPDATE_PROP,
            phase=fields.NotificationPhase.END)
        self._from_db_object(self._context, self, db_aggregate)

    @base.remotable
    def update_metadata(self, updates):
        payload = {'aggregate_id': self.id,
                   'meta_data': updates}
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updatemetadata.start",
                                                    payload)
        compute_utils.notify_about_aggregate_action(
            context=self._context,
            aggregate=self,
            action=fields.NotificationAction.UPDATE_METADATA,
            phase=fields.NotificationPhase.START)
        to_add = {}
        for key, value in updates.items():
            if value is None:
                try:
                    _metadata_delete_from_db(self._context, self.id, key)
                except exception.AggregateMetadataNotFound:
                    pass
                try:
                    self.metadata.pop(key)
                except KeyError:
                    pass
            else:
                to_add[key] = value
                self.metadata[key] = value
        _metadata_add_to_db(self._context, self.id, to_add)
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updatemetadata.end",
                                                    payload)
        compute_utils.notify_about_aggregate_action(
            context=self._context,
            aggregate=self,
            action=fields.NotificationAction.UPDATE_METADATA,
            phase=fields.NotificationPhase.END)
        self.obj_reset_changes(fields=['metadata'])

    @base.remotable
    def destroy(self):
        _aggregate_delete_from_db(self._context, self.id)

    @base.remotable
    def add_host(self, host):
        _host_add_to_db(self._context, self.id, host)

        if self.hosts is None:
            self.hosts = []
        self.hosts.append(host)
        self.obj_reset_changes(fields=['hosts'])

    @base.remotable
    def delete_host(self, host):
        _host_delete_from_db(self._context, self.id, host)

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
def _get_by_metadata_from_db(context, key=None, value=None):
    assert(key is not None or value is not None)
    query = context.session.query(api_models.Aggregate)
    query = query.join("_metadata")
    if key is not None:
        query = query.filter(api_models.AggregateMetadata.key == key)
    if value is not None:
        query = query.filter(api_models.AggregateMetadata.value == value)
    query = query.options(contains_eager("_metadata"))
    query = query.options(joinedload("_hosts"))

    return query.all()


@base.NovaObjectRegistry.register
class AggregateList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added key argument to get_by_host()
    #              Aggregate <= version 1.1
    # Version 1.2: Added get_by_metadata_key
    # Version 1.3: Added get_by_metadata
    VERSION = '1.3'

    fields = {
        'objects': fields.ListOfObjectsField('Aggregate'),
        }

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
        db_aggregates = _get_all_from_db(context)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)

    @base.remotable_classmethod
    def get_by_host(cls, context, host, key=None):
        db_aggregates = _get_by_host_from_db(context, host, key=key)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)

    @base.remotable_classmethod
    def get_by_metadata_key(cls, context, key, hosts=None):
        db_aggregates = _get_by_metadata_from_db(context, key=key)
        if hosts is not None:
            db_aggregates = cls._filter_db_aggregates(db_aggregates, hosts)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)

    @base.remotable_classmethod
    def get_by_metadata(cls, context, key=None, value=None):
        """Return aggregates with a metadata key set to value.

        This returns a list of all aggregates that have a metadata key
        set to some value. If key is specified, then only values for
        that key will qualify.
        """
        db_aggregates = _get_by_metadata_from_db(context, key=key, value=value)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)
