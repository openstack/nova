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
"""Database migrations for traits"""

from migrate.changeset.constraint import ForeignKeyConstraint
from migrate import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import Table
from sqlalchemy import Unicode


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    if migrate_engine.name == 'mysql':
        nameargs = {'collation': 'utf8_bin'}
    else:
        nameargs = {}

    resource_providers = Table('resource_providers', meta, autoload=True)

    traits = Table(
        'traits', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False,
               autoincrement=True),
        Column('name', Unicode(255, **nameargs), nullable=False),
        UniqueConstraint('name', name='uniq_traits0name'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    resource_provider_traits = Table(
        'resource_provider_traits', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('trait_id', Integer, ForeignKey('traits.id'), primary_key=True,
               nullable=False),
        Column('resource_provider_id', Integer, primary_key=True,
               nullable=False),
        Index('resource_provider_traits_resource_provider_trait_idx',
              'resource_provider_id', 'trait_id'),
        ForeignKeyConstraint(columns=['resource_provider_id'],
                             refcolumns=[resource_providers.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    for table in [traits, resource_provider_traits]:
        table.create(checkfirst=True)
