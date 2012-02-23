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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String, Table, Text
from nova import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    volumes = Table('volumes', meta, autoload=True)

    instances = Table('instances', meta, autoload=True)
    services = Table('services', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    auth_tokens = Table('auth_tokens', meta, autoload=True)

    #
    # New Tables
    #
    certificates = Table('certificates', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('user_id',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('project_id',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('file_name',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            )

    consoles = Table('consoles', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('instance_name',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('instance_id', Integer()),
            Column('password',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('port', Integer(), nullable=True),
            Column('pool_id',
                   Integer(),
                   ForeignKey('console_pools.id')),
            )

    console_pools = Table('console_pools', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('address',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('username',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('password',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('console_type',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('public_hostname',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('host',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('compute_host',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            )

    instance_actions = Table('instance_actions', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('instance_id',
                   Integer(),
                   ForeignKey('instances.id')),
            Column('action',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('error',
                   Text(length=None, convert_unicode=False,
                        assert_unicode=None,
                        unicode_error=None, _warn_on_bytestring=False)),
            )

    iscsi_targets = Table('iscsi_targets', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('target_num', Integer()),
            Column('host',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('volume_id',
                   Integer(),
                   ForeignKey('volumes.id'),
                   nullable=True),
            )

    tables = [certificates, console_pools, consoles, instance_actions,
              iscsi_targets]
    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception('Exception while creating table')
            meta.drop_all(tables=tables)
            raise

    auth_tokens.c.user_id.alter(type=String(length=255,
                                            convert_unicode=False,
                                            assert_unicode=None,
                                            unicode_error=None,
                                            _warn_on_bytestring=False))

    #
    # New Columns
    #
    instances_availability_zone = Column(
            'availability_zone',
            String(length=255, convert_unicode=False, assert_unicode=None,
                   unicode_error=None, _warn_on_bytestring=False))

    instances_locked = Column('locked',
                    Boolean(create_constraint=True, name=None))

    networks_cidr_v6 = Column(
            'cidr_v6',
            String(length=255, convert_unicode=False, assert_unicode=None,
                   unicode_error=None, _warn_on_bytestring=False))

    networks_ra_server = Column(
            'ra_server',
            String(length=255, convert_unicode=False, assert_unicode=None,
                   unicode_error=None, _warn_on_bytestring=False))

    services_availability_zone = Column(
            'availability_zone',
            String(length=255, convert_unicode=False, assert_unicode=None,
                   unicode_error=None, _warn_on_bytestring=False))

    instances.create_column(instances_availability_zone)
    instances.create_column(instances_locked)
    networks.create_column(networks_cidr_v6)
    networks.create_column(networks_ra_server)
    services.create_column(services_availability_zone)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    volumes = Table('volumes', meta, autoload=True)

    instances = Table('instances', meta, autoload=True)
    services = Table('services', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    auth_tokens = Table('auth_tokens', meta, autoload=True)

    certificates = Table('certificates', meta, autoload=True)
    consoles = Table('consoles', meta, autoload=True)
    console_pools = Table('console_pools', meta, autoload=True)
    instance_actions = Table('instance_actions', meta, autoload=True)
    iscsi_targets = Table('iscsi_targets', meta, autoload=True)

    # table order matters, don't change
    tables = [certificates, consoles, console_pools, instance_actions,
              iscsi_targets]
    for table in tables:
        table.drop()

    auth_tokens.c.user_id.alter(type=Integer())

    instances.drop_column('availability_zone')
    instances.drop_column('locked')
    networks.drop_column('cidr_v6')
    networks.drop_column('ra_server')
    services.drop_column('availability_zone')
