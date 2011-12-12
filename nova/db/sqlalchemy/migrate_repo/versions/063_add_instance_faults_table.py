# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import Boolean, Column, DateTime, Integer, ForeignKey
from sqlalchemy import MetaData, String, Table, Text
from nova import log as logging

meta = MetaData()

#
# New Tables
#
instance_faults = Table('instance_faults', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None),
                default=False),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('instance_uuid', String(36, ForeignKey('instances.uuid'))),
        Column('code', Integer(), nullable=False),
        Column('message',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('details',
               Text(length=None, convert_unicode=False, assert_unicode=None,
                    unicode_error=None, _warn_on_bytestring=False)),
        )


#
# Tables to alter
#

# (none currently)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    try:
        instance_faults.create()
    except Exception:
        logging.info(repr(instance_faults))


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    instance_faults.drop()
