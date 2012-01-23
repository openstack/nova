# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import Table, Column, MetaData, Integer

from nova import log as logging


new_columns = [
    Column('free_ram_mb', Integer()),
    Column('free_disk_gb', Integer()),
    Column('current_workload', Integer()),
    Column('running_vms', Integer()),
    ]


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine
    compute_nodes = Table('compute_nodes', meta, autoload=True)

    for column in new_columns:
        compute_nodes.create_column(column)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    compute_nodes = Table('compute_nodes', meta, autoload=True)

    for column in new_columns:
        compute_notes.drop_column(column)
