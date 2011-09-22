# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy import Text, Boolean, ForeignKey

from nova import log as logging

meta = MetaData()

# Just for the ForeignKey and column creation to succeed, these are not the
# actual definitions of tables .
#

volumes = Table('volumes', meta,
       Column('id', Integer(), primary_key=True, nullable=False),
       )

volume_type_id = Column('volume_type_id', Integer(), nullable=True)


# New Tables
#

volume_types = Table('volume_types', meta,
       Column('created_at', DateTime(timezone=False)),
       Column('updated_at', DateTime(timezone=False)),
       Column('deleted_at', DateTime(timezone=False)),
       Column('deleted', Boolean(create_constraint=True, name=None)),
       Column('id', Integer(), primary_key=True, nullable=False),
       Column('name',
              String(length=255, convert_unicode=False, assert_unicode=None,
                     unicode_error=None, _warn_on_bytestring=False),
              unique=True))

volume_type_extra_specs_table = Table('volume_type_extra_specs', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('volume_type_id',
               Integer(),
               ForeignKey('volume_types.id'),
               nullable=False),
        Column('key',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('value',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)))


volume_metadata_table = Table('volume_metadata', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('volume_id',
               Integer(),
               ForeignKey('volumes.id'),
               nullable=False),
        Column('key',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('value',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)))


new_tables = (volume_types,
              volume_type_extra_specs_table,
              volume_metadata_table)

#
# Tables to alter
#


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    for table in new_tables:
        try:
            table.create()
        except Exception:
            logging.info(repr(table))
            logging.exception('Exception while creating table')
            raise

    volumes.create_column(volume_type_id)


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    volumes.drop_column(volume_type_id)

    for table in new_tables:
        table.drop()
