# Copyright (c) 2011 NTT.
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy import MetaData, String, Table

meta = MetaData()

# Table stub-definitions
# Just for the ForeignKey and column creation to succeed, these are not the
# actual definitions of instances or services.
#
instances = Table('instances', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )

#
# Tables to alter
#
networks = Table('networks', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('injected', Boolean(create_constraint=True, name=None)),
        Column('cidr',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('netmask',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('bridge',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('gateway',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('broadcast',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('dns',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('vlan', Integer()),
        Column('vpn_public_address',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('vpn_public_port', Integer()),
        Column('vpn_private_address',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('dhcp_start',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('project_id',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('host',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('cidr_v6',
        String(length=255, convert_unicode=False, assert_unicode=None,
               unicode_error=None, _warn_on_bytestring=False)),
        Column('ra_server', String(length=255,
                                   convert_unicode=False,
                                   assert_unicode=None,
                                   unicode_error=None,
                                   _warn_on_bytestring=False)),
        Column(
        'label',
        String(length=255, convert_unicode=False, assert_unicode=None,
               unicode_error=None, _warn_on_bytestring=False)))

fixed_ips = Table('fixed_ips', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('address',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('network_id',
               Integer(),
               ForeignKey('networks.id'),
               nullable=True),
        Column('instance_id',
               Integer(),
               ForeignKey('instances.id'),
               nullable=True),
        Column('allocated', Boolean(create_constraint=True, name=None)),
        Column('leased', Boolean(create_constraint=True, name=None)),
        Column('reserved', Boolean(create_constraint=True, name=None)),
        Column("addressV6", String(length=255,
                                   convert_unicode=False,
                                   assert_unicode=None,
                                   unicode_error=None,
                                   _warn_on_bytestring=False)),
        Column("netmaskV6", String(length=3,
                                   convert_unicode=False,
                                   assert_unicode=None,
                                   unicode_error=None,
                                   _warn_on_bytestring=False)),
        Column("gatewayV6", String(length=255,
                                   convert_unicode=False,
                                   assert_unicode=None,
                                   unicode_error=None,
                                   _warn_on_bytestring=False)),
        )
#
# New Tables
#
# None

#
# Columns to add to existing tables
#
networks_netmask_v6 = Column(
        'netmask_v6',
        String(length=255, convert_unicode=False, assert_unicode=None,
               unicode_error=None, _warn_on_bytestring=False))


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine

    # Alter column name
    networks.c.ra_server.alter(name='gateway_v6')
    # Add new column to existing table
    networks.create_column(networks_netmask_v6)

    # drop existing columns from table
    fixed_ips.c.addressV6.drop()
    fixed_ips.c.netmaskV6.drop()
    fixed_ips.c.gatewayV6.drop()
