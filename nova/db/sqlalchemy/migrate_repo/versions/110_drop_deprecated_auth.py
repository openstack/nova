# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from migrate import ForeignKeyConstraint
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey,
                        Index, MetaData, String, Table)

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    tables = (
        "user_project_role_association",
        "user_project_association",
        "user_role_association",
        "projects",
        "users",
        "auth_tokens",
    )
    for table_name in tables:
        Table(table_name, meta, autoload=True).drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    auth_tokens = Table('auth_tokens', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('token_hash', String(length=255), primary_key=True,
               nullable=False),
        Column('user_id', String(length=255)),
        Column('server_management_url', String(length=255)),
        Column('storage_url', String(length=255)),
        Column('cdn_management_url', String(length=255)),
        mysql_engine='InnoDB',
    )

    projects = Table('projects', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('description', String(length=255)),
        Column('project_manager', String(length=255), ForeignKey('users.id')),
        mysql_engine='InnoDB',
    )

    user_project_association = Table('user_project_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('user_id', String(length=255), primary_key=True,
               nullable=False),
        Column('project_id', String(length=255), primary_key=True,
               nullable=False),
        mysql_engine='InnoDB',
    )

    user_project_role_association = \
        Table('user_project_role_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('user_id', String(length=255), primary_key=True,
               nullable=False),
        Column('project_id', String(length=255), primary_key=True,
               nullable=False),
        Column('role', String(length=255), primary_key=True, nullable=False),
        mysql_engine='InnoDB',
    )

    user_role_association = Table('user_role_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('user_id', String(length=255), ForeignKey('users.id'),
               primary_key=True, nullable=False),
        Column('role', String(length=255), primary_key=True, nullable=False),
        mysql_engine='InnoDB',
    )

    users = Table('users', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('access_key', String(length=255)),
        Column('secret_key', String(length=255)),
        Column('is_admin', Boolean),
        mysql_engine='InnoDB',
    )

    tables = [users, projects, user_project_association,
              auth_tokens, user_project_role_association,
              user_role_association]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.exception('Exception while creating table.')
            raise

    if migrate_engine.name == 'mysql':
        index = Index('project_id', user_project_association.c.project_id)
        index.create(migrate_engine)

    fkeys = [
        [
            [user_project_role_association.c.user_id,
             user_project_role_association.c.project_id],
            [user_project_association.c.user_id,
             user_project_association.c.project_id],
            'user_project_role_association_ibfk_1',
        ],
        [
            [user_project_association.c.user_id],
            [users.c.id],
            'user_project_association_ibfk_1',
        ],
        [
            [user_project_association.c.project_id],
            [projects.c.id],
            'user_project_association_ibfk_2',
        ],
    ]

    for fkey_pair in fkeys:
        if migrate_engine.name == 'mysql':
            # For MySQL we name our fkeys explicitly so they match Essex
            fkey = ForeignKeyConstraint(columns=fkey_pair[0],
                                   refcolumns=fkey_pair[1],
                                   name=fkey_pair[2])
            fkey.create()
        elif migrate_engine.name == 'postgresql':
            fkey = ForeignKeyConstraint(columns=fkey_pair[0],
                                   refcolumns=fkey_pair[1])
            fkey.create()

    # Hopefully this entire loop to set the charset can go away during
    # the "E" release compaction. See the notes on the dns_domains
    # table above for why this is required vs. setting mysql_charset inline.
    if migrate_engine.name == "mysql":
        tables = [
            # tables that are FK parents, must be converted early
            "projects",
            "user_project_association",
            "users",
            # those that are children and others later
            "auth_tokens",
            "user_project_role_association",
            "user_role_association",
        ]
        sql = "SET foreign_key_checks = 0;"
        for table in tables:
            sql += "ALTER TABLE %s CONVERT TO CHARACTER SET utf8;" % table
        sql += "SET foreign_key_checks = 1;"
        sql += "ALTER DATABASE %s DEFAULT CHARACTER SET utf8;" \
            % migrate_engine.url.database
        migrate_engine.execute(sql)
