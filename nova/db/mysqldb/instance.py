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

from nova.db.mysqldb import transform
from nova.db import utils as dbutils
from nova.openstack.common import uuidutils


def _build_instance_get(context):
    sql = """SELECT * from instances
        LEFT OUTER JOIN instance_info_caches on
            instance_info_caches.instance_uuid = instances.uuid
        LEFT OUTER JOIN instance_metadata as metadata on
            metadata.instance_uuid = instances.uuid and
            metadata.deleted = 0
        LEFT OUTER JOIN instance_system_metadata as system_metadata on
            system_metadata.instance_uuid = instances.uuid and
            system_metadata.deleted = 0
        LEFT OUTER JOIN instance_types on
            instances.instance_type_id = instance_types.id"""

    if context.read_deleted == 'no':
        sql += " AND instances.deleted = 0"
    elif context.read_deleted == 'only':
        sql += " AND instances.deleted > 0"
    if not context.is_admin:
        sql += " AND instances.project_id = %(project_id)s"

    kwargs = {'project_id': context.project_id}

    class Join(object):
        def __init__(self, table, target):
            self.table = table
            self.target = target
            self.use_list = True

    joins = [Join('instance_info_caches', 'info_cache'),
             Join('instance_metadata', 'metadata'),
             Join('instance_system_metadata', 'system_metadata'),
             Join('instance_types', 'instance_type')]

    return sql, kwargs, joins


def _instance_get_by_uuid(conn, context, instance_uuid):
    sql, kwargs, joins = _build_instance_get(context)
    sql += " WHERE instances.uuid = %(uuid)s"
    kwargs['uuid'] = instance_uuid

    cursor = conn.select(sql, kwargs)
    rows = cursor.fetchall()
    instances = transform.to_objects(rows, 'instances', joins)
    if not instances:
        raise exception.InstanceNotFound(instance_id=instance_uuid)

    return instances[0]


def _instance_metadata_update(conn, context, instance_ref, metadata_type,
                              table, metadata):
    uuid = instance_ref['uuid']

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


def _instance_update(conn, context, instance_uuid, values,
                     copy_old_instance=False):
    if not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(instance_uuid)

    instance_ref = _instance_get_by_uuid(conn, context, instance_uuid)

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
        _instance_metadata_update(conn, context, instance_ref,
                'metadata', 'instance_metadata',
                values.pop('metadata'))
        
    system_metadata = values.get('system_metadata')
    if system_metadata is not None:
        _instance_metadata_update(conn, context, instance_ref,
                'system_metadata', 'instance_system_metadata',
                values.pop('system_metadata'))

    # update the instance itself:
    if len(values) > 0:
        where = (('uuid', '=', instance_uuid),)
        cursor = conn.update('instances', values, where)
        if cursor.rowcount != 1:
            raise exception.InstanceNotFound(instance_id=instance_uuid)

    # get updated record
    new_instance_ref = _instance_get_by_uuid(conn, context,
            instance_uuid)
    return old_instance_ref, new_instance_ref


class Mixin(object):

    @classmethod
    def get_by_uuid(cls, conn, context, instance_uuid):
        return cls._instance_get_by_uuid(conn, context, instance_uuid)

    @classmethod
    def get_all(cls, conn, context, columns_to_join):
        sql, kwargs, joins = _build_instance_get(context)
        cursor = conn.select(sql, kwargs)
        rows = cursor.fetchall()
        instances = transform.to_objects(rows, 'instances', joins)
        return instances

    @classmethod
    def destroy(cls, conn, context, instance_uuid, constraint=None):
        if uuidutils.is_uuid_like(instance_uuid):
            instance_ref = _instance_get_by_uuid(conn, context,
                    instance_uuid)
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

    @classmethod
    def update(cls, conn, context, instance_uuid, values):
        instance_ref = _instance_update(conn, context, instance_uuid, values)[1]
        return instance_ref
