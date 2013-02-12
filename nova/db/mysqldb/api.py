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
from eventlet import tpool

from nova.db import utils as dbutils
from nova.db.mysqldb import connection
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils


mysqldb_opts = [
    cfg.BoolOpt('use_tpool',
               default=False,
               help='enable threadpooling of DB API calls.'),
]

CONF = cfg.CONF
CONF.register_opts(mysqldb_opts, group='mysqldb')
LOG = logging.getLogger(__name__)


def _tpool_enabled(f):
    """Decorator to use that will wrap a call in tpool.execute if
    CONF.mysqldb.tpool_enable is True
    """
    def wrapped(*args, **kwargs):
        if CONF.mysqldb.use_tpool:
            return tpool.execute(f, *args, **kwargs)
        else:
            return f(*args, **kwargs)
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

    @_tpool_enabled
    @dbutils.require_context
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

    def _instance_get_by_uuid(self, context, uuid, conn):

        # TODO right now the select query is just a full sql stmt below,
        # but we could opt to build a select() function that is more of a
        # one-size fits all.
        """
        joins = (
            {'type': 'LEFT OUTER JOIN',
             'table': 'instance_info_caches',
             'on': 'instance_info_caches.instance_uuid = instances.uuid'},
            {'type': 'LEFT OUTER JOIN',
             'table': 'instance_metadata',
             'on': instance_metadata.instance_uuid = %(uuid)s and
        )
        conn.select('instance', joins)
        raise
        """

        # TODO impl read_deleted fully
        read_deleted = context.read_deleted == 'yes'

        # TODO project_only

        # TODO security_group_rules join
        sql = """SELECT * from instances
            LEFT OUTER JOIN instance_info_caches on
                instance_info_caches.instance_uuid = instances.uuid
            LEFT OUTER JOIN instance_metadata on
                instance_metadata.instance_uuid = %(uuid)s and
                instance_metadata.deleted = 0
            LEFT OUTER JOIN instance_system_metadata on
                instance_system_metadata.instance_uuid = %(uuid)s and
                instance_system_metadata.deleted = 0
            LEFT OUTER JOIN instance_types on
                instances.instance_type_id = instance_types.id
            WHERE instances.uuid = %(uuid)s"""
        if not read_deleted:
            sql += " AND instances.deleted = 0"

        args = {'uuid': uuid}

        LOG.debug(sql)
        LOG.debug(args)
        cursor = conn.cursor()
        cursor.execute(sql, args)

        row = cursor.fetchone()

        if not row:
            raise exception.InstanceNotFound(instance_id=uuid)

        return self._make_sqlalchemy_like_dict(row)

    @_tpool_enabled
    @dbutils.require_context
    def instance_destroy(self, context, instance_uuid, constraint=None):
        with self.pool.get() as conn:
            if uuidutils.is_uuid_like(instance_uuid):
                instance_ref = self._instance_get_by_uuid(context,
                        instance_uuid, conn)
            else:
                raise exception.InvalidUUID(instance_uuid)
            if constraint:
                where = constraint.get_where()
            else:
                where = []
            where.append(('uuid', '=', instance_uuid))
            result = conn.soft_delete('instances', where)
            if result == 0:
                raise exception.ConstraintNotMet()
            where = (('instance_uuid', '=', instance_uuid),)
            conn.soft_delete('security_group_instance_association', where)
            conn.soft_delete('instance_info_caches', where)
        return instance_ref

    def _instance_update(self, context, instance_uuid, values,
                         copy_old_instance=False):
        with self.pool.get() as conn:
            if not uuidutils.is_uuid_like(instance_uuid):
                raise exception.InvalidUUID(instance_uuid)

            instance_ref = self._instance_get_by_uuid(context, instance_uuid,
                                                      conn)            

            # TODO instance type extra specs

            # confirm actual task state matched the expected value:
            dbutils.check_task_state(instance_ref, values)

            # TODO hostname validation

            # TODO update metadata

            # TODO update sys metadata

            # TODO update inst type


            where = (('uuid', '=', instance_uuid),)
            rowcount = conn.update("instances", values, where)
            if rowcount != 1:
                raise exception.InstanceNotFound(instance_id=instance_uuid)

            # get updated record
            new_instance_ref = self._instance_get_by_uuid(context,
                    instance_uuid, conn)
            return instance_ref, new_instance_ref

    @_tpool_enabled
    @dbutils.require_context
    def instance_update(self, context, instance_uuid, values):
        instance_ref = self._instance_update(context, instance_uuid, values)[1]
        return instance_ref

    def _make_sqlalchemy_like_dict(self, row):
        """Make a SQLAlchemy-like dictionary, where each join gets namespaced as
        dictionary within the top-level dictionary.
        """
        result = {}
        for key, value in row.iteritems():
            # find keys like join_table_name.column and dump them into a
            # sub-dict
            tok = key.split(".")
            if len(tok) == 2:
                tbl, col = tok
                join_dict = result.setdefault(tbl, {})
                join_dict[col] = value
            else:
                result[key] = value
            
        return result

    def _pretty_print_result(self, result):
        import pprint
        pprint.pprint(result, indent=4)
