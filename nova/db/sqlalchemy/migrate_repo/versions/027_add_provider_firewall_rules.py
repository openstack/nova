# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from sqlalchemy import *
from migrate import *

from nova import log as logging


meta = MetaData()


# Just for the ForeignKey and column creation to succeed, these are not the
# actual definitions of instances or services.
instances = Table('instances', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )


services = Table('services', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )


networks = Table('networks', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )


#
# New Tables
#
provider_fw_rules = Table('provider_fw_rules', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('protocol',
               String(length=5, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('from_port', Integer()),
        Column('to_port', Integer()),
        Column('cidr',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)))


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    for table in (provider_fw_rules,):
        try:
            table.create()
        except Exception:
            logging.info(repr(table))
            logging.exception('Exception while creating table')
            raise
