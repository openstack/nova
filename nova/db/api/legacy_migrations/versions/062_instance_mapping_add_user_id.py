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
from sqlalchemy import Index
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_mappings = Table('instance_mappings', meta, autoload=True)

    if not hasattr(instance_mappings.c, 'user_id'):
        instance_mappings.create_column(Column('user_id', String(length=255),
            nullable=True))
        index = Index('instance_mappings_user_id_project_id_idx',
                      instance_mappings.c.user_id,
                      instance_mappings.c.project_id)
        index.create()
