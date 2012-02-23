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

from sqlalchemy import Column, Integer, MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_types = Table('instance_types', meta, autoload=True)
    migrations = Table('migrations', meta, autoload=True)

    old_instance_type_id = Column('old_instance_type_id', Integer())
    new_instance_type_id = Column('new_instance_type_id', Integer())
    migrations.create_column(old_instance_type_id)
    migrations.create_column(new_instance_type_id)

    # Convert flavor_id to instance_type_id
    itypes = {}
    for instance_type in migrate_engine.execute(instance_types.select()):
        itypes[instance_type.id] = instance_type.flavorid

    for instance_type_id in itypes.keys():
        migrate_engine.execute(migrations.update()\
                .where(migrations.c.old_flavor_id == itypes[instance_type_id])\
                .values(old_instance_type_id=instance_type_id))
        migrate_engine.execute(migrations.update()\
                .where(migrations.c.new_flavor_id == itypes[instance_type_id])\
                .values(new_instance_type_id=instance_type_id))

    migrations.c.old_flavor_id.drop()
    migrations.c.new_flavor_id.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_types = Table('instance_types', meta, autoload=True)
    migrations = Table('migrations', meta, autoload=True)

    old_flavor_id = Column('old_flavor_id', Integer())
    new_flavor_id = Column('new_flavor_id', Integer())

    migrations.create_column(old_flavor_id)
    migrations.create_column(new_flavor_id)

    # Convert instance_type_id to flavor_id
    itypes = {}
    for instance_type in migrate_engine.execute(instance_types.select()):
        itypes[instance_type.flavorid] = instance_type.id

    for instance_type_flavorid in itypes.keys():
        migrate_engine.execute(migrations.update()\
                .where(migrations.c.old_instance_type_id ==
                    itypes[instance_type_flavorid])\
                .values(old_flavor_id=instance_type_flavorid))
        migrate_engine.execute(migrations.update()\
                .where(migrations.c.new_instance_type_id ==
                    itypes[instance_type_flavorid])\
                .values(new_flavor_id=instance_type_flavorid))

    migrations.c.old_instance_type_id.drop()
    migrations.c.new_instance_type_id.drop()
