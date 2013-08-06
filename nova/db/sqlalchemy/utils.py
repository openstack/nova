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

import re

from migrate.changeset import UniqueConstraint, ForeignKeyConstraint
from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy.engine import reflection
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import func
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import schema
from sqlalchemy.sql.expression import literal_column
from sqlalchemy.sql.expression import UpdateBase
from sqlalchemy.sql import select
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy.types import NullType

from nova.db.sqlalchemy import api as db
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)


def get_table(engine, name):
    """Returns an sqlalchemy table dynamically from db.

    Needed because the models don't work for us in migrations
    as models will be far out of sync with the current data.
    """
    metadata = MetaData()
    metadata.bind = engine
    return Table(name, metadata, autoload=True)


class InsertFromSelect(UpdateBase):
    def __init__(self, table, select):
        self.table = table
        self.select = select


@compiles(InsertFromSelect)
def visit_insert_from_select(element, compiler, **kw):
    return "INSERT INTO %s %s" % (
        compiler.process(element.table, asfrom=True),
        compiler.process(element.select))


def _get_not_supported_column(col_name_col_instance, column_name):
    try:
        column = col_name_col_instance[column_name]
    except Exception:
        msg = _("Please specify column %s in col_name_col_instance "
                "param. It is required because column has unsupported "
                "type by sqlite).")
        raise exception.NovaException(msg % column_name)

    if not isinstance(column, Column):
        msg = _("col_name_col_instance param has wrong type of "
                "column instance for column %s It should be instance "
                "of sqlalchemy.Column.")
        raise exception.NovaException(msg % column_name)
    return column


def _get_unique_constraints_in_sqlite(migrate_engine, table_name):
    regexp = "CONSTRAINT (\w+) UNIQUE \(([^\)]+)\)"

    meta = MetaData(bind=migrate_engine)
    table = Table(table_name, meta, autoload=True)

    sql_data = migrate_engine.execute(
        """
            SELECT sql
            FROM
                sqlite_master
            WHERE
                type = 'table' AND
                name = :table_name;
        """,
        table_name=table_name
    ).fetchone()[0]

    uniques = set([
        schema.UniqueConstraint(
            *[getattr(table.c, c.strip(' "'))
              for c in cols.split(",")], name=name
        )
        for name, cols in re.findall(regexp, sql_data)
    ])

    return uniques


def _drop_unique_constraint_in_sqlite(migrate_engine, table_name, uc_name,
                                      **col_name_col_instance):
    insp = reflection.Inspector.from_engine(migrate_engine)
    meta = MetaData(bind=migrate_engine)

    table = Table(table_name, meta, autoload=True)
    columns = []
    for column in table.columns:
        if isinstance(column.type, NullType):
            new_column = _get_not_supported_column(col_name_col_instance,
                                                   column.name)
            columns.append(new_column)
        else:
            columns.append(column.copy())

    uniques = _get_unique_constraints_in_sqlite(migrate_engine, table_name)
    table.constraints.update(uniques)

    constraints = [constraint for constraint in table.constraints
                    if not constraint.name == uc_name and
                    not isinstance(constraint, schema.ForeignKeyConstraint)]

    new_table = Table(table_name + "__tmp__", meta, *(columns + constraints))
    new_table.create()

    indexes = []
    for index in insp.get_indexes(table_name):
        column_names = [new_table.c[c] for c in index['column_names']]
        indexes.append(Index(index["name"],
                             *column_names,
                             unique=index["unique"]))
    f_keys = []
    for fk in insp.get_foreign_keys(table_name):
        refcolumns = [fk['referred_table'] + '.' + col
                      for col in fk['referred_columns']]
        f_keys.append(ForeignKeyConstraint(fk['constrained_columns'],
                      refcolumns, table=new_table, name=fk['name']))

    ins = InsertFromSelect(new_table, table.select())
    migrate_engine.execute(ins)
    table.drop()

    [index.create(migrate_engine) for index in indexes]
    for fkey in f_keys:
        fkey.create()
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
    if migrate_engine.name == "sqlite":
        _drop_unique_constraint_in_sqlite(migrate_engine, table_name, uc_name,
                                          **col_name_col_instance)
    else:
        meta = MetaData()
        meta.bind = migrate_engine
        t = Table(table_name, meta, autoload=True)
        uc = UniqueConstraint(*columns, table=t, name=uc_name)
        uc.drop()


