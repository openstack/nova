# Copyright 2011 OpenStack LLC
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

from sqlalchemy import Column, Integer, MetaData, String, Table


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    fixed_ips = Table('fixed_ips', meta, autoload=True)

    #
    # New Columns
    #
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
    # Add columns to existing tables
    fixed_ips.create_column(fixed_ips_addressV6)
    fixed_ips.create_column(fixed_ips_netmaskV6)
    fixed_ips.create_column(fixed_ips_gatewayV6)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    fixed_ips = Table('fixed_ips', meta, autoload=True)

    fixed_ips.drop_column('addressV6')
    fixed_ips.drop_column('netmaskV6')
    fixed_ips.drop_column('gatewayV6')
