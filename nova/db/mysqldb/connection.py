# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Rackspace Hosting
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

"""MySQdb connection handling."""

import sys
import time

import MySQLdb
from MySQLdb.constants import CLIENT as mysql_client_constants

from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils

MySQLdb.threadsafety = 1
CONF = cfg.CONF

mysqldb_opts = [
    cfg.StrOpt('database',
               default='nova',
               help='the mysql database to use'),
    cfg.StrOpt('username',
               default='nova',
               help='the mysql username'),
    cfg.StrOpt('password',
               default='',
               help='the mysql password'),
    cfg.StrOpt('hostname',
               default='127.0.0.1',
               help='the hostname or IP of the mysql server'),
    cfg.IntOpt('port',
               default=3306,
               help='the TCP port of the mysql server'),
    cfg.IntOpt('max_connections',
               default=20,
               help='maximum number of concurrent mysql connections'),
]

CONF.register_opts(mysqldb_opts, group='mysqldb')
LOG = logging.getLogger(__name__)


class RetryableException(BaseException):
    def __init__(self, *args, **kwargs):
        super(RetryableException, self).__init__(*args, **kwargs)


def _create_connection():
    conn_args = {
        'db': CONF.mysqldb.database,
        'host': CONF.mysqldb.hostname,
        'port': CONF.mysqldb.port,
        'user': CONF.mysqldb.username,
        'passwd': CONF.mysqldb.password,
        'client_flag': mysql_client_constants.FOUND_ROWS}
    return MySQLdb.connect(**conn_args)


class _Connection(object):
    def __init__(self, pool):
        self._conn = None
        self._ensure_connection()
        self.pool = pool

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        if self._conn:
            if exc:
                self._conn.rollback()
            else:
                self._conn.commit()
        self.pool.put(self)

    def cursor(self):
        return self._conn.cursor()

    def _get_columns(self, name):
        cursor = self.execute('DESCRIBE %s' % name)
        rows = cursor.fetchall()
        return [r[0] for r in rows]

    def _get_tables(self):
        cursor = self.execute('SHOW TABLES')
        rows = cursor.fetchall()
        tables = {}
        for row in rows:
            table_name = row[0]
            columns = self._get_columns(table_name)
            tables[table_name] = dict(columns=columns)
        return tables

    def _get_migrate_version(self):
        cursor = self.execute('SELECT version from migrate_version WHERE '
                              'repository_id = %s',
                              (CONF.mysqldb.database, ))
        rows = cursor.fetchall()
        if not rows:
            # FIXME(comstud)
            raise SystemError
        return rows[0][0]

    def get_schema(self):
        with self._conn:
            tables = self._get_tables()
            version = self._get_migrate_version()
            return {'version': version,
                    'tables': tables}

    def _init_connection(self):
        pass

    def _ensure_connection(self):
        if self._conn:
            return self._conn
        conn_args = {
            'db': CONF.mysqldb.database,
            'host': CONF.mysqldb.hostname,
            'port': CONF.mysqldb.port,
            'user': CONF.mysqldb.username,
            'passwd': CONF.mysqldb.password,
            'client_flag': mysql_client_constants.FOUND_ROWS}
        while True:
            try:
                info_str = _("Attempting connection to mysql server "
                             "'%(host)s:%(port)s'")
                LOG.info(info_str % conn_args)
                self._conn = _create_connection()
                self._init_connection()
            except IOError:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
                err_str = _("Error connecting to mysql server "
                            "'%(host)s:%(port)s'")
                LOG.exception(err_str % conn_args)
                # TODO(comstud): Make configurable and backoff.
                time.sleep(1)
                continue
            info_str = _("Connected to to mysql server '%(host)s:%(port)s'")
            LOG.info(info_str % conn_args)
            return self._conn

    def execute(self, query, args=None):
        conn = self._ensure_connection()
        try:
            cursor = self.cursor()
            cursor.execute(query, args)
            return cursor
        except IOError:
            exc = sys.exc_info()
            try:
                conn.close()
            except Exception:
                pass
            self._conn = None
            raise RetryableException(exc[1])

    def insert(self, table, value_map):
        columns = ''
        value_str = ''
        values = []
        for column, value in value_map.iteritems():
            if not columns:
                columns += column
                value_str += '%s'
            else:
                columns += ', ' + column
                value_str += ', %s'
            values.append(value)
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, columns, value_str)
        return self.execute(sql, args=values)

    def _where(self, where):
        where_str = ''
        args = []
        for column, operator, value in where:
            if where_str:
                where_str += ' AND '
            where_str += '`%s` %s ' % (column, operator)
            if isinstance(value, (list, tuple)):
                where_str += '(%s)' % ','.join(['%s' for x in value])
                args.extend(list(value))
            else:
                where_str += '%s'
                args.append(value)
        return where_str, args

    def select(self, sql, args):
        return self.execute(sql, args)

    def soft_delete(self, table, where):
        where_str, where_args = self._where(where)

        sql = ("UPDATE %s SET deleted=id, updated_at=updated_at, "
               "deleted_at='%s' WHERE %s" % (table, timeutils.utcnow(),
                     where_str))
        LOG.debug(sql)
        LOG.debug(where_args)
        cursor = self.execute(sql, args=where_args)
        return rowcount 

    def update(self, table, value_map, where):
        update_str = ''
        args = []

        for column, value in value_map.iteritems():
            if update_str:
                update_str += ', '
            update_str += column + '=%s'
            args.append(value)

        where_str, where_args = self._where(where)
        args.extend(where_args)
    
        sql = ("UPDATE %(table)s SET %(update_str)s WHERE %(where_str)s"
                % locals())
        LOG.debug(sql)
        LOG.debug(args)
        cursor = self.execute(sql, args=args)
        return cursor


class ConnectionPool(object):
    def __init__(self):
        self.conns_available = []
        self.max_conns = CONF.mysqldb.max_connections
        self.num_conns = 0

    def _create_conn(self):
        self.num_conns += 1
        return _Connection(self)

    def get(self):
        try:
            return self.conns_available.pop()
        except IndexError:
            pass
        if self.num_conns < self.max_conns:
            return self._create_conn()
        # FIXME(comstud): wait for one to become avail.
        assert False

    def put(self, conn):
        self.conns_available.append(conn)
