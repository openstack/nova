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

import time

import MySQLdb
from MySQLdb.constants import CLIENT as mysql_client_constants
from MySQLdb import cursors

from nova.openstack.common import cfg
from nova.openstack.common import log as logging

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
        self.ensure_connection()
        self.pool = pool

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        if exc:
            self._conn.rollback()
        else:
            self._conn.commit()
        self.pool.put(self)

    def cursor(self):
        return self._conn.cursor(cursorclass=cursors.DictCursor)

    def ensure_connection(self):
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
                return self._conn
            except IOError:
                err_str = _("Error connecting to mysql server "
                            "'%(host)s:%(port)s'")
                LOG.exception(err_str % conn_args)
            info_str = _("Connected to to mysql server '%(host)s:%(port)s'")
            LOG.info(info_str % conn_args)
            # TODO(comstud): Make configurable and backoff.
            time.sleep(1)

#    def __getattr__(self, key):
#        if key is '_conn':
#            return self._conn
#        print "GETTING %s" % key
#        attr = getattr(self._conn, key)
#        return attr
#        if not hasattr(method, '__call__'):
#            return attr
#        def _wrapper(*args, **kwargs):
#            return self.ensure(attr, *args, **kwargs)
#        _wrapper.__name__ = attr.__name__
#        return _wrapper

    def execute(self, query, args=None):
        while True:
            conn = self.ensure_connection()
            try:
                cursor = self.cursor()
                return cursor.execute(query, args)
            except IOError:
                try:
                    conn.close()
                except Exception:
                    pass
                self.conn = None

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

    def update(self, table, value_map, where):
        update_str = ''
        values = []
        where_str = ''

        for column, value in value_map.iteritems():
            if update_str:
                update_str += ', '
            update_str += column + '=%s'
            values.append(value)

        for column, operator, value in where:
            if where_str:
                where_str += ' AND'
            where_str += '%s%s' % (column, operator)
            where_str += '%s'
            values.append(value)
    
        sql = ("UPDATE %(table)s SET %(update_str)s WHERE %(where_str)s"
                % locals())
        self.execute(sql, args=values)


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
