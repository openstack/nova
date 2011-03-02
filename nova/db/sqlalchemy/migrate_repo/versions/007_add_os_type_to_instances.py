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

instances = Table('instances', meta,
        Column('id', Integer(),  primary_key=True, nullable=False),
        )

# FIXME(dubs) should this be not null?  Maybe create as nullable, then
#   populate all existing rows with 'linux', then adding not null constraint.
instances_os_type = Column('os_type',
                           String(length=255, convert_unicode=False,
                                  assert_unicode=None, unicode_error=None,
                                  _warn_on_bytestring=False),
                           nullable=False)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine

    instances.create_column(instances_os_type)

    
