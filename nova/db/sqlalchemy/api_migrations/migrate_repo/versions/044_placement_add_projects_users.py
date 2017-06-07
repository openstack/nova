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

"""Streamlines consumers table and adds projects and users table"""

from migrate import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table

_INDEXES_TO_REPLACE = (
    'consumers_project_id_uuid_idx',
    'consumers_project_id_user_id_uuid_idx',
)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    projects = Table('projects', meta,
        Column('id', Integer, primary_key=True, nullable=False,
               autoincrement=True),
        Column('external_id', String(length=255), nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        UniqueConstraint('external_id', name='uniq_projects0external_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    projects.create(checkfirst=True)

    users = Table('users', meta,
        Column('id', Integer, primary_key=True, nullable=False,
               autoincrement=True),
        Column('external_id', String(length=255), nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        UniqueConstraint('external_id', name='uniq_users0external_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    users.create(checkfirst=True)

    consumers = Table('consumers', meta, autoload=True)
    project_id_col = consumers.c.project_id
    user_id_col = consumers.c.user_id

    # NOTE(jaypipes): For PostgreSQL, we can't do col.alter(type=Integer)
    # because NVARCHAR and INTEGER are not compatible, so we need to do this
    # manual ALTER TABLE ... USING approach.
    if migrate_engine.name == 'postgresql':
        migrate_engine.execute(
            "ALTER TABLE consumers ALTER COLUMN project_id "
            "TYPE INTEGER USING project_id::integer"
        )
        migrate_engine.execute(
            "ALTER TABLE consumers ALTER COLUMN user_id "
            "TYPE INTEGER USING user_id::integer"
        )
    else:
        project_id_col.alter(type=Integer)
        user_id_col.alter(type=Integer)
