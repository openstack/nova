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
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from migrate.changeset import UniqueConstraint
from migrate import ForeignKeyConstraint
from sqlalchemy import MetaData, Table

from nova.db.sqlalchemy import utils


UC_NAME = 'uniq_aggregate_metadata0aggregate_id0key0deleted'
COLUMNS = ('aggregate_id', 'key', 'deleted')
TABLE_NAME = 'aggregate_metadata'


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    t = Table(TABLE_NAME, meta, autoload=True)

    utils.drop_old_duplicate_entries_from_table(migrate_engine, TABLE_NAME,
                                                True, *COLUMNS)
    uc = UniqueConstraint(*COLUMNS, table=t, name=UC_NAME)
    uc.create()


def downgrade(migrate_engine):
    if migrate_engine.name == 'mysql':
        # NOTE(jhesketh): MySQL Cannot drop index
        # 'uniq_aggregate_metadata0aggregate_id0key0deleted': needed in a
        # foreign key constraint. So we'll remove the fkey constraint on the
        # aggregate_metadata table and add it back after the index is
        # downgraded.
        meta = MetaData(bind=migrate_engine)
        table = Table('aggregate_metadata', meta, autoload=True)
        ref_table = Table('aggregates', meta, autoload=True)
        params = {'columns': [table.c['aggregate_id']],
                  'refcolumns': [ref_table.c['id']],
                  'name': 'aggregate_metadata_ibfk_1'}
        fkey = ForeignKeyConstraint(**params)
        fkey.drop()

    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, UC_NAME, *COLUMNS)

    if migrate_engine.name == 'mysql':
        fkey.create()
