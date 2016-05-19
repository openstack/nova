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
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    resource_providers = Table(
        'resource_providers', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(36), nullable=False),
        UniqueConstraint('uuid', name='uniq_resource_providers0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    Index('resource_providers_uuid_idx', resource_providers.c.uuid)

    inventories = Table(
        'inventories', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('resource_provider_id', Integer, nullable=False),
        Column('resource_class_id', Integer, nullable=False),
        Column('total', Integer, nullable=False),
        Column('reserved', Integer, nullable=False),
        Column('min_unit', Integer, nullable=False),
        Column('max_unit', Integer, nullable=False),
        Column('step_size', Integer, nullable=False),
        Column('allocation_ratio', Float, nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )
    Index('inventories_resource_provider_id_idx',
          inventories.c.resource_provider_id)
    Index('inventories_resource_class_id_idx',
          inventories.c.resource_class_id)

    allocations = Table(
        'allocations', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('resource_provider_id', Integer, nullable=False),
        Column('consumer_id', String(36), nullable=False),
        Column('resource_class_id', Integer, nullable=False),
        Column('used', Integer, nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )
    Index('allocations_resource_provider_class_id_idx',
          allocations.c.resource_provider_id,
          allocations.c.resource_class_id)
    Index('allocations_consumer_id_idx', allocations.c.consumer_id)
    Index('allocations_resource_class_id_idx',
          allocations.c.resource_class_id)

    for table in [resource_providers, inventories, allocations]:
        table.create(checkfirst=True)

    for table_name in ('', 'shadow_'):
        uuid_column = Column('uuid', String(36))
        compute_nodes = Table('%scompute_nodes' % table_name, meta)
        compute_nodes.create_column(uuid_column)
