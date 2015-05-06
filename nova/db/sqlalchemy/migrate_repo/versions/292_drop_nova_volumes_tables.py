# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


from migrate import ForeignKeyConstraint
from sqlalchemy.engine import reflection
from sqlalchemy import MetaData
from sqlalchemy import Table


def upgrade(engine):
    meta = MetaData()
    meta.bind = engine

    def _get_columns(source_table, params):
        columns = set()
        for column in params:
            columns.add(source_table.c[column])
        return columns

    def _remove_foreign_key_constraints(engine, meta, table_name):
        inspector = reflection.Inspector.from_engine(engine)

        for fk in inspector.get_foreign_keys(table_name):
            source_table = Table(table_name, meta, autoload=True)
            target_table = Table(fk['referred_table'], meta, autoload=True)

            fkey = ForeignKeyConstraint(
                columns=_get_columns(source_table, fk['constrained_columns']),
                refcolumns=_get_columns(target_table, fk['referred_columns']),
                name=fk['name'])
            fkey.drop()

    def _drop_table_and_indexes(meta, table_name):
        table = Table(table_name, meta, autoload=True)
        for index in table.indexes:
            index.drop()
        table.drop()

    # Drop the `iscsi_targets` and `volumes` tables They were used with
    # nova-volumes, which is deprecated and removed, but the related
    # tables are still created.
    table_names = ('iscsi_targets', 'shadow_iscsi_targets',
                   'volumes', 'shadow_volumes')

    for table_name in table_names:
        _remove_foreign_key_constraints(engine, meta, table_name)
        _drop_table_and_indexes(meta, table_name)
