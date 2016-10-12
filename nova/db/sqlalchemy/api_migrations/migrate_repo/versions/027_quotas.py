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
"""API Database migrations for quotas"""

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

    quota_classes = Table('quota_classes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('class_name', String(length=255)),
        Column('resource', String(length=255)),
        Column('hard_limit', Integer),
        Index('quota_classes_class_name_idx', 'class_name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_classes.create(checkfirst=True)

    quota_usages = Table('quota_usages', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255), nullable=False),
        Column('in_use', Integer, nullable=False),
        Column('reserved', Integer, nullable=False),
        Column('until_refresh', Integer),
        Column('user_id', String(length=255)),
        Index('quota_usages_project_id_idx', 'project_id'),
        Index('quota_usages_user_id_idx', 'user_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_usages.create(checkfirst=True)

    quotas = Table('quotas', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255), nullable=False),
        Column('hard_limit', Integer),
        UniqueConstraint('project_id', 'resource',
                         name='uniq_quotas0project_id0resource'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quotas.create(checkfirst=True)

    uniq_name = "uniq_project_user_quotas0user_id0project_id0resource"
    project_user_quotas = Table('project_user_quotas', meta,
        Column('id', Integer, primary_key=True,
               nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('user_id',
               String(length=255),
               nullable=False),
        Column('project_id',
               String(length=255),
               nullable=False),
        Column('resource',
               String(length=255),
               nullable=False),
        Column('hard_limit', Integer, nullable=True),
        UniqueConstraint('user_id', 'project_id', 'resource',
                         name=uniq_name),
        Index('project_user_quotas_project_id_idx',
              'project_id'),
        Index('project_user_quotas_user_id_idx',
              'user_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    project_user_quotas.create(checkfirst=True)

    reservations = Table('reservations', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        Column('usage_id', Integer, ForeignKey('quota_usages.id'),
               nullable=False),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255)),
        Column('delta', Integer, nullable=False),
        Column('expire', DateTime),
        Column('user_id', String(length=255)),
        Index('reservations_project_id_idx', 'project_id'),
        Index('reservations_uuid_idx', 'uuid'),
        Index('reservations_expire_idx', 'expire'),
        Index('reservations_user_id_idx', 'user_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    reservations.create(checkfirst=True)
