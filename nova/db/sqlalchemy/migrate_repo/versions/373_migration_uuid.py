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

from sqlalchemy import MetaData, Column, Table, Index
from sqlalchemy import String


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    for prefix in ('', 'shadow_'):
        migrations = Table('%smigrations' % prefix, meta, autoload=True)
        if not hasattr(migrations.c, 'uuid'):
            uuid = Column('uuid', String(36))
            migrations.create_column(uuid)
            idx = Index('%smigrations_uuid' % prefix,
                        migrations.c.uuid, unique=True)
            idx.create(migrate_engine)
