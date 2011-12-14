# Copyright 2011 Isaku Yamahata
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

from sqlalchemy import MetaData
from sqlalchemy import Boolean, String
from sqlalchemy import Column, Table

meta = MetaData()

shutdown_terminate = Column(
    'shutdown_terminate', Boolean(), default=True)
disable_terminate = Column(
    'disable_terminate', Boolean(), default=False)


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)
    instances.create_column(shutdown_terminate)
    instances.create_column(disable_terminate)


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)
    instances.drop_column(shutdown_terminate)
    instances.drop_column(disable_terminate)
