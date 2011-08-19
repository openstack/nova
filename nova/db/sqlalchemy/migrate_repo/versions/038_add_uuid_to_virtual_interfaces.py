# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
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

from nova import utils


meta = MetaData()

virtual_interfaces = Table("virtual_interfaces", meta,
                           Column("id", Integer(), primary_key=True,
                                  nullable=False))
uuid_column = Column("uuid", String(36))


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    virtual_interfaces.create_column(uuid_column)

    rows = migrate_engine.execute(virtual_interfaces.select())
    for row in rows:
        vif_uuid = str(utils.gen_uuid())
        migrate_engine.execute(virtual_interfaces.update()\
                .where(virtual_interfaces.c.id == row[0])\
                .values(uuid=vif_uuid))


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    virtual_interfaces.drop_column(uuid_column)
