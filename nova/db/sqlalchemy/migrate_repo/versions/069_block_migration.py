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

from sqlalchemy import Column, Integer, MetaData, Table
from nova import log as logging

meta = MetaData()

# Add disk_available_least column to compute_nodes table.
# Thinking about qcow2 image support, both compressed and virtual disk size
# has to be considered.
# disk_available stores "total disk size - used disk(compressed disk size)",
# while disk_available_least stores
# "total disk size - used disk(virtual disk size)".
# virtual disk size is used for kvm block migration.

compute_nodes = Table('compute_nodes', meta,
        Column('id', Integer(), primary_key=True, nullable=False))

disk_available_least = Column('disk_available_least', Integer(), default=0)


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    try:
        compute_nodes.create_column(disk_available_least)
    except Exception:
        logging.error(_("progress column not added to compute_nodes table"))
        raise


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    compute_nodes.drop_column(disk_available_least)
