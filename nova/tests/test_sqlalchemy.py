# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (c) 2012 Rackspace Hosting
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

"""Unit tests for SQLAlchemy specific code."""

from eventlet import db_pool
try:
    import MySQLdb
except ImportError:
    MySQLdb = None

from sqlalchemy import Column, MetaData, Table, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import DateTime, Integer

from nova import context
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy import session
from nova import exception
from nova import test


class DbPoolTestCase(test.TestCase):
    def setUp(self):
        super(DbPoolTestCase, self).setUp()
        self.flags(sql_dbpool_enable=True)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        if not MySQLdb:
            self.skipTest("Unable to test due to lack of MySQLdb")

    def test_db_pool_option(self):
        self.flags(sql_idle_timeout=11, sql_min_pool_size=21,
                sql_max_pool_size=42)

        info = {}

        class FakeConnectionPool(db_pool.ConnectionPool):
            def __init__(self, mod_name, **kwargs):
                info['module'] = mod_name
                info['kwargs'] = kwargs
                super(FakeConnectionPool, self).__init__(mod_name,
                        **kwargs)

            def connect(self, *args, **kwargs):
                raise test.TestingException()

        self.stubs.Set(db_pool, 'ConnectionPool',
                FakeConnectionPool)

        sql_connection = 'mysql://user:pass@127.0.0.1/nova'
        self.assertRaises(test.TestingException, session.create_engine,
                sql_connection)

        self.assertEqual(info['module'], MySQLdb)
        self.assertEqual(info['kwargs']['max_idle'], 11)
        self.assertEqual(info['kwargs']['min_size'], 21)
        self.assertEqual(info['kwargs']['max_size'], 42)


BASE = declarative_base()
_TABLE_NAME = '__tmp__test__tmp__'


class TmpTable(BASE, models.NovaBase):
    __tablename__ = _TABLE_NAME
    id = Column(Integer, primary_key=True)
    foo = Column(Integer)


class SessionErrorWrapperTestCase(test.TestCase):
    def setUp(self):
        super(SessionErrorWrapperTestCase, self).setUp()
        meta = MetaData()
        meta.bind = session.get_engine()
        test_table = Table(_TABLE_NAME, meta,
                           Column('id', Integer, primary_key=True,
                                  nullable=False),
                           Column('deleted', Integer, default=0),
                           Column('deleted_at', DateTime),
                           Column('updated_at', DateTime),
                           Column('created_at', DateTime),
                           Column('foo', Integer),
                           UniqueConstraint('foo', name='uniq_foo'))
        test_table.create()

    def tearDown(self):
        super(SessionErrorWrapperTestCase, self).tearDown()
        meta = MetaData()
        meta.bind = session.get_engine()
        test_table = Table(_TABLE_NAME, meta, autoload=True)
        test_table.drop()

    def test_flush_wrapper(self):
        tbl = TmpTable()
        tbl.update({'foo': 10})
        tbl.save()

        tbl2 = TmpTable()
        tbl2.update({'foo': 10})
        self.assertRaises(exception.DBDuplicateEntry, tbl2.save)

    def test_execute_wrapper(self):
        _session = session.get_session()
        with _session.begin():
            for i in [10, 20]:
                tbl = TmpTable()
                tbl.update({'foo': i})
                tbl.save(session=_session)

            method = _session.query(TmpTable).\
                            filter_by(foo=10).\
                            update
            self.assertRaises(exception.DBDuplicateEntry,
                              method, {'foo': 20})
