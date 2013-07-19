# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation.
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

from sqlalchemy import Column, MetaData, Enum, Table
from sqlalchemy.dialects import postgresql


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    for table_name in ['instances', 'shadow_instances']:
        enum = Enum('owner', 'admin', name='%s0locked_by' % table_name)
        if migrate_engine.url.get_dialect() is postgresql.dialect:
            # Need to explicitly create Postgres enums during migrations
            enum.create(migrate_engine, checkfirst=False)

        instances = Table(table_name, meta, autoload=True)
        locked_by = Column('locked_by', enum)
        instances.create_column(locked_by)
        instances.update().\
            where(instances.c.locked == True).\
            values(locked_by='admin').execute()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    for table_name in ['instances', 'shadow_instances']:
        instances = Table(table_name, meta, autoload=True)
        instances.drop_column('locked_by')

        Enum(name='%s0locked_by' % table_name).drop(migrate_engine,
                                                    checkfirst=False)
