#    Copyright 2016 Hewlett Packard Enterprise Development Company LP
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

from sqlalchemy import Column
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table('console_auth_tokens', meta, autoload=True)
    new_column = Column('access_url_base', String(255), nullable=True)
    if not hasattr(table.c, 'access_url_base'):
        table.create_column(new_column)
