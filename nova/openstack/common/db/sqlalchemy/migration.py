# coding: utf-8
#
# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
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
#
# Base on code in migrate/changeset/databases/sqlite.py which is under
# the following license:
#
# The MIT License
#
# Copyright (c) 2009 Evan Rosson, Jan Dittberner, Domen Kožar
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import os
import re

from migrate.changeset import ansisql
from migrate.changeset.databases import sqlite
from migrate import exceptions as versioning_exceptions
from migrate.versioning import api as versioning_api
from migrate.versioning.repository import Repository
import sqlalchemy
from sqlalchemy.schema import UniqueConstraint

from nova.openstack.common.db import exception
from nova.openstack.common.db.sqlalchemy import session as db_session
from nova.openstack.common.gettextutils import _


get_engine = db_session.get_engine


def _get_unique_constraints(self, table):
    """Retrieve information about existing unique constraints of the table

    This feature is needed for _recreate_table() to work properly.
    Unfortunately, it's not available in sqlalchemy 0.7.x/0.8.x.

    """

    data = table.metadata.bind.execute(
        """SELECT sql
           FROM sqlite_master
           WHERE
               type='table' AND
               name=:table_name""",
        table_name=table.name
    ).fetchone()[0]

    UNIQUE_PATTERN = "CONSTRAINT (\w+) UNIQUE \(([^\)]+)\)"
    return [
        UniqueConstraint(
            *[getattr(table.columns, c.strip(' "')) for c in cols.split(",")],
            name=name
        )
        for name, cols in re.findall(UNIQUE_PATTERN, data)
    ]


def _recreate_table(self, table, column=None, delta=None, omit_uniques=None):
    """Recreate the table properly

    Unlike the corresponding original method of sqlalchemy-migrate this one
    doesn't drop existing unique constraints when creating a new one.

    """

    table_name = self.preparer.format_table(table)

    # we remove all indexes so as not to have
    # problems during copy and re-create
    for index in table.indexes:
        index.drop()

    # reflect existing unique constraints
    for uc in self._get_unique_constraints(table):
        table.append_constraint(uc)
    # omit given unique constraints when creating a new table if required
    table.constraints = set([
        cons for cons in table.constraints
        if omit_uniques is None or cons.name not in omit_uniques
    ])

    self.append('ALTER TABLE %s RENAME TO migration_tmp' % table_name)
    self.execute()

    insertion_string = self._modify_table(table, column, delta)

    table.create(bind=self.connection)
    self.append(insertion_string % {'table_name': table_name})
    self.execute()
    self.append('DROP TABLE migration_tmp')
    self.execute()


def _visit_migrate_unique_constraint(self, *p, **k):
    """Drop the given unique constraint

    The corresponding original method of sqlalchemy-migrate just
    raises NotImplemented error

    """

    self.recreate_table(p[0].table, omit_uniques=[p[0].name])


def patch_migrate():
    """A workaround for SQLite's inability to alter things

    SQLite abilities to alter tables are very limited (please read
    http://www.sqlite.org/lang_altertable.html for more details).
    E. g. one can't drop a column or a constraint in SQLite. The
    workaround for this is to recreate the original table omitting
    the corresponding constraint (or column).

    sqlalchemy-migrate library has recreate_table() method that
    implements this workaround, but it does it wrong:

        - information about unique constraints of a table
          is not retrieved. So if you have a table with one
          unique constraint and a migration adding another one
          you will end up with a table that has only the
          latter unique constraint, and the former will be lost

        - dropping of unique constraints is not supported at all

    The proper way to fix this is to provide a pull-request to
    sqlalchemy-migrate, but the project seems to be dead. So we
    can go on with monkey-patching of the lib at least for now.

    """

    # this patch is needed to ensure that recreate_table() doesn't drop
    # existing unique constraints of the table when creating a new one
    helper_cls = sqlite.SQLiteHelper
    helper_cls.recreate_table = _recreate_table
    helper_cls._get_unique_constraints = _get_unique_constraints

    # this patch is needed to be able to drop existing unique constraints
    constraint_cls = sqlite.SQLiteConstraintDropper
    constraint_cls.visit_migrate_unique_constraint = \
        _visit_migrate_unique_constraint
    constraint_cls.__bases__ = (ansisql.ANSIColumnDropper,
                                sqlite.SQLiteConstraintGenerator)


def db_sync(abs_path, version=None, init_version=0):
    """Upgrade or downgrade a database.

    Function runs the upgrade() or downgrade() functions in change scripts.

    :param abs_path:     Absolute path to migrate repository.
    :param version:      Database will upgrade/downgrade until this version.
                         If None - database will update to the latest
                         available version.
    :param init_version: Initial database version
    """
    if version is not None:
        try:
            version = int(version)
        except ValueError:
            raise exception.DbMigrationError(
                message=_("version should be an integer"))

    current_version = db_version(abs_path, init_version)
    repository = _find_migrate_repo(abs_path)
    _db_schema_sanity_check()
    if version is None or version > current_version:
        return versioning_api.upgrade(get_engine(), repository, version)
    else:
        return versioning_api.downgrade(get_engine(), repository,
                                        version)


def _db_schema_sanity_check():
    engine = get_engine()
    if engine.name == 'mysql':
        onlyutf8_sql = ('SELECT TABLE_NAME,TABLE_COLLATION '
                        'from information_schema.TABLES '
                        'where TABLE_SCHEMA=%s and '
                        'TABLE_COLLATION NOT LIKE "%%utf8%%"')

        table_names = [res[0] for res in engine.execute(onlyutf8_sql,
                                                        engine.url.database)]
        if len(table_names) > 0:
            raise ValueError(_('Tables "%s" have non utf8 collation, '
                               'please make sure all tables are CHARSET=utf8'
                               ) % ','.join(table_names))


def db_version(abs_path, init_version):
    """Show the current version of the repository.

    :param abs_path: Absolute path to migrate repository
    :param version:  Initial database version
    """
    repository = _find_migrate_repo(abs_path)
    try:
        return versioning_api.db_version(get_engine(), repository)
    except versioning_exceptions.DatabaseNotControlledError:
        meta = sqlalchemy.MetaData()
        engine = get_engine()
        meta.reflect(bind=engine)
        tables = meta.tables
        if len(tables) == 0 or 'alembic_version' in tables:
            db_version_control(abs_path, init_version)
            return versioning_api.db_version(get_engine(), repository)
        else:
            raise exception.DbMigrationError(
                message=_(
                    "The database is not under version control, but has "
                    "tables. Please stamp the current version of the schema "
                    "manually."))


def db_version_control(abs_path, version=None):
    """Mark a database as under this repository's version control.

    Once a database is under version control, schema changes should
    only be done via change scripts in this repository.

    :param abs_path: Absolute path to migrate repository
    :param version:  Initial database version
    """
    repository = _find_migrate_repo(abs_path)
    versioning_api.version_control(get_engine(), repository, version)
    return version


def _find_migrate_repo(abs_path):
    """Get the project's change script repository

    :param abs_path: Absolute path to migrate repository
    """
    if not os.path.exists(abs_path):
        raise exception.DbMigrationError("Path %s not found" % abs_path)
    return Repository(abs_path)
