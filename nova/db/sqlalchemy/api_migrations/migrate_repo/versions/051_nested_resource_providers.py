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

from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    resource_providers = Table('resource_providers', meta, autoload=True)
    columns_to_add = [
            ('root_provider_id',
                Column('root_provider_id', Integer,
                       ForeignKey('resource_providers.id'))),
            ('parent_provider_id',
                Column('parent_provider_id', Integer,
                       ForeignKey('resource_providers.id'))),
    ]
    for col_name, column in columns_to_add:
        if not hasattr(resource_providers.c, col_name):
            resource_providers.create_column(column)

    indexed_columns = set()
    for idx in resource_providers.indexes:
        for c in idx.columns:
            indexed_columns.add(c.name)

    if 'root_provider_id' not in indexed_columns:
        index = Index('resource_providers_root_provider_id_idx',
                resource_providers.c.root_provider_id)
        index.create()
    if 'parent_provider_id' not in indexed_columns:
        index = Index('resource_providers_parent_provider_id_idx',
                resource_providers.c.parent_provider_id)
        index.create()
