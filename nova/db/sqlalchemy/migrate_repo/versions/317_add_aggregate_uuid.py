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

from sqlalchemy import Column
from sqlalchemy import Index
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    for table_prefix in ('', 'shadow_'):
        uuid_column = Column('uuid', String(36))
        aggregates = Table('%saggregates' % table_prefix, meta)
        if not hasattr(aggregates.c, 'uuid'):
            aggregates.create_column(uuid_column)
            if not table_prefix:
                index = Index('aggregate_uuid_idx', aggregates.c.uuid)
                index.create()
