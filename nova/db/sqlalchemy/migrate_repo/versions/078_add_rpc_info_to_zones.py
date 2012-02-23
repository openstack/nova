# Copyright 2012 OpenStack LLC.
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

from sqlalchemy import Boolean, Column
from sqlalchemy import Integer, MetaData, String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    zones = Table('zones', meta, autoload=True)

    is_parent = Column('is_parent', Boolean(), default=False)
    rpc_host = Column('rpc_host', String(255))
    rpc_port = Column('rpc_port', Integer())
    rpc_virtual_host = Column('rpc_virtual_host', String(255))

    zones.create_column(is_parent)
    zones.create_column(rpc_host)
    zones.create_column(rpc_port)
    zones.create_column(rpc_virtual_host)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    zones = Table('zones', meta, autoload=True)

    zones.drop_column('rpc_virtual_host')
    zones.drop_column('rpc_port')
    zones.drop_column('rpc_host')
    zones.drop_column('is_parent')
