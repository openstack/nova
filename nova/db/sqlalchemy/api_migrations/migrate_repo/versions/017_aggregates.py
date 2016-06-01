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
"""API Database migrations for aggregates"""

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

    aggregates = Table('aggregates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36)),
        Column('name', String(length=255)),
        Index('aggregate_uuid_idx', 'uuid'),
        UniqueConstraint('name', name='uniq_aggregate0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregates.create(checkfirst=True)

    aggregate_hosts = Table('aggregate_hosts', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('aggregate_id', Integer, ForeignKey('aggregates.id'),
              nullable=False),
        UniqueConstraint('host', 'aggregate_id',
                     name='uniq_aggregate_hosts0host0aggregate_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_hosts.create(checkfirst=True)

    aggregate_metadata = Table('aggregate_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('aggregate_id', Integer, ForeignKey('aggregates.id'),
              nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255), nullable=False),
        UniqueConstraint('aggregate_id', 'key',
                     name='uniq_aggregate_metadata0aggregate_id0key'),
        Index('aggregate_metadata_key_idx', 'key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_metadata.create(checkfirst=True)
