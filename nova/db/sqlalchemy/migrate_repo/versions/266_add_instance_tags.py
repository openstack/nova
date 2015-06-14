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

import sqlalchemy as sa


def upgrade(migrate_engine):
    meta = sa.MetaData(bind=migrate_engine)

    tags = sa.Table('tags', meta,
                    sa.Column('resource_id', sa.String(36), primary_key=True,
                              nullable=False),
                    sa.Column('tag', sa.Unicode(80), primary_key=True,
                              nullable=False),
                    sa.Index('tags_tag_idx', 'tag'),
                    mysql_engine='InnoDB',
                    mysql_charset='utf8')
    tags.create()
