#    Copyright 2016 Intel Corporation
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
    auth_tokens = Table('console_auth_tokens', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('token_hash', String(255), nullable=False),
        Column('console_type', String(255), nullable=False),
        Column('host', String(255), nullable=False),
        Column('port', Integer, nullable=False),
        Column('internal_access_path', String(255)),
        Column('instance_uuid', String(36), nullable=False),
        Column('expires', Integer, nullable=False),
        Index('console_auth_tokens_instance_uuid_idx', 'instance_uuid'),
        Index('console_auth_tokens_host_expires_idx', 'host', 'expires'),
        Index('console_auth_tokens_token_hash_idx', 'token_hash'),
        UniqueConstraint('token_hash',
                         name='uniq_console_auth_tokens0token_hash'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    auth_tokens.create(checkfirst=True)
