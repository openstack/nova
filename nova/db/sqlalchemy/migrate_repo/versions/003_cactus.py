# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


#
# New Tables
#
# Here are the old static instance types
# INSTANCE_TYPES = {
# 'm1.tiny': dict(memory_mb=512, vcpus=1, local_gb=0, flavorid=1),
# 'm1.small': dict(memory_mb=2048, vcpus=1, local_gb=20, flavorid=2),
# 'm1.medium': dict(memory_mb=4096, vcpus=2, local_gb=40, flavorid=3),
# 'm1.large': dict(memory_mb=8192, vcpus=4, local_gb=80, flavorid=4),
# 'm1.xlarge': dict(memory_mb=16384, vcpus=8, local_gb=160, flavorid=5)}
instance_types = Table('instance_types', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(),  primary_key=True, nullable=False),
        Column('memory_mb', Integer(),  nullable=False),
        Column('vcpus', Integer(),  nullable=False),
        Column('local_gb', Integer(),  nullable=False),
        Column('flavorid', Integer(),  nullable=False),
        )


def upgrade(migrate_engine):
    # Upgrade operations go here
    # Don't create your own engine; bind migrate_engine
    # to your metadata
    meta.bind = migrate_engine
    try:
        instance_types.create()
    except Exception:
        logging.info(repr(table))
        logging.exception('Exception while creating table')
        raise

    # TODO(ken-pepple) fix this to pre-populate the default EC2 types
    #INSTANCE_TYPES = {
    #    'm1.tiny': dict(memory_mb=512, vcpus=1, local_gb=0, flavorid=1),
    #    'm1.small': dict(memory_mb=2048, vcpus=1, local_gb=20, flavorid=2),
    #    'm1.medium': dict(memory_mb=4096, vcpus=2, local_gb=40, flavorid=3),
    #    'm1.large': dict(memory_mb=8192, vcpus=4, local_gb=80, flavorid=4),
    #    'm1.xlarge': dict(memory_mb=16384, vcpus=8, local_gb=160, flavorid=5)}
    # for instance_type in INSTANCE_TYPES:
    #	try:
            # prepopulate tables with EC2 types


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    #    # Operations to reverse the above upgrade go here.
    #    for table in (instance_types):
    #        table.drop()
    pass
