# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Boris Pavlovic (boris@pavlovic.me).
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

from migrate.changeset import UniqueConstraint
from sqlalchemy.engine import reflection
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import func
from sqlalchemy import MetaData, Table, Column, Index
from sqlalchemy.sql.expression import UpdateBase, literal_column
from sqlalchemy.sql import select
from sqlalchemy.types import NullType


from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)


class InsertFromSelect(UpdateBase):
    def __init__(self, table, select):
        self.table = table
        self.select = select


@compiles(InsertFromSelect)
def visit_insert_from_select(element, compiler, **kw):
    return "INSERT INTO %s %s" % (
        compiler.process(element.table, asfrom=True),
        compiler.process(element.select))


def _drop_unique_constraint_in_sqlite(migrate_engine, table_name, uc_name,
                                      **col_name_col_instance):
    insp = reflection.Inspector.from_engine(migrate_engine)
    meta = MetaData(bind=migrate_engine)

    table = Table(table_name, meta, autoload=True)
    columns = []
    for column in table.columns:
        if isinstance(column.type, NullType):
            try:
                new_column = col_name_col_instance.get(column.name)
            except Exception as e:
                msg = _("Please specify column %s in col_name_col_instance "
                        "param. It is required because column has unsupported "
                        "type by sqlite).")
                raise exception.NovaException(msg % column.name)

            if not isinstance(new_column, Column):
                msg = _("col_name_col_instance param has wrong type of "
                        "column instance for column %s It should be instance "
                        "of sqlalchemy.Column.")
                raise exception.NovaException(msg % column.name)
            columns.append(new_column)
        else:
            columns.append(column.copy())

    constraints = [constraint for constraint in table.constraints
                    if not constraint.name == uc_name]

    new_table = Table(table_name + "__tmp__", meta, *(columns + constraints))
    new_table.create()

    indexes = []
    for index in insp.get_indexes(table_name):
        column_names = [new_table.c[c] for c in index['column_names']]
        indexes.append(Index(index["name"],
                             *column_names,
                             unique=index["unique"]))

    ins = InsertFromSelect(new_table, table.select())
    migrate_engine.execute(ins)
    table.drop()

    [index.create(migrate_engine) for index in indexes]
    new_table.rename(table_name)


def drop_unique_constraint(migrate_engine, table_name, uc_name, *columns,
                           **col_name_col_instance):
    """
    This method drops UC from table and works for mysql, postgresql and sqlite.
    In mysql and postgresql we are able to use "alter table" constuction. In
    sqlite is only one way to drop UC:
        1) Create new table with same columns, indexes and constraints
           (except one that we want to drop).
        2) Copy data from old table to new.
        3) Drop old table.
        4) Rename new table to the name of old table.

    :param migrate_engine: sqlalchemy engine
    :param table_name:     name of table that contains uniq constarint.
    :param uc_name:        name of uniq constraint that will be dropped.
    :param columns:        columns that are in uniq constarint.
    :param col_name_col_instance:   contains pair column_name=column_instance.
                            column_instance is instance of Column. These params
                            are required only for columns that have unsupported
                            types by sqlite. For example BigInteger.
    """
    if migrate_engine.name in ["mysql", "postgresql"]:
        meta = MetaData()
        meta.bind = migrate_engine
        t = Table(table_name, meta, autoload=True)
        uc = UniqueConstraint(*columns, table=t, name=uc_name)
        uc.drop()
    else:
        _drop_unique_constraint_in_sqlite(migrate_engine, table_name, uc_name,
                                          **col_name_col_instance)


def drop_old_duplicate_entries_from_table(migrate_engine, table_name,
                                          use_soft_delete, *uc_column_names):
    """
    This method is used to drop all old rowss that have the same values for
    columns in uc_columns.
    """
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table(table_name, meta, autoload=True)
    columns_for_group_by = [table.c[name] for name in uc_column_names]

    columns_for_select = [func.max(table.c.id)]
    columns_for_select.extend(list(columns_for_group_by))

    duplicated_rows_select = select(columns_for_select,
                                    group_by=columns_for_group_by,
                                    having=func.count(table.c.id) > 1)

    for row in migrate_engine.execute(duplicated_rows_select):
        # NOTE(boris-42): Do not remove row that has the biggest ID.
        delete_condition = table.c.id != row[0]
        for name in uc_column_names:
            delete_condition &= table.c[name] == row[name]

        rows_to_delete_select = select([table.c.id]).where(delete_condition)
        for row in migrate_engine.execute(rows_to_delete_select).fetchall():
            LOG.info(_("Deleted duplicated row with id: %(id)s from table: "
                       "%(table)s") % dict(id=row[0], table=table_name))

        if use_soft_delete:
            delete_statement = table.update().\
                    where(delete_condition).\
                    values({
                        'deleted': literal_column('id'),
                        'updated_at': literal_column('updated_at'),
                        'deleted_at': timeutils.utcnow()
                    })
        else:
            delete_statement = table.delete().where(delete_condition)
        migrate_engine.execute(delete_statement)
