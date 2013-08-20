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

from nova import db
from nova.objects import base
from nova.objects import instance as instance_obj
from nova.objects import utils


class Migration(base.NovaObject):
    fields = {
        'id': int,
        'source_compute': utils.str_or_none,
        'dest_compute': utils.str_or_none,
        'source_node': utils.str_or_none,
        'dest_node': utils.str_or_none,
        'dest_host': utils.str_or_none,
        'old_instance_type_id': utils.int_or_none,
        'new_instance_type_id': utils.int_or_none,
        'instance_uuid': utils.str_or_none,
        'status': utils.str_or_none,
        }

    @staticmethod
    def _from_db_object(context, migration, db_migration):
        for key in migration.fields:
            migration[key] = db_migration[key]
        migration._context = context
        migration.obj_reset_changes()
        return migration

    @base.remotable_classmethod
    def get_by_id(cls, context, migration_id):
        db_migration = db.migration_get(context, migration_id)
        return cls._from_db_object(context, cls(), db_migration)

    @base.remotable_classmethod
    def get_by_instance_and_status(cls, context, instance_uuid, status):
        db_migration = db.migration_get_by_instance_and_status(
            context, instance_uuid, status)
        return cls._from_db_object(context, cls(), db_migration)

    @base.remotable
    def create(self, context):
        updates = {}
        for key in self.obj_what_changed():
            updates[key] = self[key]
        updates.pop('id', None)
        db_migration = db.migration_create(context, updates)
        self._from_db_object(context, self, db_migration)

    @base.remotable
    def save(self, context):
        updates = {}
        for key in self.obj_what_changed():
            updates[key] = self[key]
        updates.pop('id', None)
        db_migration = db.migration_update(context, self.id, updates)
        self._from_db_object(context, self, db_migration)
        self.obj_reset_changes()

    @property
    def instance(self):
        return instance_obj.Instance.get_by_uuid(self._context,
                                                 self.instance_uuid)


def _make_list(context, list_obj, item_cls, db_list):
    list_obj.objects = []
    for db_item in db_list:
        item = item_cls._from_db_object(context, item_cls(), db_item)
        list_obj.objects.append(item)
    list_obj.obj_reset_changes()
    return list_obj


class MigrationList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_unconfirmed_by_dest_compute(cls, context, confirm_window,
                                        dest_compute):
        db_migrations = db.migration_get_unconfirmed_by_dest_compute(
            context, confirm_window, dest_compute)
        return _make_list(context, MigrationList(), Migration, db_migrations)

    @base.remotable_classmethod
    def get_in_progress_by_host_and_node(cls, context, host, node):
        db_migrations = db.migration_get_in_progress_by_host_and_node(
            context, host, node)
        return _make_list(context, MigrationList(), Migration, db_migrations)

    @base.remotable_classmethod
    def get_by_filters(cls, context, filters):
        db_migrations = db.migration_get_all_by_filters(context, filters)
        return _make_list(context, MigrationList(), Migration, db_migrations)
