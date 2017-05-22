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

from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import utils as oslodbutils
from oslo_log import log as logging
from sqlalchemy.exc import OperationalError
from sqlalchemy import MetaData
from sqlalchemy import Table
from sqlalchemy.types import NullType

from nova.db.sqlalchemy import api as db
from nova import exception
from nova.i18n import _


LOG = logging.getLogger(__name__)


def check_shadow_table(migrate_engine, table_name):
    """This method checks that table with ``table_name`` and
    corresponding shadow table have same columns.
    """
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table(table_name, meta, autoload=True)
    shadow_table = Table(db._SHADOW_TABLE_PREFIX + table_name, meta,
                         autoload=True)

    columns = {c.name: c for c in table.columns}
    shadow_columns = {c.name: c for c in shadow_table.columns}

    for name, column in columns.items():
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

    for name, column in shadow_columns.items():
        if name not in columns:
            raise exception.NovaException(
                _("Extra column %(table)s.%(column)s in shadow table")
                        % {'column': name, 'table': shadow_table.name})
    return True


def create_shadow_table(migrate_engine, table_name=None, table=None,
                        **col_name_col_instance):
    """This method create shadow table for table with name ``table_name``
    or table instance ``table``.
    :param table_name: Autoload table with this name and create shadow table
    :param table: Autoloaded table, so just create corresponding shadow table.
    :param col_name_col_instance:   contains pair column_name=column_instance.
    column_instance is instance of Column. These params are required only for
    columns that have unsupported types by sqlite. For example BigInteger.
    :returns: The created shadow_table object.
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
            new_column = oslodbutils._get_not_supported_column(
                col_name_col_instance, column.name)
            columns.append(new_column)
        else:
            columns.append(column.copy())

    shadow_table_name = db._SHADOW_TABLE_PREFIX + table.name
    shadow_table = Table(shadow_table_name, meta, *columns,
                         mysql_engine='InnoDB')
    try:
        shadow_table.create()
        return shadow_table
    except (db_exc.DBError, OperationalError):
        # NOTE(ekudryashova): At the moment there is a case in oslo.db code,
        # which raises unwrapped OperationalError, so we should catch it until
        # oslo.db would wraps all such exceptions
        LOG.info(repr(shadow_table))
        LOG.exception('Exception while creating table.')
        raise exception.ShadowTableExists(name=shadow_table_name)
    except Exception:
        LOG.info(repr(shadow_table))
        LOG.exception('Exception while creating table.')
