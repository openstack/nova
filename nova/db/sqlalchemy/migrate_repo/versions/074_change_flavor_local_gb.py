# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import sqlalchemy
from sqlalchemy import select, Column, Integer

from nova import exception
from nova import flags


FLAGS = flags.FLAGS

meta = sqlalchemy.MetaData()


def _get_table(name):
    return sqlalchemy.Table(name, meta, autoload=True)


def upgrade_libvirt(instances, instance_types):
    # Update instance_types first
    tiny = None
    for inst_type in instance_types.select().execute():
        if inst_type['name'] == 'm1.tiny':
            tiny = inst_type['id']
            root_gb = 0
        else:
            root_gb = 10

        instance_types.update()\
                      .values(root_gb=root_gb,
                              ephemeral_gb=inst_type['local_gb'])\
                      .where(instance_types.c.id == inst_type['id'])\
                      .execute()

    # then update instances following same pattern
    instances.update()\
             .values(root_gb=10,
                     ephemeral_gb=instances.c.local_gb)\
             .execute()

    if tiny is not None:
        instances.update()\
                 .values(root_gb=0,
                         ephemeral_gb=instances.c.local_gb)\
                 .where(instances.c.instance_type_id == tiny)\
                 .execute()


def upgrade_other(instances, instance_types):
    for table in (instances, instance_types):
        table.update().values(root_gb=table.c.local_gb,
                              ephemeral_gb=0).execute()


def check_instance_presence(migrate_engine, instances_table):
    result = migrate_engine.execute(instances_table.select().limit(1))
    return result.fetchone() is not None


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    instances = _get_table('instances')

    data_present = check_instance_presence(migrate_engine, instances)

    if data_present and not FLAGS.connection_type:
        msg = ("Found instance records in database. You must specify "
               "connection_type to run migration migration")
        raise exception.Error(msg)

    instance_types = _get_table('instance_types')

    for table in (instances, instance_types):
        root_gb = Column('root_gb', Integer)
        root_gb.create(table)
        ephemeral_gb = Column('ephemeral_gb', Integer)
        ephemeral_gb.create(table)

    # Since this migration is part of the work to get all drivers
    # working the same way, we need to treat the new root_gb and
    # ephemeral_gb columns differently depending on what the
    # driver implementation used to behave like.
    if FLAGS.connection_type == 'libvirt':
        upgrade_libvirt(instances, instance_types)
    else:
        upgrade_other(instances, instance_types)

    default_local_device = instances.c.default_local_device
    default_local_device.alter(name='default_ephemeral_device')

    for table in (instances, instance_types):
        table.drop_column('local_gb')


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instances = _get_table('instances')
    instance_types = _get_table('instance_types')

    for table in (instances, instance_types):
        local_gb = Column('root_gb', Integer)
        local_gb.create(table)

    try:
        for table in (instances, instance_types):
            if FLAGS.connection_type == 'libvirt':
                column = table.c.ephemeral_gb
            else:
                column = table.c.root_gb
            table.update().values(local_gb=column).execute()
    except Exception:
        for table in (instances, instance_types):
            table.drop_column('local_gb')
        raise

    default_ephemeral_device = instances.c.default_ephemeral_device
    default_ephemeral_device.alter(name='default_local_device')

    for table in (instances, instance_types):
        table.drop_column('root_gb')
        table.drop_column('ephemeral_gb')
