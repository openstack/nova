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

from sqlalchemy import MetaData, Column, Table
from sqlalchemy import Enum, Boolean


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    migrations = Table('migrations', meta, autoload=True)
    shadow_migrations = Table('shadow_migrations', meta, autoload=True)

    enum = Enum('migration', 'resize', 'live-migration', 'evacuation',
                metadata=meta, name='migration_type')
    enum.create()

    migration_type = Column('migration_type', enum, nullable=True)

    if not hasattr(migrations.c, 'migration_type'):
        migrations.create_column(migration_type)
    if not hasattr(shadow_migrations.c, 'migration_type'):
        shadow_migrations.create_column(migration_type.copy())

    hidden = Column('hidden', Boolean, default=False)
    if not hasattr(migrations.c, 'hidden'):
        migrations.create_column(hidden)
    if not hasattr(shadow_migrations.c, 'hidden'):
        shadow_migrations.create_column(hidden.copy())
