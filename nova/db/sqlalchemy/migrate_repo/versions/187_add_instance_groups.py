# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

from migrate.changeset import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import utils


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    groups = Table('instance_groups', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('uuid', String(length=36), nullable=False),
        Column('name', String(length=255)),
        UniqueConstraint('uuid', 'deleted',
                         name='uniq_instance_groups0uuid0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_metadata = Table('instance_group_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        Column('group_id', Integer, ForeignKey('instance_groups.id'),
               nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_policy = Table('instance_group_policy', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('policy', String(length=255)),
        Column('group_id', Integer, ForeignKey('instance_groups.id'),
               nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_member = Table('instance_group_member', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_id', String(length=255)),
        Column('group_id', Integer, ForeignKey('instance_groups.id'),
               nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    tables = [groups, group_metadata, group_policy, group_member]

    # create all of the tables
    for table in tables:
        table.create()
        utils.create_shadow_table(migrate_engine, table=table)

    indexes = [
        Index('instance_group_metadata_key_idx', group_metadata.c.key),
        Index('instance_group_member_instance_idx',
              group_member.c.instance_id),
        Index('instance_group_policy_policy_idx', group_policy.c.policy)
    ]

    # Common indexes
    if migrate_engine.name == 'mysql' or migrate_engine.name == 'postgresql':
        for index in indexes:
            index.create(migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    table_names = ['instance_group_member', 'instance_group_policy',
                   'instance_group_metadata', 'instance_groups']
    for name in table_names:
        table = Table(name, meta, autoload=True)
        table.drop()
        table = Table(db._SHADOW_TABLE_PREFIX + name, meta, autoload=True)
        table.drop()
