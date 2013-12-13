# -*- encoding: utf-8 -*-
#
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from migrate import ForeignKeyConstraint
from sqlalchemy import MetaData, Table
from sqlalchemy.sql.expression import select

from nova.db.sqlalchemy import utils


TABLES = [
    ("compute_node_stats",
     ('compute_node_id', 'compute_nodes', 'id'),
     None),
    ("compute_nodes",
     ('service_id', 'services', 'id'),
     ('compute_node_stats', 'compute_node_id', 'id')),
    ("instance_actions",
     ('instance_uuid', 'instances', 'uuid'),
     ('instance_actions_events', 'action_id', 'id')),
    ("migrations",
     ('instance_uuid', 'instances', 'uuid'),
     None),
    ("instance_faults",
     ('instance_uuid', 'instances', 'uuid'),
     None),
]


def dump_cleanup_rows(engine, meta, table, where):
    # Dump rows that match where clause, then delete the rows
    dump_table_name = 'dump_' + table.name
    table_dump = meta.tables.get(dump_table_name)
    if table_dump is None:
        columns = [c.copy() for c in table.columns]
        table_dump = Table(dump_table_name, meta, *columns,
                           mysql_engine='InnoDB')
        table_dump.create()

    engine.execute(utils.InsertFromSelect(table_dump,
                                          table.select().where(where)))
    engine.execute(table.delete().where(where))


def upgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        return
    meta = MetaData(bind=migrate_engine)
    for table_name, ref, child in TABLES:
        table = Table(table_name, meta, autoload=True)

        column_name, ref_table_name, ref_column_name = ref
        column = table.c[column_name]

        ref_table = Table(ref_table_name, meta, autoload=True)
        ref_column = ref_table.c[ref_column_name]

        subq = select([ref_column]).where(ref_column != None)

        if child:
            # Dump and cleanup rows in child table first
            child_table_name, child_column_name, child_ref_column_name = child

            child_table = Table(child_table_name, meta, autoload=True)
            child_column = child_table.c[child_column_name]

            child_ref_column = table.c[child_ref_column_name]

            child_subq = select([child_ref_column]).where(~ column.in_(subq))
            dump_cleanup_rows(migrate_engine, meta, child_table,
                              child_column.in_(child_subq))

        dump_cleanup_rows(migrate_engine, meta, table, ~ column.in_(subq))

        params = {'columns': [column], 'refcolumns': [ref_column]}
        if migrate_engine.name == 'mysql':
            params['name'] = "_".join(('fk', table_name, column_name))
        fkey = ForeignKeyConstraint(**params)
        fkey.create()


def restore_rows(engine, meta, table_name):
    # Restore data that had been dropped in the upgrade
    table = Table(table_name, meta, autoload=True)
    table_dump_name = 'dump_' + table_name
    table_dump = Table(table_dump_name, meta, autoload=True)
    sql = utils.InsertFromSelect(table, table_dump.select())
    engine.execute(sql)
    table_dump.drop()


def downgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        return
    meta = MetaData(bind=migrate_engine)
    for table_name, ref, child in TABLES:
        table = Table(table_name, meta, autoload=True)

        column_name, ref_table_name, ref_column_name = ref
        column = table.c[column_name]

        ref_table = Table(ref_table_name, meta, autoload=True)
        ref_column = ref_table.c[ref_column_name]

        params = {'columns': [column], 'refcolumns': [ref_column]}
        if migrate_engine.name == 'mysql':
            params['name'] = "_".join(('fk', table_name, column_name))
        with migrate_engine.begin():
            fkey = ForeignKeyConstraint(**params)
            fkey.drop()

        with migrate_engine.begin():
            restore_rows(migrate_engine, meta, table_name)

        # compute_node_stats has a missing foreign key and is a child of
        # of compute_nodes. Don't bother processing it as a child since
        # only want to restore the dump once
        if child and table_name != 'compute_nodes':
            child_table_name, child_column_name, child_ref_column_name = child

            with migrate_engine.begin():
                restore_rows(migrate_engine, meta, child_table_name)
