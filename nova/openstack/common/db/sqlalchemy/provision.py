# Copyright 2013 Mirantis.inc
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

"""Provision test environment for specific DB backends"""

import argparse
import logging
import os
import random
import string

from six import moves
import sqlalchemy

from nova.openstack.common.db import exception as exc


LOG = logging.getLogger(__name__)


def get_engine(uri):
    """Engine creation

    Call the function without arguments to get admin connection. Admin
    connection required to create temporary user and database for each
    particular test. Otherwise use existing connection to recreate connection
    to the temporary database.
    """
    return sqlalchemy.create_engine(uri, poolclass=sqlalchemy.pool.NullPool)


def _execute_sql(engine, sql, driver):
    """Initialize connection, execute sql query and close it."""
    try:
        with engine.connect() as conn:
            if driver == 'postgresql':
                conn.connection.set_isolation_level(0)
            for s in sql:
                conn.execute(s)
    except sqlalchemy.exc.OperationalError:
        msg = ('%s does not match database admin '
               'credentials or database does not exist.')
        LOG.exception(msg % engine.url)
        raise exc.DBConnectionError(msg % engine.url)


def create_database(engine):
    """Provide temporary user and database for each particular test."""
    driver = engine.name

    auth = {
        'database': ''.join(random.choice(string.ascii_lowercase)
                            for i in moves.range(10)),
        'user': engine.url.username,
        'passwd': engine.url.password,
    }

    sqls = [
        "drop database if exists %(database)s;",
        "create database %(database)s;"
    ]

    if driver == 'sqlite':
        return 'sqlite:////tmp/%s' % auth['database']
    elif driver in ['mysql', 'postgresql']:
        sql_query = map(lambda x: x % auth, sqls)
        _execute_sql(engine, sql_query, driver)
    else:
        raise ValueError('Unsupported RDBMS %s' % driver)

    params = auth.copy()
    params['backend'] = driver
    return "%(backend)s://%(user)s:%(passwd)s@localhost/%(database)s" % params


def drop_database(admin_engine, current_uri):
    """Drop temporary database and user after each particular test."""

    engine = get_engine(current_uri)
    driver = engine.name
    auth = {'database': engine.url.database, 'user': engine.url.username}

    if driver == 'sqlite':
        try:
            os.remove(auth['database'])
        except OSError:
            pass
    elif driver in ['mysql', 'postgresql']:
        sql = "drop database if exists %(database)s;"
        _execute_sql(admin_engine, [sql % auth], driver)
    else:
        raise ValueError('Unsupported RDBMS %s' % driver)


def main():
    """Controller to handle commands

    ::create: Create test user and database with random names.
    ::drop: Drop user and database created by previous command.
    """
    parser = argparse.ArgumentParser(
        description='Controller to handle database creation and dropping'
        ' commands.',
        epilog='Under normal circumstances is not used directly.'
        ' Used in .testr.conf to automate test database creation'
        ' and dropping processes.')
    subparsers = parser.add_subparsers(
        help='Subcommands to manipulate temporary test databases.')

    create = subparsers.add_parser(
        'create',
        help='Create temporary test '
        'databases and users.')
    create.set_defaults(which='create')
    create.add_argument(
        'instances_count',
        type=int,
        help='Number of databases to create.')

    drop = subparsers.add_parser(
        'drop',
        help='Drop temporary test databases and users.')
    drop.set_defaults(which='drop')
    drop.add_argument(
        'instances',
        nargs='+',
        help='List of databases uri to be dropped.')

    args = parser.parse_args()

    connection_string = os.getenv('OS_TEST_DBAPI_ADMIN_CONNECTION',
                                  'sqlite://')
    engine = get_engine(connection_string)
    which = args.which

    if which == "create":
        for i in range(int(args.instances_count)):
            print(create_database(engine))
    elif which == "drop":
        for db in args.instances:
            drop_database(engine, db)


if __name__ == "__main__":
    main()
