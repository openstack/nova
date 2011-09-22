# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy import MetaData, String, Table
from nova import log as logging

meta = MetaData()

# Just for the ForeignKey and column creation to succeed, these are not the
# actual definitions of instances or services.
instances = Table('instances', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )

quotas = Table('quotas', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )


#
# New Tables
#

instance_metadata_table = Table('instance_metadata', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('instance_id',
               Integer(),
               ForeignKey('instances.id'),
               nullable=False),
        Column('key',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('value',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)))


#
# New columns
#
quota_metadata_items = Column('metadata_items', Integer())


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    for table in (instance_metadata_table, ):
        try:
            table.create()
        except Exception:
            logging.info(repr(table))
            logging.exception('Exception while creating table')
            raise

    quotas.create_column(quota_metadata_items)
