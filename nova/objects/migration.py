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
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


# TODO(berrange): Remove NovaObjectDictCompat
class Migration(base.NovaPersistentObject, base.NovaObject,
                base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    VERSION = '1.1'

    fields = {
        'id': fields.IntegerField(),
        'source_compute': fields.StringField(nullable=True),
        'dest_compute': fields.StringField(nullable=True),
        'source_node': fields.StringField(nullable=True),
        'dest_node': fields.StringField(nullable=True),
        'dest_host': fields.StringField(nullable=True),
        'old_instance_type_id': fields.IntegerField(nullable=True),
        'new_instance_type_id': fields.IntegerField(nullable=True),
        'instance_uuid': fields.StringField(nullable=True),
        'status': fields.StringField(nullable=True),
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
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        db_migration = db.migration_create(context, updates)
        self._from_db_object(context, self, db_migration)

    @base.remotable
    def save(self, context):
        updates = self.obj_get_changes()
        updates.pop('id', None)
        db_migration = db.migration_update(context, self.id, updates)
        self._from_db_object(context, self, db_migration)
        self.obj_reset_changes()

    @property
    def instance(self):
        return objects.Instance.get_by_uuid(self._context, self.instance_uuid)


class MigrationList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              Migration <= 1.1
    # Version 1.1: Added use_slave to get_unconfirmed_by_dest_compute
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('Migration'),
        }
    child_versions = {
        '1.0': '1.1',
        # NOTE(danms): Migration was at 1.1 before we added this
        '1.1': '1.1',
        }

    @base.remotable_classmethod
    def get_unconfirmed_by_dest_compute(cls, context, confirm_window,
                                        dest_compute, use_slave=False):
        db_migrations = db.migration_get_unconfirmed_by_dest_compute(
            context, confirm_window, dest_compute, use_slave=use_slave)
        return base.obj_make_list(context, cls(context), objects.Migration,
                                  db_migrations)

    @base.remotable_classmethod
    def get_in_progress_by_host_and_node(cls, context, host, node):
        db_migrations = db.migration_get_in_progress_by_host_and_node(
            context, host, node)
        return base.obj_make_list(context, cls(context), objects.Migration,
                                  db_migrations)

    @base.remotable_classmethod
    def get_by_filters(cls, context, filters):
        db_migrations = db.migration_get_all_by_filters(context, filters)
        return base.obj_make_list(context, cls(context), objects.Migration,
                                  db_migrations)
