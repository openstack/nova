# Copyright (c) 2014 The Johns Hopkins University/Applied Physics Laboratory
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
from sqlalchemy import String


def upgrade(migrate_engine):
    """Function adds ephemeral storage encryption key uuid field."""
    meta = MetaData(bind=migrate_engine)

    instances = Table('instances', meta, autoload=True)
    shadow_instances = Table('shadow_instances', meta, autoload=True)

    ephemeral_key_uuid = Column('ephemeral_key_uuid', String(36))
    instances.create_column(ephemeral_key_uuid)
    shadow_instances.create_column(ephemeral_key_uuid.copy())

    migrate_engine.execute(instances.update().
                           values(ephemeral_key_uuid=None))
    migrate_engine.execute(shadow_instances.update().
                           values(ephemeral_key_uuid=None))
