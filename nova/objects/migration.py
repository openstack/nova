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

from oslo_utils import versionutils

from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


def determine_migration_type(migration):
    if migration['old_instance_type_id'] != migration['new_instance_type_id']:
        return 'resize'
    else:
        return 'migration'


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class Migration(base.NovaPersistentObject, base.NovaObject,
                base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Added migration_type and hidden
    VERSION = '1.2'

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
        'migration_type': fields.EnumField(['migration', 'resize',
                                            'live-migration', 'evacuation'],
                                           nullable=False),
        'hidden': fields.BooleanField(nullable=False, default=False),
        }

    @staticmethod
    def _from_db_object(context, migration, db_migration):
        for key in migration.fields:
            value = db_migration[key]
            if key == 'migration_type' and value is None:
                value = determine_migration_type(db_migration)
            migration[key] = value

        migration._context = context
        migration.obj_reset_changes()
        return migration

    def obj_make_compatible(self, primitive, target_version):
        super(Migration, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2):
            if 'migration_type' in primitive:
                del primitive['migration_type']
                del primitive['hidden']

    def obj_load_attr(self, attrname):
        if attrname == 'migration_type':
            # NOTE(danms): The only reason we'd need to load this is if
            # some older node sent us one. So, guess the type.
            self.migration_type = determine_migration_type(self)
        elif attrname == 'hidden':
            self.hidden = False
        else:
            super(Migration, self).obj_load_attr(attrname)

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
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        if 'migration_type' not in updates:
            raise exception.ObjectActionError(
                action="create",
                reason="cannot create a Migration object without a "
                       "migration_type set")
        db_migration = db.migration_create(self._context, updates)
        self._from_db_object(self._context, self, db_migration)

    @base.remotable
    def save(self):
        updates = self.obj_get_changes()
        updates.pop('id', None)
        db_migration = db.migration_update(self._context, self.id, updates)
        self._from_db_object(self._context, self, db_migration)
        self.obj_reset_changes()

    @property
    def instance(self):
        return objects.Instance.get_by_uuid(self._context, self.instance_uuid)


@base.NovaObjectRegistry.register
class MigrationList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              Migration <= 1.1
    # Version 1.1: Added use_slave to get_unconfirmed_by_dest_compute
    # Version 1.2: Migration version 1.2
    VERSION = '1.2'

    fields = {
        'objects': fields.ListOfObjectsField('Migration'),
        }

    @staticmethod
    @db.select_db_reader_mode
    def _db_migration_get_unconfirmed_by_dest_compute(
            context, confirm_window, dest_compute, use_slave=False):
        return db.migration_get_unconfirmed_by_dest_compute(
            context, confirm_window, dest_compute)

    @base.remotable_classmethod
    def get_unconfirmed_by_dest_compute(cls, context, confirm_window,
                                        dest_compute, use_slave=False):
        db_migrations = cls._db_migration_get_unconfirmed_by_dest_compute(
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
