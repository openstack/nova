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
"""Database migrations for resource-providers."""

from migrate import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Unicode


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    if migrate_engine.name == 'mysql':
        nameargs = {'collation': 'utf8_bin'}
    else:
        nameargs = {}
    resource_providers = Table(
        'resource_providers', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(36), nullable=False),
        Column('name', Unicode(200, **nameargs), nullable=True),
        Column('generation', Integer, default=0),
        Column('can_host', Integer, default=0),
        UniqueConstraint('uuid', name='uniq_resource_providers0uuid'),
        UniqueConstraint('name', name='uniq_resource_providers0name'),
        Index('resource_providers_name_idx', 'name'),
        Index('resource_providers_uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    inventories = Table(
        'inventories', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('resource_provider_id', Integer, nullable=False),
        Column('resource_class_id', Integer, nullable=False),
        Column('total', Integer, nullable=False),
        Column('reserved', Integer, nullable=False),
        Column('min_unit', Integer, nullable=False),
        Column('max_unit', Integer, nullable=False),
        Column('step_size', Integer, nullable=False),
        Column('allocation_ratio', Float, nullable=False),
        Index('inventories_resource_provider_id_idx',
              'resource_provider_id'),
        Index('inventories_resource_provider_resource_class_idx',
              'resource_provider_id', 'resource_class_id'),
        Index('inventories_resource_class_id_idx',
              'resource_class_id'),
        UniqueConstraint('resource_provider_id', 'resource_class_id',
            name='uniq_inventories0resource_provider_resource_class'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    allocations = Table(
        'allocations', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('resource_provider_id', Integer, nullable=False),
        Column('consumer_id', String(36), nullable=False),
        Column('resource_class_id', Integer, nullable=False),
        Column('used', Integer, nullable=False),
        Index('allocations_resource_provider_class_used_idx',
              'resource_provider_id', 'resource_class_id',
              'used'),
        Index('allocations_resource_class_id_idx',
              'resource_class_id'),
        Index('allocations_consumer_id_idx', 'consumer_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    resource_provider_aggregates = Table(
        'resource_provider_aggregates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('resource_provider_id', Integer, primary_key=True,
               nullable=False),
        Column('aggregate_id', Integer, primary_key=True, nullable=False),
        Index('resource_provider_aggregates_aggregate_id_idx',
              'aggregate_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    for table in [resource_providers, inventories, allocations,
                  resource_provider_aggregates]:
        table.create(checkfirst=True)
