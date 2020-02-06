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
        instances = Table('%sinstances' % prefix, meta, autoload=True)
        if not hasattr(instances.c, 'hidden'):
            # NOTE(danms): This column originally included default=False. We
            # discovered in bug #1862205 that this will attempt to rewrite
            # the entire instances table with that value, which can time out
            # for large data sets (and does not even abort).
            hidden = Column('hidden', Boolean)
            instances.create_column(hidden)
