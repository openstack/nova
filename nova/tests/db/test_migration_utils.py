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

from oslo.db.sqlalchemy import utils as oslodbutils
import sqlalchemy
from sqlalchemy import Integer, String
from sqlalchemy import MetaData, Table, Column
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy import sql
from sqlalchemy.types import UserDefinedType

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import utils
from nova import exception
from nova.tests.db import test_migrations


SA_VERSION = tuple(map(int, sqlalchemy.__version__.split('.')))


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
            query_delete = sql.select([column],
                                  test_table.c.id < 5).order_by(column)
            delete_statement = utils.DeleteFromSelect(test_table,
                                                      query_delete, column)
            result_delete = conn.execute(delete_statement)
            # Verify we delete 4 rows
            self.assertEqual(result_delete.rowcount, 4)

            query_all = sql.select([test_table]).\
                        where(test_table.c.uuid.in_(uuidstrs))
            rows = conn.execute(query_all).fetchall()
            # Verify we still have 6 rows in table
            self.assertEqual(len(rows), 6)

            test_table.drop()

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

            # check missing shadow table
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

    def test_check_shadow_table_with_unsupported_sqlite_type(self):
        if 'sqlite' not in self.engines:
            self.skipTest('sqlite is not configured')
        table_name = 'test_check_shadow_table_with_unsupported_sqlite_type'
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

            # reflection of custom types has been fixed upstream
            if SA_VERSION < (0, 9, 0):
                self.assertRaises(oslodbutils.ColumnError,
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
