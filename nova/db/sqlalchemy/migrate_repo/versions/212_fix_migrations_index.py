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
from sqlalchemy import Index, MetaData, Table


data = {
    # table_name: ((index_name_1, (*old_columns), (*new_columns)), ...)
    "migrations": (
        ("migrations_by_host_nodes_and_status_idx",
         ('source_compute', 'dest_compute',
          'source_node', 'dest_node', 'status'),
         ('deleted', 'source_compute', 'dest_compute',
          'source_node', 'dest_node', 'status')),
    ),
}


def _add_index(migrate_engine, table, index_name, idx_columns):
    index = Index(
        index_name, *[getattr(table.c, col) for col in idx_columns]
    )
    index.create()


def _drop_index(migrate_engine, table, index_name, idx_columns):
    index = Index(
        index_name, *[getattr(table.c, col) for col in idx_columns]
    )
    index.drop()


def _change_index_columns(migrate_engine, table, index_name,
                          new_columns, old_columns):
    column_mysql = ['source_compute', 'dest_compute',
                    'source_node', 'dest_node']
    for idx in getattr(table, 'indexes'):
        if idx.name == index_name:
            break
    else:
        raise Exception("Index '%s' not found!" % index_name)
    idx.drop(migrate_engine)
    table.indexes.remove(idx)
    columns = []
    for column in new_columns:
        if column in column_mysql:
            columns.append(column + "(100)")
        else:
            columns.append(column)
    sql = ("create index %s ON %s (%s)" % (index_name, table,
                                           ",".join(columns)))
    migrate_engine.execute(sql)


def _modify_indexes(migrate_engine, upgrade):
    if migrate_engine.name == 'sqlite':
        return

    meta = MetaData()
    meta.bind = migrate_engine

    for table_name, indexes in data.iteritems():
        table = Table(table_name, meta, autoload=True)

        for index_name, old_columns, new_columns in indexes:
            if not upgrade:
                new_columns, old_columns = old_columns, new_columns

            if migrate_engine.name == 'postgresql':
                if upgrade:
                    _add_index(migrate_engine, table, index_name, new_columns)
                else:
                    _drop_index(migrate_engine, table, index_name, old_columns)
            elif migrate_engine.name == 'mysql':
                _change_index_columns(migrate_engine, table, index_name,
                                      new_columns, old_columns)
            else:
                raise ValueError('Unsupported DB %s' % migrate_engine.name)


def upgrade(migrate_engine):
    return _modify_indexes(migrate_engine, True)


def downgrade(migrate_engine):
    return _modify_indexes(migrate_engine, False)
