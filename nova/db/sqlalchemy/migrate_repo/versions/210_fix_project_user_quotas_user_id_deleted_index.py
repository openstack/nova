# All Rights Reserved.
#
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

from sqlalchemy import Index, MetaData, Table


def _change_index_columns(migrate_engine, new_columns, old_columns):
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table('project_user_quotas', meta, autoload=True)
    index_name = 'project_user_quotas_user_id_deleted_idx'

    Index(
        index_name,
        *[getattr(table.c, col) for col in old_columns]
    ).drop(migrate_engine)

    Index(
        index_name,
        *[getattr(table.c, col) for col in new_columns]
    ).create()


def upgrade(migrate_engine):
    new_columns = ('user_id', 'deleted')
    old_columns = ('project_id', 'deleted')
    _change_index_columns(migrate_engine, new_columns, old_columns)


def downgrade(migrate_engine):
    new_columns = ('project_id', 'deleted')
    old_columns = ('user_id', 'deleted')
    _change_index_columns(migrate_engine, new_columns, old_columns)
