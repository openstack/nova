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
#    under the License.from sqlalchemy import *

from sqlalchemy import Column, Integer, MetaData, Table

meta = MetaData()

migrations = Table('migrations', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )

#
# Tables to alter
#
#

old_flavor_id = Column('old_flavor_id', Integer())
new_flavor_id = Column('new_flavor_id', Integer())


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    migrations.create_column(old_flavor_id)
    migrations.create_column(new_flavor_id)


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    migrations.drop_column(old_flavor_id)
    migrations.drop_column(new_flavor_id)
