# Copyright (c) 2013 Boris Pavlovic (boris@pavlovic.me).
# All Rights Reserved.
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

import uuid
import warnings

from migrate.changeset import UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy import Boolean, Index, Integer, DateTime, String
from sqlalchemy import MetaData, Table, Column, ForeignKey
from sqlalchemy.engine import reflection
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.exc import SAWarning
from sqlalchemy.sql import select
from sqlalchemy.types import UserDefinedType, NullType

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import utils
from nova import exception
from nova.tests.db import test_migrations


class CustomType(UserDefinedType):
    """Dummy column type for testing unsupported types."""
    def get_col_spec(self):
        return "CustomType"


class TestMigrationUtils(test_migrations.BaseMigrationTestCase):
    """Class for testing utils that are used in db migrations."""

    def test_delete_from_select(self):
        table_name = "__test_deletefromselect_table__"
        uuidstrs = []
        for unused in range(10):
            uuidstrs.append(uuid.uuid4().hex)
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            conn = engine.connect()
            test_table = Table(table_name, meta,
                               Column('id', Integer, primary_key=True,
                                      nullable=False, autoincrement=True),
                               Column('uuid', String(36), nullable=False))
            test_table.create()
            # Add 10 rows to table
            for uuidstr in uuidstrs:
                ins_stmt = test_table.insert().values(uuid=uuidstr)
                conn.execute(ins_stmt)

            # Delete 4 rows in one chunk
            column = test_table.c.id
            query_delete = select([column],
                                  test_table.c.id < 5).order_by(column)
            delete_statement = utils.DeleteFromSelect(test_table,
                                                      query_delete, column)
            result_delete = conn.execute(delete_statement)
            # Verify we delete 4 rows
            self.assertEqual(result_delete.rowcount, 4)

            query_all = select([test_table]).\
                        where(test_table.c.uuid.in_(uuidstrs))
            rows = conn.execute(query_all).fetchall()
            # Verify we still have 6 rows in table
            self.assertEqual(len(rows), 6)

            test_table.drop()

    def test_insert_from_select(self):
        insert_table_name = "__test_insert_to_table__"
        select_table_name = "__test_select_from_table__"
        uuidstrs = []
        for unused in range(10):
            uuidstrs.append(uuid.uuid4().hex)
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            conn = engine.connect()
            insert_table = Table(insert_table_name, meta,
                               Column('id', Integer, primary_key=True,
                                      nullable=False, autoincrement=True),
                               Column('uuid', String(36), nullable=False))
            select_table = Table(select_table_name, meta,
                               Column('id', Integer, primary_key=True,
                                      nullable=False, autoincrement=True),
                               Column('uuid', String(36), nullable=False))

            insert_table.create()
            select_table.create()
            # Add 10 rows to select_table
            for uuidstr in uuidstrs:
                ins_stmt = select_table.insert().values(uuid=uuidstr)
                conn.execute(ins_stmt)

            # Select 4 rows in one chunk from select_table
            column = select_table.c.id
            query_insert = select([select_table],
                                  select_table.c.id < 5).order_by(column)
            insert_statement = utils.InsertFromSelect(insert_table,
                                                      query_insert)
            result_insert = conn.execute(insert_statement)
            # Verify we insert 4 rows
            self.assertEqual(result_insert.rowcount, 4)

            query_all = select([insert_table]).\
                        where(insert_table.c.uuid.in_(uuidstrs))
            rows = conn.execute(query_all).fetchall()
            # Verify we really have 4 rows in insert_table
            self.assertEqual(len(rows), 4)

            insert_table.drop()
            select_table.drop()

    def test_utils_drop_unique_constraint(self):
        table_name = "test_utils_drop_unique_constraint"
        uc_name = 'uniq_foo'
        values = [
            {'id': 1, 'a': 3, 'foo': 10},
            {'id': 2, 'a': 2, 'foo': 20},
            {'id': 3, 'a': 1, 'foo': 30}
        ]
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            test_table = Table(table_name, meta,
                               Column('id', Integer, primary_key=True,
                                      nullable=False),
                               Column('a', Integer),
                               Column('foo', Integer),
                               UniqueConstraint('a', name='uniq_a'),
                               UniqueConstraint('foo', name=uc_name))
            test_table.create()

            engine.execute(test_table.insert(), values)
            # NOTE(boris-42): This method is generic UC dropper.
            utils.drop_unique_constraint(engine, table_name, uc_name, 'foo')

            s = test_table.select().order_by(test_table.c.id)
            rows = engine.execute(s).fetchall()

            for i in xrange(0, len(values)):
                v = values[i]
                self.assertEqual((v['id'], v['a'], v['foo']), rows[i])

            # NOTE(boris-42): Update data about Table from DB.
            meta = MetaData()
            meta.bind = engine
            test_table = Table(table_name, meta, autoload=True)
            constraints = filter(lambda c: c.name == uc_name,
                                 test_table.constraints)
            self.assertEqual(len(constraints), 0)
            self.assertEqual(len(test_table.constraints), 1)

            test_table.drop()

    def test_util_drop_unique_constraint_with_not_supported_sqlite_type(self):
        if 'sqlite' in self.engines:
            engine = self.engines['sqlite']
            meta = MetaData(bind=engine)

            table_name = ("test_util_drop_unique_constraint_with_not_supported"
                          "_sqlite_type")
            uc_name = 'uniq_foo'
            values = [
                {'id': 1, 'a': 3, 'foo': 10},
                {'id': 2, 'a': 2, 'foo': 20},
                {'id': 3, 'a': 1, 'foo': 30}
            ]

            test_table = Table(table_name, meta,
                                Column('id', Integer, primary_key=True,
                                      nullable=False),
                               Column('a', Integer),
                               Column('foo', CustomType, default=0),
                               UniqueConstraint('a', name='uniq_a'),
                               UniqueConstraint('foo', name=uc_name))
            test_table.create()

            engine.execute(test_table.insert(), values)
            warnings.simplefilter("ignore", SAWarning)
            # NOTE(boris-42): Missing info about column `foo` that has
            #                 unsupported type CustomType.
            self.assertRaises(exception.NovaException,
                              utils.drop_unique_constraint,
                              engine, table_name, uc_name, 'foo')

            # NOTE(boris-42): Wrong type of foo instance. it should be
            #                 instance of sqlalchemy.Column.
            self.assertRaises(exception.NovaException,
                              utils.drop_unique_constraint,
                              engine, table_name, uc_name, 'foo',
                              foo=Integer())

            foo = Column('foo', CustomType, default=0)
            utils.drop_unique_constraint(engine, table_name, uc_name, 'foo',
                                         foo=foo)

            s = test_table.select().order_by(test_table.c.id)
            rows = engine.execute(s).fetchall()

        for i in xrange(0, len(values)):
            v = values[i]
            self.assertEqual((v['id'], v['a'], v['foo']), rows[i])

        # NOTE(boris-42): Update data about Table from DB.
        meta = MetaData(bind=engine)
        test_table = Table(table_name, meta, autoload=True)
        constraints = filter(lambda c: c.name == uc_name,
                             test_table.constraints)
        self.assertEqual(len(constraints), 0)
        self.assertEqual(len(test_table.constraints), 1)
        test_table.drop()

    def _populate_db_for_drop_duplicate_entries(self, engine, meta,
                                                table_name):
        values = [
            {'id': 11, 'a': 3, 'b': 10, 'c': 'abcdef'},
            {'id': 12, 'a': 5, 'b': 10, 'c': 'abcdef'},
            {'id': 13, 'a': 6, 'b': 10, 'c': 'abcdef'},
            {'id': 14, 'a': 7, 'b': 10, 'c': 'abcdef'},
            {'id': 21, 'a': 1, 'b': 20, 'c': 'aa'},
            {'id': 31, 'a': 1, 'b': 20, 'c': 'bb'},
            {'id': 41, 'a': 1, 'b': 30, 'c': 'aef'},
            {'id': 42, 'a': 2, 'b': 30, 'c': 'aef'},
            {'id': 43, 'a': 3, 'b': 30, 'c': 'aef'}
        ]

        test_table = Table(table_name, meta,
                           Column('id', Integer, primary_key=True,
                                  nullable=False),
                           Column('a', Integer),
                           Column('b', Integer),
                           Column('c', String(255)),
                           Column('deleted', Integer, default=0),
                           Column('deleted_at', DateTime),
                           Column('updated_at', DateTime))

        test_table.create()
        engine.execute(test_table.insert(), values)
        return test_table, values

    def test_drop_old_duplicate_entries_from_table(self):
        table_name = "test_drop_old_duplicate_entries_from_table"

        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            test_table, values = self.\
                    _populate_db_for_drop_duplicate_entries(engine, meta,
                                                            table_name)

            utils.drop_old_duplicate_entries_from_table(engine, table_name,
                                                        False, 'b', 'c')

            uniq_values = set()
            expected_ids = []
            for value in sorted(values, key=lambda x: x['id'], reverse=True):
                uniq_value = (('b', value['b']), ('c', value['c']))
                if uniq_value in uniq_values:
                    continue
                uniq_values.add(uniq_value)
                expected_ids.append(value['id'])

            real_ids = [row[0] for row in
                        engine.execute(select([test_table.c.id])).fetchall()]

            self.assertEqual(len(real_ids), len(expected_ids))
            for id_ in expected_ids:
                self.assertIn(id_, real_ids)
            test_table.drop()

    def test_drop_old_duplicate_entries_from_table_soft_delete(self):
        table_name = "test_drop_old_duplicate_entries_from_table_soft_delete"

        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            table, values = self.\
                    _populate_db_for_drop_duplicate_entries(engine, meta,
                                                            table_name)
            utils.drop_old_duplicate_entries_from_table(engine, table_name,
                                                        True, 'b', 'c')
            uniq_values = set()
            expected_values = []
            soft_deleted_values = []

            for value in sorted(values, key=lambda x: x['id'], reverse=True):
                uniq_value = (('b', value['b']), ('c', value['c']))
                if uniq_value in uniq_values:
                    soft_deleted_values.append(value)
                    continue
                uniq_values.add(uniq_value)
                expected_values.append(value)

            base_select = table.select()

            rows_select = base_select.\
                                where(table.c.deleted != table.c.id)
            row_ids = [row['id'] for row in
                            engine.execute(rows_select).fetchall()]
            self.assertEqual(len(row_ids), len(expected_values))
            for value in expected_values:
                self.assertIn(value['id'], row_ids)

            deleted_rows_select = base_select.\
                                    where(table.c.deleted == table.c.id)
            deleted_rows_ids = [row['id'] for row in
                                engine.execute(deleted_rows_select).fetchall()]
            self.assertEqual(len(deleted_rows_ids),
                             len(values) - len(row_ids))
            for value in soft_deleted_values:
                self.assertIn(value['id'], deleted_rows_ids)
            table.drop()

    def test_check_shadow_table(self):
        table_name = 'test_check_shadow_table'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine

            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', Integer),
                          Column('c', String(256)))
            table.create()

            #check missing shadow table
            self.assertRaises(NoSuchTableError,
                              utils.check_shadow_table, engine, table_name)

            shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, meta,
                                 Column('id', Integer),
                                 Column('a', Integer))
            shadow_table.create()

            # check missing column
            self.assertRaises(exception.NovaException,
                              utils.check_shadow_table, engine, table_name)

            # check when all is ok
            c = Column('c', String(256))
            shadow_table.create_column(c)
            self.assertTrue(utils.check_shadow_table(engine, table_name))

            # check extra column
            d = Column('d', Integer)
            shadow_table.create_column(d)
            self.assertRaises(exception.NovaException,
                              utils.check_shadow_table, engine, table_name)

            table.drop()
            shadow_table.drop()

    def test_check_shadow_table_different_types(self):
        table_name = 'test_check_shadow_table_different_types'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine

            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', Integer))
            table.create()

            shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, meta,
                                 Column('id', Integer, primary_key=True),
                                 Column('a', String(256)))
            shadow_table.create()
            self.assertRaises(exception.NovaException,
                              utils.check_shadow_table, engine, table_name)

            table.drop()
            shadow_table.drop()

    def test_check_shadow_table_with_unsupported_type(self):
        table_name = 'test_check_shadow_table_with_unsupported_type'
        engine = self.engines['sqlite']
        meta = MetaData(bind=engine)

        table = Table(table_name, meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer),
                      Column('c', CustomType))
        table.create()

        shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, meta,
                             Column('id', Integer, primary_key=True),
                             Column('a', Integer),
                             Column('c', CustomType))
        shadow_table.create()
        self.assertTrue(utils.check_shadow_table(engine, table_name))
        shadow_table.drop()

    def test_create_shadow_table_by_table_instance(self):
        table_name = 'test_create_shadow_table_by_table_instance'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', Integer),
                          Column('b', String(256)))
            table.create()
            shadow_table = utils.create_shadow_table(engine, table=table)
            self.assertTrue(utils.check_shadow_table(engine, table_name))
            table.drop()
            shadow_table.drop()

    def test_create_shadow_table_by_name(self):
        table_name = 'test_create_shadow_table_by_name'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine

            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', Integer),
                          Column('b', String(256)))
            table.create()
            shadow_table = utils.create_shadow_table(engine,
                                                     table_name=table_name)
            self.assertTrue(utils.check_shadow_table(engine, table_name))
            table.drop()
            shadow_table.drop()

    def test_create_shadow_table_not_supported_type(self):
        if 'sqlite' in self.engines:
            table_name = 'test_create_shadow_table_not_supported_type'
            engine = self.engines['sqlite']
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', CustomType))
            table.create()
            self.assertRaises(exception.NovaException,
                              utils.create_shadow_table,
                              engine, table_name=table_name)

            shadow_table = utils.create_shadow_table(engine,
                table_name=table_name,
                a=Column('a', CustomType())
            )
            self.assertTrue(utils.check_shadow_table(engine, table_name))
            table.drop()
            shadow_table.drop()

    def test_create_shadow_both_table_and_table_name_are_none(self):
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            self.assertRaises(exception.NovaException,
                              utils.create_shadow_table, engine)

    def test_create_shadow_both_table_and_table_name_are_specified(self):
        table_name = ('test_create_shadow_both_table_and_table_name_are_'
                      'specified')
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', Integer))
            table.create()
            self.assertRaises(exception.NovaException,
                              utils.create_shadow_table,
                              engine, table=table, table_name=table_name)
            table.drop()

    def test_create_duplicate_shadow_table(self):
        table_name = 'test_create_duplicate_shadow_table'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', Integer))
            table.create()
            shadow_table = utils.create_shadow_table(engine,
                                                     table_name=table_name)
            self.assertRaises(exception.ShadowTableExists,
                              utils.create_shadow_table,
                              engine, table_name=table_name)
            table.drop()
            shadow_table.drop()

    def test_change_deleted_column_type_doesnt_drop_index(self):
        table_name = 'test_change_deleted_column_type_doesnt_drop_index'
        for key, engine in self.engines.items():
            meta = MetaData(bind=engine)

            indexes = {
                'idx_a_deleted': ['a', 'deleted'],
                'idx_b_deleted': ['b', 'deleted'],
                'idx_a': ['a']
            }

            index_instances = [Index(name, *columns)
                                    for name, columns in indexes.iteritems()]

            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('a', String(255)),
                          Column('b', String(255)),
                          Column('deleted', Boolean),
                          *index_instances)
            table.create()
            utils.change_deleted_column_type_to_id_type(engine, table_name)
            utils.change_deleted_column_type_to_boolean(engine, table_name)

            insp = reflection.Inspector.from_engine(engine)
            real_indexes = insp.get_indexes(table_name)
            self.assertEqual(len(real_indexes), 3)
            for index in real_indexes:
                name = index['name']
                self.assertIn(name, indexes)
                self.assertEqual(set(index['column_names']),
                                 set(indexes[name]))
            table.drop()

    def test_change_deleted_column_type_to_id_type_integer(self):
        table_name = 'test_change_deleted_column_type_to_id_type_integer'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('deleted', Boolean))
            table.create()
            utils.change_deleted_column_type_to_id_type(engine, table_name)

            table = utils.get_table(engine, table_name)
            self.assertIsInstance(table.c.deleted.type, Integer)
            table.drop()

    def test_change_deleted_column_type_to_id_type_string(self):
        table_name = 'test_change_deleted_column_type_to_id_type_string'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', String(255), primary_key=True),
                          Column('deleted', Boolean))
            table.create()
            utils.change_deleted_column_type_to_id_type(engine, table_name)

            table = utils.get_table(engine, table_name)
            self.assertIsInstance(table.c.deleted.type, String)
            table.drop()

    def test_change_deleted_column_type_to_id_type_custom(self):
        if 'sqlite' in self.engines:
            table_name = 'test_change_deleted_column_type_to_id_type_custom'
            engine = self.engines['sqlite']
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('foo', CustomType),
                          Column('deleted', Boolean))
            table.create()

            self.assertRaises(exception.NovaException,
                              utils.change_deleted_column_type_to_id_type,
                              engine, table_name)

            fooColumn = Column('foo', CustomType())
            utils.change_deleted_column_type_to_id_type(engine, table_name,
                                                        foo=fooColumn)

            table = utils.get_table(engine, table_name)
            # NOTE(boris-42): There is no way to check has foo type CustomType.
            #                 but sqlalchemy will set it to NullType.
            self.assertIsInstance(table.c.foo.type, NullType)
            self.assertIsInstance(table.c.deleted.type, Integer)
            table.drop()

    def test_change_deleted_column_type_to_boolean(self):
        table_name = 'test_change_deleted_column_type_to_boolean'
        for key, engine in self.engines.items():
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('deleted', Integer))
            table.create()

            utils.change_deleted_column_type_to_boolean(engine, table_name)

            table = utils.get_table(engine, table_name)
            expected_type = Boolean if key != "mysql" else mysql.TINYINT
            self.assertIsInstance(table.c.deleted.type, expected_type)
            table.drop()

    def test_change_deleted_column_type_to_boolean_type_custom(self):
        if 'sqlite' in self.engines:
            table_name = \
                'test_change_deleted_column_type_to_boolean_type_custom'
            engine = self.engines['sqlite']
            meta = MetaData()
            meta.bind = engine
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('foo', CustomType),
                          Column('deleted', Integer))
            table.create()

            self.assertRaises(exception.NovaException,
                              utils.change_deleted_column_type_to_boolean,
                              engine, table_name)

            fooColumn = Column('foo', CustomType())
            utils.change_deleted_column_type_to_boolean(engine, table_name,
                                                        foo=fooColumn)

            table = utils.get_table(engine, table_name)
            # NOTE(boris-42): There is no way to check has foo type CustomType.
            #                 but sqlalchemy will set it to NullType.
            self.assertIsInstance(table.c.foo.type, NullType)
            self.assertIsInstance(table.c.deleted.type, Boolean)
            table.drop()

    def test_drop_unique_constraint_in_sqlite_fk_recreate(self):
        if 'sqlite' in self.engines:
            engine = self.engines['sqlite']
            meta = MetaData()
            meta.bind = engine
            parent_table_name = ('test_drop_unique_constraint_in_sqlite_fk_'
                                 'recreate_parent_table')
            parent_table = Table(parent_table_name, meta,
                           Column('id', Integer, primary_key=True),
                           Column('foo', Integer))
            parent_table.create()
            table_name = 'test_drop_unique_constraint_in_sqlite_fk_recreate'
            table = Table(table_name, meta,
                          Column('id', Integer, primary_key=True),
                          Column('baz', Integer),
                          Column('bar', Integer,
                                 ForeignKey(parent_table_name + ".id")),
                          UniqueConstraint('baz', name='constr1'))
            table.create()
            utils.drop_unique_constraint(engine, table_name, 'constr1', 'baz')

            insp = reflection.Inspector.from_engine(engine)
            f_keys = insp.get_foreign_keys(table_name)
            self.assertEqual(len(f_keys), 1)
            f_key = f_keys[0]
            self.assertEqual(f_key['referred_table'], parent_table_name)
            self.assertEqual(f_key['referred_columns'], ['id'])
            self.assertEqual(f_key['constrained_columns'], ['bar'])
            table.drop()
            parent_table.drop()
