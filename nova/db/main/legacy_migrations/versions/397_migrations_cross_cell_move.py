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
from sqlalchemy import Boolean


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    for prefix in ('', 'shadow_'):
        migrations = Table('%smigrations' % prefix, meta, autoload=True)
        if not hasattr(migrations.c, 'cross_cell_move'):
            cross_cell_move = Column('cross_cell_move', Boolean, default=False)
            migrations.create_column(cross_cell_move)
