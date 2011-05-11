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

meta = MetaData()


# Table stub-definitions
# Just for the ForeignKey and column creation to succeed, these are not the
# actual definitions of instances or services.
#
volumes = Table('volumes', meta,
                Column('id', Integer(), primary_key=True, nullable=False),
                )


#
# New Tables
#
# None

#
# Tables to alter
#
# None

#
# Columns to add to existing tables
#

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


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine

    # Add columns to existing tables
    volumes.create_column(volumes_provider_location)
    volumes.create_column(volumes_provider_auth)
