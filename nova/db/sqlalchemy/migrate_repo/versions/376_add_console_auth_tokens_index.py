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

from sqlalchemy import Index
from sqlalchemy import MetaData
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table('console_auth_tokens', meta, autoload=True)
    for idx in table.indexes:
        if idx.columns.keys() == ['token_hash', 'instance_uuid']:
            return
    idx_name = 'console_auth_tokens_token_hash_instance_uuid_idx'
    Index(idx_name, table.c.token_hash, table.c.instance_uuid).create()
