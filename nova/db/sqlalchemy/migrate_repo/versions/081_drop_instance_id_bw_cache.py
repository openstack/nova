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
import json

from sqlalchemy import Column, Table, MetaData, Integer, Boolean, String
from sqlalchemy import DateTime, BigInteger


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

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

    bw_usage_cache.drop_column('instance_id')


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_info_caches = Table('instance_info_caches', meta, autoload=True)
    bw_usage_cache = Table('bw_usage_cache', meta, autoload=True)

    instance_id = Column('instance_id', Integer)
    bw_usage_cache.create_column(instance_id)

    cache = {}
    for row in migrate_engine.execute(instance_info_caches.select()):
        instance_id = row['instance']['id']
        if not row['network_info']:
            continue

        nw_info = json.loads(row['network_info'])
        for vif in nw_info:
            cache[vif['address']] = instance_id

    for row in migrate_engine.execute(bw_usage_cache.select()):
        instance_id = cache[row['mac']]
        migrate_engine.execute(bw_usage_cache.update()\
                    .where(bw_usage_cache.c.id == row['id'])\
                    .values(instance_id=instance_id))
