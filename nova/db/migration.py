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
from oslo_log import log as logging
import sqlalchemy

from nova.db.api import api as api_db_api
from nova.db.main import api as main_db_api
from nova import exception
from nova.i18n import _

INIT_VERSION = {}
INIT_VERSION['main'] = 401
INIT_VERSION['api'] = 66
_REPOSITORY = {}

LOG = logging.getLogger(__name__)


def get_engine(database='main', context=None):
    if database == 'main':
        return main_db_api.get_engine(context=context)

    if database == 'api':
        return api_db_api.get_engine()


def find_migrate_repo(database='main'):
    """Get the path for the migrate repository."""
    global _REPOSITORY
    rel_path = os.path.join(database, 'legacy_migrations')
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)), rel_path)
    assert os.path.exists(path)
    if _REPOSITORY.get(database) is None:
        _REPOSITORY[database] = Repository(path)
    return _REPOSITORY[database]


def db_sync(version=None, database='main', context=None):
    """Migrate the database to `version` or the most recent version."""
    if version is not None:
        try:
            version = int(version)
        except ValueError:
            raise exception.NovaException(_("version should be an integer"))

    current_version = db_version(database, context=context)
    repository = find_migrate_repo(database)
    engine = get_engine(database, context=context)
    if version is None or version > current_version:
        return versioning_api.upgrade(engine, repository, version)
    else:
        return versioning_api.downgrade(engine, repository, version)


def db_version(database='main', context=None):
    """Display the current database version."""
    repository = find_migrate_repo(database)

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
    engine = get_engine(database, context=context)
    try:
        return versioning_api.db_version(engine, repository)
    except versioning_exceptions.DatabaseNotControlledError as exc:
        meta = sqlalchemy.MetaData()
        meta.reflect(bind=engine)
        tables = meta.tables
        if len(tables) == 0:
            db_version_control(
                INIT_VERSION[database], database, context=context)
            return versioning_api.db_version(engine, repository)
        else:
            LOG.exception(exc)
            # Some pre-Essex DB's may not be version controlled.
            # Require them to upgrade using Essex first.
            raise exception.NovaException(
                _("Upgrade DB using Essex release first."))


def db_initial_version(database='main'):
    """The starting version for the database."""
    return INIT_VERSION[database]


def db_version_control(version=None, database='main', context=None):
    repository = find_migrate_repo(database)
    engine = get_engine(database, context=context)
    versioning_api.version_control(engine, repository, version)
    return version
