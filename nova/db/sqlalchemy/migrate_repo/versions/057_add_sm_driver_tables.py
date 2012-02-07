# Copyright (c) 2011 Citrix Systems, Inc.
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String
from sqlalchemy import Table

from nova import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    volumes = Table('volumes', meta, autoload=True)

    #
    # New Tables
    #
    flavors = Table('sm_flavors', meta,
              Column('created_at', DateTime(timezone=False)),
              Column('updated_at', DateTime(timezone=False)),
              Column('deleted_at', DateTime(timezone=False)),
              Column('deleted', Boolean(create_constraint=True, name=None)),
              Column('id', Integer(), primary_key=True, nullable=False),
              Column('label',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None, _warn_on_bytestring=False)),
              Column('description',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None, _warn_on_bytestring=False)),
              )

    backend = Table('sm_backend_config', meta,
              Column('created_at', DateTime(timezone=False)),
              Column('updated_at', DateTime(timezone=False)),
              Column('deleted_at', DateTime(timezone=False)),
              Column('deleted', Boolean(create_constraint=True, name=None)),
              Column('id', Integer(), primary_key=True, nullable=False),
              Column('flavor_id', Integer(), ForeignKey('sm_flavors.id'),
                     nullable=False),
              Column('sr_uuid',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None, _warn_on_bytestring=False)),
              Column('sr_type',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None, _warn_on_bytestring=False)),
              Column('config_params',
                     String(length=2047,
                            convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None,
                            _warn_on_bytestring=False)),
              )

    sm_vol = Table('sm_volume', meta,
             Column('created_at', DateTime(timezone=False)),
             Column('updated_at', DateTime(timezone=False)),
             Column('deleted_at', DateTime(timezone=False)),
             Column('deleted', Boolean(create_constraint=True, name=None)),
             Column('id', Integer(), ForeignKey('volumes.id'),
                    primary_key=True, nullable=False),
             Column('backend_id', Integer(),
                    ForeignKey('sm_backend_config.id'),
                    nullable=False),
             Column('vdi_uuid',
                    String(length=255, convert_unicode=False,
                           assert_unicode=None,
                           unicode_error=None, _warn_on_bytestring=False)),
             )
    for table in (flavors, backend, sm_vol):
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    volumes = Table('volumes', meta, autoload=True)

    flavors = Table('sm_flavors', meta, autoload=True)
    backend = Table('sm_backend_config', meta, autoload=True)
    sm_vol = Table('sm_volume', meta, autoload=True)

    for table in (flavors, backend, sm_vol):
        try:
            table.drop()
        except Exception:
            LOG.info(repr(table))
