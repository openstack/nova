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


from sqlalchemy import BigInteger
from sqlalchemy import Column
from sqlalchemy import MetaData
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    migrations = Table('migrations', meta, autoload=True)
    shadow_migrations = Table('shadow_migrations', meta, autoload=True)

    columns = ['memory_total', 'memory_processed', 'memory_remaining',
               'disk_total', 'disk_processed', 'disk_remaining']
    for column_name in columns:
        column = Column(column_name, BigInteger, nullable=True)
        migrations.create_column(column)
        shadow_migrations.create_column(column.copy())
