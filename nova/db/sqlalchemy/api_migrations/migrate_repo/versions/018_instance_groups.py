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
"""API Database migrations for instance_groups"""

from migrate import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    groups = Table('instance_groups', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('uuid', String(length=36), nullable=False),
        Column('name', String(length=255)),
        UniqueConstraint('uuid',
                         name='uniq_instance_groups0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    groups.create(checkfirst=True)

    group_policy = Table('instance_group_policy', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('policy', String(length=255)),
        Column('group_id', Integer, ForeignKey('instance_groups.id'),
               nullable=False),
        Index('instance_group_policy_policy_idx', 'policy'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_policy.create(checkfirst=True)

    group_member = Table('instance_group_member', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(length=255)),
        Column('group_id', Integer, ForeignKey('instance_groups.id'),
               nullable=False),
        Index('instance_group_member_instance_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_member.create(checkfirst=True)
