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
"""Database migrations for consumers"""

from migrate import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    consumers = Table('consumers', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False,
               autoincrement=True),
        Column('uuid', String(length=36), nullable=False),
        Column('project_id', String(length=255), nullable=False),
        Column('user_id', String(length=255), nullable=False),
        Index('consumers_project_id_uuid_idx', 'project_id', 'uuid'),
        Index('consumers_project_id_user_id_uuid_idx', 'project_id', 'user_id',
              'uuid'),
        UniqueConstraint('uuid', name='uniq_consumers0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    consumers.create(checkfirst=True)
