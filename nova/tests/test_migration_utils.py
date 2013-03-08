# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from migrate.changeset import UniqueConstraint
from sqlalchemy import Integer, DateTime, String
from sqlalchemy import MetaData, Table, Column
from sqlalchemy.exc import SAWarning
from sqlalchemy.sql import select
from sqlalchemy.types import UserDefinedType

from nova.db.sqlalchemy import utils
from nova import exception
from nova.tests import test_migrations
import warnings


class TestMigrationUtils(test_migrations.BaseMigrationTestCase):
    """Class for testing utils that are used in db migrations."""

    def test_utils_drop_unique_constraint(self):
        table_name = "__test_tmp_table__"
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

        class CustomType(UserDefinedType):
            """Dummy column type for testing unsupported types."""
            def get_col_spec(self):
                return "CustomType"

        table_name = "__test_tmp_table__"
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
                               Column('foo', CustomType, default=0),
                               UniqueConstraint('a', name='uniq_a'),
                               UniqueConstraint('foo', name=uc_name))
            test_table.create()

            engine.execute(test_table.insert(), values)
            if key == "sqlite":
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
            meta = MetaData()
            meta.bind = engine
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
                           Column('c', String),
                           Column('deleted', Integer, default=0),
                           Column('deleted_at', DateTime),
                           Column('updated_at', DateTime))

        test_table.create()
        engine.execute(test_table.insert(), values)
        return test_table, values

    def test_drop_old_duplicate_entries_from_table(self):
        table_name = "__test_tmp_table__"

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
                self.assertTrue(id_ in real_ids)

    def test_drop_old_duplicate_entries_from_table_soft_delete(self):
        table_name = "__test_tmp_table__"

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
                self.assertTrue(value['id'] in row_ids)

            deleted_rows_select = base_select.\
                                    where(table.c.deleted == table.c.id)
            deleted_rows_ids = [row['id'] for row in
                                engine.execute(deleted_rows_select).fetchall()]
            self.assertEqual(len(deleted_rows_ids),
                             len(values) - len(row_ids))
            for value in soft_deleted_values:
                self.assertTrue(value['id'] in deleted_rows_ids)
