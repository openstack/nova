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

from alembic import command as alembic_api
from alembic import config as alembic_config
from alembic.runtime import migration as alembic_migration
from migrate import exceptions as migrate_exceptions
from migrate.versioning import api as migrate_api
from migrate.versioning import repository as migrate_repository
from oslo_log import log as logging

from nova.db.api import api as api_db_api
from nova.db.main import api as main_db_api
from nova import exception

MIGRATE_INIT_VERSION = {
    'main': 401,
    'api': 66,
}
ALEMBIC_INIT_VERSION = {
    'main': '8f2f1571d55b',
    'api': 'd67eeaabee36',
}

LOG = logging.getLogger(__name__)


def _get_engine(database='main', context=None):
    if database == 'main':
        return main_db_api.get_engine(context=context)

    if database == 'api':
        return api_db_api.get_engine()


def _find_migrate_repo(database='main'):
    """Get the path for the migrate repository."""

    path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)),
        database, 'legacy_migrations')

    return migrate_repository.Repository(path)


def _find_alembic_conf(database='main'):
    """Get the path for the alembic repository."""

    path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)),
        database, 'alembic.ini')

    config = alembic_config.Config(path)
    # we don't want to use the logger configuration from the file, which is
    # only really intended for the CLI
    # https://stackoverflow.com/a/42691781/613428
    config.attributes['configure_logger'] = False
    return config


def _is_database_under_migrate_control(engine, repository):
    try:
        migrate_api.db_version(engine, repository)
        return True
    except migrate_exceptions.DatabaseNotControlledError:
        return False


def _is_database_under_alembic_control(engine):
    with engine.connect() as conn:
        context = alembic_migration.MigrationContext.configure(conn)
        return bool(context.get_current_revision())


def _init_alembic_on_legacy_database(engine, database, repository, config):
    """Init alembic in an existing environment with sqlalchemy-migrate."""
    LOG.info(
        'The database is still under sqlalchemy-migrate control; '
        'applying any remaining sqlalchemy-migrate-based migrations '
        'and fake applying the initial alembic migration'
    )
    migrate_api.upgrade(engine, repository)

    # re-use the connection rather than creating a new one
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        alembic_api.stamp(config, ALEMBIC_INIT_VERSION[database])


def _upgrade_alembic(engine, config, version):
    # re-use the connection rather than creating a new one
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        alembic_api.upgrade(config, version or 'head')


def db_sync(version=None, database='main', context=None):
    """Migrate the database to `version` or the most recent version."""

    if database not in ('main', 'api'):
        raise exception.Invalid('%s is not a valid database' % database)

    # if the user requested a specific version, check if it's an integer:
    # if so, we're almost certainly in sqlalchemy-migrate land and won't
    # support that
    if version is not None and version.isdigit():
        raise exception.Invalid(
            'You requested an sqlalchemy-migrate database version; this is '
            'no longer supported'
        )

    engine = _get_engine(database, context=context)

    repository = _find_migrate_repo(database)
    config = _find_alembic_conf(database)
    # discard the URL stored in alembic.ini in favour of the URL configured
    # for the engine, casting from 'sqlalchemy.engine.url.URL' to str in the
    # process
    # NOTE(sean-k-mooney): the engine has already url encoded the connection
    # string using a mix of url encode styles for different parts of the url.
    # since we are updating the alembic config parser instance we need to
    # escape '%' to '%%' to account for ConfigParser's string interpolation.
    url = str(engine.url).replace('%', '%%')
    config.set_main_option('sqlalchemy.url', url)

    # if we're in a deployment where sqlalchemy-migrate is already present,
    # then apply all the updates for that and fake apply the initial alembic
    # migration; if we're not then 'upgrade' will take care of everything
    # this should be a one-time operation
    if (
        _is_database_under_migrate_control(engine, repository) and
        not _is_database_under_alembic_control(engine)
    ):
        _init_alembic_on_legacy_database(engine, database, repository, config)

    # apply anything later
    LOG.info('Applying migration(s)')

    _upgrade_alembic(engine, config, version)

    LOG.info('Migration(s) applied')


def db_version(database='main', context=None):
    """Display the current database version."""
    if database not in ('main', 'api'):
        raise exception.Invalid('%s is not a valid database' % database)

    repository = _find_migrate_repo(database)
    engine = _get_engine(database, context=context)

    migrate_version = None
    if _is_database_under_migrate_control(engine, repository):
        migrate_version = migrate_api.db_version(engine, repository)

    alembic_version = None
    if _is_database_under_alembic_control(engine):
        with engine.connect() as conn:
            m_context = alembic_migration.MigrationContext.configure(conn)
            alembic_version = m_context.get_current_revision()

    return alembic_version or migrate_version
