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

from sqlalchemy import Column, Integer, MetaData, Table, String

meta = MetaData()

default_local_device = Column(
    'default_local_device',
    String(length=255, convert_unicode=False, assert_unicode=None,
           unicode_error=None, _warn_on_bytestring=False),
    nullable=True)

default_swap_device = Column(
    'default_swap_device',
    String(length=255, convert_unicode=False, assert_unicode=None,
           unicode_error=None, _warn_on_bytestring=False),
    nullable=True)

instances = Table('instances', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    instances.create_column(default_local_device)
    instances.create_column(default_swap_device)


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    meta.bind = migrate_engine
    instances.drop_column('default_swap_device')
    instances.drop_column('default_local_device')
