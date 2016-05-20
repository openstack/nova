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

from oslo_log import log as logging
from oslo_utils import uuidutils

from nova.compute import utils as compute_utils
from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class Aggregate(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Added uuid field
    VERSION = '1.2'

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
            elif key == 'uuid':
                continue
            else:
                db_key = key
            setattr(aggregate, key, db_aggregate[db_key])

        # NOTE(danms): Remove this conditional load (and remove uuid
        # special cases above) once we're in Newton and have enforced
        # that all UUIDs in the database are not NULL.
        if db_aggregate.get('uuid'):
            aggregate.uuid = db_aggregate['uuid']

        aggregate._context = context
        aggregate.obj_reset_changes()

        # NOTE(danms): This needs to come after obj_reset_changes() to make
        # sure we only save the uuid, if we generate one.
        # FIXME(danms): Remove this in Newton once we have enforced that
        # all aggregates have uuids set in the database.
        if 'uuid' not in aggregate:
            aggregate.uuid = uuidutils.generate_uuid()
            LOG.debug('Generating UUID %(uuid)s for aggregate %(agg)i',
                      dict(uuid=aggregate.uuid, agg=aggregate.id))
            aggregate.save()

        return aggregate

    def _assert_no_hosts(self, action):
        if 'hosts' in self.obj_what_changed():
            raise exception.ObjectActionError(
                action=action,
                reason='hosts updated inline')

    @base.remotable_classmethod
    def get_by_id(cls, context, aggregate_id):
        db_aggregate = db.aggregate_get(context, aggregate_id)
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
            LOG.debug('Generated uuid %(uuid)s for aggregate',
                      dict(uuid=updates['uuid']))
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "create.start",
                                                    payload)
        metadata = updates.pop('metadata', None)
        db_aggregate = db.aggregate_create(self._context, updates,
                                           metadata=metadata)
        self._from_db_object(self._context, self, db_aggregate)
        payload['aggregate_id'] = self.id
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "create.end",
                                                    payload)

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
        db_aggregate = db.aggregate_update(self._context, self.id, updates)
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updateprop.end",
                                                    payload)
        self._from_db_object(self._context, self, db_aggregate)

    @base.remotable
    def update_metadata(self, updates):
        payload = {'aggregate_id': self.id,
                   'meta_data': updates}
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updatemetadata.start",
                                                    payload)
        to_add = {}
        for key, value in updates.items():
            if value is None:
                try:
                    db.aggregate_metadata_delete(self._context, self.id, key)
                except exception.AggregateMetadataNotFound:
                    pass
                try:
                    self.metadata.pop(key)
                except KeyError:
                    pass
            else:
                to_add[key] = value
                self.metadata[key] = value
        db.aggregate_metadata_add(self._context, self.id, to_add)
        compute_utils.notify_about_aggregate_update(self._context,
                                                    "updatemetadata.end",
                                                    payload)
        self.obj_reset_changes(fields=['metadata'])

    @base.remotable
    def destroy(self):
        db.aggregate_delete(self._context, self.id)

    @base.remotable
    def add_host(self, host):
        db.aggregate_host_add(self._context, self.id, host)
        if self.hosts is None:
            self.hosts = []
        self.hosts.append(host)
        self.obj_reset_changes(fields=['hosts'])

    @base.remotable
    def delete_host(self, host):
        db.aggregate_host_delete(self._context, self.id, host)
        self.hosts.remove(host)
        self.obj_reset_changes(fields=['hosts'])

    @property
    def availability_zone(self):
        return self.metadata.get('availability_zone', None)


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
        db_aggregates = db.aggregate_get_all(context)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)

    @base.remotable_classmethod
    def get_by_host(cls, context, host, key=None):
        db_aggregates = db.aggregate_get_by_host(context, host, key=key)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)

    @base.remotable_classmethod
    def get_by_metadata_key(cls, context, key, hosts=None):
        db_aggregates = db.aggregate_get_by_metadata_key(context, key=key)
        if hosts is not None:
            db_aggregates = cls._filter_db_aggregates(db_aggregates, hosts)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)
