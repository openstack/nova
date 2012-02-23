# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import and_, select
from sqlalchemy import BigInteger, Boolean, Column, DateTime
from sqlalchemy import Integer, MetaData, String
from sqlalchemy import Table

from nova import utils


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    vifs = Table('virtual_interfaces', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)

    bw_usage_cache = Table('bw_usage_cache', meta,
                Column('created_at', DateTime(timezone=False)),
                Column('updated_at', DateTime(timezone=False)),
                Column('deleted_at', DateTime(timezone=False)),
                Column('deleted', Boolean(create_constraint=True, name=None)),
                Column('id', Integer(), primary_key=True, nullable=False),
                Column('instance_id', Integer(), nullable=False),
                Column('network_label',
                       String(length=255, convert_unicode=False,
                              assert_unicode=None,
                              unicode_error=None, _warn_on_bytestring=False)),
                Column('start_period', DateTime(timezone=False),
                       nullable=False),
                Column('last_refreshed', DateTime(timezone=False)),
                Column('bw_in', BigInteger()),
                Column('bw_out', BigInteger()),
                useexisting=True)
    mac_column = Column('mac', String(255))
    bw_usage_cache.create_column(mac_column)

    bw_usage_cache.update()\
        .values(mac=select([vifs.c.address])\
            .where(and_(
                    networks.c.label == bw_usage_cache.c.network_label,
                    networks.c.id == vifs.c.network_id,
                    bw_usage_cache.c.instance_id == vifs.c.instance_id))\
            .as_scalar()).execute()

    bw_usage_cache.c.network_label.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    vifs = Table('virtual_interfaces', meta, autoload=True)
    network = Table('networks', meta, autoload=True)

    bw_usage_cache = Table('bw_usage_cache', meta,
                Column('created_at', DateTime(timezone=False)),
                Column('updated_at', DateTime(timezone=False)),
                Column('deleted_at', DateTime(timezone=False)),
                Column('deleted', Boolean(create_constraint=True, name=None)),
                Column('id', Integer(), primary_key=True, nullable=False),
                Column('instance_id', Integer(), nullable=False),
                Column('mac', String(255)),
                Column('start_period', DateTime(timezone=False),
                       nullable=False),
                Column('last_refreshed', DateTime(timezone=False)),
                Column('bw_in', BigInteger()),
                Column('bw_out', BigInteger()),
                useexisting=True)

    network_label_column = Column('network_label', String(255))
    bw_usage_cache.create_column(network_label_column)

    bw_usage_cache.update()\
        .values(network_label=select([network.c.label])\
            .where(and_(
                network.c.id == vifs.c.network_id,
               vifs.c.address == bw_usage_cache.c.mac,
               bw_usage_cache.c.instance_id == vifs.c.instance_id))\
            .as_scalar()).execute()

    bw_usage_cache.c.mac.drop()
