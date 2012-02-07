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


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    networks = Table('networks', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)

    # Alter column name
    networks.c.ra_server.alter(name='gateway_v6')
    # Add new column to existing table
    networks_netmask_v6 = Column(
            'netmask_v6',
            String(length=255, convert_unicode=False, assert_unicode=None,
                   unicode_error=None, _warn_on_bytestring=False))
    networks.create_column(networks_netmask_v6)

    # drop existing columns from table
    fixed_ips.c.addressV6.drop()
    fixed_ips.c.netmaskV6.drop()
    fixed_ips.c.gatewayV6.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    networks = Table('networks', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)

    networks.c.gateway_v6.alter(name='ra_server')
    networks.drop_column('netmask_v6')

    fixed_ips_addressV6 = Column(
        "addressV6",
        String(
            length=255,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False))

    fixed_ips_netmaskV6 = Column(
        "netmaskV6",
        String(
            length=3,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False))

    fixed_ips_gatewayV6 = Column(
        "gatewayV6",
        String(
            length=255,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False))

    for column in (fixed_ips_addressV6,
                   fixed_ips_netmaskV6,
                   fixed_ips_gatewayV6):
        fixed_ips.create_column(column)
