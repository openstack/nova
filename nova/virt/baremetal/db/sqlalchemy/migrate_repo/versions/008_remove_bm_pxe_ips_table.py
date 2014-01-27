# Copyright 2013 Mirantis Inc.
# All Rights Reserved
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

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


table_name = 'bm_pxe_ips'


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table(table_name, meta, autoload=True)
    table.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    bm_pxe_ips = Table(table_name, meta,
                       Column('created_at', DateTime),
                       Column('updated_at', DateTime),
                       Column('deleted_at', DateTime),
                       Column('deleted', Boolean),
                       Column('id', Integer, primary_key=True, nullable=False),
                       Column('address', String(length=255), unique=True),
                       Column('bm_node_id', Integer),
                       Column('server_address',
                              String(length=255), unique=True),
                       mysql_engine='InnoDB',
                       )
    bm_pxe_ips.create()

    Index(
        'idx_bm_pxe_ips_bm_node_id_deleted',
        bm_pxe_ips.c.bm_node_id,
        bm_pxe_ips.c.deleted
    ).create(migrate_engine)
