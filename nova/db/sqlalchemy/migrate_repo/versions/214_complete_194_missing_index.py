# Copyright 2013 Rackspace Australia
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# NOTE(jhesketh): The 194 migration that was meant to fix lost indexes from
# 152 but missed two out. We'll add them in now.

from migrate import ForeignKeyConstraint
from nova.db.sqlalchemy import utils
from sqlalchemy import MetaData, Table


data = {
    # table_name: ((index_name_1, (*old_columns), (*new_columns)), ...)
    "migrations": ((
        'migrations_instance_uuid_and_status_idx',
        ('instance_uuid', 'status'),
        ('deleted', 'instance_uuid', 'status')
    ),)
}


def upgrade(migrate_engine):
    if migrate_engine.name == 'mysql':
        # NOTE(jhesketh): MySQL Cannot drop index
        # migrations_instance_uuid_and_status_idx needed in a foreign
        # key constraint. So we'll remove the fkey constraint on the
        # aggregate_metadata table and add it back after the indexes are
        # upgraded.
        meta = MetaData(bind=migrate_engine)
        table = Table('migrations', meta, autoload=True)
        ref_table = Table('instances', meta, autoload=True)
        params = {'columns': [table.c['instance_uuid']],
                  'refcolumns': [ref_table.c['uuid']]}
        if migrate_engine.name == 'mysql':
            params['name'] = 'fk_migrations_instance_uuid'
        fkey = ForeignKeyConstraint(**params)
        fkey.drop()

    utils.modify_indexes(migrate_engine, data)

    if migrate_engine.name == 'mysql':
        fkey.create()


def downgrade(migrate_engine):
    if migrate_engine.name == 'mysql':
        # NOTE(jhesketh): MySQL Cannot drop index
        # migrations_instance_uuid_and_status_idx needed in a foreign
        # key constraint. So we'll remove the fkey constraint on the
        # aggregate_metadata table and add it back after the indexes are
        # downgraded.
        meta = MetaData(bind=migrate_engine)
        table = Table('migrations', meta, autoload=True)
        ref_table = Table('instances', meta, autoload=True)
        params = {'columns': [table.c['instance_uuid']],
                  'refcolumns': [ref_table.c['uuid']]}
        if migrate_engine.name == 'mysql':
            params['name'] = 'fk_migrations_instance_uuid'
        fkey = ForeignKeyConstraint(**params)
        fkey.drop()

    utils.modify_indexes(migrate_engine, data, upgrade=False)

    if migrate_engine.name == 'mysql':
        fkey.create()
