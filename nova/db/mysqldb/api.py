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

"""
MySQLdb DB API implementation.

This will fall back to sqlalchemy for methods that are not yet implemented
here.
"""
import eventlet
from eventlet import tpool

from nova.db import utils as dbutils
from nova.db.mysqldb import connection
from nova.db.mysqldb import models
from nova.db.mysqldb import transform
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


mysqldb_opts = [
    cfg.BoolOpt('use_tpool',
               default=False,
               help='enable threadpooling of DB API calls.'),
]

CONF = cfg.CONF
CONF.register_opts(mysqldb_opts, group='mysqldb')
LOG = logging.getLogger(__name__)

_RetryExceptions = (connection.RetryableException, )


def _tpool_enabled(f):
    """Decorator to use that will wrap a call in tpool.execute if
    CONF.mysqldb.use_tpool is True
    """
    def wrapped(*args, **kwargs):
        if CONF.mysqldb.use_tpool:
            return tpool.execute(f, *args, **kwargs)
        else:
            return f(*args, **kwargs)
    wrapped.__name__ = f.__name__
    return wrapped


def _retry(f):
    def wrapped(*args, **kwargs):
        while True:
            try:
                return f(*args, **kwargs)
            except _RetryExceptions:
                LOG.exception("Retrying...")
                eventlet.sleep(2)
                continue
            except Exception:
                LOG.exception('foo')
                raise
    wrapped.__name__ = f.__name__
    return wrapped


def _datestr(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


class Constraint(object):
    def __init__(self, conditions):
        self.conditions = conditions

    def get_where(self):
        where = []
        for key, condition in self.conditions.iteritems():
            where.extend(condition.clauses(key))
        return where


class EqualityCondition(object):
    def __init__(self, values):
        self.values = values

    def clauses(self, field):
        return [(field, 'IN', self.values)]


class InequalityCondition(object):

    def __init__(self, values):
        self.values = values

    def clauses(self, field):
        return [(field, 'NOT IN', self.values)]


class API(object):
    def __init__(self):
        self.pool = connection.ConnectionPool()
        self._launch_monitor()

    @_tpool_enabled
    @_retry
    def _check_schema(self):
        with self.pool.get() as conn:
            schema = conn.get_schema()
            models.set_schema(schema)

    def _launch_monitor(self):
        def _schema_monitor():
            while True:
                self._check_schema()
                print "sleeping"
                eventlet.sleep(5)
                print "done sleeping"
        self._check_schema()
        self._monitor_thread = eventlet.spawn_n(_schema_monitor)

    def __getattr__(self, key):
        # forward unimplemented method to sqlalchemy backend:
        return getattr(sqlalchemy_api, key)

    @staticmethod
    def constraint(**conditions):
        return Constraint(conditions)

    @staticmethod
    def equal_any(*values):
        return EqualityCondition(values)

    @staticmethod
    def not_equal(*values):
        return InequalityCondition(values)

    @dbutils.require_context
    @_tpool_enabled
    @_retry
    def bw_usage_update(self, context, uuid, mac, start_period, bw_in, bw_out,
                        last_ctr_in, last_ctr_out, last_refreshed=None):

        if last_refreshed is None:
            last_refreshed = timeutils.utcnow()

        values = {'last_refreshed': last_refreshed,
                  'last_ctr_in': last_ctr_in,
                  'last_ctr_out': last_ctr_out,
                  'bw_in': bw_in,
                  'bw_out': bw_out,
                  'updated_at': timeutils.utcnow}

        with self.pool.get() as conn:
            sql = """UPDATE bw_usage_cache SET bw_in=%s, bw_out=%s,
                         last_ctr_in=%s, last_ctr_out=%s
                     WHERE bw_usage_cache.start_period = %s AND
                           bw_usage_cache.uuid = %s AND
                           bw_usage_cache.mac = %s"""
            args = (bw_in, bw_out, last_ctr_in, last_ctr_out,
                    _datestr(start_period), uuid, mac)
            num_rows_affected = conn.execute(sql, args)
            if num_rows_affected > 0:
                return

        values.pop('updated_at')
        values['created_at'] = timeutils.utcnow()
        values['start_period'] = start_period
        values['uuid'] = uuid
        values['mac'] = mac
        # Start a new transaction.  UPDATE + INSERT can cause a deadlock
        # if mixed into the same transaction.
        with self.pool.get() as conn:
            conn.insert('bw_usage_cache', values)

    @dbutils.require_context
    @_tpool_enabled
    @_retry
    def instance_get_by_uuid(self, context, instance_uuid):
        with self.pool.get() as conn:
            return models.Models.Instance.get_by_uuid(context, instance_uuid, conn)


    @dbutils.require_context
    @_tpool_enabled
    @_retry
    def instance_get_all(self, context, columns_to_join):
        with self.pool.get() as conn:
            return models.Models.Instance.get_all(conn, context, columns_to_join)

    @dbutils.require_context
    @_tpool_enabled
    @_retry
    def instance_destroy(self, context, instance_uuid, constraint=None):
        with self.pool.get() as conn:
            return models.Models.Instance.destroy(conn, context, instance_uuid,
                    constraint)

    @dbutils.require_context
    @_tpool_enabled
    @_retry
    def instance_update(self, context, instance_uuid, values):
        with self.pool.get() as conn:
            return models.Models.Instance.update(conn, context, instance_uuid,
                    values)
