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

import mock
from oslo_utils import timeutils

from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import migration
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel


NOW = timeutils.utcnow().replace(microsecond=0)


def fake_db_migration(**updates):
    db_instance = {
        'created_at': NOW,
        'updated_at': None,
        'deleted_at': None,
        'deleted': False,
        'id': 123,
        'source_compute': 'compute-source',
        'dest_compute': 'compute-dest',
        'source_node': 'node-source',
        'dest_node': 'node-dest',
        'dest_host': 'host-dest',
        'old_instance_type_id': 42,
        'new_instance_type_id': 84,
        'instance_uuid': 'fake-uuid',
        'status': 'migrating',
        'migration_type': 'resize',
        'hidden': False,
    }

    if updates:
        db_instance.update(updates)
    return db_instance


class _TestMigrationObject(object):
    def test_get_by_id(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        self.mox.StubOutWithMock(db, 'migration_get')
        db.migration_get(ctxt, fake_migration['id']).AndReturn(fake_migration)
        self.mox.ReplayAll()
        mig = migration.Migration.get_by_id(ctxt, fake_migration['id'])
        self.compare_obj(mig, fake_migration)

    def test_get_by_instance_and_status(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        self.mox.StubOutWithMock(db, 'migration_get_by_instance_and_status')
        db.migration_get_by_instance_and_status(ctxt,
                                                fake_migration['id'],
                                                'migrating'
                                                ).AndReturn(fake_migration)
        self.mox.ReplayAll()
        mig = migration.Migration.get_by_instance_and_status(
            ctxt, fake_migration['id'], 'migrating')
        self.compare_obj(mig, fake_migration)

    def test_create(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        self.mox.StubOutWithMock(db, 'migration_create')
        db.migration_create(ctxt, {'source_compute': 'foo',
                                   'migration_type': 'resize'}
                            ).AndReturn(fake_migration)
        self.mox.ReplayAll()
        mig = migration.Migration(context=ctxt)
        mig.source_compute = 'foo'
        mig.migration_type = 'resize'
        mig.create()
        self.assertEqual(fake_migration['dest_compute'], mig.dest_compute)

    def test_recreate_fails(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        self.mox.StubOutWithMock(db, 'migration_create')
        db.migration_create(ctxt, {'source_compute': 'foo',
                                   'migration_type': 'resize'}
                            ).AndReturn(fake_migration)
        self.mox.ReplayAll()
        mig = migration.Migration(context=ctxt)
        mig.source_compute = 'foo'
        mig.migration_type = 'resize'
        mig.create()
        self.assertRaises(exception.ObjectActionError, mig.create)

    def test_create_fails_migration_type(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'migration_create')
        self.mox.ReplayAll()
        mig = migration.Migration(context=ctxt,
                                  old_instance_type_id=42,
                                  new_instance_type_id=84)
        mig.source_compute = 'foo'
        self.assertRaises(exception.ObjectActionError, mig.create)

    def test_save(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        self.mox.StubOutWithMock(db, 'migration_update')
        db.migration_update(ctxt, 123, {'source_compute': 'foo'}
                            ).AndReturn(fake_migration)
        self.mox.ReplayAll()
        mig = migration.Migration(context=ctxt)
        mig.id = 123
        mig.source_compute = 'foo'
        mig.save()
        self.assertEqual(fake_migration['dest_compute'], mig.dest_compute)

    def test_instance(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        fake_inst = fake_instance.fake_db_instance()
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(ctxt, fake_migration['instance_uuid'],
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst)
        mig = migration.Migration._from_db_object(ctxt,
                                                  migration.Migration(),
                                                  fake_migration)
        mig._context = ctxt
        self.mox.ReplayAll()
        self.assertEqual(mig.instance.host, fake_inst['host'])

    def test_instance_setter(self):
        migration = objects.Migration(instance_uuid=uuidsentinel.instance)
        inst = objects.Instance(uuid=uuidsentinel.instance)
        with mock.patch('nova.objects.Instance.get_by_uuid') as mock_get:
            migration.instance = inst
            migration.instance
            self.assertFalse(mock_get.called)
        self.assertEqual(inst, migration._cached_instance)
        self.assertEqual(inst, migration.instance)

    def test_get_unconfirmed_by_dest_compute(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        db_migrations = [fake_migration, dict(fake_migration, id=456)]
        self.mox.StubOutWithMock(
            db, 'migration_get_unconfirmed_by_dest_compute')
        db.migration_get_unconfirmed_by_dest_compute(
            ctxt, 'window', 'foo').AndReturn(db_migrations)
        self.mox.ReplayAll()
        migrations = (
            migration.MigrationList.get_unconfirmed_by_dest_compute(
                ctxt, 'window', 'foo', use_slave=False))
        self.assertEqual(2, len(migrations))
        for index, db_migration in enumerate(db_migrations):
            self.compare_obj(migrations[index], db_migration)

    def test_get_in_progress_by_host_and_node(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        db_migrations = [fake_migration, dict(fake_migration, id=456)]
        self.mox.StubOutWithMock(
            db, 'migration_get_in_progress_by_host_and_node')
        db.migration_get_in_progress_by_host_and_node(
            ctxt, 'host', 'node').AndReturn(db_migrations)
        self.mox.ReplayAll()
        migrations = (
            migration.MigrationList.get_in_progress_by_host_and_node(
                ctxt, 'host', 'node'))
        self.assertEqual(2, len(migrations))
        for index, db_migration in enumerate(db_migrations):
            self.compare_obj(migrations[index], db_migration)

    def test_get_by_filters(self):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        db_migrations = [fake_migration, dict(fake_migration, id=456)]
        self.mox.StubOutWithMock(
            db, 'migration_get_all_by_filters')
        filters = {'foo': 'bar'}
        db.migration_get_all_by_filters(ctxt, filters).AndReturn(db_migrations)
        self.mox.ReplayAll()
        migrations = migration.MigrationList.get_by_filters(ctxt, filters)
        self.assertEqual(2, len(migrations))
        for index, db_migration in enumerate(db_migrations):
            self.compare_obj(migrations[index], db_migration)

    def test_migrate_old_resize_record(self):
        db_migration = dict(fake_db_migration(), migration_type=None)
        with mock.patch('nova.db.migration_get') as fake_get:
            fake_get.return_value = db_migration
            mig = objects.Migration.get_by_id(context.get_admin_context(), 1)
        self.assertTrue(mig.obj_attr_is_set('migration_type'))
        self.assertEqual('resize', mig.migration_type)

    def test_migrate_old_migration_record(self):
        db_migration = dict(
            fake_db_migration(), migration_type=None,
            old_instance_type_id=1, new_instance_type_id=1)
        with mock.patch('nova.db.migration_get') as fake_get:
            fake_get.return_value = db_migration
            mig = objects.Migration.get_by_id(context.get_admin_context(), 1)
        self.assertTrue(mig.obj_attr_is_set('migration_type'))
        self.assertEqual('migration', mig.migration_type)

    def test_migrate_unset_type_resize(self):
        mig = objects.Migration(old_instance_type_id=1,
                                new_instance_type_id=2)
        self.assertEqual('resize', mig.migration_type)
        self.assertTrue(mig.obj_attr_is_set('migration_type'))

    def test_migrate_unset_type_migration(self):
        mig = objects.Migration(old_instance_type_id=1,
                                new_instance_type_id=1)
        self.assertEqual('migration', mig.migration_type)
        self.assertTrue(mig.obj_attr_is_set('migration_type'))

    @mock.patch('nova.db.migration_get_by_id_and_instance')
    def test_get_by_id_and_instance(self, fake_get):
        ctxt = context.get_admin_context()
        fake_migration = fake_db_migration()
        fake_get.return_value = fake_migration
        migration = objects.Migration.get_by_id_and_instance(ctxt, '1', '1')
        self.compare_obj(migration, fake_migration)


class TestMigrationObject(test_objects._LocalTest,
                          _TestMigrationObject):
    pass


class TestRemoteMigrationObject(test_objects._RemoteTest,
                                _TestMigrationObject):
    pass
