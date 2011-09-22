# Copyright 2011 OpenStack LLC.
# Copyright 2011 Isaku Yamahata
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

from sqlalchemy import MetaData, Table, Column
from sqlalchemy import DateTime, Boolean, Integer, String
from sqlalchemy import ForeignKey
from nova import log as logging

meta = MetaData()

# Just for the ForeignKey and column creation to succeed, these are not the
# actual definitions of instances or services.
instances = Table('instances', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )

volumes = Table('volumes', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )

snapshots = Table('snapshots', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )


block_device_mapping = Table('block_device_mapping', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, autoincrement=True),
        Column('instance_id',
               Integer(),
               ForeignKey('instances.id'),
               nullable=False),
        Column('device_name',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False),
               nullable=False),
        Column('delete_on_termination',
               Boolean(create_constraint=True, name=None),
               default=False),
        Column('virtual_name',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False),
               nullable=True),
        Column('snapshot_id',
               Integer(),
               ForeignKey('snapshots.id'),
               nullable=True),
        Column('volume_id', Integer(), ForeignKey('volumes.id'),
               nullable=True),
        Column('volume_size', Integer(), nullable=True),
        Column('no_device',
               Boolean(create_constraint=True, name=None),
               nullable=True),
        )


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    try:
        block_device_mapping.create()
    except Exception:
        logging.info(repr(block_device_mapping))
        logging.exception('Exception while creating table')
        meta.drop_all(tables=[block_device_mapping])
        raise


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    block_device_mapping.drop()
