# Copyright (c) 2015 Red Hat, Inc.
# All Rights Reserved.
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


from migrate import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy import MetaData, Table
from sqlalchemy.engine import reflection


def _correct_sqlite_unique_constraints(migrate_engine, table):
    # NOTE(sbauza): SQLAlchemy<1.0 doesn't provide the unique keys in the
    # constraints field of the Table object, so it would drop them if we change
    # either the scheme or the constraints. Adding them back to the Table
    # object before changing the model makes sure that they are not dropped.
    if migrate_engine.name != 'sqlite':
        # other engines don't have this problem
        return
    inspector = reflection.Inspector.from_engine(migrate_engine)
    constraints = inspector.get_unique_constraints(table.name)
    constraint_names = [c.name for c in table.constraints]
    for constraint in constraints:
        if constraint['name'] in constraint_names:
            # the constraint is already in the table
            continue
        table.constraints.add(
            UniqueConstraint(*constraint['column_names'],
                             table=table, name=constraint['name']))


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    compute_nodes = Table('compute_nodes', meta, autoload=True)
    shadow_compute_nodes = Table('shadow_compute_nodes', meta, autoload=True)
    services = Table('services', meta, autoload=True)

    _correct_sqlite_unique_constraints(migrate_engine, compute_nodes)

    # Make the service_id column nullable
    compute_nodes.c.service_id.alter(nullable=True)
    shadow_compute_nodes.c.service_id.alter(nullable=True)

    for fk in compute_nodes.foreign_keys:
        if fk.column == services.c.id:
            # Delete the FK
            fkey = ForeignKeyConstraint(columns=[compute_nodes.c.service_id],
                                        refcolumns=[services.c.id],
                                        name=fk.name)
            fkey.drop()
            break
    for index in compute_nodes.indexes:
        if 'service_id' in index.columns:
            # Delete the nested index which was created by the FK
            index.drop()
            break
