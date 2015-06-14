# Copyright (c) 2015 Cloudbase Solutions SRL
# All Rights Reserved
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

from sqlalchemy import MetaData, Column, Table
from sqlalchemy import Enum

from nova.objects import keypair


def upgrade(migrate_engine):
    """Function adds key_pairs type field."""
    meta = MetaData(bind=migrate_engine)
    key_pairs = Table('key_pairs', meta, autoload=True)
    shadow_key_pairs = Table('shadow_key_pairs', meta, autoload=True)

    enum = Enum('ssh', 'x509', metadata=meta, name='keypair_types')
    enum.create()

    keypair_type = Column('type', enum, nullable=False,
                          server_default=keypair.KEYPAIR_TYPE_SSH)

    if hasattr(key_pairs.c, 'type'):
        key_pairs.c.type.drop()

    if hasattr(shadow_key_pairs.c, 'type'):
        shadow_key_pairs.c.type.drop()

    key_pairs.create_column(keypair_type)
    shadow_key_pairs.create_column(keypair_type.copy())
