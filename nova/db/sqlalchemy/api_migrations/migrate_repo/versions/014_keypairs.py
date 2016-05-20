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
from sqlalchemy import Enum
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text

from nova.objects import keypair


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    enum = Enum('ssh', 'x509', metadata=meta, name='keypair_types')
    enum.create(checkfirst=True)

    keypairs = Table('key_pairs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(255), nullable=False),
        Column('user_id', String(255), nullable=False),
        Column('fingerprint', String(255)),
        Column('public_key', Text()),
        Column('type', enum, nullable=False,
               server_default=keypair.KEYPAIR_TYPE_SSH),
        UniqueConstraint('user_id', 'name',
                         name="uniq_key_pairs0user_id0name"),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    keypairs.create(checkfirst=True)
