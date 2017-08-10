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

from oslo_log import log as logging
from sqlalchemy import MetaData, Table, Index
from sqlalchemy.engine import reflection

LOG = logging.getLogger(__name__)

INDEX_COLUMNS_1 = ['project_id']
INDEX_NAME_1 = 'instances_project_id_idx'

INDEX_COLUMNS_2 = ['updated_at', 'project_id']
INDEX_NAME_2 = 'instances_updated_at_project_id_idx'

TABLE_NAME = 'instances'


def _get_table_index(migrate_engine, table_name, index_columns):
    inspector = reflection.Inspector.from_engine(migrate_engine)
    for idx in inspector.get_indexes(table_name):
        if idx['column_names'] == index_columns:
            break
    else:
        idx = None
    return idx


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    table = Table(TABLE_NAME, meta, autoload=True)
    if _get_table_index(migrate_engine, TABLE_NAME, INDEX_COLUMNS_1):
        LOG.info('Skipped adding %s because an equivalent index'
                 ' already exists.', INDEX_NAME_1)
    else:
        columns = [getattr(table.c, col_name) for col_name in INDEX_COLUMNS_1]
        index = Index(INDEX_NAME_1, *columns)
        index.create(migrate_engine)

    if _get_table_index(migrate_engine, TABLE_NAME, INDEX_COLUMNS_2):
        LOG.info('Skipped adding %s because an equivalent index'
                 ' already exists.', INDEX_NAME_2)
    else:
        columns = [getattr(table.c, col_name) for col_name in INDEX_COLUMNS_2]
        index = Index(INDEX_NAME_2, *columns)
        index.create(migrate_engine)
