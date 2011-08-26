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

#
# New Tables
#

virtual_storage_arrays = Table('virtual_storage_arrays', meta,
       Column('created_at', DateTime(timezone=False)),
       Column('updated_at', DateTime(timezone=False)),
       Column('deleted_at', DateTime(timezone=False)),
       Column('deleted', Boolean(create_constraint=True, name=None)),
       Column('id', Integer(), primary_key=True, nullable=False),
       Column('display_name',
              String(length=255, convert_unicode=False, assert_unicode=None,
                     unicode_error=None, _warn_on_bytestring=False)),
       Column('display_description',
              String(length=255, convert_unicode=False, assert_unicode=None,
                     unicode_error=None, _warn_on_bytestring=False)),
       Column('project_id',
              String(length=255, convert_unicode=False, assert_unicode=None,
                     unicode_error=None, _warn_on_bytestring=False)),
       Column('availability_zone',
              String(length=255, convert_unicode=False, assert_unicode=None,
                     unicode_error=None, _warn_on_bytestring=False)),
       Column('instance_type_id', Integer(), nullable=False),
       Column('image_ref',
           String(length=255, convert_unicode=False, assert_unicode=None,
                  unicode_error=None, _warn_on_bytestring=False)),
       Column('vc_count', Integer(), nullable=False),
       Column('vol_count', Integer(), nullable=False),
       Column('status',
              String(length=255, convert_unicode=False, assert_unicode=None,
                     unicode_error=None, _warn_on_bytestring=False)),
       )


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine

    try:
        virtual_storage_arrays.create()
    except Exception:
        logging.info(repr(table))
        logging.exception('Exception while creating table')
        raise


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    virtual_storage_arrays.drop()
