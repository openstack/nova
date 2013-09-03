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
from nova.objects import base
from nova.objects import utils


class Aggregate(base.NovaObject):
    fields = {
        'id': int,
        'name': str,
        'hosts': utils.list_of_strings_or_none,
        'metadata': utils.dict_of_strings_or_none,
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
        self._assert_no_hosts('create')
        updates = {}
        for key in self.obj_what_changed():
            updates[key] = self[key]
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
        updates = {}
        for key in self.obj_what_changed():
            updates[key] = self[key]

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
        return self._from_db_object(context, self, db_aggregate)

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
        payload['meta_data'] = to_add
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


def _make_list(context, list_obj, item_cls, db_list):
    list_obj.objects = []
    for db_item in db_list:
        item = item_cls._from_db_object(context, item_cls(), db_item)
        list_obj.objects.append(item)
    list_obj.obj_reset_changes()
    return list_obj


class AggregateList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_all(cls, context):
        db_aggregates = db.aggregate_get_all(context)
        return _make_list(context, AggregateList(), Aggregate, db_aggregates)

    @base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_aggregates = db.aggregate_get_by_host(context, host)
        return _make_list(context, AggregateList(), Aggregate, db_aggregates)
