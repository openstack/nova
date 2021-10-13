# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from nova.db.api import models

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging unless we're told not to.
# This line sets up loggers basically.
if config.attributes.get('configure_logger', True):
    fileConfig(config.config_file_name)

# this is the MetaData object for the various models in the API database
target_metadata = models.BASE.metadata


def include_name(name, type_, parent_names):
    """Determine which tables or columns to skip.

    This is used when we decide to "delete" a table or column. In this
    instance, we will remove the SQLAlchemy model or field but leave the
    underlying database table or column in place for a number of releases
    after. Once we're sure that there is no code running that contains
    references to the old models, we can then remove the underlying table. In
    the interim, we must track the discrepancy between models and actual
    database data here.
    """
    if type_ == 'table':
        return name not in models.REMOVED_TABLES

    if type_ == 'column':
        return (parent_names['table_name'], name) not in models.REMOVED_COLUMNS

    return True


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine, though an
    Engine is acceptable here as well.  By skipping the Engine creation we
    don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_name=include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a connection
    with the context.

    This is modified from the default based on the below, since we want to
    share an engine when unit testing so in-memory database testing actually
    works.

    https://alembic.sqlalchemy.org/en/latest/cookbook.html#connection-sharing
    """
    connectable = config.attributes.get('connection', None)

    if connectable is None:
        # only create Engine if we don't have a Connection from the outside
        connectable = engine_from_config(
            config.get_section(config.config_ini_section),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    # when connectable is already a Connection object, calling connect() gives
    # us a *branched connection*.

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_name=include_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
