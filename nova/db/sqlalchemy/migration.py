# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import os

from migrate import exceptions as versioning_exceptions
from migrate.versioning import api as versioning_api
from migrate.versioning.repository import Repository
from oslo_db.sqlalchemy import utils as db_utils
from oslo_log import log as logging
import sqlalchemy
from sqlalchemy.sql import null

from nova.db.sqlalchemy import api as db_session
from nova import exception
from nova.i18n import _

INIT_VERSION = {}
INIT_VERSION['main'] = 215
INIT_VERSION['api'] = 0
_REPOSITORY = {}

LOG = logging.getLogger(__name__)


def get_engine(database='main', context=None):
    if database == 'main':
        return db_session.get_engine(context=context)
    if database == 'api':
        return db_session.get_api_engine()


def db_sync(version=None, database='main', context=None):
    if version is not None:
        try:
            version = int(version)
        except ValueError:
            raise exception.NovaException(_("version should be an integer"))

    current_version = db_version(database, context=context)
    repository = _find_migrate_repo(database)
    if version is None or version > current_version:
        return versioning_api.upgrade(get_engine(database, context=context),
                repository, version)
    else:
        return versioning_api.downgrade(get_engine(database, context=context),
                repository, version)


def db_version(database='main', context=None):
    repository = _find_migrate_repo(database)

    # NOTE(mdbooth): This is a crude workaround for races in _db_version. The 2
    # races we have seen in practise are:
    # * versioning_api.db_version() fails because the migrate_version table
    #   doesn't exist, but meta.tables subsequently contains tables because
    #   another thread has already started creating the schema. This results in
    #   the 'Essex' error.
    # * db_version_control() fails with pymysql.error.InternalError(1050)
    #   (Create table failed) because of a race in sqlalchemy-migrate's
    #   ControlledSchema._create_table_version, which does:
    #     if not table.exists(): table.create()
    #   This means that it doesn't raise the advertised
    #   DatabaseAlreadyControlledError, which we could have handled explicitly.
    #
    # I believe the correct fix should be:
    # * Delete the Essex-handling code as unnecessary complexity which nobody
    #   should still need.
    # * Fix the races in sqlalchemy-migrate such that version_control() always
    #   raises a well-defined error, and then handle that error here.
    #
    # Until we do that, though, we should be able to just try again if we
    # failed for any reason. In both of the above races, trying again should
    # succeed the second time round.
    #
    # For additional context, see:
    # * https://bugzilla.redhat.com/show_bug.cgi?id=1652287
    # * https://bugs.launchpad.net/nova/+bug/1804652
    try:
        return _db_version(repository, database, context)
    except Exception:
        return _db_version(repository, database, context)


def _db_version(repository, database, context):
    try:
        return versioning_api.db_version(get_engine(database, context=context),
                                         repository)
    except versioning_exceptions.DatabaseNotControlledError as exc:
        meta = sqlalchemy.MetaData()
        engine = get_engine(database, context=context)
        meta.reflect(bind=engine)
        tables = meta.tables
        if len(tables) == 0:
            db_version_control(INIT_VERSION[database],
                               database,
                               context=context)
            return versioning_api.db_version(
                        get_engine(database, context=context), repository)
        else:
            LOG.exception(exc)
            # Some pre-Essex DB's may not be version controlled.
            # Require them to upgrade using Essex first.
            raise exception.NovaException(
                _("Upgrade DB using Essex release first."))


def db_initial_version(database='main'):
    return INIT_VERSION[database]


def _process_null_records(table, col_name, check_fkeys, delete=False):
    """Queries the database and optionally deletes the NULL records.

    :param table: sqlalchemy.Table object.
    :param col_name: The name of the column to check in the table.
    :param check_fkeys: If True, check the table for foreign keys back to the
        instances table and if not found, return.
    :param delete: If true, run a delete operation on the table, else just
        query for number of records that match the NULL column.
    :returns: The number of records processed for the table and column.
    """
    records = 0
    if col_name in table.columns:
        # NOTE(mriedem): filter out tables that don't have a foreign key back
        # to the instances table since they could have stale data even if
        # instances.uuid wasn't NULL.
        if check_fkeys:
            fkey_found = False
            fkeys = table.c[col_name].foreign_keys or []
            for fkey in fkeys:
                if fkey.column.table.name == 'instances':
                    fkey_found = True

            if not fkey_found:
                return 0

        if delete:
            records = table.delete().where(
                table.c[col_name] == null()
            ).execute().rowcount
        else:
            records = len(list(
                table.select().where(table.c[col_name] == null()).execute()
            ))
    return records


def db_null_instance_uuid_scan(delete=False):
    """Scans the database for NULL instance_uuid records.

    :param delete: If true, delete NULL instance_uuid records found, else
                   just query to see if they exist for reporting.
    :returns: dict of table name to number of hits for NULL instance_uuid rows.
    """
    engine = get_engine()
    meta = sqlalchemy.MetaData(bind=engine)
    # NOTE(mriedem): We're going to load up all of the tables so we can find
    # any with an instance_uuid column since those may be foreign keys back
    # to the instances table and we want to cleanup those records first. We
    # have to do this explicitly because the foreign keys in nova aren't
    # defined with cascading deletes.
    meta.reflect(engine)
    # Keep track of all of the tables that had hits in the query.
    processed = {}
    for table in reversed(meta.sorted_tables):
        # Ignore the fixed_ips table by design.
        if table.name not in ('fixed_ips', 'shadow_fixed_ips'):
            processed[table.name] = _process_null_records(
                table, 'instance_uuid', check_fkeys=True, delete=delete)

    # Now process the *instances tables.
    for table_name in ('instances', 'shadow_instances'):
        table = db_utils.get_table(engine, table_name)
        processed[table.name] = _process_null_records(
            table, 'uuid', check_fkeys=False, delete=delete)

    return processed


def db_version_control(version=None, database='main', context=None):
    repository = _find_migrate_repo(database)
    versioning_api.version_control(get_engine(database, context=context),
                                   repository,
                                   version)
    return version


def _find_migrate_repo(database='main'):
    """Get the path for the migrate repository."""
    global _REPOSITORY
    rel_path = 'migrate_repo'
    if database == 'api':
        rel_path = os.path.join('api_migrations', 'migrate_repo')
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        rel_path)
    assert os.path.exists(path)
    if _REPOSITORY.get(database) is None:
        _REPOSITORY[database] = Repository(path)
    return _REPOSITORY[database]
