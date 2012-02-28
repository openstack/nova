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

from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)
    zone_name = instances.c.zone_name
    zone_name.alter(name='cell_name')
    zones = Table('zones', meta, autoload=True)
    zones.rename('cells')


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)
    cell_name = instances.c.cell_name
    cell_name.alter(name='zone_name')
    cells = Table('cells', meta, autoload=True)
    cells.rename('zones')
