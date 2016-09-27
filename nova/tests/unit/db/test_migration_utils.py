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

from oslo_db.sqlalchemy.compat import utils as compat_utils
from oslo_db.sqlalchemy import test_base
from oslo_db.sqlalchemy import utils as oslodbutils
from sqlalchemy import Integer, String
from sqlalchemy import MetaData, Table, Column
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy import sql
from sqlalchemy.types import UserDefinedType

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import utils
from nova import exception
from nova.tests import fixtures as nova_fixtures

SA_VERSION = compat_utils.SQLA_VERSION


class CustomType(UserDefinedType):
    """Dummy column type for testing unsupported types."""
    def get_col_spec(self):
        return "CustomType"

# TODO(sdague): no tests in the nova/tests tree should inherit from
# base test classes in another library. This causes all kinds of havoc
# in these doing things incorrectly for what we need in subunit
# reporting. This is a long unwind, but should be done in the future
# and any code needed out of oslo_db should be exported / accessed as
# a fixture.


class TestMigrationUtilsSQLite(test_base.DbTestCase):
    """Class for testing utils that are used in db migrations."""

    def setUp(self):
        # NOTE(sdague): the oslo_db base test case completely
        # invalidates our logging setup, we actually have to do that
        # before it is called to keep this from vomitting all over our
        # test output.
        self.useFixture(nova_fixtures.StandardLogging())
        super(TestMigrationUtilsSQLite, self).setUp()
        self.meta = MetaData(bind=self.engine)

    def test_delete_from_select(self):
        table_name = "__test_deletefromselect_table__"
        uuidstrs = []
        for unused in range(10):
            uuidstrs.append(uuid.uuid4().hex)

        conn = self.engine.connect()
        test_table = Table(table_name, self.meta,
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
        delete_statement = db.DeleteFromSelect(test_table,
                                               query_delete, column)
        result_delete = conn.execute(delete_statement)
        # Verify we delete 4 rows
        self.assertEqual(result_delete.rowcount, 4)

        query_all = sql.select([test_table])\
                       .where(test_table.c.uuid.in_(uuidstrs))
        rows = conn.execute(query_all).fetchall()
        # Verify we still have 6 rows in table
        self.assertEqual(len(rows), 6)

    def test_check_shadow_table(self):
        table_name = 'test_check_shadow_table'

        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer),
                      Column('c', String(256)))
        table.create()

        # check missing shadow table
        self.assertRaises(NoSuchTableError,
                          utils.check_shadow_table, self.engine, table_name)

        shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, self.meta,
                             Column('id', Integer),
                             Column('a', Integer))
        shadow_table.create()

        # check missing column
        self.assertRaises(exception.NovaException,
                          utils.check_shadow_table, self.engine, table_name)

        # check when all is ok
        c = Column('c', String(256))
        shadow_table.create_column(c)
        self.assertTrue(utils.check_shadow_table(self.engine, table_name))

        # check extra column
        d = Column('d', Integer)
        shadow_table.create_column(d)
        self.assertRaises(exception.NovaException,
                          utils.check_shadow_table, self.engine, table_name)

    def test_check_shadow_table_different_types(self):
        table_name = 'test_check_shadow_table_different_types'

        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer))
        table.create()

        shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, self.meta,
                             Column('id', Integer, primary_key=True),
                             Column('a', String(256)))
        shadow_table.create()
        self.assertRaises(exception.NovaException,
                          utils.check_shadow_table, self.engine, table_name)

    @test_base.backend_specific('sqlite')
    def test_check_shadow_table_with_unsupported_sqlite_type(self):
        table_name = 'test_check_shadow_table_with_unsupported_sqlite_type'

        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer),
                      Column('c', CustomType))
        table.create()

        shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, self.meta,
                             Column('id', Integer, primary_key=True),
                             Column('a', Integer),
                             Column('c', CustomType))
        shadow_table.create()
        self.assertTrue(utils.check_shadow_table(self.engine, table_name))

    def test_create_shadow_table_by_table_instance(self):
        table_name = 'test_create_shadow_table_by_table_instance'
        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer),
                      Column('b', String(256)))
        table.create()
        utils.create_shadow_table(self.engine, table=table)
        self.assertTrue(utils.check_shadow_table(self.engine, table_name))

    def test_create_shadow_table_by_name(self):
        table_name = 'test_create_shadow_table_by_name'

        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer),
                      Column('b', String(256)))
        table.create()
        utils.create_shadow_table(self.engine, table_name=table_name)
        self.assertTrue(utils.check_shadow_table(self.engine, table_name))

    @test_base.backend_specific('sqlite')
    def test_create_shadow_table_not_supported_type(self):
        table_name = 'test_create_shadow_table_not_supported_type'
        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', CustomType))
        table.create()

        # reflection of custom types has been fixed upstream
        if SA_VERSION < (0, 9, 0):
            self.assertRaises(oslodbutils.ColumnError,
                              utils.create_shadow_table,
                              self.engine, table_name=table_name)

        utils.create_shadow_table(self.engine,
                                  table_name=table_name,
                                  a=Column('a', CustomType()))
        self.assertTrue(utils.check_shadow_table(self.engine, table_name))

    def test_create_shadow_both_table_and_table_name_are_none(self):
        self.assertRaises(exception.NovaException,
                          utils.create_shadow_table, self.engine)

    def test_create_shadow_both_table_and_table_name_are_specified(self):
        table_name = ('test_create_shadow_both_table_and_table_name_are_'
                      'specified')
        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer))
        table.create()
        self.assertRaises(exception.NovaException,
                          utils.create_shadow_table,
                          self.engine, table=table, table_name=table_name)

    def test_create_duplicate_shadow_table(self):
        table_name = 'test_create_duplicate_shadow_table'
        table = Table(table_name, self.meta,
                      Column('id', Integer, primary_key=True),
                      Column('a', Integer))
        table.create()
        utils.create_shadow_table(self.engine, table_name=table_name)
        self.assertRaises(exception.ShadowTableExists,
                          utils.create_shadow_table,
                          self.engine, table_name=table_name)


class TestMigrationUtilsPostgreSQL(TestMigrationUtilsSQLite,
                                   test_base.PostgreSQLOpportunisticTestCase):
    pass


class TestMigrationUtilsMySQL(TestMigrationUtilsSQLite,
                              test_base.MySQLOpportunisticTestCase):
    pass
