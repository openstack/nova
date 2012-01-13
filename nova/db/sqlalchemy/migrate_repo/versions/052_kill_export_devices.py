# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 University of Southern California
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy import MetaData, Table
from nova import log as logging

meta = MetaData()

# Table definition
volumes = Table('volumes', meta,
        Column('id', Integer(), primary_key=True, nullable=False)
)

export_devices = Table('export_devices', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('shelf_id', Integer()),
        Column('blade_id', Integer()),
        Column('volume_id',
               Integer(),
               ForeignKey('volumes.id'),
               nullable=True),
        )


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    try:
        export_devices.create()
    except Exception:
        logging.info(repr(export_devices))
        logging.exception('Exception while creating table')
        raise


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    export_devices.drop()
