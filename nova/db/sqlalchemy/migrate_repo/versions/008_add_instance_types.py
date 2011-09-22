# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Ken Pepple
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

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table
from nova import log as logging

meta = MetaData()


#
# New Tables
#
instance_types = Table('instance_types', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('name',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False),
                      unique=True),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('memory_mb', Integer(), nullable=False),
        Column('vcpus', Integer(), nullable=False),
        Column('local_gb', Integer(), nullable=False),
        Column('flavorid', Integer(), nullable=False, unique=True),
        Column('swap', Integer(), nullable=False, default=0),
        Column('rxtx_quota', Integer(), nullable=False, default=0),
        Column('rxtx_cap', Integer(), nullable=False, default=0))


def upgrade(migrate_engine):
    # Upgrade operations go here
    # Don't create your own engine; bind migrate_engine
    # to your metadata
    meta.bind = migrate_engine
    try:
        instance_types.create()
    except Exception:
        logging.info(repr(instance_types))
        logging.exception('Exception while creating instance_types table')
        raise

    # Here are the old static instance types
    INSTANCE_TYPES = {
    'm1.tiny': dict(memory_mb=512, vcpus=1, local_gb=0, flavorid=1),
    'm1.small': dict(memory_mb=2048, vcpus=1, local_gb=20, flavorid=2),
    'm1.medium': dict(memory_mb=4096, vcpus=2, local_gb=40, flavorid=3),
    'm1.large': dict(memory_mb=8192, vcpus=4, local_gb=80, flavorid=4),
    'm1.xlarge': dict(memory_mb=16384, vcpus=8, local_gb=160, flavorid=5)}
    try:
        i = instance_types.insert()
        for name, values in INSTANCE_TYPES.iteritems():
            # FIXME(kpepple) should we be seeding created_at / updated_at ?
            # now = datetime.datatime.utcnow()
            i.execute({'name': name, 'memory_mb': values["memory_mb"],
                        'vcpus': values["vcpus"], 'deleted': False,
                        'local_gb': values["local_gb"],
                        'flavorid': values["flavorid"]})
    except Exception:
        logging.info(repr(instance_types))
        logging.exception('Exception while seeding instance_types table')
        raise


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    for table in (instance_types):
        table.drop()
