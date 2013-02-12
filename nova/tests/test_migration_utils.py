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
from sqlalchemy import MetaData, Table, Column, Integer, BigInteger

from nova.db.sqlalchemy import utils
from nova import exception
from nova.tests import test_migrations


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
                               Column('foo', BigInteger, default=0),
                               UniqueConstraint('a', name='uniq_a'),
                               UniqueConstraint('foo', name=uc_name))
            test_table.create()

            engine.execute(test_table.insert(), values)
            if key == "sqlite":
                # NOTE(boris-42): Missing info about column `foo` that has
                #                 unsupported type BigInteger.
                self.assertRaises(exception.NovaException,
                                  utils.drop_unique_constraint,
                                  engine, table_name, uc_name, 'foo')

                # NOTE(boris-42): Wrong type of foo instance. it should be
                #                 instance of sqlalchemy.Column.
                self.assertRaises(exception.NovaException,
                                  utils.drop_unique_constraint,
                                  engine, table_name, uc_name, 'foo',
                                  foo=Integer())

            foo = Column('foo', BigInteger, default=0)
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
