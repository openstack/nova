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

from migrate import UniqueConstraint
from oslo_db.sqlalchemy import utils
from sqlalchemy import Column
from sqlalchemy import DDL
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import Table
from sqlalchemy import Unicode


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    resource_providers = Table('resource_providers', meta, autoload=True)

    name = Column('name', Unicode(200), nullable=True)
    generation = Column('generation', Integer, default=0)
    can_host = Column('can_host', Integer, default=0)

    if not hasattr(resource_providers.c, 'name'):
        # NOTE(cdent): The resource_providers table is defined as
        # latin1 to be more efficient. Now we need the name column
        # to be UTF8. First create the column, then modify it,
        # otherwise the declarative handling in sqlalchemy gets
        # confused.
        resource_providers.create_column(name)
        if migrate_engine.name == 'mysql':
            name_col_ddl = DDL(
                "ALTER TABLE resource_providers MODIFY name "
                "VARCHAR(200) CHARACTER SET utf8")
            conn = migrate_engine.connect()
            conn.execute(name_col_ddl)

        uc = UniqueConstraint('name', table=resource_providers,
                              name='uniq_resource_providers0name')
        uc.create()

        utils.add_index(migrate_engine, 'resource_providers',
                        'resource_providers_name_idx',
                        ['name'])

    if not hasattr(resource_providers.c, 'generation'):
        resource_providers.create_column(generation)

    if not hasattr(resource_providers.c, 'can_host'):
        resource_providers.create_column(can_host)

    resource_provider_aggregates = Table(
        'resource_provider_aggregates', meta,
        Column('resource_provider_id', Integer, primary_key=True,
               nullable=False),
        Column('aggregate_id', Integer, primary_key=True, nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )
    Index('resource_provider_aggregates_aggregate_id_idx',
          resource_provider_aggregates.c.aggregate_id)
    resource_provider_aggregates.create(checkfirst=True)

    utils.add_index(migrate_engine, 'allocations',
                    'allocations_resource_provider_class_used_idx',
                    ['resource_provider_id', 'resource_class_id',
                     'used'])
    utils.drop_index(migrate_engine, 'allocations',
                     'allocations_resource_provider_class_id_idx')

    # Add a unique constraint so that any resource provider can have
    # only one inventory for any given resource class.
    inventories = Table('inventories', meta, autoload=True)
    inventories_uc = UniqueConstraint(
        'resource_provider_id', 'resource_class_id', table=inventories,
        name='uniq_inventories0resource_provider_resource_class')
    inventories_uc.create()

    utils.add_index(migrate_engine, 'inventories',
                    'inventories_resource_provider_resource_class_idx',
                    ['resource_provider_id', 'resource_class_id'])
