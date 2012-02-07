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

from sqlalchemy import *
from migrate import *

from nova import utils


meta = MetaData()


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    bw_usage_cache = Table('bw_usage_cache', meta,
                           Column('id', Integer, primary_key=True),
                           Column('network_label', String(255)),
                           Column('instance_id', Integer, nullable=False),
                           Column('start_period', DateTime, nullable=False),
                           Column('last_refreshed', DateTime),
                           Column('bw_in', BigInteger),
                           Column('bw_out', BigInteger),
                           Column('created_at', DateTime(timezone=False),
                                  default=utils.utcnow()),
                           Column('updated_at', DateTime(timezone=False),
                                  onupdate=utils.utcnow()),
                           Column('deleted_at', DateTime(timezone=False)),
                           Column('deleted', Boolean(create_constraint=True,
                                                     name=None)))

    vifs = Table('virtual_interfaces', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    mac_column = Column('mac', String(255))

    try:
        bw_usage_cache.create_column(mac_column)
    except Exception:
        # NOTE(jkoelker) passing here since this migration was broken
        #                at one point
        pass

    bw_usage_cache.update()\
        .values(mac=select([vifs.c.address])\
            .where(and_(
                    networks.c.label == bw_usage_cache.c.network_label,
                    networks.c.id == vifs.c.network_id,
                    bw_usage_cache.c.instance_id == vifs.c.instance_id))\
            .as_scalar()).execute()

    bw_usage_cache.c.network_label.drop()


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    bw_usage_cache = Table('bw_usage_cache', meta,
                           Column('id', Integer, primary_key=True),
                           Column('mac', String(255)),
                           Column('instance_id', Integer, nullable=False),
                           Column('start_period', DateTime, nullable=False),
                           Column('last_refreshed', DateTime),
                           Column('bw_in', BigInteger),
                           Column('bw_out', BigInteger),
                           Column('created_at', DateTime(timezone=False),
                                  default=utils.utcnow()),
                           Column('updated_at', DateTime(timezone=False),
                                  onupdate=utils.utcnow()),
                           Column('deleted_at', DateTime(timezone=False)),
                           Column('deleted', Boolean(create_constraint=True,
                                                     name=None)))

    vifs = Table('virtual_interfaces', meta, autoload=True)
    network = Table('networks', meta, autoload=True)
    network_label_column = Column('network_label', String(255))

    bw_usage_cache.create_column(network_label_column)

    try:
        bw_usage_cache.update()\
            .values(network_label=select([network.c.label])\
                .where(and_(
                    network.c.id == vifs.c.network_id,
                   vifs.c.address == bw_usage_cache.c.mac,
                   bw_usage_cache.c.instance_id == vifs.c.instance_id))\
                .as_scalar()).execute()
    except Exception:
        # NOTE(jkoelker) passing here since this migration was broken
        #                at one point
        pass

    bw_usage_cache.c.mac.drop()
