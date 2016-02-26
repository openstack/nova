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

from migrate.changeset.constraint import ForeignKeyConstraint
from migrate import UniqueConstraint
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import dialects
from sqlalchemy import Enum
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text


def InetSmall():
    return String(length=39).with_variant(dialects.postgresql.INET(),
                  'postgresql')


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    request_specs = Table('request_specs', meta, autoload=True)
    build_requests = Table('build_requests', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('request_spec_id', Integer, nullable=False),
        Column('project_id', String(length=255), nullable=False),
        Column('user_id', String(length=255), nullable=False),
        Column('display_name', String(length=255)),
        Column('instance_metadata', Text),
        Column('progress', Integer),
        Column('vm_state', String(length=255)),
        Column('task_state', String(length=255)),
        Column('image_ref', String(length=255)),
        Column('access_ip_v4', InetSmall()),
        Column('access_ip_v6', InetSmall()),
        Column('info_cache', Text),
        Column('security_groups', Text, nullable=False),
        Column('config_drive', Boolean, default=False, nullable=False),
        Column('key_name', String(length=255)),
        Column('locked_by', Enum('owner', 'admin',
            name='build_requests0locked_by')),
        UniqueConstraint('request_spec_id',
            name='uniq_build_requests0request_spec_id'),
        Index('build_requests_project_id_idx', 'project_id'),
        ForeignKeyConstraint(columns=['request_spec_id'],
            refcolumns=[request_specs.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    build_requests.create(checkfirst=True)
