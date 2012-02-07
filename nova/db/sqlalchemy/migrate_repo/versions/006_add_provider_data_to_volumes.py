# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara.
# All Rights Reserved.
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

from sqlalchemy import Column, Integer, MetaData, String, Table


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)

    # Add columns to existing tables
    volumes_provider_location = Column('provider_location',
                                       String(length=256,
                                              convert_unicode=False,
                                              assert_unicode=None,
                                              unicode_error=None,
                                              _warn_on_bytestring=False))

    volumes_provider_auth = Column('provider_auth',
                                   String(length=256,
                                          convert_unicode=False,
                                          assert_unicode=None,
                                          unicode_error=None,
                                          _warn_on_bytestring=False))
    volumes.create_column(volumes_provider_location)
    volumes.create_column(volumes_provider_auth)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)

    volumes.drop_column('provider_location')
    volumes.drop_column('provider_auth')
