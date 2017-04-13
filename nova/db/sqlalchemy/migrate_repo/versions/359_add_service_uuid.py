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
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy import Index
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    for prefix in ('', 'shadow_'):
        services = Table(prefix + 'services', meta, autoload=True)
        if not hasattr(services.c, 'uuid'):
            services.create_column(Column('uuid', String(36), nullable=True))

    uuid_index_name = 'services_uuid_idx'
    indexes = Inspector(migrate_engine).get_indexes('services')
    if uuid_index_name not in (i['name'] for i in indexes):
        services = Table('services', meta, autoload=True)
        Index(uuid_index_name, services.c.uuid, unique=True).create()
