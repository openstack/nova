# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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

from sqlalchemy import Column, Table, MetaData, Boolean, String

meta = MetaData()

fixed_ips_host = Column('host', String(255))

networks_multi_host = Column('multi_host', Boolean, default=False)


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    fixed_ips = Table('fixed_ips', meta, autoload=True)
    fixed_ips.create_column(fixed_ips_host)

    networks = Table('networks', meta, autoload=True)
    networks.create_column(networks_multi_host)


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    fixed_ips = Table('fixed_ips', meta, autoload=True)
    fixed_ips.drop_column(fixed_ips_host)

    networks = Table('networks', meta, autoload=True)
    networks.drop_column(networks_multi_host)
