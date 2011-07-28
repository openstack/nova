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

from sqlalchemy import Column, Integer, String, MetaData, Table


meta = MetaData()


#
# Tables to alter
#
#

instance_id = Column('instance_id', Integer())
instance_uuid = Column('instance_uuid', String(255))


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    migrations = Table('migrations', meta, autoload=True)
    migrations.create_column(instance_uuid)

    if migrate_engine.name == "mysql":
        try:
            migrate_engine.execute("ALTER TABLE migrations DROP FOREIGN KEY " \
                    "`migrations_ibfk_1`;")
        except Exception:  # Don't care, just fail silently.
            pass

    migrations.c.instance_id.drop()


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    migrations = Table('migrations', meta, autoload=True)
    migrations.c.instance_uuid.drop()
    migrations.create_column(instance_id)
