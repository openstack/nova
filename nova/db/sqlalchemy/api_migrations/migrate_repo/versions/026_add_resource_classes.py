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

from migrate import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    resource_classes = Table('resource_classes', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255), nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        UniqueConstraint('name', name='uniq_resource_classes0name'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    resource_classes.create(checkfirst=True)
