# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from sqlalchemy import Index, MetaData, Table
from sqlalchemy.exc import IntegrityError, OperationalError


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # Based on bw_usage_get_by_uuids
    # from: nova/db/sqlalchemy/api.py
    t = Table('bw_usage_cache', meta, autoload=True)
    i = Index('bw_usage_cache_uuid_start_period_idx',
              t.c.uuid, t.c.start_period)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('bw_usage_cache', meta, autoload=True)
    i = Index('bw_usage_cache_uuid_start_period_idx',
              t.c.uuid, t.c.start_period)
    if migrate_engine.url.get_dialect().name.startswith('sqlite'):
        try:
            i.drop(migrate_engine)
        except OperationalError:
            # Sqlite is very broken for any kind of table modification.
            # adding columns creates a new table, then copies the data,
            # and looses the indexes.
            # Thus later migrations that add columns will cause the
            # earlier migration's downgrade unittests to fail on
            # dropping indexes.
            # Honestly testing migrations on sqlite is not really a very
            # valid test (because of above facts), but that is for
            # another day. (mdragon)
            pass
    else:
        i.drop(migrate_engine)
