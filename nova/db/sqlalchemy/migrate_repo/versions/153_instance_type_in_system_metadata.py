# Copyright 2013 IBM Corp.
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

from sqlalchemy import MetaData, select, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)
    instance_types = Table('instance_types', meta, autoload=True)
    sys_meta = Table('instance_system_metadata', meta, autoload=True)

    # Taken from nova/compute/api.py
    instance_type_props = ['id', 'name', 'memory_mb', 'vcpus',
                           'root_gb', 'ephemeral_gb', 'flavorid',
                           'swap', 'rxtx_factor', 'vcpu_weight']

    select_columns = [instances.c.uuid]
    select_columns += [getattr(instance_types.c, name)
                       for name in instance_type_props]

    q = select(select_columns, from_obj=instances.join(
            instance_types,
            instances.c.instance_type_id == instance_types.c.id)).where(
                instances.c.deleted == 0)

    i = sys_meta.insert()
    for values in q.execute():
        insert_rows = []
        for index in range(0, len(instance_type_props)):
            value = values[index + 1]
            insert_rows.append({
                "key": "instance_type_%s" % instance_type_props[index],
                "value": None if value is None else str(value),
                "instance_uuid": values[0],
            })
        i.execute(insert_rows)


def downgrade(migration_engine):
    # This migration only touches data, and only metadata at that. No need
    # to go through and delete old metadata items.
    pass
