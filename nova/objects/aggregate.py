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

from nova.compute import utils as compute_utils
from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


class Aggregate(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    VERSION = '1.1'

    fields = {
        'id': fields.IntegerField(),
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
            else:
                db_key = key
            aggregate[key] = db_aggregate[db_key]
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
        db_aggregate = db.aggregate_get(context, aggregate_id)
        return cls._from_db_object(context, cls(), db_aggregate)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        self._assert_no_hosts('create')
        updates = self.obj_get_changes()
        payload = dict(updates)
        if 'metadata' in updates:
            # NOTE(danms): For some reason the notification format is weird
            payload['meta_data'] = payload.pop('metadata')
        compute_utils.notify_about_aggregate_update(context,
                                                    "create.start",
                                                    payload)
        metadata = updates.pop('metadata', None)
        db_aggregate = db.aggregate_create(context, updates, metadata=metadata)
        self._from_db_object(context, self, db_aggregate)
        payload['aggregate_id'] = self.id
        compute_utils.notify_about_aggregate_update(context,
                                                    "create.end",
                                                    payload)

    @base.remotable
    def save(self, context):
        self._assert_no_hosts('save')
        updates = self.obj_get_changes()

        payload = {'aggregate_id': self.id}
        if 'metadata' in updates:
            payload['meta_data'] = updates['metadata']
        compute_utils.notify_about_aggregate_update(context,
                                                    "updateprop.start",
                                                    payload)
        updates.pop('id', None)
        db_aggregate = db.aggregate_update(context, self.id, updates)
        compute_utils.notify_about_aggregate_update(context,
                                                    "updateprop.end",
                                                    payload)
        self._from_db_object(context, self, db_aggregate)

    @base.remotable
    def update_metadata(self, context, updates):
        payload = {'aggregate_id': self.id,
                   'meta_data': updates}
        compute_utils.notify_about_aggregate_update(context,
                                                    "updatemetadata.start",
                                                    payload)
        to_add = {}
        for key, value in updates.items():
            if value is None:
                try:
                    db.aggregate_metadata_delete(context, self.id, key)
                except exception.AggregateMetadataNotFound:
                    pass
                try:
                    self.metadata.pop(key)
                except KeyError:
                    pass
            else:
                to_add[key] = value
                self.metadata[key] = value
        db.aggregate_metadata_add(context, self.id, to_add)
        compute_utils.notify_about_aggregate_update(context,
                                                    "updatemetadata.end",
                                                    payload)
        self.obj_reset_changes(fields=['metadata'])

    @base.remotable
    def destroy(self, context):
        db.aggregate_delete(context, self.id)

    @base.remotable
    def add_host(self, context, host):
        db.aggregate_host_add(context, self.id, host)
        if self.hosts is None:
            self.hosts = []
        self.hosts.append(host)
        self.obj_reset_changes(fields=['hosts'])

    @base.remotable
    def delete_host(self, context, host):
        db.aggregate_host_delete(context, self.id, host)
        self.hosts.remove(host)
        self.obj_reset_changes(fields=['hosts'])

    @property
    def availability_zone(self):
        return self.metadata.get('availability_zone', None)


class AggregateList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added key argument to get_by_host()
    #              Aggregate <= version 1.1
    # Version 1.2: Added get_by_metadata_key
    VERSION = '1.2'

    fields = {
        'objects': fields.ListOfObjectsField('Aggregate'),
        }
    child_versions = {
        '1.0': '1.1',
        '1.1': '1.1',
        # NOTE(danms): Aggregate was at 1.1 before we added this
        '1.2': '1.1',
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
        if hosts:
            db_aggregates = cls._filter_db_aggregates(db_aggregates, hosts)
        return base.obj_make_list(context, cls(context), objects.Aggregate,
                                  db_aggregates)
