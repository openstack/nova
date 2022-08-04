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

from sqlalchemy import MetaData, Column, Table, String

NEW_COLUMNS_NAME = ['user_id', 'project_id']
BASE_TABLE_NAME = 'migrations'


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    for prefix in ('', 'shadow_'):
        table = Table(prefix + BASE_TABLE_NAME, meta, autoload=True)
        for new_column_name in NEW_COLUMNS_NAME:
            new_column = Column(new_column_name, String(255), nullable=True)
            if not hasattr(table.c, new_column_name):
                table.create_column(new_column)
