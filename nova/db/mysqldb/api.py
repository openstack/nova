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
from nova.db.mysqldb import models
from nova.db.mysqldb import sql
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

    @_tpool_enabled
    def instance_get_by_uuid(self, context, instance_uuid):
        with self.pool.get() as conn:
            return self._instance_get_by_uuid(context, instance_uuid, conn)

    @_tpool_enabled
    def instance_get_all(self, context, columns_to_join):
        # FIXME: implement context checking.
        clauses = [sql.EQ(sql.Literal('self.deleted'), 0)]
        with self.pool.get() as conn:
            return models.Instance.select(conn, clauses=clauses)

    def _instance_get_by_uuid(self, context, instance_uuid, conn):

        clauses = [sql.EQ(sql.Literal('self.uuid'), instance_uuid)]
        if context.read_deleted == 'no':
            clauses.append(sql.EQ(sql.Literal('self.deleted'), 0))
        elif context.read_deleted == 'only':
            clauses.append(sql.GT(sql.Literal('self.deleted'), 0))
        if not context.is_admin:
            clauses.append(sql.GT(sql.Literal('self.project_id'),
                context.project_id))
        with self.pool.get() as conn:
            instance = models.Instance.select(conn, clauses=clauses)
            if not instance:
                raise exception.InstanceNotFound(instance_id=instance_uuid)
            return instance[0]

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

    def _instance_metadata_update(self, context, instance_ref, metadata_type,
                                  table, metadata, conn):
        uuid = instance_ref['uuid']

        self._pretty_print(instance_ref)
        for keyvalue in instance_ref[metadata_type]:
            print "---"
            print instance_ref[metadata_type]
            key = keyvalue['key']
            if key in metadata:
                # update existing value:
                values = {'key': key, 'value': metadata.pop(key)}
                where = (
                    ('key', '=', key),
                    ('instance_uuid', '=', uuid)
                )
                conn.update(table, values, where)

            elif key not in metadata:
                # purge keys not being updated:
                where = (
                    ('key', '=', key),
                    ('instance_uuid', '=', uuid)
                )
                conn.soft_delete(table, where)

        # add new keys:
        for key, value in metadata.iteritems():
            values = {
                'key': key,
                'value': value,
                'instance_uuid': uuid
            }
            conn.insert(table, values)


    def _instance_update(self, context, instance_uuid, values,
                         copy_old_instance=False):
        with self.pool.get() as conn:
            if not uuidutils.is_uuid_like(instance_uuid):
                raise exception.InvalidUUID(instance_uuid)

            instance_ref = self._instance_get_by_uuid(context, instance_uuid,
                                                      conn)            
            # confirm actual task state matched the expected value:
            dbutils.check_task_state(instance_ref, values)

            if copy_old_instance:
                # just return the 1st instance_ref, we don't mutate the
                # instance in this DB backend
                old_instance_ref = instance_ref
            else:
                old_instance_ref = None

            # TODO hostname validation

            metadata = values.get('metadata')
            if metadata is not None:
                self._instance_metadata_update(context, instance_ref,
                        'metadata', 'instance_metadata',
                        values.pop('metadata'), conn)
                
            system_metadata = values.get('system_metadata')
            if system_metadata is not None:
                self._instance_metadata_update(context, instance_ref,
                        'system_metadata', 'instance_system_metadata',
                        values.pop('system_metadata'), conn)

            # update the instance itself:
            if len(values) > 0:
                where = (('uuid', '=', instance_uuid),)
                rowcount = conn.update('instances', values, where)
                if rowcount != 1:
                    raise exception.InstanceNotFound(instance_id=instance_uuid)

            # get updated record
            new_instance_ref = self._instance_get_by_uuid(context,
                    instance_uuid, conn)
            return old_instance_ref, new_instance_ref

    @_tpool_enabled
    @dbutils.require_context
    def instance_update(self, context, instance_uuid, values):
        instance_ref = self._instance_update(context, instance_uuid, values)[1]
        return instance_ref
