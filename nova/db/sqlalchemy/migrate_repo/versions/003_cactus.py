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

services = Table('services', meta,
        Column('id', Integer(),  primary_key=True, nullable=False),
        )

#
# New Tables
#


#
# Tables to alter
#
instances_launched_on = Column(
         'launched_on', 
         Text(convert_unicode=False, assert_unicode=None,
              unicode_error=None, _warn_on_bytestring=False),
              nullable=True)
services_vcpus = Column('vcpus', Integer(), nullable=True)
services_memory_mb = Column('memory_mb', Integer(), nullable=True)
services_local_gb = Column('local_gb', Integer(), nullable=True)
services_vcpus_used = Column('vcpus_used', Integer(), nullable=True)
services_memory_mb_used = Column('memory_mb_used', Integer(), nullable=True)
services_local_gb_used = Column('local_gb_used', Integer(), nullable=True)
services_hypervisor_type = Column(
         'hypervisor_type', 
         Text(convert_unicode=False, assert_unicode=None,
              unicode_error=None, _warn_on_bytestring=False),
              nullable=True)
services_hypervisor_version = Column(
        'hypervisor_version', 
        Integer(), nullable=True)
services_cpu_info = Column(
         'cpu_info', 
         Text(convert_unicode=False, assert_unicode=None,
              unicode_error=None, _warn_on_bytestring=False),
         nullable=True)

def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine

    instances.create_column(instances_launched_on)
    services.create_column(services_vcpus)
    services.create_column(services_memory_mb)
    services.create_column(services_local_gb)
    services.create_column(services_vcpus_used)
    services.create_column(services_memory_mb_used)
    services.create_column(services_local_gb_used)
    services.create_column(services_hypervisor_type)
    services.create_column(services_hypervisor_version)
    services.create_column(services_cpu_info)

