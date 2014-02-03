# Copyright (c) 2013 NTT DOCOMO, INC.
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

from sqlalchemy import Column, MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('bm_nodes', meta, autoload=True)
    nodes.drop_column('prov_mac_address')


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('bm_nodes', meta, autoload=True)
    nodes.create_column(Column('prov_mac_address', String(length=255)))

    # NOTE(arata): The values held by prov_mac_address are lost in upgrade.
    # So downgrade has no other choice but to set the column to NULL.
