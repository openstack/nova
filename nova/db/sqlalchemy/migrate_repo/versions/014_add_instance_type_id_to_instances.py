# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from sqlalchemy import Column, Integer, MetaData, String, Table
#from nova import log as logging

meta = MetaData()

c_instance_type = Column('instance_type',
                           String(length=255, convert_unicode=False,
                                  assert_unicode=None, unicode_error=None,
                                  _warn_on_bytestring=False),
                           nullable=True)

c_instance_type_id = Column('instance_type_id',
                           String(length=255, convert_unicode=False,
                                  assert_unicode=None, unicode_error=None,
                                  _warn_on_bytestring=False),
                           nullable=True)

instance_types = Table('instance_types', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('name',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False),
                      unique=True))


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True,
                      autoload_with=migrate_engine)

    instances.create_column(c_instance_type_id)

    type_names = {}
    recs = migrate_engine.execute(instance_types.select())
    for row in recs:
        type_names[row[0]] = row[1]

    for type_id, type_name in type_names.iteritems():
        migrate_engine.execute(instances.update()\
            .where(instances.c.instance_type == type_name)\
            .values(instance_type_id=type_id))

    instances.c.instance_type.drop()


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True,
                      autoload_with=migrate_engine)

    instances.create_column(c_instance_type)

    recs = migrate_engine.execute(instance_types.select())
    for row in recs:
        type_id = row[0]
        type_name = row[1]
        migrate_engine.execute(instances.update()\
            .where(instances.c.instance_type_id == type_id)\
            .values(instance_type=type_name))

    instances.c.instance_type_id.drop()