def drop_old_duplicate_entries_from_table(migrate_engine, table_name,
                                          use_soft_delete, *uc_column_names):
    """
    This method is used to drop all old rows that have the same values for
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


def check_shadow_table(migrate_engine, table_name):
    """
    This method checks that table with ``table_name`` and corresponding shadow
    table have same columns.
    """
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table(table_name, meta, autoload=True)
    shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, meta,
                         autoload=True)

    columns = dict([(c.name, c) for c in table.columns])
    shadow_columns = dict([(c.name, c) for c in shadow_table.columns])

    for name, column in columns.iteritems():
        if name not in shadow_columns:
            raise exception.NovaException(
                _("Missing column %(table)s.%(column)s in shadow table")
                        % {'column': name, 'table': shadow_table.name})
        shadow_column = shadow_columns[name]

        if not isinstance(shadow_column.type, type(column.type)):
            raise exception.NovaException(
                _("Different types in %(table)s.%(column)s and shadow table: "
                  "%(c_type)s %(shadow_c_type)s")
                        % {'column': name, 'table': table.name,
                           'c_type': column.type,
                           'shadow_c_type': shadow_column.type})

    for name, column in shadow_columns.iteritems():
        if name not in columns:
            raise exception.NovaException(
                _("Extra column %(table)s.%(column)s in shadow table")
                        % {'column': name, 'table': shadow_table.name})
    return True


def create_shadow_table(migrate_engine, table_name=None, table=None,
                        **col_name_col_instance):
    """
    This method create shadow table for table with name ``table_name`` or table
    instance ``table``.
    :param table_name: Autoload table with this name and create shadow table
    :param table: Autoloaded table, so just create corresponding shadow table.
    :param col_name_col_instance:   contains pair column_name=column_instance.
                            column_instance is instance of Column. These params
                            are required only for columns that have unsupported
                            types by sqlite. For example BigInteger.
    """
    meta = MetaData(bind=migrate_engine)

    if table_name is None and table is None:
        raise exception.NovaException(_("Specify `table_name` or `table` "
                                        "param"))
    if not (table_name is None or table is None):
        raise exception.NovaException(_("Specify only one param `table_name` "
                                        "`table`"))

    if table is None:
        table = Table(table_name, meta, autoload=True)

    columns = []
    for column in table.columns:
        if isinstance(column.type, NullType):
            new_column = _get_not_supported_column(col_name_col_instance,
                                                   column.name)
            columns.append(new_column)
        else:
            columns.append(column.copy())

    shadow_table_name = db._SHADOW_TABLE_PREFIX + table.name
    shadow_table = Table(shadow_table_name, meta, *columns,
                         mysql_engine='InnoDB')
    try:
        shadow_table.create()
    except (OperationalError, ProgrammingError):
        LOG.info(repr(shadow_table))
        LOG.exception(_('Exception while creating table.'))
        raise exception.ShadowTableExists(name=shadow_table_name)
    except Exception:
        LOG.info(repr(shadow_table))
        LOG.exception(_('Exception while creating table.'))


def _get_default_deleted_value(table):
    if isinstance(table.c.id.type, Integer):
        return 0
    if isinstance(table.c.id.type, String):
        return ""
    raise exception.NovaException(_("Unsupported id columns type"))


def _restore_indexes_on_deleted_columns(migrate_engine, table_name, indexes):
    table = get_table(migrate_engine, table_name)

    insp = reflection.Inspector.from_engine(migrate_engine)
    real_indexes = insp.get_indexes(table_name)
    existing_index_names = dict([(index['name'], index['column_names'])
                                  for index in real_indexes])

    # NOTE(boris-42): Restore indexes on `deleted` column
    for index in indexes:
        if 'deleted' not in index['column_names']:
            continue
        name = index['name']
        if name in existing_index_names:
            column_names = [table.c[c] for c in existing_index_names[name]]
            old_index = Index(name, *column_names, unique=index["unique"])
            old_index.drop(migrate_engine)

        column_names = [table.c[c] for c in index['column_names']]
        new_index = Index(index["name"], *column_names, unique=index["unique"])
        new_index.create(migrate_engine)


def change_deleted_column_type_to_boolean(migrate_engine, table_name,
                                          **col_name_col_instance):
    if migrate_engine.name == "sqlite":
        return _change_deleted_column_type_to_boolean_sqlite(migrate_engine,
                                                    table_name,
                                                    **col_name_col_instance)
    insp = reflection.Inspector.from_engine(migrate_engine)
    indexes = insp.get_indexes(table_name)

    table = get_table(migrate_engine, table_name)

    old_deleted = Column('old_deleted', Boolean, default=False)
    old_deleted.create(table, populate_default=False)

    table.update().\
            where(table.c.deleted == table.c.id).\
            values(old_deleted=True).\
            execute()

    table.c.deleted.drop()
    table.c.old_deleted.alter(name="deleted")

    _restore_indexes_on_deleted_columns(migrate_engine, table_name, indexes)


def _change_deleted_column_type_to_boolean_sqlite(migrate_engine, table_name,
                                                  **col_name_col_instance):
    insp = reflection.Inspector.from_engine(migrate_engine)
    table = get_table(migrate_engine, table_name)

    columns = []
    for column in table.columns:
        column_copy = None
        if column.name != "deleted":
            if isinstance(column.type, NullType):
                column_copy = _get_not_supported_column(col_name_col_instance,
                                                        column.name)
            else:
                column_copy = column.copy()
        else:
            column_copy = Column('deleted', Boolean, default=0)
        columns.append(column_copy)

    constraints = [constraint.copy() for constraint in table.constraints]

    meta = MetaData(bind=migrate_engine)
    new_table = Table(table_name + "__tmp__", meta,
                      *(columns + constraints))
    new_table.create()

    indexes = []
    for index in insp.get_indexes(table_name):
        column_names = [new_table.c[c] for c in index['column_names']]
        indexes.append(Index(index["name"], *column_names,
                             unique=index["unique"]))

    c_select = []
    for c in table.c:
        if c.name != "deleted":
            c_select.append(c)
        else:
            c_select.append(table.c.deleted == table.c.id)

    ins = InsertFromSelect(new_table, select(c_select))
    migrate_engine.execute(ins)

    table.drop()
    [index.create(migrate_engine) for index in indexes]

    new_table.rename(table_name)
    new_table.update().\
        where(new_table.c.deleted == new_table.c.id).\
        values(deleted=True).\
        execute()


def change_deleted_column_type_to_id_type(migrate_engine, table_name,
                                          **col_name_col_instance):
    if migrate_engine.name == "sqlite":
        return _change_deleted_column_type_to_id_type_sqlite(migrate_engine,
                                                    table_name,
                                                    **col_name_col_instance)
    insp = reflection.Inspector.from_engine(migrate_engine)
    indexes = insp.get_indexes(table_name)

    table = get_table(migrate_engine, table_name)

    new_deleted = Column('new_deleted', table.c.id.type,
                         default=_get_default_deleted_value(table))
    new_deleted.create(table, populate_default=True)

    table.update().\
            where(table.c.deleted == True).\
            values(new_deleted=table.c.id).\
            execute()
    table.c.deleted.drop()
    table.c.new_deleted.alter(name="deleted")

    _restore_indexes_on_deleted_columns(migrate_engine, table_name, indexes)


def _change_deleted_column_type_to_id_type_sqlite(migrate_engine, table_name,
                                                  **col_name_col_instance):
    # NOTE(boris-42): sqlaclhemy-migrate can't drop column with check
    #                 constraints in sqlite DB and our `deleted` column has
    #                 2 check constraints. So there is only one way to remove
    #                 these constraints:
    #                 1) Create new table with the same columns, constraints
    #                 and indexes. (except deleted column).
    #                 2) Copy all data from old to new table.
    #                 3) Drop old table.
    #                 4) Rename new table to old table name.
    insp = reflection.Inspector.from_engine(migrate_engine)
    meta = MetaData(bind=migrate_engine)
    table = Table(table_name, meta, autoload=True)
    default_deleted_value = _get_default_deleted_value(table)

    columns = []
    for column in table.columns:
        column_copy = None
        if column.name != "deleted":
            if isinstance(column.type, NullType):
                column_copy = _get_not_supported_column(col_name_col_instance,
                                                        column.name)
            else:
                column_copy = column.copy()
        else:
            column_copy = Column('deleted', table.c.id.type,
                                 default=default_deleted_value)
        columns.append(column_copy)

    def is_deleted_column_constraint(constraint):
        # NOTE(boris-42): There is no other way to check is CheckConstraint
        #                 associated with deleted column.
        if not isinstance(constraint, CheckConstraint):
            return False
        sqltext = str(constraint.sqltext)
        return (sqltext.endswith("deleted in (0, 1)") or
                sqltext.endswith("deleted IN (:deleted_1, :deleted_2)"))

    constraints = []
    for constraint in table.constraints:
        if not is_deleted_column_constraint(constraint):
            constraints.append(constraint.copy())

    new_table = Table(table_name + "__tmp__", meta,
                      *(columns + constraints))
    new_table.create()

    indexes = []
    for index in insp.get_indexes(table_name):
        column_names = [new_table.c[c] for c in index['column_names']]
        indexes.append(Index(index["name"], *column_names,
                             unique=index["unique"]))

    ins = InsertFromSelect(new_table, table.select())
    migrate_engine.execute(ins)

    table.drop()
    [index.create(migrate_engine) for index in indexes]

    new_table.rename(table_name)
    new_table.update().\
        where(new_table.c.deleted == True).\
        values(deleted=new_table.c.id).\
        execute()

    # NOTE(boris-42): Fix value of deleted column: False -> "" or 0.
    new_table.update().\
        where(new_table.c.deleted == False).\
        values(deleted=default_deleted_value).\
        execute()


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
    Index(
        index_name,
        *[getattr(table.c, col) for col in old_columns]
    ).drop(migrate_engine)

    Index(
        index_name,
        *[getattr(table.c, col) for col in new_columns]
    ).create()


def modify_indexes(migrate_engine, data, upgrade=True):
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
